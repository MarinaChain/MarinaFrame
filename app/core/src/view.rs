//! Builds `TaskSummary` and `TaskView` from a task folder, without the controller lock.
//! The labels and polylines follow `src/vessel_reconstruction/rust_review.py`.
use crate::events::plain_reason;
use crate::files;
use crate::types::*;
use marinaframe_control::util;
use serde_json::{json, Value};
use std::collections::{BTreeSet, HashMap};
use std::path::Path;
use std::sync::{Arc, Mutex, OnceLock};

/// Longest polyline sent to the UI. Longer traces keep their first and last point.
const MAX_POLYLINE_POINTS: usize = 150;
pub const ENGINEERING_NOTICE_ID: &str = "engineering-approval";

#[cfg(test)]
mod tests;

/// What the view needs besides the task folder.
#[derive(Clone, Debug, Default)]
pub struct ViewContext {
    pub dismissed_notices: BTreeSet<String>,
    /// Hash of the running app binary. The controller refuses to continue a run
    /// that another binary started, so the view says so.
    pub binary_sha256: Option<String>,
    /// Plain-language failure of the last background action on this task.
    pub action_error: Option<String>,
}

pub fn map_status(controller_status: &str) -> Status {
    match controller_status {
        "ready" | "running" => Status::Running,
        "awaiting_human_review" => Status::NeedsReview,
        "abstained" => Status::Declined,
        "validation_failed" | "provider_failed" => Status::Failed,
        "cancelled" => Status::Cancelled,
        "paused" | "interrupted" => Status::Paused,
        _ => Status::Blocked, // blocked, no_progress and anything new
    }
}

fn spec_name(state: &Value, folder: &Path) -> String {
    let spec = Path::new(state["config"]["source_spec"].as_str().unwrap_or(""));
    let stem = spec.file_stem().and_then(|s| s.to_str()).unwrap_or("");
    let name = if stem == "spec" || stem.is_empty() {
        spec.parent()
            .and_then(|p| p.file_name())
            .and_then(|s| s.to_str())
    } else {
        Some(stem)
    };
    name.or_else(|| folder.file_name().and_then(|s| s.to_str()))
        .unwrap_or("run")
        .to_string()
}

fn summarize(task: &Path, state: &Value, domain: Option<&Value>) -> TaskSummary {
    let sections = domain
        .and_then(|d| d["sections"].as_array().map(Vec::len))
        .or_else(|| {
            state["domain"]["section_count"]
                .as_u64()
                .map(|n| n as usize)
        })
        .unwrap_or(0);
    TaskSummary {
        task: task.to_string_lossy().into_owned(),
        name: spec_name(state, task),
        status: map_status(state["status"].as_str().unwrap_or("")),
        policy: state["config"]["policy"]
            .as_str()
            .unwrap_or("deterministic")
            .into(),
        updated_ms: files::modified_ms(&task.join("state.json")),
        sections,
    }
}

/// Task folders directly inside the runs folder, newest first.
pub fn list_tasks(runs_folder: &Path) -> Vec<TaskSummary> {
    let Ok(entries) = std::fs::read_dir(runs_folder) else {
        return vec![];
    };
    let mut tasks: Vec<TaskSummary> = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            std::fs::symlink_metadata(path).is_ok_and(|m| m.is_dir() && !m.file_type().is_symlink())
        })
        .filter_map(|path| {
            let state = files::read_state(&path)?;
            Some(summarize(&path, &state, None))
        })
        .collect();
    tasks.sort_by(|a, b| b.updated_ms.cmp(&a.updated_ms).then(a.task.cmp(&b.task)));
    tasks
}

