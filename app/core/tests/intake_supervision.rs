//! Intake runs under the shared worker supervisor: Cancel stops the drawing reader
//! and its children, and a reader that stops reporting pages is stopped with a
//! message naming its stage. A stand-in shell script plays the worker Python.
use marinaframe_app_core::intake::{self, Worker};
use marinaframe_app_core::worker_run::Supervision;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// Most time a killed process may stay visible (until launchd or init reaps it).
const REAP_WAIT: Duration = Duration::from_secs(5);
/// Long enough that the watchdog never fires in a test that is not about it.
const NO_STALL: Duration = Duration::from_secs(600);

struct Setup {
    dir: tempfile::TempDir,
    python: String,
    drawing: String,
}

impl Setup {
    /// A fake worker Python and one drawing file in a new folder. The Python runs
    /// `script(folder)` whatever its arguments.
    fn new(script: impl FnOnce(&Path) -> String) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let python = dir.path().join("python");
        let body = script(dir.path());
        std::fs::write(&python, format!("#!/bin/sh\n{body}\n")).unwrap();
        std::fs::set_permissions(&python, std::fs::Permissions::from_mode(0o755)).unwrap();
        let drawing = dir.path().join("sheet.png");
        std::fs::write(&drawing, b"not read by the fake worker").unwrap();
        Self {
            python: python.to_string_lossy().into_owned(),
            drawing: drawing.to_string_lossy().into_owned(),
            dir,
        }
    }

    fn path(&self, name: &str) -> PathBuf {
        self.dir.path().join(name)
    }

    fn prepare(&self, supervision: &Supervision) -> marinaframe_app_core::AppError {
        let worker = Worker {
            python: &self.python,
            source: None,
        };
        intake::prepare_intake(
            &self.path("runs"),
            &worker,
            std::slice::from_ref(&self.drawing),
            false,
            supervision,
        )
        .unwrap_err()
    }
}

fn read_pid(path: &Path) -> i32 {
    std::fs::read_to_string(path)
        .unwrap()
        .trim()
        .parse()
        .unwrap()
}

/// True once `kill(pid, 0)` finds no such process and `ps` no longer lists it.
fn gone(pid: i32) -> bool {
    let started = Instant::now();
    while started.elapsed() < REAP_WAIT {
        let no_process = unsafe { libc::kill(pid, 0) } != 0
            && std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH);
        let listed = std::process::Command::new("ps")
            .args(["-p", &pid.to_string()])
            .output()
            .unwrap()
            .status
            .success();
        if no_process && !listed {
            return true;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    false
}

#[test]
fn cancel_stops_the_drawing_reader_and_its_children() {
    // The reader starts a child (as the Claude CLI would be) and keeps working.
    let setup = Setup::new(|dir| {
        format!(
            "sleep 300 & echo $! > {c}.tmp; mv {c}.tmp {c}; echo $$ > {l}.tmp; mv {l}.tmp {l}; \
             while :; do sleep 1; done",
            c = dir.join("child.pid").display(),
            l = dir.join("leader.pid").display()
        )
    });
    let leader_file = setup.path("leader.pid");
    let child_file = setup.path("child.pid");
    // The person presses Cancel once the reader and its child are running.
    let cancelled = || leader_file.exists() && child_file.exists();
    let started = Instant::now();
    let error = setup.prepare(&Supervision {
        cancelled: &cancelled,
        stall_period: NO_STALL,
    });
    assert_eq!(error.code, "intake_cancelled", "{}", error.message);
    assert!(started.elapsed() < Duration::from_secs(30));
    assert!(gone(read_pid(&leader_file)), "the reader is still running");
    assert!(
        gone(read_pid(&child_file)),
        "the reader's child is still running"
    );
}

#[test]
fn a_reader_that_stops_reporting_pages_is_stopped_with_its_stage() {
    // One page is read, then the reader hangs.
    let script = "printf '{\"request_id\":\"%s\",\"stage\":\"Read page 1\",\"part\":0,\"total\":0,\
                  \"unit\":\"part\",\"counter\":1,\"timestamp_ms\":1}' \
                  \"$MARINAFRAME_PROGRESS_REQUEST\" > \"$MARINAFRAME_PROGRESS_PATH\"\nsleep 300";
    let setup = Setup::new(|_| script.to_string());
    let started = Instant::now();
    let error = setup.prepare(&Supervision {
        cancelled: &|| false,
        stall_period: Duration::from_secs(1),
    });
    assert_eq!(error.code, "intake_stalled", "{}", error.message);
    assert!(error.message.contains("Read page 1"), "{}", error.message);
    assert!(
        error.message.contains("min without progress"),
        "{}",
        error.message
    );
    assert!(started.elapsed() < Duration::from_secs(30));
}

#[test]
fn a_reader_that_reports_each_page_is_not_stopped_however_long_it_takes() {
    // Six pages 0.4 s apart (2.4 s in all) with a 1 s stall period, then the answer.
    let mut script = String::new();
    for page in 1..=6 {
        script.push_str(&format!(
            "printf '{{\"request_id\":\"%s\",\"stage\":\"Read page {page}\",\"part\":0,\
             \"total\":0,\"unit\":\"part\",\"counter\":{page},\"timestamp_ms\":1}}' \
             \"$MARINAFRAME_PROGRESS_REQUEST\" > \"$MARINAFRAME_PROGRESS_PATH\"; sleep 0.4\n"
        ));
    }
    script.push_str("echo '{\"message\": \"finished reading\"}'; exit 1");
    let setup = Setup::new(|_| script);
    let error = setup.prepare(&Supervision {
        cancelled: &|| false,
        stall_period: Duration::from_secs(1),
    });
    // The worker's own answer arrives: it was not stopped.
    assert_eq!(error.code, "intake_worker");
    assert_eq!(error.message, "finished reading");
}
