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

- [x] Protocol committed (this commit), before any run.
- [ ] Runner `scripts/select_hard_chine_reader.py` committed.
- [ ] One run; results table (section 9).
- [ ] Recommendation and integration plan (sections 10, 11).
- [ ] Quick test tier; branch pushed.

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
