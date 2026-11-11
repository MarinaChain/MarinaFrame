# Hard-chine station joining

## Product reader and next step

When `MARINAFRAME_BODY_PLAN_READER=1`, intake uses `body_plan_reader` with
`body_plan_crossings` and code-only nesting-rank station identity. None of the
hard-chine readers is in this product path. The historical benchmark reader is
preserved separately in `benchmarks/frozen_readers/v1`.

Before integrating a chine reader, compare the existing candidates on the same
calibrated development and independent holdout sheets. Check coverage, value and
identity errors, and the traced corners. Integrate only a candidate that meets
predefined gates; otherwise keep the present product reader.

## Metrics and acceptance

PARDON ME is a **DEVELOPMENT case**. Its round-14 holdout is spent. Its truth may now guide diagnosis, but the joining code must not read truth, vessel names, or benchmark calibration constants.

Compare the frozen code-only reader with the frozen reader plus chine joining. Use each sheet's existing harness calibration without retuning. BUMBLE BEE uses the documented corrected sides. Report:

- Cells given / truth cells: only cells present in both prediction and truth.
- RMS and maximum absolute error, in metres, on those common cells. Missing cells are not zero-error cells.
- Identity errors: the existing harness's station-level nearest-truth-curve check, not a new threshold.
- Extra cells and missing cells in the machine-readable result.

PARDON ME has 57 truth cells. Published round-14 code baseline: 34/57 cells, RMS 0.1346956535 m, maximum 0.6371791158 m, identity errors [6, 10, 11]. The baseline was reproduced before implementation. Both arms are measured below; the current joining module gives no improvement. For BUE GIRL, C.A. Thayer, Balclutha, and BUMBLE BEE (corrected sides), RMS must not increase; also report coverage so abstention cannot conceal a regression. Report missing inputs explicitly.

## Boundaries

Do not edit the frozen reader, identity, crossings, Balclutha crossing harness, or round-14 report. Do not edit first-hull bottom/materialization/end handling. Work only on branch `feature/chine-joining`; do not push, merge, or switch branches.

Frozen SHA-256 values at start:

| File | SHA-256 |
|---|---|
| `src/vessel_reconstruction/body_plan_crossings.py` | `c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97` |
| `src/vessel_reconstruction/body_plan_reader.py` | `327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11` |
| `src/vessel_reconstruction/body_plan_identity.py` | `ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34` |
| `benchmarks/balclutha/crossing_value.py` | `bafb3ac55a69046cbf3fafcdd02f63889a34a69b064917b8798315ad4c9a4ddf` |
| `docs/holdouts/round14-pardon-me.md` | `21eec685953b616604972775d1887f0e492a718c4ef11c30aed563990597d049` |

## Implementation plan and resume point

1. **Metrics first.** Reproduce all available frozen-reader baselines. Record exact inputs/calibration, metric definitions, and test command here. Commit this document and measurement support before implementation.
2. **Detection and joining.** Add `src/vessel_reconstruction/body_plan_chine.py`, which calls the frozen reader and post-processes its reading. Detect a common series of angular joins, not a single coincidental touch. Require local endpoint proximity, an angular change, consistent vertical progression and nesting. Join one-waterline fragments to their continuation without moving measured crossings. Keep the original reading when evidence is insufficient. Route `body_plan_intake.py` through this wrapper. Add PIL synthetic V-section tests in `tests/test_body_plan_chine.py`, including mirrored sides, smooth/no-chine drawings, ambiguous neighbours, and product integration. Observe failing tests before implementation, then run reader/intake and new tests. Commit.
3. **Measure and report.** Run both arms on all five sheets with the same constants and truth. Save final JSON in `outputs/`, update the table here, check no-regression and frozen hashes, run relevant tests, and commit. Report limitations without hiding missing or incorrect cells.

Use `.venv/bin/python` with `PYTHONPATH=src:.`. Start test chains with `set -o pipefail`; never pipe git commands. Check `git log` and `git status` at resume before repeating a step. Each numbered step ends with a commit.

Initial verification: `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_body_plan_reader.py tests/test_body_plan_intake.py -q`: **34 passed** (5.25 s).

Current resume point: metrics protocol committed in `48a2965`; joining module and synthetic tests committed in `4232502`. The measurement step is complete below. **Product integration is not done and is not part of this measurement step.** Stop after committing these results; do not tune the algorithm or change the intake path in this step.

## Measured results: implementation `4232502`

Both arms use code-only rank identity and the existing harness scorer. The second arm calls `body_plan_chine.join_chine` on the **same frozen reading** used by the first arm. It does not change calibration, crossing measurement, truth selection, or scoring. All five sheets and truth files were found. No model calls or image outputs were needed.

| Sheet | Cells given: frozen → joined | RMS m: frozen → joined | Max absolute m: frozen → joined | Identity-error stations: frozen → joined |
|---|---|---|---|---|
| PARDON ME (development) | 34/57 → 34/57 | 0.134696 → 0.134696 | 0.637179 → 0.637179 | [6, 10, 11] → [6, 10, 11] |
| BUE GIRL | 37/39 → 37/39 | 0.001431 → 0.001431 | 0.005839 → 0.005839 | [] → [] |
| C.A. Thayer | 149/151 → 149/151 | 0.011616 → 0.011616 | 0.132379 → 0.132379 | [] → [] |
| Balclutha | 151/151 → 151/151 | 0.148012 → 0.148012 | 1.811325 → 1.811325 | [] → [] |
| BUMBLE BEE (corrected sides) | 50/54 → 50/54 | 0.148585 → 0.148585 | 0.463648 → 0.463648 | [1, 2, 3, 4, 5, 6] → [1, 2, 3, 4, 5, 6] |

| Sheet | Missing cells, both arms | Extra cells, both arms | Chains aft / fore, both arms | Changed sides |
|---|---:|---:|---|---|
| PARDON ME | 23 | 1 | 13 / 14 | none |
| BUE GIRL | 2 | 7 | 7 / 6 | none |
| C.A. Thayer | 2 | 1 | 13 / 11 | none |
| Balclutha | 0 | 4 | 11 / 10 | none |
| BUMBLE BEE (corrected sides) | 4 | 2 | 7 / 9 | none |

**Decision:** RMS and coverage do not regress on any of the four comparison sheets. However, the wrapper returns each original side reading unchanged on **all five sheets**, including PARDON ME. Thus the no-regression result is an unchanged-output check, not evidence that joins are safe on real scans. The development objective is **not met**: no missing PARDON ME cell is recovered; its large errors and identity errors remain. The synthetic V-section recovery does not establish recovery on this scan. No thresholds were retuned after measurement. Do not treat this result as a successful chine fix or engineering approval.

The PARDON ME frozen result matches the published round-14 code baseline at full precision. Balclutha retains its doubtful truth cell in the primary metric, as its harness requires; the existing scorer also reports the secondary RMS without that cell in the JSON. Identity errors use the existing scorer: at least three shared waterlines, with either adjacent station fitting the predicted values better than the named station. An empty identity-error list does not prove correct identity.

### Calibration and input record

Use the existing `sheet_layout()` for each harness, except for BUMBLE BEE's documented development correction from `docs/AUTO_CALIBRATION.md` section 4. BUMBLE BEE is **aft left, stations (9, 10, 11, 12, 13, 14); fore right, stations (8, 7, 6, 5, 4, 3, 2, 1)**. This is not a plain swap of the round-13 station sets. All other BUMBLE BEE constants, including grid columns by sign, are unchanged.

| Sheet | Calibration source | Centre column | Pixels/metre | Max offset px |
|---|---|---:|---:|---:|
| PARDON ME | `benchmarks/pardon_me/holdout_value.py` | 3270 | 984.251968503937 | 1550 |
| BUE GIRL | `benchmarks/bue_girl/holdout_value.py` | 3266.5 | 1312.3359580052493 | 1650 |
| C.A. Thayer | `benchmarks/thayer/holdout_value.py` | 8857.5 | 492.1259842519685 | 3150 |
| Balclutha | `benchmarks/balclutha/crossing_value.py` + `tiled_value.py` | 4824 | 491.48 | 3150 |
| BUMBLE BEE | `benchmarks/bumble_bee/holdout_value.py`, corrected sides above | 3009 | 1312.3359580052493 | 1900 |

Machine-readable evidence: `outputs/body_plan_chine_measurements.json`. It records full-precision scores, all calibration rows/grid columns/station orders, absolute input paths, sheet and truth SHA-256 fingerprints, predicted cell values, missing/extra cell keys, identities, and chain summaries for both arms. It does not copy the truth values into the repository.

Reproduce from this worktree:

```bash
set -o pipefail
PYTHONPATH=src:. .venv/bin/python scripts/measure_body_plan_chine.py \
  --sources /Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources \
  --truth-root /private/tmp/claude-501 \
  --legacy-truth-root /private/tmp/claude-501/-Users-jonathanjie-Documents-workspace/31a3f286-f3b9-4116-93bc-756e11ead9ee/scratchpad/wv-agent \
  --out outputs/body_plan_chine_measurements.json
```

The truth paths under `--truth-root` are `pardon-me/truth_s4.json`, `bue-girl/truth_s2.json`, and `bumble-bee/truth_s2.json`. The legacy truth paths are `thayer/truth_s4.json` and `balclutha/truth_s7.json`. These local inputs must exist to repeat the measurement; the script reports any missing inputs explicitly.

### Verification

