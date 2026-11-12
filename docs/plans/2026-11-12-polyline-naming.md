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

## Tasks and resume point

- [x] Read both briefs, relevant lessons, reader-selection sections 9-13, BODY_PLAN_CHINE, prior integration plan and naming interfaces.
- [x] Write this fixed protocol before any run.
- [ ] Commit protocol. Record its commit in the final report.
- [ ] Resolve independent station-position acquisition and permitted development inputs, without opening truth to build anchors. Present the concrete acquisition design for review before implementation.
- [ ] Write failing synthetic tests for a missed station, an extra station and uneven spacing; also mirrored halves, ambiguous matches, duplicate claims and absent anchors. Verify the failures before implementation.
- [ ] Implement only the naming change and its opt-in experimental route; keep tracing and default environment flag unchanged. Run focused tests and commit.
- [ ] Commit the four-arm runner and frozen evidence before the single scored run.
- [ ] Run once on the nine sheets; write raw per-ship evidence under ignored `work/polyline-naming/`, and aggregate report here. Report rule acceptance and identity errors explicitly.
- [ ] Run `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`, push only `lane/polyline-naming`, and remove only this worktree's `target/` after push.

**Stop/resume:** stopped after the protocol, before naming implementation, synthetic tests and scoring. No result exists, no selection decision is possible, and no new holdout material was opened. Next substantive action is to resolve the independent drawing-position input and review that acquisition design. Do not rerun a campaign to discover anchors from truth.
