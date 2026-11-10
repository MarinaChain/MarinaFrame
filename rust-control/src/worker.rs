//! Linux process supervision. Resource boundaries are not a hostile-code sandbox.
use crate::types::{Config, Pending};
use crate::util::Result;
use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

pub static STOP: AtomicBool = AtomicBool::new(false);
extern "C" fn stop_signal(_: libc::c_int) {
    STOP.store(true, Ordering::SeqCst);
}
pub fn install_signals() {
    unsafe {
        libc::signal(libc::SIGINT, stop_signal as *const () as libc::sighandler_t);
        libc::signal(
            libc::SIGTERM,
            stop_signal as *const () as libc::sighandler_t,
        );
    }
}
pub fn cancelled(root: &Path) -> bool {
    STOP.load(Ordering::SeqCst) || root.join("cancel.request").exists()
}

/// Five minutes permits slow native calls on loaded laptops. Lack of progress
/// asks the person what to do; it does not kill the worker or adopt its files.
pub const NO_PROGRESS_SECONDS: u64 = 300;
/// CAD steps normally report hundreds of units. Limit invented alternating
/// stages to 10,000 advances per worker step; explicit waiting does not refill it.
const MAX_PROGRESS_ADVANCES_PER_STEP: u64 = 10_000;
const MAX_PROGRESS_BYTES: u64 = 2048;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct WorkerProgress {
    pub request_id: String,
    pub stage: String,
    pub part: u64,
    pub total: u64,
    pub unit: String,
    pub counter: u64,
    pub timestamp_ms: u64,
}

pub fn progress_path(root: &Path, request_id: &str) -> std::path::PathBuf {
    root.join("worker-logs")
        .join(format!("{request_id}.progress.json"))
}

pub fn read_progress(root: &Path, request_id: &str) -> Option<WorkerProgress> {
    if request_id.is_empty()
        || !request_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
    {
        return None;
    }
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(progress_path(root, request_id))
        .ok()?;
    let metadata = file.metadata().ok()?;
    if !metadata.is_file() || metadata.len() > MAX_PROGRESS_BYTES {
        return None;
    }
    let mut bytes = Vec::new();
    file.take(MAX_PROGRESS_BYTES + 1)
        .read_to_end(&mut bytes)
        .ok()?;
    if bytes.len() as u64 > MAX_PROGRESS_BYTES {
        return None;
    }
    let value: WorkerProgress = serde_json::from_slice(&bytes).ok()?;
    (value.request_id == request_id
        && !value.stage.is_empty()
        && value.stage.len() <= 120
        && !value.stage.chars().any(char::is_control)
        && value.part <= value.total
        && value.total <= 100_000
        && ["part", "section", "format"].contains(&value.unit.as_str()))
    .then_some(value)
}

/// Uses elapsed monotonic time supplied by the supervisor (a fake clock in tests).
struct ProgressWatchdog {
    counter: u64,
    last_pair: Option<(String, u64)>,
    last_progress: Duration,
}
impl ProgressWatchdog {
    fn new(now: Duration) -> Self {
        Self {
            counter: 0,
            last_pair: None,
            last_progress: now,
        }
    }
    fn update(
        &mut self,
        now: Duration,
        progress: Option<&WorkerProgress>,
        keep_waiting: bool,
    ) -> bool {
        if let Some(progress) = progress {
            let pair = (progress.stage.clone(), progress.part);
            if self.last_pair.as_ref() != Some(&pair)
                && self.counter < MAX_PROGRESS_ADVANCES_PER_STEP
            {
                self.last_pair = Some(pair);
                self.counter += 1;
                self.last_progress = now;
            }
        }
        if keep_waiting {
            self.last_progress = now;
        }
        now.saturating_sub(self.last_progress) >= Duration::from_secs(NO_PROGRESS_SECONDS)
    }
}

/// This request takes no controller lock: the running supervisor holds that lock.
pub fn keep_waiting(root: &Path, request_id: &str) -> Result<()> {
    crate::util::atomic_json(
        &root.join("keep-waiting.request"),
        &serde_json::json!({"request_id":request_id}),
        true,
    )
}

