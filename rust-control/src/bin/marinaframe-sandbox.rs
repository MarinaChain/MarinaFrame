//! Private hostile-code launcher. Setup errors have a reserved exit code (125).
#[cfg(target_os = "linux")]
#[path = "sandbox/linux.rs"]
mod linux;

fn main() {
    #[cfg(target_os = "linux")]
    let error = linux::launch().unwrap_err();
    #[cfg(not(target_os = "linux"))]
    let error = "Linux sandbox launcher is only supported on Linux";
    eprintln!("Linux sandbox setup failed: {error}; no unsafe fallback");
    std::process::exit(125);
}
