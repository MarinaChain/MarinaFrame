/// Local runs may omit the worker; required CI runs must exercise it.
pub fn worker_python() -> Option<String> {
    let python = std::env::var("MARINAFRAME_TEST_PYTHON")
        .ok()
        .filter(|path| !path.trim().is_empty());
    if python.is_none() {
        assert_ne!(
            std::env::var("MARINAFRAME_REQUIRE_WORKER").as_deref(),
            Ok("1"),
            "MARINAFRAME_TEST_PYTHON must be set when MARINAFRAME_REQUIRE_WORKER=1"
        );
        eprintln!("MARINAFRAME_TEST_PYTHON not set; skipping");
    }
    python
}

/// Wait until no background action runs on `task`, then read its view.
///
/// Read the view only after the run is idle: a view read first can still show
/// `Running` when the run finishes between the two calls (seen under load).
// Each test crate compiles this module; not every crate waits on a run.
#[allow(dead_code)]
pub fn wait_until_idle(
    backend: &marinaframe_app_core::Backend,
    task: &str,
) -> marinaframe_app_core::types::TaskView {
    // A real CAD run on a loaded CI machine finishes well inside this bound.
    const RUN_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(240);
    let start = std::time::Instant::now();
    loop {
        if !backend.is_busy(task) {
            return backend.get_task(task).unwrap();
        }
        assert!(start.elapsed() < RUN_TIMEOUT, "run did not finish");
        std::thread::sleep(std::time::Duration::from_millis(300));
    }
}
