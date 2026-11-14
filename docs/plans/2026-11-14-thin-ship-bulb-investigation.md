# Ship-D bulb residual investigation

## Fixed scope and checkpoint

Local base merged by fast-forward to `2e02d0a`. Original gate remains FAIL (median 2.03001%, p90 10.28459%); no new gate. Use only the frozen 300 development IDs, recheck current exclusion list before reading trace or selected input rows. No holdout or sealed data. Production solver stays unchanged unless a defect is demonstrated by a failing synthetic test.

## Pre-run diagnostic protocol

1. Split all 9,600 residuals by Fn, bow bulb length/LOA (0–.05, .05–.10, >=.10), maximum bulb cross-sectional area proxy (elliptical area pi*halfwidth*halfheight divided by beam*depth; <.05/.05–.15/>=.15), and peak immersion `(draft-Hbb*WL)/draft` (<0/0–.5/>=.5). Include counts, signed median, absolute median and p90. These are descriptive bins, not validity gates. Keep per-ID values ignored.
2. Diagnostic subset: select the six bow-bulb hulls with largest finite per-hull maximum residual and three no-bow-bulb controls by the same rule, ties by ID. Test draft=.25/.5/.67, Fn=.1/.2/.3/.45. Results cannot serve as unbiased validation.
3. Change one variable at a time relative to 301×51/512 angles/lambda=24: x stations=1201 only; z waterlines=201 only; angle nodes=2048 only; lambda limit=48 only; replace returned keel z with exact -draft only. Record full differences, including failures. Inspect grid/section representation and endpoint breadths. No silent clipping or end closure.
4. Reference-code check on identical default offsets: independently vectorise published Filon expressions and confirm N=21 reproduces stored Cw, then change only its angle count to 81 and 321. This isolates published angular quadrature from hull resolution and theory. Do not label a reference discrepancy a production bug.
5. Compare theory content from source: both are Michell integrals; neither reference nor production includes nonlinear near-surface bulb physics. A shared theory limitation cannot alone explain a difference between these codes. Do not infer physical validity from agreement with this reference.
6. Commit script/tests and protocol before diagnostic run. Run long work in background with log. Summarise aggregate evidence only in git, document limits in `docs/plans/2026-11-13-thin-ship.md`. Run quick tier with required inline env, identity check, push lane only. Delete only this worktree target as final step.

## Resume point

Protocol written before diagnostic computations. Next: script and synthetic reference tests; then run splits and one-factor experiments. No change to original gate or sample.
