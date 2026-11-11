# Polyline hard-chine reader: station-naming fix and product integration

Date: 2026-11-11. Branch: `lane/polyline-integration` (from `continue/v0.5` at `960135e`, which includes lane B's
thresholds `14125aa` and the reader-selection results). `engineering_approved: false`.

User decision: choose the polyline reader (`src/vessel_reconstruction/body_plan_polyline.py`) as the hard-chine
reader, fix its station-naming errors, and integrate it into the product.

## 1. Development sheets (fixed)

Nine sheets, all development: PARDON ME, BUE GIRL, C.A. Thayer, Balclutha, BUMBLE BEE (corrected sides), and the
four V-bottom sheets E. C. COLLIER, WHITE GULL, COLLEEN, CALEB JONES (development, formerly holdout;
`benchmarks/spent_real_sheet_holdouts.json`). Only these four folders under `work/holdout/` are opened.
`work/holdout/cama_beach_skiff_22` and `work/holdout/davis_boat` are clean holdouts and are not opened; no reader
runs on them in this lane. Calibrations and scorers are the committed ones, as in
`scripts/select_hard_chine_reader.py` (five sheets) and `scripts/confirm_hard_chine_reader.py` (four sheets).

## 2. Measurement

Runner: `scripts/measure_polyline_naming.py` (this commit). Two arms from one frozen reading per sheet: frozen v1
(rank identity) and the polyline product rule (`body_plan_polyline.read_sheet` plus per-station engagement, the
same rule as `benchmarks/deadrise_holdout/score.py`). Cells: waterline cells on the five sheets (their harness
scorers); point cells on the four V-bottom sheets and waterline cells on WHITE GULL and COLLEEN (deadrise
scorers). Wrong = error > 0.15 m. Correct = given - wrong. Per sheet, kinds are summed. The product waterline
table of each arm is fingerprinted (`table_sha256`: every key and the exact float repr).

Baseline ("before"): the runner at this commit, before any reader change. Expected (published, section 13 of
`docs/plans/2026-11-11-reader-selection.md`), polyline arm, correct / wrong:

| Sheet | Correct | Wrong |
|---|---|---|
| PARDON ME | 42 | 1 |
| BUE GIRL | 37 | 0 |
| C.A. Thayer | 149 | 0 |
| Balclutha | 150 | 1 |
| BUMBLE BEE (corrected) | 37 | 13 |
| E. C. COLLIER | 20 | 2 |
| WHITE GULL | 51 | 2 |
| COLLEEN | 39 | 0 |
| CALEB JONES | 6 | 10 |
| Total | 531 | 29 |

If the baseline run differs from this table, the run is the baseline and the difference is recorded.

## 3. Gates (fixed before any change to the reader)

The naming fix is committed only if all hold, comparing the polyline arm after the fix with the baseline run:

1. **No sheet loses correct cells:** on each of the nine sheets, correct cells after >= correct cells before.
2. **Wrong cells fall:** total wrong cells over the nine sheets after < total before (29 if the baseline is as
   published).
3. **Round-bilge tables frozen:** on BUE GIRL, C.A. Thayer, Balclutha and BUMBLE BEE, the polyline product table
   equals the frozen table exactly (dict equality and equal `table_sha256`), as it does now.

The runner checks the three gates with `--baseline` (`gates.all_gates_pass`). No gate, band or threshold is
changed after a result is seen. The fix is general: no vessel name, sheet constant or truth value in the reader.

Integration gate (step 3): the integrated product entry point gives, on the nine sheets, the same tables and curves
as the fixed polyline product rule, and on the four round-bilge sheets the same product table as the existing
reader (rank names). The runner is pointed at the entry point; the per-sheet numbers must equal the fix run.

## 4. Steps and resume point

- [x] Gates and runner committed (this file, `scripts/measure_polyline_naming.py`) in `15fc1f0`.
- [x] Baseline run at `15fc1f0`: `work/polyline-integration/before.json` (sha256 `4215993d76bf64f5...`).
- [x] Cause of the CALEB JONES naming errors from the traces; general fix in the naming step with unit tests.
- [x] After run with `--baseline`: `work/polyline-integration/after.json` (sha256 `df6e637c7508645f...`); all gates pass; per-sheet table in section 5; fix commit.
- [ ] Integration: one product entry point for the body-plan side reading; v2 and chine joining out of `src/`;
  tests; integration run; integration commit.
- [ ] Re-pin the Cama Beach (`docs/BODY_PLAN_CHINE.md`) and Davis Boat (`docs/holdouts/davis-boat.md`) protocols
  to the integrated reader files' sha256, as an amendment before any run. No run on those sheets.
