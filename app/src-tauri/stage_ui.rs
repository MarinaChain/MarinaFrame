// Release UI staging (docs/plans/2026-11-09-packaging.md, step 2). Used by build.rs on every
// build and tested from main.rs (`#[path]` module), so `cargo build`, `tauri build` and CI all
// embed the same checked copy.
//
// It copies only the files the app needs from `app/ui` into `app/ui-release` (git-ignored),
// which `tauri.conf.json` embeds. The browser mock (`ui/mock`), the screenshots and any local
// data stay out. Staging fails when a copied file has a type outside ALLOWED_EXTENSIONS
// (drawings and CAD or model files such as .glb, .step, .tif or .pdf are never UI files) or is
// larger than MAX_FILE_BYTES. `tauri dev` serves `app/ui` itself (tauri.dev.conf.json).

use std::path::{Path, PathBuf};

/// The top-level entries of `ui/` that the app loads. Everything else stays out.
pub const INCLUDED: [&str; 5] = ["index.html", "styles.css", "js", "vendor", "assets"];
/// Text and font types of a web UI. A file without an extension is a licence text (LICENSE).
pub const ALLOWED_EXTENSIONS: [&str; 8] = ["html", "css", "js", "mjs", "svg", "woff2", "txt", "md"];
/// The largest UI file today is the three.js module (0.7 MB); a drawing or a model is larger.
pub const MAX_FILE_BYTES: u64 = 1024 * 1024;

fn files_under(folder: &Path, out: &mut Vec<PathBuf>) -> std::io::Result<()> {
    for entry in std::fs::read_dir(folder)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        if kind.is_dir() {
            files_under(&entry.path(), out)?;
        } else {
            out.push(entry.path());
        }
    }
    Ok(())
}

