use crate::types::State;
use crate::util::{self, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs::{self, File, OpenOptions};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub sequence: u64,
    pub previous_sha256: Option<String>,
    pub kind: String,
    pub time_ms: u64,
    pub payload: Value,
    pub state_after: State,
    pub event_sha256: String,
}
impl Event {
    fn digest(&self) -> Result<String> {
        let mut v = serde_json::to_value(self).map_err(|_| "event_encode")?;
        v.as_object_mut().unwrap().remove("event_sha256");
        util::hash_json(&v)
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Checkpoint {
    head_sha256: String,
    state: State,
}

pub struct Store {
    pub path: PathBuf,
    pub events: Vec<Event>,
    pub state: State,
    pub head: Option<String>,
    _lock: File,
}
impl Store {
    fn lock(path: &Path) -> Result<File> {
        if fs::symlink_metadata(path)
            .map_err(|_| "task_missing")?
            .file_type()
            .is_symlink()
            || !path.is_dir()
        {
            return Err("invalid_task_root".into());
        }
        let f = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(path.join("controller.lock"))
            .map_err(|_| "task_lock_open")?;
        if !f.metadata().map_err(|_| "lock_metadata")?.is_file() {
            return Err("task_lock_not_regular".into());
        }
        if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err("task_already_running".into());
        }
        Ok(f)
    }
    pub fn create(path: &Path, state: State) -> Result<Self> {
        state.validate()?;
        let path = util::absolute(path)?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|_| "task_parent_create")?;
        }
        fs::DirBuilder::new()
            .mode(0o700)
            .create(&path)
            .map_err(|_| "task_exists_or_create_failed")?;
        fs::create_dir(path.join("events")).map_err(|_| "event_directory_create")?;
        let lock = Self::lock(&path)?;
        let mut s = Self {
            path,
            events: vec![],
            state,
            head: None,
            _lock: lock,
        };
        s.append("task_created",json!({"controller":"rust","aggregate_budget_policy":"explicit_config; null means uncapped","professional_review":false}))?;
        Ok(s)
    }
    pub fn open(path: &Path) -> Result<Self> {
        Self::open_inner(path, false)
    }
    fn open_inner(path: &Path, recover: bool) -> Result<Self> {
        let path = util::absolute(path)?;
        let lock = Self::lock(&path)?;
        let dir = path.join("events");
        if fs::symlink_metadata(&dir)
            .map_err(|_| "events_missing")?
            .file_type()
            .is_symlink()
        {
            return Err("events_symlink".into());
        }
        let mut paths = fs::read_dir(&dir)
            .map_err(|_| "events_missing")?
            .map(|r| r.map(|e| e.path()).map_err(|_| "event_entry".to_string()))
            .collect::<Result<Vec<_>>>()?;
        paths.sort();
        if paths.is_empty() || paths.len() > 100_000 {
            return Err("event_inventory_bound".into());
        }
        let mut events: Vec<Event> = vec![];
        let mut head = None;
        for (i, p) in paths.iter().enumerate() {
            if p.file_name().and_then(|s| s.to_str()) != Some(&format!("{:08}.json", i + 1)) {
                return Err("noncontiguous_or_uncommitted_event_inventory".into());
            }
            let e: Event = util::parse(&util::read_bounded(p, 4 * 1024 * 1024)?, 4 * 1024 * 1024)?;
            e.state_after.validate()?;
            if e.sequence != (i + 1) as u64
                || e.previous_sha256 != head
                || e.digest()? != e.event_sha256
            {
                return Err("event_chain_mismatch".into());
            }
            if let Some(first) = events.first() {
                if e.state_after.task_id != first.state_after.task_id {
                    return Err("task_identity_changed".into());
                }
            }
            head = Some(e.event_sha256.clone());
            events.push(e);
        }
        let state = events.last().unwrap().state_after.clone();
        let checkpoint_path = path.join("state.json");
        if checkpoint_path.exists() || checkpoint_path.is_symlink() {
            let checkpoint: Checkpoint = util::parse(
                &util::read_bounded(&checkpoint_path, 4 * 1024 * 1024)?,
                4 * 1024 * 1024,
            )?;
            let matches = Some(&checkpoint.head_sha256) == head.as_ref()
                && util::hash_json(&checkpoint.state)? == util::hash_json(&state)?;
            if !matches {
                let prefix = events
                    .iter()
                    .find(|e| e.event_sha256 == checkpoint.head_sha256)
                    .is_some_and(|e| {
                        util::hash_json(&e.state_after).ok()
                            == util::hash_json(&checkpoint.state).ok()
                    });
                if !recover || !prefix {
                    return Err("state_checkpoint_mismatch".into());
                }
            }
        } else if !recover {
            return Err("state_checkpoint_missing".into());
        }
        Ok(Self {
            path,
            events,
            state,
            head,
            _lock: lock,
        })
    }
    pub fn recover_checkpoint(path: &Path) -> Result<Value> {
        let mut store = Self::open_inner(path, true)?;
        store.verify(true)?;
        store.append(
            "checkpoint_recovered_from_committed_events",
            json!({"actor":"operator","uncommitted_work_adopted":false}),
        )?;
        Ok(
            json!({"recovered":true,"head_sha256":store.head,"status":store.state.status,"engineering_approved":false}),
        )
    }
    pub fn append(&mut self, kind: &str, payload: Value) -> Result<()> {
        self.state.validate()?;
        let mut event = Event {
            sequence: self.events.len() as u64 + 1,
            previous_sha256: self.head.clone(),
            kind: kind.into(),
            time_ms: util::now_ms(),
            payload,
            state_after: self.state.clone(),
            event_sha256: String::new(),
        };
        event.event_sha256 = event.digest()?;
        let bytes = util::json_bytes(&event)?;
        if bytes.len() > 4 * 1024 * 1024 {
            return Err("event_size_limit".into());
        }
        util::atomic_bytes(
            &self
                .path
                .join("events")
                .join(format!("{:08}.json", event.sequence)),
            &bytes,
            false,
        )?;
        self.head = Some(event.event_sha256.clone());
        self.events.push(event);
        util::atomic_json(
            &self.path.join("state.json"),
            &Checkpoint {
                head_sha256: self.head.clone().unwrap(),
                state: self.state.clone(),
            },
            true,
        )
    }
    pub fn verify(&self, allow_pending_domain: bool) -> Result<Value> {
        let mut count = 0;
        for event in &self.events {
            verify_artifact_values(&self.path, &event.payload, &mut count)?;
        }
        let mut domain_ok = true;
        if let Some(expected) = &self.state.domain_checkpoint_sha256 {
            let actual = util::file_hash(&util::safe_file(&self.path, "domain/state.json")?)?;
            domain_ok = &actual == expected;
            if !domain_ok
                && !(allow_pending_domain
                    && self
                        .state
                        .pending
                        .as_ref()
                        .is_some_and(|p| p.kind == "worker"))
            {
                return Err("domain_checkpoint_mismatch".into());
            }
            if domain_ok {
                verify_domain_identity(&self.path, &self.state.domain)?;
            }
        }
        if self.state.status == crate::types::Status::AwaitingHumanReview {
            if self.state.pending.is_some() {
                return Err("review_ready_with_pending_operation".into());
            }
            let context = &self.state.last_observation["validation_context"];
            match self.state.audit_implementation_sha256.as_deref() {
                Some(pin) => crate::validation::ready(
                    &self.path,
                    &self.state.last_observation,
                    &self.state.domain,
                    context,
                    Some(pin),
                ),
                // Finalized before the pin existed (new tasks cannot finalize
                // without one): readable, but not re-bound to a pinned identity.
                None => crate::validation::ready_legacy_unpinned(
                    &self.path,
                    &self.state.last_observation,
                    &self.state.domain,
                    context,
                ),
            }?;
        }
        Ok(
            json!({"valid":domain_ok,"pending_domain_requires_reconciliation":!domain_ok,"schema_version":self.state.schema_version,
            "head_sha256":self.head,"events":self.events.len(),"artifact_references_verified":count,"status":self.state.status,
            "engineering_approved":false,"local_consistency_only":true}),
        )
    }
}

