//! The one way to start and stop worker processes (code-review item 5).
//!
//! Every Python worker of the controller and of the desktop app is started by
//! [`WorkerCommand`]:
//! - in its own session and process group, so a stop also reaches its children;
//! - with an empty environment plus an explicit allowlist, so no model key or
//!   other secret of the parent is inherited;
//! - a stop sends SIGTERM to the group, waits [`STOP_GRACE`], then sends SIGKILL
//!   to the group.
//!
//! If the group cannot be made, the spawn fails: nothing runs unsupervised.
//!
//! Our own deterministic code has no wall-clock or CPU limit. [`run_watched`]
//! stops a worker only when the person cancels it or when its progress record
//! does not advance for the stall period. Only sandboxed model code has caps,
//! and those are set where that code runs.
use serde::{Deserialize, Serialize};
use std::ffi::OsStr;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

/// Time between SIGTERM and SIGKILL: enough for Python to run its signal
/// handlers (which stop separately supervised sandbox groups), short enough
/// that a Cancel feels immediate.
pub const STOP_GRACE: Duration = Duration::from_secs(2);
/// Five minutes permits slow native calls on loaded laptops.
pub const NO_PROGRESS_SECONDS: u64 = 300;
/// The default stall period: [`NO_PROGRESS_SECONDS`].
pub const DEFAULT_STALL_PERIOD: Duration = Duration::from_secs(NO_PROGRESS_SECONDS);
/// Variables every worker may see. None of them holds a secret.
pub const BASE_ENVIRONMENT: [&str; 4] = ["PATH", "LANG", "LC_ALL", "TZ"];
/// CAD steps normally report hundreds of units. Limit invented alternating
/// stages to 10,000 advances per worker step; explicit waiting does not refill it.
pub(crate) const MAX_PROGRESS_ADVANCES_PER_STEP: u64 = 10_000;
/// A progress record is one small JSON object.
const MAX_PROGRESS_BYTES: u64 = 2048;
/// How often the supervision loop checks the leader and the cancel request.
const POLL_INTERVAL: Duration = Duration::from_millis(20);
/// How often the progress file is read (it is written at work boundaries only).
const PROGRESS_POLL_INTERVAL: Duration = Duration::from_millis(250);
/// The request id that [`run_watched`] gives its worker's progress record.
const WATCHED_REQUEST_ID: &str = "worker";

// ------------------------------------------------------------------ progress

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

fn valid_request_id(request_id: &str) -> bool {
    !request_id.is_empty()
        && request_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
}

