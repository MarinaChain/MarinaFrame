# Hard-chine reader selection (code-review item 7, second half)

Date: 2026-11-11. Branch: `lane/reader-selection` (from `continue/v0.5` at `4f03667`).
Status: protocol written before any run. `engineering_approved: false`.

## 1. Goal

Code-review item 7 (`docs/plans/2026-11-10-code-review.md`): three hard-chine readers exist and none is in the
product path. The v1 body-plan reader is frozen as a benchmark copy (`0234044`, `benchmarks/frozen_readers/v1`).
This plan selects one hard-chine reader by a fixed metric on development cases and writes the integration plan.
It does not integrate. Lane B is changing `body_plan_crossings.py`, `sheet_calibration.py` and `ingest.py`; this
lane does not edit them.

## 2. The candidates

All three read a body-plan sheet with the host calibration (`SheetLayout`) and the frozen v1 reading. Each claim
below is from `docs/BODY_PLAN_CHINE.md` and the module docstrings.

| Arm | Modules (src) | Method | Claim |
|---|---|---|---|
| 0. Frozen v1 (baseline) | `benchmarks/frozen_readers/v1` | crossings at waterline rows, chains, nesting-rank identity | the product reader when `MARINAFRAME_BODY_PLAN_READER=1` |
| A. Chine joining | `body_plan_chine.py` (146 lines) | joins one-waterline fragments to their continuation at a series of angular joins | recovers missing lower-piece cells; measured: no join fires on any dev sheet (`4232502`) |
| B. Reader v2 | `body_plan_reader_v2.py` + `body_plan_chine_line.py` (695 lines) | finds the drawn chine line; names upper pieces by nesting, lower pieces by the chine point where their own ink arrives | PARDON ME 34/57 -> 45/57 cells, RMS 0.1347 -> 0.0056 m; round-bilge sheets unchanged |
| C. Polyline (product rule) | `body_plan_polyline.py` (1,107 lines) + `engage`/`polyline_table` in `benchmarks/deadrise_holdout/score.py` | traces each station side, bottom and knuckle as a polyline; a declined half keeps the frozen table, with clear-knuckle stations engaged one by one | low-deadrise V-bottoms (COLLIER 22/31 point cells); PARDON ME 43/57, RMS 0.0355 m; round-bilge sheets unchanged |

## 3. Development cases (fixed)

Only these five sheets, with their committed harness calibrations and scorers, as in
`scripts/measure_chine_reader_v2.py`:

| Sheet | Hull | Calibration | Scorer |
|---|---|---|---|
| PARDON ME (s4) | hard chine, steep sides | `benchmarks/pardon_me/holdout_value.py` | `pardon.score` |
| BUE GIRL (s2) | round bilge (regression) | `benchmarks/bue_girl/holdout_value.py` | `bue.score` |
| C.A. Thayer (s4) | round bilge (regression) | `benchmarks/thayer/holdout_value.py` | `thayer.score` |
| Balclutha (s7) | round bilge (regression) | `benchmarks/balclutha/crossing_value.py` | `cv.score` |
| BUMBLE BEE (s2, corrected sides) | round bilge (regression) | `measure_body_plan_chine.corrected_bumble_layout` | `bumble.score` |

Excluded: E. C. COLLIER, WHITE GULL, COLLEEN and CALEB JONES. Their holdouts are spent and the chine document
calls them development cases, but their sheets and truth are under `work/holdout/`, which the lane rules
(`work/pm-briefs/common.md`) forbid a development lane to open. This lane does not open them. Their recorded
one-run verdicts (section 7) are context only; they do not enter the selection rule.

Consequence, stated before the run: PARDON ME is the only hard-chine sheet in the scored set. The four
round-bilge sheets test only that a reader leaves round-bilge drawings alone. The selection is therefore
evidence for one drawing style. The published results on these five sheets are known to this lane (section 2),
so this run is a reproduction under one harness and one commit, not a blind test.

## 4. Run rules

- One run of each arm on each sheet, from one script (`scripts/select_hard_chine_reader.py`), at one commit.
- No constant, calibration, scorer or reader change after this protocol commit. No tuning. A crash is reported as
  a crash; a fix to the measuring script (not to a reader) is allowed and is recorded.
- Truth is loaded after all four arms have read the sheet, for scoring only.
- Results go to `work/reader-selection/result.json` (git-ignored); the tables below copy the numbers.

## 5. Metric (fixed)

