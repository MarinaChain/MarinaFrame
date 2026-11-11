//! Stops of the shared worker supervisor reach the whole process group, and only
//! the progress watchdog (never total time) stops a worker that runs on.
use marinaframe_control::supervised::{
    never_cancelled, run_watched, Watch, WatchedEnd, WorkerCommand, STOP_GRACE,
};
use std::path::Path;
use std::time::{Duration, Instant};

/// Most time a killed process may stay visible (until launchd or init reaps it).
const REAP_WAIT: Duration = Duration::from_secs(5);

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

fn shell(script: &str) -> WorkerCommand {
    let mut command = WorkerCommand::python("/bin/sh", None);
    command.args(["-c", script]);
    command
}

fn watch_with<'a>(stall_period: Duration, cancelled: &'a dyn Fn() -> bool) -> Watch<'a> {
    Watch {
        stall_period,
        cancelled,
        operation: "test",
    }
}

/// Long enough that the watchdog never fires in a test that is not about it.
const NO_STALL: Duration = Duration::from_secs(600);

#[test]
fn cancel_stops_the_worker_and_its_grandchild_even_when_they_ignore_sigterm() {
    let dir = tempfile::tempdir().unwrap();
    let leader_file = dir.path().join("leader.pid");
    let grandchild_file = dir.path().join("grandchild.pid");
    // SIGTERM is ignored by the shell and (inherited) by its sleeping child,
    // so only the SIGKILL after the grace can end them.
    let script = format!(
        "trap '' TERM; sleep 300 & echo $! > {g}.tmp; mv {g}.tmp {g}; echo $$ > {l}.tmp; \
         mv {l}.tmp {l}; while :; do sleep 1; done",
        g = grandchild_file.display(),
        l = leader_file.display()
    );
    let cancelled = || grandchild_file.exists() && leader_file.exists();
    let started = Instant::now();
    let end = run_watched(&mut shell(&script), &watch_with(NO_STALL, &cancelled)).unwrap();
    assert!(matches!(end, WatchedEnd::Cancelled));
    assert!(
        started.elapsed() >= STOP_GRACE,
        "SIGKILL came before the grace"
    );
    let leader = read_pid(&leader_file);
    let grandchild = read_pid(&grandchild_file);
    assert!(gone(leader), "the worker {leader} is still running");
    assert!(
        gone(grandchild),
        "the grandchild {grandchild} is still running"
    );
}

#[test]
fn a_grandchild_left_behind_by_a_finished_worker_is_stopped() {
    let dir = tempfile::tempdir().unwrap();
    let grandchild_file = dir.path().join("grandchild.pid");
    let script = format!(
        "sleep 300 > /dev/null 2>&1 & echo $! > {}; echo done",
        grandchild_file.display()
    );
    let end = run_watched(&mut shell(&script), &watch_with(NO_STALL, &never_cancelled)).unwrap();
    let WatchedEnd::Finished(finished) = end else {
        panic!("the worker did not finish");
    };
    assert!(finished.status.success());
    assert_eq!(finished.stdout, b"done\n");
    assert!(gone(read_pid(&grandchild_file)));
}

/// A shell command that writes one progress record for `stage` and `part`.
fn report(stage: &str, part: u32) -> String {
    format!(
        "printf '{{\"request_id\":\"%s\",\"stage\":\"{stage}\",\"part\":{part},\"total\":100,\
         \"unit\":\"part\",\"counter\":{part},\"timestamp_ms\":1}}' \
         \"$MARINAFRAME_PROGRESS_REQUEST\" > \"$MARINAFRAME_PROGRESS_PATH\""
    )
}

#[test]
fn no_progress_for_the_stall_period_stops_the_worker_and_names_the_stage() {
    let script = format!("{}; sleep 300", report("Read page 1", 1));
    let stall = Duration::from_secs(1);
    let started = Instant::now();
    let end = run_watched(&mut shell(&script), &watch_with(stall, &never_cancelled)).unwrap();
    let WatchedEnd::Stalled { stage, minutes } = end else {
        panic!("the worker was not stopped as stalled");
    };
    assert_eq!(stage, "Read page 1");
    assert!(minutes >= 1.0 / 60.0);
    assert!(started.elapsed() < Duration::from_secs(30));
}

#[test]
fn a_worker_that_keeps_reporting_progress_runs_past_the_stall_period() {
    // Eight reports 0.4 s apart: 3.2 s in all, with a 1 s stall period.
    let reports: Vec<String> = (1..=8)
        .map(|part| format!("{}; sleep 0.4", report("Reading", part)))
        .collect();
    let script = format!("{}; echo finished", reports.join("; "));
    let stall = Duration::from_secs(1);
    let end = run_watched(&mut shell(&script), &watch_with(stall, &never_cancelled)).unwrap();
    let WatchedEnd::Finished(finished) = end else {
        panic!("a worker that made progress was stopped");
    };
    assert_eq!(finished.stdout, b"finished\n");
}

#[test]
fn a_worker_leads_its_own_process_group() {
    // The shell prints its PID, then its process group ID: they must be equal.
    let end = run_watched(
        &mut shell("echo $$; ps -o pgid= -p $$"),
        &watch_with(NO_STALL, &never_cancelled),
    )
    .unwrap();
    let WatchedEnd::Finished(finished) = end else {
        panic!("the worker did not finish");
    };
    let text = String::from_utf8(finished.stdout).unwrap();
    let values: Vec<&str> = text.split_whitespace().collect();
    assert_eq!(values.len(), 2, "{text}");
    assert_eq!(values[0], values[1], "{text}");
    assert_ne!(values[1], unsafe { libc::getpgrp() }.to_string());
}
