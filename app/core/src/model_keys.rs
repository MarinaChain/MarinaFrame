//! DeepSeek (OpenCode Go) keys for runs started from the desktop app.
//!
//! An app opened from Finder does not get the shell environment, so the app
//! reads the same key file as `scripts/load_opencode_keys.sh`:
//! `~/.config/marinaframe/opencode-go-keys.txt`, one key per line, mode 600.
//! Lines that are empty or contain "@" (account labels) are skipped; at most
//! three keys are used, in file order. No function here returns or logs a key
//! except [`export_keys_for_this_process`], which only sets environment
//! variables for the provider worker process.
use marinaframe_control::provider::credentials::CREDENTIAL_VARIABLES;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

const KEY_FILE: &str = ".config/marinaframe/opencode-go-keys.txt";
const MAX_KEY_FILE_BYTES: usize = 16 * 1024;
/// Group and other read bits. A key file readable by others is refused.
const SHARED_READ_BITS: u32 = 0o044;

/// Where the key file is expected, or None when HOME is unknown.
pub fn key_file() -> Option<PathBuf> {
    std::env::var_os("HOME").map(|home| PathBuf::from(home).join(KEY_FILE))
}

/// The keys in `path`, at most three. An unreadable, shared or empty file gives none.
fn read_keys(path: &Path) -> Vec<String> {
    let Ok(metadata) = std::fs::metadata(path) else {
        return vec![];
    };
    if !metadata.is_file() || metadata.permissions().mode() & SHARED_READ_BITS != 0 {
        return vec![];
    }
    let Ok(bytes) = marinaframe_control::util::read_bounded(path, MAX_KEY_FILE_BYTES) else {
        return vec![];
    };
    String::from_utf8_lossy(&bytes)
        .lines()
        .map(|line| line.split_whitespace().collect::<String>())
        .filter(|line| !line.is_empty() && !line.contains('@'))
        .take(CREDENTIAL_VARIABLES.len())
        .collect()
}

fn environment_has_key() -> bool {
    CREDENTIAL_VARIABLES
        .iter()
        .any(|name| std::env::var(name).is_ok_and(|value| !value.is_empty()))
}

/// Where model keys come from for a new run, if any.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeySource {
    Environment,
    KeyFile,
}

pub fn key_source() -> Option<KeySource> {
    if environment_has_key() {
        return Some(KeySource::Environment);
    }
    key_file()
        .filter(|path| !read_keys(path).is_empty())
        .map(|_| KeySource::KeyFile)
}

/// The keys a new run's provider worker would load, with their 1-based slot,
/// following the same rules: the environment (slot = variable position) when it
/// has any key, else the key file in line order. For the usage check only
/// ([`crate::model_usage`]): the keys go into a request header and nowhere else.
pub(crate) fn configured_keys() -> (Option<KeySource>, Vec<(u8, String)>) {
    if environment_has_key() {
        let keys = CREDENTIAL_VARIABLES
            .iter()
            .enumerate()
            .filter_map(|(index, name)| {
                let key = std::env::var(name).ok().filter(|k| !k.is_empty())?;
                Some((index as u8 + 1, key))
            })
            .collect();
        return (Some(KeySource::Environment), keys);
    }
    let keys: Vec<(u8, String)> = key_file()
        .map(|path| read_keys(&path))
        .unwrap_or_default()
        .into_iter()
        .zip(1u8..)
        .map(|(key, slot)| (slot, key))
        .collect();
    let source = (!keys.is_empty()).then_some(KeySource::KeyFile);
    (source, keys)
}

/// For the provider worker process only: when the environment has no key,
/// load the key file into `OPENCODE_API_KEY*`. Call it before any other thread
/// starts, because it changes this process's environment.
pub fn export_keys_for_this_process() {
    if environment_has_key() {
        return;
    }
    let Some(path) = key_file() else { return };
    for (variable, key) in CREDENTIAL_VARIABLES.iter().zip(read_keys(&path)) {
        std::env::set_var(variable, key);
    }
}

/// The provider worker entry of the desktop app: load keys (this process is still
/// single-threaded), then run one model request exactly as `marinaframe
/// provider-worker` does. True when the worker finished.
pub fn run_provider_worker(response: &Path, timeout_seconds: u64) -> bool {
    export_keys_for_this_process();
    marinaframe_control::provider::provider_worker(response, timeout_seconds).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write(dir: &Path, text: &str, mode: u32) -> PathBuf {
        let path = dir.join("keys.txt");
        std::fs::write(&path, text).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
        path
    }

    #[test]
    fn reads_up_to_three_keys_and_skips_labels_and_blank_lines() {
        let dir = tempfile::tempdir().unwrap();
        let path = write(
            dir.path(),
            "me@example.com\n key-one \n\nkey-two\nkey-three\nkey-four\n",
            0o600,
        );
        assert_eq!(read_keys(&path), vec!["key-one", "key-two", "key-three"]);
    }

    #[test]
    fn a_key_file_readable_by_others_gives_no_key() {
        let dir = tempfile::tempdir().unwrap();
        let path = write(dir.path(), "key-one\n", 0o644);
        assert!(read_keys(&path).is_empty());
    }

    #[test]
    fn a_missing_file_gives_no_key() {
        assert!(read_keys(Path::new("/definitely/not/a/key/file")).is_empty());
    }
}
