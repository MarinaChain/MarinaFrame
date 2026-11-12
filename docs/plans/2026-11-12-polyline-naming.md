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

**Stop/resume:** stopped after the protocol, before naming implementation, synthetic tests and scoring. No result exists, no selection decision is possible, and no new holdout material was opened. Next substantive action is to resolve the independent drawing-position input and review that acquisition design. Do not rerun a campaign to discover anchors from truth.
