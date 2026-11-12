# GA refactor checkpoint — 2026-11-12

## Status and stop point

Partial work only. Shared label vocabulary now lives in `ga_vocabulary.py`; both passes import it and preserve old import names. Vocabulary, reasons, prompts and constants are unchanged. Two synthetic tests check shared-object exports. The offline proof runner captures and compares all required output types without model entry points.

Stopped before scale/commercial function moves because both baseline and changed `make test-quick` fail at `app/core/tests/replace_sheet.rs:144`. The assertion expects no action error; actual error is `sheet_replacement_failed`. Baseline run: 3 passed, 1 failed in that test binary; changed run: the same. This lane does not alter the Rust worker or relax the test.

## Proof

All baseline captures were made at `c30e5cf` before source edits. The unified baseline was also compared with the independent initial captures: all 56 files identical.

From the worktree, use the main venv Python and `PYTHONPATH=src`:

```sh
P=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
W=/Users/jonathanjie/Documents/workspace/MarinaFrame/work/ga-internal-23
PYTHONPATH=src $P scripts/ga_replay_scale.py --run "$W/dev-runs/u10" --inputs "$W/inputs" --out work/ga-refactor/before-scale
PYTHONPATH=src $P scripts/ga_refactor_proof.py --run "$W/dev-runs/u10" --inputs "$W/inputs" --out work/ga-refactor/before
PYTHONPATH=src $P scripts/ga_refactor_proof.py --run "$W/dev-runs/u10" --inputs "$W/inputs" --out work/ga-refactor/vocabulary --before work/ga-refactor/before --latest "$W/dev-runs/u10r6"
PYTHONPATH=src $P scripts/ga_arrangement_gate.py work/ga-refactor/before-scale
CARGO_TARGET_DIR="$PWD/target" make test-quick PY="$P"
```

Output folders must be new when repeating captures. Exact outputs and logs remain in ignored `work/ga-refactor/`; no per-ship data is committed.

| Output type | Byte-identical to baseline |
|---|---:|
| First-pass `ga_reading.json` | 14/14 |
| `reinterpret_particulars` `ga_reading.json` | 14/14 |
| Scale replay `ga_reading.json` | 14/14 |
| Arrangement input | 14/14 |

Arrangement inputs also match latest `u10r6` 14/14. Gate: 14/14. Model calls: 0. No drawing image was viewed; no sealed/holdout data was opened. No GitHub API calls.

## Checks

- GA tests: 265 passed; new vocabulary export tests: 2 passed.
- UI tests: 275 passed.
- Secret pattern scan: 0 findings (bounded scan, not proof of absence).
- `git diff --check`: clean.
- Full quick tier: FAILED as described above; The additional Python-only quick tier was stopped at this early-stop checkpoint; it did not produce a full count. The required quick tier stopped in Rust before reaching Python. Do not claim the expected 2246-test baseline count was reproduced.

## Module map

Line counts include comments and blank lines. Longest function uses AST source span, including nested steps.

| Module | Before lines | After lines | Longest function before → after |
|---|---:|---:|---|
| `ga_scale` | 2514 | 2514 | `spacing_table` 185 → 185 |
| `ga_commercial` | 1168 | 1153 | `interpret` 124 → 124 |
| `ga_labels` | 563 | 534 | `text_candidates` 55 → 55 |
| `ga_vocabulary` | — | 51 | none |
| `ga_reader` | 534 | 534 | `section_deck_camber` 39 → 39 |

## Not done and resume

Scale job modules, commercial job modules, long-function extraction, tuned-constant audit and final structural refresh are not done. No `.codesight` directory is present in this worktree. `ga_reader` has no commercial-path caller; current direct uses are tests. It remains unchanged pending its separate-purpose docstring step.

Resume at step 4 of `docs/plans/2026-11-12-ga-refactor.md` after the PM addresses the baseline quick-tier failure. Keep the recorded baseline outputs. Push only `lane/ga-refactor`; do not merge. The worktree Rust target is removed after the checkpoint push.
