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

Numerical investigation complete; original gate unchanged. No production defect demonstrated, so no production fix or new gate. Focused solver/validation/diagnostic suite: 31 passed; separate export/diagnostic check: 4 passed. Tracked identity scan: 0 findings. First quick-tier attempt was killed by the tool's 600-second background limit during Python tests; partial log contains one failure marker but no final failure details. Retained `work/thin-ship-shipd/bulb-quick.log`. Retry completed with exit 0, log `bulb-quick-retry.log`: Rust format/clippy/test stages passed; Python 2,804 passed, 4 skipped, 130 deselected, 5 warnings in 534.02 seconds; UI 275 passed, 0 failed; bounded secret scan 1,429 tracked text files, 0 findings. Final tracked identity scan: 0 findings; `git diff --check` clean. The interrupted attempt's failure marker did not recur; its cause remains unknown, and it is not presented as a passing run. Next: commit this completion record, push only `lane/thin-ship-shipd`, retain worktree and raw evidence, inspect/remove only this lane's local target (if present).

## Results and evidence

All split percentiles below are **complete-case descriptive statistics**, not gates. Full denominator is still 9,600, with eight unsupported open-end conditions. Original 2.03001%/10.28459% fixed-denominator gate FAIL stays recorded.

| Split | conditions / finite | median absolute % | p90 absolute % |
|---|---:|---:|---:|
| No bow bulb | 7456 / 7456 | 1.966 | 9.811 |
| Bow bulb | 2144 / 2136 | 2.246 | 12.068 |
| Bulb length/LOA <.05 | 448 / 440 | 2.327 | 12.223 |
| .05–.10 | 576 / 576 | 2.297 | 11.915 |
| >=.10 | 1120 / 1120 | 2.152 | 11.694 |
| Elliptical area proxy <.05 | 672 / 672 | 1.951 | 10.536 |
| .05–.15 | 576 / 568 | 1.805 | 10.668 |
| >=.15 | 896 / 896 | 2.946 | 12.636 |
| Peak above waterline | 208 / 208 | 3.761 | 14.381 |
| Peak immersion 0–.5 draft | 408 / 400 | 2.791 | 13.604 |
| Peak immersion >=.5 draft | 1528 / 1528 | 1.931 | 10.767 |

Area proxy = pi × bulb maximum halfwidth × max(peak height, WL−peak height)/(deck beam × depth). It is not measured bulb area or volume. Length alone has no monotonic adverse relation; area and shallow immersion show stronger concentration. Confounding by Fn and hull shape remains.

| Fn | finite / 1200 | median absolute % | p90 absolute % |
|---|---:|---:|---:|
| .10 | 1199 | 13.111 | 27.699 |
| .15 | 1199 | 4.091 | 10.105 |
| .20 | 1199 | 2.403 | 6.508 |
| .25 | 1199 | 1.984 | 5.208 |
| .30 | 1199 | .860 | 3.809 |
| .35 | 1199 | .852 | 2.957 |
| .40 | 1199 | 1.627 | 5.588 |
| .45 | 1199 | 1.332 | 6.101 |

At Fn=.10, area-proxy >=.15 p90 is 46.809%, versus 27.632% for <.05. Peak immersion 0–.5 draft has p90 64.200%; at Fn=.30 this is 4.677%. Bulb length >=.10 has p90 39.144% at Fn=.10, 4.368% at Fn=.30. Cross-split counts and signed errors are in the aggregate JSON.

### One-factor causal tests (108 selected diagnostic conditions)

These are six worst-residual bow-bulb hulls and three worst-residual controls, not an unbiased sample. Baseline median/p90 error: 3.468%/21.383%.

- **Production angular quadrature:** 512→2048 nodes changes Cw median <2e-11%, maximum .1881%; p90 error 21.374%. Not the primary cause.
- **Production tail:** lambda 24→48 changes median .01969%, maximum .53676%; p90 error 21.383%. Small here; not a universal tail bound.
- **Station resolution:** 301→1201, all else fixed, changes median .13990%, maximum 21.925%; p90 error worsens to 22.531%. Bow-bulb-only changes median .14570%, p90 3.230%, max 8.422%. Resolution matters for individual hulls but does not remove the reference discrepancy.
- **Depth resolution:** 51→201 waterlines changes median .07418%, maximum 21.940%; p90 error 21.525%. Bow-bulb-only median .07977%, p90 .47961%, max 3.306%. No production interpolation defect demonstrated.
- **Section representation:** independent coordinate-indexed waterline reconstruction matches returned dense breadths exactly (maximum 0 m) for all 27 hull/draft grids. Bulb is explicitly present in half-breadths, not approximated as a separate force. The first diagnostic attempt failed because a subtract/add coordinate round trip changed strict boundary membership; its log is retained. Corrected diagnostic uses the original geometry linspace.
- **Waterline-entry/keel origin:** both codes use the identical top breadth row at z=0, no surface-entry correction. Setting only the near-keel z to exact −draft changes median .000000102%, maximum .00000534%; cannot explain the residual. Open-end cases remain unsupported, not silently closed.
- **Published reference quadrature:** vectorised published expression matches its original nested-loop code to 5.19e-12% in the direct spot check. At 21 angles it reproduces stored Cw median .00629%, p90 .03065%, max 4.463% (stored speed uses separately sampled published WL; do not claim exact reproduction). Increasing **only reference angle count** to 321 reduces reference/production discrepancy from median 3.461%, p90 21.395% to median .16312%, p90 3.12671%. Bow-bulb-only p90 falls 14.655%→3.258%; controls 43.540%→2.875%. This is strong evidence for coarse reference angular integration, not a production defect.
- **Full development diagnostic:** same offsets, only reference angles raised to 321; all 9,600 conditions retained, 9,592 finite. Complete-case difference from unchanged production: median .12527%, p90 1.66344%, max 26.34733%. This is a new numerical reference diagnostic, **not a replacement for the published-reference gate**. Eight production failures remain. No production fix was made.
- **Physics hypothesis:** rejected as an explanation of inter-code differences. Both implementations evaluate Michell theory, with no nonlinear bulb/free-surface interaction, breaking, trim, sinkage or viscous effects in the reference. Shared omissions still limit physical prediction, especially shallow bulbs; they cannot establish which code matches real drag.

## Reproduction and retained files

Script: `scripts/investigate_thin_ship_bulbs.py`; synthetic tests: `tests/test_thin_ship_bulb_diagnostics.py`. Invoke with main venv `python -I`, explicit dependency path `work/thin-ship-shipd/dependencies`, and arguments `--source <main>/work/sources/shipd --exclusions <main>/work/ship-d-excluded-ids.txt --manifest work/thin-ship-shipd/sample.json --trace work/thin-ship-shipd/full/trace.jsonl --output <new ignored directory>`. Original failed attempt: `bulb-investigation`; corrected: `bulb-investigation-retry`; complete development repeat: `bulb-development`, under ignored `work/thin-ship-shipd/`. Each has a background log. Export aggregates with `--export work/thin-ship-shipd/bulb-development --output outputs/thin-ship-shipd/bulb-summary.json`. No per-ID geometry or residuals committed.

## Recommendation, not a gate

Do not tune production to the 21-angle target. PM could commission a fresh frozen non-excluded development cohort with independently converged angular reference, before setting any gate. No IDs are selected and no threshold is proposed as active. Physical bulb validity needs independent tank/CFD evidence; this comparison cannot establish it.
