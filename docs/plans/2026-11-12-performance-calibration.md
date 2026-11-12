# Resistance Calibration Implementation Plan — draft

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Freeze a separately named, one-parameter full-form resistance correction for independent PM scoring.

**Architecture:** Keep Holtrop 1982 and 1984 unchanged. A wrapper changes only the excess viscous form factor of Holtrop 1984; fitting and ship-level cross-validation are offline development operations.

**Tech Stack:** Python dataclasses, standard-library least squares, existing JSON evaluator, pytest.

## Exposure inventory (before new measured-data reads)

KCS: all six published resistance points and geometry already exposed. JBC: resistance, self-propulsion and open-water tables already exposed. KVLCC2: independent first blind score is now public development evidence; all evaluator cases in `work/perf-eval/kvlcc2-cases.json` are permitted development inputs by the PM brief. These are the ONLY measured-resistance ships permitted here.

KVLCC1 and DTMB 5415: previous lane saw conditions and geometry availability, not resistance series. Do not open their measurements. The inherited unsubstantiated Lewis/Series60 worked-example fixture was previously exposed and rejected; exclude that fixture from any blind selection. No other full-form ship data will be read. PM chooses a fresh blind ship; this lane neither selects nor scores it. No restricted pilot, holdout or sealed paths.

## Pre-fit protocol (commit before fitting)

- Base method: `holtrop_1984`, model scale, correlation allowance disabled.
- Named correction: `holtrop_1984_full_form_v1`.
- One fitted parameter alpha in [0, 1]. Define fixed full-form weight w=clip((Cb_LWL-0.75)/0.05,0,1). Correct form factor F'=1+(F-1)*(1-alpha*w). Thus only excess viscous resistance is reduced; ITTC friction, wave, bulb, transom and appendages are unchanged. Thresholds are declared before fitting, not optimized.
- Physical hypothesis: the ship-regression excess form factor is too large for these model-scale full forms. This is not a new universal form-factor law. No CA fitting or wave fitting.
- Minimize mean over ships of mean over that ship's rows of squared relative CT errors. Duplicate method cases must not duplicate measurements; fit only 1984 cases. Multiple conditions of one ship share its total weight equally across all its rows. Solve scalar linear least squares analytically and clip alpha to [0,1]. If no sensitivity remains, use alpha=0 and report non-identifiability. No optimizer search or method selection.
- Report CT and PE signed errors at every speed, MAE by ship, parameter bound hits, and equal-ship aggregate. Source reference areas remain unchanged; CT and PE errors need not be equal.
- Leave one SHIP out: fit on the other two and evaluate the omitted ship. Never leave only one speed out. Report all folds, including no-sensitivity folds.
- Fixed diagnostic gate: all ship-level leave-one-out CT MAEs <=10%, and equal-ship CT MAE below baseline. A failure is reported; it does not trigger new parameters, threshold changes or a second fit design.
- Scope: model-scale calm-water resistance only; full forms 0.75<=Cb_LWL<=0.85, Fn 0.10–0.20, Re 1e6–2e7. Outside this envelope return explicit range warnings. Cb<=0.75 remains exactly baseline but is not evidence for a full-form fit. Ship-scale calibrated calls and propulsion/fuel with the calibrated method are rejected: neither was calibrated.
- Preserve all baseline warnings and `engineering_approved=false`. No accuracy status claim.

## Review before implementation

Architecture PASS: separate wrapper, baseline untouched. Quality PASS: one bounded scalar and explicit no-sensitivity handling. Tests WARN: add independent hand-computed fit tests, grouping/duplicate rejection and error-path coverage. Performance PASS: linear in the number of development points; no CAD rerun needed if existing inputs are available. Scientific WARN: only two full-form ships; leave-one-out is diagnostic, not independent blind evidence.

## Tasks and checks

1. Commit this protocol before opening the newly permitted KVLCC2 case values or fitting. Obtain existing KCS/JBC input through PM/shared public inputs, without modifying another worktree.
2. Add `tests/test_performance_calibration.py` with synthetic component arithmetic, alpha bounds, zero sensitivity, equal-ship weighting, exact ship exclusion, domain warnings and unchanged baseline checks. Run failing tests, then implement `src/vessel_reconstruction/performance_calibration.py` with wrapper and fitting functions. Commit passing focused tests.
3. Extend `src/vessel_reconstruction/performance_compare.py` to accept the separately named frozen method, reject calibrated ship scale and propulsion, and preserve both baselines. Add evaluator tests. Add an allowlisted offline development runner `scripts/calibrate_performance.py` that emits input SHA, all fits/folds, row errors and baseline comparison into ignored `work/` only. No measured fixtures in git.
4. Run development fit once under this fixed protocol; record coefficient and all diagnostic results here. Freeze the scalar in code, retaining reproducible fitting separately. Run focused tests and `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` in background. Do not set wall-clock caps on project jobs.
5. Commit passing code, tag `perf-frozen-2` without moving an existing tag, record full SHA and evaluator command. Push only `lane/perf-calibration` and the new tag; do not merge. Inspect and remove only this worktree's `target/` last, if present (never shared cache).

## Evaluator handoff

PM supplies schema-v1 cases with method `holtrop_1984_full_form_v1`, explicit model scale and no propeller. No fitting occurs in the evaluator:

```bash
git switch --detach perf-frozen-2
PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python -m vessel_reconstruction.performance_compare --input /absolute/pm-owned/cases.json --output /absolute/pm-owned/new-score.json --markdown /absolute/pm-owned/new-score.md
```

PM records the immutable tag SHA and input SHA and scores a named unexposed ship once. Until then no new blind evidence exists.

## Resume point

Protocol written; not yet fitted. Next: commit protocol, obtain public development inputs, then synthetic tests. Results and exact freeze SHA follow below.
