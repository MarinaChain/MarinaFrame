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

## Results — fixed protocol, draft

The single fit returned **alpha=0.43669732630769764**, interior to [0,1].
**The predeclared diagnostic gate FAILED.** Equal-ship leave-one-out CT MAE
is 12.569%, worse than the 9.620% baseline. JBC and KVLCC2 exceed 10%.
No term, threshold, ship weighting or gate was changed after seeing this result.
The frozen candidate is experimental, not a transferable accuracy claim.

The public evaluator uses two source-labelled case names for KVLCC2; both
are grouped as the SAME ship before weighting and omission. All nine rows
(one second-source point plus eight series points) share KVLCC2's weight.
KCS has six rows and JBC one. KCS is below the fixed full-form threshold;
its correction is zero. Thus only TWO ships constrain alpha.

| Ship | Baseline CT MAE % | Fit CT MAE % | LOO CT MAE % | Baseline PE MAE % | Fit PE MAE % | LOO PE MAE % |
|---|---:|---:|---:|---:|---:|---:|
| JBC | 2.839 | 7.881 | 14.730 | 4.503 | 6.390 | 13.350 |
| KCS | 7.180 | 7.180 | 7.180 | 8.134 | 8.134 | 8.134 |
| KVLCC2 | 18.842 | 7.343 | 15.797 | 18.842 | 7.343 | 15.797 |

LOO alphas (omitted ship): JBC 0.715699477, KCS 0.436697326, KVLCC2 0.115637843. No fold hits a parameter bound.

### Signed errors at each speed

KVLCC2 CT and PE errors are identical because the estimated and measured
reference areas match. For other ships the published S0 differs from mesh area.

| Ship | Speed m/s | Baseline CT % | Fit CT % | LOO CT % | Baseline PE % | Fit PE % | LOO PE % |
|---|---:|---:|---:|---:|---:|---:|---:|
| KCS | 0.915000 | +5.082 | +5.082 | +5.082 | +6.440 | +6.440 | +6.440 |
| KCS | 1.281000 | +3.972 | +3.972 | +3.972 | +5.316 | +5.316 | +5.316 |
| KCS | 1.647000 | +8.349 | +8.349 | +8.349 | +9.749 | +9.749 | +9.749 |
| KCS | 1.922000 | +12.094 | +12.094 | +12.094 | +13.543 | +13.543 | +13.543 |
| KCS | 2.196000 | +10.836 | +10.836 | +10.836 | +12.268 | +12.268 | +12.268 |
| KCS | 2.379000 | -2.746 | -2.746 | -2.746 | -1.489 | -1.489 | -1.489 |
| JBC | 1.176717 | +2.839 | -7.881 | -14.730 | +4.503 | -6.390 | -13.350 |
| KVLCC2 | 1.047000 | +18.430 | +7.008 | +15.405 | +18.430 | +7.008 | +15.405 |
| KVLCC2 | 0.743045 | +20.112 | +8.437 | +17.020 | +20.112 | +8.437 | +17.020 |
| KVLCC2 | 0.809257 | +19.636 | +8.015 | +16.559 | +19.636 | +8.015 | +16.559 |
| KVLCC2 | 0.875469 | +19.074 | +7.516 | +16.013 | +19.074 | +7.516 | +16.013 |
| KVLCC2 | 0.949038 | +18.585 | +7.092 | +15.542 | +18.585 | +7.092 | +15.542 |
| KVLCC2 | 0.978465 | +18.597 | +7.114 | +15.556 | +18.597 | +7.114 | +15.556 |
| KVLCC2 | 1.015250 | +18.269 | +6.838 | +15.242 | +18.269 | +6.838 | +15.242 |
| KVLCC2 | 1.044677 | +18.454 | +7.028 | +15.428 | +18.454 | +7.028 | +15.428 |
| KVLCC2 | 1.081462 | +18.422 | +7.042 | +15.409 | +18.422 | +7.042 | +15.409 |

### Provenance and reproduction

No new ship's measured data was opened. Inputs are the prior public development
cases, copied by PM, plus the former KVLCC2 evaluator input explicitly released
for development in this brief. Source-cell and paper/table references remain in
each row of the ignored `work/perf-calibration/fit-v1.json` report.

- `development-v3.json` SHA-256 `a2f56bf51b3264bb40f758b03cc2160bf54011973d845e3818b3808334fdd357`.
- `kvlcc2-cases.json` SHA-256 `ea4791d32937623876705b1544e97b6f4b3d8ec85d662742e307d0a89dfc72db`.

```bash
PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python scripts/calibrate_performance.py --input work/perf-calibration/development-v3.json --input /Users/jonathanjie/Documents/workspace/MarinaFrame/work/perf-eval/kvlcc2-cases.json --output work/perf-calibration/new-fit.json
```

The output path must not exist. Runtime fitting is separate from the evaluator;
the frozen evaluator uses only the stored scalar. The correction is limited to
model-scale force. Full-scale calls and calibrated propulsion are rejected.
KVLCC2 sources remain second-hand/rounded, water density assumed, and sinkage/
trim condition uncertain. Existing baseline warnings are retained. KCS lies
outside the correction envelope. No universal validity or fuel accuracy follows.

### PM decision and conclusion

Protocol commit: **bc98a00**. PM decision after seeing the failed gate: **do not
spend a blind ship on this candidate**. Freeze `perf-frozen-2` as experimental,
**failed transfer gate**, with default and both baseline methods unchanged.
The evaluator command above is retained for reproducibility, not authorization
to run a blind score. No new blind score is planned or performed.

One correction term fitted on three development ships does not transfer under
the fixed gate. More full-form model-test data (for example the pilot's model
tests, handled only by an authorized lane) or CFD is needed before a tanker
estimate. KCS contributes no fit sensitivity, making this effectively a
compromise between two full forms, whose preferred corrections differ strongly.

### Resume point

Fit completed under unchanged protocol. Focused checks: **121 passed**.
Quick-tier and independent code review are in progress. Runtime replay agrees
with the offline fit at all **16 development points**, for CT and PE within
1e-10 percentage points. Independent review found missing calibration-envelope
text in Markdown; a failing regression assertion reproduced it, and rendering
the combined, de-duplicated warning lists fixed it (**36 integration tests
passed**). The first quick run hit the tool time limit; a second was stopped
when the review fix changed the source. Neither counts as a passing quick run.
A fresh full quick tier now runs after the fix.

Next: record final checks, freeze and push experimental tag `perf-frozen-2`;
no blind scoring. Full CAD tier was not requested or run.