/// The progress record at `path` for `request_id`, or None when it is absent,
/// not a regular file, too large or not a valid record.
pub fn read_progress_file(path: &Path, request_id: &str) -> Option<WorkerProgress> {
    if !valid_request_id(request_id) {
        return None;
    }
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
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

/// Counts work boundaries (a new stage or part), not heartbeats or total time.
/// Uses elapsed monotonic time supplied by the supervisor (a fake clock in tests).
pub(crate) struct ProgressWatchdog {
    pub(crate) counter: u64,
    pub(crate) last_pair: Option<(String, u64)>,
    pub(crate) last_progress: Duration,
    stall_period: Duration,
}

impl ProgressWatchdog {
    pub(crate) fn new(now: Duration, stall_period: Duration) -> Self {
        Self {
            counter: 0,
            last_pair: None,
            last_progress: now,
            stall_period,
        }
    }

    /// Record what the worker reports now; true when it has stalled.
    pub(crate) fn update(
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
        now.saturating_sub(self.last_progress) >= self.stall_period
    }

    /// The last stage reported, or `fallback` when none was.
    pub(crate) fn stage<'a>(&'a self, fallback: &'a str) -> &'a str {
        self.last_pair
            .as_ref()
            .map_or(fallback, |(stage, _)| stage.as_str())
    }

    /// Minutes since the last progress.
    pub(crate) fn idle_minutes(&self, now: Duration) -> f64 {
        now.saturating_sub(self.last_progress).as_secs_f64() / 60.0
    }
}

/// The plain message for a worker stopped by the progress watchdog.
pub fn stall_message(stage: &str, minutes: f64) -> String {
    format!("The worker was stopped at {stage} after {minutes:.1} min without progress.")
}

// ------------------------------------------------------------------ command

/// Kernel limits for a worker. The file-size and open-file limits are fixed.
#[derive(Clone, Copy, Debug)]
pub struct ResourceLimits {
    /// Address-space limit; enforced on Linux only (see `pre_exec_setup`).
    pub memory_bytes: u64,
    /// 0 sets no CPU limit.
    pub cpu_seconds: u64,
}
/// Largest file a limited worker may write (bytes).
const WORKER_FILE_SIZE_LIMIT: u64 = 256 * 1024 * 1024;
/// Most open files of a limited worker.
const WORKER_OPEN_FILES_LIMIT: u64 = 128;

/// A worker command: its own process group and an explicit environment.
pub struct WorkerCommand {
    command: Command,
    limits: Option<ResourceLimits>,
}

impl WorkerCommand {
    /// `python` with only [`BASE_ENVIRONMENT`], one thread per numeric library,
    /// no bytecode files and, when given, `PYTHONPATH` = `source`.
    pub fn python(python: impl AsRef<OsStr>, source: Option<&Path>) -> Self {
        let mut command = Command::new(python);
        command.env_clear();
        let mut worker = Self {
            command,
            limits: None,
        };
        for key in BASE_ENVIRONMENT {
            worker.pass_through(key);
        }
        worker
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("PYTHONUNBUFFERED", "1")
            .env("OPENBLAS_NUM_THREADS", "1")
            .env("OMP_NUM_THREADS", "1")
            .env("OMP_THREAD_LIMIT", "1")
            .env("MKL_NUM_THREADS", "1");
        if let Some(source) = source {
            worker.env("PYTHONPATH", source);
        }
        worker
    }

    /// A program that keeps the parent's environment. Only for the controller's
    /// own provider worker, which reads the model keys it is given.
    pub fn inheriting_environment(program: impl AsRef<OsStr>) -> Self {
        Self {
            command: Command::new(program),
            limits: None,
        }
    }

    /// Copy `key` from the parent's environment when it is set.
    pub fn pass_through(&mut self, key: &str) -> &mut Self {
        if let Some(value) = std::env::var_os(key) {
            self.command.env(key, value);
        }
        self
    }

    pub fn env(&mut self, key: impl AsRef<OsStr>, value: impl AsRef<OsStr>) -> &mut Self {
        self.command.env(key, value);
        self
    }

    pub fn arg(&mut self, arg: impl AsRef<OsStr>) -> &mut Self {
        self.command.arg(arg);
        self
    }

    pub fn args<I, S>(&mut self, args: I) -> &mut Self
    where
        I: IntoIterator<Item = S>,
        S: AsRef<OsStr>,
    {
        self.command.args(args);
        self
    }

    pub fn current_dir(&mut self, dir: impl AsRef<Path>) -> &mut Self {
        self.command.current_dir(dir);
        self
    }

    pub fn stdio(&mut self, stdin: Stdio, stdout: Stdio, stderr: Stdio) -> &mut Self {
        self.command.stdin(stdin).stdout(stdout).stderr(stderr);
        self
    }

    pub fn resource_limits(&mut self, limits: ResourceLimits) -> &mut Self {
        self.limits = Some(limits);
        self
    }

    /// Start the worker as the leader of a new session and process group.
    /// Fails (and nothing runs) when the group or a limit cannot be set.
    pub fn spawn(&mut self) -> std::io::Result<ProcessGroup> {
        let limits = self.limits;
        let parent = unsafe { libc::getpid() };
        unsafe {
            self.command
                .pre_exec(move || pre_exec_setup(parent, limits));
        }
        let child = self.command.spawn()?;
        Ok(ProcessGroup {
            child,
            reaped: false,
        })
    }
}

/// Runs in the child between fork and exec; only async-signal-safe calls.
fn pre_exec_setup(parent: libc::pid_t, limits: Option<ResourceLimits>) -> std::io::Result<()> {
    if unsafe { libc::setsid() } < 0 {
        return Err(std::io::Error::last_os_error());
    }
    // Linux stops the worker when its supervisor dies. macOS has no
    // parent-death signal; recovery handles orphaned workers.
    #[cfg(target_os = "linux")]
    if unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) } < 0 {
        return Err(std::io::Error::last_os_error());
    }
    if unsafe { libc::getppid() } != parent {
        return Err(std::io::Error::other("parent changed"));
    }
    match limits {
        Some(limits) => set_resource_limits(limits),
        None => Ok(()),
    }
}

