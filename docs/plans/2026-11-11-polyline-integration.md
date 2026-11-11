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

- [ ] Gates and runner committed (this file, `scripts/measure_polyline_naming.py`).
- [ ] Baseline run: `work/polyline-integration/before.json`.
- [ ] Cause of the CALEB JONES naming errors from the traces; general fix in the naming step with unit tests.
- [ ] After run with `--baseline`: `work/polyline-integration/after.json`; per-sheet table in section 5; fix commit.
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

(filled after the runs)
