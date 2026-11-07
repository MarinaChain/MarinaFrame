# Offset-table reading with the DeepSeek vision model (first slice)

Status: implemented as described below (2026-11-07). It replaces the removed Tesseract path
(`offset_table_ocr`). Archived OCR runs still verify; new OCR specs stay rejected.

## Goal

Read the printed half-breadth tokens of an offset table from source pixels, with the model as a
narrow transcriber. Every value that reaches CAD must come from one printed token in one
human-declared cell crop, sent to the model with recorded pixel hashes, and must pass a strict
deterministic parser. Any doubt becomes a blocking gap. Nothing is guessed or repaired.

## Flow and ownership

```
spec.json (input_mode offset_table_vision, human-declared cells)
  │ 1. Python: python -m vessel_reconstruction.table_vision prepare --spec S --out CROPS
  │    deterministic grayscale cell crops (PNG) + crops manifest (hashes, sizes)
  ▼
CROPS/manifest.json + CROPS/*.png
  │ 2. Rust: marinaframe read-table --crops CROPS --out READ --provider-transfer-basis TEXT
  │    batches of <= 4 crops; each batch is one supervised provider-worker request
  ▼
READ/table_reading.json (all receipts, transcriptions, counts) + READ/requests, READ/receipts
  │ 3. Python pipeline: spec.table_reading.file -> READ/table_reading.json
  │    recompute crops from the captured source, bind receipts by crop hash,
  │    strict parse, checks, sections or blocking gaps, CAD loft, sealed run record
  ▼
run directory (verify_run checks the reading record is captured and hash-bound)
```

- **The model call happens only in Rust.** `read-table` builds the request and starts the same
  `provider-worker` subprocess as `live_decision` (same supervision, timeouts, key rotation,
  usage meters, credential-echo checks). No Python HTTP client is used or extended.
- Python is a subordinate worker. It prepares crops and checks results. It never contacts a
  provider.

## What the model receives and may return

- Input: one system prompt (`TABLE_PROMPT` in `rust-control/src/transcription.rs`),
  a text block that lists `cell_id` per image, and the cell crops as PNG data URLs. The model
  does not receive station positions, waterline heights, units of the vessel or other cells.
- Output: exactly `{"cells":[{"cell_id":ID,"token":TEXT}|{"cell_id":ID,"abstain_reason":TEXT}]}`.
  - One entry for each requested cell, no other cell ids, no duplicates.
  - `token`: the printed characters, 1..32 printable ASCII characters. No conversion, no unit
    change, no digit correction.
  - `abstain_reason`: up to 200 characters when the crop is unreadable or ambiguous.
  - Unknown fields, a missing cell, an unrequested cell, or both/neither of token and abstain:
    the whole response is rejected (`state: failed`, `error_code` names the contract).
- The model never returns a number for CAD, a coordinate, a path, code or a policy. The
  token text is data. The number comes only from the Python parser.

## Deterministic checks (Python, `table_vision.py`)

Per cell, in order; the first failure is a blocking gap on that station:

| Check | Gap kind |
|---|---|
| No completed receipt has an image with this `cell_id` | `table_cell_unread` |
| Receipt image hash differs from the crop recomputed from the captured source | `table_cell_pixels_mismatch` |
| Two completed readings of the cell disagree | `conflicting_table_readings` |
| Model abstained | `table_cell_abstained` |
| Token is not strict feet-inches-eighths (`F-I-E`, inches 0..11, eighths 0..7) | `ambiguous_table_cell` |
| Value exceeds half of the declared `constraints.beam_m` (with its tolerance) | `table_value_out_of_range` |

Record-level checks (blocking, whole table): reading record schema, `engineering_approved`
must be false, source hash must match the captured source, model identity must be
`deepseek-v4.1-flash`, and a transcription entry for a cell that was not an image in the same
request is rejected (`table_reading_unrequested_cell`).

Consistency: a half-breadth that decreases with height gives a `warning` gap
(`non_monotonic_station`), not a block, because tumblehome is real. Hull-shape priors are not
used to correct or reject values.

Units: `table_value_units` must be `feet_inches_eighths`. Other notations are rejected
(`table_units_unresolved`). Output geometry is metres. Unit marks (`'`, `"`) or decimals in a
token make it ambiguous; they are not stripped.

## What is recorded

- Crops manifest: per cell `cell_id`, section, cell index, crop file, SHA-256, bytes, width,
  height, and the source SHA-256.
