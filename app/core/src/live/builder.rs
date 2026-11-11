//! Turns ledger events into live steps, one event at a time.
//!
//! Event order in a live run: `provider_intent`, `provider_result`, `decision`,
//! `worker_intent`, `worker_result`. The decision opens a step; the worker result
//! fills its tool card, marks and build. Harness operations (initialize, survey,
//! first hull) have no decision; their worker intent opens a code step.
use super::geometry::{self, BoxPx, Calibration, Point, SectionGeometry, ViewFrame};
use super::*;
use crate::events::plain_reason;
use marinaframe_control::util;
use serde::Deserialize;
use serde_json::Value;
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::Arc;
use std::time::Instant;

/// Largest event file read. Event files are 10 to 200 KB.
const MAX_EVENT_BYTES: usize = 4 * 1024 * 1024;
/// Longest narration line and longest notes, in characters.
const MAX_TEXT_CHARS: usize = 400;
const MAX_NOTES_CHARS: usize = 2000;
/// Most images listed per step.
const MAX_IMAGES: usize = 4;
/// Most target chips per step.
const MAX_TARGETS: usize = 12;
/// A decision equal to one of this many recent model steps is a repeat.
const REPEAT_WINDOW: usize = 3;
/// Half size of the attention box around a model click, in sheet pixels.
const CLICK_BOX_HALF_PX: f64 = 150.0;
/// Space around a corridor in its attention box, in sheet pixels.
const CORRIDOR_PAD_PX: f64 = 40.0;

/// Only the fields the live view needs. `serde` skips the large `state_after`
/// (the controller state) except its status.
#[derive(Deserialize)]
struct LedgerEvent {
    #[serde(default)]
    kind: String,
    #[serde(default)]
    time_ms: u64,
    #[serde(default)]
    payload: Value,
    #[serde(default)]
    state_after: Option<StateAfter>,
}

#[derive(Deserialize, Default)]
struct StateAfter {
    #[serde(default)]
    status: Option<String>,
}

/// The model's answer that the next decision step quotes.
struct ModelAnswer {
    model_ms: u64,
    cost_usd: Option<f64>,
}

/// The step that waits for a worker result.
struct OpenWork {
    step: usize,
    operation: String,
    arguments: Value,
    started_ms: Option<u64>,
}

pub(crate) struct TaskLive {
    read_through: u64,
    started_ms: Option<u64>,
    newest_ms: u64,
    steps: Vec<LiveStep>,
    /// Decision event sequence -> step index (repeats map to the repeated step).
    decision_steps: HashMap<u64, usize>,
    /// Recent model steps as (tool and arguments, step index), newest last.
    recent: VecDeque<(String, usize)>,
    /// Repeated step index -> its `repeat_collapsed` step index.
    repeat_steps: HashMap<usize, usize>,
    open_work: Option<OpenWork>,
    model_since_ms: Option<u64>,
    model_answer: Option<ModelAnswer>,
    finished: bool,
    views: HashMap<String, ViewFrame>,
    sections: HashMap<String, SectionGeometry>,
    /// Revision id -> build path.
    revisions: HashMap<String, String>,
    build_curves: HashMap<String, Arc<Vec<SectionCurve>>>,
    /// Builds whose curves an earlier step already carried.
    curves_sent: HashSet<String>,
    domain: Option<((u64, u64), Arc<Value>)>,
    last_used: Instant,
}

impl TaskLive {
    pub(crate) fn new(task: &Path) -> Self {
        let mut live = TaskLive {
            read_through: 0,
            started_ms: None,
            newest_ms: 0,
            steps: vec![],
            decision_steps: HashMap::new(),
            recent: VecDeque::new(),
            repeat_steps: HashMap::new(),
            open_work: None,
            model_since_ms: None,
            model_answer: None,
            finished: false,
            views: HashMap::new(),
            sections: HashMap::new(),
            revisions: HashMap::new(),
            build_curves: HashMap::new(),
            curves_sent: HashSet::new(),
            domain: None,
            last_used: Instant::now(),
        };
        // The captured spec places every section before any worker result does.
        if let Some(spec) = files::read_captured_spec(task) {
            for section in spec["sections"].as_array().into_iter().flatten() {
                live.learn_section(section);
            }
        }
        live
    }

    pub(crate) fn last_used(&self) -> Instant {
        self.last_used
    }

    pub(crate) fn build_path(&self, revision: &str) -> Option<String> {
        self.revisions.get(revision).cloned().or_else(|| {
            self.revisions
                .values()
                .find(|path| path.as_str() == revision)
                .cloned()
        })
    }

    /// Parse the event files newer than the last call.
    pub(crate) fn refresh(&mut self, task: &Path) {
        self.last_used = Instant::now();
        let listed = files::event_files(task);
        let newest = listed.last().map_or(0, |(sequence, _)| *sequence);
        if newest < self.read_through {
            // The ledger was replaced (a new run in the same folder): start again.
            *self = TaskLive::new(task);
        }
        for (sequence, path) in listed {
            if sequence <= self.read_through {
                continue;
            }
            // The controller writes each event file atomically; an unreadable one
            // is skipped rather than retried forever.
            let event = util::read_bounded(&path, MAX_EVENT_BYTES)
                .ok()
                .and_then(|bytes| serde_json::from_slice::<LedgerEvent>(&bytes).ok());
            if let Some(event) = event {
                self.apply(task, sequence, event);
            }
            self.read_through = sequence;
        }
    }

    pub(crate) fn snapshot(&self, after_sequence: u64) -> LiveSteps {
        let started = self.started_ms.unwrap_or(0);
        let in_flight = match (&self.open_work, self.model_since_ms) {
            (
                Some(OpenWork {
                    operation,
                    started_ms: Some(since),
                    ..
                }),
                _,
            ) => Some(InFlight {
                kind: InFlightKind::Worker,
                operation: Some(operation.clone()),
                since_ms: since.saturating_sub(started),
                progress: None,
                stalled: false,
            }),
            (_, Some(since)) => Some(InFlight {
                kind: InFlightKind::Model,
                operation: None,
                since_ms: since.saturating_sub(started),
                progress: None,
                stalled: false,
            }),
            _ => None,
        };
        LiveSteps {
            steps: self
                .steps
                .iter()
                .filter(|step| step.last_sequence > after_sequence)
                .cloned()
                .collect(),
            last_sequence: self.read_through,
            started_ms: started,
            elapsed_ms: self.newest_ms.saturating_sub(started),
            in_flight,
            finished: self.finished,
        }
    }

    fn relative(&self, time_ms: u64) -> u64 {
        time_ms.saturating_sub(self.started_ms.unwrap_or(time_ms))
    }

