# Model investigation of crowded drawings (W11)

Date: 2026-11-08. Base `725029d` (branch `continue/v0.5`), factory merged from `b9c89cb`.
Every result keeps `engineering_approved=false`. Gunnerus is development data.

## 1. Boundary (founder and CEO decisions)

- Provider transfer of any acquired drawing is authorized ("you can send any of them to deepseek",
  `docs/CONTINUATION_STATUS.md`). Every image sent is in a receipt with its SHA-256, byte size,
  pixel size and sheet crop box.
- The model decides how to investigate: any region, any zoom, any order, any tool, any number of
  calls. There is no aggregate call, token or spend cap. Per-request time limits, retries with
  back-off, cancellation and no-progress stops stay.
- The model may not write free coordinates, run code, change files, paths, policy or gates, grade
  its own work or approve anything. A model choice is a guess in draft mode; only a person
  confirms it; the Rust controller alone decides review readiness.

## 2. Tools (live policy, `--on-ambiguity draft` only)

| Tool | Arguments (bounded in `types.rs` and again in Python) | Executed by the harness | Returns |
|---|---|---|---|
| `view_region` | sheet rectangle, max side 256–1024 px | crop, enlarge at most 4x or reduce, red ticks every 100 view px | pixels (PNG <= 190 KB, <= 1 Mpx), view id, crop box, scale |
| `read_region` | sheet rectangle, subject (labels, scale bar, dimensions, title block) | same as a view | pixels; what the model reads is its claim |
| `trace_corridor` | section, view id, 2–24 points in that view's pixels, half width 1–64 view px | engine tracer (`ingest._trace`) inside the corridor, on the corridor's rows; then the engine itself re-reads the traced ink in a 2.75 px corridor (`_extract_one`) | a candidate (`model_traced`) with support scores, or a refusal with the reason and an image of the refused corridor |
| `assign_station` | section, candidate id, label view id, label text, reason, optional comparison id | station-identity verifier | an open guess of kind `model_choice` |
| `propose_sheet_setup` | view, rectangle, px/m, grid spacing, optional datum lines, evidence view, scale claim, reason | grid and datum verifier | an accepted setup (for comparisons only) or a refusal |
| `compare_views` | section, candidate, plan setup, 1–12 heights | body-plan half-breadths against ink on the plan-view station line | match table and pixels |
| `ask_person` | question (<= 512 chars) | stops the task (`paused`, `model_asked_person`) | — |
| existing | `inspect_source`, `select_contours`, `build_draft` (rebuild), `render_candidate`, `validate_candidate`, `finish` (submit) | unchanged | — |

Before the first model call the harness inspects every section and selects the unique lines, as
the deterministic draft policy does (`investigation_preparation`); no model call is spent on it.

## 3. Deterministic verifiers

| Proposal | Checks (all must pass; a failure returns to the model as an observation with the reason) |
|---|---|
| corridor trace | ink on >= 90 % of the traced rows, gaps <= 2.5 %, long-component support >= 0.65 (engine thresholds); span >= 25 % of the section height and >= 50 % of the corridor rows; bounded corridor representation; the engine accepts the line in its own tight corridor (coverage, gap, ambiguity, side checks). The vertical range of a line that ends inside the calibrated range is where its ink ends, never a model value. |
| station assignment | candidate is in this section's catalog, selectable and snapped (Rust also checks: coverage >= 0.9, a corridor, `snap.passed` for a traced line); the section is not already selected; the label view is pixels the model received (a view or an inspection image) and overlaps the section's panel; the same ink is not assigned to another section or selected there (2 px on 80 % of shared rows); a named comparison exists for this section and candidate |
| sheet setup | a regular grid of long straight lines exists in the region and its spacing equals px/m x grid spacing within 2 % (whole multiples allowed); every claimed datum lies within 3 px of a long straight line; for a body view, it agrees with the declared section calibration (1 % scale, 3 px datum). The build always keeps the declared calibration. |
| receipt | the raw response body is stored; Rust re-hashes it and re-derives decision, model, completion id and usage; any difference is refused |

## 4. How autonomy and limits are enforced (Rust)

- `Operation` allowlist: 14 typed tools with `deny_unknown_fields`; no tool sets a status, a gate, a
  tolerance, a path or code. Investigation tools are refused outside draft mode.
- `validate_selection`: a policy can never select a model-traced line
  (`model_traced_candidate_requires_person`) or a line with a non-grid competitor, never confirm a
  guess (`guess_requires_operator_confirmation`), and can assign only snapped ink.
- `check_guess_contract`: a `model_choice` guess must name snapped ink and carry verifier evidence
  with `passed: true`, `identity_certified: false`, at most 4 KB; it is part of the generation id.
- `validation::ready` refuses any open guess first (`draft_guesses_open`); `finish` with open guesses
  stops at `draft_not_verified`. The model's own `build_draft` does not stop the task (it can render
  and revise); its `finish` builds the current draft if needed and then stops.
- Refused proposals (13 codes) and refused model output (HTTP 200, not one valid tool call) return
  to the model as observations; more than `2 x max_repeated_action` consecutive refusals, 3 identical
  actions in one generation, or 40 model decisions without a new generation or build stop the task
  (`no_progress`). Retries: HTTP 429/502/503/504, 3 attempts, wait <= 30 s.
- Receipts: purpose `investigation` and its prompt hash are bound; images carry `crop_box_px` and
  `pixel_size` (checked against the PNG header by the provider worker).

## 5. Tests and mutation check

`rust-control/tests/investigation_guards.rs` (7 quick tests, 1 real CAD), controller unit tests
(receipt forgery, mode binding, snapped assignment, draft-mode tools, refusal counting), validation
unit test (`model_choice` contract), `tests/test_investigation.py` (7 tests).

Mutation check (one guard removed at a time; the named tests must fail): 11 of 11 caught —
model-traced selection, unsnapped assignment, unknown candidate, unsnapped `model_choice`,
evidence `passed`, receipt body re-derivation, receipt purpose binding, draft-mode-only tools,
policy guess confirmation, open guesses block readiness, argument bounds.
Not covered by a mutation: the engine re-read inside `corridor_trace` (no fixture makes the
engine refuse ink that the corridor tracer accepted) and the no-progress counters' stop condition.

## 6. Evaluation

See `docs/LLM_LINE_IDENTITY.md` for the completed continuation design, verification evidence and three-arm development evaluation. This note is the historical pre-continuation design; current test counts and limitations are in that report.
