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

/// Audit contract of a single-solid run (`build_hull`).
const AUDIT_CONTRACT_V1: &str = "step_source_sections_v1";
/// Audit contract of a region run (`build_region_hull`, multi-piece stations):
/// a compound of solids, a per-solid audit and per-piece trace fidelity. The
/// tolerances and the sampling are those of v1.
const AUDIT_CONTRACT_REGIONS_V2: &str = "step_source_regions_v2";
const GEOMETRY_AUDIT_KEYS: [&str; 12] = [
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
];
const REGION_GEOMETRY_AUDIT_KEYS: [&str; 3] = [
    "expected_solid_count",
    "solids",
    "solid_volume_relative_error",
];
const SECTION_REPORT_KEYS: [&str; 10] = [
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
];
const CONTEXT_KEYS: [&str; 5] = [
    "binding",
    "evidence",
    "sampling",
    "section_info",
    "engine_metrics",
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
            || ![AUDIT_CONTRACT_V1, AUDIT_CONTRACT_REGIONS_V2]
                .contains(&self.audit_contract_version.as_str())
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
    // A region run's context adds "regions"; it is checked against the run below.
    let mut context_keys = CONTEXT_KEYS.to_vec();
    if context.get("regions").is_some() {
        context_keys.push("regions");
    }
    exact_keys(context, &context_keys)?;
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
    let region_run = result["metrics"].get("region_loft").is_some();
    require(
        c.audit_contract_version
            == if region_run {
                AUDIT_CONTRACT_REGIONS_V2
            } else {
                AUDIT_CONTRACT_V1
            }
            && context.get("regions").is_some() == region_run,
        "audit_contract_version_not_current_run",
    )?;
    let g = &audit["geometry_audit"];
    let mut geometry_keys = GEOMETRY_AUDIT_KEYS.to_vec();
    if region_run {
        geometry_keys.extend(REGION_GEOMETRY_AUDIT_KEYS);
    }
    exact_keys(g, &geometry_keys)?;
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
    let cad_pass = if region_run {
        region_cad_pass(g, &result, valid, closed, solids, shells, relative)?
    } else {
        valid && closed && solids == 1 && shells == 1 && relative <= 1e-6
    };
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
        info.insert(id.to_string(),json!({"x_m":source["x_m"],"sample_count":observed_sample_count(source)?,"pixels_per_metre":source["evidence"]["calibration"]["pixels_per_metre"]}));
    }
    if region_run {
        let mut pieces = serde_json::Map::new();
        for i in &indexes {
            let source = &all[*i];
            let id = source["id"].as_str().ok_or("section_id_type")?;
            pieces.insert(id.to_string(), json!(piece_sample_counts(source)?));
        }
        let mut volumes = result["metrics"]["region_loft"]["solid_volumes_m3"]
            .as_array()
            .ok_or("region_solid_volumes")?
            .iter()
            .map(finite)
            .collect::<Result<Vec<_>>>()?;
        volumes.sort_by(f64::total_cmp);
        require(
            context["regions"]
                == json!({"audit_contract_version":AUDIT_CONTRACT_REGIONS_V2,
                    "solid_count":result["metrics"]["solid_count"],
                    "solid_volumes_m3":volumes,"piece_sample_counts":pieces}),
            "context_regions_not_current_run",
        )?;
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
        let mut section_keys = SECTION_REPORT_KEYS.to_vec();
        if region_run {
            section_keys.push("pieces");
        }
        exact_keys(s, &section_keys)?;
        require(
            s["section_id"] == source["id"]
                && close(finite(&s["x_m"])?, finite(&source["x_m"])?)
                && s["sample_count"].as_u64() == Some(observed_sample_count(source)? as u64),
            "sampled_section_identity",
        )?;
        if region_run {
            check_piece_reports(s, &piece_sample_counts(source)?)?;
        }
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

/// All observed samples of a section: its curve, or every piece's curves.
fn observed_sample_count(source: &Value) -> Result<usize> {
    match source.get("points_yz_m") {
        Some(points) => Ok(points.as_array().ok_or("source_points")?.len()),
        None => Ok(piece_sample_counts(source)?.iter().sum()),
    }
}

/// Observed samples per piece of a multi-piece section; empty for a single curve.
fn piece_sample_counts(source: &Value) -> Result<Vec<usize>> {
    let Some(pieces) = source.get("pieces") else {
        return Ok(vec![]);
    };
    let mut counts = vec![];
    for piece in pieces.as_array().ok_or("source_pieces")? {
        let outer = piece["points_yz_m"]
            .as_array()
            .ok_or("source_piece_points")?
            .len();
        let inner = match piece.get("inner_points_yz_m") {
            Some(points) => points.as_array().ok_or("source_piece_points")?.len(),
            None => 0,
        };
        counts.push(outer + inner);
    }
    Ok(counts)
}

/// CAD validity of a region compound: the engine's solid count, each solid
/// valid and closed with one shell, and each reimported solid volume equal to
/// the engine's (sorted lists, relative 1e-6).
fn region_cad_pass(
    g: &Value,
    result: &Value,
    valid: bool,
    closed: bool,
    solids: u64,
    shells: u64,
    relative: f64,
) -> Result<bool> {
    let expected = integer(&g["expected_solid_count"], 1, 20_000)?;
    require(
        result["metrics"]["solid_count"].as_u64() == Some(expected),
        "audit_expected_solids_not_current_run",
    )?;
    let items = g["solids"].as_array().ok_or("solid_audit_type")?;
    require(items.len() as u64 == solids, "solid_audit_incomplete")?;
    let mut measured = vec![];
    let mut each_ok = true;
    let mut all_closed = true;
    for item in items {
        exact_keys(
            item,
            &["volume_m3", "valid_shape", "shell_count", "closed_shell"],
        )?;
        measured.push(nonnegative(&item["volume_m3"])?);
        let shell_count = integer(&item["shell_count"], 0, 20_000)?;
        let item_valid = item["valid_shape"]
            .as_bool()
            .ok_or("solid_valid_not_boolean")?;
        let item_closed = item["closed_shell"]
            .as_bool()
            .ok_or("solid_closed_not_boolean")?;
        each_ok &= item_valid && shell_count == 1;
        all_closed &= item_closed;
    }
    require(
        measured.windows(2).all(|w| w[0] <= w[1]) && all_closed == closed,
        "solid_audit_order_or_summary",
    )?;
    let mut engine = result["metrics"]["region_loft"]["solid_volumes_m3"]
        .as_array()
        .ok_or("region_solid_volumes")?
        .iter()
        .map(finite)
        .collect::<Result<Vec<_>>>()?;
    engine.sort_by(f64::total_cmp);
    let reported = nonnegative(&g["solid_volume_relative_error"])?;
    let same_count = engine.len() == measured.len();
    if same_count {
        let error = measured
            .iter()
            .zip(&engine)
            .map(|(a, b)| (a - b).abs() / b.max(1e-12))
            .fold(0f64, f64::max);
        require(close(error, reported), "solid_volume_error_contradiction")?;
    }
    Ok(valid
        && closed
        && solids == expected
        && shells == expected
        && each_ok
        && same_count
        && reported <= 1e-6
        && relative <= 1e-6)
}

/// Per-piece trace reports of one sampled section agree with its pieces and its maximum.
fn check_piece_reports(report: &Value, counts: &[usize]) -> Result<()> {
    let pieces = report["pieces"].as_array().ok_or("piece_reports_type")?;
    require(pieces.len() == counts.len(), "piece_reports_incomplete")?;
    let mut maximum = None::<f64>;
    for (index, (piece, count)) in pieces.iter().zip(counts).enumerate() {
        exact_keys(piece, &["piece", "sample_count", "max_m"])?;
        require(
            piece["piece"].as_u64() == Some(index as u64)
                && integer(&piece["sample_count"], 1, 1025)? == *count as u64,
            "piece_report_identity",
        )?;
        let m = nonnegative(&piece["max_m"])?;
        maximum = Some(maximum.map_or(m, |v| v.max(m)));
    }
    if let Some(m) = maximum {
        require(
            close(m, nonnegative(&report["max_m"])?),
            "piece_maxima_contradiction",
        )?;
    }
    Ok(())
}

// ------------------------------------------------------------ draft guesses
//
// A draft build takes the best-scoring candidate where a section is ambiguous
// and spans stations that have no readable line. Each such choice is an open
// guess in the domain checkpoint (`guesses`). Rust checks every guess against
// the inspected catalog and refuses review readiness while any guess is open.

const GUESS_KINDS: [&str; 5] = [
    "best_candidate",
    "bridged_gap",
    "dropped_end",
    "model_choice",
    // A section shape the model wrote (propose_section, see authoring.rs).
    "model_authored",
];
/// Source labels of a model-authored section.
const AUTHORED_LABELS: [&str; 2] = ["ai_inferred", "ai_corrected"];
/// Largest verifier evidence of one model choice (JSON bytes).
const MAX_VERIFIER_EVIDENCE_BYTES: usize = 4096;
/// Row coverage that the engine requires of a traced line.
const MIN_ROW_COVERAGE: f64 = 0.9;

/// A candidate traced from source ink: selectable, with the engine's row
/// coverage and a corridor, and (for a line the model traced) a passed
/// engine re-read in that corridor. Only such a candidate can be a model
/// choice; a model never supplies a line.
pub fn snapped_candidate(candidate: &Value) -> bool {
    candidate["selectable"] == true
        && candidate["source_support"]["observed_row_fraction"]
            .as_f64()
            .is_some_and(|f| f >= MIN_ROW_COVERAGE)
        && candidate["contour_selection"].is_object()
        && (candidate["model_traced"] != true || candidate["snap"]["passed"] == true)
}
const GUESS_FIELDS: [&str; 10] = [
    "guess_id",
    "section_id",
    "kind",
    "x_m",
    "x_range_m",
    "chosen_candidate_id",
    "alternatives",
    "score",
    "reason",
    "status",
];
const MAX_GUESSES: usize = 300;
const MAX_GUESS_REASON_CHARS: usize = 512;

/// The domain checkpoint (`domain/state.json`).
pub fn domain_checkpoint(root: &Path) -> Result<Value> {
    util::read_json(
        &util::safe_file(root, "domain/state.json")?,
        32 * 1024 * 1024,
    )
}

/// Open guesses of a domain checkpoint. Tasks from before drafts have none.
pub fn open_guesses(checkpoint: &Value) -> Result<&[Value]> {
    match checkpoint.get("guesses") {
        None | Some(Value::Null) => Ok(&[]),
        Some(Value::Array(guesses)) if guesses.len() <= MAX_GUESSES => Ok(guesses),
        _ => Err("draft_guess_contract".into()),
    }
}

/// Identity part of the open guesses (section id -> chosen candidate id or
/// null). The domain generation id includes it while any guess is open.
pub fn guessed_choices(checkpoint: &Value) -> Result<Option<Value>> {
    let guesses = open_guesses(checkpoint)?;
    if guesses.is_empty() {
        return Ok(None);
    }
    let mut choices = serde_json::Map::new();
    for guess in guesses {
        let section = guess["section_id"].as_str().ok_or("draft_guess_contract")?;
        choices.insert(section.into(), guess["chosen_candidate_id"].clone());
    }
    Ok(Some(Value::Object(choices)))
}

fn guess_shape(guess: &Value, selected: &serde_json::Map<String, Value>) -> Result<()> {
    if guess["kind"] == "model_choice" || guess["kind"] == "model_authored" {
        // A model choice (or model-authored section) also carries the verifier's evidence, which must say
        // that the deterministic checks passed.
        let mut fields = GUESS_FIELDS.to_vec();
        fields.push("verifier_evidence");
        exact_keys(guess, &fields).map_err(|_| "draft_guess_contract")?;
        let evidence = &guess["verifier_evidence"];
        require(
            evidence.is_object()
                && evidence["passed"] == true
                && evidence["verifier"].is_string()
                && evidence["identity_certified"] == false
                && util::json_bytes(evidence).is_ok_and(|b| b.len() <= MAX_VERIFIER_EVIDENCE_BYTES),
            "draft_guess_contract",
        )?;
    } else {
        exact_keys(guess, &GUESS_FIELDS).map_err(|_| "draft_guess_contract")?;
    }
    let section = guess["section_id"]
        .as_str()
        .filter(|s| util::valid_section_id(s))
        .ok_or("draft_guess_contract")?;
    let reason_chars = guess["reason"].as_str().map_or(0, |r| r.chars().count());
    let x = guess["x_m"].as_f64().filter(|x| x.is_finite());
    let range = match &guess["x_range_m"] {
        Value::Null => None,
        Value::Array(pair) if pair.len() == 2 => {
            let low = pair[0].as_f64().filter(|v| v.is_finite());
            let high = pair[1].as_f64().filter(|v| v.is_finite());
            match (low, high) {
                (Some(low), Some(high)) if low <= high => Some((low, high)),
                _ => return Err("draft_guess_contract".into()),
            }
        }
        _ => return Err("draft_guess_contract".into()),
    };
    require(
        guess["status"] == "open"
            && GUESS_KINDS.iter().any(|k| guess["kind"] == *k)
            && guess["guess_id"]
                .as_str()
                .is_some_and(|id| id.starts_with("guess-") && util::valid_id(id, 64))
            && x.is_some()
            && (1..=MAX_GUESS_REASON_CHARS).contains(&reason_chars)
            && guess["alternatives"]
                .as_array()
                .is_some_and(|a| a.iter().all(Value::is_string))
            && !selected.contains_key(section),
        "draft_guess_contract",
    )?;
    let x = x.unwrap_or_default();
    let shape_ok = match guess["kind"].as_str() {
        Some("best_candidate" | "model_choice") => {
            guess["chosen_candidate_id"].is_string()
                && guess["score"]
                    .as_f64()
                    .is_some_and(|s| (0.0..=1.0).contains(&s))
                && range.is_none()
        }
        Some("model_authored") => {
            guess["chosen_candidate_id"].is_string() && guess["score"].is_null() && range.is_none()
        }
        Some(kind) => {
            let no_choice = guess["chosen_candidate_id"].is_null()
                && guess["score"].is_null()
                && guess["alternatives"].as_array().is_some_and(Vec::is_empty);
            let range_ok = match (kind, range) {
                ("bridged_gap", Some((low, high))) => low < x && x < high,
                ("dropped_end", None) => true,
                ("dropped_end", Some((low, high))) => low <= x && x <= high,
                _ => false,
            };
            no_choice && range_ok
        }
        None => false,
    };
    require(shape_ok, "draft_guess_contract")
}

/// Check the open guesses of a domain checkpoint against its own inspected
/// catalog and against the worker's domain description. Returns the number of
/// open guesses. A guess cannot name a candidate that was not inspected, hide
/// a readable line behind a "bridged" claim, or share a section with a
/// selection; the description must list exactly the checkpoint's guesses.
pub fn check_guess_contract(checkpoint: &Value, description: &Value) -> Result<usize> {
    let guesses = open_guesses(checkpoint)?;
    let described: &[Value] = match description.get("open_guesses") {
        None | Some(Value::Null) => &[],
        Some(Value::Array(list)) => list,
        _ => return Err("draft_guess_description_mismatch".into()),
    };
    require(described == guesses, "draft_guess_description_mismatch")?;
    let empty = serde_json::Map::new();
    let selected = match checkpoint.get("selected") {
        None if guesses.is_empty() => &empty,
        value => value
            .and_then(Value::as_object)
            .ok_or("draft_guess_contract")?,
    };
    let mut sections = BTreeSet::new();
    for guess in guesses {
        guess_shape(guess, selected)?;
        let section = guess["section_id"].as_str().unwrap_or_default();
        require(sections.insert(section), "draft_guess_contract")?;
        let candidates = checkpoint["catalog"][section]["candidates"]
            .as_array()
            .ok_or("draft_guess_not_in_catalog")?;
        let inspected = candidates
            .iter()
            .filter_map(|c| c["candidate_id"].as_str())
            .collect::<BTreeSet<_>>();
        let selectable = candidates
            .iter()
            .filter(|c| c["selectable"] == true)
            .filter_map(|c| c["candidate_id"].as_str())
            .collect::<BTreeSet<_>>();
        let alternatives = guess["alternatives"]
            .as_array()
            .ok_or("draft_guess_contract")?;
        let consistent = match guess["chosen_candidate_id"].as_str() {
            Some(chosen) => {
                selectable.contains(chosen)
                    && alternatives
                        .iter()
                        .all(|a| a != chosen && a.as_str().is_some_and(|a| inspected.contains(a)))
            }
            // A section with a selectable inspected line cannot be declared
            // unreadable. Traced lines enter a draft only as model choices.
            None => candidates
                .iter()
                .all(|c| c["selectable"] != true || c["model_traced"] == true),
        };
        let fitted_row = checkpoint["vessel_table"]["stations"]
            .as_array()
            .is_some_and(|rows| {
                rows.iter()
                    .any(|row| row["id"] == section && row["source"] == "fitted")
            });
        require(
            consistent || (guess["chosen_candidate_id"].is_null() && fitted_row),
            "draft_guess_not_in_catalog",
        )?;
        if guess["kind"] == "best_candidate" {
            // A traced line is never a best-score guess; only a station claim
            // (model_choice) can carry it into a draft.
            let chosen = candidates
                .iter()
                .find(|c| c["candidate_id"] == guess["chosen_candidate_id"]);
            require(
                chosen.is_some_and(|c| c["model_traced"] != true),
                "draft_guess_not_in_catalog",
            )?;
        }
        if guess["kind"] == "model_choice" {
            // The model's choice must be ink the engine re-read, never a line
            // the model wrote.
            let chosen = candidates
                .iter()
                .find(|c| c["candidate_id"] == guess["chosen_candidate_id"]);
            require(
                chosen.is_some_and(snapped_candidate),
                "draft_guess_not_snapped_to_ink",
            )?;
        }
        if guess["kind"] == "model_authored" {
            // A model-authored section names the model's own curve, with its
            // source label; it never poses as traced ink.
            let chosen = candidates
                .iter()
                .find(|c| c["candidate_id"] == guess["chosen_candidate_id"]);
            require(
                chosen.is_some_and(|c| {
                    c["model_traced"] == true
                        && AUTHORED_LABELS
                            .iter()
                            .any(|label| c["authored"]["source_label"] == *label)
                }),
                "draft_guess_not_model_authored",
            )?;
        }
    }
    Ok(guesses.len())
}

/// A draft is never review-ready. This runs before every other readiness
/// check, so its refusal does not depend on any later check.
fn refuse_draft(root: &Path, domain: &Value) -> Result<()> {
    require(
        open_guesses(&domain_checkpoint(root)?)?.is_empty(),
        "draft_guesses_open",
    )?;
    let candidate = &domain["current_candidate"];
    require(
        candidate.get("draft").is_none_or(|draft| *draft == false),
        "draft_candidate_not_verifiable",
    )?;
    // A missing or unreadable run record is not judged here: `assess` refuses
    // it with its own code after the manifest check.
    let record = candidate["path"]
        .as_str()
        .and_then(|run| util::safe_file(root, &format!("{run}/result.json")).ok())
        .and_then(|path| util::read_json(&path, 32 * 1024 * 1024).ok());
    if let Some(result) = record {
        require(result.get("draft").is_none(), "draft_build_not_verifiable")?;
    }
    Ok(())
}

/// Finalization predicate. `audit_pin` is the audit implementation identity the
/// controller pinned from the initialize receipt; the contract must carry exactly
/// that value. Without a pin nothing finalizes (fail closed). A draft (open
/// guesses, a draft candidate or a draft run record) never passes.
pub fn ready(
    root: &Path,
    observation: &Value,
    domain: &Value,
    context: &Value,
    audit_pin: Option<&str>,
) -> Result<Contract> {
    refuse_draft(root, domain)?;
    let c = assess(root, observation, domain, context)?;
    let pin = audit_pin.ok_or("audit_implementation_unpinned")?;
    require(
        c.binding.audit_implementation_sha256 == pin,
        "audit_implementation_mismatch",
    )?;
    review_outcome(observation, c)
}

/// Re-check a task that was finalized before the audit pin existed. It applies
/// every `ready` check except the pin, which such a task never recorded. Only
/// `Store::verify` and the offline `check-validation` diagnostic may call it;
/// the controller finish path must call `ready`.
pub fn ready_legacy_unpinned(
    root: &Path,
    observation: &Value,
    domain: &Value,
    context: &Value,
) -> Result<Contract> {
    refuse_draft(root, domain)?;
    review_outcome(observation, assess(root, observation, domain, context)?)
}

fn review_outcome(observation: &Value, c: Contract) -> Result<Contract> {
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

    /// A consistent draft checkpoint: s0 has two lines (one guessed), s1 is
    /// selected, s2 has no readable line (bridged between s1 and s3).
    fn draft_checkpoint() -> Value {
        json!({
            "selected": {"s1": "c-s1", "s3": "c-s3"},
            "catalog": {
                "s0": {"candidates": [
                    {"candidate_id": "c-outer", "selectable": true},
                    {"candidate_id": "c-inner", "selectable": true}]},
                "s1": {"candidates": [{"candidate_id": "c-s1", "selectable": true}]},
                "s2": {"candidates": []},
                "s3": {"candidates": [{"candidate_id": "c-s3", "selectable": true}]}},
            "guesses": [
                {"guess_id": "guess-0123456789abcdef0123", "section_id": "s0", "kind": "best_candidate",
                 "x_m": 0.0, "x_range_m": null, "chosen_candidate_id": "c-outer",
                 "alternatives": ["c-inner"], "score": 0.93,
                 "reason": "2 lines found; took the best-supported one (score 0.93).", "status": "open"},
                {"guess_id": "guess-fedcba9876543210fedc", "section_id": "s2", "kind": "bridged_gap",
                 "x_m": 4.0, "x_range_m": [2.0, 6.0], "chosen_candidate_id": null,
                 "alternatives": [], "score": null,
                 "reason": "No readable line at x=4 m; smoothed across x=2 to 6 m.", "status": "open"}]
        })
    }

    fn described(checkpoint: &Value) -> Value {
        json!({"open_guesses": checkpoint["guesses"]})
    }

    #[test]
    fn guess_contract_accepts_a_consistent_draft_and_old_tasks() {
        let checkpoint = draft_checkpoint();
        assert_eq!(
            check_guess_contract(&checkpoint, &described(&checkpoint)),
            Ok(2)
        );
        assert_eq!(
            guessed_choices(&checkpoint).unwrap(),
            Some(json!({"s0": "c-outer", "s2": null}))
        );
        // A task from before drafts: no guesses, no description field.
        let old = json!({"selected": {}, "catalog": {}});
        assert_eq!(check_guess_contract(&old, &json!({})), Ok(0));
        assert_eq!(guessed_choices(&old).unwrap(), None);
    }

    #[test]
    fn forged_or_edited_guess_lists_are_rejected() {
        type Forgery = (&'static str, fn(&mut Value), &'static str);
        let forgeries: [Forgery; 16] = [
            (
                "unknown chosen candidate",
                |c| c["guesses"][0]["chosen_candidate_id"] = json!("c-forged"),
                "draft_guess_not_in_catalog",
            ),
            (
                "unknown alternative",
                |c| c["guesses"][0]["alternatives"] = json!(["c-forged"]),
                "draft_guess_not_in_catalog",
            ),
            (
                "readable line hidden as bridge",
                |c| {
                    c["catalog"]["s2"]["candidates"] =
                        json!([{"candidate_id": "c-s2", "selectable": true}])
                },
                "draft_guess_not_in_catalog",
            ),
            (
                "uninspected section",
                |c| {
                    c["catalog"].as_object_mut().unwrap().remove("s2");
                },
                "draft_guess_not_in_catalog",
            ),
            (
                "guessed and selected",
                |c| c["selected"]["s0"] = json!("c-outer"),
                "draft_guess_contract",
            ),
            (
                "duplicate section",
                |c| {
                    let g = c["guesses"][0].clone();
                    c["guesses"].as_array_mut().unwrap().push(g);
                },
                "draft_guess_contract",
            ),
            (
                "unknown kind",
                |c| c["guesses"][0]["kind"] = json!("verified"),
                "draft_guess_contract",
            ),
            (
                "resolved status",
                |c| c["guesses"][0]["status"] = json!("resolved"),
                "draft_guess_contract",
            ),
            (
                "score above one",
                |c| c["guesses"][0]["score"] = json!(1.5),
                "draft_guess_contract",
            ),
            (
                "score as text",
                |c| c["guesses"][0]["score"] = json!("0.9"),
                "draft_guess_contract",
            ),
            (
                "bridge outside its range",
                |c| c["guesses"][1]["x_range_m"] = json!([5.0, 6.0]),
                "draft_guess_contract",
            ),
            (
                "bridge with a choice",
                |c| c["guesses"][1]["chosen_candidate_id"] = json!("c-s1"),
                "draft_guess_contract",
            ),
            (
                "empty reason",
                |c| c["guesses"][0]["reason"] = json!(""),
                "draft_guess_contract",
            ),
            (
                "missing field",
                |c| {
                    c["guesses"][0].as_object_mut().unwrap().remove("reason");
                },
                "draft_guess_contract",
            ),
            (
                "extra field",
                |c| c["guesses"][0]["verified"] = json!(true),
                "draft_guess_contract",
            ),
            (
                "guess list not a list",
                |c| c["guesses"] = json!({"s0": "c-outer"}),
                "draft_guess_contract",
            ),
        ];
        for (name, forge, code) in forgeries {
            let mut checkpoint = draft_checkpoint();
            forge(&mut checkpoint);
            // The description mirrors the forged checkpoint, so only the
            // contract itself can reject the forgery.
            let description = described(&checkpoint);
            assert_eq!(
                check_guess_contract(&checkpoint, &description).unwrap_err(),
                code,
                "{name}"
            );
        }
    }

    #[test]
    fn description_must_list_exactly_the_checkpoint_guesses() {
        let checkpoint = draft_checkpoint();
        for description in [
            json!({}),
            json!({"open_guesses": []}),
            json!({"open_guesses": [checkpoint["guesses"][0]]}),
            json!({"open_guesses": "none"}),
        ] {
            assert_eq!(
                check_guess_contract(&checkpoint, &description).unwrap_err(),
                "draft_guess_description_mismatch"
            );
        }
        let mut edited = described(&checkpoint);
        edited["open_guesses"][0]["reason"] = json!("Confirmed by a person.");
        assert_eq!(
            check_guess_contract(&checkpoint, &edited).unwrap_err(),
            "draft_guess_description_mismatch"
        );
    }

    /// The s0 guess of `draft_checkpoint` as a model choice of a traced line.
    fn model_choice_checkpoint() -> Value {
        let mut checkpoint = draft_checkpoint();
        checkpoint["catalog"]["s0"]["candidates"]
            .as_array_mut()
            .unwrap()
            .push(
                json!({"candidate_id":"trace-s0","selectable":true,"model_traced":true,
                "source_support":{"observed_row_fraction":0.97},
                "contour_selection":{"anchors_px":[[10.0,0.0],[12.0,100.0]],"half_width_px":2.75},
                "snap":{"verifier":"engine_reread_in_tight_corridor_v1","passed":true}}),
            );
        let guess = &mut checkpoint["guesses"][0];
        guess["kind"] = json!("model_choice");
        guess["chosen_candidate_id"] = json!("trace-s0");
        guess["alternatives"] = json!(["c-outer", "c-inner"]);
        guess["reason"] = json!("Label 0 is written at the end of this curve.");
        guess["verifier_evidence"] = json!({"verifier":"station_assignment_v1","passed":true,
            "checks":["candidate_traced_from_ink_and_selectable"],"identity_certified":false});
        checkpoint
    }

    #[test]
    fn a_model_choice_must_be_snapped_ink_with_passed_evidence() {
        let checkpoint = model_choice_checkpoint();
        assert_eq!(
            check_guess_contract(&checkpoint, &described(&checkpoint)).unwrap(),
            2
        );
        let unsnapped: [fn(&mut Value); 4] = [
            |c| c["catalog"]["s0"]["candidates"][2]["snap"]["passed"] = json!(false),
            |c| {
                c["catalog"]["s0"]["candidates"][2]["source_support"]["observed_row_fraction"] =
                    json!(0.5)
            },
            |c| {
                c["catalog"]["s0"]["candidates"][2]
                    .as_object_mut()
                    .unwrap()
                    .remove("contour_selection");
            },
            |c| c["catalog"]["s0"]["candidates"][2]["snap"] = json!(null),
        ];
        for forge in unsnapped {
            let mut checkpoint = model_choice_checkpoint();
            forge(&mut checkpoint);
            assert_eq!(
                check_guess_contract(&checkpoint, &described(&checkpoint)).unwrap_err(),
                "draft_guess_not_snapped_to_ink"
            );
        }
        let bad_evidence: [fn(&mut Value); 6] = [
            |g| g["verifier_evidence"]["passed"] = json!(false),
            |g| g["verifier_evidence"]["identity_certified"] = json!(true),
            |g| {
                g.as_object_mut().unwrap().remove("verifier_evidence");
            },
            |g| g["verifier_evidence"] = json!("passed"),
            |g| g["verifier_evidence"]["padding"] = json!("x".repeat(5000)),
            |g| g["engineering_approved"] = json!(true),
        ];
        for forge in bad_evidence {
            let mut checkpoint = model_choice_checkpoint();
            forge(&mut checkpoint["guesses"][0]);
            assert_eq!(
                check_guess_contract(&checkpoint, &described(&checkpoint)).unwrap_err(),
                "draft_guess_contract"
            );
        }
        // A traced line is never a best-score guess.
        let mut checkpoint = model_choice_checkpoint();
        let guess = checkpoint["guesses"][0].as_object_mut().unwrap();
        guess.remove("verifier_evidence");
        guess.insert("kind".into(), json!("best_candidate"));
        assert_eq!(
            check_guess_contract(&checkpoint, &described(&checkpoint)).unwrap_err(),
            "draft_guess_not_in_catalog"
        );
        // Verifier evidence belongs to model choices only.
        let mut checkpoint = draft_checkpoint();
        checkpoint["guesses"][0]["verifier_evidence"] =
            json!({"verifier":"x","passed":true,"identity_certified":false});
        assert_eq!(
            check_guess_contract(&checkpoint, &described(&checkpoint)).unwrap_err(),
            "draft_guess_contract"
        );
    }

    /// The s0 guess of `draft_checkpoint` as a section shape the model wrote.
    fn model_authored_checkpoint() -> Value {
        let mut checkpoint = draft_checkpoint();
        checkpoint["catalog"]["s0"]["candidates"]
            .as_array_mut()
            .unwrap()
            .push(
                json!({"candidate_id":"authored-s0","selectable":true,"model_traced":true,
                "authored":{"source_label":"ai_inferred","basis":"Blend of s1 and s2."}}),
            );
        let guess = &mut checkpoint["guesses"][0];
        guess["kind"] = json!("model_authored");
        guess["chosen_candidate_id"] = json!("authored-s0");
        guess["alternatives"] = json!(["c-outer", "c-inner"]);
        guess["score"] = json!(null);
        guess["reason"] = json!("ai_inferred: Blend of s1 and s2.");
        guess["verifier_evidence"] = json!({"verifier":"section_authoring_checks_v1","passed":true,
            "identity_certified":false,"source_label":"ai_inferred"});
        checkpoint
    }

    #[test]
    fn a_model_authored_guess_names_the_models_labelled_curve() {
        let checkpoint = model_authored_checkpoint();
        assert_eq!(
            check_guess_contract(&checkpoint, &described(&checkpoint)).unwrap(),
            2
        );
        type Forge = (fn(&mut Value), &'static str);
        let forged: [Forge; 4] = [
            (
                |c| {
                    c["catalog"]["s0"]["candidates"][2]["authored"]["source_label"] =
                        json!("traced")
                },
                "draft_guess_not_model_authored",
            ),
            (
                |c| c["guesses"][0]["chosen_candidate_id"] = json!("c-outer"),
                "draft_guess_not_in_catalog",
            ),
            (
                |c| c["guesses"][0]["score"] = json!(0.9),
                "draft_guess_contract",
            ),
            (
                |c| {
                    c["guesses"][0]
                        .as_object_mut()
                        .unwrap()
                        .remove("verifier_evidence");
                },
                "draft_guess_contract",
            ),
        ];
        for (forge, code) in forged {
            let mut checkpoint = model_authored_checkpoint();
            forge(&mut checkpoint);
            assert_eq!(
                check_guess_contract(&checkpoint, &described(&checkpoint)).unwrap_err(),
                code
            );
        }
    }
}