    fn apply(&mut self, task: &Path, sequence: u64, event: LedgerEvent) {
        let time = event.time_ms;
        self.started_ms.get_or_insert(time);
        self.newest_ms = self.newest_ms.max(time);
        let payload = &event.payload;
        match event.kind.as_str() {
            "task_created" => self.push_system(sequence, time, "Run started", "The run started."),
            "provider_intent" => self.model_since_ms = Some(time),
            "provider_result" | "provider_reconciled" => {
                let since = self.model_since_ms.take().unwrap_or(time);
                self.model_answer = Some(ModelAnswer {
                    model_ms: time.saturating_sub(since),
                    cost_usd: payload["receipt"]["usage"]["list_cost"].as_f64(),
                });
            }
            "provider_not_sent" | "provider_outcome_unknown" => {
                self.model_since_ms = None;
                self.push_system(
                    sequence,
                    time,
                    "Model request failed",
                    "The model request ended without an answer.",
                );
            }
            "decision" => {
                self.close_unrun("Not run");
                self.on_decision(sequence, time, payload);
            }
            "missing_sections_hint" => {
                let count = payload["section_ids"].as_array().map_or(0, Vec::len);
                self.close_unrun(&format!(
                    "Not run: {count} section{} have no line yet",
                    if count == 1 { "" } else { "s" }
                ));
            }
            "worker_intent" => self.on_worker_intent(sequence, time, payload),
            "worker_result" => self.on_worker_result(task, sequence, time, payload),
            "repeated_action_refused" => self.on_repeat_refused(sequence, time, payload),
            "operation_rejected" => self.on_operation_rejected(sequence, time, payload),
            "model_output_rejected" => {
                self.model_answer = None;
                self.push_system(
                    sequence,
                    time,
                    "Answer not usable",
                    "The model's answer did not follow the tool rules, so it was asked again.",
                );
            }
            "context_compacted" => self.push_system(
                sequence,
                time,
                "Notes shortened",
                "Older steps were summarised to keep the model's context small.",
            ),
            "finalization_rejected" => {
                self.push_step(StepBase {
                    kind: StepKind::Refused,
                    title: "Not ready to finish".into(),
                    text: "The model has not looked at the current views.".into(),
                    ..StepBase::system(sequence, time)
                });
            }
            "candidate_ready_for_human_review" => {
                self.finished = true;
                self.push_step(StepBase {
                    kind: StepKind::Finish,
                    title: "Ready for review".into(),
                    text: "The model is ready for a person to review.".into(),
                    ..StepBase::system(sequence, time)
                });
            }
            "task_terminated" => {
                let status = event.state_after.and_then(|s| s.status);
                self.on_terminated(sequence, time, payload, status.as_deref());
            }
            "task_resumed" => {
                self.finished = false;
                self.push_system(sequence, time, "Resumed", "The run continues.");
            }
            "operator_revision_requested" => self.on_revision_requested(sequence, time, payload),
            "operator_revision_result" => self.on_revision_result(sequence, time, payload),
            "operator_revision_forced" => self.on_revision_forced(sequence, time, payload),
            _ => {}
        }
    }

    // ---- decisions ----

    fn on_decision(&mut self, sequence: u64, time: u64, payload: &Value) {
        let decision = &payload["decision"];
        let Some(tool) = decision["tool"].as_str() else {
            return;
        };
        let arguments = decision["arguments"].clone();
        let actor = match payload["actor"].as_str() {
            Some("live_model") => Actor::Model,
            Some("human_operator" | "assistant_operator") => Actor::Person,
            _ => Actor::Code,
        };
        let answer = self.model_answer.take();
        let reason = decision["reason"]
            .as_str()
            .map(|r| plain_text(r, MAX_TEXT_CHARS));
        // The controller's progress key changes when the run made progress, so the
        // same call after progress is not a repeat.
        let signature = format!("{tool}:{arguments}:{}", payload["progress_key"]);
        if actor == Actor::Model {
            let repeated = self
                .recent
                .iter()
                .find(|(seen, _)| *seen == signature)
                .map(|(_, step)| *step);
            if let Some(original) = repeated {
                let repeat = self.collapse_repeat(original, sequence, time, reason, None);
                self.decision_steps.insert(sequence, original);
                self.open_work = Some(OpenWork {
                    step: repeat,
                    operation: tool.into(),
                    arguments,
                    started_ms: None,
                });
                return;
            }
        }
        let title = decision_title(tool, &arguments, actor);
        let (marks, attention) = self.decision_marks(tool, &arguments);
        let kind = if tool == "finish" {
            StepKind::Finish
        } else {
            tool_kind(tool)
        };
        let step = self.push_step(StepBase {
            kind,
            actor,
            text: reason.unwrap_or_else(|| title.clone()),
            title,
            notes: decision["notes"]
                .as_str()
                .map(|n| plain_text(n, MAX_NOTES_CHARS)),
            targets: targets(&arguments),
            attention,
            marks,
            tool: (tool != "finish").then(|| ToolCard {
                tool: tool.into(),
                duration_ms: None,
                state: ResultState::Working,
                text: "Waiting for the host".into(),
                kept: None,
            }),
            model_ms: answer.as_ref().map(|a| a.model_ms),
            cost_usd: answer.and_then(|a| a.cost_usd),
            ..StepBase::system(sequence, time)
        });
        self.decision_steps.insert(sequence, step);
        if actor == Actor::Model {
            self.recent.push_back((signature, step));
            if self.recent.len() > REPEAT_WINDOW {
                self.recent.pop_front();
            }
        }
        self.open_work = (tool != "finish").then(|| OpenWork {
            step,
            operation: tool.into(),
            arguments,
            started_ms: None,
        });
    }

    /// The open decision was never sent to a worker (the controller declined it):
    /// close its tool card, and do not count it when looking for repeats.
    fn close_unrun(&mut self, text: &str) {
        let Some(work) = self.open_work.take_if(|work| work.started_ms.is_none()) else {
            return;
        };
        self.recent.retain(|(_, step)| *step != work.step);
        let step = &mut self.steps[work.step];
        if step.kind != StepKind::RepeatCollapsed {
            step.kind = StepKind::Refused;
        }
        if let Some(card) = step.tool.as_mut() {
            card.state = ResultState::Refused;
            card.text = text.into();
        }
    }

    /// Fold a repeat of step `original` into its `repeat_collapsed` step and
    /// return that step's index.
    fn collapse_repeat(
        &mut self,
        original: usize,
        sequence: u64,
        time: u64,
        reason: Option<String>,
        refusal: Option<&str>,
    ) -> usize {
        let index = match self.repeat_steps.get(&original) {
            Some(index) => *index,
            None => {
                let first = &self.steps[original];
                let base = StepBase {
                    kind: StepKind::RepeatCollapsed,
                    actor: first.actor,
                    title: first.title.clone(),
                    text: first.text.clone(),
                    targets: first.targets.clone(),
                    attention: first.attention_px,
                    tool: first.tool.as_ref().map(|card| ToolCard {
                        duration_ms: None,
                        state: ResultState::Working,
                        text: "Waiting for the host".into(),
                        ..card.clone()
                    }),
                    repeat_of: Some(first.sequence),
                    ..StepBase::system(sequence, time)
                };
                let index = self.push_step(base);
                self.repeat_steps.insert(original, index);
                index
            }
        };
        let original_title = self.steps[original].title.clone();
        let step = &mut self.steps[index];
        step.count += 1;
        step.last_sequence = sequence;
        step.title = format!("{original_title} ({} times)", step.count);
        if let Some(reason) = reason {
            step.text = reason;
        }
        if let (Some(text), Some(card)) = (refusal, step.tool.as_mut()) {
            card.state = ResultState::Refused;
            card.text = text.into();
        }
        index
    }

