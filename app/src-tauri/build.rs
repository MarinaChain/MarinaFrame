//! Stage and check the release UI (`app/core/src/release_ui.rs`) before Tauri embeds it, so
//! every build of the app (`cargo build`, `tauri build`) embeds `app/ui-release` and never
//! `app/ui/mock`. The staging rules are tested in marinaframe-app-core, which CI runs.
use std::path::PathBuf;

mod stage_ui {
    include!("../core/src/release_ui.rs");
}

fn main() {
    let app = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    println!("cargo:rerun-if-changed=../ui");
    println!("cargo:rerun-if-changed=../core/src/release_ui.rs");
    let found = stage_ui::stage(&app.join("ui"), &app.join("ui-release"));
    if !found.is_empty() {
        panic!("Release UI check failed:\n  {}", found.join("\n  "));
    }
    tauri_build::build()
}