- Per request (existing `Receipt` type, extended): `purpose: table_transcription`, request and
  prompt hashes, `images` (crop SHA-256, bytes, `pixels_attached`), requested/returned model,
  completion id, HTTP status, usage tokens and cost, credential slot selection (never a key),
  `transcription`, `error_code`, attempt and retry links.
- The reading record keeps every receipt, also failed and not-sent ones, plus counts:
  requests intended/completed/failed/unknown/not sent, cells requested/transcribed/abstained/
  unread, prompt and completion tokens, observed cost, requests without cost.
- The pipeline captures the reading record into the run as `table_reading.json`. Its hash is
  part of the run identity and is checked by `verify_run`. Each section's cell evidence holds
  the token, request id, completion id and crop hash.

## Engineering approval

`engineering_approved` stays false at every level: the reading record must say false, the run
review state is fixed to unreviewed, and a review-ready status means only "candidate for human
review". A model transcription is not a label; it is never gold data.

## Deliberately out of scope

- Finding the table, cells, stations or waterline heights automatically. A human declares
  them (`roi_px`, `x_m`, `z_m`), as with the OCR path.
- The Rust live controller loop (`run --policy live`) and its `DomainTools` agent still accept
  only `calibrated_section_curves`. Table runs use the batch pipeline.
- Notations other than feet-inches-eighths; decimal metre tables.
- Model self-consistency voting, second reads, or cross-model comparison. A second read can be
  added later as a disagreement check; it is not proof of correctness.
- Resume of an interrupted `read-table`: the receipts stay on disk, but the reading record is
  written only at the end; rerun into a new directory.
- Accuracy claims. Only synthetic tables were read. No licensed drawing was sent.

## Code and tests

| Part | File |
|---|---|
| Model contract, prompt | `rust-control/src/transcription.rs` |
| Purpose field, `interpret_completion`, table input check | `rust-control/src/provider.rs` |
| `read-table` command, receipt binding, batching, stop rules | `rust-control/src/table_reading.rs` |
| Controller rejects table receipts in the decision loop | `rust-control/src/controller.rs` (`apply_provider`) |
| Crops, parser, checks | `src/vessel_reconstruction/table_vision.py` |
| Spec, budget, run capture, run verification | `schema.py`, `resources.py`, `pipeline.py`, `run_record.py` |
| Synthetic table generator | `examples/make_table_example.py` |
| Tests | `tests/test_table_vision.py`, `rust-control/tests/table_reading_cli.rs`, unit tests in the Rust modules |

No test uses the network. Recorded provider bodies go through `interpret_completion`; injected
read-table records go through the Python checks; `read-table` without keys is run end to end.

Batching: at most 4 crops per request (`max_images_per_request`), 1024 output tokens, retries
only for HTTP 429/502/503/504 (3 attempts, wait at most 30 s). The run stops at the first
not-sent or unknown request and after 2 consecutive failed batches. No aggregate cap.

## Live check (2026-11-07, synthetic table only)

Run with `examples/make_table_example.py` (4 stations x 5 waterlines, 20 printed cells),
`table_vision prepare`, then `read-table` with the keys loaded by
`scripts/load_opencode_keys.sh`.

| Step | Requests | Completed / failed / unknown / not sent | Cells read / abstained | Prompt / completion tokens | Reported cost |
|---|---|---|---|---|---|
| Image probe, 1 cell | 1 | 1 / 0 / 0 / 0 | 1 / 0 | 485 / 23 | 0.0 USD (`go`; list 0.00008655) |
| Full table, 20 cells | 5 | 5 / 0 / 0 / 0 | 20 / 0 | 5665 / 370 | 0.0 USD (`go`; list 0.00107175) |

- Requested and returned model: `deepseek-v4.1-flash` on every receipt. Key slot 1 was chosen
  (48 % highest window); slots 2 and 3 were exhausted.
- Image support is confirmed: the probe returned `6-0-5`, a token that exists only in the crop
  pixels.
- 20 of 20 tokens equal the printed tokens. The pipeline run on this reading was
  `review_required` with no gaps, exported STEP, and `verify_run` was valid.
  `engineering_approved` stayed false.
- This is one clean synthetic table in a sans-serif font. It says nothing about scanned,
  handwritten or degraded historical tables.

## Open risks

- Crop identity depends on deterministic PNG encoding by the locked Pillow version. A Pillow
  change can change hashes and then blocks every cell (`table_cell_pixels_mismatch`); it fails
  closed.
- Telling the model the expected notation can bias it to produce a well-formed but wrong token.
  The parser checks form, not truth. Human review of every cell remains required.