    fn on_repeat_refused(&mut self, sequence: u64, time: u64, payload: &Value) {
        self.model_answer = None;
        let earlier = payload["earlier_decision_event_id"]
            .as_u64()
            .and_then(|id| self.decision_steps.get(&id).copied());
        let reason = payload["decision"]["reason"]
            .as_str()
            .map(|r| plain_text(r, MAX_TEXT_CHARS));
        let refusal = "Same step again, refused";
        match earlier {
            Some(original) => {
                self.collapse_repeat(original, sequence, time, reason, Some(refusal));
            }
            None => {
                self.push_step(StepBase {
                    kind: StepKind::RepeatCollapsed,
                    actor: Actor::Model,
                    title: refusal.into(),
                    text: reason.unwrap_or_else(|| refusal.into()),
                    ..StepBase::system(sequence, time)
                });
            }
        }
    }

    fn on_operation_rejected(&mut self, sequence: u64, time: u64, payload: &Value) {
        self.model_answer = None;
        let decision = &payload["decision"];
        let tool = decision["tool"].as_str().unwrap_or("step");
        let why = plain_reason(payload["reason"].as_str().unwrap_or(""));
        let arguments = &decision["arguments"];
        let (mut marks, attention) = self.decision_marks(tool, arguments);
        refuse_marks(&mut marks, &why);
        self.push_step(StepBase {
            kind: StepKind::Refused,
            actor: Actor::Model,
            title: format!(
                "Not allowed: {}",
                decision_title(tool, arguments, Actor::Model)
            ),
            text: decision["reason"]
                .as_str()
                .map(|r| plain_text(r, MAX_TEXT_CHARS))
                .unwrap_or_else(|| why.clone()),
            targets: targets(arguments),
            attention,
            marks,
            tool: Some(ToolCard {
                tool: tool.into(),
                duration_ms: None,
                state: ResultState::Refused,
                text: capitalize(&why),
                kept: None,
            }),
            ..StepBase::system(sequence, time)
        });
    }

    // ---- mark and revise ----

