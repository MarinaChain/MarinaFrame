//! The vision-model veto at finalization (W12).
//!
//! After the authoritative finalization predicate has passed, and only when the
//! task was started with `--model-review true`, the controller renders one
//! image per sampled station (source crop beside the same crop with the cut of
//! the exported STEP drawn over it) and asks the vision model whether each cut
//! follows the drawn hull line.
//!
//! Authority is one-sided by construction:
//! - `veto` returns either `None` (nothing changes) or blocking findings; it has
//!   no code path that sets a status, a pass, a review state or an approval.
//! - A failed, incomplete or unsure review is not a veto and changes nothing.
//! - A recorded veto stays bound to its STEP: any later finalization of the same
//!   STEP is refused without a new model call.
use crate::provider::vision::{self, ReviewReply, Usage, Verdict, VisionReply};
use crate::provider::{self, Purpose};
use crate::store::{self, Store};
use crate::supervised::{
    run_watched, stall_message, Watch, WatchedEnd, WorkerCommand, DEFAULT_STALL_PERIOD,
};
use crate::types::*;
use crate::util::{self, Result};
use crate::worker;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::path::Path;

/// Event that enables the review for a task; appended once by `run`.
pub const REQUESTED_EVENT: &str = "model_review_requested";
/// Event that holds the blocking findings of a veto.
pub const VETO_EVENT: &str = "model_review_veto";
pub const IMAGES_VERSION: &str = "marinaframe.review_images.v1";
pub const RECORD_VERSION: &str = "marinaframe.model_review.v1";
/// Stations per request: three side-by-side images stay below the provider's
/// request size and keep each verdict tied to few images.
const STATIONS_PER_REQUEST: usize = 3;
const MAX_STATIONS: usize = 64;
const MAX_IMAGE_BYTES: usize = 1_048_576;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewImage {
    /// The id the model answers with (letters, digits, `-`).
    pub review_id: String,
    pub section_id: String,
    pub x_m: f64,
    pub file: String,
    pub sha256: String,
    pub bytes: u64,
    pub width: u32,
    pub height: u32,
    pub crop_box_px: [i64; 4],
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewImages {
    pub schema_version: String,
    pub step_sha256: String,
    pub source_sha256: String,
    pub engineering_approved: bool,
    pub images: Vec<ReviewImage>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Finding {
    pub kind: String,
    pub section_id: String,
    pub review_id: String,
    pub reason: String,
    pub request_id: String,
    pub completion_id: Option<String>,
    pub image_sha256: String,
}

/// True when the task asked for the model review at creation.
pub fn requested(store: &Store) -> bool {
    store.events.iter().any(|e| e.kind == REQUESTED_EVENT)
}

/// A veto recorded earlier for this exact STEP.
fn recorded_veto(store: &Store, step_sha256: &str) -> Option<Value> {
    store
        .events
        .iter()
        .rev()
        .find(|e| e.kind == VETO_EVENT && e.payload["step_sha256"] == step_sha256)
        .map(|e| e.payload.clone())
}

/// The blocking findings of the completed review replies. Only an explicit
/// `does_not_follow` verdict on a requested station is a finding.
pub fn findings(images: &[ReviewImage], receipts: &[provider::Receipt]) -> Vec<Finding> {
    let mut found = vec![];
    for receipt in receipts {
        if receipt.state != provider::RequestState::Completed
            || receipt.purpose != Purpose::BuildReview
        {
            continue;
        }
        let Some(VisionReply::BuildReview(ReviewReply { stations })) = &receipt.vision else {
            continue;
        };
        for station in stations {
            if station.verdict != Verdict::DoesNotFollow {
                continue;
            }
            let Some(image) = images.iter().find(|i| i.review_id == station.station_id) else {
                continue;
            };
            if !receipt.images.iter().any(|r| r.sha256 == image.sha256) {
                continue;
            }
            found.push(Finding {
                kind: VETO_EVENT.into(),
                section_id: image.section_id.clone(),
                review_id: image.review_id.clone(),
                reason: station.reason.clone(),
                request_id: receipt.request_id.clone(),
                completion_id: receipt.completion_id.clone(),
                image_sha256: image.sha256.clone(),
            });
        }
    }
    found
}

/// Load the renderer's manifest and check every image against the current STEP.
pub fn load_images(directory: &Path, step_sha256: &str) -> Result<(ReviewImages, Vec<Vec<u8>>)> {
    let raw = util::read_bounded(&directory.join("manifest.json"), 262_144)?;
    let manifest: ReviewImages = util::parse(&raw, 262_144)?;
    if manifest.schema_version != IMAGES_VERSION
        || manifest.engineering_approved
        || manifest.step_sha256 != step_sha256
        || !util::valid_hash(&manifest.source_sha256)
        || manifest.images.is_empty()
        || manifest.images.len() > MAX_STATIONS
    {
        return Err("review_images_contract".into());
    }
    let mut ids = BTreeSet::new();
    let mut bytes = vec![];
    for image in &manifest.images {
        if !util::valid_id(&image.review_id, 32)
            || !ids.insert(image.review_id.clone())
            || !util::valid_section_id(&image.section_id)
            || !util::valid_id(&image.file, 128)
            || !image.file.ends_with(".png")
            || image.file.starts_with('.')
            || !util::valid_hash(&image.sha256)
        {
            return Err("review_image_contract".into());
        }
        let data = util::read_bounded(&directory.join(&image.file), MAX_IMAGE_BYTES)?;
        provider::check_png(&data)?;
        if util::hash(&data) != image.sha256 || data.len() as u64 != image.bytes {
            return Err("review_image_identity_mismatch".into());
        }
        bytes.push(data);
    }
    Ok((manifest, bytes))
}

/// Run the Python renderer under the progress watchdog, with the shared worker
/// environment. It reads the candidate run and writes only `out`. A cancel or a
/// stall stops its whole process group; either one fails the review.
fn render(config: &Config, run: &Path, out: &Path, logs: &Path, root: &Path) -> Result<bool> {
    let mut command = WorkerCommand::python(
        &config.worker_python,
        config.worker_source.as_deref().map(Path::new),
    );
    command
        .args(["-m", "vessel_reconstruction.llm_review", "render", "--run"])
        .arg(run)
        .arg("--out")
        .arg(out);
    let cancelled = || worker::cancelled(root);
    let watch = Watch {
        stall_period: DEFAULT_STALL_PERIOD,
        cancelled: &cancelled,
        operation: "rendering the review images",
    };
    let end = run_watched(&mut command, &watch).map_err(|_| "review_render_start")?;
    let (success, stdout, stderr) = match end {
        WatchedEnd::Finished(finished) => {
            (finished.status.success(), finished.stdout, finished.stderr)
        }
        WatchedEnd::Cancelled => (false, vec![], b"Stopped: the run was cancelled.\n".to_vec()),
        WatchedEnd::Stalled { stage, minutes } => (
            false,
            vec![],
            format!("{}\n", stall_message(&stage, minutes)).into_bytes(),
        ),
    };
    std::fs::write(logs.join("render.stdout"), stdout).map_err(|_| "review_log")?;
    std::fs::write(logs.join("render.stderr"), stderr).map_err(|_| "review_log")?;
    Ok(success)
}

struct Review {
    outcome: &'static str,
    stop_reason: Option<String>,
    findings: Vec<Finding>,
    usage: Usage,
}

fn review(store: &Store, step_sha256: &str, relative: &str) -> Result<(Review, Value)> {
    let directory = store.path.join(relative);
    let mut result = Review {
        outcome: "incomplete",
        stop_reason: None,
        findings: vec![],
        usage: Usage::default(),
    };
    let mut receipts = vec![];
    let mut verdicts = vec![];
    let config = &store.state.config;
    if !config.provider_transfer_authorized || config.authorization_basis.is_empty() {
        result.stop_reason = Some("provider_transfer_not_authorized".into());
        return Ok((result, json!([])));
    }
    let candidate = &store.state.domain["current_candidate"];
    let run = candidate["path"].as_str().ok_or("review_candidate_path")?;
    let step = util::safe_file(&store.path, &format!("{run}/model.step"))?;
    if util::file_hash(&step)? != step_sha256 {
        return Err("review_step_identity".into());
    }
    let images_dir = directory.join("images");
    let run_dir = step.parent().ok_or("review_run")?;
    if !render(config, run_dir, &images_dir, &directory, &store.path)? {
        result.stop_reason = Some("review_render_failed".into());
        return Ok((result, json!([])));
    }
    let (manifest, bytes) = load_images(&images_dir, step_sha256)?;
    let mut consecutive_failures = 0;
    for (chunk, data) in manifest
        .images
        .chunks(STATIONS_PER_REQUEST)
        .zip(bytes.chunks(STATIONS_PER_REQUEST))
    {
        let request = vision::RequestManifest {
            schema_version: vision::REQUEST_VERSION.into(),
            purpose: Purpose::BuildReview,
            source_sha256: manifest.source_sha256.clone(),
            engineering_approved: false,
            context: json!({"step_sha256":step_sha256,"note":"left half: source crop; right half: same crop with the STEP cut in magenta"}),
            images: chunk
                .iter()
                .map(|i| vision::RequestImage {
                    image_id: i.review_id.clone(),
                    file: format!("images/{}", i.file),
                    sha256: i.sha256.clone(),
                    bytes: i.bytes,
                    width: i.width,
                    height: i.height,
                    view: format!("station:{}", i.review_id),
                    crop_box_px: i.crop_box_px,
                })
                .collect(),
        };
        let template = vision::template(
            store.state.current_model(),
            &request,
            &util::hash_json(&manifest)?,
            data,
            store.state.generation_id.as_deref().unwrap_or("none"),
        )?;
        let prefix = format!("{relative}/");
        let sent = vision::send(&store.path, &prefix, config, &template, &mut result.usage)?;
        if let Some(VisionReply::BuildReview(reply)) = &sent.reply {
            verdicts.extend(reply.stations.iter().cloned());
            consecutive_failures = 0;
        } else {
            consecutive_failures += 1;
        }
        receipts.extend(sent.receipts);
        if consecutive_failures >= 2 {
            result.stop_reason = Some("review_no_progress".into());
            break;
        }
        if let Some(reason) = sent.stop {
            result.stop_reason = Some(reason);
            break;
        }
    }
    result.findings = findings(&manifest.images, &receipts);
    let answered = verdicts.len() == manifest.images.len();
    result.outcome = if !result.findings.is_empty() {
        "veto"
    } else if answered && result.stop_reason.is_none() {
        "no_veto"
    } else {
        "incomplete"
    };
    let record = json!({"schema_version":RECORD_VERSION,"step_sha256":step_sha256,
        "images_manifest_sha256":util::file_hash(&images_dir.join("manifest.json"))?,
        "images":manifest.images,"receipts":receipts,"verdicts":verdicts,"usage":result.usage,
        "findings":result.findings,"outcome":result.outcome,"stop_reason":result.stop_reason,
        "can_approve":false,"engineering_approved":false});
    Ok((result, record))
}

/// The finalization hook. `None` means nothing changes. `Some(findings)` means
/// the controller must keep the task out of review. Called only after the
/// authoritative predicate passed; it can never make a failed task pass.
pub fn veto(store: &mut Store, step_sha256: &str) -> Result<Option<Value>> {
    if let Some(previous) = recorded_veto(store, step_sha256) {
        store.append(
            "model_review_veto_retained",
            json!({"step_sha256":step_sha256,"engineering_approved":false}),
        )?;
        return Ok(Some(previous));
    }
    if !requested(store) {
        return Ok(None);
    }
    let relative = format!("model-review/{}", util::nonce());
    let directory = store.path.join(&relative);
    std::fs::create_dir_all(directory.join("images")).map_err(|_| "review_directory")?;
    for sub in ["requests", "receipts"] {
        std::fs::create_dir_all(directory.join(sub)).map_err(|_| "review_directory")?;
    }
    let (result, record) = match review(store, step_sha256, &relative) {
        Ok(done) => done,
        // A review that cannot run is not a veto; the reason is recorded.
        Err(code) => (
            Review {
                outcome: "incomplete",
                stop_reason: Some(code),
                findings: vec![],
                usage: Usage::default(),
            },
            Value::Null,
        ),
    };
    result.usage.add_to(&mut store.state.counters);
    let record = if record.is_null() {
        json!({"schema_version":RECORD_VERSION,"step_sha256":step_sha256,"outcome":result.outcome,
            "stop_reason":result.stop_reason,"can_approve":false,"engineering_approved":false})
    } else {
        record
    };
    util::atomic_json(&directory.join("review.json"), &record, false)?;
    store.append(
        "model_review",
        json!({"record":store::artifact(&store.path,&format!("{relative}/review.json"),"model_review_record")?,
            "step_sha256":step_sha256,"outcome":result.outcome,"stop_reason":result.stop_reason,
            "usage":result.usage,"can_approve":false,"engineering_approved":false}),
    )?;
    if result.findings.is_empty() {
        return Ok(None);
    }
    let payload = json!({"step_sha256":step_sha256,"findings":result.findings,"blocking":true,
        "record":format!("{relative}/review.json"),"engineering_approved":false});
    store.append(VETO_EVENT, payload.clone())?;
    Ok(Some(payload))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::provider::vision::StationVerdict;
    use crate::provider::{ImageReceipt, Receipt, RequestState};

    fn image(id: &str, sha: &str) -> ReviewImage {
        ReviewImage {
            review_id: id.into(),
            section_id: format!("section {id}"),
            x_m: 1.0,
            file: format!("{id}.png"),
            sha256: sha.into(),
            bytes: 1,
            width: 1,
            height: 1,
            crop_box_px: [0, 0, 1, 1],
        }
    }

    fn receipt(stations: &[(&str, Verdict)], shas: &[&str]) -> Receipt {
        let value = json!({"protocol":provider::PROTOCOL,"request_id":"vision-1","state":"completed",
            "endpoint":GO_ENDPOINT,"requested_model":GO_MODEL,"returned_model":GO_MODEL,"completion_id":"c1",
            "provider_request_id":null,"http_status":200,"response_sha256":null,"request_sha256":"a".repeat(64),
            "prompt_sha256":"a".repeat(64),"source_manifest_sha256":"a".repeat(64),"generation_id":"g","revision_id":"r",
            "observation_sha256":"a".repeat(64),"images":[],"usage":{},"observed_cost_usd":null,"latency_seconds":0.0,
            "decision":null,"error_code":null,"attempt":1,"retry_of":null,"retry_after_seconds":null,
            "aggregate_request_cap":null,"aggregate_token_cap":null,"aggregate_spend_cap":null,"evidence_mode":"live",
            "purpose":"build_review"});
        let mut receipt: Receipt = serde_json::from_value(value).unwrap();
        receipt.state = RequestState::Completed;
        receipt.images = shas
            .iter()
            .map(|sha| ImageReceipt {
                artifact_id: "x".into(),
                path: "x.png".into(),
                sha256: (*sha).into(),
                bytes: 1,
                mime_type: "image/png".into(),
                evidence_kind: vision::REVIEW_EVIDENCE_KIND.into(),
                view: None,
                generation_id: None,
                revision_id: None,
                step_sha256: None,
                pixels_attached: true,
                crop_box_px: None,
                pixel_size: None,
            })
            .collect();
        receipt.vision = Some(VisionReply::BuildReview(ReviewReply {
            stations: stations
                .iter()
                .map(|(id, verdict)| StationVerdict {
                    station_id: (*id).into(),
                    verdict: *verdict,
                    reason: "seen".into(),
                })
                .collect(),
        }));
        receipt
    }

    #[test]
    fn only_does_not_follow_on_a_sent_image_is_a_finding() {
        let (a, b) = ("a".repeat(64), "b".repeat(64));
        let images = [image("s000", &a), image("s001", &b)];
        let none = receipt(
            &[("s000", Verdict::Follows), ("s001", Verdict::CannotTell)],
            &[&a, &b],
        );
        assert!(findings(&images, &[none]).is_empty());
        let veto = receipt(
            &[("s000", Verdict::Follows), ("s001", Verdict::DoesNotFollow)],
            &[&a, &b],
        );
        let found = findings(&images, std::slice::from_ref(&veto));
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].section_id, "section s001");
        assert_eq!(found[0].kind, VETO_EVENT);
        // A verdict about an image that was not in that request is not evidence.
        let unsent = receipt(&[("s001", Verdict::DoesNotFollow)], &[&a]);
        assert!(findings(&images, &[unsent]).is_empty());
        // A failed receipt must not contribute even if it contains a forged verdict.
        let mut failed_with_reply = veto.clone();
        failed_with_reply.state = RequestState::Failed;
        assert!(findings(&images, &[failed_with_reply]).is_empty());
        // A failed request carries no verdict.
        let mut failed = veto;
        failed.vision = None;
        failed.state = RequestState::Failed;
        assert!(findings(&images, &[failed]).is_empty());
    }

    #[test]
    fn images_must_belong_to_the_current_step() {
        let dir = tempfile::tempdir().unwrap();
        let png: &[u8] = &[
            0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48,
            0x44, 0x52, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02, 0x08, 0x00, 0x00, 0x00,
            0x00, 0x57, 0xdd, 0x52, 0xf8, 0x00, 0x00, 0x00, 0x0e, 0x49, 0x44, 0x41, 0x54, 0x78,
            0x9c, 0x63, 0xfc, 0xcf, 0xc0, 0xc4, 0xc0, 0x00, 0x00, 0x05, 0x0d, 0x01, 0x03, 0xb8,
            0x4a, 0x5c, 0x6f, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60,
            0x82,
        ];
        std::fs::write(dir.path().join("s000.png"), png).unwrap();
        let mut entry = image("s000", &util::hash(png));
        entry.bytes = png.len() as u64;
        let manifest = ReviewImages {
            schema_version: IMAGES_VERSION.into(),
            step_sha256: "c".repeat(64),
            source_sha256: "d".repeat(64),
            engineering_approved: false,
            images: vec![entry],
        };
        util::atomic_json(&dir.path().join("manifest.json"), &manifest, false).unwrap();
        load_images(dir.path(), &"c".repeat(64)).unwrap();
        assert_eq!(
            load_images(dir.path(), &"e".repeat(64)).unwrap_err(),
            "review_images_contract"
        );
        let mut approved = manifest;
        approved.engineering_approved = true;
        util::atomic_json(&dir.path().join("manifest.json"), &approved, true).unwrap();
        assert!(load_images(dir.path(), &"c".repeat(64)).is_err());
    }
}
