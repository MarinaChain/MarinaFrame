//! Which Python runs the CAD worker, found at run time (packaging plan step 1).
//!
//! Order: the `MARINAFRAME_WORKER_PYTHON` environment variable, then the path in
//! Settings, then the worker runtime inside the app bundle
//! (`Contents/Resources/worker/bin/python3`), then (development only) the repository
//! `.venv`. When none is found the path is empty, the setup check asks, and the
//! person's choice is saved to Settings. Nothing here depends on where the app was
//! built.
//!
//! No place merely beside the app (or beside a bare executable) is searched: anyone
//! who can write that folder could plant a Python that the app would then run
//! without asking. The bundle's own Resources folder is covered by its signature.
use std::path::{Path, PathBuf};

pub const ENVIRONMENT_VARIABLE: &str = "MARINAFRAME_WORKER_PYTHON";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PythonSource {
    Environment,
    Settings,
    InBundle,
    Repository,
    None,
}

impl PythonSource {
    /// How the setup check names the source.
    pub fn words(self) -> &'static str {
        match self {
            Self::Environment => "from MARINAFRAME_WORKER_PYTHON",
            Self::Settings => "from Settings",
            Self::InBundle => "inside the app",
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

/// The worker runtime inside the app bundle of the executable `exe`
/// (`<App>.app/Contents/Resources/worker/bin/python3`), or None when `exe` is not in a
/// bundle (a development or bare build).
pub fn bundled_python(exe: &Path) -> Option<PathBuf> {
    let dir = exe.parent()?;
    let contents = dir.parent()?;
    let in_bundle = dir.file_name().is_some_and(|n| n == "MacOS")
        && contents.file_name().is_some_and(|n| n == "Contents");
    in_bundle.then(|| contents.join("Resources/worker/bin/python3"))
}

/// Pure rule, for tests: the first source that names a Python. An environment or
/// Settings value is taken as given (the setup check says when it is not found);
/// the bundled runtime and the repository count only when the file exists.
pub fn resolve(
    environment: Option<String>,
    settings: &str,
    bundled: Option<PathBuf>,
    repository: Option<PathBuf>,
) -> WorkerPython {
    let named = |path: String, source| WorkerPython { path, source };
    if let Some(value) = environment.filter(|v| !v.trim().is_empty()) {
        return named(value, PythonSource::Environment);
    }
    if !settings.trim().is_empty() {
        return named(settings.to_string(), PythonSource::Settings);
    }
    if let Some(path) = bundled.filter(|p| p.is_file()) {
        return named(path.to_string_lossy().into_owned(), PythonSource::InBundle);
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
    let bundled = std::env::current_exe()
        .ok()
        .and_then(|exe| bundled_python(&exe));
    resolve(
        std::env::var(ENVIRONMENT_VARIABLE).ok(),
        settings,
        bundled,
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
    fn the_environment_wins_then_settings_then_the_bundle_then_the_repository() {
        let dir = tempfile::tempdir().unwrap();
        let bundled = python_at(
            dir.path(),
            "MarinaFrame.app/Contents/Resources/worker/bin/python3",
        );
        let repo = python_at(dir.path(), "repo/.venv/bin/python");
        let env = resolve(
            Some("/opt/py".into()),
            "/set/py",
            Some(bundled.clone()),
            Some(repo.clone()),
        );
        assert_eq!(env.source, PythonSource::Environment);
        let set = resolve(None, "/set/py", Some(bundled.clone()), Some(repo.clone()));
        assert_eq!(
            (set.path.as_str(), set.source),
            ("/set/py", PythonSource::Settings)
        );
        let app = resolve(
            Some(" ".into()),
            "",
            Some(bundled.clone()),
            Some(repo.clone()),
        );
        assert_eq!(app.source, PythonSource::InBundle);
        assert_eq!(app.path, bundled.to_string_lossy());
        let dev = resolve(None, "", Some(dir.path().join("missing")), Some(repo));
        assert_eq!(dev.source, PythonSource::Repository);
        let none = resolve(None, "", None, None);
        assert_eq!((none.path.as_str(), none.source), ("", PythonSource::None));
    }

    #[test]
    fn only_the_runtime_inside_the_bundle_is_searched() {
        let bundle = Path::new("/Apps/MarinaFrame.app/Contents/MacOS/marinaframe-app");
        assert_eq!(
            bundled_python(bundle),
            Some(PathBuf::from(
                "/Apps/MarinaFrame.app/Contents/Resources/worker/bin/python3"
            ))
        );
        // A bare executable has no bundle: nothing beside it is searched.
        assert_eq!(
            bundled_python(Path::new("/build/target/release/marinaframe-app")),
            None
        );
    }

    #[test]
    fn a_python_planted_beside_the_bundle_is_never_used() {
        let dir = tempfile::tempdir().unwrap();
        let exe = dir
            .path()
            .join("MarinaFrame.app/Contents/MacOS/marinaframe-app");
        python_at(dir.path(), "MarinaFrame Worker/bin/python3");
        python_at(
            dir.path(),
            "MarinaFrame.app/Contents/MacOS/worker/bin/python3",
        );
        let found = resolve(None, "", bundled_python(&exe), None);
        assert_eq!(found.source, PythonSource::None);
    }
}