    /// A person marked part of the drawing and said what to fix.
    fn on_revision_requested(&mut self, sequence: u64, time: u64, payload: &Value) {
        self.finished = false;
        let request = &payload["request"];
        let points = |value: &Value| -> Option<Vec<Point>> {
            value
                .as_array()?
                .iter()
                .map(|p| Some([p.get(0)?.as_f64()?, p.get(1)?.as_f64()?]))
                .collect()
        };
        let region = &request["region"];
        let mut marks = vec![];
        if let Ok(region_box) = serde_json::from_value::<BoxPx>(region["page_px_box"].clone()) {
            marks.push(box_mark(region_box, Tone::Person, None));
        } else if let Some(mut lasso) = points(&region["lasso_px"]).filter(|p| !p.is_empty()) {
            lasso.push(lasso[0]);
            marks.push(Mark {
                shape: MarkShape::Polyline,
                tone: Tone::Person,
                points_px: lasso,
                label: None,
                tag: None,
                candidate_id: None,
                half_width_px: None,
            });
        }
        let attention = marks.first().and_then(|mark| {
            let xs = mark.points_px.iter().map(|p| p[0]);
            let ys = mark.points_px.iter().map(|p| p[1]);
            Some([
                xs.clone().reduce(f64::min)?,
                ys.clone().reduce(f64::min)?,
                xs.reduce(f64::max)?,
                ys.reduce(f64::max)?,
            ])
        });
        let targets = payload["sections"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .take(MAX_TARGETS)
            .map(|id| Target {
                kind: TargetKind::Section,
                id: id.into(),
            })
            .collect();
        let instruction = request["instruction"].as_str().unwrap_or("");
        self.push_step(StepBase {
            kind: StepKind::Revise,
            actor: Actor::Person,
            title: "Marked for revision".into(),
            text: plain_text(instruction, MAX_TEXT_CHARS),
            targets,
            attention,
            marks,
            ..StepBase::system(sequence, time)
        });
    }

    /// The focused pass ended: which edits the keep rule kept, and the fit change.
    fn on_revision_result(&mut self, sequence: u64, time: u64, payload: &Value) {
        let outcome = payload["outcome"].as_str().unwrap_or("stopped").to_string();
        let fit_change = payload["fit_change"].as_f64();
        let not_kept_change = payload["not_kept_fit_change"].as_f64();
        let title = revision_title(&outcome, fit_change, not_kept_change);
        let reason = payload["edits"]
            .as_array()
            .and_then(|edits| edits.iter().find(|e| e["kept"] == false))
            .and_then(|edit| edit["reason"].as_str())
            .map(|reason| capitalize(&plain_text(reason, MAX_TEXT_CHARS)))
            .unwrap_or_default();
        let kept = match outcome.as_str() {
            "kept" => Some(true),
            "not_kept" | "partly_kept" => Some(false),
            _ => None,
        };
        let index = self.push_step(StepBase {
            kind: StepKind::Revise,
            title: title.clone(),
            text: String::new(),
            tool: Some(ToolCard {
                tool: "keep rule".into(),
                duration_ms: None,
                state: if outcome == "stopped" {
                    ResultState::Failed
                } else {
                    ResultState::Ok
                },
                text: if reason.is_empty() { title } else { reason },
                kept,
            }),
            ..StepBase::system(sequence, time)
        });
        self.steps[index].mark_revision = Some(MarkRevision {
            revision_id: payload["revision_id"].as_str().unwrap_or("").into(),
            fit_change,
            not_kept_fit_change: not_kept_change,
            can_keep_anyway: kept == Some(false),
            operator_forced: false,
            outcome,
        });
    }

    /// A person kept the not-kept edits anyway: the result step loses its button.
    fn on_revision_forced(&mut self, sequence: u64, time: u64, payload: &Value) {
        let revision_id = payload["revision_id"].as_str().unwrap_or("");
        if let Some(step) = self.steps.iter_mut().rev().find(|s| {
            s.mark_revision
                .as_ref()
                .is_some_and(|r| r.revision_id == revision_id)
        }) {
            let revision = step.mark_revision.as_mut().expect("found above");
            revision.can_keep_anyway = false;
            revision.operator_forced = true;
            step.last_sequence = sequence;
        }
        self.push_step(StepBase {
            kind: StepKind::Revise,
            actor: Actor::Person,
            title: "Kept anyway".into(),
            text: String::new(),
            ..StepBase::system(sequence, time)
        });
    }

    fn on_terminated(&mut self, sequence: u64, time: u64, payload: &Value, status: Option<&str>) {
        let why = capitalize(&plain_reason(payload["reason"].as_str().unwrap_or("")));
        let (kind, title) = match status {
            Some("paused") => (StepKind::System, "Paused"),
            Some("awaiting_human_review") => (StepKind::Finish, "Ready for review"),
            Some("draft_not_verified") => (StepKind::Finish, "Stopped with a draft to check"),
            Some("abstained") => (StepKind::Finish, "Declined"),
            Some("cancelled") => (StepKind::Finish, "Cancelled"),
            _ => (StepKind::Finish, "Stopped"),
        };
        self.finished = kind == StepKind::Finish;
        self.open_work = None;
        self.model_since_ms = None;
        self.push_step(StepBase {
            kind,
            title: title.into(),
            text: if why.is_empty() { title.into() } else { why },
            ..StepBase::system(sequence, time)
        });
    }

    // ---- worker operations ----

    fn on_worker_intent(&mut self, sequence: u64, time: u64, payload: &Value) {
        let operation = payload["operation"].as_str().unwrap_or("step").to_string();
        let open = self
            .open_work
            .as_mut()
            .filter(|work| work.operation == operation && work.started_ms.is_none());
        if let Some(work) = open {
            work.started_ms = Some(time);
            return;
        }
        let step = self.push_step(StepBase {
            kind: tool_kind(&operation),
            actor: Actor::Code,
            title: code_title(&operation).into(),
            text: code_text(&operation).into(),
            tool: Some(ToolCard {
                tool: operation.clone(),
                duration_ms: None,
                state: ResultState::Working,
                text: "Working".into(),
                kept: None,
            }),
            ..StepBase::system(sequence, time)
        });
        self.open_work = Some(OpenWork {
            step,
            operation,
            arguments: Value::Null,
            started_ms: Some(time),
        });
    }

    fn on_worker_result(&mut self, task: &Path, sequence: u64, time: u64, payload: &Value) {
        let operation = payload["operation"].as_str().unwrap_or("step").to_string();
        let work = match self.open_work.take() {
            Some(work) if work.operation == operation => work,
            _ => {
                // A result without its intent (an older ledger): a step of its own.
                let step = self.push_step(StepBase {
                    kind: tool_kind(&operation),
                    actor: Actor::Code,
                    title: code_title(&operation).into(),
                    text: code_text(&operation).into(),
                    ..StepBase::system(sequence, time)
                });
                OpenWork {
                    step,
                    operation: operation.clone(),
                    arguments: Value::Null,
                    started_ms: None,
                }
            }
        };
        let response = &payload["response"];
        let result = &response["result"];
        self.learn_from_result(result);
        let card = result_card(&operation, response, time, work.started_ms);
        let is_repeat = self.steps[work.step].kind == StepKind::RepeatCollapsed;
        let mut marks = vec![];
        if !is_repeat {
            marks = self.result_marks(task, &operation, &work.arguments, result);
        }
        let revision = self.revision_from(task, &operation, response);
        let images = model_images(result);
        let view_box = geometry::box_px(&result["view"]["crop_box_px"]);
        let step = &mut self.steps[work.step];
        step.last_sequence = sequence;
        if !is_repeat {
            if card.state == ResultState::Refused {
                step.kind = StepKind::Refused;
                refuse_marks(&mut step.marks, &card.text);
            }
            if operation == "render_candidate" && revision.is_some() {
                step.kind = StepKind::Score;
            }
            if let Some(title) = result_title(&operation, &work.arguments, result) {
                step.title = title;
            }
            step.marks.extend(marks);
            step.attention_px = step.attention_px.or(view_box);
            step.images = images;
        }
        step.tool = Some(card);
        step.revision = revision.or(step.revision.take());
    }

    /// Remember view frames and section panels that a result reports.
    fn learn_from_result(&mut self, result: &Value) {
        let frames = std::iter::once(&result["view"])
            .chain(result["artifacts"].as_array().into_iter().flatten())
            .filter_map(ViewFrame::from_value);
        for (id, frame) in frames {
            self.views.entry(id).or_insert(frame);
        }
        for section in result["sections"].as_array().into_iter().flatten() {
            self.learn_section(section);
        }
    }

    fn learn_section(&mut self, section: &Value) {
        let Some(id) = section["id"].as_str().or(section["section_id"].as_str()) else {
            return;
        };
        let entry = self.sections.entry(id.to_string()).or_default();
        if let Some(roi) = geometry::box_px(&section["roi_px"]) {
            entry.roi = Some(roi);
        }
        if let Some(calibration) = Calibration::from_value(&section["calibration"]) {
            entry.calibration = Some(calibration);
        }
    }

    fn frame(&self, view_id: &Value) -> Option<ViewFrame> {
        let id = view_id.as_str()?;
        self.views.get(id).copied().or_else(|| {
            let domain = self.domain.as_ref()?.1.clone();
            let view = domain["views"]
                .as_array()?
                .iter()
                .find(|v| v["view_id"] == id)?;
            ViewFrame::from_value(view).map(|(_, frame)| frame)
        })
    }

    fn section_roi(&self, id: &Value) -> Option<BoxPx> {
        self.sections.get(id.as_str()?)?.roi
    }

    /// `domain/state.json`, re-read only when the file changed.
    fn domain(&mut self, task: &Path) -> Option<Arc<Value>> {
        let file = task.join("domain/state.json");
        let stamp = (
            files::modified_ms(&file),
            std::fs::metadata(&file).map(|m| m.len()).unwrap_or(0),
        );
        if let Some((seen, domain)) = &self.domain {
            if *seen == stamp {
                return Some(domain.clone());
            }
        }
        let domain = Arc::new(files::read_domain(task)?);
        self.domain = Some((stamp, domain.clone()));
        Some(domain)
    }

    fn candidate_line(
        &mut self,
        task: &Path,
        section_id: Option<&str>,
        candidate_id: &str,
    ) -> Option<Vec<Point>> {
        let domain = self.domain(task)?;
        geometry::candidate_polyline(task, &domain, section_id, candidate_id)
    }

    // ---- marks ----

    /// Marks and camera box of a decision, from its arguments alone.
    fn decision_marks(&self, tool: &str, arguments: &Value) -> (Vec<Mark>, Option<BoxPx>) {
        let section_box = self.section_roi(&arguments["section_id"]);
        match tool {
            "read_region" | "view_region" | "propose_sheet_setup" => {
                let Some(region) = geometry::box_px(&arguments["region_px"]) else {
                    return (vec![], None);
                };
                let label = arguments["subject"]
                    .as_str()
                    .or(arguments["view"].as_str())
                    .map(|s| s.replace('_', " "));
                (vec![box_mark(region, Tone::Attention, label)], Some(region))
            }
            "trace_from_point" => {
                let click = self
                    .frame(&arguments["view_id"])
                    .zip(geometry::point(&arguments["point_px"]))
                    .map(|(frame, p)| frame.to_sheet(p));
                let Some(click) = click else {
                    return (vec![], section_box);
                };
                let mark = Mark {
                    shape: MarkShape::Point,
                    tone: Tone::Attention,
                    points_px: geometry::round_points(&[click]),
                    label: None,
                    tag: None,
                    candidate_id: None,
                    half_width_px: None,
                };
                (vec![mark], geometry::bounds(&[click], CLICK_BOX_HALF_PX))
            }
            "trace_corridor" => {
                let Some(frame) = self.frame(&arguments["view_id"]) else {
                    return (vec![], section_box);
                };
                let path: Vec<Point> = geometry::points(&arguments["path_px"])
                    .into_iter()
                    .map(|p| frame.to_sheet(p))
                    .collect();
                let half_width = arguments["half_width_px"]
                    .as_f64()
                    .map(|w| geometry::round_to(frame.length_to_sheet(w), 1));
                let pad = half_width.unwrap_or(0.0) + CORRIDOR_PAD_PX;
                let mark = Mark {
                    shape: MarkShape::Band,
                    tone: Tone::Attention,
                    points_px: geometry::round_points(&path),
                    label: None,
                    tag: None,
                    candidate_id: None,
                    half_width_px: half_width,
                };
                (vec![mark], geometry::bounds(&path, pad))
            }
            "describe_views" => {
                let mut marks = vec![];
                for view in arguments["views"].as_array().into_iter().flatten() {
                    if let Some(region) = geometry::box_px(&view["region_px"]) {
                        let label = view["kind"].as_str().map(|k| k.replace('_', " "));
                        marks.push(box_mark(region, Tone::View, label));
                    }
                    for panel in view["panels"].as_array().into_iter().flatten() {
                        if let Some(region) = geometry::box_px(&panel["region_px"]) {
                            let label = panel["panel_id"].as_str().map(String::from);
                            marks.push(box_mark(region, Tone::Panel, label));
                        }
                    }
                }
                let attention = geometry::union(marks.iter().filter_map(mark_box));
                (marks, attention)
            }
            "inspect_source" | "select_contours" => {
                let ids: Vec<&Value> = match tool {
                    "inspect_source" => arguments["section_ids"]
                        .as_array()
                        .map(|list| list.iter().collect())
                        .unwrap_or_default(),
                    _ => arguments["selections"]
                        .as_array()
                        .map(|list| list.iter().map(|s| &s["section_id"]).collect())
                        .unwrap_or_default(),
                };
                let panels: Vec<Mark> = ids
                    .iter()
                    .filter_map(|id| {
                        let roi = self.section_roi(id)?;
                        Some(box_mark(roi, Tone::Panel, id.as_str().map(String::from)))
                    })
                    .collect();
                let attention = geometry::union(panels.iter().filter_map(mark_box));
                (panels, attention)
            }
            _ => (vec![], section_box),
        }
    }

    /// Marks that only the worker result can give: strokes, accepted lines,
    /// model-drawn sections, survey regions.
    fn result_marks(
        &mut self,
        task: &Path,
        operation: &str,
        arguments: &Value,
        result: &Value,
    ) -> Vec<Mark> {
        let refused = result["status"] == "proposal_refused";
        let section = result["section_id"]
            .as_str()
            .or(arguments["section_id"].as_str())
            .map(String::from);
        match operation {
            "survey_sheet" => survey_marks(&result["sheet_survey"]),
            "enumerate_strokes" => {
                let strokes: Vec<Value> = result["strokes"].as_array().cloned().unwrap_or_default();
                strokes
                    .iter()
                    .filter_map(|stroke| {
                        let candidate = stroke["candidate_id"].as_str()?;
                        let line = self
                            .candidate_line(task, section.as_deref(), candidate)
                            .or_else(|| {
                                let ends = [
                                    geometry::point(&stroke["top_end_px"])?,
                                    geometry::point(&stroke["bottom_end_px"])?,
                                ];
                                Some(geometry::round_points(&ends))
                            })?;
                        Some(line_mark(
                            line,
                            Tone::Stroke,
                            None,
                            candidate,
                            stroke["tag"].as_u64(),
                        ))
                    })
                    .collect()
            }
            "trace_corridor" | "trace_from_point" if !refused => {
                let Some(candidate) = result["candidate_id"].as_str() else {
                    return vec![];
                };
                self.candidate_line(task, section.as_deref(), candidate)
                    .map(|line| vec![line_mark(line, Tone::Accepted, None, candidate, None)])
                    .unwrap_or_default()
            }
            "assign_station" if !refused => {
                let guess = &result["guess"];
                let Some(candidate) = guess["chosen_candidate_id"]
                    .as_str()
                    .or(arguments["candidate_id"].as_str())
                else {
                    return vec![];
                };
                let label = match (section.as_deref(), arguments["label_text"].as_str()) {
                    (Some(id), Some(text)) => Some(format!("{id}: \"{}\"", plain_text(text, 64))),
                    (Some(id), None) => Some(id.to_string()),
                    _ => None,
                };
                self.candidate_line(task, section.as_deref(), candidate)
                    .map(|line| vec![line_mark(line, Tone::Accepted, label, candidate, None)])
                    .unwrap_or_default()
            }
            "select_contours" if result["ok"] != false => {
                let picks: Vec<(String, String)> = arguments["selections"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|pick| {
                        Some((
                            pick["section_id"].as_str()?.to_string(),
                            pick["candidate_id"].as_str()?.to_string(),
                        ))
                    })
                    .collect();
                picks
                    .iter()
                    .filter_map(|(section, candidate)| {
                        let line = self.candidate_line(task, Some(section), candidate)?;
                        Some(line_mark(
                            line,
                            Tone::Accepted,
                            Some(section.clone()),
                            candidate,
                            None,
                        ))
                    })
                    .collect()
            }
            "propose_section" => {
                let calibration = section
                    .as_deref()
                    .and_then(|id| self.sections.get(id)?.calibration);
                let curve = geometry::points(&result["curve_summary_yz_m"]);
                let (Some(calibration), true) = (calibration, curve.len() >= 2) else {
                    return vec![];
                };
                let line: Vec<Point> = curve.iter().map(|p| calibration.to_sheet(*p)).collect();
                let label = section.map(|id| format!("{id}, drawn by the model"));
                let candidate = result["candidate_id"].as_str().unwrap_or_default();
                let mut mark = line_mark(
                    geometry::round_points(&line),
                    Tone::Authored,
                    label,
                    candidate,
                    None,
                );
                if candidate.is_empty() {
                    mark.candidate_id = None;
                }
                vec![mark]
            }
            _ => vec![],
        }
    }

    // ---- builds and scores ----

    /// Section curves of a build for a step. Only the first step of a build
    /// carries the points; later steps carry the sections with empty points.
    fn curves(&mut self, task: &Path, path: &str) -> Vec<SectionCurve> {
        let curves = self
            .build_curves
            .entry(path.to_string())
            .or_insert_with(|| Arc::new(geometry::build_sections(task, path)))
            .clone();
        if self.curves_sent.insert(path.to_string()) {
            return curves.to_vec();
        }
        curves
            .iter()
            .map(|curve| SectionCurve {
                points_yz_m: vec![],
                ..curve.clone()
            })
            .collect()
    }

    /// A build (a result with a candidate build path) or a score (a render with
    /// `fit_score`).
    fn revision_from(
        &mut self,
        task: &Path,
        operation: &str,
        response: &Value,
    ) -> Option<RevisionInfo> {
        let result = &response["result"];
        let candidate = &result["candidate"];
        if let Some(path) = candidate["path"].as_str().filter(|p| safe_relative(p)) {
            let id = candidate["revision_id"]
                .as_str()
                .or(result["revision_id"].as_str())
                .map(String::from);
            if let Some(id) = &id {
                self.revisions.insert(id.clone(), path.to_string());
            }
            return Some(RevisionInfo {
                id,
                path: Some(path.to_string()),
                fit: candidate["combined_fit"].as_f64(),
                sections: self.curves(task, path),
            });
        }
        let score = &result["fit_score"];
        if operation != "render_candidate" || !score.is_object() {
            return None;
        }
        let id = result["rendered_revision_id"]
            .as_str()
            .or(result["revision_id"].as_str())
            .map(String::from);
        let current = &response["domain"]["current_candidate"];
        let path = id
            .as_ref()
            .and_then(|id| self.revisions.get(id).cloned())
            .or_else(|| {
                (current["revision_id"].as_str() == id.as_deref())
                    .then(|| current["path"].as_str().map(String::from))
                    .flatten()
            })
            .filter(|p| safe_relative(p));
        let mut sections = path
            .as_deref()
            .map(|p| self.curves(task, p))
            .unwrap_or_default();
        for section in &mut sections {
            let fit = &score["station_ink_fit"][&section.id]["rms_m"];
            section.ink_rms_m = fit.as_f64().map(|rms| geometry::round_to(rms, 4));
        }
        Some(RevisionInfo {
            id,
            path,
            fit: score["combined_fit"].as_f64(),
            sections,
        })
    }

    // ---- step list ----

    fn push_system(&mut self, sequence: u64, time: u64, title: &str, text: &str) {
        // Identical system lines in a row (notes shortened again) share one step.
        if let Some(last) = self.steps.last_mut() {
            if last.kind == StepKind::System && last.title == title {
                last.count += 1;
                last.last_sequence = sequence;
                return;
            }
        }
        self.push_step(StepBase {
            title: title.into(),
            text: text.into(),
            ..StepBase::system(sequence, time)
        });
    }

    fn push_step(&mut self, base: StepBase) -> usize {
        let time_ms = self.relative(base.time);
        self.steps.push(LiveStep {
            sequence: base.sequence,
            last_sequence: base.sequence,
            time_ms,
            kind: base.kind,
            actor: base.actor,
            title: base.title,
            text: base.text,
            notes: base.notes,
            targets: base.targets,
            attention_px: base.attention.map(round_box),
            marks: base.marks,
            tool: base.tool,
            revision: None,
            images: vec![],
            model_ms: base.model_ms,
            cost_usd: base.cost_usd,
            repeat_of: base.repeat_of,
            count: 1,
            mark_revision: None,
        });
        self.steps.len() - 1
    }
}

/// The parts of a new step; the rest starts empty.
struct StepBase {
    sequence: u64,
    time: u64,
    kind: StepKind,
    actor: Actor,
    title: String,
    text: String,
    notes: Option<String>,
    targets: Vec<Target>,
    attention: Option<BoxPx>,
    marks: Vec<Mark>,
    tool: Option<ToolCard>,
    model_ms: Option<u64>,
    cost_usd: Option<f64>,
    repeat_of: Option<u64>,
}

impl StepBase {
    fn system(sequence: u64, time: u64) -> Self {
        StepBase {
            sequence,
            time,
            kind: StepKind::System,
            actor: Actor::Code,
            title: String::new(),
            text: String::new(),
            notes: None,
            targets: vec![],
            attention: None,
            marks: vec![],
            tool: None,
            model_ms: None,
            cost_usd: None,
            repeat_of: None,
        }
    }
}

// ---- plain text ----

fn tool_kind(tool: &str) -> StepKind {
    match tool {
        "survey_sheet" => StepKind::Survey,
        "describe_views" | "propose_sheet_setup" => StepKind::Views,
        "describe_vessel" => StepKind::Vessel,
        "inspect_source" | "view_region" | "recall_view" | "compare_views" => StepKind::Look,
        "read_region" => StepKind::Read,
        "enumerate_strokes" => StepKind::Strokes,
        "trace_from_point" => StepKind::Trace,
        "trace_corridor" => StepKind::Corridor,
        "assign_station" | "select_contours" => StepKind::Assign,
        "propose_section" => StepKind::ProposeSection,
        "build_first_hull" | "build_draft" | "build_provisional" => StepKind::Build,
        "render_candidate" => StepKind::Render,
        "validate_candidate" => StepKind::Score,
        "finish" => StepKind::Finish,
        _ => StepKind::System,
    }
}

/// "s01", "s01 and s02", "s01, s02 and s03", "9 sections".
fn section_list(ids: &[&str]) -> String {
    match ids {
        [] => "the next sections".into(),
        [one] => (*one).into(),
        [a, b] => format!("{a} and {b}"),
        [a, b, c] => format!("{a}, {b} and {c}"),
        list => format!("{} sections", list.len()),
    }
}

fn decision_title(tool: &str, arguments: &Value, actor: Actor) -> String {
    let section = arguments["section_id"].as_str().unwrap_or("a section");
    let you = actor == Actor::Person;
    match tool {
        "survey_sheet" => "Surveyed the sheet".into(),
        "describe_views" => {
            let count = arguments["views"].as_array().map_or(0, Vec::len);
            format!("Named {count} view{}", if count == 1 { "" } else { "s" })
        }
        "describe_vessel" => "Recorded the vessel's dimensions and stations".into(),
        "view_region" => "Looked at part of the sheet".into(),
        "recall_view" => "Looked at an earlier view again".into(),
        "read_region" => format!(
            "Read the {}",
            arguments["subject"]
                .as_str()
                .unwrap_or("region")
                .replace('_', " ")
        ),
        "inspect_source" => {
            let ids: Vec<&str> = arguments["section_ids"]
                .as_array()
                .map(|list| list.iter().filter_map(Value::as_str).collect())
                .unwrap_or_default();
            format!("Read the candidate lines of {}", section_list(&ids))
        }
        "enumerate_strokes" => format!("Listed the strokes in the {section} panel"),
        "trace_from_point" => format!("Clicked on the ink at {section}"),
        "trace_corridor" => format!("Drew a corridor along {section}"),
        "assign_station" => match arguments["label_text"].as_str() {
            Some(label) => format!(
                "Claimed a line is the section at {section} (\"{}\")",
                plain_text(label, 64)
            ),
            None => format!("Claimed a line is the section at {section}"),
        },
        "select_contours" => {
            let ids: Vec<&str> = arguments["selections"]
                .as_array()
                .map(|list| {
                    list.iter()
                        .filter_map(|s| s["section_id"].as_str())
                        .collect()
                })
                .unwrap_or_default();
            let verb = if you { "You picked" } else { "Picked" };
            format!("{verb} the line for {}", section_list(&ids))
        }
        "propose_section" => format!("Drew the section at {section}"),
        "build_draft" | "build_provisional" => {
            if you {
                "You rebuilt the model".into()
            } else {
                "Built a draft".into()
            }
        }
        "render_candidate" => format!(
            "Compared the {} view with the drawing",
            arguments["view"].as_str().unwrap_or("model")
        ),
        "validate_candidate" => "Checked the model against the drawing".into(),
        "propose_sheet_setup" => "Proposed a scale for a view".into(),
        "compare_views" => format!("Compared {section} with the plan view"),
        "ask_person" => "Asked a person".into(),
        "finish" => {
            let summary = arguments["summary"].as_str().map(|s| plain_text(s, 160));
            match (arguments["outcome"].as_str(), summary) {
                (Some("abstain"), Some(summary)) => format!("Declined: {summary}"),
                (Some("abstain"), None) => "Declined".into(),
                (_, Some(summary)) => format!("Finished: {summary}"),
                _ => "Finished".into(),
            }
        }
        other => capitalize(&other.replace('_', " ")),
    }
}

/// A better title once the result is known, for example the stroke count.
fn result_title(operation: &str, arguments: &Value, result: &Value) -> Option<String> {
    let section = result["section_id"]
        .as_str()
        .or(arguments["section_id"].as_str())?;
    match operation {
        "enumerate_strokes" => {
            let count = result["strokes"].as_array()?.len();
            Some(format!(
                "Listed {count} stroke{} in the {section} panel",
                if count == 1 { "" } else { "s" }
            ))
        }
        _ => None,
    }
}

fn code_title(operation: &str) -> &'static str {
    match operation {
        "initialize" => "Opened the sheet",
        "survey_sheet" => "Surveyed the sheet",
        "inspect_source" => "Read the candidate lines",
        "build_first_hull" => "Built the first hull",
        "build_draft" | "build_provisional" => "Built a draft",
        "render_candidate" => "Compared the model with the drawing",
        "validate_candidate" => "Checked the model against the drawing",
        "select_contours" => "Picked the clear lines",
        _ => "Worked on the run",
    }
}

