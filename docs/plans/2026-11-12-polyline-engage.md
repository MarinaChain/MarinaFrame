# Polyline engagement on a flat-bottom hard chine (lane N)

Date: 2026-11-12. Branch: `lane/polyline-engage` (from `continue/v0.5` at `3865d8c`). `engineering_approved: false`.

## 1. Problem

On CAMA BEACH SKIFF No. 22 (14 ft flat-bottom hard-chine skiff; published holdout run 2026-11-11, FAIL) the
polyline reader declined both halves (aft 1 of 11 traced lines with a sharp knuckle, fore 2 of 15) and the product
gave the crossing reader's cells for all stations but one (fore station 2 engaged). Stations 2, 3, 8, 9 show a
constant 0.04 to 0.11 m offset with identity errors: probably curves named after a neighbour.

Goals: find why polyline did not engage, and why the crossing reader misnames 2, 3, 8, 9; fix generally (no vessel
name, no truth value, no new constant without a one-line reason) with unit tests on synthetic drawings
(flat-bottom chine, V-bottom, round bilge).

## 2. Sheets (all development)

Eleven sheets: PARDON ME, BUE GIRL, C.A. Thayer, Balclutha, BUMBLE BEE (corrected sides), E. C. COLLIER, WHITE GULL,
COLLEEN, CALEB JONES, CAMA BEACH SKIFF No. 22, Davis Boat. Cama Beach and the Davis Boat are spent holdouts
(`benchmarks/spent_real_sheet_holdouts.json`); **their numbers after this work are development numbers, not holdout
numbers**. No other holdout or sealed folder is opened. Calibrations and scorers are the committed ones.

Runner: `scripts/measure_polyline_engage.py` (the nine sheets of `scripts/measure_polyline_naming.py`, plus Cama Beach
and Davis with the deadrise scorers: waterline and point cells). Wrong = error > 0.15 m; correct = given - wrong;
kinds summed per sheet. Round bilge = BUE GIRL, C.A. Thayer, Balclutha, BUMBLE BEE, Davis Boat.

## 3. Gates (fixed before any change to the reader)

The change is committed only if all hold, comparing the polyline arm after the change with the baseline run of the
runner at the commit that adds this file:

1. **No sheet loses correct cells:** on each of the eleven sheets, correct after >= correct before.
2. **Total wrong cells do not rise:** total wrong after <= total wrong before (eleven sheets).
3. **Round-bilge tables unchanged:** on the five round-bilge sheets the polyline product table has the same
   `table_sha256` as the baseline and equals the frozen table.

Checked by the runner with `--baseline` (`gates.all_gates_pass`). No gate, band or threshold is changed after a
result is seen.

## 4. Steps and resume point

- [x] Gates and runner committed (this file, `scripts/measure_polyline_engage.py`) in `1a33fee`.
- [x] Baseline run: `work/polyline-engage/before.json` (exit 0). Reader at `1a33fee` (loaded before any edit;
  its `polyline_sha256` field was hashed at write time and shows an edited file); Cama calibration at
  `aa88271` (corrected; the engaged fore station is named 1, not the published 2). The nine original sheets
  equal the published polyline-integration result (550 correct, 19 wrong); total 612 correct, 29 wrong.
- [x] Diagnosis on Cama Beach (section 5).
- [x] General fix with synthetic tests (uncommitted until the gates pass; synthetic tests pass).
- [x] Cama trace check of the fix: fore stations 2 to 6 traced (chines within 1 to 8 px of the printed
  chines), aft 7 traced.
- [x] After run 1, reader sha256 `a1629f5de3822a0e...` (`work/polyline-engage/after.json`): **gates fail**.
  Cama Beach 22 correct / 10 wrong -> 33 / 0 (both halves read: aft 7, 8; fore 6, 5, 4, 3); round-bilge tables
  unchanged; eight other sheets equal; but COLLEEN 43 / 0 -> 28 / 11 (fore names 6 to 1 instead of 6 to 2,
  identity errors 1 to 5; aft no longer read as a whole). Total wrong 29 -> 30. Not committed.