- Measurement command: exit 0; five cases completed. Both arms have exactly equal predicted cells, identities, chain summaries, and scores on each case.
- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_body_plan_chine.py tests/test_body_plan_reader.py tests/test_body_plan_intake.py -q`: **40 passed** (7.13 s).
- All five protected SHA-256 values above remain unchanged.
- `body_plan_intake.py`, the chine module, and its tests are unchanged from `4232502`. No product integration, push, merge, branch switch, or other-lane edits were made.

### Why no joins: measured rejection gates (`4232502`)

This is diagnosis of the unchanged detector, not a threshold search. Chain indices are the frozen reader indices used by `benchmarks/pardon_me/diagnose.py`. The saved-arm diagnosis was reconstructed and checked against its saved scores. No new station identities are inferred from proximity.

Enumeration includes **every ordered pair searched by `join_chine`** (upper lowest waterline exactly one level above lower highest), plus vertically ordered pairs with ends within one waterline spacing (300 px) even if the level gate excludes them. Thus distant search candidates are retained, not filtered away. Δx and Δy are upper-piece bottom end minus lower-piece top end, in image coordinates. Gap is Euclidean. Reach is the greatest distance from either endpoint to the fitted line intersection. Both gap and reach must meet the same tolerance; small gap alone is insufficient.

#### aft

Waterline spacing = 300.0 px; endpoint fit window = 30.0 px (skip first 3 px, at least 5 samples and 15 px row span). Gap and intersection reach ≤ **11.970 px** = min(2 × median station width, 0.05 × spacing). Angle ≥ **20°**. Level step = **1**.

| Lower → upper chain | Level step (=1) | Δx / Δy px | Gap px (≤ 11.970) | Angle ° (≥20) | Reach px (≤ 11.970) | First rejection; other failed local gates |
|---|---:|---:|---:|---:|---:|---|
| 7 → 0 | 2 | -24.00 / -255.00 | 256.13 | 68.64 | 253.33 | adjacent levels; gap; intersection reach |
| 7 → 1 | 2 | -24.00 / -255.00 | 256.13 | 68.64 | 253.33 | adjacent levels; gap; intersection reach |
| 7 → 2 | 2 | -15.00 / -255.00 | 255.44 | 69.14 | 255.53 | adjacent levels; gap; intersection reach |
| 7 → 3 | 2 | -15.00 / -255.00 | 255.44 | 69.14 | 255.53 | adjacent levels; gap; intersection reach |
| 7 → 4 | 1 | 34.50 / 56.00 | 65.77 | 64.56 | 44.27 | gap; intersection reach |
| 7 → 5 | 1 | 34.50 / 56.00 | 65.77 | 64.56 | 44.27 | gap; intersection reach |
| 7 → 6 | 1 | 83.50 / 67.00 | 107.06 | 59.04 | 80.12 | gap; intersection reach |
| 7 → 10 | 1 | 16.50 / 63.00 | 65.12 | 73.48 | 54.36 | gap; intersection reach |
| 7 → 11 | 1 | 64.50 / 63.00 | 90.16 | 61.98 | 61.91 | gap; intersection reach |
| 8 → 0 | 2 | -24.00 / -255.00 | 256.13 | 68.64 | 253.33 | adjacent levels; gap; intersection reach |
| 8 → 1 | 2 | -24.00 / -255.00 | 256.13 | 68.64 | 253.33 | adjacent levels; gap; intersection reach |
| 8 → 2 | 2 | -15.00 / -255.00 | 255.44 | 69.14 | 255.53 | adjacent levels; gap; intersection reach |
| 8 → 3 | 2 | -15.00 / -255.00 | 255.44 | 69.14 | 255.53 | adjacent levels; gap; intersection reach |
| 8 → 4 | 1 | 34.50 / 56.00 | 65.77 | 64.56 | 44.27 | gap; intersection reach |
| 8 → 5 | 1 | 34.50 / 56.00 | 65.77 | 64.56 | 44.27 | gap; intersection reach |
| 8 → 6 | 1 | 83.50 / 67.00 | 107.06 | 59.04 | 80.12 | gap; intersection reach |
| 8 → 10 | 1 | 16.50 / 63.00 | 65.12 | 73.48 | 54.36 | gap; intersection reach |
| 8 → 11 | 1 | 64.50 / 63.00 | 90.16 | 61.98 | 61.91 | gap; intersection reach |
| 9 → 0 | 1 | -8.00 / -74.00 | 74.43 | 1.99 | 127.35 | gap; angle; intersection reach |
| 9 → 1 | 1 | -8.00 / -74.00 | 74.43 | 1.99 | 127.35 | gap; angle; intersection reach |
| 9 → 2 | 1 | 1.00 / -74.00 | 74.01 | 2.49 | 161.57 | gap; angle; intersection reach |
| 9 → 3 | 1 | 1.00 / -74.00 | 74.01 | 2.49 | 161.57 | gap; angle; intersection reach |
| 10 → 0 | 1 | -17.50 / -74.00 | 76.04 | 3.61 | 223.32 | gap; angle; intersection reach |
| 10 → 1 | 1 | -17.50 / -74.00 | 76.04 | 3.61 | 223.32 | gap; angle; intersection reach |
| 10 → 2 | 1 | -8.50 / -74.00 | 74.49 | 4.11 | 81.42 | gap; angle; intersection reach |
| 10 → 3 | 1 | -8.50 / -74.00 | 74.49 | 4.11 | 81.42 | gap; angle; intersection reach |
| 12 → 4 | 1 | -1314.50 / -119.00 | 1319.88 | 6.71 | 11251.18 | gap; angle; intersection reach |
| 12 → 5 | 1 | -1314.50 / -119.00 | 1319.88 | 6.71 | 11251.18 | gap; angle; intersection reach |
| 12 → 6 | 1 | -1265.50 / -108.00 | 1270.10 | 12.23 | 5973.00 | gap; angle; intersection reach |
| 12 → 10 | 1 | -1332.50 / -112.00 | 1337.20 | 2.22 | 34546.58 | gap; angle; intersection reach |
| 12 → 11 | 1 | -1284.50 / -112.00 | 1289.37 | 9.28 | 7961.96 | gap; angle; intersection reach |

Series gates (after local gates): each lower and upper endpoint must have **exactly 1** candidate; **at least 3** unique pairs; strict nesting at shared waterlines; column span **>15 px**; maximum straight-series row residual **≤12 px**.

Actual local-pass groups: `[]`.

#### fore

Waterline spacing = 300.0 px; endpoint fit window = 30.0 px (skip first 3 px, at least 5 samples and 15 px row span). Gap and intersection reach ≤ **11.738 px** = min(2 × median station width, 0.05 × spacing). Angle ≥ **20°**. Level step = **1**.

| Lower → upper chain | Level step (=1) | Δx / Δy px | Gap px (≤ 11.738) | Angle ° (≥20) | Reach px (≤ 11.738) | First rejection; other failed local gates |
|---|---:|---:|---:|---:|---:|---|
| 3 → 2 | 1 | 1013.50 / 126.00 | 1021.30 | 93.35 | 1022.47 | gap; intersection reach |
| 3 → 11 | 1 | 43.50 / 868.00 | 869.09 | 84.32 | 862.27 | gap; intersection reach |
| 4 → 0 | 1 | 1.50 / -7.00 | 7.16 | 66.30 | 11.56 | local pass; series gate |
| 4 → 1 | 1 | -100.50 / -45.00 | 110.11 | 64.76 | 120.23 | gap; intersection reach |
| 4 → 2 | 2 | -270.50 / -90.00 | 285.08 | 64.94 | 312.46 | adjacent levels; gap; intersection reach |
| 4 → 3 | 1 | 13.50 / 10.00 | 16.80 | 141.01 | 10.57 | gap |
| 4 → 10 | 1 | -1240.50 / 652.00 | 1401.41 | 73.97 | 1291.93 | gap; intersection reach |
| 5 → 0 | 1 | 1.50 / -7.00 | 7.16 | 66.30 | 11.56 | local pass; series gate |
| 5 → 1 | 1 | -100.50 / -45.00 | 110.11 | 64.76 | 120.23 | gap; intersection reach |
| 5 → 2 | 2 | -270.50 / -90.00 | 285.08 | 64.94 | 312.46 | adjacent levels; gap; intersection reach |
| 5 → 3 | 1 | 13.50 / 10.00 | 16.80 | 141.01 | 10.57 | gap |
| 5 → 10 | 1 | -1240.50 / 652.00 | 1401.41 | 73.97 | 1291.93 | gap; intersection reach |
| 6 → 0 | 1 | 84.50 / 38.00 | 92.65 | 63.81 | 97.93 | gap; intersection reach |
| 6 → 1 | 1 | -17.50 / 0.00 | 17.50 | 62.27 | 21.37 | gap; intersection reach |
| 6 → 2 | 2 | -187.50 / -45.00 | 192.82 | 62.44 | 217.97 | adjacent levels; gap; intersection reach |
| 6 → 3 | 1 | 96.50 / 55.00 | 111.07 | 138.52 | 117.49 | gap; intersection reach |
| 6 → 10 | 1 | -1157.50 / 697.00 | 1351.15 | 71.48 | 1221.51 | gap; intersection reach |
| 7 → 2 | 1 | 12.00 / -11.00 | 16.28 | 61.85 | 11.82 | gap; intersection reach |
| 7 → 11 | 1 | -958.00 / 731.00 | 1205.04 | 70.88 | 1013.78 | gap; intersection reach |

Series gates (after local gates): each lower and upper endpoint must have **exactly 1** candidate; **at least 3** unique pairs; strict nesting at shared waterlines; column span **>15 px**; maximum straight-series row residual **≤12 px**.

Actual local-pass groups: `[{"level": 1, "candidates": [[4, 0], [5, 0]], "unique": [], "accepted": []}]`.


#### Interpretation and change decision

- **Aft: no local pair passes.** The nearest searched bottom-to-top pair is 7/8 → 10 (65.12 px gap, 54.36 px reach), far above 11.970 px. Chains 7 and 8 have the same followed upper endpoint, and chains 4 and 5 have the same lower endpoint. Raising tolerance to 66 px would admit several ambiguous alternatives; it would not establish station identity. The 74 px gaps to chains 0–3 also have only 1.99–4.11° turns, so lowering the angle gate would confuse a same-direction continuation with a knuckle.
- **Fore: two local passes, zero unique pairs.** 4 → 0 and 5 → 0 both pass the existing geometric gates, but share the same upper chain. The uniqueness rule removes both; therefore the three-pair series rule sees zero unique pairs. These lower chains share their W-1 crossing but have different W-2 nodes. They are not interchangeable station identities.
- **Two plausible fore joins just miss proximity gates.** 6 → 1 needs 17.50 px gap and 21.37 px reach; 7 → 2 needs 16.28 px gap and 11.82 px reach. An approximately 22 px tolerance would admit them. It would also admit 4/5 → 3, whose 141.01° direction change and shared bottom geometry are not evidence of a valid station continuation. Even after resolving that ambiguity, only two unique neighbouring joins would remain, below the three-station requirement. A tolerance increase alone cannot recover the full series.
- **Path ends are not necessarily chine endpoints.** Fore chain 3 ends at x=3270 (centreline) on its upper extension, while its W0 crossing is far out; its pair with chain 2 has a 1021.30 px gap. The frozen `chain_path` follows up to 1200 rows beyond measured crossings and can follow another line. A large endpoint gap can therefore be a wrong path branch, not a physical gap in the drawing. It is not safe to bridge it by raising a tolerance.

**No detector or threshold change is justified by this endpoint table alone.** It supports a specific next investigation: re-trace locally from the measured crossings toward the chine, distinguish shared/merged paths, and validate branch choice and nesting before assigning each short bottom piece. That is more than a threshold adjustment. It needs additional ink evidence and synthetic tests for the shared endpoints and branch changes. Do not use truth proximity as the production pairing rule.

The current result remains **34/57, RMS 0.1346956535 m**, not an improvement. No detection change is made in this diagnostic commit, so the five-sheet results above remain the current measurements. Do not integrate this unchanged detector into the product path.

Reproduce the diagnostic table:

```bash
set -o pipefail
PYTHONPATH=src:. .venv/bin/python scripts/diagnose_body_plan_chine.py \
  --sheet /Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources/haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif \
  --truth /private/tmp/claude-501/pardon-me/truth_s4.json \
  --runs /private/tmp/claude-501/pardon-me/runs \
  --out outputs/body_plan_chine_diagnosis.json \
  --markdown work/chine/why-no-joins.md