fn code_text(operation: &str) -> &'static str {
    match operation {
        "initialize" => "Reading the sheet and the spec.",
        "survey_sheet" => "Finding the views and grids on the sheet.",
        "inspect_source" => "Tracing the candidate lines of each section.",
        "build_first_hull" => "Building the first hull from the traced lines.",
        "build_draft" | "build_provisional" => "Building the hull from the current lines.",
        "render_candidate" => "Cutting the model at each station and comparing it with the ink.",
        "validate_candidate" => "Checking the model against the drawing.",
        "select_contours" => "Choosing the lines that only one stroke supports.",
        _ => "Working.",
    }
}

/// The tool card of a finished worker operation.
fn result_card(operation: &str, response: &Value, time: u64, started: Option<u64>) -> ToolCard {
    let result = &response["result"];
    let duration_ms = started.map(|s| time.saturating_sub(s));
    let card = |state, text: String, kept| ToolCard {
        tool: operation.into(),
        duration_ms,
        state,
        text,
        kept,
    };
    if response["execution_state"] != "completed" {
        let code = response["error_code"].as_str().unwrap_or("unknown");
        return card(
            ResultState::Failed,
            format!("The step did not finish ({})", code.replace('_', " ")),
            None,
        );
    }
    let status = result["status"].as_str().unwrap_or("");
    let message = result["message"].as_str().map(|m| plain_text(m, 240));
    if status == "proposal_refused" {
        let why = message
            .or_else(|| result["error_code"].as_str().map(|c| c.replace('_', " ")))
            .unwrap_or_else(|| "no reason given".into());
        return card(ResultState::Refused, format!("Refused: {why}"), None);
    }
    let fit = |value: &Value| value.as_f64().map(|f| format!("{f:.4}"));
    if operation.starts_with("build") && result["ok"] == false {
        let blocking = result["candidate"]["gaps"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|gap| gap["severity"] == "blocking")
            .and_then(|gap| gap["message"].as_str())
            .map(|m| plain_text(m, 200))
            .unwrap_or_else(|| "a section has no usable line".into());
        return card(ResultState::Failed, format!("Blocked: {blocking}"), None);
    }
    if let Some(comparison) = result["fit_comparison"].as_object() {
        let kept = comparison.get("keep").and_then(Value::as_bool);
        let before = comparison.get("fit_before").and_then(Value::as_f64);
        let after = comparison.get("fit_after").and_then(Value::as_f64);
        let change = match (before, after) {
            (Some(b), Some(a)) => format!("fit {b:.4} to {a:.4}"),
            _ => "fit not compared".into(),
        };
        let text = if kept == Some(false) {
            format!("Not kept: {change}")
        } else {
            format!("Kept: {change}")
        };
        return card(ResultState::Ok, text, kept);
    }
    let count = |key: &str| result[key].as_array().map_or(0, Vec::len);
    let text = match operation {
        "enumerate_strokes" => format!("{} strokes", count("strokes")),
        "read_region" | "view_region" | "recall_view" => {
            match geometry::point(&result["view"]["pixel_size"]) {
                Some(size) => format!("Saw a {:.0} x {:.0} px view", size[0], size[1]),
                None => "Saw the region".into(),
            }
        }
        "inspect_source" => {
            let lines: usize = result["sections"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|s| s["candidates"].as_array().map_or(0, Vec::len))
                .sum();
            format!("{} sections, {lines} candidate lines", count("sections"))
        }
        "survey_sheet" => format!(
            "{} regions found",
            result["sheet_survey"]["candidate_regions"]
                .as_array()
                .map_or(0, Vec::len)
        ),
        "describe_views" => format!("{} views recorded", count("described_views")),
        "assign_station" if status == "assigned_as_open_guess" => {
            "Accepted as a guess for a person to confirm".into()
        }
        "trace_corridor" | "trace_from_point" => "Found a line in the ink".into(),
        "render_candidate" => match fit(&result["fit_score"]["combined_fit"]) {
            Some(fit) => format!("Fit {fit}"),
            None => "Rendered".into(),
        },
        op if op.starts_with("build") => match fit(&result["candidate"]["combined_fit"]) {
            Some(fit) => format!("Built; fit {fit}"),
            None => capitalize(&status.replace('_', " ")),
        },
        _ if status.is_empty() => "Done".into(),
        _ => capitalize(&status.replace('_', " ")),
    };
    card(ResultState::Ok, text, None)
}

