use serde::de::{self, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

pub type Result<T> = std::result::Result<T, String>;

pub fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
pub fn json_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    // Sorting via Value makes this stable across typed struct field order.
    let value = serde_json::to_value(value).map_err(|_| "json_encode")?;
    serde_json::to_vec(&value).map_err(|_| "json_encode".into())
}
pub fn hash_json<T: Serialize>(value: &T) -> Result<String> {
    Ok(hash(&json_bytes(value)?))
}
pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
pub fn nonce() -> String {
    static COUNT: AtomicU64 = AtomicU64::new(0);
    let mut random = [0u8; 16];
    let _ = File::open("/dev/urandom").and_then(|mut f| f.read_exact(&mut random));
    format!(
        "{}-{}-{}-{}",
        now_ms(),
        std::process::id(),
        COUNT.fetch_add(1, Ordering::SeqCst),
        &hash(&random)[..12]
    )
}
pub fn valid_hash(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
pub fn valid_id(s: &str, max: usize) -> bool {
    !s.is_empty()
        && s.len() <= max
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_.:-".contains(&c))
}
pub fn valid_section_id(s: &str) -> bool {
    !s.trim().is_empty() && s.chars().count() <= 256 && !s.chars().any(char::is_control)
}
pub fn absolute(path: &Path) -> Result<PathBuf> {
    let p = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir().map_err(|_| "cwd")?.join(path)
    };
    if p.components().any(|c| matches!(c, Component::ParentDir)) {
        return Err("parent_path_rejected".into());
    }
    Ok(p)
}
pub fn safe_file(root: &Path, relative: &str) -> Result<PathBuf> {
    if relative.is_empty()
        || relative.len() > 4096
        || relative.contains('\\')
        || relative.contains('\0')
        || relative.starts_with('/')
    {
        return Err("unsafe_artifact_path".into());
    }
    let mut p = root.to_path_buf();
    for part in relative.split('/') {
        if part.is_empty() || part == "." || part == ".." {
            return Err("unsafe_artifact_path".into());
        }
        p.push(part);
        let m = fs::symlink_metadata(&p).map_err(|_| "artifact_missing")?;
        if m.file_type().is_symlink() {
            return Err("artifact_symlink".into());
        }
    }
    if !p.is_file() {
        return Err("artifact_not_regular".into());
    }
    Ok(p)
}
pub fn read_bounded(path: &Path, max: usize) -> Result<Vec<u8>> {
    let meta = fs::symlink_metadata(path).map_err(|_| "file_missing")?;
    if !meta.is_file() || meta.file_type().is_symlink() || meta.len() > max as u64 {
        return Err("file_bound_or_type".into());
    }
    let mut f = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|_| "file_open")?;
    let mut bytes = Vec::new();
    (&mut f)
        .take((max + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| "file_read")?;
    if bytes.len() > max {
        return Err("file_size_limit".into());
    }
    Ok(bytes)
}
pub fn file_hash(path: &Path) -> Result<String> {
    let meta = fs::symlink_metadata(path).map_err(|_| "artifact_missing")?;
    if !meta.is_file() || meta.file_type().is_symlink() || meta.len() > 512 * 1024 * 1024 {
        return Err("artifact_bound_or_type".into());
    }
    let mut f = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|_| "artifact_open")?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 65536];
    let mut total = 0;
    loop {
        let n = f.read(&mut buf).map_err(|_| "artifact_read")?;
        if n == 0 {
            break;
        }
        total += n;
        if total > 512 * 1024 * 1024 {
            return Err("artifact_size_limit".into());
        }
        h.update(&buf[..n]);
    }
    Ok(format!("{:x}", h.finalize()))
}
pub fn atomic_bytes(path: &Path, bytes: &[u8], replace: bool) -> Result<()> {
    let parent = path.parent().ok_or("missing_parent")?;
    fs::create_dir_all(parent).map_err(|_| "create_directory")?;
    if fs::symlink_metadata(path)
        .map(|m| m.file_type().is_symlink())
        .unwrap_or(false)
    {
        return Err("target_symlink".into());
    }
    let temp = parent.join(format!(".pending-{}", nonce()));
    let mut f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&temp)
        .map_err(|_| "atomic_create")?;
    f.write_all(bytes)
        .and_then(|_| f.sync_all())
        .map_err(|_| "atomic_write")?;
    drop(f);
    if replace {
        fs::rename(&temp, path).map_err(|_| "atomic_rename")?;
    } else {
        fs::hard_link(&temp, path).map_err(|_| "atomic_publish_exists_or_failed")?;
        fs::remove_file(&temp).map_err(|_| "atomic_unlink")?;
    }
    File::open(parent)
        .and_then(|f| f.sync_all())
        .map_err(|_| "directory_sync")?;
    Ok(())
}
pub fn atomic_json<T: Serialize>(path: &Path, value: &T, replace: bool) -> Result<()> {
    let mut bytes = json_bytes(value)?;
    bytes.push(b'\n');
    atomic_bytes(path, &bytes, replace)
}

