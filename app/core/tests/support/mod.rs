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
