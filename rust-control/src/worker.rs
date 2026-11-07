//! Linux process supervision. Resource boundaries are not a hostile-code sandbox.
use crate::types::{Config, Pending};
use crate::util::Result;
use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::Write;
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
fn admission(root: &Path, deadline: u64) -> Result<Option<Admission>> {
    let path = std::env::temp_dir().join(format!("marinaframe-native-admission-{}.lock", unsafe {
        libc::geteuid()
    }));
    let f = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|_| "admission_open")?;
    if !f.metadata().map_err(|_| "admission_metadata")?.is_file() {
        return Err("admission_not_regular".into());
    }
    let started = Instant::now();
    while unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        if cancelled(root) || started.elapsed().as_secs() >= deadline {
            return Ok(None);
        }
        std::thread::sleep(Duration::from_millis(25));
    }
    Ok(Some(Admission { _file: f }))
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
    let is_provider = pending.kind == "provider";
    let queued = Instant::now();
    let _admission = if is_provider {
        None
    } else {
        let slot = admission(root, 120)?;
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
        for key in ["PATH", "LANG", "LC_ALL", "TZ"] {
            if let Ok(v) = std::env::var(key) {
                c.env(key, v);
            }
        }
        c.env("PYTHONDONTWRITEBYTECODE", "1")
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
            });
        }
        let output = std::fs::metadata(&stdout_path)
            .map(|m| m.len())
            .unwrap_or(0)
            + std::fs::metadata(&stderr_path)
                .map(|m| m.len())
                .unwrap_or(0);
        let reason = if cancelled(root) {
            Some(ProcessState::Cancelled)
        } else if pipe_failed {
            Some(ProcessState::ProtocolWriteFailed)
        } else if started.elapsed().as_secs() >= timeout {
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
