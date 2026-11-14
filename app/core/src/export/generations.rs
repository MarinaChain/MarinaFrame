//! Resolve immutable package generations once per read operation.
use super::{write_error, AppResult};
use std::path::{Path, PathBuf};

fn ordinary(path: &Path, directory: bool) -> AppResult<()> {
    let metadata = std::fs::symlink_metadata(path).map_err(|_| write_error())?;
    #[cfg(windows)]
    let reparse = {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    };
    #[cfg(not(windows))]
    let reparse = false;
    if metadata.file_type().is_symlink()
        || reparse
        || (directory && !metadata.is_dir())
        || (!directory && !metadata.is_file())
    {
        return Err(write_error());
    }
    Ok(())
}

pub(super) fn resolve(root: &Path) -> AppResult<PathBuf> {
    let pointer = root.join("current.json");
    match std::fs::symlink_metadata(&pointer) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(root.to_owned()),
        Err(_) => return Err(write_error()),
        Ok(metadata) if metadata.len() > 4096 => return Err(write_error()),
        Ok(_) => {}
    }
    ordinary(root, true)?;
    ordinary(&pointer, false)?;
    use std::io::Read;
    let mut bytes = Vec::new();
    std::fs::File::open(pointer)
        .map_err(|_| write_error())?
        .take(4097)
        .read_to_end(&mut bytes)
        .map_err(|_| write_error())?;
    if bytes.len() > 4096 {
        return Err(write_error());
    }
    let value: serde_json::Value = serde_json::from_slice(&bytes).map_err(|_| write_error())?;
    let name = value["generation"].as_str().ok_or_else(write_error)?;
    if value["schema_version"] != 1
        || name.len() != 34
        || !name.starts_with("g-")
        || !name[2..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(write_error());
    }
    let folder = root.join(name);
    ordinary(&folder, true)?;
    Ok(folder)
}

#[cfg(windows)]
pub(super) fn publish(root: &Path, stage: &Path) -> AppResult<()> {
    use std::io::Write;
    use std::os::windows::ffi::OsStrExt;
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(source: *const u16, target: *const u16, flags: u32) -> i32;
    }
    fn move_path(source: &Path, target: &Path, replace: bool) -> AppResult<()> {
        let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
        let target: Vec<u16> = target.as_os_str().encode_wide().chain(Some(0)).collect();
        // Same-volume rename only: never COPY_ALLOWED or delete the old pointer first.
        let result =
            unsafe { MoveFileExW(source.as_ptr(), target.as_ptr(), 8 | u32::from(replace)) };
        if result == 0 {
            return Err(write_error());
        }
        Ok(())
    }
    std::fs::create_dir_all(root).map_err(|_| write_error())?;
    ordinary(root, true)?;
    ordinary(stage, true)?;
    let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
    let name = format!(
        "g-{:016x}{:08x}{:08x}",
        marinaframe_control::util::now_ms(),
        std::process::id(),
        sequence
    );
    let destination = root.join(&name);
    for entry in std::fs::read_dir(stage).map_err(|_| write_error())? {
        let entry = entry.map_err(|_| write_error())?;
        ordinary(&entry.path(), false)?;
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(entry.path())
            .and_then(|file| file.sync_all())
            .map_err(|_| write_error())?;
    }
    move_path(stage, &destination, false)?;
    let temporary = root.join(format!(".current-{}.tmp", &name[2..]));
    let result = (|| {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|_| write_error())?;
        write!(
            file,
            "{}",
            serde_json::json!({"schema_version":1,"generation":name})
        )
        .map_err(|_| write_error())?;
        file.sync_all().map_err(|_| write_error())?;
        drop(file);
        move_path(&temporary, &root.join("current.json"), true)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(temporary);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(windows)]
    #[test]
    fn windows_publish_retains_previous_generation() {
        let root = std::env::temp_dir().join(format!(
            "mf-native-generation-{}-{}",
            std::process::id(),
            marinaframe_control::util::now_ms()
        ));
        let first = root.with_extension("first");
        let second = root.with_extension("second");
        std::fs::create_dir_all(&first).unwrap();
        std::fs::write(first.join("report.pdf"), b"old").unwrap();
        publish(&root, &first).unwrap();
        let old = resolve(&root).unwrap();
        std::fs::create_dir_all(&second).unwrap();
        std::fs::write(second.join("report.pdf"), b"new").unwrap();
        publish(&root, &second).unwrap();
        let current = resolve(&root).unwrap();
        assert_ne!(old, current);
        assert_eq!(std::fs::read(old.join("report.pdf")).unwrap(), b"old");
        assert_eq!(std::fs::read(current.join("report.pdf")).unwrap(), b"new");
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn resolve_legacy_and_generation_without_traversal() {
        let root = std::env::temp_dir().join(format!(
            "mf-generation-{}-{}",
            std::process::id(),
            marinaframe_control::util::now_ms()
        ));
        std::fs::create_dir_all(&root).unwrap();
        assert_eq!(resolve(&root).unwrap(), root);
        let name = "g-0123456789abcdef0123456789abcdef";
        std::fs::create_dir(root.join(name)).unwrap();
        std::fs::write(
            root.join("current.json"),
            serde_json::json!({"schema_version":1,"generation":name}).to_string(),
        )
        .unwrap();
        assert_eq!(resolve(&root).unwrap(), root.join(name));
        std::fs::write(
            root.join("current.json"),
            r#"{"schema_version":1,"generation":"../escape"}"#,
        )
        .unwrap();
        assert!(resolve(&root).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
