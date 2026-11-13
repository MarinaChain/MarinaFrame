# Ship-D thin-ship validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Check the merged thin-ship solver against 300 non-excluded Ship-D hulls without tuning it.

**Architecture:** A standalone validation script reads selected rows from the local public dataset and generates offsets with the dataset parameterisation. Keep raw inputs, selected IDs, traces and per-condition output in ignored `work/`; commit only code and a small aggregate summary. Do not change the production solver.

**Tech Stack:** Python, NumPy, existing shared venv; local Ship-D geometry code.

## Pre-run review

- Architecture: PASS — standalone validation; no production dependency on Ship-D.
- Code quality: WARN — public geometry code is external; run Python with `-I`, import only the named geometry file, pin its checksum, and keep working directory outside the dataset.
- Test coverage: PASS — synthetic tests cover exclusion, deterministic selection, coefficient conversion, unsupported offsets and fixed denominators.
- Performance: PASS — serial, bounded 300 × 32 evaluation; log long jobs in background.

## Frozen protocol (must be committed before resistance computations)

- Base: local `continue/v0.5`, commit `76d7e01`; solver unchanged.
- Population: Constrained_Randomized_Set_1, _2 and _3 only, not diffusion subsets.
- IDs: zero-based CSV data-row index as `shipd-{subset}-{row:05d}`.
- Exclude every ID from main checkout `work/ship-d-excluded-ids.txt` before selection. No holdout or sealed sources may be opened.
- Sample: 100 per subset. Rank eligible IDs by SHA-256 of UTF-8 `20261114:{id}`, take the first 100 in each subset (digest order). Thus deterministic without dependence on RNG implementation. Freeze selected-ID digest and source digests in the first commit. No replacement after failures.
- Conditions: draft/depth = [0.25, 0.33, 0.50, 0.67]; Fn based on the generated waterline length = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45]. Total denominator: 9,600 conditions.
- Primary offsets: dataset's `gen_PC_for_Cw`, 301 x points, 51 waterlines. Preserve returned values; use `draft_m=-Z[0]` because the geometry starts at depth × 1e-8, not exact keel. Never silently close open ends, clip invalid breadths or replace failed hulls.
- Solver: default 512 angle nodes, lambda_max=24, rho=1000 kg/m³, g=9.81 m/s². No corrections.
- Convention: Ship-D Cw = Rw/(0.5 rho U² LOA²), not wetted-area Cw. Set the solver's normalization area to LOA², explicitly a reference area for this comparison, not a physical wetted area. Compute U using generated WL, as in the dataset notebook. Check generated versus published WL and stored Cw versus Rw_Output where available, as diagnostics only.
- Gate: median `100*abs(Cw_calc-Cw_ref)/abs(Cw_ref)` <=3% AND 90th percentile <=10%, across all 9,600 conditions. Missing/nonfinite/unsupported results or nonpositive references count as infinite error, not dropped rows. Gate fails if either threshold fails. No threshold changes after results.
- Report secondary complete-case statistics, coverage and each subset; these cannot override the primary gate. Report outlier patterns by bow/stern bulb flag, open-end/transom state and LOA/deck-beam slenderness (bands <5, 5–10, >=10).
- Diagnostic only: first 3 selected hulls at all conditions; examine every trace before scaling. If executable, double panels/angles and increase lambda_max on first 3 hulls at Fn=.1/.3/.45 and draft=.5. No sample substitution or gate change.
- Engineering status remains `review_required`; engineering_approved=false.

## Source conventions

Local `code/README.md`: 3 constrained subsets, 32 wave-drag conditions. `Compute_Dataset_Entirety.ipynb` cells 7–9: draft-major ordering, generated WL for speed, rho=1000, g=9.81, 301×51 offsets, 21 angle samples for published Rw, LOA² normalization with test LOA=10. `ModifiedMichellCw.py:170–205` also uses LOA². This is a numerical-code comparison, not tank-test validation; published angular discretisation may be a material error source.

## Small steps and checks

