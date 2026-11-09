//! What the AI did in a draft, read-only: the source label of every section, the
//! warnings of the build, and the live model's activity from the event ledger.
//!
//! Nothing here can fail a task. Missing or unreadable files give empty results.
use crate::artifact::guard_inside_task;
use crate::files;
use crate::types::{ActivityStep, GuessKind, ModelActivity, SectionSource, SourceCount};
use marinaframe_control::util;
use serde_json::Value;
use std::collections::{BTreeSet, HashMap};
use std::path::Path;

#[cfg(test)]
mod tests;

/// Largest build record (`result.json`) read for labels and warnings.
const MAX_BUILD_RECORD_BYTES: usize = 8 * 1024 * 1024;
/// Largest event file read for the activity list.
const MAX_EVENT_BYTES: usize = 4 * 1024 * 1024;
/// Most warnings shown; a draft with more has a repeated problem.
const MAX_WARNINGS: usize = 40;
/// Most model steps listed.
const MAX_STEPS: usize = 400;
/// Label used when a draft section carries none (drafts older than W17b).
const DEFAULT_LABEL: &str = "traced";
/// Shown order of the labels in the summary.
const LABEL_ORDER: [&str; 7] = [
    "traced",
    "read",
    "repaired",
    "interpolated",
    "ai_inferred",
    "ai_corrected",
    "omitted",
];

/// Labels per section id, and the count per label.
pub struct DraftSources {
    pub by_section: HashMap<String, SectionSource>,
    pub counts: Vec<SourceCount>,
}

/// The `result.json` of the current build, only when that build is a draft.
pub fn build_record(task: &Path, build: &Value) -> Option<Value> {
    if build["draft"] != true {
        return None;
    }
    let file = guard_inside_task(task, &format!("{}/result.json", build["path"].as_str()?)).ok()?;
    let bytes = util::read_bounded(&file, MAX_BUILD_RECORD_BYTES).ok()?;
    serde_json::from_slice(&bytes).ok()
}

/// Source label of each built section. A section the loft spans (a bridged gap)
/// is `interpolated`, one beyond the draft's end is `omitted`.
pub fn draft_sources(record: &Value, open_guesses: &[(String, GuessKind)]) -> DraftSources {
    let mut by_section = HashMap::new();
    for section in record["sections"].as_array().into_iter().flatten() {
        let Some(id) = section["id"].as_str() else {
            continue;
        };
        let label = section["source_label"].as_str().unwrap_or(DEFAULT_LABEL);
        let basis = section["evidence"]["authored_basis"]
            .as_str()
            .map(String::from);
        by_section.insert(
            id.to_string(),
            SectionSource {
                label: label.into(),
                basis,
            },
        );
    }
    for (id, kind) in open_guesses {
        let label = match kind {
            GuessKind::BridgedGap => "interpolated",
            GuessKind::DroppedEnd => "omitted",
            _ => continue,
        };
        by_section.entry(id.clone()).or_insert(SectionSource {
            label: label.into(),
            basis: None,
        });
    }
    let counts = count_labels(&by_section);
    DraftSources { by_section, counts }
}

fn count_labels(by_section: &HashMap<String, SectionSource>) -> Vec<SourceCount> {
    let count_of = |label: &str| by_section.values().filter(|s| s.label == label).count();
    // A label that the worker adds later still counts, after the known ones.
    let unknown: BTreeSet<&str> = by_section
        .values()
        .map(|s| s.label.as_str())
        .filter(|l| !LABEL_ORDER.contains(l))
        .collect();
    LABEL_ORDER
        .iter()
        .copied()
        .chain(unknown)
        .map(|label| SourceCount {
            label: label.into(),
            count: count_of(label),
        })
        .filter(|c| c.count > 0)
        .collect()
}

/// Warnings of a draft build: build-level warnings (repairs, interpolation, fragmented
/// curves) and the fairing notes of model-written sections. Blocking gaps are not
/// listed here; the task status already says so.
pub fn draft_warnings(record: &Value, x_m: &HashMap<String, f64>) -> Vec<String> {
    let place = |id: Option<&str>| -> String {
        match id.and_then(|id| x_m.get(id)) {
            Some(x) => format!("At {x:.1} m: "),
            None => String::new(),
        }
    };
    let mut warnings: Vec<String> = vec![];
    for gap in record["gaps"].as_array().into_iter().flatten() {
        if gap["severity"] != "warning" {
            continue;
        }
        if let Some(message) = gap["message"].as_str() {
            warnings.push(format!("{}{message}", place(gap["section_id"].as_str())));
        }
    }
    for section in record["sections"].as_array().into_iter().flatten() {
        let ai = section["source_label"]
            .as_str()
            .is_some_and(|l| l.starts_with("ai_"));
        if !ai {
            continue;
        }
        for message in section["warnings"].as_array().into_iter().flatten() {
            if let Some(message) = message.as_str() {
                warnings.push(format!("{}{message}", place(section["id"].as_str())));
            }
        }
    }
    let mut seen = BTreeSet::new();
    warnings.retain(|w| seen.insert(w.clone()));
    warnings.truncate(MAX_WARNINGS);
    warnings
}

/// Live-model steps, request count, tokens and list cost from the event ledger.
/// None when the run never used the live model.
pub fn model_activity(task: &Path) -> Option<ModelActivity> {
    let mut activity = ModelActivity {
        steps: vec![],
        requests: 0,
        prompt_tokens: 0,
        completion_tokens: 0,
        list_cost_usd: 0.0,
        list_cost_complete: true,
    };
    for (sequence, path) in files::event_files(task) {
        let Ok(bytes) = util::read_bounded(&path, MAX_EVENT_BYTES) else {
            continue;
        };
        // Event files are compact JSON. Skip parsing events that cannot matter.
        let mentions = |needle: &[u8]| bytes.windows(needle.len()).any(|w| w == needle);
        if !mentions(b"\"kind\":\"decision\"") && !mentions(b"\"kind\":\"provider_") {
            continue;
        }
        let Ok(event) = serde_json::from_slice::<Value>(&bytes) else {
            continue;
        };
        let payload = &event["payload"];
        match event["kind"].as_str() {
            Some("decision") if payload["actor"] == "live_model" => {
                if let Some(tool) = payload["decision"]["tool"].as_str() {
                    if activity.steps.len() < MAX_STEPS {
                        activity.steps.push(ActivityStep {
                            sequence,
                            tool: tool.replace('_', " "),
                            reason: payload["decision"]["reason"].as_str().unwrap_or("").into(),
                        });
                    }
                }
            }
            Some("provider_result" | "provider_reconciled") => {
                let usage = &payload["receipt"]["usage"];
                activity.requests += 1;
                activity.prompt_tokens += usage["prompt_tokens"].as_u64().unwrap_or(0);
                activity.completion_tokens += usage["completion_tokens"].as_u64().unwrap_or(0);
                match usage["list_cost"].as_f64() {
                    Some(cost) => activity.list_cost_usd += cost,
                    None => activity.list_cost_complete = false,
                }
            }
            _ => {}
        }
    }
    (activity.requests > 0 || !activity.steps.is_empty()).then_some(activity)
}
