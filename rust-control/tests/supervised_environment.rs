//! A worker started by the shared builder sees only the allowlisted environment.
//! Its own test binary: it changes this process's environment.
use marinaframe_control::supervised::{
    never_cancelled, run_watched, Watch, WatchedEnd, WorkerCommand, DEFAULT_STALL_PERIOD,
};

#[test]
fn parent_secrets_do_not_reach_the_worker() {
    std::env::set_var("ANTHROPIC_API_KEY", "sk-parent-secret");
    std::env::set_var("OPENAI_API_KEY", "sk-parent-secret-2");
    std::env::set_var("LANG", "en_GB.UTF-8");
    let mut command = WorkerCommand::python("/bin/sh", None);
    command.args(["-c", "env"]).env("MARINAFRAME_GIVEN", "yes");
    let watch = Watch {
        stall_period: DEFAULT_STALL_PERIOD,
        cancelled: &never_cancelled,
        operation: "env",
    };
    let WatchedEnd::Finished(finished) = run_watched(&mut command, &watch).unwrap() else {
        panic!("the worker did not finish");
    };
    let environment = String::from_utf8(finished.stdout).unwrap();
    assert!(!environment.contains("sk-parent-secret"), "{environment}");
    assert!(!environment.contains("API_KEY"), "{environment}");
    assert!(environment.contains("LANG=en_GB.UTF-8"));
    assert!(environment.contains("MARINAFRAME_GIVEN=yes"));
    assert!(environment.contains("MARINAFRAME_PROGRESS_PATH="));
    assert!(!environment.contains("HOME="), "{environment}");
}
