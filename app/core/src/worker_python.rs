//! Which Python runs the CAD worker, found at run time (packaging plan step 1).
//!
//! Order: the `MARINAFRAME_WORKER_PYTHON` environment variable, then the path in
//! Settings, then a worker runtime next to the app, then (development only) the
//! repository `.venv`. When none is found the path is empty and the setup check
//! asks the person to choose a Python. Nothing here depends on where the app was
//! built.
use std::path::{Path, PathBuf};

pub const ENVIRONMENT_VARIABLE: &str = "MARINAFRAME_WORKER_PYTHON";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PythonSource {
    Environment,
    Settings,
    NextToApp,
    Repository,
    None,
}

impl PythonSource {
    /// How the setup check names the source.
    pub fn words(self) -> &'static str {
        match self {
            Self::Environment => "from MARINAFRAME_WORKER_PYTHON",
            Self::Settings => "from Settings",
            Self::NextToApp => "next to the app",
            Self::Repository => "in the repository .venv",
            Self::None => "",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkerPython {
    pub path: String,
    pub source: PythonSource,
}

/// Where a worker runtime may sit next to the app, for the executable `exe`:
/// inside the bundle (`Contents/Resources/worker/bin/python3`), beside the bundle
/// (`MarinaFrame Worker/bin/python3` in the same folder as `MarinaFrame.app`), and
/// beside a bare executable (`worker/bin/python3`).
pub fn candidates_next_to(exe: &Path) -> Vec<PathBuf> {
    let mut found = vec![];
    let Some(dir) = exe.parent() else {
        return found;
    };
    let is_bundle = dir.file_name().is_some_and(|n| n == "MacOS")
        && dir
            .parent()
            .and_then(Path::file_name)
            .is_some_and(|n| n == "Contents");
    if is_bundle {
        let contents = dir.parent().expect("Contents");
        found.push(contents.join("Resources/worker/bin/python3"));
        if let Some(beside) = contents.parent().and_then(Path::parent) {
            found.push(beside.join("MarinaFrame Worker/bin/python3"));
        }
    } else {
        found.push(dir.join("worker/bin/python3"));
    }
    found
}

/// Pure rule, for tests: the first source that names a Python. An environment or
/// Settings value is taken as given (the setup check says when it is not found);
/// the places next to the app and the repository count only when the file exists.
pub fn resolve(
    environment: Option<String>,
    settings: &str,
    next_to_app: &[PathBuf],
    repository: Option<PathBuf>,
) -> WorkerPython {
    let named = |path: String, source| WorkerPython { path, source };
    if let Some(value) = environment.filter(|v| !v.trim().is_empty()) {
        return named(value, PythonSource::Environment);
    }
    if !settings.trim().is_empty() {
        return named(settings.to_string(), PythonSource::Settings);
    }
    if let Some(path) = next_to_app.iter().find(|p| p.is_file()) {
        return named(path.to_string_lossy().into_owned(), PythonSource::NextToApp);
    }
    if let Some(path) = repository.filter(|p| p.is_file()) {
        return named(
            path.to_string_lossy().into_owned(),
            PythonSource::Repository,
        );
    }
    named(String::new(), PythonSource::None)
}

/// The worker Python for this process, with Settings' value `settings` and the
/// repository root (development checkouts only).
pub fn find(settings: &str, repo_root: Option<&Path>) -> WorkerPython {
    let next_to_app = std::env::current_exe()
        .map(|exe| candidates_next_to(&exe))
        .unwrap_or_default();
    resolve(
        std::env::var(ENVIRONMENT_VARIABLE).ok(),
        settings,
        &next_to_app,
        repo_root.map(|root| root.join(".venv/bin/python")),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn python_at(dir: &Path, relative: &str) -> PathBuf {
        let path = dir.join(relative);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, b"").unwrap();
        path
    }

    #[test]
    fn the_environment_wins_then_settings_then_next_to_app_then_the_repository() {
        let dir = tempfile::tempdir().unwrap();
        let bundled = python_at(
            dir.path(),
            "MarinaFrame.app/Contents/Resources/worker/bin/python3",
        );
        let repo = python_at(dir.path(), "repo/.venv/bin/python");
        let near = vec![bundled.clone()];
        let env = resolve(Some("/opt/py".into()), "/set/py", &near, Some(repo.clone()));
        assert_eq!(env.source, PythonSource::Environment);
        let set = resolve(None, "/set/py", &near, Some(repo.clone()));
        assert_eq!(
            (set.path.as_str(), set.source),
            ("/set/py", PythonSource::Settings)
        );
        let app = resolve(Some(" ".into()), "", &near, Some(repo.clone()));
        assert_eq!(app.source, PythonSource::NextToApp);
        assert_eq!(app.path, bundled.to_string_lossy());
        let dev = resolve(None, "", &[dir.path().join("missing")], Some(repo));
        assert_eq!(dev.source, PythonSource::Repository);
        let none = resolve(None, "", &[], None);
        assert_eq!((none.path.as_str(), none.source), ("", PythonSource::None));
    }

    #[test]
    fn places_next_to_a_bundle_and_a_bare_executable() {
        let bundle = Path::new("/Apps/MarinaFrame.app/Contents/MacOS/marinaframe-app");
        assert_eq!(
            candidates_next_to(bundle),
            vec![
                PathBuf::from("/Apps/MarinaFrame.app/Contents/Resources/worker/bin/python3"),
                PathBuf::from("/Apps/MarinaFrame Worker/bin/python3"),
            ]
        );
        let bare = Path::new("/build/target/release/marinaframe-app");
        assert_eq!(
            candidates_next_to(bare),
            vec![PathBuf::from("/build/target/release/worker/bin/python3")]
        );
    }
}