// serde_json::Value alone accepts duplicate object keys. This visitor rejects
// them before converting into strict versioned structs or operation enums.
struct StrictValue(Value);
impl<'de> Deserialize<'de> for StrictValue {
    fn deserialize<D: Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = StrictValue;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                write!(f, "finite JSON without duplicate keys")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> std::result::Result<Self::Value, E> {
                Ok(StrictValue(Value::Bool(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> std::result::Result<Self::Value, E> {
                Ok(StrictValue(v.into()))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> std::result::Result<Self::Value, E> {
                Ok(StrictValue(v.into()))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> std::result::Result<Self::Value, E> {
                serde_json::Number::from_f64(v)
                    .map(|n| StrictValue(Value::Number(n)))
                    .ok_or_else(|| E::custom("nonfinite"))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> std::result::Result<Self::Value, E> {
                Ok(StrictValue(Value::String(v.into())))
            }
            fn visit_string<E: de::Error>(self, v: String) -> std::result::Result<Self::Value, E> {
                Ok(StrictValue(Value::String(v)))
            }
            fn visit_unit<E: de::Error>(self) -> std::result::Result<Self::Value, E> {
                Ok(StrictValue(Value::Null))
            }
            fn visit_none<E: de::Error>(self) -> std::result::Result<Self::Value, E> {
                Ok(StrictValue(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(
                self,
                mut a: A,
            ) -> std::result::Result<Self::Value, A::Error> {
                let mut out = Vec::new();
                while let Some(v) = a.next_element::<StrictValue>()? {
                    out.push(v.0);
                    if out.len() > 100_000 {
                        return Err(de::Error::custom("array bound"));
                    }
                }
                Ok(StrictValue(Value::Array(out)))
            }
            fn visit_map<A: MapAccess<'de>>(
                self,
                mut a: A,
            ) -> std::result::Result<Self::Value, A::Error> {
                let mut out = Map::new();
                while let Some(k) = a.next_key::<String>()? {
                    if out.contains_key(&k) {
                        return Err(de::Error::custom("duplicate key"));
                    }
                    let v = a.next_value::<StrictValue>()?;
                    out.insert(k, v.0);
                    if out.len() > 100_000 {
                        return Err(de::Error::custom("object bound"));
                    }
                }
                Ok(StrictValue(Value::Object(out)))
            }
        }
        d.deserialize_any(V)
    }
}
pub fn strict_value(bytes: &[u8], max: usize) -> Result<Value> {
    if bytes.len() > max {
        return Err("json_byte_limit".into());
    }
    let v: StrictValue = serde_json::from_slice(bytes).map_err(|_| "invalid_strict_json")?;
    fn walk(v: &Value, depth: usize, count: &mut usize) -> Result<()> {
        *count += 1;
        if depth > 32 || *count > 200_000 {
            return Err("json_structure_limit".into());
        }
        match v {
            Value::Array(a) => {
                for x in a {
                    walk(x, depth + 1, count)?;
                }
            }
            Value::Object(a) => {
                for (k, x) in a {
                    if k.len() > 4096 {
                        return Err("json_key_limit".into());
                    }
                    walk(x, depth + 1, count)?;
                }
            }
            _ => (),
        }
        Ok(())
    }
    walk(&v.0, 0, &mut 0)?;
    Ok(v.0)
}
pub fn parse<T: serde::de::DeserializeOwned>(bytes: &[u8], max: usize) -> Result<T> {
    serde_json::from_value(strict_value(bytes, max)?).map_err(|_| "typed_contract_rejected".into())
}
pub fn read_json(path: &Path, max: usize) -> Result<Value> {
    strict_value(&read_bounded(path, max)?, max)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn finite_float_event_bytes_survive_disk_parse_roundtrip() {
        // Default serde_json parsing can move some f64 values by one ULP and
        // invalidate an otherwise unchanged event chain. float_roundtrip is a
        // required protocol dependency feature, exercised over varied exponents.
        let mut bits = 0x5f38_2da1_75ce_902bu64;
        let mut checked = 0;
        for _ in 0..12_000 {
            bits = bits
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            let value = f64::from_bits(bits);
            if !value.is_finite() {
                continue;
            }
            let before = json_bytes(&serde_json::json!({"measurement":value})).unwrap();
            let after = json_bytes(&strict_value(&before, 1024).unwrap()).unwrap();
            assert_eq!(before, after, "float bits {bits:016x}");
            checked += 1;
        }
        assert!(checked > 11_000);
    }
    #[test]
    fn duplicate_nonfinite_and_nested_duplicates_rejected() {
        for raw in [
            r#"{"a":1,"a":2}"#,
            r#"{"x":{"a":1,"a":2}}"#,
            r#"{"x":NaN}"#,
            r#"{"x":1e9999}"#,
        ] {
            assert!(strict_value(raw.as_bytes(), 4096).is_err());
        }
        assert!(strict_value(br#"{"x":true,"y":1.2}"#, 4096).is_ok());
    }
    #[test]
    fn paths_and_atomic_publication_fail_closed() {
        let d = tempfile::tempdir().unwrap();
        atomic_bytes(&d.path().join("a"), b"first", false).unwrap();
        assert!(atomic_bytes(&d.path().join("a"), b"second", false).is_err());
        assert!(safe_file(d.path(), "../a").is_err());
        assert!(safe_file(d.path(), "/etc/passwd").is_err());
        std::os::unix::fs::symlink(d.path().join("a"), d.path().join("link")).unwrap();
        assert!(safe_file(d.path(), "link").is_err());
        assert_eq!(read_bounded(&d.path().join("a"), 32).unwrap(), b"first");
    }
}
