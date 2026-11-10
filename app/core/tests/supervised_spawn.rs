//! Keep worker launches behind the shared supervisor.
#[test]
fn python_workers_do_not_construct_processes_directly() {
    for file in [
        "src/intake.rs",
        "src/export.rs",
        "src/part_revise.rs",
        "../../rust-control/src/model_review.rs",
        "../../rust-control/src/worker.rs",
    ] {
        let source =
            std::fs::read_to_string(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(file))
                .unwrap();
        assert!(
            !source.contains("Command::new(worker.python)"),
            "{file} bypasses the supervisor"
        );
        assert!(
            !source.contains("Command::new(self.python)"),
            "{file} bypasses the supervisor"
        );
        assert!(
            !source.contains("Command::new(&config.worker_python)"),
            "{file} bypasses the supervisor"
        );
        assert!(
            source.contains("WorkerCommand") || source.contains("module_command("),
            "{file} does not use the shared worker builder"
        );
    }
}
