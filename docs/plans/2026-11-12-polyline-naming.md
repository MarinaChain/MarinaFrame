# Polyline station-position naming implementation plan and fixed protocol

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Name traced hard-chine stations from independent drawing positions, so a missing or extra trace cannot shift other names.

**Architecture:** Keep tracing, engagement, scoring and the product default unchanged. Match each trace to independent station-position evidence from the drawing, not its rank or scored offsets. The current calibration does not supply that evidence; implementation and scoring have not started.

**Tech Stack:** Python, NumPy, existing body-plan readers and benchmark scorers, pytest.

`engineering_approved: false`. Branch: `lane/polyline-naming`; base: `1d503ae`.
Authority: PM briefs `polyline-naming.md` and `common.md`, dated 2026-11-12.

## Fixed development cases

Only these nine sheets may be scored:

- PARDON ME s4, BUE GIRL s2, C.A. Thayer s4, Balclutha s7, BUMBLE BEE s2 (documented corrected sides).
- E. C. COLLIER, WHITE GULL, COLLEEN, CALEB JONES: spent holdouts, now development cases.

Use the existing harness calibrations and scorers from reader-selection section 3 and sections 12-13. Truth must come from `work/dev-truth/` and the existing benchmark modules. Do not open `work/holdout/`, new holdout sheets or truth, sealed material, or candidate previews. If the four spent sheets are not available in permitted development storage, report the missing inputs; do not relocate or delete shared inputs.

## Fixed comparison arms

1. New position-named polyline reader, experimental only.
2. Polyline v1.1: the historical `d026adb` implementation used in reader-selection section 13, not today's corrected product reader.
3. Current product reader at this lane's base, including the merged station-preservation and engagement fixes. Do not label frozen v1 as the current product reader. Report frozen v1 separately if useful.
4. Reader v2, now in `benchmarks/hard_chine/reader_v2.py`.

Freeze reader hashes, runner commit, input hashes and independent position evidence before the scored run. Build all predictions before loading truth for scoring. Do not feed benchmark truth to the matcher.

## Fixed metrics and selection rule

Use existing scorers without changing bands or identity checks:

- Waterline cells on the original five sheets.
- Point cells on the four spent V-bottom sheets, plus waterline cells on WHITE GULL and COLLEEN.
- Correct cells = common cells given minus wrong cells. Wrong means absolute error > 0.15 m.
- Report given, correct, wrong, RMS, maximum error, missing/extra cells and identity errors for every arm, per sheet and cell kind.
- Sum cell counts over all nine sheets. Total RMS is common-cell-count-weighted RMS, not the mean of sheet RMS values. Keep cell kinds visible.

Accept the new reader only if **all** hold over the nine sheets:

1. Its total correct cells are at least polyline v1.1's total correct cells.
2. Its total wrong cells are no greater than the current product reader's total wrong cells.
3. It has no identity error from naming.

For gate 3, report every existing scorer identity flag. Any flag on a position-named trace fails the gate; flags on unchanged fallback curves are reported separately and cannot be silently removed. This conservative attribution avoids a post-result judgement that excuses a naming error. An empty scorer flag list alone is not proof of identity.

No gate or threshold may be widened after a result. One scored development run after synthetic tests pass. A reader failure is a result, not permission to tune. A runner-only defect may be fixed with a recorded explanation. No new holdout run belongs to this lane.

## Design review and blocker (before runs)

Source inspection only; no sheet, truth, or reader experiment was opened or run.

- `body_plan_reader.SideLayout` supplies `stations_outer_first` and buttock grid columns; it has no station-specific position reference.
- `SheetLayout` supplies centre, scale and waterline rows, not cross-view correspondences.
- `body_plan_polyline.read_half` names whole-half traces by nesting order. Its per-station engagement inherits the crossing reader's names. Neither supplies independent station identity.
- Longitudinal station spacing in a profile is not a transverse position in the body plan. Even spacing cannot safely be mapped to even nesting offsets. Doing so would be a new unsupported geometry assumption.

Recommended design: independently calibrate named image-position anchors from drawing labels or corresponding profile/half-breadth curves. Compare each trace at anchor rows, abstain on ambiguity and duplicate claims, and never shift another name or fall back to rank for a purported position identity.

Alternatives not selected: OCR-only labels (previously unsuccessful, BODY_PLAN_CHINE label-based naming section); interpolation from ordered station numbers (does not establish a body-plan position and recreates the rank assumption).

Review: architecture **WARN** (independent evidence acquisition is not yet designed); quality **PASS** (no proposed coupling to truth); tests **WARN** (end-to-end anchor acquisition is missing); performance **PASS** (small station sets). Do not implement a matcher-only stub and claim the lane is complete.