- [x] COLLEEN diagnosis: on both halves a line far below the hull (side rows 3622 to 4392 at about 1400 px,
  a frame or box edge) meets a long level line at row 4393 (turn 90 degrees) that ends 318 / 349 px from the
  centreline: it was taken as a level bottom, so fore had six stations (names shifted) and aft four for three
  (declined). Fix: a level bottom must run on to the centreline, its inner end within `CENTRE_CLEAR_WIDTHS`
  (existing constant: "this close to the centre column is the centreline or keel") line widths of the centre
  column (Cama's level bottoms end 0 to 3 px from it). Synthetic test: a box corner below a flat-bottom half.
- [x] After run 2 (`work/polyline-engage/after2.json`, sha256 `3cd23e5b22ebc17b...`; baseline `before.json`
  `6e22bb5ecedec67e...`), reader sha256 `735d2209b76bd398...`: **all gates pass** (section 5).

**Truth files (PM, 2026-11-12).** The legacy truth of C.A. Thayer (`thayer/truth_s4.json`) and Balclutha
(`balclutha/truth_s7.json`) was deleted from the shared scratchpad (`wv-agent/`) in a disk cleanup; no backup
exists. The baseline and after run 1 used the old files. The runner (`0d8eda0`) carries a baseline score over for
a sheet whose truth file is missing only when both arms' tables are byte-identical to the baseline (equal tables
give equal scores; PM confirmed), and stops otherwise. From after run 2's restart on, both truth roots are
`work/dev-truth` (PARDON ME, BUE GIRL and BUMBLE BEE there are byte-identical to the files the baseline used;
after run 2 itself was started with the old paths, which give the same bytes). A new lane re-transcribed
Thayer sheet 4 and Balclutha sheet 7 into `work/dev-truth` (two blind transcriptions agree on every cell; all
files match `work/dev-truth/SHA256SUMS`). PM check: on the current product reader the **restored truth
reproduces the published values exactly** (Thayer 149 of 151 cells, 0 wrong, RMS 0.011616 m; Balclutha 151 of
151, 1 wrong, RMS 0.148012 m). So the fallback was reverted (`6afc0b2`), and after run 2 was stopped and started
again with both truth roots at `work/dev-truth`: every sheet is scored against its truth. The baseline used the
old Thayer and Balclutha files; with the restored truth reproducing them exactly, the comparison holds.
- [x] Reader change and tests committed after the gates passed.
- [x] Quick test tier at `762e0a9` (exit 0; Python 1910 passed, 76 deselected; Rust and UI ok; a first attempt
  was stopped from outside by SIGTERM and run again); branch `lane/polyline-engage` pushed (no merge).

Resume: read the checkboxes; result files are in `work/polyline-engage/` (git-ignored). Uncommitted work at a
pause is in the worktree (`git diff`): `body_plan_polyline.py` and `tests/test_body_plan_polyline.py`.

Reproduce (from the worktree root):

```bash
set -o pipefail
PYTHONPATH=src:. /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python \
  scripts/measure_polyline_engage.py \
  --sources /Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources \
  --truth-root /Users/jonathanjie/Documents/workspace/MarinaFrame/work/dev-truth \
  --legacy-truth-root /Users/jonathanjie/Documents/workspace/MarinaFrame/work/dev-truth \
  --holdout-root /Users/jonathanjie/Documents/workspace/MarinaFrame/work/holdout \
  --out work/polyline-engage/before.json
```

## 5. Results

### Diagnosis (Cama Beach, development case)

