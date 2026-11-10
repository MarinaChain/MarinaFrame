# Hard-chine station joining

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