## Amendment: PM position-evidence decision (before any run)

The PM supplied the missing evidence design after checkpoint `25aa9e0`: use code-only cross-view shape matching first, existing positioned printed labels only as fallback. No reader experiment has run, so this amendment precedes results and does not relax a measured gate. The acceptance rule above is unchanged.

### Evidence and matching method (fixed)

Read independent station half-breadths at drawn waterlines from the half-breadth plan, or equivalent section samples from profile buttocks. Use existing code-only view readers and drawing calibration, never scored offsets or newly generated model readings. Keep station positions as drawn; do not assume even spacing. Keep fore/aft membership and the calibrated order within each half.

Compare section vectors in metres. Pair cost is RMS over at least **three shared drawn levels**; fewer levels provide no match. A candidate pair must have RMS **<= 0.05 m**. Solve one monotonic alignment over all sections and stations, permitting unmatched sections (cost **0.05 m** each) and skipped stations (cost **0**). This is alignment in known fore/aft order, not assignment of names by rank: any number of sections or stations may be skipped.

A name is accepted only if all hold:

1. Its assigned station is the section's unique lowest-RMS candidate among all station vectors with sufficient overlap.
2. The second-best station RMS is at least **twice** the best RMS **and** at least **0.02 m greater**. With one usable candidate, the local margin is infinite; the global alternative test below still applies.
3. Forbidding that pair and re-solving the complete alignment increases total cost by at least **0.02 m**. Equal-cost alternatives are ambiguous and remain unnamed.

Do not retry alignment after rejecting ambiguous names. Report all unmatched and rejected sections as unnamed. Missing cross-view evidence never causes rank fallback.

Only when a half has no usable cross-view station vector may existing pipeline labels supply names: a positioned label must identify a permitted station and lie within **two measured stroke widths** of exactly one section side; each section and label name must have exactly one claim. Duplicate or ambiguous claims stay unnamed. Do not add model calls or infer labels from nesting order. If the existing pipeline provides no positioned labels, leave the sections unnamed and record that fact.

The new route is experimental and does not change `MARINAFRAME_BODY_PLAN_READER` or existing product calls. Existing tracer geometry and eligibility checks are retained. Round-bilge fallback curves remain unchanged; every polyline section requires independent identity, including sections previously engaged under crossing-reader names.

### Implementation and checks

Create `src/vessel_reconstruction/body_plan_position_names.py` for vector matching and joint alignment, with tests in `tests/test_body_plan_position_names.py`. Test a missed station, extra section, uneven station spacing, a near-tie that must stay unnamed, global collision alternatives, no evidence, and positioned-label ambiguity. Exercise extraction from synthetic plan/profile ink independently of scored truth. Add a separate runner `scripts/measure_polyline_position_names.py`; preserve historical runners. Record per-half evidence source and unnamed count, per-sheet scorer identity errors for each arm, and unchanged selection gates.

Review: architecture **PASS** (separate opt-in route); quality **PASS** (truth-free matching, explicit abstention); tests **PASS** (missing/extra/uneven/near-tie paths specified); performance **PASS** (small dynamic-programming alignment, one forbidden-edge solve per proposed name). Input availability remains a preflight check, not permission to omit sheets silently.

## Amendment: printed station numbers primary (PM decision, before real-sheet runs)

The user approved the PM switch after unscored detection showed no numbered station positions. No real sheet has been scored. This pre-run amendment supersedes the evidence priority and the earlier prohibition on new model requests, not the fixed nine-sheet acceptance gates.

Primary evidence is the text and pixel box of each printed body-plan station number, read through the controller's new `station_numbers` vision purpose. Use Claude Sonnet 5.5 (`claude-sonnet-5-5`) through the existing Claude subscription transport only. Contract: `{items:[{printed,image_id,box}]}` with strict keys, finite ordered in-image boxes and known attachment IDs. An invalid root refuses the reply; an invalid item is dropped alone with its index/reason. No model-selected curve ID, station correspondence, geometry, rank or approval is accepted.

The station purpose uses one tool-free CLI turn without CLI structured-output repair, so hidden schema-repair calls cannot exceed the request budget; Rust still validates the JSON strictly. The sender caps this purpose at two attempts and Python does not retry. One request per sheet is planned. A single retry is allowed **only** for transport failure or root-contract refusal, with the same prompt/images; never retry based on scores, coverage or perceived accuracy. Hard cap: **two requests per sheet, eighteen total**, counting failed/refused calls. A refused sheet keeps every polyline section unnamed; it never restores rank names. No automatic model or provider fallback. Report subscription receipt cost and token usage; unknown cost is unknown, not zero. No billed API calls.