**M1, existing scorer.** Per sheet and arm, from the harness scorer plus `measure_chine_reader_v2.summarise`:
cells given / truth cells, RMS and maximum absolute error (m) on common cells, wrong cells (error > 0.15 m, the
harness band), identity-error stations (the harness check), extra cells (cells not in truth). Correct cells =
cells given minus wrong cells.

**M2, per-section ink distance.** Truth-free. For each arm's waterline table, one section per (half, station)
with at least two cells. Order its cells by waterline height and convert each cell to its image point
(column = centre + sign x half-breadth x px/m, row = the waterline's calibrated row). On each straight chord
between consecutive cells, take 9 equally spaced interior samples (the end points lie on the drawn waterline row,
which is ink, so they are not sampled). Distance = Euclidean distance (px) from the sample to the nearest ink
pixel of the frozen `load_ink` mask (`scipy.ndimage.distance_transform_edt` on the section's bounding box plus
a 200 px margin), divided by px/m. Per section: RMS and maximum (m). Per sheet and arm: number of sections,
median section RMS (mm), and **off-ink sections** = sections whose maximum exceeds 0.05 m. This is the same
idea as `station_overlay.ink_fit` (distance from section points to ink), applied to waterline tables. A chord
cuts a curved station, so a correct section can be some mm off ink; the metric compares arms, it is not a gate
on its own.

## 6. Selection rule (fixed)

**Eligibility.** An arm is eligible only if all hold:

1. Round-bilge no regression: on each of BUE GIRL, C.A. Thayer, Balclutha and BUMBLE BEE, cells given >= frozen,
   RMS <= frozen (1e-9 m tolerance for float noise), wrong cells <= frozen.
2. PARDON ME no regression: cells given >= frozen, RMS <= frozen, wrong cells <= frozen.
3. Extra cells on every sheet <= frozen extra cells on that sheet.

**Ranking** of eligible arms A, B, C on PARDON ME:

1. More correct cells.
2. Lower RMS.

**Tie rule.** Two arms tie when their correct cells differ by at most 1 and their RMS differs by at most
0.005 m. A tie is broken, in order, by: fewer off-ink sections on PARDON ME; lower median section RMS ink distance
on PARDON ME; fewer identity-error stations on PARDON ME; fewer src lines to integrate (section 2). If an arm
that does nothing (output identical to frozen on all five sheets) is eligible, it can be ranked but it cannot be
recommended: the recommendation is then the best arm that changes output, or "keep frozen" if none is eligible.

**No eligible arm:** recommend keeping the present product reader and integrating none.

**Margin** is reported as the difference in correct cells and in RMS between the winner and the runner-up on
PARDON ME, plus M2.

## 7. Context not in the rule (recorded verdicts, `docs/BODY_PLAN_CHINE.md`)

| Sheet (one run each) | Reader v2 | Polyline |
|---|---|---|
| E. C. COLLIER | FAIL (equal to frozen, 7/31) | dev case after: 22/31 point cells, RMS 0.069 m |
| WHITE GULL | FAIL | FAIL (both halves declined, equal to frozen) |
| COLLEEN | FAIL (9/26, RMS 0.52 m) | PASS (21/26, RMS 0.0006 m, fore half) |
| CALEB JONES | FAIL (1/30) | FAIL (16/30, identity shift by rank naming) |

If the rule's winner conflicts with this record, the recommendation says so. Integration of the winner is then
conditional on a confirmatory run of this same protocol on those four sheets, after the PM approves opening
their folders.

## 8. Resume point

- [x] Protocol committed in `f8aecbf`, before any run.
- [x] Runner `scripts/select_hard_chine_reader.py` committed in `a4d373d`.
- [x] One run at `a4d373d`, exit 0; results table (section 9).
- [x] Recommendation and integration plan (sections 10, 11).
- [x] Quick test tier (make test-quick: 1845 Python, 191 UI passed; lint, Rust, secret scan clean); branch pushed.

Next action for whoever resumes: section 11, step 0 (PM decision on the confirmatory run). Do not rerun the
selection on the five sheets; the run is spent.

Resume: check `git log` on `lane/reader-selection`; if the runner exists and `work/reader-selection/result.json`
exists, do not rerun; fill the tables from it.

Reproduce (from the worktree root):

```bash
set -o pipefail
PYTHONPATH=src:. /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python \
  scripts/select_hard_chine_reader.py \
  --sources /Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources \
  --truth-root /private/tmp/claude-501 \
  --legacy-truth-root /private/tmp/claude-501/-Users-jonathanjie-Documents-workspace/31a3f286-f3b9-4116-93bc-756e11ead9ee/scratchpad/wv-agent \
  --out work/reader-selection/result.json
```

## 9. Results (one run, commit `a4d373d`, 2026-11-11)

Evidence (git-ignored): `work/reader-selection/result.json` (sha256 `fb7d0cd7f6a7f441...`) and `stdout.txt`.
Exit 0, no crash, no script change after the run. No model calls. Truth fingerprints are in the JSON.

**PARDON ME (hard chine, 57 truth cells)**

| Arm | Cells | Correct | RMS m | Max m | Wrong | Identity errors | Extra | Ink median mm | Off-ink sections | Same as frozen |
|---|---|---|---|---|---|---|---|---|---|---|
| Frozen v1 | 34/57 | 31 | 0.134696 | 0.6372 | 3 | [6, 10, 11] | 1 | 1.04 | 0 | - |
| A. Joining | 34/57 | 31 | 0.134696 | 0.6372 | 3 | [6, 10, 11] | 1 | 1.04 | 0 | yes |
| **B. Reader v2** | **45/57** | **45** | **0.005556** | **0.0297** | **0** | **[6]** | **0** | 5.38 | 0 | no |
| C. Polyline | 43/57 | 42 | 0.035486 | 0.1621 | 1 | [6, 10, 11] | 1 | 4.36 | 0 | no |

**Round-bilge regression sheets.** All four arms give a table identical to frozen on every sheet:

| Sheet | Cells | RMS m | Wrong | Identity errors | Extra | Ink median mm | Off-ink sections |
|---|---|---|---|---|---|---|---|
| BUE GIRL | 37/39 | 0.001431 | 0 | [] | 7 | 10.01 | 1 |
| C.A. Thayer | 149/151 | 0.011616 | 0 | [] | 1 | 15.60 | 8 |
| Balclutha | 151/151 | 0.148012 | 1 | [] | 4 | 18.20 | 11 |
| BUMBLE BEE (corrected) | 50/54 | 0.148585 | 13 | [1..6] | 2 | 5.95 | 0 |

Reproduction: every number above equals the published value in `docs/BODY_PLAN_CHINE.md` (frozen baseline,
joining `4232502`, reader v2, polyline v1.1 `d026adb`). The src stroke-width scaling of item 8 did not change
any arm on these sheets.

Missing PARDON ME cells: v2 misses 12 (aft W0 of 6-8, W1 of 9, aft W-1 of 6-10, W-2 of 2-4); polyline misses 14
(all of station 1, which it does not read, and the same aft W0/W-1 cluster). The ink metric is low for every arm on
PARDON ME (no off-ink section); the lower frozen median reflects fewer, shorter sections, not better sections.
The ink metric does not separate B and C on this sheet; on the round-bilge sheets it is the same for every arm,
so its off-ink counts there describe chord sag on curved sections, not reader error.

**Rule applied (section 6).**

| Gate | A. Joining | B. Reader v2 | C. Polyline |
|---|---|---|---|
| Round-bilge no regression | pass (identical) | pass (identical) | pass (identical) |
| PARDON ME no regression | pass (identical) | pass (45 >= 34; 0.0056 <= 0.1347; 0 <= 3) | pass (43 >= 34; 0.0355 <= 0.1347; 1 <= 3) |
| Extra cells <= frozen | pass | pass (0 <= 1 on PARDON ME) | pass |
| Eligible | yes, but output identical to frozen on all five sheets: cannot be recommended | yes | yes |

Ranking on PARDON ME: B 45 correct cells, C 42, A 31. B minus C = 3 correct cells (> 1), so no tie; the tie rule
is not used. **Winner by the rule: B, reader v2.** Margin over C: +3 correct cells (45 vs 42), RMS 0.0300 m
lower (0.0056 vs 0.0355 m), 1 wrong cell fewer, identity-error stations 1 vs 3. Ink distance: both 0 off-ink
sections; median 5.38 mm (B) vs 4.36 mm (C), not used because there is no tie.

## 10. Recommendation

**Reader v2 (`body_plan_reader_v2.py` + `body_plan_chine_line.py`) is the selected hard-chine reader, with a
condition.** It wins the committed rule on the only allowed hard-chine sheet by 3 correct cells and 0.030 m RMS,
and it leaves all four round-bilge sheets unchanged.

The winner **conflicts with the record in section 7**. Reader v2 failed all four V-bottom sheets when each was a
one-run holdout (COLLIER equal to frozen; WHITE GULL and CALEB JONES worse than frozen on cells; COLLEEN 9/26 with
RMS 0.52 m against frozen 15/26 and 0.16 m, because it verified a wrong line). Its fallback ("no verified line,
keep frozen") does not protect a sheet where it verifies the wrong line. The polyline reader passed COLLEEN and
was best on COLLIER. So the evidence is: v2 for steep-sided hard chines with a drawn chine line (one sheet),
polyline for low-deadrise V-bottoms (two sheets), and neither is general. One drawing (PARDON ME) decides this
selection; that is weak evidence.

Therefore, as written in section 7 before the run: integrate v2 only after a confirmatory run of this protocol
on COLLIER, WHITE GULL, COLLEEN and CALEB JONES, with the same gates. That needs a PM decision to open
`work/holdout/` for those four spent sheets (or to copy them to a development folder). If v2 fails the gates
there, do not integrate any reader into the product path; keep frozen v1, and open a separate design item for a
combined rule (v2 where its chine line verifies and the polyline reader declines, polyline where it reads a half).
That combined rule is a new reader and needs its own protocol.

Not recommended: A (joining). It changed no output on any of the five sheets; it is dead code.

## 11. Integration plan (not started; do not start before step 0)

Step 0. PM decides the confirmatory run (section 10). Lane B must merge first: v2 calls src `body_plan_crossings`
(`follow_curve`, crossing kinds) and src `body_plan_reader`, which lane B is changing now.

Step 1. After lane B merges, rerun `scripts/select_hard_chine_reader.py` on the five sheets as a check, not a
selection: B and C must still give the section 9 numbers. Any change is a regression in lane B's work or here.

Step 2. One interface in `body_plan_intake.py`: `read_side(ink, layout, side) -> SideResult` with
`table`, `curves` (per station), `identity_source` ('rank' or 'chine point') and `flags`. `read_with_calibration`
(lines 78-110) calls it for each side instead of `measure_side` + `identities_by_rank`. Behind the existing
`MARINAFRAME_BODY_PLAN_READER` flag; default off stays. Each station record states its identity source.
v2 reads both halves together (`read_sheet` decides `hard_chine` from either half), so `read_side` takes the
pair or `read_with_calibration` calls `read_sheet` once.

Step 3. Curves: v2 gives cells, not a curve per station. Use the upper chains' path for the part above the chine
and the retraced lower-piece path below it; where neither exists, the curve is the cells only. A cell that v2
abstained on stays absent, with a flag.

What moves into the product path: `body_plan_reader_v2.py`, `body_plan_chine_line.py` (already in `src/`; they
become imported by intake). Nothing else.

What moves out of `src/`:

| File | Where | Why |
|---|---|---|
| `src/vessel_reconstruction/body_plan_chine.py` | delete (git history keeps it) | no join on any dev sheet; output identical to frozen |
| `tests/test_body_plan_chine.py` | delete with it | |
| `scripts/measure_body_plan_chine.py`, `scripts/diagnose_body_plan_chine.py` | move `fingerprint` and `corrected_bumble_layout` to `benchmarks/hard_chine/cases.py` first (three scripts import them: `measure_vbottom_dev_sheets.py`, `measure_chine_reader_v2.py`, `select_hard_chine_reader.py`), then delete both | |
| `src/vessel_reconstruction/body_plan_polyline.py` | `benchmarks/hard_chine/polyline.py` | best V-bottom evidence; keep for the combined-rule item, out of the product package |
| `tests/test_body_plan_polyline.py` | keep, new import path | |
| `benchmarks/deadrise_holdout/score.py`, `scripts/measure_vbottom_*.py`, `scripts/measure_deadrise_holdout.py`, `scripts/select_hard_chine_reader.py` | update the polyline import | |

Tests that change:

- `tests/test_body_plan_intake.py`: add `read_side` cases (synthetic round-bilge sheet gives the frozen table and
  `identity_source='rank'`; synthetic hard-chine sheet with a drawn chine line names lower pieces by chine point;
  a chine stroke on a waterline is rejected and the side falls back).
- `tests/test_reader_scale.py`: imports intake; must still pass unchanged.
- `tests/test_body_plan_reader_v2.py`, `tests/test_body_plan_chine_line.py`: unchanged.
- `tests/test_frozen_readers.py` and the three holdout-value tests: unchanged (they pin the frozen copy, not src).
- `tests/test_body_plan_chine.py`: deleted. `tests/test_body_plan_polyline.py`: import path only.
