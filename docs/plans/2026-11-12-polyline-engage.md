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
- [ ] Baseline run: `work/polyline-engage/before.json`. Started at `1a33fee` (it loaded the reader before any
  edit); paused by the PM (SIGSTOP, demo build) and resumed by the PM. Its `polyline_sha256` field is hashed
  when the report is written, so it shows the edited file; the `commit` field (`1a33fee`) is the code it ran.
  If it was killed, run it again from a checkout of `1a33fee`.
- [x] Diagnosis on Cama Beach (section 5).
- [ ] General fix with synthetic tests: code written (uncommitted at the pause), synthetic tests being run.
- [ ] Cama trace check of the fix (`diag.py` in the scratchpad: per-seed trace outcome), then the after run.
- [ ] After run with `--baseline`: `work/polyline-engage/after.json`; per-sheet table in section 5.
- [ ] Quick test tier; push the branch (no merge).

Resume: read the checkboxes; result files are in `work/polyline-engage/` (git-ignored). Uncommitted work at a
pause is in the worktree (`git diff`): `body_plan_polyline.py` and `tests/test_body_plan_polyline.py`.

Reproduce (from the worktree root):

```bash
set -o pipefail
PYTHONPATH=src:. /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python \
  scripts/measure_polyline_engage.py \
  --sources /Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources \
  --truth-root /private/tmp/claude-501 \
  --legacy-truth-root /private/tmp/claude-501/-Users-jonathanjie-Documents-workspace/31a3f286-f3b9-4116-93bc-756e11ead9ee/scratchpad/wv-agent \
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
2. For a level branch, the grid-line test uses only the calibrated rows that are drawn (`drawn_rows`: ink
   within half a line width of the row at more than `GRID_SHARE` of the columns across both halves; a bottom
   covers at most its own half). Descending branches keep the test against every calibrated row.
3. The polyline keeps rows strictly decreasing: a level bottom is stored as its rabbet end and the knuckle
   (`LEVEL_ROW_STEP_PX` = 0.5 px: twice the 0.25 px rise `_monotone` needs to keep the knuckle); the traced
   bottom is kept in `level_bottom` for the bottom-ownership test.

No vessel name or truth value; one new constant with its reason. Synthetic tests: flat-bottom half on both sides
(traced, named 4-3-2-1, knuckles, rabbets; one bottom 5 px from an undrawn measuring row), its table, `drawn_rows`,
and a V-bottom with a level line through its knuckles that keeps its descending bottoms. Before the fix the
flat-bottom half was declined ("no bottom branch" for 3 of 4 lines), as on Cama.