pub fn verify_artifact_values(root: &Path, value: &Value, count: &mut usize) -> Result<()> {
    match value {
        Value::Object(obj) => {
            if let (Some(Value::String(path)), Some(Value::String(sha)), Some(bytes)) =
                (obj.get("path"), obj.get("sha256"), obj.get("bytes"))
            {
                let expected = bytes.as_u64().ok_or("artifact_size_type")?;
                if !util::valid_hash(sha) {
                    return Err("artifact_hash_type".into());
                }
                let p = util::safe_file(root, path)?;
                if fs::metadata(&p).map_err(|_| "artifact_stat")?.len() != expected
                    || util::file_hash(&p)? != *sha
                {
                    return Err("artifact_identity_mismatch".into());
                }
                *count += 1;
            }
            for v in obj.values() {
                verify_artifact_values(root, v, count)?;
            }
        }
        Value::Array(a) => {
            for v in a {
                verify_artifact_values(root, v, count)?;
            }
        }
        _ => (),
    }
    Ok(())
}

pub fn verify_domain_identity(root: &Path, description: &Value) -> Result<()> {
    let d = util::read_json(
        &util::safe_file(root, "domain/state.json")?,
        32 * 1024 * 1024,
    )?;
    if d["version"] != "source_bound_tools_v1" {
        return Err("domain_schema".into());
    }
    let input_name = d["active_spec_file"].as_str().unwrap_or("spec.json");
    let input = util::safe_file(root, &format!("domain/input/{input_name}"))?;
    let input_hash = d["input_spec_sha256"]
        .as_str()
        .ok_or("input_spec_binding")?;
    if util::file_hash(&input)? != input_hash {
        return Err("input_spec_changed".into());
    }
    if d["input_errors"].as_array().is_some_and(|a| a.is_empty()) {
        let mut spec = util::read_json(&input, 2 * 1024 * 1024)?;
        if spec["schema_version"] != "1.0" || spec["units"] != "m" {
            return Err("input_unit_or_schema_contract".into());
        }
        // A sheet-only intake spec declares no sections; after phase 1 the
        // domain writes them to a second, hash-bound file (materialize.py).
        let sheet_only =
            d["sheet_only"] == true && spec["sections"].as_array().is_some_and(|a| a.is_empty());
        if sheet_only {
            if let Some(hash) = d["materialized_spec_sha256"].as_str() {
                let materialized = util::safe_file(root, "domain/input/materialized_spec.json")?;
                if util::file_hash(&materialized)? != hash {
                    return Err("materialized_spec_changed".into());
                }
                spec = util::read_json(&materialized, 2 * 1024 * 1024)?;
            }
        }
        let awaiting_sections = sheet_only && d["materialized_spec_sha256"].is_null();
        if !awaiting_sections
            && spec["input_mode"]
                .as_str()
                .unwrap_or("calibrated_section_curves")
                == "calibrated_section_curves"
        {
            let sections = spec["sections"]
                .as_array()
                .ok_or("input_section_inventory")?;
            let mut ids = std::collections::BTreeSet::new();
            if !(3..=300).contains(&sections.len()) {
                return Err("input_section_count".into());
            }
            for section in sections {
                let sid = section["id"].as_str().ok_or("input_section_identity")?;
                if !util::valid_section_id(sid) || !ids.insert(sid) {
                    return Err("input_duplicate_or_invalid_section".into());
                }
                let finite = |v: &Value| {
                    v.as_f64()
                        .filter(|x| x.is_finite())
                        .ok_or("input_numeric_contract".to_string())
                };
                let x = finite(&section["x_m"])?;
                let zlo = finite(&section["z_min_m"])?;
                let zhi = finite(&section["z_max_m"])?;
                let scale = finite(&section["calibration"]["pixels_per_metre"])?;
                finite(&section["calibration"]["centerline_px"])?;
                finite(&section["calibration"]["baseline_px"])?;
                let roi = section["roi_px"].as_array().ok_or("input_roi")?;
                if roi.len() != 4
                    || roi.iter().any(|v| finite(v).is_err())
                    || x.abs() > 10_000_000.
                    || zlo.abs() > 10_000_000.
                    || zhi.abs() > 10_000_000.
                    || zhi <= zlo
                    || scale <= 0.
                    || scale > 1_000_000_000.
                {
                    return Err("input_geometry_bounds".into());
                }
                let coords = roi.iter().map(finite).collect::<Result<Vec<_>>>()?;
                if coords.iter().any(|n| *n < 0. || *n > 1_000_000.)
                    || coords[2] <= coords[0]
                    || coords[3] <= coords[1]
                {
                    return Err("input_roi_bounds".into());
                }
            }
        }
    }
    let sources = d["sources"].as_object().ok_or("source_inventory")?;
    for item in sources.values() {
        let name = item["file"].as_str().ok_or("source_file")?;
        if util::file_hash(&util::safe_file(root, &format!("domain/input/{name}"))?)?
            != item["sha256"].as_str().ok_or("source_hash")?
        {
            return Err("source_changed".into());
        }
    }
    let manifest = util::hash_json(&json!({"spec_sha256":input_hash,"sources":sources}))?;
    let mut identity = json!({"source":input_hash,"selected":d["selected"]});
    // Open draft guesses are part of the generation identity, so a draft
    // generation never equals the generation a person later confirms.
    if let Some(guessed) = crate::validation::guessed_choices(&d)? {
        identity["guessed"] = guessed;
    }
    let generation = format!("generation-{}", &util::hash_json(&identity)?[..24]);
    crate::validation::check_guess_contract(&d, description)?;
    let revision = format!("r{:04}", d["revision"].as_u64().ok_or("revision_type")?);
    if description["source_manifest_sha256"] != manifest
        || description["generation_id"] != generation
        || description["revision_id"] != revision
        || description["engineering_approved"] != false
        || description["human_semantic_review_required"] != true
    {
        return Err("domain_identity_or_review_boundary".into());
    }
    Ok(())
}

