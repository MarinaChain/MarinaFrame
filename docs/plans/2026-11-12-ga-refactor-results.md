# GA refactor results — 2026-11-12

## Changes and checkpoints

No rule, prompt, or tuned-constant value changes. `ga_scale` and `ga_commercial` remain the compatible entry points, with explicit re-exports. Dependencies are explicit; there is no global injection or dynamic module proxy.

| Commit | Step | GA tests | Four output types identical | Latest arrangement / gate | Model calls |
|---|---|---:|---:|---:|---:|
| `f95a377` | Shared label vocabulary and offline proof | 265 + 2 | 14/14 each | 14/14 / 14/14 | 0 |
| `577c81b` | Scale modules split by job | 267 | 14/14 each | 14/14 / 14/14 | 0 |
| `3af9ebe` | Commercial modules split by job | 267 | 14/14 each | 14/14 / 14/14 | 0 |
| `111ef76` | Frame, extent, overlap and depth steps | 267 | 14/14 each | 14/14 / 14/14 | 0 |
| `701dcf0` | Interpretation, fragments and CLI steps | 267 | 14/14 each | 14/14 / 14/14 | 0 |

The four output types are first-pass `ga_reading.json`, `reinterpret_particulars` `ga_reading.json`, scale replay `ga_reading.json`, and `ga_arrangement_input.json`. Arrangement inputs also match `u10r6` exactly. Baseline captures were made at `c30e5cf` before source edits. The independent initial captures and unified baseline match in all 56 files. Per-case bytes and logs stay in ignored `work/ga-refactor/`; nothing per ship is in git.

## Sheet-replacement diagnostic

The original full-tier assertion at `app/core/tests/replace_sheet.rs:144` reported the complete registry message:

> The action could not be completed (sheet_replacement_failed).

The PM confirmed the test passes elsewhere and instructed one diagnostic run, not a test/app change:

```sh
CARGO_TARGET_DIR="$PWD/target" \
MARINAFRAME_TEST_PYTHON=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python \
RUST_BACKTRACE=1 cargo test -p marinaframe-app-core --test replace_sheet \
  real_worker_replaces_one_unreadable_extra_sheet_without_a_hull_rebuild -- --exact --nocapture
```

Result: **1 passed, 0 failed, 3 filtered out**. Both assertions of `registry.last_error(&task)` passed against `None`; there is no error string from this diagnostic. The original failure did not recur. This does not establish which environment factor caused the earlier failure. No test or app code was changed. Per PM direction, the full quick tier is left to the PM at merge and does not block the targeted refactor gates.

## Reproduction

Run from the lane worktree. Output folders must be new. Do not use sealed/holdout data.

```sh
P=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
W=/Users/jonathanjie/Documents/workspace/MarinaFrame/work/ga-internal-23
# Baseline, run before editing at c30e5cf:
PYTHONPATH=src $P scripts/ga_replay_scale.py --run "$W/dev-runs/u10" --inputs "$W/inputs" --out work/ga-refactor/before-scale
PYTHONPATH=src $P scripts/ga_refactor_proof.py --run "$W/dev-runs/u10" --inputs "$W/inputs" --out work/ga-refactor/before
# Repeat per checkpoint with a new name:
PYTHONPATH=src $P scripts/ga_refactor_proof.py --run "$W/dev-runs/u10" --inputs "$W/inputs" --out work/ga-refactor/NEW --before work/ga-refactor/before --latest "$W/dev-runs/u10r6"
PYTHONPATH=src $P -m pytest tests/test_ga_commercial.py tests/test_ga_labels.py tests/test_ga_scale.py tests/test_ga_arrangement.py tests/test_ga_vocabulary.py -q
CARGO_TARGET_DIR="$PWD/target" MARINAFRAME_TEST_PYTHON="$P" cargo test -p marinaframe-control ga_reading
# Lane W script on each newly generated arrangement:
for case in work/ga-refactor/NEW/GA-*; do
  PYTHONPATH=src $P scripts/ga_arrangement_gate.py "$case/scale"
done
```