fn set_resource_limits(limits: ResourceLimits) -> std::io::Result<()> {
    // On macOS RLIMIT_AS is an alias of RLIMIT_RSS: the kernel rejects
    // lowering it and does not enforce RSS limits. The worker memory
    // limit is therefore Linux-only (see docs/CONTINUATION_STATUS.md).
    #[cfg(target_os = "linux")]
    let memory_limit = Some((libc::RLIMIT_AS, limits.memory_bytes, limits.memory_bytes));
    #[cfg(not(target_os = "linux"))]
    let memory_limit = None;
    let cpu = limits.cpu_seconds;
    // The hard CPU limit is one second above the soft one, so SIGXCPU comes first.
    let cpu_limit = (cpu > 0).then_some((libc::RLIMIT_CPU, cpu, cpu + 1));
    let fixed = [
        (
            libc::RLIMIT_FSIZE,
            WORKER_FILE_SIZE_LIMIT,
            WORKER_FILE_SIZE_LIMIT,
        ),
        (
            libc::RLIMIT_NOFILE,
            WORKER_OPEN_FILES_LIMIT,
            WORKER_OPEN_FILES_LIMIT,
        ),
    ];
    for (which, soft, hard) in memory_limit.into_iter().chain(cpu_limit).chain(fixed) {
        let limit = libc::rlimit {
            rlim_cur: soft as libc::rlim_t,
            rlim_max: hard as libc::rlim_t,
        };
        if unsafe { libc::setrlimit(which, &limit) } != 0 {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(())
}

// ------------------------------------------------------------------ group

/// A running worker and its process group. The leader stays unreaped until the
/// group has been signalled, so its PID (the group ID) cannot be reused before
/// the last group signal. Dropping it kills the group.
pub struct ProcessGroup {
    child: Child,
    reaped: bool,
}

impl ProcessGroup {
    /// The leader's PID, which is also the process group ID.
    pub fn id(&self) -> i32 {
        self.child.id() as i32
    }

    pub fn child_mut(&mut self) -> &mut Child {
        &mut self.child
    }

    /// Whether the leader has exited, without reaping it.
    pub fn leader_exited(&self) -> std::io::Result<bool> {
        let pid = self.id();
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
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted {
                return Ok(false);
            }
            return Err(error);
        }
        Ok(unsafe { info.si_pid() } == pid)
    }

    fn signal_group(&self, signal: libc::c_int) {
        unsafe {
            libc::kill(-self.id(), signal);
        }
    }

    fn reap(mut self) -> std::io::Result<ExitStatus> {
        self.reaped = true;
        self.child.wait()
    }

    /// After the leader exited: a worker's exit does not authorize live
    /// descendants, so kill what is left of the group, then reap the leader.
    pub fn finish(self) -> std::io::Result<ExitStatus> {
        self.signal_group(libc::SIGKILL);
        self.reap()
    }

    /// Stop the whole group: SIGTERM, up to [`STOP_GRACE`] for the leader to
    /// exit, then SIGKILL (for descendants that ignored SIGTERM), then reap.
    pub fn stop(self) -> std::io::Result<ExitStatus> {
        self.signal_group(libc::SIGTERM);
        let grace = Instant::now();
        while grace.elapsed() < STOP_GRACE {
            if self.leader_exited().unwrap_or(false) {
                break;
            }
            std::thread::sleep(POLL_INTERVAL);
        }
        self.signal_group(libc::SIGKILL);
        self.reap()
    }

    /// Kill the whole group at once (error paths), then reap.
    pub fn kill(self) -> std::io::Result<ExitStatus> {
        self.finish()
    }
}

impl Drop for ProcessGroup {
    fn drop(&mut self) {
        if !self.reaped {
            self.signal_group(libc::SIGKILL);
            let _ = self.child.wait();
        }
    }
}

// ------------------------------------------------------------------ watched run

/// When [`run_watched`] stops a worker besides its own exit.
pub struct Watch<'a> {
    /// No progress for this long stops the worker.
    pub stall_period: Duration,
    /// True when the person asked to stop.
    pub cancelled: &'a dyn Fn() -> bool,
    /// Named in the stall message when the worker reported no stage.
    pub operation: &'a str,
}