pub fn get_task(task: &Path, context: &ViewContext) -> Result<TaskView, String> {
    let state = files::read_state(task).ok_or("task_missing")?;
    let domain = files::read_domain(task);
    let summary = summarize(task, &state, domain.as_ref());
    let sections = section_views(task, domain.as_ref(), summary.status);
    let validation = current_validation(&state, domain.as_ref());
    let current_build = current_build(&state, domain.as_ref());
    Ok(TaskView {
        revision: state["revision_id"].as_str().map(String::from),
        source_page: source_page(task, domain.as_ref()),
        model: current_build.and_then(|build| model_view(task, build)),
        checks: check_views(validation),
        provider: crate::provider_view::provider_calls(task),
        notices: notices(&summary, &state, context),
        evidence: evidence(&state, validation, task),
        sections,
        summary,
    })
}

fn current_validation<'a>(state: &Value, domain: Option<&'a Value>) -> Option<&'a Value> {
    let validation = domain?.get("validation").filter(|v| v.is_object())?;
    let same = |key: &str| validation[key] == state[key];
    (same("generation_id") && same("revision_id")).then_some(validation)
}

fn current_build<'a>(state: &'a Value, domain: Option<&'a Value>) -> Option<&'a Value> {
    let candidate = &state["domain"]["current_candidate"];
    if candidate["valid"] == true {
        return Some(candidate);
    }
    let last_valid = domain
        .map(|d| &d["last_valid_candidate"])
        .filter(|v| v.is_object());
    last_valid.or_else(|| Some(&state["domain"]["last_valid_candidate"]).filter(|v| v.is_object()))
}

fn model_view(task: &Path, build: &Value) -> Option<ModelView> {
    let folder = build["path"].as_str()?;
    let stl_path = format!("{folder}/model.stl");
    // Only offer a model whose file is a regular file inside the task.
    crate::artifact::guard_artifact_path(task, &stl_path).ok()?;
    let metrics = &build["metrics"];
    Some(ModelView {
        stl_path,
        length_m: metrics["length_m"].as_f64()?,
        beam_m: metrics["beam_m"].as_f64()?,
        depth_m: metrics["depth_m"].as_f64()?,
        volume_m3: metrics["volume_m3"].as_f64(),
    })
}

fn source_page(task: &Path, domain: Option<&Value>) -> Option<SourcePage> {
    let recorded = domain
        .and_then(|d| d["inspection_artifacts"].as_array())
        .and_then(|list| list.iter().rev().find(|a| a["kind"] == "source_page"))
        .and_then(|a| a["path"].as_str());
    [recorded, Some("domain/input/source.png")]
        .into_iter()
        .flatten()
        .find_map(|path| {
            crate::artifact::guard_artifact_path(task, path).ok()?;
            let (width, height) = files::png_size(&task.join(path))?;
            Some(SourcePage {
                path: path.into(),
                width,
                height,
            })
        })
}

// ---- sections and candidates ----

type Polylines = HashMap<String, Vec<[f64; 2]>>;

fn polyline_cache() -> &'static Mutex<HashMap<String, Arc<Polylines>>> {
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<Polylines>>>> = OnceLock::new();
    CACHE.get_or_init(Default::default)
}

fn downsample(points: &[[f64; 2]]) -> Vec<[f64; 2]> {
    if points.len() <= MAX_POLYLINE_POINTS {
        return points.to_vec();
    }
    let step = (points.len() - 1) as f64 / (MAX_POLYLINE_POINTS - 1) as f64;
    (0..MAX_POLYLINE_POINTS)
        .map(|i| points[((i as f64 * step).round() as usize).min(points.len() - 1)])
        .collect()
}

fn point_list(value: &Value) -> Vec<[f64; 2]> {
    value
        .as_array()
        .map(|list| {
            list.iter()
                .filter_map(|p| Some([p.get(0)?.as_f64()?, p.get(1)?.as_f64()?]))
                .collect()
        })
        .unwrap_or_default()
}

