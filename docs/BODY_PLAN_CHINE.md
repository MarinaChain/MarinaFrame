# Hard-chine station joining

## Metrics and acceptance

PARDON ME is a **DEVELOPMENT case**. Its round-14 holdout is spent. Its truth may now guide diagnosis, but the joining code must not read truth, vessel names, or benchmark calibration constants.

Compare the frozen code-only reader with the frozen reader plus chine joining. Use each sheet's existing harness calibration without retuning. BUMBLE BEE uses the documented corrected sides. Report:

- Cells given / truth cells: only cells present in both prediction and truth.
- RMS and maximum absolute error, in metres, on those common cells. Missing cells are not zero-error cells.
- Identity errors: the existing harness's station-level nearest-truth-curve check, not a new threshold.
- Extra cells and missing cells in the machine-readable result.

PARDON ME has 57 truth cells. Published round-14 code baseline: 34/57 cells, RMS 0.1346956535 m, maximum 0.6371791158 m, identity errors [6, 10, 11]. Reproduce it before implementation. Joined results are pending, not zero. For BUE GIRL, C.A. Thayer, Balclutha, and BUMBLE BEE (corrected sides), RMS must not increase; also report coverage so abstention cannot conceal a regression. Report missing inputs explicitly.

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

Current resume point: step 1, baseline measurements pending. No joining implementation exists yet.