/// Every reason the staged folder may not ship, one line per file; empty when it may.
pub fn problems(folder: &Path) -> Vec<String> {
    let mut files = vec![];
    if let Err(error) = files_under(folder, &mut files) {
        return vec![format!("{}: {error}", folder.display())];
    }
    files.sort();
    let mut found = vec![];
    for path in files {
        let name = path
            .strip_prefix(folder)
            .unwrap_or(&path)
            .display()
            .to_string();
        let Ok(meta) = std::fs::symlink_metadata(&path) else {
            found.push(format!("{name}: cannot be read"));
            continue;
        };
        if !meta.is_file() {
            found.push(format!("{name}: not a regular file"));
            continue;
        }
        let extension = path
            .extension()
            .map(|e| e.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default();
        if !extension.is_empty() && !ALLOWED_EXTENSIONS.contains(&extension.as_str()) {
            found.push(format!(
                "{name}: .{extension} files are not part of the UI (drawing, model or data file?)"
            ));
        }
        if meta.len() > MAX_FILE_BYTES {
            found.push(format!(
                "{name}: {} bytes, more than {MAX_FILE_BYTES}",
                meta.len()
            ));
        }
    }
    found
}

/// Copy `from` (a file or folder) to `to`, writing only files whose bytes differ, so a
/// build does not touch unchanged files (Cargo watches their times). Adds every copied
/// path to `wanted`.
fn copy_tree(from: &Path, to: &Path, wanted: &mut Vec<PathBuf>) -> std::io::Result<()> {
    let meta = std::fs::symlink_metadata(from)?;
    if meta.is_dir() {
        std::fs::create_dir_all(to)?;
        for entry in std::fs::read_dir(from)? {
            let entry = entry?;
            copy_tree(&entry.path(), &to.join(entry.file_name()), wanted)?;
        }
        return Ok(());
    }
    // A link would let the copy reach outside ui/; leave a marker that the check reports.
    let (target, bytes) = if meta.is_file() {
        (to.to_path_buf(), std::fs::read(from)?)
    } else {
        (to.with_extension("link-not-copied"), vec![])
    };
    if std::fs::read(&target).ok().as_deref() != Some(bytes.as_slice()) {
        std::fs::write(&target, &bytes)?;
    }
    wanted.push(target);
    Ok(())
}

/// Bring `target` in line with the included entries of `source` and check the result.
pub fn stage(source: &Path, target: &Path) -> Vec<String> {
    if let Err(error) = std::fs::create_dir_all(target) {
        return vec![format!("{}: {error}", target.display())];
    }
    let mut wanted = vec![];
    for entry in INCLUDED {
        let from = source.join(entry);
        if !from.exists() {
            return vec![format!("ui/{entry} is missing")];
        }
        if let Err(error) = copy_tree(&from, &target.join(entry), &mut wanted) {
            return vec![format!("ui/{entry}: {error}")];
        }
    }
    // Remove what is no longer in ui/ (or was never meant to be in the release UI).
    let mut present = vec![];
    if files_under(target, &mut present).is_ok() {
        for path in present.into_iter().filter(|p| !wanted.contains(p)) {
            let _ = std::fs::remove_file(path);
        }
    }
    problems(target)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fake_ui(root: &Path) -> PathBuf {
        let ui = root.join("ui");
        for dir in ["js", "vendor", "assets", "mock/files", "screenshots"] {
            std::fs::create_dir_all(ui.join(dir)).unwrap();
        }
        for (file, text) in [
            ("index.html", "<!doctype html>"),
            ("styles.css", "body{}"),
            ("js/app.js", ""),
            ("vendor/LICENSE", "MIT"),
            ("assets/mark.svg", "<svg/>"),
            ("mock/files/whole-vessel-draft.glb", "glTF"),
            ("screenshots/shot.png", "png"),
        ] {
            std::fs::write(ui.join(file), text).unwrap();
        }
        ui
    }

    #[test]
    fn a_stale_file_in_the_staged_folder_is_removed() {
        let dir = tempfile::tempdir().unwrap();
        let ui = fake_ui(dir.path());
        let target = dir.path().join("ui-release");
        std::fs::create_dir_all(target.join("mock/files")).unwrap();
        std::fs::write(target.join("mock/files/old.glb"), "glTF").unwrap();
        assert_eq!(stage(&ui, &target), Vec::<String>::new());
        assert!(!target.join("mock/files/old.glb").exists());
    }

    #[test]
    fn the_mock_screenshots_and_local_data_stay_out() {
        let dir = tempfile::tempdir().unwrap();
        let ui = fake_ui(dir.path());
        let target = dir.path().join("ui-release");
        assert_eq!(stage(&ui, &target), Vec::<String>::new());
        assert!(target.join("js/app.js").is_file());
        assert!(target.join("vendor/LICENSE").is_file());
        assert!(!target.join("mock").exists());
        assert!(!target.join("screenshots").exists());
    }

    #[test]
    fn a_model_drawing_or_large_file_fails_the_check() {
        let dir = tempfile::tempdir().unwrap();
        let ui = fake_ui(dir.path());
        std::fs::write(ui.join("assets/hull.step"), "ISO-10303-21;").unwrap();
        std::fs::write(ui.join("vendor/sheet.TIF"), "II*").unwrap();
        std::fs::write(
            ui.join("js/big.js"),
            vec![b' '; MAX_FILE_BYTES as usize + 1],
        )
        .unwrap();
        let found = stage(&ui, &dir.path().join("ui-release"));
        assert_eq!(found.len(), 3, "{found:?}");
        assert!(found.iter().any(|p| p.contains("hull.step")));
        assert!(found.iter().any(|p| p.contains("sheet.TIF")));
        assert!(found.iter().any(|p| p.contains("big.js")));
    }

    #[test]
    fn a_link_in_the_ui_is_not_followed() {
        let dir = tempfile::tempdir().unwrap();
        let ui = fake_ui(dir.path());
        std::os::unix::fs::symlink("/etc/hosts", ui.join("js/hosts.js")).unwrap();
        let found = stage(&ui, &dir.path().join("ui-release"));
        assert_eq!(found.len(), 1, "{found:?}");
        assert!(found[0].contains("link-not-copied"));
    }
}