- [ ] Quick test tier, push the branch.

Resume: read the checkboxes; result files are in `work/polyline-integration/` (git-ignored).

Reproduce (from the worktree root):

```bash
set -o pipefail
PYTHONPATH=src:. /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python \
  scripts/measure_polyline_naming.py \
  --sources /Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources \
  --truth-root /private/tmp/claude-501 \
  --legacy-truth-root /private/tmp/claude-501/-Users-jonathanjie-Documents-workspace/31a3f286-f3b9-4116-93bc-756e11ead9ee/scratchpad/wv-agent \
  --holdout-root /Users/jonathanjie/Documents/workspace/MarinaFrame/work/holdout \
  --out work/polyline-integration/before.json
```

## 5. Results

### Baseline

The baseline run equals the published table in section 2 on every sheet (531 correct, 29 wrong).

### Cause of the CALEB JONES naming errors (from the traces, `work/lane-i/`)

Both halves of CALEB JONES are read as a whole, so names come from nesting rank. Trace by trace:

- Fore: six stations were traced with knuckles at 1511, 1501, 1415, 1234, 966 and 607 px from the centreline.
  The two at 1501 and 1415 px have sides of their own, but their bottoms run into the outermost station's
  bottom near the keel (crowded stations). `_own_bottoms` gave that bottom to the outer station, could not
  trace another for the inner two, and **dropped them**. Four stations were left and took the names 7, 6, 5, 4;
  the last three are stations 4, 3, 2 (the half-breadth plan gives chine offsets 1501 and 1414 px for stations
  6 and 5). Every inner name shifted by two.
- Aft: station 8 (knuckle 1472 px) was dropped the same way, and the transom outline (a knuckled line with a
  159 px side, against about 700 px for the station sides) was counted as a station. Names shifted by one.

### Fix (general, `body_plan_polyline.py`, module docstring step 5)

1. A station whose bottom is an outer station's, with no other bottom line, keeps its **side and knuckle**
   (`side_and_knuckle_only`) instead of being dropped, so it keeps its place in the nesting order.
2. A traced station whose side is shorter than `FRAGMENT_SIDE_SHARE` (0.5, an existing constant) of the half's
   median side is an outline (transom, stem or keel corner), not a station: it takes no rank and is listed unnamed.

No new constant, vessel name or truth value. Unit tests (synthetic drawings, `tests/test_body_plan_polyline.py`):
a station without its own bottom keeps side and knuckle; crowded stations sharing one bottom keep ranks 4-3-2-1
on both halves; a short-side outline takes no rank (before the fix that half was declined, 5 lines for 4).

### After the fix (one run, gates checked by the runner)

Polyline product rule, correct / wrong cells per sheet (wrong = error > 0.15 m):

| Sheet | Before | After | Gate 1 (correct not fewer) | Gate 3 (table = frozen) |
|---|---|---|---|---|
| PARDON ME | 42 / 1 | 42 / 1 | pass | - |
| BUE GIRL | 37 / 0 | 37 / 0 | pass | pass |
| C.A. Thayer | 149 / 0 | 149 / 0 | pass | pass |
| Balclutha | 150 / 1 | 150 / 1 | pass | pass |
| BUMBLE BEE (corrected) | 37 / 13 | 37 / 13 | pass | pass |
| E. C. COLLIER | 20 / 2 | 20 / 2 | pass | - |
| WHITE GULL | 51 / 2 | 51 / 2 | pass | - |
| COLLEEN | 39 / 0 | **43 / 0** | pass | - |
| CALEB JONES | 6 / 10 | **21 / 0** | pass | - |
| **Total** | **531 / 29** | **550 / 19** | gate 2: 19 < 29, pass | |

CALEB JONES: both halves read as a whole, named fore 7, 6, 5, 4, 3, 2 and aft 107 (the calibration's placeholder
for the left copy of 7), 8, 9, 10; 21 of 30 point cells, RMS 0.660 -> 0.028 m, no wrong cell. The harness
identity check still lists station 7 (it was [4, 5, 6, 7, 8, 9]); no station-7 cell is wrong. COLLEEN: the aft
half now keeps its station 9 (side and knuckle, its bottom ends on station 8's), so the half has three knuckled
stations and is read as a whole (7, 8, 9) instead of engaging 7 and 8 one by one: waterline cells 22 -> 23, point
cells 17 -> 20, all correct. The other seven sheets are unchanged. These are development results, not holdout
results (all nine sheets have been seen).
