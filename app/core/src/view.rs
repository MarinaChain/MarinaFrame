//! Builds `TaskSummary` and `TaskView` from a task folder, without the controller lock.
//! The labels and polylines follow `src/vessel_reconstruction/rust_review.py`.
use crate::draft_view;
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

/// Open guesses as `(section id, kind)`, for sections the draft did not build.
fn open_ids(open: &[SectionGuess]) -> Vec<(String, GuessKind)> {
    open.iter()
        .map(|g| (g.section_id.clone(), g.view.kind))
        .collect()
}

fn section_stations(sections: &[SectionView]) -> HashMap<String, f64> {
    sections.iter().map(|s| (s.id.clone(), s.x_m)).collect()
}

/// What the view needs besides the task folder.
#[derive(Clone, Debug, Default)]
pub struct ViewContext {
    pub dismissed_notices: BTreeSet<String>,
    /// Hash of the running app binary. The controller refuses to continue a run
    /// that another binary started, so the view says so.
    pub binary_sha256: Option<String>,
    /// Plain-language failure of the last background action on this task.
    pub action_error: Option<String>,
    /// The person's review of whole-vessel parts in this task: component id -> decision.
    pub part_reviews: std::collections::HashMap<String, crate::parts::PartReview>,
    /// A person's sign-off of this task's parts, if any.
    pub sign_off: Option<SignOffView>,
}

pub fn map_status(controller_status: &str) -> Status {
    match controller_status {
        "ready" | "running" => Status::Running,
        "stalled" => Status::Stalled,
        "awaiting_human_review" => Status::NeedsReview,
        "draft_not_verified" => Status::Draft,
        "abstained" => Status::Declined,
        "validation_failed" | "provider_failed" => Status::Failed,
        "cancelled" => Status::Cancelled,
        "paused" | "interrupted" => Status::Paused,
        _ => Status::Blocked, // blocked, no_progress and anything new
    }
}

/// Longest run name shown; a longer vessel_id is not a usable label.
const MAX_NAME_CHARS: usize = 80;

/// Prefix of the blinded vessel_id that the benchmark factory writes
/// (`benchmarks/factory/generate.py`: "factory-" + 12 hex digits of a hash).
const FACTORY_ID_PREFIX: &str = "factory-";
/// Hex digits of a blinded factory id shown in its label.
const FACTORY_LABEL_HEX: usize = 6;

/// A usable label: trimmed, not empty, not too long.
fn usable_name(text: &str) -> Option<String> {
    let trimmed = text.trim();
    (!trimmed.is_empty() && trimmed.chars().count() <= MAX_NAME_CHARS).then(|| trimmed.to_string())
}

/// "factory-70ed8f4700b0" -> "Benchmark hull 70ed8f". The factory hides the case
/// name on purpose, so the label keeps the hash but reads as a name.
fn factory_label(vessel_id: &str) -> Option<String> {
    let hash = vessel_id.strip_prefix(FACTORY_ID_PREFIX)?;
    let is_hash = hash.len() >= FACTORY_LABEL_HEX && hash.chars().all(|c| c.is_ascii_hexdigit());
    is_hash.then(|| format!("Benchmark hull {}", &hash[..FACTORY_LABEL_HEX]))
}