/// Candidate traces of one section from its evidence file (`source_points_px`).
/// The file is used only when its hash matches the hash the worker recorded.
fn section_polylines(task: &Path, domain: &Value, section_id: &str) -> Arc<Polylines> {
    let record = domain["inspection_artifacts"].as_array().and_then(|list| {
        list.iter()
            .rev()
            .find(|a| a["kind"] == "source_candidate_evidence" && a["section_id"] == section_id)
    });
    let Some((path, sha)) = record.and_then(|a| Some((a["path"].as_str()?, a["sha256"].as_str()?)))
    else {
        return Arc::default();
    };
    let Ok(file) = crate::artifact::guard_inside_task(task, path) else {
        return Arc::default();
    };
    if util::file_hash(&file).ok().as_deref() != Some(sha) {
        return Arc::default();
    }
    let key = format!("{}#{sha}", file.display());
    if let Some(hit) = polyline_cache()
        .lock()
        .ok()
        .and_then(|c| c.get(&key).cloned())
    {
        return hit;
    }
    let parsed: Polylines = util::read_bounded(&file, 8 * 1024 * 1024)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
        .and_then(|doc| {
            Some(
                doc["candidates"]
                    .as_array()?
                    .iter()
                    .filter_map(|c| {
                        Some((
                            c["candidate_id"].as_str()?.to_string(),
                            downsample(&point_list(&c["source_points_px"])),
                        ))
                    })
                    .collect(),
            )
        })
        .unwrap_or_default();
    let parsed = Arc::new(parsed);
    if let Ok(mut cache) = polyline_cache().lock() {
        if cache.len() > 2048 {
            cache.clear();
        }
        cache.insert(key, parsed.clone());
    }
    parsed
}

fn candidate_label(candidate: &Value, index: usize) -> String {
    match candidate["hypothesis"].as_str() {
        Some("grid_supported_contour_hypothesis") => "Main hull line".into(),
        Some("retained_alternative_source_continuity") => format!("Other line {}", index),
        _ => format!("Line {}", index + 1),
    }
}

fn candidate_why(candidate: &Value) -> String {
    let support = &candidate["source_support"];
    let mut parts: Vec<String> = vec![];
    if let Some(fraction) = support["observed_row_fraction"].as_f64() {
        parts.push(format!(
            "Traced across {:.0}% of the section height",
            fraction * 100.0
        ));
    }
    if candidate["grid_supported_hypothesis"] == true {
        parts.push("follows the drawing grid".into());
    }
    match candidate["non_grid_competing_components"].as_u64() {
        Some(0) | None => {}
        Some(n) => parts.push(format!(
            "{n} other strong stroke{} compete{}",
            if n == 1 { "" } else { "s" },
            if n == 1 { "s" } else { "" }
        )),
    }
    if candidate["selectable"] != true {
        parts.push("cannot be chosen".into());
    }
    let mut text = parts.join("; ");
    if let Some(first) = text.get(..1) {
        text = first.to_uppercase() + &text[1..];
    }
    if text.is_empty() {
        text = "No detail recorded".into();
    }
    text + "."
}

fn candidate_views(
    task: &Path,
    domain: &Value,
    section_id: &str,
    chosen_id: Option<&str>,
) -> Vec<CandidateView> {
    let Some(candidates) = domain["catalog"][section_id]["candidates"].as_array() else {
        return vec![];
    };
    let polylines = section_polylines(task, domain, section_id);
    candidates
        .iter()
        .enumerate()
        .filter_map(|(index, c)| {
            let id = c["candidate_id"].as_str()?;
            let polyline = polylines
                .get(id)
                .filter(|p| !p.is_empty())
                .cloned()
                // Without the evidence file, the two anchors still show where the line runs.
                .unwrap_or_else(|| point_list(&c["contour_selection"]["anchors_px"]));
            Some(CandidateView {
                id: id.into(),
                label: candidate_label(c, index),
                chosen: chosen_id == Some(id),
                selectable: c["selectable"] == true,
                why: candidate_why(c),
                polyline_px: polyline,
            })
        })
        .collect()
}