Image preparation follows the existing GA approach: whole-sheet overview plus overlapping higher-resolution tiles, deterministic gray PNG, at most **six images**, each <= **2048 px side**, **1,048,576 pixels**, **1,048,576 bytes**, and <= **1,400,000 raw image bytes total**. Tile the calibrated body-plan region (centre +/- max offset, and measured row span extended by one span above and below, clipped to sheet), not a manually selected label crop. Context exposes only attachment dimensions and the task, never truth values or expected station-number lists. Boxes map back through each attachment's exact crop and resize transform. Overview and tiles may contain offsets tables, but the prompt asks only for labels printed beside body-plan curves and forbids reading offset tables for identity.

Numeric interpretation: accept only an entire printed nonnegative integer token (whitespace trimmed); no inferred offsets, reindexing, plus/minus-one correction or placeholder aliases. A name must be permitted on that body-plan half. Non-numeric labels and unmatched literal numbers are reported, not guessed. The historical station-107 placeholder is not printed 107 and is not silently mapped to 7.

Fixed geometric rule: distance from the **mapped box centre** to the nearest point on a traced section side (including its ends), in original sheet pixels, must be <= **0.05 m × calibrated pixels/metre**. Exactly **one** eligible section on that half may be within that distance. Shared-knuckle traces and short-side outlines retain existing exclusions. All claims are checked together: two label claims for one curve, or the same station claimed by two curves on the same half, leave every conflicting curve unnamed. Identical overlapping-tile detections are deduplicated only when printed text agrees and mapped boxes have intersection/union >= **0.5**; keep the smallest mapped box deterministically. No nearest-wins tie break and no rank fallback. Every ambiguity is retained in the report.

Cross-view matching remains separately opt-in, with the already frozen margins, only where both views and independently numbered positions exist. It is **off in this label-primary comparison** and is not an automatic rescue for refused label replies. Round-bilge fallback output stays unchanged; a whole hard-chine half remains read even if none of its sections can be named. On a declined half with traced sections, only independently named polyline sections are emitted; rank-named crossing curves are not used to conceal unnamed polyline identity.

Before requests: commit this amendment, strict Rust purpose and parse tests, synthetic numbered-body-plan tests (missed station, extra curve, two numbers for one curve), image transforms and budget tests, and the four-arm runner. Freeze executable/source hashes and inputs. Build **all predictions on all nine sheets before opening any truth file**. Then score exactly once against historical polyline v1.1, the product reader at `1d503ae`, and benchmark reader v2, with per-sheet identity flags, unnamed counts, request usage and cost. No thresholds or gates change after results.

## Tasks and resume point

- [x] Read both briefs, relevant lessons, reader-selection sections 9-13, BODY_PLAN_CHINE, prior integration plan and naming interfaces.
- [x] Write this fixed protocol before any run.
- [x] Commit protocol before runs: `e9051e8`.
- [ ] Resolve independent station-position acquisition and permitted development inputs, without opening truth to build anchors. Present the concrete acquisition design for review before implementation.
- [ ] Write failing synthetic tests for a missed station, an extra station and uneven spacing; also mirrored halves, ambiguous matches, duplicate claims and absent anchors. Verify the failures before implementation.
- [ ] Implement only the naming change and its opt-in experimental route; keep tracing and default environment flag unchanged. Run focused tests and commit.
- [ ] Commit the four-arm runner and frozen evidence before the single scored run.
- [ ] Run once on the nine sheets; write raw per-ship evidence under ignored `work/polyline-naming/`, and aggregate report here. Report rule acceptance and identity errors explicitly.
- [ ] Run `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`, push only `lane/polyline-naming`, and remove only this worktree's `target/` after push.

## Checkpoint validation

The first quick-tier command was killed by the tool's 600-second background limit, not a test failure. The complete retry with a longer tool allowance exited 0: lint, Rust tests, 2,042 Python tests passed (4 skipped, 87 deselected), 269 UI tests passed, and secret scan passed. Logs remain under ignored `work/polyline-naming/`. Only documentation changed after that run. No reader experiment ran. Push the checkpoint to `lane/polyline-naming`; do not merge.

## Amendment implementation checkpoint

