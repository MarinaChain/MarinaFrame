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
