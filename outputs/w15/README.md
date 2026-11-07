# W15 result inventory

All results are development results. `engineering_approved=false` throughout.

## Reproduction boundaries

Run from the W15 worktree. Use the main checkout's `.venv/bin/python` with
`PYTHONPATH=src`. All raw data belongs in the main checkout's `work/w15/`.

The adapter API is `vessel_reconstruction.plan_corridors.derive_contour_selection`.
It accepts a plan RGB image, an existing body section, declared plan setup,
waterline regions/height evidence and a bounded corridor half width. Its return
value contains all anchor outcomes and either an existing-format selection or
`None`. It does not mutate the section, infer waterline names, read a reference
model, or build CAD.

The optional raster-preparation config is documented in
`docs/BENCHMARK_GUNNERUS.md`, section 9. Real source coordinates and raw JSON
configs are deliberately not included here. The synthetic tests give a complete
redistributable example.

## Local evidence (not committed)

Relative to main `work/w15/`:

- `baseline-source/`: baseline source archive from `844c842`.
- `after-source/src/`: immutable after worker source.
- `bin/marinaframe-baseline-844c842`: immutable controller; no Rust logic changed.
- `gunnerus/frozen-stations.json`: frozen 72-station W9b setup.
- `gunnerus/`: excluded initial 59-station archived-input attempts.
- `gunnerus72/input/`, `gunnerus72/after-input/`: before/after input and refusal evidence.
- `gunnerus72/{before,after}-{abstain,draft}/`: native task records.
- `plan-evidence/`: same-PDF raster calibration, label inspection and raw setup.
- `anchor-aggregate.json`, `gunnerus-aggregate.json`: local aggregate records.
- `factory/`: four regenerated development inputs, frozen-hash checks, native tasks,
  exported models and post-read independent scores.
- `prepare_after.py`, `regenerate_controls.py`, `run_controls.py`,
  `score_controls.py`, `summarize_gunnerus.py`: local reproduction drivers.
- `test-quick.log`: initial invalidated quick attempt (source changed during test).
- `test-quick-stable.log`: stable-source quick verification (passed: 701 Python,
  Rust quick suites, formatting, Clippy and bounded secret scan).
- `test-full.log`, `test-full-exit.txt`, `full-preflight.txt`: the single full-tier
  invocation and its concurrency check, once native/scorer work ends.

Do not move raw source data into this output directory. Aggregate results and
final verification status are in `docs/BENCHMARK_GUNNERUS.md`, section 9.