/// Images of model observations in the result, as task-relative paths.
fn model_images(result: &Value) -> Vec<String> {
    result["artifacts"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|a| a["kind"] == "model_observation" && a["mime_type"] == "image/png")
        .filter_map(|a| a["path"].as_str())
        .filter(|path| safe_relative(path))
        .take(MAX_IMAGES)
        .map(String::from)
        .collect()
}

fn targets(arguments: &Value) -> Vec<Target> {
    let mut found: Vec<Target> = vec![];
    let mut add = |kind: TargetKind, id: Option<&str>| {
        if let Some(id) = id.filter(|id| !id.is_empty() && id.len() <= 64) {
            if found.len() < MAX_TARGETS && !found.iter().any(|t| t.kind == kind && t.id == id) {
                found.push(Target {
                    kind,
                    id: id.into(),
                });
            }
        }
    };
    add(TargetKind::Section, arguments["section_id"].as_str());
    for id in arguments["section_ids"].as_array().into_iter().flatten() {
        add(TargetKind::Section, id.as_str());
    }
    for pick in arguments["selections"].as_array().into_iter().flatten() {
        add(TargetKind::Section, pick["section_id"].as_str());
    }
    add(TargetKind::View, arguments["view_id"].as_str());
    add(TargetKind::View, arguments["label_view_id"].as_str());
    for view in arguments["views"].as_array().into_iter().flatten() {
        add(TargetKind::View, view["view_id"].as_str());
    }
    found
}