fn roi(value: &Value) -> [i64; 4] {
    let get = |i: usize| value.get(i).and_then(Value::as_i64).unwrap_or(0);
    [get(0), get(1), get(2), get(3)]
}

fn section_views(task: &Path, domain: Option<&Value>, status: Status) -> Vec<SectionView> {
    let spec = files::read_captured_spec(task);
    let declared: Vec<Value> = spec
        .as_ref()
        .and_then(|s| s["sections"].as_array().cloned())
        .unwrap_or_default();
    let Some(domain) = domain else {
        return declared
            .iter()
            .filter_map(|s| {
                Some(SectionView {
                    id: s["id"].as_str()?.into(),
                    x_m: s["x_m"].as_f64().unwrap_or(0.0),
                    roi_px: roi(&s["roi_px"]),
                    state: SectionState::NotRead,
                    reason: "Not read yet.".into(),
                    candidates: vec![],
                })
            })
            .collect();
    };
    // Prefer the declared list (all sections); fall back to the inspected catalog.
    let mut entries: Vec<(String, f64, [i64; 4])> = declared
        .iter()
        .filter_map(|s| {
            Some((
                s["id"].as_str()?.to_string(),
                s["x_m"].as_f64().unwrap_or(0.0),
                roi(&s["roi_px"]),
            ))
        })
        .collect();
    if entries.is_empty() {
        if let Some(catalog) = domain["catalog"].as_object() {
            entries = catalog
                .iter()
                .map(|(id, e)| {
                    (
                        id.clone(),
                        e["x_m"].as_f64().unwrap_or(0.0),
                        roi(&e["roi_px"]),
                    )
                })
                .collect();
        }
    }
    entries.sort_by(|a, b| a.1.total_cmp(&b.1).then(a.0.cmp(&b.0)));
    let finished_without_pick =
        matches!(status, Status::Declined | Status::Blocked | Status::Failed);
    entries
        .into_iter()
        .map(|(id, x_m, roi_px)| {
            let chosen_id = domain["selected"][&id].as_str();
            let candidates = candidate_views(task, domain, &id, chosen_id);
            let (section_state, reason) = if let Some(chosen) = candidates.iter().find(|c| c.chosen)
            {
                (
                    SectionState::Chosen,
                    format!("Picked the {}.", chosen.label.to_lowercase()),
                )
            } else if candidates.is_empty() {
                (SectionState::NotRead, "Not read yet.".into())
            } else if finished_without_pick {
                (SectionState::Declined, declined_reason(&candidates))
            } else {
                (SectionState::NotRead, "Read, no line picked yet.".into())
            };
            SectionView {
                id,
                x_m,
                roi_px,
                state: section_state,
                reason,
                candidates,
            }
        })
        .collect()
}

fn declined_reason(candidates: &[CandidateView]) -> String {
    match candidates.len() {
        0 | 1 => "Declined: no line was clear enough.".into(),
        2 => "Declined: two lines fit equally well.".into(),
        n => format!("Declined: {n} lines fit about equally well."),
    }
}

// ---- checks ----

fn millimetres(metres: Option<f64>) -> Option<String> {
    metres.map(|m| format!("{:.2} mm", m * 1000.0))
}

fn check_result(outcome: &str) -> CheckResult {
    match outcome {
        "passed" | "succeeded" => CheckResult::Pass,
        "failed" => CheckResult::Fail,
        _ => CheckResult::NotRun,
    }
}

