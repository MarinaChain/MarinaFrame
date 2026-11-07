# W11 continuation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the live vision model investigate hull-line identity while deterministic code controls geometry and review readiness.

**Architecture:** Keep the existing typed Rust controller and Python investigation tools. The model supplies claims and bounded view instructions, not geometry or approval. Every accepted identity remains an open `model_choice` guess.

**Tech Stack:** Rust, Python, NumPy, Pillow, OpenCascade, DeepSeek through the Rust provider worker.

## Constraints and review

- Work only in this worktree and branch. Do not push. Preserve W12-owned files.
- No wider gates, tolerances, aggregate tool/cost caps, reference answers in inference, or model self-approval.
- Use `PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`, `PYTHONPATH=$PWD/src`, and `--worker-source $PWD/src`.
- Review: architecture PASS; code quality WARN (foreground cache and repeated enumeration); coverage WARN (prove guards with mutations); performance WARN (large repeated section masks and disk use).
- The current strategy file has no section 7. Follow the user's explicit W11 scope.

## Task 1: Establish the WIP baseline

1. Read the listed history, Python modules, Rust controller/types/validation/provider, benchmark runners, tests and design documents.
2. Run `PYTHONPATH="$PWD/src" make test-quick PY=$PY`; keep output in `work/w11/checks/`.
3. For each failure, write a regression test, observe failure, make the smallest fix, and rerun the focused test.
4. Inspect cache identity/lifetime and enumeration at repeated calls and candidate capacity. Do not change engine acceptance thresholds.

## Task 2: Prove the trust boundary

Files: `rust-control/tests/investigation_guards.rs`, `rust-control/src/controller.rs`, `rust-control/src/types.rs`, `rust-control/src/validation.rs`, `tests/test_investigation.py`.

1. Check existing tests for unsnapped selections, review/gate injection, self-confirmation and forged receipt data.
2. Extend existing cases where possible. Keep real-CAD tests ignored with the project's exact marker.
3. Remove one guard at a time, run its focused test and require failure, then restore the exact source. Keep mutation logs outside tracked source. Never commit mutations.
4. Run quick checks and secret scan before a code checkpoint commit.

## Task 3: Run paired development evaluation

Files: `benchmarks/investigation/arms.py`, `benchmarks/investigation/factory_sample.py`.

1. Preserve prior pilot runs as development history, not final results.
2. Reuse hash-checked prepared inputs: Gunnerus, Balclutha s7/s48, Wapama s5, ALMA lines/sections, and the fixed 40-case factory development sample. Never use validation/sealed hull splits.
3. Build the release controller. Freeze the worker source for each final run batch if needed. Load keys only through the canonical loader; never print them.
4. Run abstain, draft and live arms on identical inputs. Keep every terminal outcome, failed request, abstention and prior pilot usage separate.
5. Summarize actual receipts, tokens, reported cost, missing-cost calls, wall time, guesses and lines. Fix summary handling of missing state before running failed cases through it.
6. Open overlays and record visible correct/wrong/uncertain identity. Do not equate ink support with identity.
7. Score Gunnerus with cached STEP truth and the existing metric file. Score factory drafts only after inference. Record no-model cases explicitly.
8. Retain compact results, receipts and overlays; delete only inspected intermediate run folders after scoring.

## Task 4: Review, verify and report

1. Write `docs/LLM_LINE_IDENTITY.md` with design, limits, tables, visual evidence, all failures and honest conclusions. Put compact final evidence under `outputs/w11/`.
2. Use demand-elegance and verification-before-completion before final delivery.
3. Run `make test-quick` and `$PY scripts/scan_secrets.py` before each commit.
4. Check `pgrep -fl 'make test-full'`; run the full tier once only when none is running. Use the explicit worktree worker source for the smoke check.
5. Commit on the existing branch, include the required attribution, do not push. Run `cargo clean` when done.
6. Report under 500 words, with exact model usage and final commit SHA.

## Resume point

Baseline quick tier is running with the correct runtime (`work/w11/checks/quick.log`). Rust compile, formatting and lint passed on the WIP. No source fixes have been made. Read-only guard review is in progress. Prepared inputs and earlier pilot runs already exist under `work/w11/`; inspect before overwriting or deletion.
