# Holdout calibration: CAMA BEACH SKIFF No. 22 and Davis Boat (lane L, 2026-11-11)

Goal: write both sheet calibrations truth-blind, before any reader run.
Branch: `lane/holdout-calibration` from `origin/continue/v0.5` `dbd76df`.

## Plan and status

1. Read the protocols (hashes only, no truth values) and the CALEB JONES calibration format. Done.
2. Measure scale, axes, waterlines, sides and reach on crops of each sheet; never view the table of
   offsets at a legible scale. Done.
3. Independent truth-blind second check of scale, axes and sides. Done: full agreement (Davis bow side
   rests on convention in both readings).
4. Write `benchmarks/cama_beach_skiff_22/holdout_value.py`, `benchmarks/davis_boat/holdout_value.py`,
   the Cama BOATS entry and `tests/test_holdout_calibrations.py`. Done.
5. Protocol amendments with SHA-256 of each file (`docs/BODY_PLAN_CHINE.md`, Cama section;
   `docs/holdouts/davis-boat.md`). Done.
6. Quick test tier, commit, push the branch; no merge. See the commit log.

## Checks

- `tests/test_holdout_calibrations.py` and `tests/test_deadrise_holdouts.py`: 23 passed.
- `make test-quick`: lint and Rust passed; with `PY` set to the main checkout venv, Python 1901 passed
  (76 deselected), UI 226 passed / 0 failed, secret scan clean.

## Resume point

Calibration is complete. Next (other lanes): the PM runs the Cama Beach holdout once with
`scripts/measure_deadrise_holdout.py --boat cama-beach-skiff-22`; for the Davis Boat, the round-bilge
run script and pin update (protocol section 6, step 2) come first. Any edit to a calibration file
after this commit must be recorded in the protocol before the run.
