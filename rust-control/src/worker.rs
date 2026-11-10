//! Linux process supervision. Resource boundaries are not a hostile-code sandbox.
use crate::types::{Config, Pending};
use crate::util::Result;
use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::process::ExitStatusExt;
use std::path::Path;
use std::process::Stdio;
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

pub use crate::supervised::WorkerProgress;
/// Lack of progress for this long asks the person what to do; it does not
/// kill the worker or adopt its files.
pub use crate::supervised::NO_PROGRESS_SECONDS;
use crate::supervised::{ProgressWatchdog, ResourceLimits, WorkerCommand, DEFAULT_STALL_PERIOD};

pub fn progress_path(root: &Path, request_id: &str) -> std::path::PathBuf {
    root.join("worker-logs")
        .join(format!("{request_id}.progress.json"))
}

pub fn read_progress(root: &Path, request_id: &str) -> Option<WorkerProgress> {
    crate::supervised::read_progress_file(&progress_path(root, request_id), request_id)
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
    ResourceLimit,
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

fn resource_limit_message(
    limit: &str,
    operation: &str,
    progress: Option<&WorkerProgress>,
) -> String {
    match progress {
        Some(value) if value.total > 0 => format!(
            "Stopped by the {limit} while {}, {} of {} {}.",
            value.stage, value.part, value.total, value.unit
        ),
        Some(value) => format!("Stopped by the {limit} while {}.", value.stage),
        None => format!("Stopped by the {limit} during {operation}."),
    }
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
        provider_command(config, &response)?
    } else {
        python_command(root, config, pending, source_spec, &response)
    };
    let log_parent = root.join("worker-logs");
    std::fs::create_dir_all(&log_parent).map_err(|_| "worker_logs_create")?;
    let stdout_path = log_parent.join(format!("{}.stdout", pending.id));
    let stderr_path = log_parent.join(format!("{}.stderr", pending.id));
    let stdout = new_log_file(&stdout_path)?;
    let stderr = new_log_file(&stderr_path)?;
    command
        .current_dir(root)
        .stdio(Stdio::piped(), Stdio::from(stdout), Stdio::from(stderr));
    let limits = if is_provider {
        PROVIDER_LIMITS
    } else {
        ResourceLimits {
            memory_bytes: config.limits.worker_memory_bytes,
            cpu_seconds: config.limits.worker_cpu_seconds,
        }
    };
    command.resource_limits(limits);
    let cpu = limits.cpu_seconds;
    let started = Instant::now();
    let mut group = match command.spawn() {
        Ok(group) => group,
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
    let mut stdin = group.child_mut().stdin.take();
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
    let mut watchdog = ProgressWatchdog::new(Duration::ZERO, DEFAULT_STALL_PERIOD);
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
        let exited = match group.leader_exited() {
            Ok(exited) => exited,
            Err(_) => {
                let _ = group.kill();
                return Err("worker_wait".into());
            }
        };
        if exited {
            // A worker's terminal receipt does not authorize live descendants:
            // `finish` kills the rest of the group before it reaps the leader.
            let status = group.finish().map_err(|_| "worker_wait")?;
            let bytes = log_bytes(&stdout_path, &stderr_path);
            let signal = status.signal();
            let limit = if bytes > MAX_LOG_BYTES {
                Some("output size limit (1 MiB)".to_string())
            } else if signal == Some(libc::SIGXCPU) {
                Some(format!("CPU limit ({cpu} seconds)"))
            } else if signal == Some(libc::SIGXFSZ) {
                Some("file size limit (256 MiB)".to_string())
            } else {
                None
            };
            let message = limit.as_deref().map(|name| {
                resource_limit_message(
                    name,
                    &pending.operation,
                    read_progress(root, &pending.id).as_ref(),
                )
            });
            return Ok(ProcessOutcome {
                state: if bytes > MAX_LOG_BYTES {
                    ProcessState::OutputLimit
                } else if limit.is_some() {
                    ProcessState::ResourceLimit
                } else {
                    ProcessState::Exited
                },
                exit_code: status.code(),
                wall_seconds: started.elapsed().as_secs_f64(),
                queue_wait_seconds: queue_wait,
                spawned: true,
                message,
            });
        }
        let output = log_bytes(&stdout_path, &stderr_path);
        let elapsed = started.elapsed();
        if !is_provider && elapsed >= next_progress_poll {
            next_progress_poll = elapsed + Duration::from_millis(250);
            let progress = read_progress(root, &pending.id);
            let waiting = take_keep_waiting(root, &pending.id);
            let next_stalled = watchdog.update(elapsed, progress.as_ref(), waiting);
            if next_stalled != stalled {
                if let Err(error) = on_stall_change(next_stalled, progress.as_ref()) {
                    let _ = group.kill();
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
        } else if output > MAX_LOG_BYTES {
            Some(ProcessState::OutputLimit)
        } else {
            None
        };
        if let Some(state) = reason {
            // The bridge's handler cancels separately supervised native groups
            // during the grace; native workers also keep parent-death controls.
            let _ = group.stop();
            return Ok(ProcessOutcome {
                message: if matches!(state, ProcessState::TimedOut) {
                    Some(timeout_message(watchdog.stage(&pending.operation), elapsed))
                } else if matches!(state, ProcessState::OutputLimit) {
                    Some(resource_limit_message(
                        "output size limit (1 MiB)",
                        &pending.operation,
                        read_progress(root, &pending.id).as_ref(),
                    ))
                } else if matches!(state, ProcessState::Cancelled) && stalled {
                    Some(crate::supervised::stall_message(
                        watchdog.stage(&pending.operation),
                        watchdog.idle_minutes(elapsed),
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

/// Worker logs larger than this stop the worker (stdout and stderr together).
const MAX_LOG_BYTES: u64 = 1024 * 1024;
/// The provider worker only sends HTTP requests: 1 GiB and 30 CPU seconds.
const PROVIDER_LIMITS: ResourceLimits = ResourceLimits {
    memory_bytes: 1024 * 1024 * 1024,
    cpu_seconds: 30,
};

/// The controller's own provider worker. It keeps the controller environment
/// because it reads the model keys itself; it runs no Python and no model code.
fn provider_command(config: &Config, response: &Path) -> Result<WorkerCommand> {
    let mut command =
        WorkerCommand::inheriting_environment(std::env::current_exe().map_err(|_| "binary_path")?);
    command
        .arg("provider-worker")
        .arg("--response")
        .arg(response)
        .arg("--timeout")
        .arg(config.limits.request_wall_seconds.to_string());
    Ok(command)
}

/// The Python CAD worker with the shared minimal environment.
fn python_command(
    root: &Path,
    config: &Config,
    pending: &Pending,
    source_spec: &Path,
    response: &Path,
) -> WorkerCommand {
    let mut command = WorkerCommand::python(
        &config.worker_python,
        config.worker_source.as_deref().map(Path::new),
    );
    command
        .args(["-m", "vessel_reconstruction.rust_worker", "--task-root"])
        .arg(root)
        .arg("--source-spec")
        .arg(source_spec)
        .arg("--response")
        .arg(response)
        // A hull build setting (Python fairing.SETTING), not a secret.
        .pass_through("MARINAFRAME_HULL_FAIRING")
        .env(
            "MARINAFRAME_PROGRESS_PATH",
            progress_path(root, &pending.id),
        )
        .env("MARINAFRAME_PROGRESS_REQUEST", &pending.id);
    command
}

fn new_log_file(path: &Path) -> Result<File> {
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|_| "worker_log_exists".into())
}

fn log_bytes(stdout: &Path, stderr: &Path) -> u64 {
    let size = |path: &Path| std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    size(stdout) + size(stderr)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resource_limit_message_names_stage_and_progress() {
        let progress = WorkerProgress {
            request_id: "test".into(),
            stage: "Making the mesh".into(),
            part: 7,
            total: 16,
            unit: "part".into(),
            counter: 1,
            timestamp_ms: 1,
        };
        let message =
            resource_limit_message("CPU limit (1 second)", "build_draft", Some(&progress));
        assert!(message.contains("CPU limit"));
        assert!(message.contains("Making the mesh"));
        assert!(message.contains("7 of 16"));
    }

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