```

The JSON includes full-precision endpoints, fitted directions, intersections, failed gates and chain-crossing records. The script calls the module's `_end`, `_meeting`, and `_series` and independently lists each rejected gate; it also calls the existing saved-run diagnosis and requires its scores to match. All local-pass candidates were checked against the module's actual candidate search. The production module, its constants, the frozen files, and the intake path are unchanged.


## Chine line measurement

Module `src/vessel_reconstruction/body_plan_chine_line.py`; benchmark `scripts/measure_chine_line.py` (writes `work/chine/chine_line_measurement.json`, git-ignored); test `tests/test_body_plan_chine_line.py`. The module reads only the ink mask, the host calibration and the frozen reader's measurement. Truth is read afterwards for the table only.

Method: seed on heavy ink runs (1.5 to 2.0 curve widths) and trace each as a shallow line column by column, passing crossing lines. Keep long shallow strokes. Continue the stroke on its fitted line past each end, because the heavy line merges with other lines near the knuckles. For each reader chain, take where its path crosses the stroke, or where a quadratic continuation of its path end meets it (at most 1.5 waterline spacings). The chine is the stroke with the most chains that have measured crossings on both sides (the sheer has them only below, the keel only above). Chine points are the upper-piece meetings, outermost first, assigned to stations by rank. Chains drawn on top of each other give one point.

Result on PARDON ME with the harness calibration: a chine line is found on both halves (fore: 7 chains on both sides; aft: 4). Station 1 to 11 all get a point. Units: feet (300 px/ft), baseline row 5229. Error = measured minus printed.

| Station | y measured | y printed | y error | z measured | z printed | z error |
|---|---|---|---|---|---|---|
| 1 | 1.043 | 1.057 | -0.014 | 0.390 | 0.411 | -0.021 |
| 2 | 2.487 | 2.516 | -0.029 | 0.217 | 0.240 | -0.023 |
| 3 | 3.375 | 3.385 | -0.011 | 0.073 | 0.078 | -0.005 |
| 4 | 3.939 | 3.953 | -0.014 | -0.075 | -0.078 | +0.003 |
| 5 | 4.281 | 4.297 | -0.016 | -0.204 | -0.208 | +0.004 |
| 6 | 4.656 | 4.484 | +0.172 | -0.477 | -0.302 | -0.175 |
| 7 | 4.519 | 4.589 | -0.070 | -0.487 | -0.375 | -0.112 |
| 8 | 4.449 | 4.630 | -0.181 | -0.491 | -0.417 | -0.075 |
| 9 | 4.417 | 4.578 | -0.161 | -0.494 | -0.458 | -0.035 |
| 10 | 4.357 | 4.521 | -0.164 | -0.498 | -0.490 | -0.008 |
| 11 | 3.980 | 4.427 | -0.447 | -0.580 | -0.500 | -0.080 |

RMS over 11 stations: half-breadth **0.171 ft (0.052 m)**, height **0.072 ft (0.022 m)**. Fore stations 1 to 5: 0.018 ft and 0.014 ft (sub-pixel to 9 px). Aft stations 6 to 11: 0.231 ft and 0.097 ft. The aft points sit in a cluster about 70 px wide where the station curves overlap, the reader's chains 0/1, 2/3 and 4/5 share paths, and the six aft points follow the reader's chain order. Station 11 (error -0.447 ft) is a chain that crosses the line 130 px away from the cluster; it is probably a wrong chain, so the aft assignment by rank is not trustworthy.

### Can it fill PARDON ME's missing cells?

Published baseline: 34 of 57 cells, 23 missing. Cheap test (comparison only, not product code): fill a missing cell by straight-line interpolation on its station between the chine point and the nearest measured crossing on the same side of the chine. Only **6 of 23** missing cells have such a neighbour (W0 cells of stations 1, 2, 6, 7, 8, 9); the other 17 have no measured crossing on that side. On those 6, RMS error is 0.099 m, maximum 0.199 m. Stations 1 and 2 are errors of the reader identity (their W0 points are far off), and stations 6 to 9 are 0.01 to 0.05 m. The chine line fixes where the knuckle is, but it does not supply the lower-piece crossings at W-1 and W-2 (the stations 3 to 10 fan lines) or the stations 1 and 2 curves; those cells need curve tracing along the lower pieces, not a chine point. Expect the chine line to recover at most about 4 of 23 cells at useful accuracy (aft W0, 0.01 to 0.05 m). Not integrated into the product path.

## Resume point (PM, 2026-11-10)

Neither joining (no join fires: aft gaps ~65 px, fore ambiguity) nor the chine line (accurate fore, ~5 mm, but it fills
only ~4 of 23 missing cells) closes PARDON ME's gap. Most missing cells are the short station pieces below the chine,
which the frozen reader drops because it keeps only chains crossing two or more waterlines, plus the identity errors at
stations 1-2. Next: a reader v2 (new module, frozen files untouched) that accepts one-waterline pieces below a detected
chine line as station pieces, named by their chine point; PARDON ME is a dev case, so the result needs a new hard-chine
holdout sheet.

## Reader v2 (branch `feature/chine-reader-v2`)

Module `src/vessel_reconstruction/body_plan_reader_v2.py`; benchmark `scripts/measure_chine_reader_v2.py`
(writes `outputs/body_plan_chine_reader_v2.json`); tests `tests/test_body_plan_reader_v2.py`. The frozen
crossings, reader and identity modules are untouched. PARDON ME is a **development case**: it guided the design,
so its numbers below are not evidence of generalisation.

Method (code only, no truth, no vessel names):

1. Find the chine line with `body_plan_chine_line`. Reject a stroke that lies on a drawn waterline (most of it within
   2 curve widths of a waterline row): this is what the old line finder returned on C.A. Thayer and Balclutha. Without a
   verified line a side keeps the frozen rank identities, so a round-bilge sheet is unchanged.
2. Upper pieces: chains that reach the line and have at least two measured crossings above it. Chains that share the
   same highest crossing are one curve (the frozen builder forks one curve into several chains). Groups are ranked
   outermost first by nesting at one waterline that all groups cross; the k-th group is station k. Its chine point is
   where its chains meet the line.
3. Lower pieces: every station crossing below the line is re-traced up its own ink to the line (`follow_curve`).
   It is named after the chine point where it arrives, if that point is within 0.10 waterline spacing and at least
   twice nearer than the next point. A crossing on the line and running along it is the line itself and is skipped.
4. A cell that two different crossings claim is left empty (abstained), as is a crossing that does not arrive at one
   clear chine point. No neighbouring value, truth or position prior picks a branch.

Metrics as in "Metrics and acceptance". Added: wrong cells = cells given with error above 0.15 m (the harness band).

### Holdout protocol (written before any reader run on a candidate)

- **Candidate.** A public-domain hard-chine body-plan sheet with a printed table of offsets that gives half-breadths
  (or can be converted without judgement) at stations and waterlines. Record source URL and rights statement. Download
  to `work/holdout/` only (git-ignored). The sheet must not be one of the five dev sheets.
- **Truth.** Only the printed table of offsets, keyed by station and waterline, read by a person or a model that does
  not see reader output, frozen to a file outside the repository before the reader runs. Cells that are blank or
  illegible are not truth cells. Truth is never read by the reader.
- **Calibration.** Centre column, pixels per metre, waterline rows, maximum offset, sides, station order and grid
  columns are set once from the drawing's own scale and labels, recorded in this file before scoring, and not changed
  after scoring.
- **Arms.** Frozen reader with rank identities versus reader v2, same calibration, same scorer.
- **Report.** Cells given / truth cells, RMS and maximum error on common cells, wrong cells (> 0.15 m), identity
  errors (harness check), extra and missing cells, abstained crossings, whether a chine line was verified per side.
- **Gates (pass only if all hold).** v2 gives at least as many cells as frozen; v2 RMS and wrong cells are not worse
  than frozen; v2 wrong cells are at most 10 percent of cells given; no extra cell that the truth shows is blank;
  the verified chine line is on the drawn chine (checked on the overlay).
- **No tuning.** Constants in `body_plan_reader_v2.py` and `body_plan_chine_line.py` are fixed before the run. One run
  is scored. A failure is reported as a failure; fixes after scoring make the sheet a development case.
- **Round-bilge check.** The same run must leave every round-bilge dev sheet identical to the frozen result.

### Holdout protocol amendment (PM, 2026-11-10, before any reader run on a candidate)

The two hard-chine candidates found (E. C. COLLIER, HAER MD-77 sheet 2; skipjack CALEB JONES, HAER MD-171 sheet 1)
print **point offsets**, not waterline half-breadths: for each station, height above base and half-breadth of the
SHEER, CHINE and RABBET. Interpolating straight lines between them would add judgement (the COLLIER sheet notes a
slightly hollow bottom aft). So for these sheets:

- **Truth cells** are the printed (station, point) pairs: chine half-breadth at chine height, sheer half-breadth at
  sheer height, and rabbet half-breadth at rabbet height. No interpolated waterline truth is made.
- **Reader value for a truth cell**: the reader's traced station curve evaluated at the printed height of that point
  (the half-breadth of the station curve at that z). A station with no traced curve at that height gives no cell.
- **Metrics and gates** are otherwise unchanged (cells given, RMS, max, wrong cells > 0.15 m, identity errors, both
  arms, no tuning, one scored run). A separate line reports the chine cells only.
- **Files** are in `work/holdout/<boat>/` (git-ignored) with a SOURCE.md (URL, rights, sha256). COLLIER:
  `md1203-sheet-00002a-lines.tif`, sha256 80e689130705ffcbd46716320865502a618a69cdd94d96191c3cafc3b22e0637.
  CALEB JONES: download pending.
- **Truth entry**: a person or a model that does not see reader output reads the table into
  `work/holdout/<boat>/truth.json` (feet-inches-eighths converted to metres), frozen before the run.

### Holdout candidates (state: none scored)

The Library of Congress site and `tile.loc.gov` answer this host with a Cloudflare challenge (HTTP 403, "Just a
moment"). The challenge is not bypassed, so no sheet was downloaded and no truth exists. Candidates from catalogue
search results (hull form not verified by eye; rights: HAER/HABS drawings are US Government works, the LoC rights
advisory lists no known restrictions; confirm on the item page before use):

| Candidate | Catalogue URL | Note |
|---|---|---|
| St. Lawrence River Skiff, Antique Boat Museum (HAER NY-2432) | https://www.loc.gov/resource/hhh.ny2432.sheet | lines plan with table of offsets; hull form unknown |
| 19' 6" Mukilteo Boat, Center for Wooden Boats (HAER WA-224) | https://www.loc.gov/resource/hhh.wa0921.sheet | lines and offsets table; likely round or lapstrake |
| USS Saginaw Gig (HAER VA-146) | https://www.loc.gov/resource/hhh.va2293.sheet | lines plan and table of offsets; likely round |
| Skipjack KATHRYN (HAER MD-117) | search the LoC catalogue for "Kathryn skipjack" | skipjacks are hard-chine; sheets not located |

**Protocol state: written, nothing run.** The next step needs a person (or a browser session that passes the
challenge normally) to download one or two sheets into `work/holdout/`, then freeze truth and calibration as above.

### Reader v2 results (PARDON ME is a development case)

Frozen reader (rank identities) versus reader v2, same harness calibration and scorers; BUMBLE BEE with the
corrected sides. Evidence: `outputs/body_plan_chine_reader_v2.json`.

| Sheet | Cells given | RMS m | Max m | Wrong cells (>0.15 m) | Identity-error stations |
|---|---|---|---|---|---|
| PARDON ME (development) | 34/57 -> 45/57 | 0.134696 -> 0.005556 | 0.6372 -> 0.0297 | 3 -> 0 | [6, 10, 11] -> [6] |
| BUE GIRL | 37/39 -> 37/39 | 0.001431 (same) | 0.0058 (same) | 0 -> 0 | [] |
| C.A. Thayer | 149/151 -> 149/151 | 0.011616 (same) | 0.1324 (same) | 0 -> 0 | [] |
| Balclutha | 151/151 -> 151/151 | 0.148012 (same) | 1.8113 (same) | 1 -> 1 | [] |
| BUMBLE BEE (corrected) | 50/54 -> 50/54 | 0.148585 (same) | 0.4636 (same) | 13 -> 13 | [1..6] (same) |

Round-bilge check: no chine line is accepted on BUE GIRL, C.A. Thayer, Balclutha or BUMBLE BEE (the two false lines
on Thayer and Balclutha lie on waterlines and are rejected), so those sheets give the frozen table unchanged.

PARDON ME: all stations 1-5 (fore) are now named from their chine points. The wrong W-1/W-2 values that the frozen
reader gave to stations 1 and 2 are gone, and their W3 to W-1 cells are filled. Aft W3 and W2 are fixed for stations
10 and 11 (a curve forked into two chains had shifted the numbering).

Still missing (12 cells): station 2, 3, 4 at W-2 (two lines meet at 0.13 m near the keel and both trace to station 5;
two crossings claim one cell, so the cell is left empty); aft W-1 for stations 6 to 10 (the six lower pieces run along
the heavy line for about 300 px and meet within 15 to 70 px; no arrival is clearly nearest, so all are left out); aft W0
for stations 6 to 9 and aft W1 for station 9 (links across the cluster are ambiguous). Station 6 remains an identity
error (it crosses its neighbours between W2 and W0).

Limits: development case only; one drawing style; the line finder is unchanged and its weak points (wrong
branch at merges) are handled only by abstention. No holdout has been scored.

### E. C. COLLIER holdout: calibration and scorer (written before any reader run on the sheet)

Branch `feature/collier-holdout`. Calibration `benchmarks/ec_collier/holdout_value.py`; scorer
`benchmarks/ec_collier/point_score.py`; tests `tests/test_ec_collier_holdout.py`; overlay
`scripts/ec_collier_calibration_overlay.py` (writes `work/ec_collier/calibration_overlay.png`, git-ignored).
No reader has run on the sheet. Truth (`work/holdout/ec-collier/truth.json`, sha256 a6ef1671...) was not opened.

**Disclosure.** The brief listed `preview_8x.png` (whole sheet, 1/8 scale) as an input. It shows the printed
table of hull measurements at low resolution, so the calibrating agent saw the table. No constant was set from it:
every constant comes from the scale bars, the drawn base line, centreline and labels (sources in the file comments),
and the measuring rows are a fixed grid from the scale.

Calibration (full-sheet pixels):

| Constant | Value | How set |
|---|---|---|
| Pixels per foot | 150.25 | feet scale bar, ticks 0 and 70 ft (columns 1995.0, 12512.5). Drawn vertical "8'-10 1/2" extreme half-breadth" gives 149.9 (0.2 %). The metres bar (500.2 px/m, labelled 1:24) and the 45'-10" length dimension (153.4 px/ft) disagree and are not used |
| Centre column | 3209.3 | fit of the centreline ink, at row 6950 (mid hull); +1.2/-1.1 px over the hull rows |
| Base row | 7656.1 at the centre, slope 0.001144 row/column | fit of the drawn BASE LINE; heights are measured from the sloped line |
| Sides | aft left, outer first (4, 3, 2, 1, 0); fore right, outer first (5, 6, 7, 8, 9, 10) | two readings that agree: (1) labels in the body plan; (2) profile: station 0 at the transom, 10 at the stem, widest at station 4 to 5 |
| Grid columns | none | no buttocks drawn |
| Max offset | 1370 px | hull ink reaches 1341 (aft) and 1318 (fore); aft station labels start at 1381 |
| Measuring rows | every 6 in from 0.5 ft to 8.0 ft above base (16 rows, 75.1 px apart), labels '0-6-0' ... '8-0-0' | scale only; top row above the top of the log rail at the centre |

Row spacing is a choice with consequences for both readers and was made before any run. The reader's
spacing-scaled constants were developed on 300 to 600 px spacings. A 3-inch grid (37.6 px) would put most of any
traced chine line within v2's waterline-rejection band (about 13 px either side of each row), so v2 would reject
its own chine line, and the chine-point match radius would be 3.8 px. A 1-ft grid (150 px) suits the constants but
leaves few rows for interpolation. 6 inches is the compromise. The sheet has no drawn waterlines, so a row near a
drawn line (light waterline at 3.5 ft, keel and deck lines) is moved onto it by the frozen waterline locator; the
scorer uses each crossing's measured row, so this does not move a scored height.

Scorer (amendment):

- Truth cells: printed (station, point) for SHEER, CHINE, RABBET with both height and half-breadth printed.
- Reader value: the station's half-breadth at the printed height, linear between its crossings on two consecutive
  measuring rows that enclose the height (heights from each crossing's measured row and column). No extrapolation;
  if either enclosing row has no crossing for the station, no cell.
- Report: cells given / truth cells, RMS, maximum, wrong cells (> 0.15 m), the same for chine cells only and per
  point, identity errors, missing and extra cells, unevaluable blank points; per arm, abstentions and whether a
  chine line was verified per side (v2).
- Identity errors: as the harness (a station's curve fits station ±1's printed points better than its own), with at
  least **2** shared points instead of 3, because a station has at most 3 printed points.
- Extra cell: a reader value at a printed height whose half-breadth is printed blank. A point with a blank height
  cannot be evaluated and is listed only.
- Gates (unchanged): v2 cells >= frozen; v2 RMS and wrong cells not worse; v2 wrong <= 10 % of v2 cells given; no
  extra cell on blank truth; the verified chine line on the drawn chine (overlay, by eye).
- Truth loader: accepts the table form (`stations`, a height table and a half-breadth table keyed by point), a list
  of records, or station -> point -> values; values as feet-inches-eighths strings or numbers in metres (feet or
  inches when the key ends `_ft`/`_in`); refuses values outside 0 to 4 m. It has not been run on truth.json.

Known limits before the run: the bottom is shallow (about 1:6 to 1:9 rise on the aft half), and the frozen
crossing classifier calls lines flatter than 6 columns per row "shallow", not station curves; so many rows below
the chine will have no bottom crossings and chine and rabbet cells may be missing. Where a station does have a
crossing below the chine, interpolating across the knuckle can give a large chine error at 6-inch spacing. The fore
label "5" lies beside station 5 within the reach limit.

PM approved the calibration as committed (6-inch rows) and gave the truth file format; the loader accepts exactly
that format and checks the truth sha256 (`6915b3b`). Run script `scripts/measure_ec_collier_holdout.py` (`e1c7d25`).

### HOLDOUT RESULT: E. C. COLLIER (one run, no tuning) - FAIL

One run of both arms on 2026-11-10 with the committed calibration and scorer; no constant changed after the run.
Source and protocol files unchanged since `2d31179`. Evidence (git-ignored): `work/ec_collier/holdout_result.json`
(sha256 09d88133...), overlay `work/ec_collier/holdout_v2_overlay.png`. Truth sha256 a6ef1671... matched; the file
lists 1 "unsure" entry (not used). The script wrote the JSON and overlay, then failed on a diagnostic print (a numpy
integer in `json.dumps`); that print was fixed afterwards, display only. The run was not repeated.

| Arm | Cells given | RMS m | Max m | Wrong (>0.15 m) | Identity errors | Extra | Abstained | Chine line verified (aft / fore) |
|---|---|---|---|---|---|---|---|---|
| Frozen (rank identities) | 7/31 | 0.9124 | 2.3133 | 3 | [] | 0 | - | - |
| Reader v2 | 7/31 | 0.9124 | 2.3133 | 3 | [] | 0 | 0 / 0 | no / no |

Chine cells only (both arms): **4/10, RMS 0.2057 m, max 0.4032 m, 1 wrong.** By point (both arms): sheer 2 cells
(RMS 0.391 m, 1 wrong), chine 4 (0.206 m, 1 wrong), rabbet 1 (2.313 m, 1 wrong). Cells given: chine of stations
0, 1, 2, 3 (errors +0.403, -0.010, +0.081, -0.009 m); sheer of stations 8 and 10; rabbet of station 10.

Gates:

| Gate | Result |
|---|---|
| v2 cells >= frozen | pass (equal) |
| v2 RMS not worse | pass (equal) |
| v2 wrong cells not worse | pass (equal) |
| v2 wrong <= 10 % of cells given | **fail** (3/7 = 43 %) |
| No extra cell on blank truth | pass |
| Verified chine line on the drawn chine | **fail**: no line is verified on either half |

**Result: FAIL.** v2 equals the frozen reader on this sheet: it verified no chine line, so both halves kept the
frozen rank identities. Aft: the line finder found no line. Fore: it traced the drawn light waterline (rows 7128 to
7138, 3.5 ft), which v2 correctly rejected as lying on a measuring row. The drawn chine (the curve through the station
knuckles) was not found on either half.

Why so few cells: the frozen reader measured crossings mainly on the station sides above the chine; the shallow
bottom gave few station crossings (aft: 3 crossings classed "shallow"; fore: none), so heights below the chine are
mostly unmeasured. Sheer cells are missing because the chains above the deck line run along the log-rail and deck
lines, or end. The identity check finds no error only because few stations have two scored points; the frozen chains
are visibly misnamed (for example the chain named station 10 is the station 5/6 side below 6 ft, then a deck line),
which gives the 2.31 m rabbet error and the 0.55 m station-8 sheer error.

E. C. COLLIER is now spent as a holdout; any change made after looking at this result makes it a development case.

## V-bottom polyline reader (branch `feature/vbottom-reader`, 2026-11-10)

Module `src/vessel_reconstruction/body_plan_polyline.py`; tests `tests/test_body_plan_polyline.py` (synthetic
PIL body plans: both halves, round bilge, a missing inner station, crossing lines, buttock grid lines);
measurement `scripts/measure_vbottom_collier.py` (COLLIER, point scorer) and `scripts/measure_vbottom_dev_sheets.py`
(five waterline dev sheets). The frozen `body_plan_{crossings,reader,identity}.py` are not edited (hashes as in
"Boundaries", checked). **E. C. COLLIER is a DEVELOPMENT case** (its holdout is spent); its truth was read only to
score and diagnose, never by the reader. PARDON ME is a development case too.

Why a new reader: the crossing reader measures stations where they cross horizontal rows. A low-deadrise bottom
runs nearly horizontal, so it barely crosses rows and the classifier calls it "shallow"; on COLLIER no chine line
was found and the chains were misnamed (7/31 cells, 3 wrong).

Method (code only; no truth, no vessel names, no benchmark constants):

1. **Seeds**: narrow, steep ink runs on the half just off each measuring row (station sides). Runs near the
   centre column are skipped. Scan lines are joined across 1 to 2 px specks (the 1-bit scan breaks lines).
2. **Side**: each seed is followed up and down along its own ink (step 2 px; perpendicular search; a run wider
   than 1.8 line widths is a crossing line and is passed on the trace's straight prediction). The side is cut at
   its first sharp corner below and above the seed (where the trace ran on along the chine curve or a deck line).
   A side on a calibrated buttock column is rejected.
3. **Bottom**: from the side's lower end, branches are followed inward at 2-degree steps. A bottom must start on
   ink, never rise above its start, descend overall, be long (half the knuckle half-breadth and 15 line widths),
   not lie along one drawn waterline row, and is cut at its own first sharp corner (the keel). The branch that
   reaches nearest the centreline is taken; a start further up the side is tried only when none leaves the end.
   The drawn chine curve between knuckles rises inward and is therefore never taken as a bottom.
4. **Knuckle**: the intersection of straight fits of the side's lower arm and the bottom's outer arm. It must
   turn by 25 degrees or more and be sharp (half-length arms see at least 75 % of the turn; a round bilge turns
   gradually) and lie within 2 line widths of the ink.
5. **Names**: stations ranked outermost first by nesting and named in the calibration's order. More stations
   than the calibration lists: the half is declined. Fewer: names run from the outermost and the innermost are
   left unread, unless a long untraced side-like line lies between two traced stations; then stations inward of
   it are not named (this stopped a misnaming on PARDON ME, where station 4's line was lost). A knuckle out of
   the chine order (half-breadths must decrease inward) is not named.
6. **Decline**: a half with fewer than max(3, half the calibration's stations) knuckled stations is declined and
   keeps the existing reader.

Output per station: the (row, column) polyline from rabbet to the top of the traced side, the chine, sheer and
rabbet points, and `half_breadth_m(row)` at any row (rows decrease strictly along the polyline, so it crosses a
row once). `waterline_table` gives a waterline table for scoring. The **sheer** is the top end of the traced side:
where the station's tick runs on into the log rail it is the rail top, otherwise the rail's lower edge, so it is
not one drawn feature.

### COLLIER result (development case)

Committed calibration (`benchmarks/ec_collier/holdout_value.py`) and point scorer (`point_score.py`) unchanged. The
polyline's own points are passed to the scorer as consecutive samples, so the scorer interpolates along the traced
ink, not between 6-inch rows. Evidence (git-ignored): `work/vbottom/collier_result.json`, overlay
`work/vbottom/collier_result_overlay.png` (knuckles on the drawn chine curve, checked by eye).

| Arm | Cells given | RMS m | Max m | Wrong (>0.15 m) | Chine only | Identity errors | Extra |
|---|---|---|---|---|---|---|---|
| Frozen (baseline, reproduced) | 7/31 | 0.9124 | 2.3133 | 3 | 4/10, RMS 0.2057, 1 wrong | [] | 0 |
| Polyline | **22/31** | **0.0691** | **0.1883** | **2** | **10/10, RMS 0.0412, max 0.108, 0 wrong** | [5] | 0 |

By point (polyline): sheer 6 cells, RMS 0.007 m; chine 10, RMS 0.041 m; rabbet 6, RMS 0.121 m, 2 wrong
(stations 2 +0.157, 7 +0.188). Point-scorer gates (polyline in place of v2): all code gates pass (22 >= 7; RMS,
wrong not worse; 2/22 = 9 % wrong; no extra cell).

All 10 traced stations (aft 4..0, fore 5..9) carry their own knuckle; fore station 10 (it meets the stem) is not
read. Missing cells: sheer of 1, 4, 7, 8, 10 (the traced side stops at the rail's lower edge, below the printed
sheer height); rabbet of 4, 6, 9, 10 (printed rabbet height below the traced bottom's inner end). The rabbet
errors are where the low-deadrise bottoms merge at the keel: there 1 cm of height is about 10 cm of half-breadth.
Identity error [5]: stations 4 (aft) and 5 (fore) are the two widest sections and nearly equal, so the 2-point
neighbour check prefers station 4's points for station 5; the names follow the calibration's side order.

### Dev sheets: round-bilge decline and PARDON ME

Product rule measured: a half the polyline reader reads takes its waterline table; a declined half keeps the frozen
rank-identity table. Same calibrations, truth and scorers as reader v2. Evidence: `work/vbottom/dev_sheets.json`.

| Sheet | Halves read | Cells | RMS m | Max m | Wrong | Identity errors |
|---|---|---|---|---|---|---|
| PARDON ME (dev) | fore | 34/57 -> 43/57 | 0.134696 -> 0.035633 | 0.6372 -> 0.1621 | 3 -> 1 | [6, 10, 11] (same) |
| BUE GIRL | none | 37/39 (same) | 0.001431 (same) | 0.0058 | 0 | [] |
| C.A. Thayer | none | 149/151 (same) | 0.011616 (same) | 0.1324 | 0 | [] |
| Balclutha | none | 151/151 (same) | 0.148012 (same) | 1.8113 | 1 | [] |
| BUMBLE BEE (corrected) | none | 50/54 (same) | 0.148585 (same) | 0.4636 | 13 | [1..6] (same) |

Round-bilge check: every half of BUE GIRL, Thayer, Balclutha and BUMBLE BEE is declined; their tables are
identical to the frozen tables. Margin: at most 3 knuckled "stations" were found on a round-bilge half (Balclutha
fore: 3 of 10 needed 5); these are grid and keel junctions, not stations. The first version (before the grid-line
rules) read BUE GIRL wrongly on both halves (22/39, RMS 0.39 m): buttock lines meeting waterlines look like knuckles.
PARDON ME: fore stations 5, 4, 3, 2 are read (station 1 not); the aft half (a tight cluster of curves on one
heavy line) is declined. Reader v2 remains better on PARDON ME (45/57, RMS 0.0056 m); the two readers address
different drawings and are not combined here.

Open items: sheer definition (rail edge vs top of tick); rabbet cells at merged keel lines; station 10/stem
sections; a hollow bottom is followed but its corner test is tuned only on straight bottoms; the decline margin on
Balclutha is small; product integration (`body_plan_intake.py`) is not done; no holdout scored.

### Holdout protocol: WHITE GULL and COLLEEN (written before any run; folders not opened)

`work/holdout/white-gull/` and `work/holdout/colleen/` are **UNSCORED HOLDOUTS**. Nothing in them was opened while
writing this module or this protocol. The reader under test is `body_plan_polyline.py` at sha256
`1f39f8661ffd2967e9309a0cc777e9d26e5320956ac79504ac381f0fd2eb771a` with its constants as committed; any edit
before the run is recorded and the protocol re-committed before the run.

- **Calibration first, per sheet**, in `benchmarks/<boat>/holdout_value.py`, committed before any reader run: centre
  column, base row (and slope), pixels per metre from the printed scale bar (checked against one drawn dimension),
  measuring rows (the drawn waterlines; where none are drawn, a fixed grid from the scale, as COLLIER), maximum
  offset, buttock grid columns, sides and station order. Sides are set by two independent readings (labels in the
  body plan; stem and stern in the profile) and both are recorded (lesson: check the side assignment twice).
- **Truth first**: the printed table, read by a person or a model that does not see reader output, into
  `work/holdout/<boat>/truth.json`, sha256 recorded here before the run. Blank or illegible cells are not truth.
- **Cells**: (a) **waterline cells**: printed (station, waterline) half-breadths, reader value = the station's
  polyline at that waterline's row (`waterline_table`), scored with the waterline harness scorer; (b) **point
  cells**: printed (station, SHEER/CHINE/RABBET) height and half-breadth pairs, scored with the COLLIER point-scorer
  rules (polyline evaluated at the printed height; no extrapolation). A sheet scores whichever kinds it prints.
- **Arms**: frozen reader with rank identities vs the product rule (polyline on read halves, frozen on declined
  halves), same calibration and scorer. Report separately for each kind of cell: cells given / truth cells, RMS,
  maximum, wrong cells (> 0.15 m), chine-only and sheer-only lines, identity errors (harness check), extra and
  missing cells, halves read or declined with the reader's notes.
- **Gates (pass only if all hold)**: polyline cells >= frozen; polyline RMS and wrong cells not worse; polyline wrong
  cells at most 10 % of cells given; no extra cell where truth is blank; on the overlay, every named knuckle lies on
  a drawn station corner (checked by eye and recorded). A round-bilge sheet passes only if both halves are declined
  and the table equals the frozen table.
- **One run, no tuning**: run once per sheet, the full JSON and overlay kept in `work/`. A failure is reported as a
  failure. Any change after the run makes the sheet a development case.

Verification (2026-11-10): `PYTHONPATH=src:. .venv/bin/python -m pytest -q`: 1730 passed, 1 skipped, 5 failed in
392 s. The 5 failures (`test_ship_cad.py` sandbox tests x3, `test_part_revise.py`, `test_whole_vessel_step1.py`) are
the macOS `sandbox-exec` worker exiting 71 inside this agent's own sandbox; they import nothing from this branch's
files (the branch adds 5 files and edits only this document). `tests/test_body_plan_polyline.py`: 8 passed. Frozen
reader hashes unchanged.

### WHITE GULL and COLLEEN: calibration and scorer (written before any reader run on either sheet)

Branch `feature/deadrise-holdouts`. Calibrations `benchmarks/white_gull/holdout_value.py` and
`benchmarks/colleen/holdout_value.py`; shared scorer `benchmarks/deadrise_holdout/score.py`; tests
`tests/test_deadrise_holdouts.py` (synthetic); overlay `scripts/deadrise_calibration_overlay.py` (writes
`work/deadrise_holdouts/<boat>_calibration_overlay.png`, git-ignored). `body_plan_polyline.py` sha256 checked:
`1f39f866...` as pinned above. **No reader has run on either sheet. No truth file was opened.** Sheet sha256 values
match SOURCE.md.

**Disclosure.** `table_crop*.png`, `truth*.json`, `preview_8x.png` and the PM scratchpad were not opened. To find the
body plan, profile and scale bar, the calibrating agent viewed each whole sheet once at 1/24 scale. On WHITE GULL the
table's numbers are not legible at that scale. On COLLEEN the table is larger and its row and column structure was
visible; no value was read or used. A note line under it was glimpsed. Every constant comes from the scale bars,
drawn lines, labels and the profile and half-breadth plans (sources in the file comments).

| Constant | WHITE GULL (1/2" = 1'-0") | COLLEEN (3/4" = 1'-0") |
|---|---|---|
| Pixels per foot | 200.0: feet bar 0 / 50 ticks at 2014.0 / 12014.0; metres bar 199.95 (0.03 %); drawn "4'-0"" station spacing 800 px, "3'-5 5/16"" 689 px (200.1) | 300.0: feet bar 0 / 5 ticks at 6225.0 / 7725.0; drawn beam "9'-5 3/8"" 2833 px (299.9), "4'-0"" station spacing 1200 px, "2'-6 3/4"" 770 px (300.5) |
| Centre column | 3779.5 (dash-dot ink 3778 to 3781; buttocks symmetric) | 2826.0 (dash-dot ink 2825 to 2827) |
| Base row | 4146.0, slope 0 (drawn "Baseline", below the keel) | 3133.0, slope 0 (drawn "Baseline", **above** the keel; keel bottom about -2.06 ft) |
| Measuring rows | drawn W2..W6 at 3746, 3546, 3345, 3145, 2945; W1 (not drawn in the body plan) at 3946 from the scale. Wk = k ft (profile labels, 200 px apart). Painted waterline (3658, 2.44 ft) is not a measuring row | no waterlines drawn; 6-inch grid from -2.0 to +3.5 ft (12 rows, 150 px), labels signed ft-in-eighths ('-1-6-0' ... '3-6-0') |
| Sides | fore LEFT outer first (5, 4, 3, 2, 1); aft RIGHT (6, 7, 8, 9, 10) | aft LEFT outer first (7, 8, 9); fore RIGHT (6, 5, 4, 3, 2, 1) |
| Grid columns | buttocks 1 to 6 ft both halves (3579.5 ... 2579.5; 3979.5 ... 4979.5) | none drawn |
| Max offset | 1356 px (hull 1341.5 left / about 1320 right; labels from 1358.5) | 1465 px (hull 1443 right / 1364 left) |

Sides, read twice (lesson: check the side assignment twice):

- WHITE GULL. (1) Body-plan labels: "Sta.1" to "Sta.5" left with leaders (5 outermost), "Sta.6" to "Sta.10" right
  (6 outermost). (2) Profile and plan: stem at the profile's right. No station numbers are printed there, so the plan's
  outer line was compared: 670 px at the station line next to the stem against about 690 px for the innermost left
  curve ("Sta.1"), and 1074 to 1102 px at the station line next to the transom against about 1020 to 1070 px for the
  innermost right curve ("Sta.10"). Stations count from the bow; left = forebody. Both readings agree.
- COLLEEN. (1) Labels: "1" to "6" along the right sheer (6 outermost), "7", "8", "9" on the left from the outside in.
  (2) The profile is labelled "Sta.9" (transom end) to "Sta.1" (stem). Half-breadth-plan chine at stations 7, 8, 9 =
  1311 / 1289.5 / 1262.5 px against the left curves near the chine at 1311.5 / 1287.5 / 1263.0 px. Station 1's sheer
  (685 px) is the innermost right curve. Left = aftbody. Both readings agree.

Known limits recorded before the run (not fixed; the protocol forbids tuning):

- **Transom outlines.** Each sheet has a heavy, unlabelled curve inside the last aft station, with a heavy horizontal
  lower edge at chine height (WHITE GULL right half, row 3771; COLLEEN left half, row 3239). It is not a station and is
  not listed. A reader that counts it as a station may decline the half (more curves than stations) or misname it.
- **COLLEEN fore nesting.** Station 6 is outside station 5 at the chine (1297 vs 1238 px in the plan), but station 5
  is wider at the sheer (1439 vs 1425 px). The two curves may cross near the top, which can break rank naming there.
- **Labels inside the reach.** WHITE GULL: the left "Chine" label lies across the W2 row (1220 to 1410 px out).
  COLLEEN: left "7" (2.5 ft row), both "Chine" labels (-0.5 ft row), right "4" (3.0 ft row) and right "2" (3.5 ft row,
  above the hull) are inside 1465 px. A single reach serves both halves, so these cannot be excluded.
- **COLLEEN grid.** Waterline truth cells are scored only on measuring rows. A printed waterline whose height is on
  no measuring row (within 0.02 ft) is listed in the result as unmatched and is not scored. The grid is never changed
  after a run. (Amended before the run, with the PM's truth format; the first draft stopped the loader instead.)
- WHITE GULL draws two sheer lines ("Actual Sheer" and "Measured Sheer"). The polyline sheer is the top of the traced
  side, as on COLLIER.

Scorer (`benchmarks/deadrise_holdout/score.py`, exactly the committed protocol):

- **Waterline cells**: printed (station, waterline) half-breadths. Arm values: frozen `table_from_identities`, v2
  `sheet_table`, polyline `waterline_table` on read halves with the frozen table on declined halves (product rule).
  Scored with the waterline harness scorer (`balclutha.model_value.score`, identity check with 3 shared waterlines)
  on the printed rows only, plus wrong cells (> 0.15 m) and missing / extra keys. Extra = a reader value where the
  printed cell is blank.
- **Point cells**: printed (station, SHEER / CHINE / RABBET) height and half-breadth pairs, COLLIER point-scorer
  rules. Frozen and v2 samples = the station's crossings on consecutive measuring rows; polyline = its traced points.
  No extrapolation. Identity check with 2 shared points. Separate chine-only, sheer-only and rabbet-only lines.
- **Truth file** (`work/holdout/<boat>/truth.json` in the main checkout, read-only), format given by the PM:
  `{"units": "ft-in-eighths", "stations": ["1", ..., "TRANSOM"], "x_positions": [...], "heights": {ROW NAME: [...]},
  "half_breadths": {ROW NAME: [...]}, "notes": {...}, "unsure": [...]}`. Row names are matched with all whitespace
  removed. Waterline truth = half-breadth rows "WL <height>". Point truth = SHEER, CHINE, RABBET. The rabbet
  half-breadth row is "RABBET", or "KEEL RABBET" when there is no "RABBET" (COLLEEN). The loader ignores BUTTOCK, KEEL
  and STEM EDGE rows and the TRANSOM column. Each value is feet-inches-eighths: a leading "-" makes the whole value
  negative, and a trailing "+" adds 1/16 inch. null = no cell. The loader refuses half-breadths outside 0 to 4 m and
  heights outside -1.5 to 4 m. It stops unless the sha256 equals `TRUTH_SHA256` in the calibration. WHITE GULL:
  `de30930e...a2f2`. COLLEEN: `bbc124ef...a4cc`.
- **Run script** `scripts/measure_deadrise_holdout.py --boat <boat>`: frozen, v2 and polyline (product rule) all
  read the sheet before the truth is loaded. Output: JSON and overlay in `work/deadrise_holdouts/`. Smoke-tested
  only on the COLLIER dev sheet with a fake truth file.
- Gates per kind of cell (`gates`): as the protocol, with the by-eye knuckle check recorded separately.

PM approved both calibrations as committed in `30611af` and gave the truth format and sha256 values (2026-11-10).

### HOLDOUT RESULT: WHITE GULL and COLLEEN (one run each, no tuning)

One run per sheet on 2026-11-10 with calibrations `30611af` and loader and run script `f0ac36f`. The three arms are
the frozen reader (rank identities), reader v2, and the polyline reader under the product rule. No constant was
changed after the run. Truth sha256 matched (WHITE GULL `de30930e...`, COLLEEN `bbc124ef...`); neither file lists
"unsure" entries. `body_plan_polyline.py` sha256 is `1f39f866...` as pinned. Evidence (git-ignored), in
`work/deadrise_holdouts/`:

- `<boat>_holdout_result.json` (WHITE GULL `33a79bf9...`, COLLEEN `283e85f8...`)
- `<boat>_holdout_overlay.png`
- `<boat>_holdout_stdout.txt`

Truth cells: WHITE GULL 53 waterline, 30 point. COLLEEN 26 waterline (WL -1, 0, +1 ft), 26 point. The WHITE GULL
row "WL 0-0-0" (the base line) is not a measuring row; it is listed as unmatched and not scored.

**WHITE GULL.** v2 verified a chine line on the fore half only. The polyline reader **declined both halves**: it found
2 knuckled stations per half and needs 3, so its table and curves equal the frozen reader's.

| Arm | Waterline cells | RMS m | Max m | Wrong | Point cells | RMS m | Max m | Wrong | Chine only | Identity (WL / pt) | Extra |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Frozen | 45/53 | 0.0263 | 0.1315 | 0 | 8/30 | 0.1338 | 0.2477 | 2 | 5/10, RMS 0.169, 2 wrong | [7] / [6] | W6 of 5, 6, 7 |
| v2 | 43/53 | 0.0179 | 0.1153 | 0 | 7/30 | 0.1394 | 0.2477 | 2 | 4/10, RMS 0.184, 2 wrong | [7] / [6] | W6 of 5, 6, 7 |
| Polyline (both halves declined) | 45/53 | 0.0263 | 0.1315 | 0 | 8/30 | 0.1338 | 0.2477 | 2 | 5/10, RMS 0.169, 2 wrong | [7] / [6] | W6 of 5, 6, 7 |

Point cells by kind (all arms): sheer 3/10 (RMS 0.006 m) and rabbet 0/10. The chine errors are -0.25 m (stations 6
and 7) and -0.13 m (station 2).

Gates:

| Gate | v2 (WL / point) | Polyline (WL / point) |
|---|---|---|
| Cells >= frozen | **fail** (43 < 45) / **fail** (7 < 8) | pass / pass |
| RMS not worse | pass / **fail** (0.139 > 0.134) | pass / pass |
| Wrong not worse | pass / pass | pass / pass |
| Wrong <= 10 % of cells | pass / **fail** (2/7) | pass / **fail** (2/8 = 25 %) |
| No extra on blank truth | **fail** (W6 of stations 5, 6, 7) / pass | **fail** (same, from the frozen table) / pass |
| By eye | v2 fore line on the drawn chine from station 5 to 2. It then runs along the painted waterline (row 3658), where its "station 1" point lies, and outward along the "Chine" label leader: **fail** | no named knuckle (both halves declined). The 4 unnamed knuckles are on drawn corners (fore: stations 5 and 3; aft: at the lower corners of the transom outline and station 10, 1072 and 1094 px out) |

**WHITE GULL: FAIL** (both v2 and polyline). The polyline reader's decline follows its own rule: on each half only 2
stations gave a sharp knuckle. The other traced lines ended as grid lines (11 fore, 5 aft, on the drawn buttocks), with
no bottom branch, or with no sharp knuckle. On this sheet the 1-ft buttock grid crosses every station, and the aft
stations crowd within 100 px of each other near the transom outline.

**COLLEEN.** v2 verified a chine line on the fore half only. The polyline reader **read the fore half** (stations 6,
5, 4, 3, 2; station 1 innermost not read) and **declined the aft half** (2 knuckled curves, 3 needed; the frozen table
is kept there).

| Arm | Waterline cells | RMS m | Max m | Wrong | Point cells | RMS m | Max m | Wrong | Chine only | Identity (WL / pt) | Extra |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Frozen | 15/26 | 0.1642 | 0.4787 | 3 | 3/26 | 0.0259 | 0.0360 | 0 | 0/9 | [] / [] | none |
| v2 | 9/26 | 0.5234 | 1.0617 | 3 | 2/26 | 1.0420 | 1.0819 | 2 | 1/9, 1.082 m, 1 wrong | [5] / [5] | none |
| Polyline (fore read, aft declined) | **21/26** | **0.0006** | **0.0016** | **0** | **10/26** | **0.0047** | **0.0092** | **0** | **5/9, RMS 0.003, 0 wrong** | [] / [] | none |

Polyline point cells by kind: chine 5/9 (stations 2 to 6, RMS 3 mm); rabbet 5/8 (stations 2 to 6, RMS 6 mm); sheer
0/9. The traced side stops below the printed sheer height, as on COLLIER. Missing cells: station 1 (not read); aft
stations 7 to 9 chine, rabbet and sheer (frozen curves on the declined half do not enclose those heights); -1 ft for
stations 7 and 8.

Gates:

| Gate | v2 (WL / point) | Polyline (WL / point) |
|---|---|---|
| Cells >= frozen | **fail** (9 < 15) / **fail** (2 < 3) | pass (21 >= 15) / pass (10 >= 3) |
| RMS not worse | **fail** / **fail** | pass / pass |
| Wrong not worse | pass / **fail** (2 > 0) | pass / pass |
| Wrong <= 10 % of cells | **fail** (3/9) / **fail** (2/2) | pass (0/21) / pass (0/10) |
| No extra on blank truth | pass / pass | pass / pass |
| By eye | v2 fore line on the drawn chine from station 6 to the bow (dashed part) and out along the "Chine" label leader. Its chine points are at station 1's corner and between stations 3 and 4 (misplaced): **fail** | **pass**: the 5 named knuckles (2 to 6) are on the drawn station corners. The aft half's 2 unnamed knuckles are on the aft chine corners |

**COLLEEN: PASS for the polyline reader** (all code gates for both kinds of cell, and the by-eye gate). **FAIL for
v2.** The pass covers the fore half only, with 21/26 waterline and 10/26 point cells. The aft half was declined (the
transom outline and stations 7 to 9 lie within about 70 px, and only 2 sharp knuckles were found). Sheer cells are not
read.

**Summary.** One hard-chine holdout passes for the polyline reader (COLLEEN, fore half) and one fails (WHITE GULL: it
declined both halves, so it is equal to the frozen reader, which fails on the 10 % wrong-cell gate for point cells and
on extra W6 cells). Reader v2 fails both. WHITE GULL and COLLEEN are now spent as holdouts; any change made after
looking at these results makes them development cases.

## V-bottom reader v1.1 (branch `feature/vbottom-v11`, founder approved 2026-11-10)

Development cases only: E. C. COLLIER, WHITE GULL and COLLEEN (holdouts spent), PARDON ME, and the round-bilge set
(BUE GIRL, C.A. Thayer, Balclutha, BUMBLE BEE corrected) for regression. Truth was read to score and diagnose, never
by the reader. The frozen `body_plan_{crossings,reader,identity}.py` are not edited. Calibrations are the committed
ones. `work/holdout/caleb-jones` is an unscored holdout and was not opened.

Measurement: `scripts/measure_vbottom_collier.py` (COLLIER, point scorer, polyline arm), `scripts/measure_deadrise_holdout.py
--boat white-gull|colleen` (waterline and point cells, product rule), `scripts/measure_vbottom_dev_sheets.py`
(five waterline sheets, product rule). Evidence per step in `work/vbottom11/<step>/` (git-ignored). "Base" is
`3afcf46`, reproduced exactly (the published tables above).

### Step 1: engagement per station

Before, a half with fewer than max(3, half its stations) knuckled stations was declined as a whole. Now:

1. **One station per drawn line.** Two traces are one station only when their polylines are one line *and* their
   sides are one line (or one side is a fragment, under half the half's median side). Neighbouring aft stations
   share most of their bottom near the keel; COLLEEN's aft stations 7 and 8 were merged by the old whole-polyline
   test. The trace with the longest side is kept.
2. **A shared knuckle is nobody's.** Different sides that end at one knuckle point (within 1.5 line widths) ran
   into one line (PARDON ME aft: four sides end at one point of the heavy line). None of them is named or engaged.
3. **A bottom belongs to one station.** When two stations claim one bottom line, it is the outer station's (a
   bottom starts at its own knuckle and runs inward, so it can pass an inner knuckle but never an outer one). The
   inner station is traced again without that line, or dropped. COLLEEN aft: station 8 had taken station 7's
   bottom, and "station 9" station 8's.
4. **Engagement per station** (`engage_stations`, `half_table`). On a half that is not read as a whole, a traced
   station with a **clear knuckle** (turn >= 45 degrees, knuckle at least 0.2 of the reach from the centreline)
   takes the name that the existing (frozen rank-identity) reader gave the same curve: that station's cells lie
   within 1.5 line widths of the traced side at 2 or more rows and at 75 % of the shared rows. No match, two
   matches, or two traces for one name: not engaged. The engaged polyline replaces that station's cells; every
   other station keeps the existing cells; an existing cell of another station that lies on an engaged polyline
   (within 1 line width) is dropped, so one drawn line never gives two stations. When other lines through the
   knuckle also reach the centreline, nothing tells which is this station's bottom without its neighbours traced:
   only the side and knuckle are engaged.

Halves read as a whole are unchanged in rule (names by nesting rank, polylines only). The engagement thresholds were
chosen from the knuckle features of every traced station on all eight sheets: round-bilge "knuckles" turn 27 to 42
degrees (Balclutha bilges, seen with short arms) or lie at 0.03 to 0.10 of the reach (keel and stem junctions);
the hard-chine knuckles engaged turn 58 to 76 degrees at 0.6 to 0.9 of the reach.

Results (base -> step 1):

| Sheet | Halves read / engaged stations | Waterline cells | WL RMS m | WL wrong | Point cells | Point RMS m | Point wrong | Chine cells (RMS m) |
|---|---|---|---|---|---|---|---|---|
| COLLIER | both read (unchanged) | - | - | - | 22/31 -> 22/31 | 0.0691 -> 0.0691 | 2 -> 2 | 10 (0.041) -> same |
| WHITE GULL | none -> engaged fore 5, 3; aft 8, 9 | 45/53 -> 45/53 | 0.0263 -> 0.0289 | 0 -> 0 | 8/30 -> 12/30 | 0.1338 -> 0.1065 | 2 -> 2 | 5 (0.169) -> 7 (0.139) |
| COLLEEN | fore read -> fore read, aft engaged 7, 8 | 21/26 -> 22/26 | 0.0006 -> 0.0007 | 0 -> 0 | 10/26 -> 13/26 | 0.0047 -> 0.0063 | 0 -> 0 | 5 (0.003) -> 7 (0.003) |
| PARDON ME | fore read | 43/57 -> 43/57 | 0.035633 -> 0.035486 | 1 -> 1 | - | - | - | - |
| BUE GIRL, Thayer, Balclutha, BUMBLE BEE | none, none engaged | identical | identical | identical | - | - | - | - |

Round-bilge check: on all four sheets no station is engaged and the product table equals the frozen table
(`table_unchanged: true`). PARDON ME's small change is station 3 (fore): the kept trace is now the one with the longer
side. WHITE GULL: stations 8 and 9 were named by the frozen reader; the drawing's leaders ("Sta.8", "Sta.9") confirm
the names (the earlier holdout note that called the 1072 px knuckle the transom outline was wrong: the transom is the
heavy curve further in). Its extra W6 cells (stations 6 to 9) and the 5/W5 error (-0.08 m, side top at the rail) are
the sheer and extra-cell items of steps 2 and 3. COLLEEN station 7 now gives side and knuckle only (one other bottom
line through its knuckle), so its correct -1 ft and rabbet cells of the first trial are not given; COLLEEN station 9
has no own bottom line (it ends on the transom) and is not engaged.

### Step 2: the sheer

**Rule.** The sheer of a station is where its line ends on the drawn sheer line, at that line's **top edge**: the
deck top at the side (COLLIER's table defines sheer as the intersection of the deck top and the hull exterior). The
trace up a side (`trace_side_up`) passes lines that cross the side and stops where the ink ends. Then:

1. If it stopped inside the line it met (a wide run), the end is carried on along the side's direction to the far
   edge of that line's ink, at most 3 line widths (a line met at a grazing angle is not followed).
2. If the top part of the side is drawn with a thinner pen (median ink width under 0.75 of the side's lower half,
   over at least 5 line widths), it is a label leader or a grid line that the trace ran on into: the side ends at
   the junction (`_cut_at_thin_line`). WHITE GULL stations 8 and 9 ran up their "Sta.8"/"Sta.9" leaders.
3. If the top of the side runs on up a calibrated grid column for 5 line widths, the side ends where it joins
   the column (`_cut_at_grid`). WHITE GULL station 5 left the hull for the 6-ft buttock.

The polyline's `sheer` is that top end. A rail drawn on above the deck (COLLIER's log rail) is followed only when the
same line continues; where the rail tick is offset from the hull line (a jog at the rail's lower edge), the side ends
there. Two other rules were tried and dropped: following such jogs to the rail top (it also followed station labels
printed beyond the sheer on COLLEEN) and stopping where the ink beyond a crossing line turns away (the turns at
rail lines, 6 to 13 degrees, overlap those at label leaders, 1 to 6 degrees).

Results (step 1 -> step 2):

| Sheet | Waterline cells | WL RMS m | WL wrong | WL extra | Point cells | Point RMS m | Point wrong | Sheer cells (RMS m) |
|---|---|---|---|---|---|---|---|---|
| COLLIER | - | - | - | - | 22/31 -> 22/31 | 0.0691 -> 0.0691 | 2 -> 2 | 6 (0.007) -> 6 (0.007) |
| WHITE GULL | 45/53 -> 43/53 | 0.0289 -> 0.0269 | 0 -> 0 | W6 of 6, 7, 8, 9 -> W6 of 6, 7 | 12/30 -> 12/30 | 0.1065 -> 0.1065 | 2 -> 2 | 5 (0.005) -> 5 (0.005) |
| COLLEEN | 22/26 -> 22/26 | 0.0007 -> 0.0007 | 0 -> 0 | none | 13/26 -> 17/26 | 0.0063 -> 0.0070 | 0 -> 0 | 0/9 -> 4/9 (0.009) |
| PARDON ME | 43/57 -> 43/57 | 0.035486 -> 0.035486 | 1 -> 1 | - | - | - | - | - |
| Round-bilge set | identical (no station engaged; tables equal the frozen tables) | | | | | | | |

COLLEEN sheer cells: stations 3, 4, 5 and aft 8 (errors +6 to +10 mm and -9 mm). Still missing: station 2 (traced top
7 px, 0.6 in, below the printed height), 6 (the side meets the sheer line at a grazing angle near its end), 7 (17 px
short; the aft sheer line is light there) and 1 and 9 (not traced). WHITE GULL: the W6 cells of 8 and 9 are gone
(their leaders); stations 5 loses W4 and W5 (correct values in step 1 that came from the side's lower part being
on the hull; after the cut the polyline ends below them), and its W5 error (-0.08 m) is gone. The W6 cells of
stations 6 and 7 come from the frozen reader (step 3). COLLIER: unchanged; its missing sheer cells (stations 1, 4, 7,
8, 10) are the offset rail ticks above.

### Step 3: no cells where the hull is not drawn

A polyline gives cells only between its own ends (rabbet to sheer), on its own traced ink, by construction; step 2
put the sheer end on the drawn sheer line. The remaining extra cells came from the existing reader on declined
halves. Rule (`unsupported_cells`, applied on a half with engaged stations): each existing station that is not
engaged is traced up its own line from its middle cell by height (the lowest cell may lie on the bottom, the highest
above the sheer), with the step-2 sheer rules and the thin-line and grid cuts; its cells more than one line width
above that top end are left out of the table and the curves. A station whose middle cell gives no seed on ink, or
whose trace rises less than 15 line widths, is not checked (no evidence either way; the first version of the rule
removed five correct W2 to W6 cells of WHITE GULL station 1, whose trace failed at once). Halves without engaged
stations, so the whole round-bilge set, are not touched.

Results (step 2 -> step 3):

| Sheet | Waterline cells | WL RMS m | WL extra | Point cells | Point RMS m | Point wrong | Point identity errors |
|---|---|---|---|---|---|---|---|
| WHITE GULL | 43/53 -> 43/53 | 0.0269 -> 0.0269 | W6 of 6, 7 -> **none** | 12/30 -> 10/30 | 0.1065 -> 0.1166 | 2 -> 2 | [6] -> [] |
| COLLEEN | 22/26 (same) | 0.0007 (same) | none | 17/26 (same) | 0.0070 (same) | 0 | [] |
| COLLIER | - | - | - | 22/31 (same) | 0.0691 (same) | 2 | [5] |
| PARDON ME | 43/57 (same) | 0.035486 (same) | - | - | - | - | - |
| Round-bilge set | identical (no station engaged) | | | | | | |

WHITE GULL: the frozen W6 cells of stations 6 and 7 (above their drawn sheer) are left out. Two point cells go with
them: the frozen sheer cells of 6 and 7 were interpolated between W5 and the W6 sample above the sheer, and without
it the printed sheer height is no longer enclosed. Both were within 1 cm; they are lost, not wrong.

### Step 4: reader v2 chine-line guard

`body_plan_reader_v2.chine_columns`: the traced chine stroke is the chine only where it does not run **along a drawn
waterline** (a straight horizontal ink run at least half the reach long, a measuring row or not, such as WHITE GULL's
painted waterline, followed over at least 0.1 of the reach; a chine only crosses such a line over a short stretch)
and does not run **out beyond the hull** (more than 2 curve widths outside the outermost measured station crossing:
a label leader). The longest remaining stretch is the chine; it must still span 0.25 of the reach, or the half has no
verified line. A station whose pieces meet the stroke outside that stretch keeps its upper cells but gets **no chine
point**, so no lower piece is named by it. The existing whole-line waterline test runs first, unchanged, so a line
rejected before is still rejected.

Results, reader v2 arm (base -> step 4):

| Sheet | Chine points (fore) | Waterline cells | WL RMS m | Point cells | Point RMS m | Chine cells (RMS m) |
|---|---|---|---|---|---|---|
| WHITE GULL | 5, 4, 3, 2, 1 -> 5, 4, 3, 2 | 43/53 -> 42/53 | 0.0179 -> 0.0181 | 7/30 -> 6/30 | 0.139 -> 0.150 | 4 (0.184) -> 3 (0.212) |
| COLLEEN | 6, 5 -> same | 9/26 -> 9/26 | 0.523 (same) | 2/26 (same) | 1.042 (same) | 1 (1.082) (same) |
| Five waterline dev sheets | | identical to the published v2 table (PARDON ME 45/57, RMS 0.005556; round-bilge set unchanged, no line verified) | | | | |

WHITE GULL: the line now stops at station 2; the false "station 1" chine point on the painted waterline is gone.
The two cells it gave are lost with it: 1/W2 (a lower piece named by that point) and the station 1 chine point cell
(-0.036 m). Both were within the band, but they came from a point that was not on the chine, so leaving them out is
the guard working, not a loss of evidence. COLLEEN's v2 failure is not this guard's case: its line has only 2 upper
pieces for 6 stations and its chine points are misplaced on the drawn chine itself (the base result notes); the
guard does not change it. v2 still fails both sheets' gates; the polyline product rule is the reader to use on them.

### v1.1 summary (base `3afcf46` -> `d026adb`; polyline product rule, development cases)

| Sheet | WL cells | WL RMS m | WL extra | Point cells | Point RMS m | Point wrong | Chine / sheer / rabbet cells | Code gates vs frozen |
|---|---|---|---|---|---|---|---|---|
| COLLIER | - | - | - | 22/31 -> 22/31 | 0.0691 (same) | 2 (same) | 10 / 6 / 6 (same) | pass (same) |
| WHITE GULL | 45/53 -> 43/53 | 0.0263 -> 0.0269 | W6 of 5, 6, 7 -> none | 8/30 -> 10/30 | 0.1338 -> 0.1166 | 2 -> 2 | 5/3/0 -> 7/3/0 | WL: fail (cells 43 < 45, RMS +0.0006); point: fail (2/10 wrong) |
| COLLEEN | 21/26 -> 22/26 | 0.0006 -> 0.0007 | none | 10/26 -> 17/26 | 0.0047 -> 0.0070 | 0 -> 0 | 5/0/5 -> 7/4/6 | pass (both kinds) |
| PARDON ME | 43/57 -> 43/57 | 0.035633 -> 0.035486 | - | - | - | - | - | - |
| BUE GIRL, Thayer, Balclutha, BUMBLE BEE | identical tables (no station engaged) | | | | | | | |

WHITE GULL still fails its gates: its two wrong point cells are the frozen chine cells of stations 6 and 7 (-0.25 m;
the frozen curves interpolate across the knuckle), which are not engaged (no clear knuckle traced on their sides);
it loses two correct W4/W5 cells of station 5 (cut where its trace left the hull for a buttock line).

Open items: COLLIER sheer cells behind offset rail ticks (1, 4, 7, 8, 10); sheer cells that miss by a few pixels
(COLLEEN 2, 6, 7) because a polyline is not extrapolated; engaged stations whose bottom is ambiguous give side and
knuckle only (COLLEEN 7, WHITE GULL 3, 8, 9: no rabbet cells); the bottom branch choice still prefers the branch that
reaches nearest the centreline, and an outer station can take an inner station's bottom where the inner one runs
above the keel (synthetic case; resolved on COLLEEN by the ownership rule only when both stations are traced); the
thresholds of steps 1 to 3 were set on these development sheets; product integration (`body_plan_intake.py`) is not
done; no holdout scored with v1.1.

### Holdout protocol: CALEB JONES (written before any run; folder not opened)

`work/holdout/caleb-jones/` is an **UNSCORED HOLDOUT** (skipjack CALEB JONES, HAER MD-171 sheet 1). Nothing in it was
opened while writing v1.1 or this protocol: no sheet, preview, crop or truth file. Its table prints **point offsets**
(height above base and half-breadth of SHEER, CHINE and RABBET per station), as COLLIER's.

**Reader under test (pinned).** The run is valid only with these files at these SHA-256 values (`shasum -a 256`);
any edit before the run is recorded here and the protocol is committed again before the run:

| File | SHA-256 |
|---|---|
| `src/vessel_reconstruction/body_plan_polyline.py` | `14ab4e82386c1bd11c3626ccf58b7b8ba3ab7dee222ddb7d69c6067fc299494b` |
| `src/vessel_reconstruction/body_plan_reader_v2.py` | `61c6e834ed4df675b96cafd50fc4e77d811f85ef205354697cadb8eaa5a8174f` |
| `src/vessel_reconstruction/body_plan_chine_line.py` | `ef2bd68f4f9e1f65d185dbc8de1896c6383134b6df9c8558200bfd83bf239223` |
| `src/vessel_reconstruction/body_plan_crossings.py` | `c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97` |
| `src/vessel_reconstruction/body_plan_reader.py` | `327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11` |
| `src/vessel_reconstruction/body_plan_identity.py` | `ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34` |
| `benchmarks/deadrise_holdout/score.py` | `30140ebb89feda86ab8e607aaf0ef34161d9f3329dcc806813624a7483c6d820` |
| `benchmarks/ec_collier/point_score.py` | `b38bbda707c921f3d930cebf7ad37cb73e025a29af5e9dabac36a17755df2158` |
| `benchmarks/balclutha/crossing_value.py` | `bafb3ac55a69046cbf3fafcdd02f63889a34a69b064917b8798315ad4c9a4ddf` |
| `benchmarks/balclutha/model_value.py` | `aa3786c262434e8451f7659e2885c2fecbd6b3a285c922113c93409d638a71e0` |
| `scripts/measure_deadrise_holdout.py` | `986efc563925f5b0d1351252ef735d59943185d05d478a30883b7cb9f148f660` |

**Order of work (each step committed before the next):**

1. **Calibration** in `benchmarks/caleb_jones/holdout_value.py`, by an agent that does not open the truth file, the
   table crops or any reader output, with the same interface as `benchmarks/colleen/holdout_value.py`
   (`SHEET_SHA256`, `TRUTH_SHA256 = None` until step 2, `PIXELS_PER_FT`, `CENTRE_COLUMN`, `BASE_ROW` and slope,
   `height_ft`, `WATERLINE_ROWS` / `WATERLINE_HEIGHTS_FT` / `WATERLINES`, `STATIONS`, sides and grid columns,
   `MAX_OFFSET_PX`, `OVERLAY_REGION`, `sheet_layout()`). Scale from the printed scale bar, checked against one drawn
   dimension; centre column and base line from the drawn lines; measuring rows a fixed 6-inch grid from the scale (no
   waterlines are expected; as COLLIER and COLLEEN); maximum offset clear of labels where possible, with the labels
   inside it listed. **Sides read twice** (body-plan labels; stem and transom in the profile), both readings recorded.
   If the sheet shows the table, the calibrating agent records that it saw it and that no constant came from it.
   An overlay of the calibration is checked by eye. `scripts/measure_deadrise_holdout.py` already lists the boat
   `caleb-jones`; no other code changes.
2. **Blind truth.** A person or a model that sees no reader output reads the printed SHEER, CHINE and RABBET rows
   (heights and half-breadths, feet-inches-eighths) into `work/holdout/caleb-jones/truth.json` in the PM format of
   the WHITE GULL and COLLEEN truth files (`units`, `stations`, `heights`, `half_breadths`, `notes`, `unsure`). Blank
   or illegible cells are null. Its SHA-256 is written into `TRUTH_SHA256` and committed.
3. **One run**, with no tuning: `scripts/measure_deadrise_holdout.py --boat caleb-jones --sheet ... --truth ... --out
   work/deadrise_holdouts/caleb-jones_holdout_result.json --overlay work/deadrise_holdouts/caleb-jones_holdout_overlay.png`.
   The script checks the sheet and truth SHA-256 values; all three readers run before the truth file is read. The
   JSON, overlay and stdout are kept in `work/` and their SHA-256 values recorded. The run is not repeated; a crash
   after the JSON is written is fixed in display code only, as on COLLIER.

**Cells and metrics** (as the WHITE GULL and COLLEEN protocol, point cells): truth cells are the printed (station,
SHEER / CHINE / RABBET) pairs with both height and half-breadth printed. Reader value: the station's curve at the
printed height (polyline: its traced points; frozen and v2: its crossings on consecutive measuring rows), no
extrapolation. Arms: frozen reader (rank identities), reader v2, and the polyline product rule (halves read as a
whole give their polylines; on declined halves the frozen curves with stations engaged one by one, without frozen
samples on engaged ink or above their station's traced side). Report per arm: cells given / truth cells, RMS,
maximum, wrong cells (> 0.15 m), identity errors (2 shared points), sheer-only, chine-only and rabbet-only lines,
missing and extra cells, halves read / declined / engaged stations with the reader's notes; for v2 whether a chine
line was verified per half. Printed waterline cells, if any, are scored as well, as on WHITE GULL.

**Gates (polyline product rule against the frozen reader; pass only if all hold):** cells >= frozen; RMS not worse;
wrong cells not worse; wrong cells <= 10 % of cells given; no extra cell where the printed half-breadth is blank; by
eye on the overlay, every named or engaged knuckle lies on a drawn station corner (recorded). A failure is reported
as a failure. After the run CALEB JONES is a development case.

Verification (2026-11-10, `b9b2289` plus a test fix): `PYTHONPATH=src:. .venv/bin/python -m pytest -q`: 1758 passed,
1 skipped, 6 failed in 1135 s. Five are the known macOS `sandbox-exec` worker failures inside this agent's sandbox
(`test_ship_cad.py` x3, `test_part_revise.py`, `test_whole_vessel_step1.py`; exit 71; they import nothing from these
files). The sixth was `test_existing_cells_above_their_own_traced_side_are_unsupported`, whose synthetic station line
was too short for the guard added late in step 3; its geometry was corrected (test only, no module change) and
`tests/test_body_plan_polyline.py` passes (20). The pinned hashes above are unchanged. Frozen reader hashes unchanged.

### CALEB JONES: calibration and scorer (written before any reader run on the sheet)

Branch `feature/caleb-holdout`. Calibration `benchmarks/caleb_jones/holdout_value.py` (interface of COLLEEN's). The
11 pinned files were checked first: all SHA-256 values match the table above. Sheet SHA-256 `c05fb65a...85b8` matches
SOURCE.md. **No reader has run on the sheet. No truth file, table crop, preview or reader output was opened.**

**Disclosure.** To find the body plan the calibrating agent viewed the upper-left quarter of the sheet (rows 0 to 4800,
columns 0 to 7200) at 1/8 scale. The left edge of the table of offsets was in that view: its row names (SHEER, CHINE,
RABBET, and SHEER / CHINE AT STEM under "height above baseline" and "half-breadths from centreline") and the values of
the two "AT STEM" rows were legible, with the first words of a note ("Stations offset 4'-0""). No value was used; the
stem rows are not stations and the loader ignores them. Every later view of the sheet masked rows 1900 to 4300 from
column 5650 (the table), or showed only the body plan, profile, half-breadth plan or scale bar.

| Constant | Value and source |
|---|---|
| Pixels per foot | 200.0: feet bar "0" / "5" ticks at 11299 / 12299. Body-plan beam "16'-9 15/16"" 3367 px (200.05); station spacing "4'-0"" 800 px in profile and plan (200.0). The centimetre bar is drawn 0.9 % short (650 px/m) and is not used |
| Centre column | 3436.5 (dash-dot ink 3435 to 3438 above the stem head and below the keel) |
| Base row | 2989.0, slope 0 (drawn "Baseline", one pixel, columns 1583 to 5290). The chines lie just below it; bottoms meet the keel near -1.73 ft, keel bottom about -2.28 ft |
| Measuring rows | no waterlines drawn; 6-inch grid from -2.0 to +4.5 ft (14 rows, 100 px), labels signed ft-in-eighths. -2.0 ft crosses only the keel sides; 4.5 ft is above the highest station top (station 1, about 4.2 ft); the 0.0 ft row is on the drawn base line |
| Sides | fore RIGHT outer first (7, 6, 5, 4, 3, 2, 1); aft LEFT outer first (107, 8, 9, 10), where 107 is a placeholder for the left copy of station 7 (below) |
| Grid columns | none drawn |
| Max offset | 1705 px (hull 1683 left / 1684 right at station 7's top; labels "7" from 1792 px and "Baseline" from 1776 px stay outside) |

Sides, read twice (lesson: check the side assignment twice):

1. Body-plan labels: "1" (innermost, at the stem) to "7" (outermost) along the right sheer; "8", "9", "10" on the left
   from the outside inward.
2. Profile and half-breadth plan: the profile is labelled "10" (transom, left) to "1" (stem, right), and the stem
   rakes forward at the right. Plan half-breadths at the outer line, stations 7, 8, 9, 10: 1683 / 1649 / 1567 / 1455
   px against the left body-plan curve tops 1681 / 1646 / 1561 / 1451 px; at the heavy sheer line, stations 1, 2, 3,
   6, 7: 433 / 855 / 1175.5 / 1635 / 1666 px against the right curves 435 / 855 / 1176 / 1636 / 1660 px. Right =
   forebody, left = aftbody. Both readings agree.

**Station 7 is drawn on both halves.** The left half's outermost curve has no label and is the mirror of the right
station 7 (left / right offsets 1683 / 1684 px at row 2495, 1656 / 1657 at 2600, 1604 / 1604 at 2800, 1526 / 1527 at
3100) and of the plan's station 7; the beam dimension spans the two. The label "7" is on the right, so the right curve
is station 7. The left copy is listed as placeholder station 107 so that rank naming does not call it "8". It is not a
truth station: the loader requires the truth stations 1 to 10, and the scorer scores only printed cells, so 107 is
never scored and gives no extra cell (checked with a synthetic truth and synthetic curves; no reader ran). Without the
placeholder every left curve would be named one station too far out.

Known limits recorded before the run (not fixed; the protocol forbids tuning):

- **Transom outline.** The left half has a heavy, unlabelled outline inside station 10: a top edge near row 2355
  running in to the centreline, a side down to about row 2550 (1290 px out), a heavy diagonal inward to about row
  2925 (45 px out) and a vertical beside the keel; a thin line also runs from about row 2955 (1290 px out) to the
  keel. It crosses the 0.5 to 3.0 ft rows. A reader that counts it as a station may misname or decline the half.
- **Station 10's corner is rounded** (a curve from about -0.5 ft into the bottom), not a sharp knuckle. The left
  half has 4 listed curves, of which 3 have sharp chines.
- **Two lines at the top.** Every station runs up past the heavy "Sheer" line to a thin top line (the covering board
  top, about 0.1 to 0.2 ft higher). Which of the two the table calls the sheer is not known to this calibration.
- **Labels inside the reach** (all above the hull at their columns except "Sheer"): left "8" and right "6" (3.0 ft
  row), left "9" and "10" and right "4" (3.5 ft row), right "2" (glyph foot on the 4.0 ft row), and the word "Sheer"
  inside the forebody between the sheer line and stations 1 and 2 (534 to 752 px out, 3.5 ft row).

Scorer (step 2): `benchmarks/deadrise_holdout/score.py` and `scripts/measure_deadrise_holdout.py`, pinned and
unchanged. Point cells: printed (station, SHEER / CHINE / RABBET) height and half-breadth pairs, COLLIER point-scorer
rules, no extrapolation, identity check with 2 shared points, sheer-, chine- and rabbet-only lines. Printed heights may
be negative (leading "-" makes the whole value negative; "+" adds 1/16 in); the loader accepts heights from -1.5 to 4
m. Rows named "... AT STEM" are not point rows and are ignored. Printed waterline cells, if any, are scored as on
WHITE GULL. `TRUTH_SHA256 = None`: the loader stops until the PM gives the truth file's SHA-256.

Calibration overlay (git-ignored): `work/deadrise_holdouts/caleb-jones_calibration_overlay.png` (SHA-256
`19c15f706651049a...`), drawn by `scripts/deadrise_calibration_overlay.py` through a wrapper that adds the boat to its
list (the script file is not changed). Checked by eye: the centre line is on the dash-dot centreline, the base line on
the drawn "Baseline", the reach lines just outside station 7 on both halves, and the grid from below the bottoms to
above station 1's top.

### CALEB JONES pre-run amendment (PM approved 2026-11-10, before any reader run)

PM approved the calibration as committed in `70789b1`, including placeholder station 107. The sheer ambiguity (heavy
"Sheer" line or thin covering-board line) is not resolved from the table; the run records which line each reader took.
Truth: `work/holdout/caleb-jones/truth.json`, SHA-256 `1830c5213591604f52f5cb36c1924acee338ad3a1b52d706fff86c4b8dbae9e5`
(checked; the file was not opened by this agent), now `TRUTH_SHA256` in the calibration. The PM states that its
stations are printed "0.000" to "10.000" and that station 0.000 is all null.

**Amendment: truth station names only.** The pinned loader took only plain digit names ("7") as stations, so it
refused this file before scoring. `benchmarks/deadrise_holdout/score.py` now reads a whole-number name ("7" or
"7.000") as that station and ignores any column whose number is not in the calibration's `STATIONS` (as TRANSOM was
ignored); the stations kept must still be the calibration's, in order. Nothing else in the scorer changed. New pinned
SHA-256: `1bc962218d25b86c6006a23c2e5567e241ad169cd430f2bdcb73a92793f58be1` (was `30140ebb...c820`). The other ten pinned files are unchanged.
Checks: `tests/test_deadrise_holdouts.py` 17 passed (new synthetic test; the old refusal of a "0" column is replaced by
refusals of a missing and an out-of-order station). The WHITE GULL and COLLEEN truth files parse to identical cells with
the old and new loader (pure parse check, no reader run), so their published scores are unchanged.

### HOLDOUT RESULT: CALEB JONES (one run, no tuning) - FAIL

One run on 2026-11-10 with the calibration `70789b1` and the amended scorer `1a16e01` (truth SHA-256 matched;
`body_plan_polyline.py` `14ab4e82...` as pinned; no "unsure" entries). Nothing was changed after the run. Evidence
(git-ignored) in `work/deadrise_holdouts/`: `caleb-jones_holdout_result.json` (`c10d2bd000a32686...`),
`caleb-jones_holdout_overlay.png` (`aaacb43ff5aef7d4...`), `caleb-jones_holdout_stdout.txt` (`e8e579b8df5dd291...`).
Truth cells: 30 point cells (SHEER, CHINE, RABBET for stations 1 to 10), no waterline cells.

Readers: the polyline reader **read both halves as a whole** (no stations engaged). Fore: 4 knuckled stations for 7,
named 7, 6, 5, 4; innermost 3, 2, 1 not read. Aft: 4 knuckled lines named 107, 8, 9, 10. v2 verified a chine line on
the fore half only ("1 upper pieces for 7 stations"), with one chine point (station 7).

| Arm | Point cells | RMS m | Max m | Wrong | Sheer only | Chine only | Rabbet only | Identity errors | Extra |
|---|---|---|---|---|---|---|---|---|---|
| Frozen | 5/30 | 0.589 | 1.244 | 4 | 3/10, RMS 0.223, 2 wrong | 2/10, RMS 0.890, 2 wrong | 0/10 | [] | none |
| v2 | 1/30 | 0.193 | 0.193 | 1 | 0/10 | 1/10, RMS 0.193, 1 wrong | 0/10 | [] | none |
| Polyline (both halves read) | 16/30 | 0.660 | 1.753 | 10 | 7/10, RMS 0.451, 5 wrong | 6/10, RMS 0.960, 5 wrong | 3/10, RMS 0.082, 0 wrong | [4, 5, 6, 7, 8, 9] | none |

Polyline errors (m): station 7 chine +0.001, sheer +0.006, rabbet +0.124; station 4 chine -1.175, sheer -0.898; 5
chine -0.858, sheer -0.600; 6 chine -0.463, sheer -0.373, rabbet +0.068; 8 chine -0.354, sheer -0.133; 9 chine
-1.753, sheer -0.182; 10 sheer -0.259; 4 rabbet -0.007.

Gates (point cells; there are no waterline truth cells, so the waterline gates do not apply):

| Gate | v2 | Polyline |
|---|---|---|
| Cells >= frozen | **fail** (1 < 5) | pass (16 >= 5) |
| RMS not worse | pass (0.193 <= 0.589) | **fail** (0.660 > 0.589) |
| Wrong not worse | pass (1 <= 4) | **fail** (10 > 4) |
| Wrong <= 10 % of cells | **fail** (1/1) | **fail** (10/16) |
| No extra on blank truth | pass | pass |
| By eye | v2's verified "chine" line runs along the heavy sheer line, not the chine, and its one chine point (row 2381, 1020 px out) is on the sheer line: **fail** | **fail**: see below |

By eye (overlay): the fore knuckle named 7 is on station 7's corner. The knuckles named 6, 5 and 4 lie on drawn
corners, but of stations 4, 3 and 2: the outer stations 6 and 5 (plan chine half-breadths 1501 and 1414 px against 1512 px for station 7 at the
chine) were not traced, and rank naming shifted the inner names by two. Aft: 107 is on the left copy of station 7;
the knuckles named 8 and 9 are on stations 9 and 10 (station 8, next to the copy of 7, was not traced); the knuckle
named 10 is on the corner of the **transom outline**, not a station. These name shifts are the identity errors and
the large chine and sheer errors.

Sheer line taken (PM question): the polyline sheer of every traced station ends on the **thin top line** (covering
board top), not on the heavy "Sheer" line (overlay marks; station 7 sheer at row 2494, its top). Frozen and v2 sample
the station crossings on the measuring rows only, so they take no sheer line; their sheer cells are interpolated
between grid rows. Station 7, the only correctly named polyline station, scored sheer +0.006 m at the printed
height, so this run does not separate the two lines.

**CALEB JONES: FAIL** for both v2 and the polyline reader. The polyline failure is a naming failure, not a tracing
failure on the stations it named correctly: on a half read as a whole, names are given by nesting rank, so a missed
outer station (crowded stations 5 and 6 beside 7; station 8 beside the copy of 7) and a counted transom outline shift
every inner name. CALEB JONES is now a development case.

### Label-based station naming (development, 2026-11-10): not adopted

Two attempts to name V-bottom stations from printed station labels (OCR near each traced line) instead of nesting rank
were run on the four development sheets (COLLIER, WHITE GULL, COLLEEN, CALEB JONES). Neither was merged.

| Attempt | COLLIER cells | CALEB cells | CALEB identity errors | Outcome |
|---|---|---|---|---|
| v1.1 (rank naming, current) | 22/31 | 16/30 | [4, 5, 6, 7, 8, 9] | kept |
| Labels name stations; abstain otherwise | 0/31 | 3/30 | [] | rejected: removes errors only by abstaining |
| Labels as anchors that correct rank naming (two or more monotonic anchors required) | 22/31 | 16/30 | [4, 5, 6, 7, 8, 9] | rejected: no two usable labels were read on either CALEB half, so it fell back to rank naming |

WHITE GULL and COLLEEN were unchanged in both attempts. The limit is the OCR read of the small hand-lettered station
numbers, not the anchor logic. Looser anchor rules were not tried, to avoid tuning to the development sheets. Next
candidates: station identity from the plan or profile view (station spacing along the baseline), or a vision-model
label read offered as a suggestion for the user to confirm. Code: unmerged branch `fix/vbottom-label-names`
(commits `60ceecb`, `c2694c5`), kept in a local clone only.

### Frozen reader v1: real-sheet equivalence (2026-11-11)

After the move to `benchmarks/frozen_readers/v1/` (code-review item 7), the frozen copy was checked on the real
E. C. COLLIER sheet (HAER MD-77 sheet 2, protocol SHA-256 checked): `load_ink` gives an identical 9632 x 14460 ink
array, and `measure_side` gives identical readings on both halves (frozen vs product module). The COLLIER holdout
script, now importing the frozen copy, reproduces the published result exactly: 7 of 31 point cells, RMS 0.912 m,
3 wrong cells, for both arms. The three frozen files are byte-identical to the pinned product files.

### Reader thresholds scaled by stroke width (code-review item 8, partial, 2026-11-11)

Five fixed pixel distances in the crossings reader now scale with `factor = measured stroke width / 5 px`
(the 1700 x 2300 synthetic reference): tracing band, minimum diagonal length, centreline exclusion,
link tolerance and the search margin. Gap and minimum-run thresholds are not scaled yet.

- Gunnerus lines plan (development sheet): factor 1.00, so readings are unchanged.
- E. C. COLLIER (holdout, scored once, no tuning after): factor 2.00. The score is unchanged:
  7 of 31 point cells, RMS 0.912 m, 3 wrong cells, the same as the frozen v1 reader.

The change is a robustness fix for scans at other resolutions. It does not improve the COLLIER score.

### Holdout protocol: CAMA BEACH SKIFF No. 22 (written before any run; lane E, 2026-11-11)

`work/holdout/cama_beach_skiff_22/` is an **UNSCORED HOLDOUT**: a 14 ft flat-bottom, hard-chine
rowing skiff (built 1934), HAER WA-199 sheet 1 of 2, "Lines Plans with Table of Offsets", drawn by
Todd A. Croteau, 2011. Source: https://www.loc.gov/resource/hhh.wa0881.sheet/ (US Government work;
LoC: no known restrictions). Downloaded by the PM through a normal browser. No reader has run on it.

| File (not in git) | SHA-256 |
|---|---|
| `work/holdout/cama_beach_skiff_22/master-pnp-habshaer-wa-wa0800-wa0881-sheet-00001a.tif` (14400 x 9600) | `db390a25fcd033c1912d4cbce248cb91cbe4b2e736203ecfcc3e34f395cc6e42` |
| `work/holdout/cama_beach_skiff_22/truth.json` | `473ef776bd3d0d022e4c5e7ee47dc223853cf5a2ae6e08c984ca0ba9f8651b1e` |

**Truth (frozen).** The printed table, in the `parse_truth` format (`units` ft-in-eighths, values as
printed). Stations printed "0.000" to "10.000"; rows: heights SHEER and CHINE; half-breadths
WL 0-9-0, WL 0-6-0, WL 0-3-0, WL 0-0-0, SHEER, CHINE (no RABBET row). CHINE heights are printed
negative (the flat bottom is below the baseline). Column 10.000 has only its x-position (all
cells blank); column 0.000 has no CHINE and no WL 0-0-0 cell. The stem and transom cells (SHEER /
CHINE AT STEM / AT TRANSOM) are not per-station and are kept in `notes` only, not scored. Two
transcriptions: reading A (lane E) and reading B (a separate agent with its own crops, blind to
A); they agree on all 77 filled cells, so `unsure` is empty. Parse check with the pinned loader and
stations 1 to 9: 36 waterline cells and 18 point cells (9 sheer, 9 chine).

**Sides (read twice, agree).**
- Reading 1 (lane E, labels and profile): body-plan left half labelled 8 (outermost), 9, 10; right
  half 7 (outermost) to 1, with an unlabelled near-vertical line just right of the centreline
  (probably the stem / station 0). Profile: raked stem at the right end with station 1 next to it,
  transom at the left end with station 10 next to it. So right half = forebody (1 to 7), left half
  = aftbody (8 to 10).
- Reading 2 (separate agent, own crops, table not read): right half labelled 1 to 7 (outermost 7;
  curves 6 and 7 almost coincide and cross near the chine), left half 8, 9, 10 (outermost 8) plus
  an unlabelled heavy line (about column 2850) and a thin line (about column 2895) that look like
  the transom outline; no station labelled on both halves. Stem at the right of the profile (about
  column 11080), transom at the left (about column 3000); right-half sections narrow and V-like,
  left-half sections wide with flat bottoms below the baseline. Right = forebody, left = aftbody.
  Approximate centreline column 3885, baseline row 3234 (for the calibrating agent to measure).
- Note for calibration: station 10 is labelled in the body plan but has no printed offsets, so it
  can give no truth cell; the unlabelled transom outline and the near-centreline line must not be
  named as stations.

**Reader under test (pinned at `4f03667`).** The run is valid only with these files at these
SHA-256 values; an edit before the run is recorded here and the protocol committed again:

| File | SHA-256 |
|---|---|
| `src/vessel_reconstruction/body_plan_polyline.py` | `14ab4e82386c1bd11c3626ccf58b7b8ba3ab7dee222ddb7d69c6067fc299494b` |
| `src/vessel_reconstruction/body_plan_reader_v2.py` | `61c6e834ed4df675b96cafd50fc4e77d811f85ef205354697cadb8eaa5a8174f` |
| `src/vessel_reconstruction/body_plan_chine_line.py` | `ef2bd68f4f9e1f65d185dbc8de1896c6383134b6df9c8558200bfd83bf239223` |
| `src/vessel_reconstruction/body_plan_crossings.py` | `8c0ffde62d5913cfbbba33fff8eecb7e08862439c9edc4063ec691e285c5987c` |
| `src/vessel_reconstruction/body_plan_reader.py` | `327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11` |
| `src/vessel_reconstruction/body_plan_identity.py` | `ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34` |
| `benchmarks/frozen_readers/v1/body_plan_reader.py` | `327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11` |
| `benchmarks/frozen_readers/v1/body_plan_crossings.py` | `c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97` |
| `benchmarks/frozen_readers/v1/body_plan_identity.py` | `ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34` |
| `benchmarks/deadrise_holdout/score.py` | `1bc962218d25b86c6006a23c2e5567e241ad169cd430f2bdcb73a92793f58be1` |
| `benchmarks/ec_collier/point_score.py` | `b38bbda707c921f3d930cebf7ad37cb73e025a29af5e9dabac36a17755df2158` |
| `benchmarks/balclutha/crossing_value.py` | `f5ab03b178508c1cf9232417c38d2888cc1fb94b07d519e830c9fb5c9df82536` |
| `benchmarks/balclutha/model_value.py` | `aa3786c262434e8451f7659e2885c2fecbd6b3a285c922113c93409d638a71e0` |
| `scripts/measure_deadrise_holdout.py` | `40e4bd8c1ad32e3278d2f5b194056def13a688e0c77afb6cf9e4e0fa727e174e` |

**Order of work (each step committed before the next).**
1. **Calibration** in `benchmarks/cama_beach_skiff_22/holdout_value.py` by an agent that has not
   seen `truth.json`, the table crops or this lane's transcription (lane E read the table, so it
   must not calibrate). Same interface as `benchmarks/caleb_jones/holdout_value.py`, with
   `TRUTH_SHA256` set to the value above. Scale from the printed bar ("SCALE: 1 1/2" = 1'-0"")
   checked against a drawn dimension (the profile station spacing 1'-4" or the length 13'-7");
   measuring rows on the printed waterlines (W0 baseline, W1, W2, W3 = 0, 3, 6, 9 in) plus a fixed
   grid below the baseline for the chines; sides as above. Adding the boat to `BOATS` in
   `scripts/measure_deadrise_holdout.py` is the only code change; it changes that file's pinned
   hash, which is then recorded here before the run.
2. **One run**, no tuning, as on CALEB JONES; JSON, overlay and stdout kept in `work/` with their
   SHA-256 values.

**Cells, metrics and gates** are those of "Holdout protocol: CALEB JONES" with both kinds of cell:
waterline cells (36) and point cells (sheer and chine; 18). Gates (polyline product rule against
the frozen reader; pass only if all hold): cells >= frozen; RMS not worse; wrong cells (> 0.15 m)
not worse; wrong cells <= 10 % of cells given; no extra cell where the printed cell is blank; by
eye on the overlay, every named or engaged knuckle lies on a drawn station corner. A failure is
reported as a failure; after the run the sheet is a development case.

**Dropped: 14'-3" Double Ended Davis Boat (HAER WA-227).** Sheet `work/holdout/davis_boat/`
(SHA-256 `728ea5130529fbd9945fd4045a42bc274085ad89d8cf5a9dea1415d2271b7465`) shows a double-ended
round-bilge hull: smooth body-plan sections, diagonals and buttocks, and no chine row in its table.
It is not a hard-chine holdout; no truth was made from it. Its table was looked at in the sheet
overview only, so it is not a clean blind holdout for a round-bilge test either.