/// View boxes for a sheet survey. When the run came from the intake screen, show the
/// views the person saw there (body plan, profile, ...). The survey's own candidate
/// regions are only fixed-size search tiles, so they are the fallback.
fn survey_marks(survey: &Value) -> Vec<Mark> {
    let intake_views: Vec<Mark> = survey["intake_regions"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|region| region["label"] != "other")
        .filter_map(|region| {
            let label = region["label"].as_str().map(view_label);
            Some(box_mark(
                geometry::box_px(&region["region_px"])?,
                Tone::View,
                label,
            ))
        })
        .collect();
    if !intake_views.is_empty() {
        return intake_views;
    }
    survey["candidate_regions"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|region| {
            let label = region["kind"].as_str().map(view_label);
            Some(box_mark(
                geometry::box_px(&region["region_px"])?,
                Tone::View,
                label,
            ))
        })
        .collect()
}

/// "body_plan" -> "Body plan".
fn view_label(kind: &str) -> String {
    let words = kind.replace('_', " ");
    let mut chars = words.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => words,
    }
}

fn box_mark(region: BoxPx, tone: Tone, label: Option<String>) -> Mark {
    let region = round_box(region);
    Mark {
        shape: MarkShape::Box,
        tone,
        points_px: vec![[region[0], region[1]], [region[2], region[3]]],
        label,
        tag: None,
        candidate_id: None,
        half_width_px: None,
    }
}

