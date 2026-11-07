//! Independent finalization predicate. Python is the geometry tool; no worker
//! envelope boolean, cache flag or model assertion grants readiness here.
use crate::store::{verify_artifact_values, verify_domain_identity};
use crate::util::{self, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

/// Native worker resource profiles; the macOS profile has no address-space
/// limit and no parent-death signal (docs/CONTINUATION_STATUS.md).
const KNOWN_RESOURCE_PROFILES: [&str; 2] = [
    "linux_rlimit_process_group_v1",
    "darwin_rlimit_process_group_v1",
];

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Check {
    Passed,
    Failed,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Binding {
    pub generation_id: String,
    pub revision_id: String,
    pub run_id: String,
    pub source_manifest_sha256: String,
    pub input_spec_sha256: String,
    pub selection_sha256: String,
    pub revision_spec_sha256: String,
    pub run_manifest_sha256: String,
    pub run_result_sha256: String,
    pub step_sha256: String,
    pub audit_implementation_sha256: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Checks {
    pub worker_execution: String,
    pub artifact_integrity: Check,
    pub cad_validity: Check,
    pub trace_fidelity: Check,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Units {
    pub input: String,
    pub step: String,
    pub reported: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Tolerances {
    pub max_section_distance_m: f64,
    pub max_relative_metric_error: f64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Sampling {
    pub policy: String,
    pub section_ids: Vec<String>,
    pub total_section_count: usize,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Measurements {
    pub max_section_distance_m: f64,
    pub relative_metric_error: f64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Evidence {
    pub kind: String,
    pub path: String,
    pub sha256: String,
    pub bytes: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Contract {
    pub schema_version: String,
    pub binding: Binding,
    pub checks: Checks,
    pub outcome: Check,
    pub units: Units,
    pub tolerances: Tolerances,
    pub sampling: Sampling,
    pub measurements: Measurements,
    pub evidence: Vec<Evidence>,
    pub audit_contract_version: String,
    pub semantic_review: String,
    pub engineering_approved: bool,
}
impl Contract {
    pub fn check_shape(&self) -> Result<()> {
        if self.schema_version != "marinaframe.validation.v1"
            || self.audit_contract_version != "step_source_sections_v1"
            || self.semantic_review != "required"
            || self.engineering_approved
            || self.units.input != "m"
            || self.units.step != "mm"
            || self.units.reported != "m"
            || self.checks.worker_execution != "succeeded"
            || self.checks.artifact_integrity != Check::Passed
            || self.tolerances.max_section_distance_m != 0.0011
            || self.tolerances.max_relative_metric_error != 1e-6
        {
            return Err("validation_contract_or_boundary".into());
        }
        let b = serde_json::to_value(&self.binding).unwrap();
        for (k, v) in b.as_object().unwrap() {
            if k.ends_with("sha256") && !v.as_str().is_some_and(util::valid_hash) {
                return Err("validation_hash".into());
            }
        }
        if self.binding.generation_id.len() != 35
            || !self.binding.generation_id.starts_with("generation-")
            || !self.binding.generation_id[11..]
                .bytes()
                .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
            || !(5..=9).contains(&self.binding.revision_id.len())
            || !self.binding.revision_id.starts_with('r')
            || !self.binding.revision_id[1..]
                .bytes()
                .all(|c| c.is_ascii_digit())
            || self.binding.run_id.len() != 20
            || !self
                .binding
                .run_id
                .bytes()
                .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
        {
            return Err("validation_identity_format".into());
        }
        let m = &self.measurements;
        if !m.max_section_distance_m.is_finite()
            || m.max_section_distance_m < 0.
            || !m.relative_metric_error.is_finite()
            || m.relative_metric_error < 0.
        {
            return Err("validation_measurement_type".into());
        }
        if (self.checks.trace_fidelity == Check::Passed) != (m.max_section_distance_m <= 0.0011)
            || (self.checks.cad_validity == Check::Passed && m.relative_metric_error > 1e-6)
            || (self.outcome == Check::Passed)
                != (self.checks.cad_validity == Check::Passed
                    && self.checks.trace_fidelity == Check::Passed)
        {
            return Err("contradictory_validation".into());
        }
        let s = &self.sampling;
        let ids = s.section_ids.iter().collect::<BTreeSet<_>>();
        if s.policy != "first_two_middle_last_two_v1"
            || !(3..=300).contains(&s.total_section_count)
            || s.section_ids.len() != s.total_section_count.min(5)
            || ids.len() != s.section_ids.len()
            || s.section_ids.iter().any(|s| !util::valid_section_id(s))
        {
            return Err("validation_sampling".into());
        }
        if !(10..=64).contains(&self.evidence.len())
            || self
                .evidence
                .iter()
                .map(|e| &e.path)
                .collect::<BTreeSet<_>>()
                .len()
                != self.evidence.len()
            || self.evidence.iter().any(|e| {
                e.bytes == 0
                    || e.bytes > 512 * 1024 * 1024
                    || !util::valid_hash(&e.sha256)
                    || e.kind.is_empty()
                    || e.kind.len() > 80
                    || e.path.is_empty()
                    || e.path.len() > 4096
                    || e.path.starts_with('/')
                    || e.path.contains(['\\', '\0'])
                    || e.path
                        .split('/')
                        .any(|p| p.is_empty() || p == "." || p == "..")
            })
        {
            return Err("validation_evidence_inventory".into());
        }
        Ok(())
    }
}
fn require(ok: bool, code: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(code.into())
    }
}
fn finite(v: &Value) -> Result<f64> {
    let n = v.as_f64().ok_or("required_numeric_measurement")?;
    require(n.is_finite(), "nonfinite_measurement")?;
    Ok(n)
}
fn nonnegative(v: &Value) -> Result<f64> {
    let n = finite(v)?;
    require(n >= 0., "negative_measurement")?;
    Ok(n)
}
fn integer(v: &Value, min: u64, max: u64) -> Result<u64> {
    let n = v.as_u64().ok_or("integer_measurement_type")?;
    require(n >= min && n <= max, "integer_measurement_bound")?;
    Ok(n)
}
fn close(a: f64, b: f64) -> bool {
    (a - b).abs() <= 1e-12 + 1e-9 * a.abs().max(b.abs())
}
fn exact_keys(v: &Value, keys: &[&str]) -> Result<()> {
    let a = v.as_object().ok_or("required_object")?;
    require(
        a.keys().map(String::as_str).collect::<BTreeSet<_>>() == keys.iter().copied().collect(),
        "missing_or_unknown_fields",
    )
}

pub fn verify_manifest(run: &Path, run_id: &str) -> Result<()> {
    let manifest = util::read_json(&util::safe_file(run, "manifest.json")?, 4 * 1024 * 1024)?;
    exact_keys(
        &manifest,
        &[
            "schema_version",
            "kind",
            "hash_algorithm",
            "canonicalization",
            "run_id",
            "record",
            "files",
            "mutable_files",
            "local_integrity_only",
        ],
    )?;
    require(
        manifest["schema_version"] == "2.0"
            && manifest["kind"] == "marinaframe_run_manifest"
            && manifest["hash_algorithm"] == "sha256"
            && manifest["run_id"] == run_id
            && manifest["mutable_files"]
                == json!([".review.lock", "review_history.json", "review_state.json"]),
        "native_manifest_contract",
    )?;
    let files = manifest["files"]
        .as_object()
        .ok_or("native_manifest_files")?;
    require(
        !files.is_empty() && files.len() <= 1000,
        "native_manifest_count",
    )?;
    for required in [
        "result.json",
        "input_spec.json",
        "replay_spec.json",
        "extracted_sections.json",
        "cad_sections.json",
        "mesh.json",
        "model.step",
    ] {
        require(files.contains_key(required), "native_required_file")?;
    }
    for (path, entry) in files {
        exact_keys(entry, &["sha256", "size_bytes"])?;
        let p = util::safe_file(run, path)?;
        require(
            util::file_hash(&p)? == entry["sha256"].as_str().ok_or("native_file_hash")?
                && fs::metadata(&p).map_err(|_| "native_stat")?.len()
                    == entry["size_bytes"].as_u64().ok_or("native_file_size")?,
            "native_file_changed",
        )?;
    }
    let mut actual = BTreeSet::new();
    let mut todo = vec![run.to_path_buf()];
    while let Some(dir) = todo.pop() {
        for entry in fs::read_dir(&dir).map_err(|_| "native_inventory")? {
            let p = entry.map_err(|_| "native_entry")?.path();
            let m = fs::symlink_metadata(&p).map_err(|_| "native_stat")?;
            require(!m.file_type().is_symlink(), "native_symlink")?;
            if m.is_dir() {
                todo.push(p);
            } else if m.is_file() {
                actual.insert(
                    p.strip_prefix(run)
                        .map_err(|_| "native_path")?
                        .to_string_lossy()
                        .into_owned(),
                );
            } else {
                return Err("native_special_file".into());
            }
        }
    }
    for allowed in [
        "manifest.json",
        ".review.lock",
        "review_history.json",
        "review_state.json",
    ] {
        actual.remove(allowed);
    }
    require(
        actual == files.keys().cloned().collect(),
        "native_inventory_mismatch",
    )
}

pub fn assess(
    root: &Path,
    observation: &Value,
    domain: &Value,
    context: &Value,
) -> Result<Contract> {
    verify_domain_identity(root, domain)?;
    require(
        observation["engineering_approved"] == false
            && observation["human_semantic_review_required"] == true,
        "observation_review_boundary",
    )?;
    let validation = &observation["validation"];
    exact_keys(
        validation,
        &[
            "geometry_checks_passed",
            "immutable_run_verified",
            "geometry_audit",
            "sampled_sections",
            "sampled_section_count",
            "total_section_count",
            "section_sampling",
            "numeric_reference_truth_used",
            "unresolved_semantics",
            "human_semantic_review_required",
            "engineering_approved",
            "generation_id",
            "revision_id",
            "identity_certified",
            "artifacts",
            "contract",
        ],
    )?;
    let c: Contract = serde_json::from_value(validation["contract"].clone())
        .map_err(|_| "validation_typed_schema")?;
    c.check_shape()?;
    exact_keys(
        context,
        &[
            "binding",
            "evidence",
            "sampling",
            "section_info",
            "engine_metrics",
        ],
    )?;
    require(
        c.binding.generation_id == domain["generation_id"]
            && c.binding.revision_id == domain["revision_id"]
            && observation["generation_id"] == domain["generation_id"]
            && observation["revision_id"] == domain["revision_id"]
            && validation["generation_id"] == domain["generation_id"]
            && validation["revision_id"] == domain["revision_id"],
        "stale_validation",
    )?;
    require(
        serde_json::to_value(&c.binding).unwrap() == context["binding"]
            && serde_json::to_value(&c.sampling).unwrap() == context["sampling"],
        "validation_context_changed",
    )?;
    let state = util::read_json(
        &util::safe_file(root, "domain/state.json")?,
        32 * 1024 * 1024,
    )?;
    require(
        c.binding.source_manifest_sha256 == domain["source_manifest_sha256"]
            && c.binding.input_spec_sha256 == state["input_spec_sha256"]
            && c.binding.selection_sha256 == util::hash_json(&state["selected"])?,
        "validation_source_or_selection",
    )?;
    let candidate = &domain["current_candidate"];
    require(
        candidate["valid"] == true
            && candidate["generation_id"] == c.binding.generation_id
            && candidate["revision_id"] == c.binding.revision_id
            && candidate["run_id"] == c.binding.run_id,
        "validation_candidate_mismatch",
    )?;
    let rel = candidate["path"].as_str().ok_or("candidate_path")?;
    let result_path = util::safe_file(root, &format!("{rel}/result.json"))?;
    let run = result_path.parent().ok_or("run_parent")?;
    verify_manifest(run, &c.binding.run_id)?;
    let result = util::read_json(&result_path, 32 * 1024 * 1024)?;
    require(
        util::file_hash(&result_path)? == c.binding.run_result_sha256
            && util::file_hash(&util::safe_file(root, &format!("{rel}/manifest.json"))?)?
                == c.binding.run_manifest_sha256
            && util::file_hash(&util::safe_file(root, &format!("{rel}/model.step"))?)?
                == c.binding.step_sha256,
        "validation_native_identity",
    )?;
    let revision_spec = util::safe_file(
        root,
        &format!("domain/revisions/{}/spec.json", c.binding.revision_id),
    )?;
    require(
        util::file_hash(&revision_spec)? == c.binding.revision_spec_sha256
            && result["provenance"]["submitted_spec_sha256"] == c.binding.revision_spec_sha256
            && result["status"] == "review_required"
            && result["review"]["engineering_approved"] == false
            && result["exports"]["step_units"] == "mm"
            && result["exports"]["stl_units"] == "mm"
            && result["exports"]["mesh_units"] == "m",
        "validation_built_source_or_units",
    )?;
    require(
        result["run_id"] == c.binding.run_id
            && result["review"] == json!({"state":"unreviewed","engineering_approved":false}),
        "native_run_review_identity",
    )?;
    let selection = util::read_json(
        &util::safe_file(
            root,
            &format!("domain/revisions/{}/selection.json", c.binding.revision_id),
        )?,
        262_144,
    )?;
    require(
        selection
            == json!({"revision_id":c.binding.revision_id,"generation_id":c.binding.generation_id,"selected":state["selected"],"source_sha256":state["sources"],
        "human_semantic_review_required":true,"engineering_approved":false,"identity_certified":false}),
        "revision_selection_disagrees",
    )?;
    verify_artifact_values(root, &serde_json::to_value(&c.evidence).unwrap(), &mut 0)?;
    let paths = [
        ("captured_input_spec", "domain/input/spec.json".to_string()),
        (
            "submitted_input_spec",
            "domain/input/submitted_spec.json".to_string(),
        ),
        (
            "revision_spec",
            format!("domain/revisions/{}/spec.json", c.binding.revision_id),
        ),
        (
            "revision_selection",
            format!("domain/revisions/{}/selection.json", c.binding.revision_id),
        ),
        ("run_manifest", format!("{rel}/manifest.json")),
        ("run_result", format!("{rel}/result.json")),
        ("exported_step", format!("{rel}/model.step")),
    ];
    let mut expected_evidence = paths
        .iter()
        .map(|(kind, path)| crate::store::artifact(root, path, kind))
        .collect::<Result<Vec<_>>>()?;
    for (role, source) in state["sources"].as_object().ok_or("source_inventory")? {
        let path = format!(
            "domain/input/{}",
            source["file"].as_str().ok_or("source_filename")?
        );
        expected_evidence.push(crate::store::artifact(
            root,
            &path,
            &format!("captured_{role}"),
        )?);
    }
    require(
        context["evidence"] == Value::Array(expected_evidence.clone()),
        "context_evidence_not_current_files",
    )?;
    let artifacts = validation["artifacts"]
        .as_array()
        .ok_or("validation_artifacts")?;
    require(
        (3..=7).contains(&artifacts.len()),
        "validation_artifact_count",
    )?;
    let mut expected_worker_artifacts = vec![];
    let mut section_artifact_ids = vec![];
    for a in artifacts {
        require(
            a["id"]
                == format!(
                    "artifact-{}",
                    a["sha256"]
                        .as_str()
                        .ok_or("artifact_hash")?
                        .get(..24)
                        .ok_or("artifact_hash_length")?
                ),
            "artifact_id_mismatch",
        )?;
        if a["kind"] == "step_section_cut_comparison" {
            exact_keys(
                a,
                &[
                    "id",
                    "path",
                    "sha256",
                    "mime_type",
                    "kind",
                    "bytes",
                    "section_id",
                ],
            )?;
            require(
                a["mime_type"] == "image/png" && a["section_id"].is_string(),
                "section_artifact_type",
            )?;
            section_artifact_ids.push(a["section_id"].clone());
        } else {
            exact_keys(a, &["id", "path", "sha256", "mime_type", "kind", "bytes"])?;
            require(
                (a["kind"] == "step_reimport_validation"
                    || a["kind"] == "validation_worker_receipt")
                    && a["mime_type"] == "application/json",
                "audit_artifact_type",
            )?;
        }
        if a["kind"] != "validation_worker_receipt" {
            let mut item = json!({"file":Path::new(a["path"].as_str().ok_or("artifact_path")?).file_name().and_then(|n|n.to_str()).ok_or("artifact_filename")?,"kind":a["kind"]});
            if let Some(id) = a.get("section_id") {
                item["section_id"] = id.clone();
            }
            expected_worker_artifacts.push(item);
        }
        expected_evidence.push(
            json!({"kind":a["kind"],"path":a["path"],"sha256":a["sha256"],"bytes":a["bytes"]}),
        );
    }
    require(
        Value::Array(section_artifact_ids) == json!(c.sampling.section_ids),
        "section_artifact_order",
    )?;
    require(
        serde_json::to_value(&c.evidence).unwrap() == Value::Array(expected_evidence),
        "validation_evidence_binding",
    )?;
    let by_kind = c
        .evidence
        .iter()
        .fold(BTreeMap::<&str, Vec<&Evidence>>::new(), |mut map, e| {
            map.entry(&e.kind).or_default().push(e);
            map
        });
    for k in [
        "captured_input_spec",
        "submitted_input_spec",
        "revision_spec",
        "revision_selection",
        "run_manifest",
        "run_result",
        "exported_step",
        "step_reimport_validation",
        "validation_worker_receipt",
    ] {
        require(
            by_kind.get(k).is_some_and(|v| v.len() == 1),
            "required_validation_evidence",
        )?;
    }
    for role in state["sources"]
        .as_object()
        .ok_or("source_inventory")?
        .keys()
    {
        require(
            by_kind
                .get(format!("captured_{role}").as_str())
                .is_some_and(|v| v.len() == 1),
            "captured_source_coverage",
        )?;
    }
    require(
        by_kind
            .get("step_section_cut_comparison")
            .is_some_and(|v| v.len() == c.sampling.section_ids.len()),
        "section_image_coverage",
    )?;
    let audit = util::read_json(
        &util::safe_file(root, &by_kind["step_reimport_validation"][0].path)?,
        2 * 1024 * 1024,
    )?;
    let mut raw = validation.clone();
    for k in [
        "generation_id",
        "revision_id",
        "identity_certified",
        "artifacts",
        "contract",
    ] {
        raw.as_object_mut().unwrap().remove(k);
    }
    require(raw == audit, "cached_raw_audit_disagrees")?;
    let receipt = util::read_json(
        &util::safe_file(root, &by_kind["validation_worker_receipt"][0].path)?,
        2 * 1024 * 1024,
    )?;
    exact_keys(&receipt, &["validation", "artifacts", "resources"])?;
    exact_keys(
        &receipt["resources"],
        &[
            "wall_seconds",
            "cpu_seconds",
            "peak_rss_kib",
            "resource_profile",
        ],
    )?;
    nonnegative(&receipt["resources"]["wall_seconds"])?;
    nonnegative(&receipt["resources"]["cpu_seconds"])?;
    integer(&receipt["resources"]["peak_rss_kib"], 1, 1 << 40)?;
    require(
        KNOWN_RESOURCE_PROFILES
            .iter()
            .any(|profile| receipt["resources"]["resource_profile"] == *profile)
            && receipt["artifacts"] == Value::Array(expected_worker_artifacts),
        "audit_worker_resource_or_inventory_contract",
    )?;
    require(receipt["validation"] == audit, "audit_receipt_disagrees")?;
    require(
        audit["immutable_run_verified"] == true
            && audit["numeric_reference_truth_used"] == false
            && audit["engineering_approved"] == false
            && audit["human_semantic_review_required"] == true
            && validation["identity_certified"] == false,
        "audit_truth_or_review_boundary",
    )?;
    require(
        audit["unresolved_semantics"]
            == json!([
                "contour identity",
                "caller calibration",
                "station correspondence",
                "symmetry",
                "terminal and upper closure",
                "current vessel condition"
            ])
            && audit["section_sampling"]
                == "first two, middle, last two; bounded sample, not exhaustive",
        "audit_semantics_or_sampling_contract",
    )?;
    let g = &audit["geometry_audit"];
    exact_keys(
        g,
        &[
            "source",
            "step_sha256",
            "step_units",
            "reported_units",
            "valid_shape",
            "solid_count",
            "shell_count",
            "closed_shell",
            "metrics",
            "relative_metric_error",
            "engineering_approved",
            "human_semantic_review_required",
        ],
    )?;
    require(
        g["source"] == "independently_reimported_exported_STEP"
            && g["step_sha256"] == c.binding.step_sha256
            && g["step_units"] == "mm"
            && g["reported_units"] == "m"
            && g["engineering_approved"] == false
            && g["human_semantic_review_required"] == true,
        "audit_step_identity_or_units",
    )?;
    let mut relative = 0f64;
    exact_keys(
        &g["metrics"],
        &["length_m", "beam_m", "depth_m", "volume_m3"],
    )?;
    for k in ["length_m", "beam_m", "depth_m", "volume_m3"] {
        let measured = nonnegative(&g["metrics"][k])?;
        let expected = nonnegative(&result["metrics"][k])?;
        require(measured > 0. && expected > 0., "nonpositive_geometry")?;
        relative = relative.max((measured - expected).abs() / expected.max(1e-12));
    }
    require(
        close(relative, nonnegative(&g["relative_metric_error"])?)
            && close(relative, c.measurements.relative_metric_error),
        "metric_measurement_contradiction",
    )?;
    let valid = g["valid_shape"]
        .as_bool()
        .ok_or("valid_shape_not_boolean")?;
    let closed = g["closed_shell"]
        .as_bool()
        .ok_or("closed_shell_not_boolean")?;
    let solids = integer(&g["solid_count"], 0, 20_000)?;
    let shells = integer(&g["shell_count"], 0, 20_000)?;
    let cad_pass = valid && closed && solids == 1 && shells == 1 && relative <= 1e-6;
    let all = result["sections"].as_array().ok_or("section_inventory")?;
    let n = all.len();
    require(
        n == c.sampling.total_section_count && n >= 3,
        "section_total_mismatch",
    )?;
    let indexes = BTreeSet::from([0, 1, n / 2, n - 2, n - 1]);
    let ids = indexes
        .iter()
        .map(|i| all[*i]["id"].as_str().unwrap_or("").to_string())
        .collect::<Vec<_>>();
    require(ids == c.sampling.section_ids, "section_sampling_mismatch")?;
    let expected_metrics = json!({"length_m":result["metrics"]["length_m"],"beam_m":result["metrics"]["beam_m"],"depth_m":result["metrics"]["depth_m"],"volume_m3":result["metrics"]["volume_m3"]});
    require(
        context["engine_metrics"] == expected_metrics,
        "context_metrics_not_current_run",
    )?;
    let mut info = serde_json::Map::new();
    for i in &indexes {
        let source = &all[*i];
        let id = source["id"].as_str().ok_or("section_id_type")?;
        info.insert(id.to_string(),json!({"x_m":source["x_m"],"sample_count":source["points_yz_m"].as_array().ok_or("source_points")?.len(),"pixels_per_metre":source["evidence"]["calibration"]["pixels_per_metre"]}));
    }
    require(
        context["section_info"] == Value::Object(info),
        "context_section_info_not_current_run",
    )?;
    let sections = audit["sampled_sections"]
        .as_array()
        .ok_or("sampled_sections_type")?;
    require(
        sections.len() == ids.len()
            && audit["sampled_section_count"].as_u64() == Some(ids.len() as u64)
            && audit["total_section_count"].as_u64() == Some(n as u64),
        "sampled_section_coverage",
    )?;
    let mut maximum = 0f64;
    for (s, i) in sections.iter().zip(indexes) {
        let source = &all[i];
        exact_keys(
            s,
            &[
                "section_id",
                "x_m",
                "sample_count",
                "distance_type",
                "rms_m",
                "p95_m",
                "max_m",
                "max_px",
                "source_measurement_uncertainty_m",
                "section_edges",
            ],
        )?;
        require(
            s["section_id"] == source["id"]
                && close(finite(&s["x_m"])?, finite(&source["x_m"])?)
                && s["sample_count"].as_u64()
                    == source["points_yz_m"].as_array().map(|a| a.len() as u64),
            "sampled_section_identity",
        )?;
        require(s["distance_type"]=="observed source-centre samples to actual STEP section boundary; no reference truth used","unknown_distance_contract")?;
        integer(&s["sample_count"], 2, 1025)?;
        integer(&s["section_edges"], 1, 8192)?;
        require(finite(&s["x_m"])? >= -1e6, "station_position_bound")?;
        if !s["source_measurement_uncertainty_m"].is_null() {
            nonnegative(&s["source_measurement_uncertainty_m"])?;
        }
        let m = nonnegative(&s["max_m"])?;
        maximum = maximum.max(m);
        require(
            nonnegative(&s["rms_m"])? <= m + 1e-12
                && nonnegative(&s["p95_m"])? <= m + 1e-12
                && close(
                    nonnegative(&s["max_px"])?,
                    m * finite(&source["evidence"]["calibration"]["pixels_per_metre"])?,
                ),
            "section_measurement_contradiction",
        )?;
    }
    let trace_pass = maximum <= 0.0011;
    let passed = cad_pass && trace_pass;
    require(
        close(maximum, c.measurements.max_section_distance_m)
            && (c.checks.cad_validity == Check::Passed) == cad_pass
            && (c.checks.trace_fidelity == Check::Passed) == trace_pass
            && (c.outcome == Check::Passed) == passed
            && audit["geometry_checks_passed"].as_bool() == Some(passed),
        "audit_conclusion_contradiction",
    )?;
    Ok(c)
}

pub fn ready(
    root: &Path,
    observation: &Value,
    domain: &Value,
    context: &Value,
) -> Result<Contract> {
    let c = assess(root, observation, domain, context)?;
    require(
        observation["ok"] == true
            && observation["status"] == "validated_review_required"
            && c.outcome == Check::Passed,
        "candidate_validation_failed",
    )?;
    Ok(c)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn golden() -> Value {
        serde_json::from_str(include_str!(
            "../../tests/fixtures/validation_contract/passed.json"
        ))
        .unwrap()
    }
    #[test]
    fn cross_language_golden_pass_and_fail() {
        for (raw, expected) in [
            (
                include_str!("../../tests/fixtures/validation_contract/passed.json"),
                Check::Passed,
            ),
            (
                include_str!("../../tests/fixtures/validation_contract/failed.json"),
                Check::Failed,
            ),
        ] {
            let c: Contract = util::parse(raw.as_bytes(), 262_144).unwrap();
            c.check_shape().unwrap();
            assert_eq!(c.outcome, expected);
        }
    }
    #[test]
    fn incomplete_unknown_boolean_and_contradictory_contracts_fail() {
        let original = golden();
        for key in original.as_object().unwrap().keys() {
            let mut x = original.clone();
            x.as_object_mut().unwrap().remove(key);
            assert!(
                serde_json::from_value::<Contract>(x).is_err(),
                "missing {key}"
            );
        }
        for (pointer, bad) in [
            ("/engineering_approved", json!(0)),
            ("/engineering_approved", json!(true)),
            ("/units/input", json!("mm")),
            ("/schema_version", json!("unknown")),
            ("/outcome", json!("failed")),
            ("/checks/trace_fidelity", json!(true)),
            ("/measurements/max_section_distance_m", json!(-1.)),
            ("/measurements/max_section_distance_m", json!(true)),
            ("/measurements/max_section_distance_m", json!(0.8)),
            ("/tolerances/max_section_distance_m", json!(0.5)),
            ("/sampling/total_section_count", json!(true)),
            ("/semantic_review", json!("approved")),
        ] {
            let mut x = original.clone();
            *x.pointer_mut(pointer).unwrap() = bad;
            assert!(
                serde_json::from_value::<Contract>(x)
                    .map(|c| c.check_shape().is_err())
                    .unwrap_or(true),
                "{pointer}"
            );
        }
        let mut x = original;
        x["extra"] = true.into();
        assert!(serde_json::from_value::<Contract>(x).is_err());
    }
}