/// For a [`Watch`] that nobody can cancel.
pub fn never_cancelled() -> bool {
    false
}

/// A worker that exited by itself.
pub struct Finished {
    pub status: ExitStatus,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

pub enum WatchedEnd {
    Finished(Finished),
    Cancelled,
    /// No progress for the stall period at `stage`; `minutes` since the last progress.
    Stalled {
        stage: String,
        minutes: f64,
    },
}

/// Run `command` to its end with stdin closed and stdout and stderr captured.
/// The worker reports progress through `MARINAFRAME_PROGRESS_PATH` (a private
/// folder made here); the whole group is stopped on cancel or stall.
pub fn run_watched(command: &mut WorkerCommand, watch: &Watch) -> std::io::Result<WatchedEnd> {
    let progress_dir = private_progress_dir()?;
    let progress_path = progress_dir.path().join("progress.json");
    command
        .env("MARINAFRAME_PROGRESS_PATH", &progress_path)
        .env("MARINAFRAME_PROGRESS_REQUEST", WATCHED_REQUEST_ID)
        .stdio(Stdio::null(), Stdio::piped(), Stdio::piped());
    let mut group = command.spawn()?;
    let stdout = read_to_end_in_thread(group.child_mut().stdout.take());
    let stderr = read_to_end_in_thread(group.child_mut().stderr.take());
    let started = Instant::now();
    let mut watchdog = ProgressWatchdog::new(Duration::ZERO, watch.stall_period);
    let mut next_progress_poll = Duration::ZERO;
    loop {
        if group.leader_exited()? {
            let status = group.finish()?;
            return Ok(WatchedEnd::Finished(Finished {
                status,
                stdout: stdout.join().unwrap_or_default(),
                stderr: stderr.join().unwrap_or_default(),
            }));
        }
        if (watch.cancelled)() {
            group.stop()?;
            return Ok(WatchedEnd::Cancelled);
        }
        let elapsed = started.elapsed();
        if elapsed >= next_progress_poll {
            next_progress_poll = elapsed + PROGRESS_POLL_INTERVAL;
            let progress = read_progress_file(&progress_path, WATCHED_REQUEST_ID);
            if watchdog.update(elapsed, progress.as_ref(), false) {
                group.stop()?;
                return Ok(WatchedEnd::Stalled {
                    stage: watchdog.stage(watch.operation).to_string(),
                    minutes: watchdog.idle_minutes(elapsed),
                });
            }
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

/// A new folder only this user can open; removed when dropped.
fn private_progress_dir() -> std::io::Result<tempfile::TempDir> {
    use std::os::unix::fs::PermissionsExt;
    tempfile::Builder::new()
        .prefix("marinaframe-progress-")
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()
}

/// Read a pipe on its own thread so that a full pipe cannot block the worker.
fn read_to_end_in_thread(pipe: Option<impl Read + Send + 'static>) -> JoinHandle<Vec<u8>> {
    std::thread::spawn(move || {
        let mut bytes = vec![];
        if let Some(mut pipe) = pipe {
            let _ = pipe.read_to_end(&mut bytes);
        }
        bytes
    })
}

#[cfg(test)]
mod tests {
    use super::*;

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

    fn watchdog() -> ProgressWatchdog {
        ProgressWatchdog::new(Duration::ZERO, DEFAULT_STALL_PERIOD)
    }

    #[test]
    fn watchdog_ignores_child_counter_changes_and_limits_accepted_advances() {
        let mut watch = watchdog();
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
    fn watchdog_counts_progress_not_heartbeats_or_total_duration() {
        let mut watch = watchdog();
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
        let mut watch = watchdog();
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
    fn watchdog_uses_the_given_stall_period_and_names_the_last_stage() {
        let mut watch = ProgressWatchdog::new(Duration::ZERO, Duration::from_secs(60));
        assert_eq!(watch.stage("intake"), "intake");
        assert!(!watch.update(Duration::from_secs(10), Some(&progress_record(1, 1)), false));
        assert!(watch.update(Duration::from_secs(70), Some(&progress_record(1, 1)), false));
        assert_eq!(watch.stage("intake"), "Building the hull");
        assert!((watch.idle_minutes(Duration::from_secs(70)) - 1.0).abs() < 1e-9);
        assert!(stall_message("Read page 2", 5.0).contains("Read page 2 after 5.0 min"));
    }
}