Checkpoint folder names: `vocabulary`, `scale-split`, `commercial-split`, `scale-steps`, `commercial-steps`, `final`. Each has corresponding `*-tests.log` and `*-proof.log` (vocabulary uses `vocabulary-unit.log` plus the separate export-test result).

## Module map

Before is `c30e5cf`. Line counts include comments and blank lines. Longest function is the AST source span, including nested steps.

| Original module | Before lines | Longest function |
|---|---:|---|
| `ga_scale` | 2514 | `spacing_table` (185) |
| `ga_commercial` | 1168 | `interpret` (124) |
| `ga_labels` | 563 | `text_candidates` (55) |
| `ga_reader` | 534 | `section_deck_camber` (39) |

| Final module | Lines | Longest function |
|---|---:|---|
| `ga_commercial` | 199 | `read_one` (62) |
| `ga_commercial_cli` | 135 | `_argument_parser` (44) |
| `ga_commercial_settings` | 110 | `definition_sentences` (20) |
| `ga_counts` | 262 | `finish_counts` (76) |
| `ga_images` | 187 | `prepare` (48) |
| `ga_interpretation` | 336 | `interpret` (58) |
| `ga_labels` | 534 | `text_candidates` (55) |
| `ga_provider` | 60 | `failed_reading` (18) |
| `ga_reader` | 538 | `section_deck_camber` (39) |
| `ga_reading_output` | 45 | `write_app_run` (17) |
| `ga_scale` | 320 | `scale_pass` (77) |
| `ga_scale_arrangement` | 540 | `merged_spaces` (75) |
| `ga_scale_depth` | 222 | `_check_pointed_depth` (64) |
| `ga_scale_dimensions` | 300 | `read_scale` (75) |
| `ga_scale_extents` | 167 | `read_extents` (74) |
| `ga_scale_frames` | 509 | `spacing_table` (65) |
| `ga_scale_geometry` | 45 | `side_of_label` (7) |
| `ga_scale_overlaps` | 386 | `_resolve_extent_pair` (61) |
| `ga_scale_requests` | 261 | `prepare_extents` (51) |
| `ga_scale_settings` | 234 | none |
| `ga_spaces` | 36 | `add_space` (15) |
| `ga_vocabulary` | 49 | none |

The longest remaining GA reader function is `scale_pass` at 77 lines (before: 185).

## Final checks

- GA plus legacy envelope tests: **315 passed** (267 GA tests plus 48 legacy tests).
- `cargo test -p marinaframe-control ga_reading`: **11 passed**, no failures.
- Final four output types: **14/14 byte-identical each**; latest arrangement match **14/14**; gate **14/14**; model calls **0**.
- Lane W script run separately on all final arrangements: **14/14 pass**.
- Static undefined-name checks and full-range `git diff --check`: pass after removing trailing vocabulary blank lines.
- AST audit: all 147 original named constant expressions are retained unchanged.
- Bounded secret pattern scan: 0 findings, not proof of absence.
- Full quick tier: not rerun after continuation, per PM direction. The earlier full-tier failures remain recorded above.
- Independent source review: pending.


## Scope retained

`ga_reader` is the earlier vector/raster whole-vessel geometry reader. No commercial-path caller uses it; direct source-tree uses are tests. It is retained with a separate-purpose module docstring. Image limits still used by scale requests come through the compatible commercial module, including the tested patched total-byte limit.

All tuned constant values and their original reasons are retained in settings modules; no new fit thresholds were introduced. Existing numeric expressions and prompt text stay unchanged. No images were viewed or sent to a model. No sealed/holdout paths were opened. No GitHub API calls were made. No `.codesight` index or context map is configured in this worktree, so there is nothing local to refresh.