**Why polyline declined.** Per-trace outcome of `read_half` (frozen reader code at `1a33fee`): aft 11 lines traced,
1 with a knuckle (5 "no bottom branch", 5 short lines); fore 15 traced, 2 with a knuckle (6 "no bottom branch",
7 short lines). The sides are found. Each station's bottom is drawn **level** from its knuckle to the centreline (a
flat bottom; the rows differ by station because of rocker), and the drawn chine curve rises inward from each
knuckle. `_bottom` accepted only a branch that descends by `BOTTOM_MIN_DESCENT_SHARE` (2 % of its length), so a
level bottom never qualified; the chine curve is rejected because it rises. The two fore stations that were
traced (chines at offsets 520 and 697 px) have bottoms drawn with a slight slope. A second cause on the same
sheet: the calibration adds measuring rows below the base line (rows 3260 to 3410) that are **not drawn**, and the
grid-line test (`on_grid_line` against every calibrated row, band 2 line widths + 3 px) rejected level bottoms
lying near them (fore bottom at row about 3420 against the row 3410).

**Why 2, 3, 8, 9 carry a neighbour's name** (the frozen table against the printed offsets):

- Aft: the curves named 8, 9, 10 read the printed offsets of stations **7**, 8, 9 within 1 to 2 mm (for example
  "8" at W0 to W9 0.440 / 0.485 / 0.528 / 0.572 against station 7's 0.441 / 0.484 / 0.529 / 0.572).
- Fore: the curve named 2 reads station 3 at W0 to W3 within 1 mm (0.376 / 0.398 / 0.420 / 0.443 m against
  0.376 / 0.398 / 0.421 / 0.443), and "3" reads station 4 (0.441 / 0.469 / 0.497 / 0.526 against 0.441 / 0.468 /
  0.497 / 0.525).
- Cause, mainly the **calibration**: the table's station n is the body-plan curve labelled n + 1 on both halves.
  At W3 the printed offsets of 1 to 9 (384, 650, 872, 1033, 1128, 1156, 1126, 1047, 953 px) equal the
  calibration's own half-breadth-plan readings for the profile lines labelled 2 to 10; near W6 the right curves
  (1084, 1065, 984, 832, 616, 360 px) are table 6 to 1 and the left curves (1048, 971, 876 px) table 7, 8, 9.
  So the left half is table 7, 8, 9 and the heavy line read as the transom outline is 10; the right half is
  table 6 to 0. No station is drawn on both halves (an earlier note in this lane, sent to the PM, called the
  left outermost line "station 7 drawn again"; that was wrong: it is table 7, drawn once).
- Crossing reader, fore: two short chains below the base line ("4" and "5" in the published table, W0 and below
  only) take ranks 3 and 4, so the inner curves are named two ranks too far in; with the published names the two
  errors partly cancelled (net shift one).

**Calibration correction (PM decision, `aa88271`).** Cama Beach is a spent holdout, so its calibration was
corrected for development use: aft (7, 8, 9, 10), fore (6, 5, 4, 3, 2, 1, 0). The correction uses evidence from
the printed offsets (truth-informed). The published holdout result is not re-scored and stays FAIL; every Cama
number below is a development number. The gate baseline for Cama is the reader at `1a33fee` with this corrected
calibration (the runner imports a calibration module when it reaches the sheet; the Cama record's `named` lists
show which calibration it used, and the baseline is rerun if they show the old one).

**Fix (general, `body_plan_polyline.py`).**

1. A level branch (one that neither descends by `BOTTOM_MIN_DESCENT_SHARE` nor rises above its start by a line
   width) is a flat bottom. It is taken only when no descending branch leaves the side, so every V-bottom choice
   is unchanged. Selection among level branches uses the same rule as for descending ones.
2. For a level branch, the grid-line test uses only the calibrated rows that are drawn (`drawn_rows`: on
   each half, ink on the row, one pixel either side for the calibration's rounding, at more than `GRID_SHARE`
   of the half's columns). Descending branches keep the test against every calibrated row. A first version
   (ink within half a line width plus 1 px, across both halves together) called Cama's undrawn row 3410
   drawn: the aft bottom of station 7 (about row 3403) and the fore bottoms (about 3420) each lie a few pixels
   from it (coverage 0.64 / 0.67 per half at +-5 px). Measured on Cama at +-1 px: drawn W0 to W3 and the base
   line 0.79 to 1.00 on each half, the eight undrawn measuring rows 0.01 to 0.12.
3. The polyline keeps rows strictly decreasing: a level bottom is stored as its rabbet end and the knuckle
   (`LEVEL_ROW_STEP_PX` = 0.5 px: twice the 0.25 px rise `_monotone` needs to keep the knuckle); the traced
   bottom is kept in `level_bottom` for the bottom-ownership test.

No vessel name or truth value; one new constant with its reason. Synthetic tests: flat-bottom half on both sides
(traced, named 4-3-2-1, knuckles, rabbets; one bottom 5 px from an undrawn measuring row), its table, `drawn_rows`,
and a V-bottom with a level line through its knuckles that keeps its descending bottoms. Before the fix the
flat-bottom half was declined ("no bottom branch" for 3 of 4 lines), as on Cama. Rule 4 (after run 1, COLLEEN):
a level bottom must end within `CENTRE_CLEAR_WIDTHS` line widths of the centre column (a box corner below a
flat-bottom half is the synthetic test).

### After the fix (after run 2; development cases only)

Polyline product rule, cells given / correct / wrong per sheet (wrong = error > 0.15 m; kinds summed). Baseline:
reader at `1a33fee`, Cama calibration corrected (`aa88271`). **Cama Beach numbers are development numbers, not
holdout numbers** (spent holdout; truth-informed calibration; the published FAIL stands). Thayer and Balclutha are
scored against the restored truth in `work/dev-truth`, which reproduces the published values exactly.

| Sheet | Before (given / correct / wrong) | After | Gate 1 | Gate 3 (round bilge: table unchanged) |
|---|---|---|---|---|
| PARDON ME | 43 / 42 / 1 | 43 / 42 / 1 | pass | - |
| BUE GIRL | 37 / 37 / 0 | 37 / 37 / 0 | pass | pass |
| C.A. Thayer | 149 / 149 / 0 | 149 / 149 / 0 | pass | pass |
| Balclutha | 151 / 150 / 1 | 151 / 150 / 1 | pass | pass |
| BUMBLE BEE (corrected) | 50 / 37 / 13 | 50 / 37 / 13 | pass | pass |
| E. C. COLLIER | 22 / 20 / 2 | 22 / 20 / 2 | pass | - |
| WHITE GULL | 53 / 51 / 2 | 53 / 51 / 2 | pass | - |
| COLLEEN | 43 / 43 / 0 | 43 / 43 / 0 | pass | - |
| CALEB JONES | 21 / 21 / 0 | 21 / 21 / 0 | pass | - |
| CAMA BEACH (development) | 32 / 22 / 10 | **33 / 33 / 0** | pass | - |
| Davis Boat | 40 / 40 / 0 | 40 / 40 / 0 | pass | pass |
| **Total** | **641 / 612 / 29** | **642 / 623 / 19** | gate 2: 19 <= 29, pass | |

Cama Beach after: both halves read as a whole (aft 7, 8; fore 6, 5, 4, 3; before: both declined, fore station 1
engaged). Waterline 24 of 36 cells, RMS 0.055 m, 0 wrong; point (sheer, chine) 9 of 18, RMS 0.053 m, 0 wrong. The
harness identity check still lists fore 3, 4, 5 (no wrong cell). Not read: aft 9 and 10 (their sides end where the
traces reach no level bottom: 'no bottom branch'); fore 2 is traced (chine within 2 px of the printed one) but
left unnamed by the half's naming checks (cause not investigated); fore 1 and 0 near the stem are not traced. The
other ten sheets give the same cells as before; the
round-bilge tables are byte-identical to the baseline and the frozen reader.

Open items: Cama aft 9 and 10 and fore 0 to 2 are not read (fore 2 traced, not named); Cama fore identity flags at 3 to 5 not investigated;
the fore crossing-reader fragment chains below the base line (the misnaming cause on halves that polyline does
not read) are not changed; a flat bottom that ends at a keel outline off the centreline (more than 4 line
widths) is not read as a level bottom.
