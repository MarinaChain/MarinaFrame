//! Settings and dismissed notices. The caller passes the storage folder (the Tauri
//! app config dir for the desktop app, any folder for a server).
use crate::error::{AppError, AppResult};
use crate::types::{Settings, Theme};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

const SETTINGS_FILE: &str = "settings.json";
const NOTICES_FILE: &str = "dismissed_notices.json";
const MAX_FILE_BYTES: usize = 256 * 1024;

/// Where the app keeps its own files and what its defaults are.
#[derive(Clone, Debug)]
pub struct AppPaths {
    /// Holds `settings.json` and `dismissed_notices.json`.
    pub config_dir: PathBuf,
    /// Default parent of the runs folder (the app data dir).
    pub data_dir: PathBuf,
    /// Repository checkout used to find the default Python, when there is one.
    pub repo_root: Option<PathBuf>,
}

impl AppPaths {
    pub fn default_settings(&self) -> Settings {
        let venv_python = self
            .repo_root
            .as_ref()
            .map(|root| root.join(".venv/bin/python"))
            .filter(|python| python.is_file());
        Settings {
            runs_folder: self.data_dir.join("runs").to_string_lossy().into_owned(),
            worker_python: venv_python
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default(),
            theme: Theme::System,
            ai_drafting: true,
        }
    }
}

fn read_small(path: &Path) -> Option<Vec<u8>> {
    marinaframe_control::util::read_bounded(path, MAX_FILE_BYTES).ok()
}

/// Write through a temporary file and rename, so a crash never leaves half a file.
fn write_atomic(dir: &Path, name: &str, bytes: &[u8]) -> AppResult<()> {
    fs::create_dir_all(dir)
        .map_err(|_| AppError::new("storage_write", "Settings could not be saved."))?;
    let temp = dir.join(format!(".{name}.tmp"));
    fs::write(&temp, bytes)
        .and_then(|_| fs::rename(&temp, dir.join(name)))
        .map_err(|_| AppError::new("storage_write", "Settings could not be saved."))
}

pub fn get_settings(paths: &AppPaths) -> Settings {
    read_small(&paths.config_dir.join(SETTINGS_FILE))
        .and_then(|bytes| serde_json::from_slice::<Settings>(&bytes).ok())
        .unwrap_or_else(|| paths.default_settings())
}

pub fn set_settings(paths: &AppPaths, settings: Settings) -> AppResult<Settings> {
    let invalid = || AppError::from_code("invalid_settings");
    if !Path::new(&settings.runs_folder).is_absolute() || settings.runs_folder.contains('\0') {
        return Err(invalid());
    }
    if !settings.worker_python.is_empty() {
        let python = Path::new(&settings.worker_python);
        if !python.is_absolute() || !python.is_file() {
            return Err(AppError::from_code("worker_python_missing"));
        }
    }
    let bytes = serde_json::to_vec_pretty(&settings).map_err(|_| invalid())?;
    write_atomic(&paths.config_dir, SETTINGS_FILE, &bytes)?;
    Ok(settings)
}

#[derive(Default, Serialize, Deserialize)]
struct Dismissed {
    dismissed: BTreeSet<String>,
}

pub fn dismissed_notices(paths: &AppPaths) -> BTreeSet<String> {
    read_small(&paths.config_dir.join(NOTICES_FILE))
        .and_then(|bytes| serde_json::from_slice::<Dismissed>(&bytes).ok())
        .map(|d| d.dismissed)
        .unwrap_or_default()
}

fn save_dismissed(paths: &AppPaths, dismissed: BTreeSet<String>) -> AppResult<()> {
    let bytes = serde_json::to_vec_pretty(&Dismissed { dismissed })
        .map_err(|_| AppError::new("storage_write", "Settings could not be saved."))?;
    write_atomic(&paths.config_dir, NOTICES_FILE, &bytes)
}

pub fn dismiss_notice(paths: &AppPaths, id: &str) -> AppResult<()> {
    if id.is_empty() || id.len() > 256 || id.chars().any(char::is_control) {
        return Err(AppError::new(
            "invalid_notice",
            "That notice does not exist.",
        ));
    }
    let mut dismissed = dismissed_notices(paths);
    dismissed.insert(id.to_string());
    save_dismissed(paths, dismissed)
}

pub fn reset_notices(paths: &AppPaths) -> AppResult<()> {
    save_dismissed(paths, BTreeSet::new())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn paths(tmp: &tempfile::TempDir) -> AppPaths {
        AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        }
    }

    #[test]
    fn dismissed_notices_survive_a_restart_and_reset() {
        let tmp = tempfile::tempdir().unwrap();
        let p = paths(&tmp);
        assert!(dismissed_notices(&p).is_empty());
        dismiss_notice(&p, "engineering-approval").unwrap();
        // A second AppPaths value with the same folder acts like a restart.
        assert!(dismissed_notices(&paths(&tmp)).contains("engineering-approval"));
        reset_notices(&p).unwrap();
        assert!(dismissed_notices(&p).is_empty());
    }

    #[test]
    fn settings_default_then_round_trip_and_reject_bad_values() {
        let tmp = tempfile::tempdir().unwrap();
        let p = paths(&tmp);
        let mut settings = get_settings(&p);
        assert!(settings.runs_folder.ends_with("data/runs"));
        settings.theme = Theme::Dark;
        set_settings(&p, settings.clone()).unwrap();
        assert_eq!(get_settings(&p), settings);
        settings.runs_folder = "relative/runs".into();
        assert_eq!(
            set_settings(&p, settings.clone()).unwrap_err().code,
            "invalid_settings"
        );
        settings.runs_folder = tmp.path().join("runs").to_string_lossy().into_owned();
        settings.worker_python = "/definitely/not/python".into();
        assert_eq!(
            set_settings(&p, settings).unwrap_err().code,
            "worker_python_missing"
        );
    }

    #[test]
    fn ai_drafting_is_on_by_default_also_for_an_older_settings_file() {
        let tmp = tempfile::tempdir().unwrap();
        let p = paths(&tmp);
        assert!(get_settings(&p).ai_drafting);
        // A settings file written before the field existed.
        fs::create_dir_all(&p.config_dir).unwrap();
        let older = serde_json::json!({"runs_folder": tmp.path().join("runs"),
                                       "worker_python": "", "theme": "system"});
        fs::write(p.config_dir.join(SETTINGS_FILE), older.to_string()).unwrap();
        assert!(get_settings(&p).ai_drafting);
    }
}
