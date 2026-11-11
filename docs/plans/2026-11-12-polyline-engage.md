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

- [ ] Gates and runner committed (this file, `scripts/measure_polyline_engage.py`).
- [ ] Baseline run: `work/polyline-engage/before.json`.
- [ ] Diagnosis on Cama Beach (traces, overlay crops) of polyline decline and crossing-reader names.
- [ ] General fix with synthetic tests (flat-bottom chine, V-bottom, round bilge).
- [ ] After run with `--baseline`: `work/polyline-engage/after.json`; per-sheet table in section 5.
- [ ] Quick test tier; push the branch (no merge).

Resume: read the checkboxes; result files are in `work/polyline-engage/` (git-ignored).

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

(Filled in after the runs.)
