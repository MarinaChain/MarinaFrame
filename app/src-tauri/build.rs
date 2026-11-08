//! Stage and check the release UI (stage_ui.rs) before Tauri embeds it, so every build —
//! `cargo build`, `tauri build`, CI — embeds `app/ui-release` and never `app/ui/mock`.
use std::path::PathBuf;

mod stage_ui {
    include!("stage_ui.rs");
}

fn main() {
    let app = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    println!("cargo:rerun-if-changed=../ui");
    println!("cargo:rerun-if-changed=stage_ui.rs");
    let found = stage_ui::stage(&app.join("ui"), &app.join("ui-release"));
    if !found.is_empty() {
        panic!("Release UI check failed:\n  {}", found.join("\n  "));
    }
    tauri_build::build()
}