fn check_views(validation: Option<&Value>) -> Vec<CheckView> {
    let contract = validation.map(|v| &v["contract"]).filter(|c| c.is_object());
    let Some(contract) = contract else {
        return vec![CheckView {
            name: "Checked against the drawing".into(),
            value: "Not run yet".into(),
            limit: None,
            result: CheckResult::NotRun,
        }];
    };
    let checks = &contract["checks"];
    let outcome = |key: &str| checks[key].as_str().unwrap_or("not run");
    let measured = &contract["measurements"];
    let tolerance = &contract["tolerances"];
    let distance = measured["max_section_distance_m"].as_f64();
    let relative = measured["relative_metric_error"].as_f64();
    let relative_limit = tolerance["max_relative_metric_error"].as_f64();
    vec![
        CheckView {
            name: "Validation ran".into(),
            value: outcome("worker_execution").into(),
            limit: None,
            result: check_result(outcome("worker_execution")),
        },
        CheckView {
            name: "Files match their records".into(),
            value: outcome("artifact_integrity").into(),
            limit: None,
            result: check_result(outcome("artifact_integrity")),
        },
        CheckView {
            name: "3D solid is valid".into(),
            value: outcome("cad_validity").into(),
            limit: None,
            result: check_result(outcome("cad_validity")),
        },
        CheckView {
            name: "Trace fidelity".into(),
            value: millimetres(distance).unwrap_or_else(|| outcome("trace_fidelity").into()),
            limit: millimetres(tolerance["max_section_distance_m"].as_f64()),
            result: check_result(outcome("trace_fidelity")),
        },
        CheckView {
            name: "Volume after STEP re-import".into(),
            value: relative
                .map(|r| format!("{r:.1e}"))
                .unwrap_or_else(|| "not run".into()),
            limit: relative_limit.map(|l| format!("{l:.0e}")),
            result: match (relative, relative_limit) {
                (Some(r), Some(l)) if r <= l => CheckResult::Pass,
                (Some(_), Some(_)) => CheckResult::Fail,
                _ => CheckResult::NotRun,
            },
        },
    ]
}

// ---- notices and evidence ----

fn notices(summary: &TaskSummary, state: &Value, context: &ViewContext) -> Vec<NoticeView> {
    let mut all = vec![NoticeView {
        id: ENGINEERING_NOTICE_ID.into(),
        tone: Tone::Info,
        text: "Engineering approval is never automatic. A person has to review a model before anyone relies on it.".into(),
    }];
    if matches!(summary.status, Status::Failed | Status::Blocked) {
        if let Some(reason) = state["termination_reason"].as_str() {
            all.push(NoticeView {
                id: format!("stopped:{reason}"),
                tone: Tone::Warning,
                text: format!("Stopped: {}.", plain_reason(reason)),
            });
        }
    }
    let other_build = context.binary_sha256.as_deref().is_some_and(|mine| {
        state["config"]["binary_sha256"]
            .as_str()
            .is_some_and(|theirs| theirs != mine)
    });
    if other_build && summary.status != Status::Running {
        all.push(NoticeView {
            id: "other-build".into(),
            tone: Tone::Info,
            text: "A different build of MarinaFrame made this run, so it can be viewed here but not continued or changed.".into(),
        });
    }
    if let Some(message) = &context.action_error {
        all.push(NoticeView {
            id: "action-failed".into(),
            tone: Tone::Warning,
            text: message.clone(),
        });
    }
    all.retain(|n| !context.dismissed_notices.contains(&n.id));
    all
}

fn evidence(state: &Value, validation: Option<&Value>, task: &Path) -> Value {
    json!({
        "task_id": state["task_id"],
        "head_sha256": files::read_head(task),
        "generation_id": state["generation_id"],
        "revision_id": state["revision_id"],
        "controller_status": state["status"],
        "termination_reason": state["termination_reason"],
        "model": state["config"]["model"],
        "controller_binary_sha256": state["config"]["binary_sha256"],
        "source_manifest_sha256": state["source_manifest_sha256"],
        "domain_checkpoint_sha256": state["domain_checkpoint_sha256"],
        "worker_implementation_sha256": state["worker_implementation_sha256"],
        "audit_implementation_sha256": state["audit_implementation_sha256"],
        "counters": state["counters"],
        "validation_contract": validation.map(|v| v["contract"].clone()).unwrap_or(Value::Null),
        "engineering_approved": false,
    })
}