fn take_keep_waiting(root: &Path, request_id: &str) -> bool {
    let path = root.join("keep-waiting.request");
    let requested = crate::util::read_bounded(&path, 1024)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).ok())
        .is_some_and(|value| value["request_id"] == request_id);
    requested && std::fs::remove_file(path).is_ok()
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessState {
    ProtocolWriteFailed,
    Exited,
    StartFailed,
    Cancelled,
    TimedOut,
    OutputLimit,
    QueueTimeout,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ProcessOutcome {
    pub state: ProcessState,
    pub exit_code: Option<i32>,
    pub wall_seconds: f64,
    pub queue_wait_seconds: f64,
    pub spawned: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

fn timeout_message(stage: &str, elapsed: Duration) -> String {
    format!(
        "The worker reached the configured safety time limit at {stage} after {:.1} min.",
        elapsed.as_secs_f64() / 60.0
    )
}

struct Admission {
    _file: File,
}
pub struct DomainGuard {
    _file: File,
}
pub fn domain_guard(root: &Path) -> Result<DomainGuard> {
    if std::fs::symlink_metadata(root.join("domain"))
        .map_err(|_| "domain_missing")?
        .file_type()
        .is_symlink()
    {
        return Err("domain_symlink".into());
    }
    let f = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(root.join("domain/lock"))
        .map_err(|_| "domain_lock_missing")?;
    if !f.metadata().map_err(|_| "domain_lock_metadata")?.is_file() {
        return Err("domain_lock_not_regular".into());
    }
    if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err("domain_operation_in_progress".into());
    }
    Ok(DomainGuard { _file: f })
}
/// Native (CAD/tracing) work that may run at once for this user, across all tasks.
/// This is a capacity limit, not a correctness lock: each task has its own folder and
/// domain lock. Each native worker uses about one core and up to its memory limit, so
/// the default is half the cores (at least 1, at most MAX_NATIVE_SLOTS); set
/// MARINAFRAME_NATIVE_SLOTS to override. Each slot is one lock file; slot 0 keeps the
/// original name so scripts that take the lock (for example scorers) exclude one slot.
const MAX_NATIVE_SLOTS: usize = 8;

fn default_native_slots() -> usize {
    let cores = std::thread::available_parallelism().map_or(2, |n| n.get());
    (cores / 2).clamp(1, MAX_NATIVE_SLOTS)
}
/// How long a native step waits for a free slot before it gives up (seconds). Many
/// concurrent tasks queue here; 120 s ended runs needlessly under load.
pub const ADMISSION_DEADLINE_SECONDS: u64 = 1800;

fn native_slots() -> usize {
    std::env::var("MARINAFRAME_NATIVE_SLOTS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|slots| (1..=MAX_NATIVE_SLOTS).contains(slots))
        .unwrap_or_else(default_native_slots)
}

fn open_slot(dir: &Path, slot: usize) -> Result<std::fs::File> {
    let uid = unsafe { libc::geteuid() };
    let name = if slot == 0 {
        format!("marinaframe-native-admission-{uid}.lock")
    } else {
        format!("marinaframe-native-admission-{uid}-{slot}.lock")
    };
    let f = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(dir.join(name))
        .map_err(|_| "admission_open")?;
    if !f.metadata().map_err(|_| "admission_metadata")?.is_file() {
        return Err("admission_not_regular".into());
    }
    Ok(f)
}

fn admission(root: &Path, deadline: u64) -> Result<Option<Admission>> {
    admission_in(&std::env::temp_dir(), native_slots(), root, deadline)
}

fn admission_in(
    dir: &Path,
    slot_count: usize,
    root: &Path,
    deadline: u64,
) -> Result<Option<Admission>> {
    let slots = (0..slot_count)
        .map(|slot| open_slot(dir, slot))
        .collect::<Result<Vec<_>>>()?;
    let started = Instant::now();
    loop {
        for f in &slots {
            if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
                let file = f.try_clone().map_err(|_| "admission_open")?;
                return Ok(Some(Admission { _file: file }));
            }
        }
        if cancelled(root) || started.elapsed().as_secs() >= deadline {
            return Ok(None);
        }
        std::thread::sleep(Duration::from_millis(25));
    }
}

// Leave an exited leader unreaped until its process group has been cleaned up.
// Reaping first would permit PID/group-ID reuse before the final group signal.
fn exited_without_reaping(pid: i32) -> Result<bool> {
    let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
    let result = unsafe {
        libc::waitid(
            libc::P_PID,
            pid as libc::id_t,
            &mut info,
            libc::WEXITED | libc::WNOHANG | libc::WNOWAIT,
        )
    };
    if result != 0 {
        if std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted {
            return Ok(false);
        }
        return Err("worker_wait".into());
    }
    Ok(unsafe { info.si_pid() } == pid)
}

pub fn run(
    root: &Path,
    config: &Config,
    pending: &Pending,
    request: &[u8],
    source_spec: &Path,
) -> Result<ProcessOutcome> {
    run_with_progress(root, config, pending, request, source_spec, |_, _| Ok(()))
}

pub fn run_with_progress(
    root: &Path,
    config: &Config,
    pending: &Pending,
    request: &[u8],
    source_spec: &Path,
    mut on_stall_change: impl FnMut(bool, Option<&WorkerProgress>) -> Result<()>,
) -> Result<ProcessOutcome> {
    let is_provider = pending.kind == "provider";
    let queued = Instant::now();
    let _admission = if is_provider {
        None
    } else {
        let slot = admission(root, ADMISSION_DEADLINE_SECONDS)?;
        if slot.is_none() {
            return Ok(ProcessOutcome {
                state: if cancelled(root) {
                    ProcessState::Cancelled
                } else {
                    ProcessState::QueueTimeout
                },
                exit_code: None,
                wall_seconds: 0.,
                queue_wait_seconds: queued.elapsed().as_secs_f64(),
                spawned: false,
                message: None,
            });
        }
        slot
    };
    let queue_wait = queued.elapsed().as_secs_f64();
    if cancelled(root) {
        return Ok(ProcessOutcome {
            state: ProcessState::Cancelled,
            exit_code: None,
            wall_seconds: 0.,
            queue_wait_seconds: queue_wait,
            spawned: false,
            message: None,
        });
    }
    let response = root.join(&pending.response_path);
    let mut command = if is_provider {
        let mut c = Command::new(std::env::current_exe().map_err(|_| "binary_path")?);
        c.arg("provider-worker")
            .arg("--response")
            .arg(&response)
            .arg("--timeout")
            .arg(config.limits.request_wall_seconds.to_string());
        c
    } else {
        let mut c = Command::new(&config.worker_python);
        c.args(["-m", "vessel_reconstruction.rust_worker", "--task-root"])
            .arg(root)
            .arg("--source-spec")
            .arg(source_spec)
            .arg("--response")
            .arg(&response);
        c.env_clear();
        // MARINAFRAME_HULL_FAIRING is a hull build setting (Python fairing.SETTING), not a secret.
        for key in ["PATH", "LANG", "LC_ALL", "TZ", "MARINAFRAME_HULL_FAIRING"] {
            if let Ok(v) = std::env::var(key) {
                c.env(key, v);
            }
        }
        c.env("PYTHONDONTWRITEBYTECODE", "1")
            .env(
                "MARINAFRAME_PROGRESS_PATH",
                progress_path(root, &pending.id),
            )
            .env("MARINAFRAME_PROGRESS_REQUEST", &pending.id)
            .env("PYTHONUNBUFFERED", "1")
            .env("OPENBLAS_NUM_THREADS", "1")
            .env("OMP_NUM_THREADS", "1")
            .env("OMP_THREAD_LIMIT", "1")
            .env("MKL_NUM_THREADS", "1");
        if let Some(path) = &config.worker_source {
            c.env("PYTHONPATH", path);
        }
        c
    };
    let log_parent = root.join("worker-logs");
    std::fs::create_dir_all(&log_parent).map_err(|_| "worker_logs_create")?;
    let stdout_path = log_parent.join(format!("{}.stdout", pending.id));
    let stderr_path = log_parent.join(format!("{}.stderr", pending.id));
    let stdout = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&stdout_path)
        .map_err(|_| "worker_log_exists")?;
    let stderr = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&stderr_path)
        .map_err(|_| "worker_log_exists")?;
    command
        .current_dir(root)
        .stdin(Stdio::piped())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    let memory = if is_provider {
        1024 * 1024 * 1024
    } else {
        config.limits.worker_memory_bytes
    };
    let cpu = if is_provider {
        30
    } else {
        config.limits.worker_cpu_seconds
    };
    let parent = unsafe { libc::getpid() };
    unsafe {
        command.pre_exec(move || {
            if libc::setsid() < 0 {
                return Err(std::io::Error::last_os_error());
            }
            // Linux stops the worker when the controller dies. macOS has no
            // parent-death signal: an orphaned worker there is bounded only by
            // its RLIMIT_CPU limit (see docs/CONTINUATION_STATUS.md).
            #[cfg(target_os = "linux")]
            if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) < 0 {
                return Err(std::io::Error::last_os_error());
            }
            if libc::getppid() != parent {
                return Err(std::io::Error::other("parent changed"));
            }
            // On macOS RLIMIT_AS is an alias of RLIMIT_RSS: the kernel rejects
            // lowering it and does not enforce RSS limits. The worker memory
            // limit is therefore Linux-only (see docs/CONTINUATION_STATUS.md).
            #[cfg(target_os = "linux")]
            let memory_limit = Some((libc::RLIMIT_AS, memory, memory));
            #[cfg(not(target_os = "linux"))]
            let memory_limit = {
                let _ = memory;
                None
            };
            for (which, soft, hard) in memory_limit.into_iter().chain([
                (libc::RLIMIT_CPU, cpu, cpu + 1),
                (libc::RLIMIT_FSIZE, 256 * 1024 * 1024, 256 * 1024 * 1024),
                (libc::RLIMIT_NOFILE, 128, 128),
            ]) {
                let lim = libc::rlimit {
                    rlim_cur: soft as libc::rlim_t,
                    rlim_max: hard as libc::rlim_t,
                };
                if libc::setrlimit(which, &lim) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
            }
            Ok(())
        });
    }
    let started = Instant::now();
    let mut child = match command.spawn() {
        Ok(c) => c,
        Err(_) => {
            return Ok(ProcessOutcome {
                state: ProcessState::StartFailed,
                exit_code: None,
                wall_seconds: started.elapsed().as_secs_f64(),
                queue_wait_seconds: queue_wait,
                spawned: false,
                message: None,
            })
        }
    };
    let pid = child.id() as i32;
    let mut stdin = child.stdin.take();
    let mut offset = 0usize;
    let mut pipe_failed = stdin.is_none();
    if let Some(pipe) = &stdin {
        let flags = unsafe { libc::fcntl(pipe.as_raw_fd(), libc::F_GETFL) };
        if flags < 0
            || unsafe { libc::fcntl(pipe.as_raw_fd(), libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0
        {
            pipe_failed = true;
        }
    }
    let timeout = if is_provider {
        config.limits.request_wall_seconds + 5
    } else {
        config.limits.worker_wall_seconds
    };
    let mut watchdog = ProgressWatchdog::new(Duration::ZERO);
    let mut stalled = false;
    let mut next_progress_poll = Duration::ZERO;
    loop {
        if let Some(pipe) = stdin.as_mut() {
            if offset < request.len() && !pipe_failed {
                match pipe.write(&request[offset..request.len().min(offset + 65_536)]) {
                    Ok(0) => pipe_failed = true,
                    Ok(n) => offset += n,
                    Err(e)
                        if matches!(
                            e.kind(),
                            std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                        ) => {}
                    Err(_) => pipe_failed = true,
                }
            }
            if offset == request.len() || pipe_failed {
                stdin.take();
            }
        }
        let exited = match exited_without_reaping(pid) {
            Ok(exited) => exited,
            Err(error) => {
                unsafe { libc::kill(-pid, libc::SIGKILL) };
                let _ = child.wait();
                return Err(error);
            }
        };
        if exited {
            // A worker's terminal receipt does not authorize live descendants.
            // The unreaped leader still pins the group identity here.
            unsafe { libc::kill(-pid, libc::SIGKILL) };
            let status = child.wait().map_err(|_| "worker_wait")?;
            let bytes = std::fs::metadata(&stdout_path)
                .map(|m| m.len())
                .unwrap_or(0)
                + std::fs::metadata(&stderr_path)
                    .map(|m| m.len())
                    .unwrap_or(0);
            return Ok(ProcessOutcome {
                state: if bytes > 1024 * 1024 {
                    ProcessState::OutputLimit
                } else {
                    ProcessState::Exited
                },
                exit_code: status.code(),
                wall_seconds: started.elapsed().as_secs_f64(),
                queue_wait_seconds: queue_wait,
                spawned: true,
                message: None,
            });
        }
        let output = std::fs::metadata(&stdout_path)
            .map(|m| m.len())
            .unwrap_or(0)
            + std::fs::metadata(&stderr_path)
                .map(|m| m.len())
                .unwrap_or(0);
        let elapsed = started.elapsed();
        if !is_provider && elapsed >= next_progress_poll {
            next_progress_poll = elapsed + Duration::from_millis(250);
            let progress = read_progress(root, &pending.id);
            let waiting = take_keep_waiting(root, &pending.id);
            let next_stalled = watchdog.update(elapsed, progress.as_ref(), waiting);
            if next_stalled != stalled {
                if let Err(error) = on_stall_change(next_stalled, progress.as_ref()) {
                    unsafe {
                        libc::kill(-pid, libc::SIGKILL);
                    }
                    let _ = child.wait();
                    return Err(error);
                }
                stalled = next_stalled;
            }
        }
        let reason = if cancelled(root) {
            Some(ProcessState::Cancelled)
        } else if pipe_failed {
            Some(ProcessState::ProtocolWriteFailed)
        } else if timeout > 0 && elapsed.as_secs() >= timeout {
            Some(ProcessState::TimedOut)
        } else if output > 1024 * 1024 {
            Some(ProcessState::OutputLimit)
        } else {
            None
        };
        if let Some(state) = reason {
            unsafe {
                libc::kill(-pid, libc::SIGTERM);
            }
            let grace = Instant::now();
            while grace.elapsed() < Duration::from_secs(2) {
                if exited_without_reaping(pid).unwrap_or(false) {
                    break;
                }
                std::thread::sleep(Duration::from_millis(20));
            }
            // The bridge's handler cancels separately supervised native groups.
            // Native workers also retain parent-death controls from the engine.
            unsafe {
                libc::kill(-pid, libc::SIGKILL);
            }
            let _ = child.wait();
            return Ok(ProcessOutcome {
                message: if matches!(state, ProcessState::TimedOut) {
                    let stage = watchdog
                        .last_pair
                        .as_ref()
                        .map_or(pending.operation.as_str(), |(stage, _)| stage.as_str());
                    Some(timeout_message(stage, elapsed))
                } else if matches!(state, ProcessState::Cancelled) && stalled {
                    let stage = watchdog
                        .last_pair
                        .as_ref()
                        .map_or(pending.operation.as_str(), |(stage, _)| stage.as_str());
                    Some(format!(
                        "The worker was stopped at {stage} after {:.1} min without progress.",
                        elapsed.saturating_sub(watchdog.last_progress).as_secs_f64() / 60.0
                    ))
                } else {
                    None
                },
                state,
                exit_code: None,
                wall_seconds: started.elapsed().as_secs_f64(),
                queue_wait_seconds: queue_wait,
                spawned: true,
            });
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safety_limit_message_names_stage_and_minutes() {
        let message = timeout_message("Making the mesh", Duration::from_secs(330));
        assert!(message.contains("Making the mesh"));
        assert!(message.contains("5.5 min"));
        assert!(!message.contains("atomic publication"));
    }

    fn progress_record(part: u64, counter: u64) -> WorkerProgress {
        WorkerProgress {
            request_id: "worker-test".into(),
            stage: "Building the hull".into(),
            part,
            total: 100_000,
            unit: "section".into(),
            counter,
            timestamp_ms: 1,
        }
    }

    #[test]
    fn watchdog_ignores_child_counter_changes_and_limits_accepted_advances() {
        let mut watch = ProgressWatchdog::new(Duration::ZERO);
        assert!(!watch.update(Duration::ZERO, Some(&progress_record(1, 10)), false));
        assert!(watch.update(
            Duration::from_secs(300),
            Some(&progress_record(1, u64::MAX)),
            false
        ));
        assert!(!watch.update(
            Duration::from_secs(301),
            Some(&progress_record(2, 0)),
            false
        ));
        for part in 3..=MAX_PROGRESS_ADVANCES_PER_STEP {
            watch.update(
                Duration::from_secs(301),
                Some(&progress_record(part, 0)),
                false,
            );
        }
        assert_eq!(watch.counter, MAX_PROGRESS_ADVANCES_PER_STEP);
        assert!(watch.update(
            Duration::from_secs(601),
            Some(&progress_record(99_999, 0)),
            false
        ));
        // Explicit waiting can reset the stall clock, but never replenishes the budget.
        assert!(!watch.update(Duration::from_secs(602), None, true));
        assert!(watch.update(
            Duration::from_secs(902),
            Some(&progress_record(1, 0)),
            false
        ));
    }

    #[test]
    fn progress_reader_rejects_links_fifo_oversized_and_non_object_records() {
        use std::os::unix::fs::symlink;
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir(dir.path().join("worker-logs")).unwrap();
        let path = progress_path(dir.path(), "worker-test");
        let target = dir.path().join("private.json");
        let bytes = serde_json::to_vec(&progress_record(1, 1)).unwrap();
        std::fs::write(&target, &bytes).unwrap();
        symlink(&target, &path).unwrap();
        assert!(read_progress(dir.path(), "worker-test").is_none());
        std::fs::remove_file(&path).unwrap();
        let name = std::ffi::CString::new(path.as_os_str().as_encoded_bytes()).unwrap();
        assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
        let mut writer = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(&path)
            .unwrap();
        writer.write_all(&bytes).unwrap();
        let now = Instant::now();
        assert!(read_progress(dir.path(), "worker-test").is_none());
        assert!(now.elapsed() < Duration::from_secs(1));
        drop(writer);
        std::fs::remove_file(&path).unwrap();
        for bad in [vec![b' '; 2049], b"[]".to_vec()] {
            std::fs::write(&path, bad).unwrap();
            assert!(read_progress(dir.path(), "worker-test").is_none());
        }
    }

    #[test]
    fn watchdog_counts_progress_not_heartbeats_or_total_duration() {
        let mut watch = ProgressWatchdog::new(Duration::ZERO);
        assert!(!watch.update(
            Duration::from_secs(299),
            Some(&progress_record(1, 1)),
            false
        ));
        // A repeated heartbeat is not progress.
        assert!(watch.update(
            Duration::from_secs(599),
            Some(&progress_record(1, 1)),
            false
        ));
        // Keep waiting grants another no-progress window to the same worker.
        assert!(!watch.update(Duration::from_secs(600), Some(&progress_record(1, 1)), true));
        assert!(watch.update(
            Duration::from_secs(900),
            Some(&progress_record(1, 1)),
            false
        ));
        assert!(!watch.update(
            Duration::from_secs(901),
            Some(&progress_record(2, 2)),
            false
        ));
        for counter in 3..100 {
            assert!(!watch.update(
                Duration::from_secs(901 + (counter - 2) * 200),
                Some(&progress_record(counter, counter)),
                false
            ));
        }
    }

    #[test]
    fn watchdog_detects_absent_and_unchanged_work() {
        let mut watch = ProgressWatchdog::new(Duration::ZERO);
        assert!(watch.update(Duration::from_secs(300), None, false));
        assert!(!watch.update(
            Duration::from_secs(301),
            Some(&progress_record(8, 8)),
            false
        ));
        assert!(watch.update(
            Duration::from_secs(601),
            Some(&progress_record(8, 7)),
            false
        ));
    }

    #[test]
    fn absolute_worker_cap_is_disabled_by_default_and_can_be_large() {
        let mut limits = crate::types::OperationalLimits::default();
        assert_eq!(limits.worker_wall_seconds, 0);
        limits.worker_wall_seconds = 86_400;
        limits.validate().unwrap();
    }

    #[test]
    fn admission_grants_each_slot_once_and_refuses_when_all_are_taken() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("task");
        std::fs::create_dir_all(&root).unwrap();
        let first = admission_in(dir.path(), 2, &root, 0).unwrap();
        let second = admission_in(dir.path(), 2, &root, 0).unwrap();
        assert!(first.is_some() && second.is_some());
        assert!(admission_in(dir.path(), 2, &root, 0).unwrap().is_none());
        drop(first);
        assert!(admission_in(dir.path(), 2, &root, 0).unwrap().is_some());
    }
}
