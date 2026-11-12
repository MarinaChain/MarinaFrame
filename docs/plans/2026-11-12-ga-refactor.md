# GA Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separate GA reader jobs without changing output bytes, prompts, constants, or rules.

**Architecture:** Keep `ga_scale` and `ga_commercial` as compatible entry points. Move cohesive jobs into modules with explicit imports; keep dependencies directed and preserve call order. Do not use dynamic global injection or duplicate implementations.

**Tech Stack:** Python, NumPy, Pillow, pytest, existing Rust/UI quick tier.

## Boundaries

Work only in `sol-ga-refactor`, branch `lane/ga-refactor`, starting at `c30e5cf`.
Read only development rounds under the main checkout's `work/ga-internal-23/dev-runs`.
Never inspect drawing images, sealed data, holdout rounds, or holdout images. Code may read development images for replay. No model calls. No `gh` calls. Per-ship outputs stay in ignored `work/ga-refactor/`.

## Design review

- Architecture: PASS. Job modules and explicit compatibility exports match current Python code.
- Quality: WARN. Imports between coarse/fine passes can form cycles; keep imports local where needed. Preserve constant comments and all prompts verbatim.
- Tests: WARN. A test patches `ga_commercial.MAX_TOTAL_IMAGE_BYTES`; image helpers must retain that setting's effect. Add compatibility tests, not per-ship fixtures.
- Performance: PASS. Move code without adding image reads or loops.

## Steps and checks

1. Capture the baseline at `c30e5cf` before edits. Use `scripts/ga_replay_scale.py` on main-checkout `dev-runs/u10`, with main-checkout `inputs`, into a fresh `work/ga-refactor/before-scale`. Capture `interpret` and `reinterpret_particulars` for the same 14 cases into `before-interpretation-2` (the first attempt failed before writing any case because a parent directory was missing). Assert exactly 14 cases. Compare arrangement bytes to `u10r6`. Run the gate and quick tier.
2. Add a reusable offline proof runner that captures first-pass, particulars, and scale replay; blocks model entry points; compares each required file byte-for-byte; emits aggregate counts only. Record baseline module sizes and longest function.
3. Move vocabulary from `ga_labels.py` and `ga_commercial.py` into `ga_vocabulary.py`. Re-export old names. Run GA unit tests, complete replay comparison, and quick tier; commit this move only after all pass.
4. Split `ga_scale.py` into frame fitting, request/extents, dimension checks, overlap/outline, and arrangement jobs. Resolve dependencies explicitly. Keep public and private names imported by tests available. Make one cohesive move per commit with the same proof and quick tier.
5. Split `ga_commercial.py` image preparation, interpretation/checks, counts and CLI. Preserve the patched image-byte limit through explicit parameters if a move needs it. Use the same proof and quick tier for each commit.
6. Extract named steps from functions over about 80 lines, without changing expression order or constants. Test and replay each small change before committing.
7. Check all uses of `ga_reader.py`. Keep it; document its separate purpose if it is not in the commercial path.
8. Refresh structural index if present. Review elegance, run final proof/gate/quick tier, record module map and commands, commit results, push only `lane/ga-refactor`. Inspect and remove this worktree's `target/` as the last step. Do not merge.

## Commands

Run from this worktree; `P=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`.

- Unit tests: `PYTHONPATH=src $P -m pytest tests/test_ga_commercial.py tests/test_ga_labels.py tests/test_ga_scale.py tests/test_ga_arrangement.py`
- Quick tier: `CARGO_TARGET_DIR="$PWD/target" make test-quick PY=$P` (background job; no process timeout).
- Scale: `PYTHONPATH=src $P scripts/ga_replay_scale.py --run /Users/jonathanjie/Documents/workspace/MarinaFrame/work/ga-internal-23/dev-runs/u10 --inputs /Users/jonathanjie/Documents/workspace/MarinaFrame/work/ga-internal-23/inputs --out work/ga-refactor/NEW-scale`
- Gate: `PYTHONPATH=src $P scripts/ga_arrangement_gate.py work/ga-refactor/NEW-scale`

## Resume point

Stopped after the vocabulary move (step 3), before any scale/commercial function moves. Baseline and changed quick tiers both fail at `app/core/tests/replace_sheet.rs:144`: expected no registry error, got `sheet_replacement_failed`. Do not fix or widen this unrelated gate in this lane. Resume step 4 only after the PM resolves or explicitly accepts the baseline failure. See `docs/plans/2026-11-12-ga-refactor-results.md` for tracked evidence (the final report copy is in ignored `outputs/ga-refactor-checkpoint.md`). The early-stop commit/push is required by the lane brief; it is not a claim that the quick tier passes.