pub fn directory_size(path: &Path) -> Result<u64> {
    let mut total = 0u64;
    let mut todo = vec![path.to_path_buf()];
    let mut count = 0;
    while let Some(p) = todo.pop() {
        for r in fs::read_dir(p).map_err(|_| "disk_inventory")? {
            let e = r.map_err(|_| "disk_entry")?;
            let m = fs::symlink_metadata(e.path()).map_err(|_| "disk_stat")?;
            if m.file_type().is_symlink() {
                return Err("task_symlink".into());
            }
            count += 1;
            if count > 200_000 {
                return Err("task_inventory_limit".into());
            }
            if m.is_dir() {
                todo.push(e.path());
            } else if m.is_file() {
                total = total.checked_add(m.len()).ok_or("disk_overflow")?;
            } else {
                return Err("task_special_file".into());
            }
        }
    }
    Ok(total)
}

pub fn artifact(root: &Path, path: &str, kind: &str) -> Result<Value> {
    let p = util::safe_file(root, path)?;
    Ok(
        json!({"path":path,"kind":kind,"sha256":util::file_hash(&p)?,"bytes":fs::metadata(p).map_err(|_|"artifact_stat")?.len()}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;
    fn initial() -> State {
        crate::controller::new_state(Config {
            worker_python: "/usr/bin/python3".into(),
            worker_source: None,
            source_spec: "/tmp/spec.json".into(),
            policy: Policy::Deterministic,
            limits: OperationalLimits::default(),
            provider_transfer_authorized: false,
            authorization_basis: String::new(),
            model: GO_MODEL.into(),
            binary_sha256: "a".repeat(64),
            on_ambiguity: OnAmbiguity::Abstain,
            fallback_models: vec![],
            inspection_workers: None,
        })
    }
    #[test]
    fn lock_chain_and_checkpoint_reject_tampering() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("task");
        let mut store = Store::create(&path, initial()).unwrap();
        assert!(Store::open(&path).is_err());
        store.append("test", json!({"value":1})).unwrap();
        drop(store);
        let store = Store::open(&path).unwrap();
        assert!(store.verify(false).is_ok());
        drop(store);
        let file = path.join("events/00000002.json");
        let mut event: Value = util::read_json(&file, 100_000).unwrap();
        event["payload"]["value"] = json!(2);
        util::atomic_json(&file, &event, true).unwrap();
        assert!(Store::open(&path).is_err());
        assert!(Store::recover_checkpoint(&path).is_err());
    }
    #[test]
    fn explicit_recovery_accepts_only_missing_or_exact_prefix_cache() {
        for missing in [false, true] {
            let temp = tempfile::tempdir().unwrap();
            let path = temp.path().join("task");
            let mut store = Store::create(&path, initial()).unwrap();
            let old = std::fs::read(path.join("state.json")).unwrap();
            store.append("committed", json!({})).unwrap();
            drop(store);
            if missing {
                std::fs::remove_file(path.join("state.json")).unwrap();
            } else {
                std::fs::write(path.join("state.json"), old).unwrap();
            }
            assert!(Store::open(&path).is_err());
            Store::recover_checkpoint(&path).unwrap();
            let store = Store::open(&path).unwrap();
            assert_eq!(store.events.len(), 3);
        }
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("task");
        drop(Store::create(&path, initial()).unwrap());
        let mut checkpoint: Value = util::read_json(&path.join("state.json"), 100_000).unwrap();
        checkpoint["state"]["status"] = "awaiting_human_review".into();
        util::atomic_json(&path.join("state.json"), &checkpoint, true).unwrap();
        assert!(Store::recover_checkpoint(&path).is_err());
    }
    #[test]
    fn immutable_artifacts_and_uncommitted_events_are_not_adopted() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("task");
        let mut store = Store::create(&path, initial()).unwrap();
        util::atomic_bytes(&path.join("evidence/a"), b"original", false).unwrap();
        store
            .append("evidence", artifact(&path, "evidence/a", "test").unwrap())
            .unwrap();
        std::fs::write(path.join("evidence/a"), b"changed").unwrap();
        assert!(store.verify(false).is_err());
        drop(store);
        std::fs::write(path.join("events/.pending-crash"), b"partial").unwrap();
        assert!(Store::open(&path).is_err());
        assert!(Store::recover_checkpoint(&path).is_err());
    }
}
