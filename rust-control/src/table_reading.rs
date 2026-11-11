//! `read-table`: send prepared offset-table cell crops to the provider worker
//! and keep every receipt. The model only transcribes printed tokens; the
//! Python pipeline parses and checks them. Nothing here approves geometry.
use crate::provider::transcription::{CELL_EVIDENCE_KIND, TABLE_PROMPT};
use crate::provider::{self, ImageReceipt, ProviderInput, Purpose, Receipt, RequestState};
use crate::types::*;
use crate::util::{self, Result};
use crate::{models, worker};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::path::Path;
use std::time::{Duration, Instant};

pub const CROPS_VERSION: &str = "marinaframe.table_crops.v1";
pub const READING_VERSION: &str = "marinaframe.table_reading.v1";
const MAX_MANIFEST_BYTES: usize = 4 * 1024 * 1024;
const MAX_CELLS: usize = 4096;
/// Output tokens for one request of at most four cells. A reply is about
/// 30 tokens per cell; the rest is margin for abstain reasons.
const MAX_OUTPUT_TOKENS: u64 = 1024;
/// Batches that fail after their retries before the run stops.
const MAX_CONSECUTIVE_FAILED_BATCHES: u32 = 2;
/// Retry waits above this need an operator; the run stops instead.
const MAX_BACKOFF_SECONDS: u64 = 30;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CropCell {
    pub cell_id: String,
    pub section_id: String,
    pub cell_index: u32,
    pub crop_file: String,
    pub sha256: String,
    pub bytes: u64,
    pub width: u32,
    pub height: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CropManifest {
    pub schema_version: String,
    pub source_sha256: String,
    pub table_value_units: String,
    pub engineering_approved: bool,
    pub cells: Vec<CropCell>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ReadingCounts {
    pub cells_requested: u64,
    pub cells_transcribed: u64,
    pub cells_abstained: u64,
    pub cells_unread: u64,
    pub requests_intended: u64,
    pub requests_completed: u64,
    pub requests_failed: u64,
    pub requests_unknown: u64,
    pub requests_not_sent: u64,
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    pub observed_cost_usd: f64,
    pub requests_without_cost: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReadingRecord {
    pub schema_version: String,
    pub evidence_mode: String,
    pub engineering_approved: bool,
    pub crops_manifest_sha256: String,
    pub source_sha256: String,
    pub table_value_units: String,
    pub endpoint: String,
    pub requested_model: String,
    pub prompt_sha256: String,
    pub authorization_basis: String,
    pub receipts: Vec<Receipt>,
    pub counts: ReadingCounts,
    pub stop_reason: Option<String>,
    pub started_ms: u64,
    pub finished_ms: u64,
}

fn plain_file_name(name: &str) -> bool {
    util::valid_id(name, 128) && !name.starts_with('.') && name.ends_with(".png")
}

/// Load the crop manifest and every crop; return the crops with their bytes.
pub fn load_crops(
    directory: &Path,
    limits: &OperationalLimits,
) -> Result<(CropManifest, String, Vec<Vec<u8>>)> {
    let raw = util::read_bounded(&directory.join("manifest.json"), MAX_MANIFEST_BYTES)?;
    let manifest: CropManifest = util::parse(&raw, MAX_MANIFEST_BYTES)?;
    if manifest.schema_version != CROPS_VERSION
        || manifest.engineering_approved
        || !util::valid_hash(&manifest.source_sha256)
        || manifest.table_value_units != "feet_inches_eighths"
        || manifest.cells.is_empty()
        || manifest.cells.len() > MAX_CELLS
    {
        return Err("crop_manifest_contract".into());
    }
    let mut ids = BTreeSet::new();
    let mut crops = Vec::with_capacity(manifest.cells.len());
    for cell in &manifest.cells {
        if !util::valid_id(&cell.cell_id, 64)
            || !ids.insert(cell.cell_id.clone())
            || !util::valid_section_id(&cell.section_id)
            || !plain_file_name(&cell.crop_file)
            || !util::valid_hash(&cell.sha256)
        {
            return Err("crop_cell_contract".into());
        }
        let bytes = util::read_bounded(&directory.join(&cell.crop_file), limits.max_image_bytes)?;
        provider::check_png(&bytes)?;
        let width = u32::from_be_bytes(bytes[16..20].try_into().unwrap());
        let height = u32::from_be_bytes(bytes[20..24].try_into().unwrap());
        if util::hash(&bytes) != cell.sha256
            || bytes.len() as u64 != cell.bytes
            || width != cell.width
            || height != cell.height
        {
            return Err("crop_identity_mismatch".into());
        }
        crops.push(bytes);
    }
    Ok((manifest, util::hash(&raw), crops))
}

/// Build the provider payload for one batch of cells.
pub fn batch_payload(
    model: &str,
    cells: &[&CropCell],
    crops: &[&Vec<u8>],
) -> Result<(Value, Value, Vec<ImageReceipt>)> {
    let listing = cells
        .iter()
        .enumerate()
        .map(|(i, c)| json!({"image":i+1,"cell_id":c.cell_id}))
        .collect::<Vec<_>>();
    let prompt = json!({"task":"transcribe_offset_table_cells","expected_notation":"feet_inches_eighths",
        "cells":listing,"response_schema":{"cells":[{"cell_id":"string","token":"string, or omit and give abstain_reason"}]}});
    let mut content = vec![
        json!({"type":"text","text":String::from_utf8(util::json_bytes(&prompt)?).map_err(|_| "prompt_encoding")?}),
    ];
    let mut images = vec![];
    for (cell, bytes) in cells.iter().zip(crops) {
        content.push(json!({"type":"image_url","image_url":{"url":format!("data:image/png;base64,{}",STANDARD.encode(bytes)),"detail":"original"}}));
        images.push(ImageReceipt {
            artifact_id: cell.cell_id.clone(),
            path: cell.crop_file.clone(),
            sha256: cell.sha256.clone(),
            bytes: cell.bytes,
            mime_type: "image/png".into(),
            evidence_kind: CELL_EVIDENCE_KIND.into(),
            view: None,
            generation_id: None,
            revision_id: None,
            step_sha256: None,
            pixels_attached: true,
            crop_box_px: None,
            pixel_size: None,
        });
    }
    let messages =
        json!([{"role":"system","content":TABLE_PROMPT},{"role":"user","content":content}]);
    let payload = models::payload(model, MAX_OUTPUT_TOKENS, false, 0., messages)?;
    Ok((payload, prompt, images))
}

/// Check that a receipt belongs to its request and is internally consistent.
pub fn check_receipt(receipt: &Receipt, input: &ProviderInput) -> Result<()> {
    if receipt.protocol != provider::PROTOCOL
        || receipt.request_id != input.request_id
        || !provider::model_bound(receipt, input)
        || receipt.purpose != Purpose::TableTranscription
        || receipt.decision.is_some()
        || receipt.request_sha256 != util::hash_json(&input.payload)?
        || receipt.prompt_sha256 != util::hash(TABLE_PROMPT.as_bytes())
        || util::hash_json(&receipt.images)? != util::hash_json(&input.images)?
        || receipt.attempt != input.attempt
    {
        return Err("table_receipt_binding".into());
    }
    let completed = receipt.state == RequestState::Completed;
    if completed
        != (receipt.transcription.is_some()
            && receipt.http_status == Some(200)
            && receipt.error_code.is_none()
            && provider::returned_requested_model(receipt))
    {
        return Err("table_receipt_state_contradiction".into());
    }
    if let Some(t) = &receipt.transcription {
        t.validate(&provider::requested_cells(&receipt.images))?;
    }
    if receipt.observed_cost_usd != receipt.usage.get("cost").and_then(Value::as_f64) {
        return Err("table_receipt_cost_contradiction".into());
    }
    Ok(())
}

fn add_usage(counts: &mut ReadingCounts, receipt: &Receipt) {
    counts.prompt_tokens += receipt.usage["prompt_tokens"].as_u64().unwrap_or(0);
    counts.completion_tokens += receipt.usage["completion_tokens"].as_u64().unwrap_or(0);
    match receipt.observed_cost_usd {
        Some(cost) => counts.observed_cost_usd += cost,
        None => counts.requests_without_cost += 1,
    }
}

enum BatchOutcome {
    Completed,
    Failed,
    Stop(String),
}

struct Run<'a> {
    out: &'a Path,
    config: Config,
    record: ReadingRecord,
}

impl Run<'_> {
    fn send(&mut self, cells: &[&CropCell], crops: &[&Vec<u8>]) -> Result<BatchOutcome> {
        let (payload, prompt, images) = batch_payload(&self.config.model, cells, crops)?;
        let mut retry_of = None;
        for attempt in 1..=3u32 {
            if worker::cancelled(self.out) {
                return Ok(BatchOutcome::Stop("cancelled".into()));
            }
            let id = format!("table-{}", util::nonce());
            let pending = Pending {
                kind: "provider".into(),
                id: id.clone(),
                operation: "table_transcription".into(),
                response_path: format!("receipts/{id}.json"),
                request_path: format!("requests/{id}.json"),
                domain_before: None,
                started_ms: util::now_ms(),
            };
            let input = ProviderInput {
                protocol: provider::PROTOCOL.into(),
                request_id: id.clone(),
                source_manifest_sha256: self.record.crops_manifest_sha256.clone(),
                generation_id: "table_reading".into(),
                revision_id: self.record.source_sha256.clone(),
                observation_sha256: util::hash_json(&prompt)?,
                images: images.clone(),
                payload: payload.clone(),
                attempt,
                retry_of: retry_of.clone(),
                purpose: Purpose::TableTranscription,
            };
            util::atomic_json(&self.out.join(&pending.request_path), &input, false)?;
            self.record.counts.requests_intended += 1;
            let outcome = worker::run(
                self.out,
                &self.config,
                &pending,
                &util::json_bytes(&input)?,
                Path::new("/dev/null"),
            )?;
            let path = self.out.join(&pending.response_path);
            if !path.is_file() {
                if outcome.spawned {
                    self.record.counts.requests_unknown += 1;
                    self.record.counts.requests_without_cost += 1;
                    return Ok(BatchOutcome::Stop("provider_outcome_unknown".into()));
                }
                self.record.counts.requests_not_sent += 1;
                return Ok(BatchOutcome::Stop("provider_worker_not_started".into()));
            }
            let receipt: Receipt = util::parse(
                &util::read_bounded(&path, 2 * 1024 * 1024)?,
                2 * 1024 * 1024,
            )?;
            check_receipt(&receipt, &input)?;
            add_usage(&mut self.record.counts, &receipt);
            let state = receipt.state.clone();
            let retryable = state == RequestState::Failed
                && matches!(receipt.http_status, Some(429 | 502 | 503 | 504))
                && receipt.error_code.as_deref()
                    != Some("provider_retry_after_requires_deferred_resume");
            let wait = receipt.retry_after_seconds.unwrap_or(2u64.pow(attempt));
            let error = receipt.error_code.clone();
            if let Some(t) = &receipt.transcription {
                for cell in &t.cells {
                    if cell.token.is_some() {
                        self.record.counts.cells_transcribed += 1;
                    } else {
                        self.record.counts.cells_abstained += 1;
                    }
                }
            }
            self.record.receipts.push(receipt);
            match state {
                RequestState::Completed => {
                    self.record.counts.requests_completed += 1;
                    return Ok(BatchOutcome::Completed);
                }
                RequestState::NotSent => {
                    self.record.counts.requests_not_sent += 1;
                    return Ok(BatchOutcome::Stop(
                        error.unwrap_or("provider_not_sent".into()),
                    ));
                }
                RequestState::TransmissionOrCompletionUnknown => {
                    self.record.counts.requests_unknown += 1;
                    return Ok(BatchOutcome::Stop("provider_outcome_unknown".into()));
                }
                RequestState::Failed => self.record.counts.requests_failed += 1,
            }
            if !retryable || attempt == 3 || wait > MAX_BACKOFF_SECONDS {
                return Ok(BatchOutcome::Failed);
            }
            let until = Instant::now() + Duration::from_secs(wait);
            while Instant::now() < until {
                if worker::cancelled(self.out) {
                    return Ok(BatchOutcome::Stop("cancelled".into()));
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            retry_of = Some(id);
        }
        Ok(BatchOutcome::Failed)
    }
}

/// Read all cells of a crop directory into `out/table_reading.json`.
pub fn read_table(crops_dir: &Path, out: &Path, basis: &str) -> Result<Value> {
    if basis.trim().is_empty() || basis.chars().count() > 1024 {
        return Err("live_provider_transfer_basis_required".into());
    }
    let limits = OperationalLimits::default();
    let (manifest, manifest_sha256, crops) = load_crops(crops_dir, &limits)?;
    if out.exists() {
        return Err("table_reading_output_exists".into());
    }
    for directory in ["requests", "receipts"] {
        std::fs::create_dir_all(out.join(directory)).map_err(|_| "table_reading_output_create")?;
    }
    let config = Config {
        // The provider worker is this binary; no Python runs in read-table.
        worker_python: "/nonexistent/no-python-worker".into(),
        worker_source: None,
        source_spec: crops_dir
            .join("manifest.json")
            .to_string_lossy()
            .into_owned(),
        policy: Policy::Live,
        limits: limits.clone(),
        provider_transfer_authorized: true,
        authorization_basis: basis.into(),
        model: GO_MODEL.into(),
        binary_sha256: util::file_hash(&std::env::current_exe().map_err(|_| "binary_path")?)?,
        on_ambiguity: OnAmbiguity::Abstain,
        fallback_models: vec![],
        inspection_workers: None,
    };
    let mut run = Run {
        out,
        config,
        record: ReadingRecord {
            schema_version: READING_VERSION.into(),
            evidence_mode: "live".into(),
            engineering_approved: false,
            crops_manifest_sha256: manifest_sha256,
            source_sha256: manifest.source_sha256.clone(),
            table_value_units: manifest.table_value_units.clone(),
            endpoint: GO_ENDPOINT.into(),
            requested_model: GO_MODEL.into(),
            prompt_sha256: util::hash(TABLE_PROMPT.as_bytes()),
            authorization_basis: basis.into(),
            receipts: vec![],
            counts: ReadingCounts {
                cells_requested: manifest.cells.len() as u64,
                ..Default::default()
            },
            stop_reason: None,
            started_ms: util::now_ms(),
            finished_ms: 0,
        },
    };
    let batch = limits.max_images_per_request.max(1);
    let mut consecutive_failures = 0;
    for (cells, bytes) in manifest.cells.chunks(batch).zip(crops.chunks(batch)) {
        let cells = cells.iter().collect::<Vec<_>>();
        let bytes = bytes.iter().collect::<Vec<_>>();
        match run.send(&cells, &bytes)? {
            BatchOutcome::Completed => consecutive_failures = 0,
            BatchOutcome::Failed => {
                consecutive_failures += 1;
                if consecutive_failures >= MAX_CONSECUTIVE_FAILED_BATCHES {
                    run.record.stop_reason = Some("repeated_failed_batches".into());
                    break;
                }
            }
            BatchOutcome::Stop(reason) => {
                run.record.stop_reason = Some(reason);
                break;
            }
        }
    }
    let counts = &mut run.record.counts;
    counts.cells_unread =
        counts.cells_requested - counts.cells_transcribed - counts.cells_abstained;
    run.record.finished_ms = util::now_ms();
    util::atomic_json(&out.join("table_reading.json"), &run.record, false)?;
    Ok(
        json!({"table_reading":out.join("table_reading.json"),"counts":run.record.counts,
        "stop_reason":run.record.stop_reason,"engineering_approved":false}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fake credential; the echo check must not match the recorded body.
    const TEST_KEY: &str = "fixture-credential-not-in-any-body";

    /// A real 2x2 white grayscale PNG, as Pillow writes it.
    const PNG: &[u8] = &[
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44,
        0x52, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02, 0x08, 0x00, 0x00, 0x00, 0x00, 0x57,
        0xdd, 0x52, 0xf8, 0x00, 0x00, 0x00, 0x0e, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0xfc,
        0xcf, 0xc0, 0xc4, 0xc0, 0x00, 0x00, 0x05, 0x0d, 0x01, 0x03, 0xb8, 0x4a, 0x5c, 0x6f, 0x00,
        0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    ];

    fn crop_dir(cells: usize) -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        let mut entries = vec![];
        for i in 0..cells {
            let name = format!("c000-{i:03}.png");
            std::fs::write(dir.path().join(&name), PNG).unwrap();
            entries.push(
                json!({"cell_id":format!("c000-{i:03}"),"section_id":"st-1","cell_index":i,
                "crop_file":name,"sha256":util::hash(PNG),"bytes":PNG.len(),"width":2,"height":2}),
            );
        }
        let manifest = json!({"schema_version":CROPS_VERSION,"source_sha256":"a".repeat(64),
            "table_value_units":"feet_inches_eighths","engineering_approved":false,"cells":entries});
        std::fs::write(dir.path().join("manifest.json"), manifest.to_string()).unwrap();
        dir
    }

    fn receipt_for(input: &ProviderInput) -> Receipt {
        Receipt {
            protocol: provider::PROTOCOL.into(),
            request_id: input.request_id.clone(),
            state: RequestState::Failed,
            endpoint: GO_ENDPOINT.into(),
            requested_model: GO_MODEL.into(),
            returned_model: None,
            completion_id: None,
            provider_request_id: None,
            http_status: Some(200),
            response_sha256: None,
            request_sha256: util::hash_json(&input.payload).unwrap(),
            prompt_sha256: util::hash(TABLE_PROMPT.as_bytes()),
            source_manifest_sha256: input.source_manifest_sha256.clone(),
            generation_id: input.generation_id.clone(),
            revision_id: input.revision_id.clone(),
            observation_sha256: input.observation_sha256.clone(),
            images: input.images.clone(),
            usage: json!({}),
            observed_cost_usd: None,
            latency_seconds: 0.,
            decision: None,
            error_code: None,
            attempt: 1,
            retry_of: None,
            retry_after_seconds: None,
            aggregate_request_cap: None,
            aggregate_token_cap: None,
            aggregate_spend_cap: None,
            evidence_mode: "live".into(),
            credential_selection: None,
            purpose: Purpose::TableTranscription,
            transcription: None,
            vision: None,
        }
    }

    fn input_for(dir: &Path) -> ProviderInput {
        let (manifest, sha, crops) = load_crops(dir, &OperationalLimits::default()).unwrap();
        let cells = manifest.cells.iter().collect::<Vec<_>>();
        let bytes = crops.iter().collect::<Vec<_>>();
        let (payload, prompt, images) = batch_payload(GO_MODEL, &cells, &bytes).unwrap();
        ProviderInput {
            protocol: provider::PROTOCOL.into(),
            request_id: "table-test".into(),
            source_manifest_sha256: sha,
            generation_id: "table_reading".into(),
            revision_id: "a".repeat(64),
            observation_sha256: util::hash_json(&prompt).unwrap(),
            images,
            payload,
            attempt: 1,
            retry_of: None,
            purpose: Purpose::TableTranscription,
        }
    }

    fn completion(content: &str) -> Vec<u8> {
        serde_json::to_vec(
            &json!({"id":"cmpl-1","model":GO_MODEL,"choices":[{"finish_reason":"stop",
            "message":{"role":"assistant","content":content}}],
            "usage":{"prompt_tokens":900,"completion_tokens":40,"total_tokens":940,"cost":0.0004}}),
        )
        .unwrap()
    }

    #[test]
    fn crops_are_hash_bound_and_tampering_is_rejected() {
        let dir = crop_dir(2);
        let (manifest, _, crops) = load_crops(dir.path(), &OperationalLimits::default()).unwrap();
        assert_eq!(manifest.cells.len(), 2);
        assert_eq!(crops[0], PNG);
        let mut changed = PNG.to_vec();
        changed[40] ^= 1;
        std::fs::write(dir.path().join("c000-001.png"), changed).unwrap();
        assert_eq!(
            load_crops(dir.path(), &OperationalLimits::default()).unwrap_err(),
            "crop_identity_mismatch"
        );
    }

    #[test]
    fn manifest_cannot_claim_approval_or_escape_its_directory() {
        let dir = crop_dir(1);
        let path = dir.path().join("manifest.json");
        let original = std::fs::read_to_string(&path).unwrap();
        for (from, to) in [
            (
                "\"engineering_approved\":false",
                "\"engineering_approved\":true",
            ),
            (
                "\"crop_file\":\"c000-000.png\"",
                "\"crop_file\":\"../c000-000.png\"",
            ),
            ("\"feet_inches_eighths\"", "\"metres\""),
        ] {
            assert!(original.contains(from));
            std::fs::write(&path, original.replace(from, to)).unwrap();
            assert!(load_crops(dir.path(), &OperationalLimits::default()).is_err());
        }
    }

    #[test]
    fn table_request_passes_the_provider_input_contract() {
        let dir = crop_dir(3);
        let input = input_for(dir.path());
        assert_eq!(input.images.len(), 3);
        assert!(input
            .images
            .iter()
            .all(|i| i.evidence_kind == CELL_EVIDENCE_KIND && i.pixels_attached));
        provider::check_input(&input).unwrap();
        let raw = serde_json::to_vec(&input).unwrap();
        let parsed: ProviderInput = util::parse(&raw, 2 * 1024 * 1024).unwrap();
        assert_eq!(parsed.purpose, Purpose::TableTranscription);
        // The decision prompt or a non-crop image cannot ride on a table request.
        let mut wrong = input.clone();
        wrong.payload["messages"][0]["content"] = provider::SYSTEM_PROMPT.into();
        assert_eq!(
            provider::check_input(&wrong).unwrap_err(),
            "table_request_contract"
        );
        let mut wrong = input;
        wrong.images[1].evidence_kind = "candidate_render".into();
        assert_eq!(
            provider::check_input(&wrong).unwrap_err(),
            "table_image_contract"
        );
    }

    #[test]
    fn recorded_completion_gives_a_bound_transcription_receipt() {
        let dir = crop_dir(2);
        let input = input_for(dir.path());
        let mut receipt = receipt_for(&input);
        let body = completion(
            r#"{"cells":[{"cell_id":"c000-000","token":"18-7-4"},{"cell_id":"c000-001","abstain_reason":"blank cell"}]}"#,
        );
        provider::interpret_completion(&mut receipt, &body, TEST_KEY).unwrap();
        assert_eq!(receipt.state, RequestState::Completed);
        assert_eq!(receipt.usage["total_tokens"], 940);
        assert_eq!(receipt.observed_cost_usd, Some(0.0004));
        check_receipt(&receipt, &input).unwrap();
        // The receipt round-trips through the strict typed contract.
        let raw = serde_json::to_vec(&receipt).unwrap();
        let back: Receipt = util::parse(&raw, 2 * 1024 * 1024).unwrap();
        assert_eq!(back.transcription, receipt.transcription);
    }

    #[test]
    fn recorded_completion_for_an_unrequested_cell_fails_the_request() {
        let dir = crop_dir(2);
        let input = input_for(dir.path());
        let mut receipt = receipt_for(&input);
        let body = completion(
            r#"{"cells":[{"cell_id":"c000-000","token":"18-7-4"},{"cell_id":"c007-003","token":"2-1-0"}]}"#,
        );
        assert_eq!(
            provider::interpret_completion(&mut receipt, &body, TEST_KEY).unwrap_err(),
            "transcription_cell_not_requested"
        );
        assert_eq!(receipt.state, RequestState::Failed);
        assert!(receipt.transcription.is_none());
        check_receipt(&receipt, &input).unwrap();
    }

    #[test]
    fn decision_shaped_or_wrong_model_completion_is_not_a_transcription() {
        let dir = crop_dir(1);
        let input = input_for(dir.path());
        let mut receipt = receipt_for(&input);
        let body = completion(r#"{"tool":"finish","arguments":{},"reason":"x"}"#);
        assert!(provider::interpret_completion(&mut receipt, &body, TEST_KEY).is_err());
        let mut other = receipt_for(&input);
        let body = String::from_utf8(completion(r#"{"cells":[]}"#))
            .unwrap()
            .replace(GO_MODEL, "other-model");
        assert_eq!(
            provider::interpret_completion(&mut other, body.as_bytes(), TEST_KEY).unwrap_err(),
            "provider_model_identity"
        );
    }

    #[test]
    fn receipt_with_a_forged_transcription_or_prompt_is_rejected() {
        let dir = crop_dir(1);
        let input = input_for(dir.path());
        let mut receipt = receipt_for(&input);
        let body = completion(r#"{"cells":[{"cell_id":"c000-000","token":"1-2-3"}]}"#);
        provider::interpret_completion(&mut receipt, &body, TEST_KEY).unwrap();
        let mut forged = receipt.clone();
        forged.prompt_sha256 = util::hash(provider::SYSTEM_PROMPT.as_bytes());
        assert!(check_receipt(&forged, &input).is_err());
        let mut forged = receipt.clone();
        forged.transcription.as_mut().unwrap().cells[0].cell_id = "c999-999".into();
        assert!(check_receipt(&forged, &input).is_err());
        let mut forged = receipt;
        forged.state = RequestState::Failed;
        assert!(check_receipt(&forged, &input).is_err());
    }

    #[test]
    fn old_decision_receipts_and_requests_stay_readable() {
        let dir = crop_dir(1);
        let mut input = input_for(dir.path());
        input.purpose = Purpose::ModelDecision;
        let value = serde_json::to_value(&input).unwrap();
        assert!(value.get("purpose").is_none());
        let mut receipt = receipt_for(&input);
        receipt.purpose = Purpose::ModelDecision;
        let value = serde_json::to_value(&receipt).unwrap();
        assert!(value.get("purpose").is_none() && value.get("transcription").is_none());
        let back: Receipt = serde_json::from_value(value).unwrap();
        assert_eq!(back.purpose, Purpose::ModelDecision);
    }
}