- Pre-run method and margins committed: `2b3d46b`.
- Experimental matcher and adapters committed: `c9726ea`; 13 focused synthetic tests pass. Tests cover missing/extra sections, uneven station identity spacing, near-ties, global collisions, insufficient/nonfinite evidence, label ambiguity, plan abstentions and short sections. Each new adapter was tested failing before implementation. No product imports or defaults changed.
- The existing code-only `view_reader_v2.read_views` extracts independent plan curves when profile/plan ROIs and scale are available. `plan_vectors` samples only named, finite waterline ink at calibrated longitudinal station positions; it does not use table-guided `view_measure.measure_plan`.
- Preflight source inspection found only the original five case folders under shared `work/dev-truth/`. The four spent V-bottom sheet filenames were not found under permitted shared `work/sources/`. No profile/plan ROI or positioned-label artifacts were found in those five development folders. Existing benchmark layouts supply body-plan calibration only. No truth contents or forbidden folders were opened during this preflight.
- Amendment quick tier exited 0: lint and Rust tests passed; 2,055 Python tests passed (4 skipped, 87 deselected, 5 warnings); 269 UI tests passed; secret scan passed. Log: ignored `work/polyline-naming/test-quick-amendment.log`.
- The evidence-acquisition/runner work is **not complete**. A vector adapter is not an end-to-end raster extraction test. There has been no nine-sheet run, result table, unnamed count on real sheets, or acceptance decision. No score can be inferred from synthetic tests.

## Product detection preflight after PM input decision

The PM supplied byte-identical spent-sheet copies under shared `work/dev-truth/{caleb-jones,colleen,ec-collier,white-gull}/`; `SPENT-HOLDOUTS.md` records their development status. The input-storage blocker is resolved. Only those development copies were used; no `work/holdout/` path was opened.

Runner: `scripts/preflight_polyline_position_inputs.py`, committed before detection in `3e29f82`. Initial unscored detection failed at image loading: Pillow's large-image guard and the intake text survey's RGB requirement. Loader-only fix `588863b` restored the image guard after each known development scan and supplied RGB to `intake.survey_page`. No matching threshold, reader, calibration or scoring rule changed. The corrected detection completed all nine cases without extraction exceptions.

Path: `intake.survey_page` -> `draft_fit.reference_views` -> `view_reader_v2.read_views`; `vessel_description.profile_station_lines` was attempted wherever a profile region existed. No model calls, truth loads, manual regions, guessed station identities or scoring. Scale was supplied from each existing truth-independent benchmark drawing calibration: `reference_views` consumes a scale, it does not detect one. The benchmark callers similarly obtain scale from an existing input spec.

| Sheet | Profile region | Plan region | Scale | Numbered station positions |
|---|---|---|---|---|
| PARDON ME | missing | missing | supplied, not detected | missing |
| BUE GIRL | missing | missing | supplied, not detected | missing |
| C.A. Thayer | missing | missing | supplied, not detected | missing |
| Balclutha | missing | missing | supplied, not detected | missing |
| BUMBLE BEE | missing | missing | supplied, not detected | missing |
| E. C. COLLIER | missing | missing | supplied, not detected | missing |
| WHITE GULL | detected | detected | supplied, not detected | missing |
| COLLEEN | missing | missing | supplied, not detected | missing |
| CALEB JONES | missing | missing | supplied, not detected | missing |

No unlabelled station columns were returned, including on WHITE GULL. More importantly, this code path has no printed-station-number decoder: it cannot turn detected columns into independent station identities. Assigning numbers in column order would violate the no-rank-fallback rule. No existing positioned label artifact was substituted.

Evidence is frozen under ignored `work/polyline-naming/input-preflight-rgb/`: per-sheet JSON includes source image SHA-256, detected regions, scale provenance, view-reader status, extracted plan vectors where present and missing inputs. `manifest.json` records their SHA-256 values, reader source hashes, commit `588863b176737906207680a940800b7c536f1402`, zero model calls and no scoring. Manifest SHA-256: `021579e681e2ac38c24c0bf68ceb8c0131927f6472090a2166a84fa058c76bc3`. Failed initial preflight evidence remains separately under `input-preflight/`; it was not used for selection.

Checkpoint quick tier exited 0: lint and Rust tests passed; 2,055 Python tests passed (4 skipped, 87 deselected, 5 warnings); 269 UI tests passed; secret scan passed. Log: ignored `work/polyline-naming/test-quick-preflight.log`.

**Stop/resume:** the fixed protocol requires all nine sheets and does not permit partial selection. Stop before the four-arm scored run. The separate truth-blind marking lane must supply profile/plan regions for the eight missing cases, numbered longitudinal station positions for all nine, and the mapping of drawn levels into body-plan coordinates. If fully automatic scale detection is required rather than the unchanged drawing calibrations, scale is also missing on all nine. Then finish the extraction integration and runner, hash/freeze inputs before scoring, and execute the unchanged comparison once. No real-sheet naming counts, identity scores, selection result or acceptance claim exists yet.