fn line_mark(
    line: Vec<Point>,
    tone: Tone,
    label: Option<String>,
    candidate_id: &str,
    tag: Option<u64>,
) -> Mark {
    Mark {
        shape: MarkShape::Polyline,
        tone,
        points_px: line,
        label,
        tag,
        candidate_id: Some(candidate_id.to_string()),
        half_width_px: None,
    }
}

fn mark_box(mark: &Mark) -> Option<BoxPx> {
    match mark.points_px.as_slice() {
        [a, b] if mark.shape == MarkShape::Box => Some([a[0], a[1], b[0], b[1]]),
        _ => None,
    }
}

/// Turn the attention marks of a refused step amber, with the reason on the first.
fn refuse_marks(marks: &mut [Mark], reason: &str) {
    let mut labelled = false;
    for mark in marks.iter_mut().filter(|m| m.tone == Tone::Attention) {
        mark.tone = Tone::Refused;
        if !labelled {
            mark.label = Some(reason.to_string());
            labelled = true;
        }
    }
}

fn round_box(region: BoxPx) -> BoxPx {
    region.map(|v| geometry::round_to(v, 1))
}

/// A task-relative path without `..`, backslashes or a leading slash.
fn safe_relative(path: &str) -> bool {
    !path.is_empty()
        && !path.starts_with('/')
        && !path.contains('\\')
        && !path.contains(':')
        && path
            .split('/')
            .all(|part| !part.is_empty() && part != "." && part != "..")
}

/// "Kept, fit +0.031", "Not kept: worse by 0.020", "Not kept: fit +0.001 is too small".
pub(super) fn revision_title(
    outcome: &str,
    fit_change: Option<f64>,
    not_kept_change: Option<f64>,
) -> String {
    let not_kept = match not_kept_change {
        Some(change) if change < 0.0 => format!("worse by {:.3}", -change),
        Some(change) => format!("fit +{change:.3} is too small"),
        None => "the fit did not improve".into(),
    };
    let kept = match fit_change {
        Some(change) => format!("fit {change:+.3}"),
        None => "fit not scored".into(),
    };
    match outcome {
        "kept" => format!("Kept, {kept}"),
        "partly_kept" => format!("Partly kept, {kept}; one edit not kept: {not_kept}"),
        "not_kept" => format!("Not kept: {not_kept}"),
        "no_edit" => "No edit made".into(),
        _ => "Revision stopped".into(),
    }
}

fn capitalize(text: &str) -> String {
    let mut chars = text.chars();
    chars
        .next()
        .map(|c| c.to_uppercase().collect::<String>() + chars.as_str())
        .unwrap_or_default()
}

/// Model or worker text, safe to show: host paths replaced, control characters
/// removed, at most `max_chars` characters.
pub(super) fn plain_text(text: &str, max_chars: usize) -> String {
    let words: Vec<String> = text
        .split_whitespace()
        .map(|word| {
            let bare = word.trim_start_matches(['(', '[', '"', '\'', '`']);
            let host_path = (bare.starts_with('/') && bare[1..].contains('/'))
                || bare.starts_with("~/")
                || bare.get(1..3) == Some(":\\");
            if host_path {
                "[path]".to_string()
            } else {
                word.chars().filter(|c| !c.is_control()).collect()
            }
        })
        .collect();
    let joined = words.join(" ");
    if joined.chars().count() <= max_chars {
        return joined;
    }
    let cut: String = joined.chars().take(max_chars.saturating_sub(1)).collect();
    format!("{}…", cut.trim_end())
}

#[cfg(test)]
mod survey_mark_tests {
    use super::*;
    use serde_json::json;

    fn labels(marks: &[Mark]) -> Vec<String> {
        marks
            .iter()
            .map(|m| m.label.clone().unwrap_or_default())
            .collect()
    }

    #[test]
    fn intake_views_replace_the_search_tiles() {
        let survey = json!({
            "candidate_regions": [{"region_px": [0, 0, 768, 736], "kind": "unclassified"}],
            "intake_regions": [
                {"region_px": [10, 10, 900, 300], "label": "profile"},
                {"region_px": [2000, 10, 2500, 300], "label": "body_plan"},
                {"region_px": [10, 400, 50, 450], "label": "other"}
            ]
        });
        assert_eq!(labels(&survey_marks(&survey)), ["Profile", "Body plan"]);
    }

    #[test]
    fn without_intake_views_the_search_tiles_show() {
        let survey =
            json!({"candidate_regions": [{"region_px": [0, 0, 768, 736], "kind": "unclassified"}]});
        assert_eq!(labels(&survey_marks(&survey)), ["Unclassified"]);
    }
}
