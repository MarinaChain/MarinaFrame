//! `read_artifact`: send one image or STL file from inside a task folder.
use crate::error::{AppError, AppResult};
use crate::types::Artifact;
use base64::{engine::general_purpose::STANDARD, Engine};
use std::fs;
use std::path::{Path, PathBuf};

const MAX_IMAGE_BYTES: usize = 16 * 1024 * 1024;
const MAX_STL_BYTES: usize = 48 * 1024 * 1024;

/// Check a task-relative path and return the file path.
///
/// Rejected: absolute paths, `..` or empty segments, backslashes, NUL bytes, any
/// symlink on the way (including the task folder), and anything that is not a
/// regular file.
pub fn guard_inside_task(task_root: &Path, relative: &str) -> AppResult<PathBuf> {
    let unsafe_path = || AppError::from_code("unsafe_artifact_path");
    if relative.is_empty()
        || relative.len() > 1024
        || relative.starts_with('/')
        || relative.contains('\\')
        || relative.contains('\0')
    {
        return Err(unsafe_path());
    }
    if fs::symlink_metadata(task_root)
        .map(|m| m.file_type().is_symlink() || !m.is_dir())
        .unwrap_or(true)
    {
        return Err(AppError::from_code("invalid_task_root"));
    }
    let mut path = task_root.to_path_buf();
    for part in relative.split('/') {
        if part.is_empty() || part == "." || part == ".." {
            return Err(unsafe_path());
        }
        path.push(part);
        let meta =
            fs::symlink_metadata(&path).map_err(|_| AppError::from_code("artifact_missing"))?;
        if meta.file_type().is_symlink() {
            return Err(AppError::from_code("artifact_symlink"));
        }
    }
    if !path.is_file() {
        return Err(AppError::from_code("artifact_not_regular"));
    }
    Ok(path)
}

/// `guard_inside_task` plus the type rule: only PNG, JPEG and STL. Returns the
/// file path, the MIME type and the size limit.
pub fn guard_artifact_path(
    task_root: &Path,
    relative: &str,
) -> AppResult<(PathBuf, &'static str, usize)> {
    let (mime, limit) = match relative
        .rsplit('.')
        .next()
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("png") => ("image/png", MAX_IMAGE_BYTES),
        Some("jpg" | "jpeg") => ("image/jpeg", MAX_IMAGE_BYTES),
        Some("stl") => ("model/stl", MAX_STL_BYTES),
        _ => return Err(AppError::from_code("artifact_type_not_allowed")),
    };
    Ok((guard_inside_task(task_root, relative)?, mime, limit))
}

pub fn read_artifact(task_root: &Path, relative: &str) -> AppResult<Artifact> {
    let (path, mime, limit) = guard_artifact_path(task_root, relative)?;
    // `read_bounded` refuses a final symlink and a file above the limit.
    let bytes = marinaframe_control::util::read_bounded(&path, limit).map_err(|code| {
        if code == "file_bound_or_type" || code == "file_size_limit" {
            AppError::from_code("artifact_too_large")
        } else {
            AppError::from_code(code)
        }
    })?;
    Ok(Artifact {
        mime: mime.into(),
        base64: STANDARD.encode(bytes),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    fn task() -> tempfile::TempDir {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("task");
        fs::create_dir_all(root.join("domain")).unwrap();
        fs::write(root.join("domain/a.png"), b"\x89PNG").unwrap();
        fs::write(root.join("domain/m.STL"), b"solid x").unwrap();
        fs::write(root.join("domain/state.json"), b"{}").unwrap();
        fs::write(tmp.path().join("secret.png"), b"secret").unwrap();
        symlink(tmp.path().join("secret.png"), root.join("domain/link.png")).unwrap();
        symlink(tmp.path(), root.join("outside")).unwrap();
        tmp
    }

    #[test]
    fn reads_images_and_stl_inside_the_task() {
        let tmp = task();
        let root = tmp.path().join("task");
        let png = read_artifact(&root, "domain/a.png").unwrap();
        assert_eq!(png.mime, "image/png");
        assert_eq!(STANDARD.decode(png.base64).unwrap(), b"\x89PNG");
        assert_eq!(
            read_artifact(&root, "domain/m.STL").unwrap().mime,
            "model/stl"
        );
    }

    #[test]
    fn rejects_unsafe_paths_symlinks_and_other_types() {
        let tmp = task();
        let root = tmp.path().join("task");
        let code = |p: &str| read_artifact(&root, p).unwrap_err().code;
        assert_eq!(code("../secret.png"), "unsafe_artifact_path");
        assert_eq!(code("domain/../../secret.png"), "unsafe_artifact_path");
        assert_eq!(
            code(&tmp.path().join("secret.png").to_string_lossy()),
            "unsafe_artifact_path"
        );
        assert_eq!(code("domain\\a.png"), "unsafe_artifact_path");
        assert_eq!(code("domain//a.png"), "unsafe_artifact_path");
        assert_eq!(code("domain/link.png"), "artifact_symlink");
        assert_eq!(code("outside/secret.png"), "artifact_symlink");
        assert_eq!(code("domain/state.json"), "artifact_type_not_allowed");
        assert_eq!(code("domain/missing.png"), "artifact_missing");
        assert_eq!(code("domain"), "artifact_type_not_allowed");
    }

    #[test]
    fn rejects_a_symlinked_task_root() {
        let tmp = task();
        let linked = tmp.path().join("linked");
        symlink(tmp.path().join("task"), &linked).unwrap();
        assert_eq!(
            read_artifact(&linked, "domain/a.png").unwrap_err().code,
            "invalid_task_root"
        );
    }
}