1. Create `scripts/validate_thin_ship_shipd.py` selection/freezing mode; read only table headers/counts and exclusion IDs. Freeze sample/source digests here; commit this plan and selector before evaluation.
2. Add synthetic tests in `tests/test_thin_ship_shipd_validation.py`; run them red before adding evaluation/report helpers. Add bounded evaluation with explicit unsupported cases and append-only traces. Commit code/tests before running the pilot.
3. Run first 3 selected hulls with a background log, inspect all 96 outcomes; retain failures. Then run all 300 in background. Keep data outside git; add a small aggregate under `outputs/thin-ship-shipd/summary.json`. Commit results and plan update.
4. Review change simplicity, run focused tests, tracked-file identity check and `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` in background. Supply `MF_IDENTITY_DENYLIST_FILE` and `MARINAFRAME_TEST_PYTHON` inline. Record exact results, commit, push only `lane/thin-ship-shipd`. Inspect and delete only this worktree's `target/` as final tool step.

## Results (2026-11-14)

- Frozen sample committed in `b4c12a7` before any resistance calculation. Evaluator/tests committed in `a8bcfe2`. Production solver unchanged.
- Synthetic tests: 4 expected missing-helper failures, then 5 passed. Pilot: 96/96 finite, median 2.05749%, p90 8.66881%; all traces inspected before scaling.
- Full sample: 300 hulls, 9,600 conditions; 9,592 finite (99.9167%). Median absolute relative difference **2.03001%**; p90 **10.28459%**. **Fixed gate FAILS**, since p90 exceeds 10%. Complete-case median 2.02692%, p90 10.22977%; failure is not caused only by missing cases. 1,003 conditions exceed 10% or fail.
- Eight conditions have invalid negative/nonfinite offsets and remain infinite-error conditions. No endpoint closure, clipping, sample replacement or threshold change. All 9,600 generated grids have closed endpoints; this sample provides no open-transom comparison.
- Outlier patterns: bow-bulb p90 12.2355% versus 9.8109% without; stern-bulb p90 10.0224% versus 10.3530% without. Slenderness p90: <5 = 9.9420%, 5–10 = 11.0144%, >=10 = 8.2914%. These are descriptive, not independent causal tests. Subset p90: 10.8335%, 10.4602%, 9.5737%.
- Reference checks: maximum generated-versus-published WL difference 0.00019685 m; stored Cw versus Rw-implied Cw difference <=0.001882%. LOA-squared normalization and draft-major condition order match the dataset notebook.
- Nine refined pilot conditions (601×101 offsets, 1024 angles, lambda_max=48): change from defaults min/median/max 0.06027/0.34326/3.85909%. This is not a universal convergence guarantee. Published reference uses 21 angle samples; no production tuning was attempted.
- Median default evaluation time: 7.864 ms on this Mac (serial full run).
- Aggregate deliverable: `outputs/thin-ship-shipd/summary.json`. Detailed traces and hashes remain in ignored `work/thin-ship-shipd/`. First pilot attempt stopped before evaluation because numpy-stl was missing; dependencies installed only in lane scratch, then pilot retried. Original failed log retained.
- Tracked-file identity check with private denylist: 0 findings. Quick tier running; final result to be recorded below.
- Review limitation: reviewer launches incorrectly requested extra-worktree isolation and were stopped. No independent review completed. No other worktree was entered or edited by this session. Self-review retained fixed denominators, source hashes, strict invalid-offset handling and aggregate-only output; PM independent review remains needed.
- Engineering status: `review_required`; engineering_approved=false.

## Resume point

Measurement complete; fixed gate fails. Remaining: finish quick tier, record exact result, push only this branch, inspect/remove this lane's `target/`. Aggregate exporter added after a missing-helper RED test; 7 focused tests pass and export reproduces the committed aggregate byte-for-byte. Export command: `python -I scripts/validate_thin_ship_shipd.py export --source work/thin-ship-shipd/full --exclusions <main>/work/ship-d-excluded-ids.txt --manifest work/thin-ship-shipd/sample.json --output outputs/thin-ship-shipd/summary.json`.

Frozen provenance: SHA-256 `a2465175dd6a38879f99787824d9419946c2bcdf3a6c1b38c54d8d4580c671de` (newline-joined IDs, no final newline), 100 each from populations of 10,000. Exclusion SHA-256 `0b44a428638e648bc56a982469a93b17320424d8697bc76d1cd829fff1dfcaa3`. Geometry source SHA-256 `da44dc1d50bf466023118051ce3b33a4cce580218b7d3236ea08030f24682f28`. Full source hashes and IDs are in ignored `work/thin-ship-shipd/sample.json`, reproducible using the committed selector. No resistance results have been computed. Next: synthetic tests and evaluator, then pilot.