/// Run name, first found of: the vessel name typed at intake; a label for a
/// blinded benchmark id; the vessel_id of the captured spec; the task folder name.
fn run_name(folder: &Path) -> String {
    let typed = files::read_intake_record(folder).and_then(|record| {
        record["particulars"]["vessel_name"]
            .as_str()
            .and_then(usable_name)
    });
    let vessel_id = || {
        files::read_captured_spec(folder)
            .and_then(|spec| spec["vessel_id"].as_str().and_then(usable_name))
            .map(|id| factory_label(&id).unwrap_or(id))
    };
    typed
        .or_else(vessel_id)
        .or_else(|| {
            folder
                .file_name()
                .and_then(|s| s.to_str())
                .map(String::from)
        })
        .unwrap_or_else(|| "run".into())
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
        name: run_name(task),
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
    let open = open_guesses(&state, domain.as_ref());
    let draft = draft_view(&state, domain.as_ref(), summary.status, &open);
    let mut sections = section_views(task, domain.as_ref(), summary.status, &open);
    let validation = current_validation(&state, domain.as_ref());
    let current_build = current_build(&state, domain.as_ref());
    let record = current_build.and_then(|build| draft_view::build_record(task, build));
    let draft_sources = record
        .as_ref()
        .map(|r| draft_view::draft_sources(r, &open_ids(&open)));
    if let Some(sources) = &draft_sources {
        for section in &mut sections {
            section.source = sources.by_section.get(&section.id).cloned();
        }
    }
    // Every build (draft or not) says where it read each section.
    let mut section_records = current_build
        .and_then(|build| draft_view::result_record(task, build))
        .map(|r| crate::source_record::section_records(&r))
        .unwrap_or_default();
    for section in &mut sections {
        section.source_record = section_records.remove(&section.id);
    }
    Ok(TaskView {
        sheet_review: crate::sheet_review::read(task),
        source_counts: draft_sources
            .as_ref()
            .map(|s| s.counts.clone())
            .unwrap_or_default(),
        warnings: record
            .as_ref()
            .map(|r| draft_view::draft_warnings(r, &section_stations(&sections)))
            .unwrap_or_default(),
        activity: draft_view::model_activity(task),
        revision: state["revision_id"].as_str().map(String::from),
        source_page: source_page(task, domain.as_ref()),
        model: current_build.and_then(|build| model_view(task, build)),
        checks: check_views(validation),
        provider: crate::provider_view::provider_calls(task),
        notices: notices(&summary, &state, context, draft.as_ref()),
        evidence: evidence(&state, validation, task),
        components: crate::parts::read_components(task, &context.part_reviews),
        sign_off: context.sign_off.clone(),
        whole_vessel_model: crate::parts::whole_vessel_model(task),
        capacity_plan: crate::run_tables::read_capacity_plan(task),
        tank_model: crate::run_tables::tank_model_path(task).is_some(),
        structure_files: crate::run_tables::structure_files(task),
        steel_records: crate::run_tables::steel_records(task),
        body_plan_check: crate::body_plan_check::read(task, &context.part_reviews),
        draft,
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

/// Largest build record read for its export names.
const MAX_BUILD_RECORD_BYTES: usize = 8 * 1024 * 1024;
/// STL name of a verified build. A draft build names its file in `exports.stl`.
const VERIFIED_STL_NAME: &str = "model.stl";

/// STL file name from the build's `result.json` (`exports.stl`). Only a plain
/// file name is used; anything else falls back to the verified name.
fn stl_file_name(task: &Path, folder: &str) -> String {
    let record = format!("{folder}/result.json");
    let name = crate::artifact::guard_inside_task(task, &record)
        .ok()
        .and_then(|file| util::read_bounded(&file, MAX_BUILD_RECORD_BYTES).ok())
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
        .and_then(|result| result["exports"]["stl"].as_str().map(String::from));
    match name {
        Some(name) if !name.is_empty() && name != ".." && !name.contains(['/', '\\']) => name,
        _ => VERIFIED_STL_NAME.into(),
    }
}

// ---- drafts ----

/// An open guess and the section it belongs to.
struct SectionGuess {
    section_id: String,
    view: GuessView,
}

fn parse_guess(value: &Value) -> Option<SectionGuess> {
    let kind = match value["kind"].as_str()? {
        "best_candidate" => GuessKind::BestCandidate,
        "bridged_gap" => GuessKind::BridgedGap,
        "dropped_end" => GuessKind::DroppedEnd,
        "model_choice" => GuessKind::ModelChoice,
        "model_authored" => GuessKind::ModelAuthored,
        _ => return None,
    };
    let x_range_m = value["x_range_m"]
        .as_array()
        .and_then(|r| Some([r.first()?.as_f64()?, r.get(1)?.as_f64()?]));
    Some(SectionGuess {
        section_id: value["section_id"].as_str()?.into(),
        view: GuessView {
            id: value["guess_id"].as_str()?.into(),
            kind,
            x_range_m,
            chosen_candidate_id: value["chosen_candidate_id"].as_str().map(String::from),
            alternatives: value["alternatives"]
                .as_array()
                .map(|list| {
                    list.iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default(),
            score: value["score"].as_f64(),
            reason: value["reason"].as_str().unwrap_or("").into(),
        },
    })
}

/// Open guesses: the controller state's list, else the domain checkpoint's.
fn open_guesses(state: &Value, domain: Option<&Value>) -> Vec<SectionGuess> {
    let list = state["domain"]["open_guesses"]
        .as_array()
        .or_else(|| domain.and_then(|d| d["guesses"].as_array()));
    list.map(|list| list.iter().filter_map(parse_guess).collect())
        .unwrap_or_default()
}

fn resolved_guesses(state: &Value, domain: Option<&Value>) -> Vec<ResolvedGuessView> {
    let list = state["domain"]["resolved_guesses"]
        .as_array()
        .or_else(|| domain.and_then(|d| d["resolved_guesses"].as_array()));
    list.map(|list| {
        list.iter()
            .filter_map(|value| {
                let guess = parse_guess(value)?.view;
                let resolution = match value["resolution"].as_str()? {
                    "confirmed" => Resolution::Confirmed,
                    "replaced" => Resolution::Replaced,
                    _ => return None,
                };
                Some(ResolvedGuessView {
                    guess,
                    resolution,
                    resolved_candidate_id: value["resolved_candidate_id"].as_str()?.into(),
                })
            })
            .collect()
    })
    .unwrap_or_default()
}

fn draft_view(
    state: &Value,
    domain: Option<&Value>,
    status: Status,
    open: &[SectionGuess],
) -> Option<DraftView> {
    if status != Status::Draft {
        return None;
    }
    Some(DraftView {
        status: "draft_not_verified".into(),
        guesses: open.iter().map(|g| g.view.clone()).collect(),
        resolved: resolved_guesses(state, domain),
    })
}

/// Banner for a draft: how many guesses remain and what to do next.
fn draft_notice(draft: &DraftView) -> NoticeView {
    let open = draft.guesses.len();
    let stuck = draft
        .guesses
        .iter()
        .filter(|g| matches!(g.kind, GuessKind::BridgedGap | GuessKind::DroppedEnd))
        .count();
    let pickable = open - stuck;
    let text = if open == 0 {
        "Draft: not verified. The app cannot confirm this model.".to_string()
    } else if stuck == 0 {
        format!(
            "Draft: {} to check. Confirm each guessed line or pick another. The app then rebuilds and checks the model.",
            plural(open, "guess", "guesses")
        )
    } else if pickable == 0 {
        format!(
            "Draft: {} to check. No line could be read there, so there is nothing to pick and this run stays a draft.",
            plural(open, "guess", "guesses")
        )
    } else {
        let has = |n: usize| if n == 1 { "has" } else { "have" };
        format!(
            "Draft: {} to check. {pickable} {} a line to confirm or change. {stuck} {} no readable line, so this run stays a draft.",
            plural(open, "guess", "guesses"),
            has(pickable),
            has(stuck)
        )
    };
    NoticeView {
        // The count is in the id, so the banner returns when the count changes.
        id: format!("draft-guesses:{open}"),
        tone: Tone::Warning,
        text,
    }
}

fn plural(count: usize, one: &str, many: &str) -> String {
    format!("{count} {}", if count == 1 { one } else { many })
}

fn model_view(task: &Path, build: &Value) -> Option<ModelView> {
    let folder = build["path"].as_str()?;
    let stl_path = format!("{folder}/{}", stl_file_name(task, folder));
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

/// The drawing page the run read, as input to the worker (drawing pixels).
const INPUT_PAGE: &str = "domain/input/source.png";

/// The page image of the drawing pane. `width` and `height` are in drawing pixels, the
/// units of section boxes and lines: a recorded page that is a scaled render of the input
/// page (large scans are rendered at most 3000 px wide) keeps its image, and the UI draws it
/// at the input page's size.
fn source_page(task: &Path, domain: Option<&Value>) -> Option<SourcePage> {
    let recorded = domain
        .and_then(|d| d["inspection_artifacts"].as_array())
        .and_then(|list| list.iter().rev().find(|a| a["kind"] == "source_page"))
        .and_then(|a| a["path"].as_str());
    let input_size = crate::artifact::guard_artifact_path(task, INPUT_PAGE)
        .ok()
        .and_then(|_| files::png_size(&task.join(INPUT_PAGE)));
    [recorded, Some(INPUT_PAGE)]
        .into_iter()
        .flatten()
        .find_map(|path| {
            crate::artifact::guard_artifact_path(task, path).ok()?;
            let image_size = files::png_size(&task.join(path))?;
            let (width, height) = match input_size {
                Some(input) if is_scaled_copy(image_size, input) => input,
                _ => image_size,
            };
            Some(SourcePage {
                path: path.into(),
                width,
                height,
            })
        })
}

/// True when an image of `small` pixels is `large` scaled down evenly (the same shape, within
/// one pixel of rounding on each side).
fn is_scaled_copy(small: (u32, u32), large: (u32, u32)) -> bool {
    let (small_w, small_h) = (f64::from(small.0), f64::from(small.1));
    let (large_w, large_h) = (f64::from(large.0), f64::from(large.1));
    if small_w <= 0.0 || small_h <= 0.0 || large_w <= small_w {
        return false;
    }
    let scale = small_w / large_w;
    (large_h * scale - small_h).abs() <= 1.0
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
pub(crate) fn section_polylines(task: &Path, domain: &Value, section_id: &str) -> Arc<Polylines> {
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

fn section_views(
    task: &Path,
    domain: Option<&Value>,
    status: Status,
    open: &[SectionGuess],
) -> Vec<SectionView> {
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
                    guess: None,
                    source: None,
                    candidates: vec![],
                    source_record: None,
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
            let guess = open
                .iter()
                .find(|g| g.section_id == id)
                .map(|g| g.view.clone());
            // A guessed line is in the draft but not confirmed. It is marked chosen
            // so the drawing shows it; the section state says it is a guess.
            let chosen_id = guess
                .as_ref()
                .and_then(|g| g.chosen_candidate_id.as_deref())
                .or_else(|| domain["selected"][&id].as_str());
            let candidates = candidate_views(task, domain, &id, chosen_id);
            let (section_state, reason) = if let Some(guess) = &guess {
                (SectionState::Guessed, guess.reason.clone())
            } else if let Some(chosen) = candidates.iter().find(|c| c.chosen) {
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
                guess,
                source: None,
                candidates,
                source_record: None,
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

fn notices(
    summary: &TaskSummary,
    state: &Value,
    context: &ViewContext,
    draft: Option<&DraftView>,
) -> Vec<NoticeView> {
    let mut all = vec![NoticeView {
        id: ENGINEERING_NOTICE_ID.into(),
        tone: Tone::Info,
        text: "Engineering approval is never automatic. A person has to review a model before anyone relies on it.".into(),
    }];
    if let Some(draft) = draft {
        all.push(draft_notice(draft));
    }
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
