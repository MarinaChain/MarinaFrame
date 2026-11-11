# W12 Setup and Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish checked model sheet setup and a veto-only build reviewer, with measured development results.

**Architecture:** Python prepares source-bound images and checks model proposals. Rust alone sends requests through its provider worker and applies the finalization veto. Missing values remain missing; no validation gates change.

**Tech Stack:** Rust, Python, Pillow, NumPy, CadQuery, DeepSeek through the existing provider worker.

---

## Boundaries and review

- Work only in this worktree. Do not push. Do not edit W11 files or trace logic.
- Architecture PASS: follows table reading; no Python HTTP.
- Quality WARN: pixel checks establish consistency, not the truth of text or semantic identity. State this limitation.
- Tests WARN: add renderer/finalization coverage and mutations, not only reply parsing tests.
- Performance PASS: bounded requests and no-progress termination; no aggregate call cap.

## Task 1: Establish WIP baseline

1. Read the listed source and strategy documents.
2. Run `cargo test --workspace --no-run`.
3. Fix formatting only, then run `PYTHONPATH=$PWD/src make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`.
4. Record failures and fix their causes before feature work.

## Task 2: Checked sheet setup

Files: new `src/vessel_reconstruction/llm_setup.py`, `tests/test_llm_setup.py`.

1. Write tests for ink panels, axis alignment, independent scale marks, scale disagreement, station order and missing evidence.
2. Run them to confirm failure before implementation.
3. Add source-bound ruled crops and Rust CLI orchestration with feedback and no-progress termination.
4. Keep model proposals separate from check results. Missing semantic or setup fields block automatic spec publication.
5. Run tests. Mutate each guard, confirm its regression test fails, restore.

## Task 3: Veto reviewer

Files: `rust-control/src/model_review.rs`, `src/vessel_reconstruction/llm_review.py`, new reviewer tests. Only the existing narrow finalization hook may change in `controller.rs`.

1. Test the renderer output-directory contract and receipt/image binding.
2. Fix the directory mismatch.
3. Test explicit veto, no-veto, incomplete reply, retained same-STEP veto and engineering approval remaining false.
4. Mutation-test new guards and the finalization hook. Add CAD Rust integration files to `CAD_RUST_TESTS` if used.

## Task 4: Development evaluation

Files: `benchmarks/llm_setup_review/`, evidence under `work/w12/`, final summaries under `outputs/`.

1. Regenerate 40 development drawings with `sample --setup-sample`; confirm frozen drawing hashes.
2. Run setup without sending generator truth; compare each proposed and checked value to truth afterwards.
3. Render authentic source sheets and inspect setup overlay images.
4. Rebuild `sysser45-L1` and correct controls, retaining task evidence; run veto review and count station-level true/false vetoes and misses.
5. Prove the silent wrong-build cause from retained trace and truth. Propose a fix without changing `agent_tools.py`.

## Task 5: Final verification and commit

1. Write `docs/LLM_SETUP_AND_REVIEW.md`: design, tolerances, measured results, limitations, exact calls/tokens/cost from receipts.
2. Run demand-elegance review and focused tests.
3. Run quick tier before commit. Check `pgrep -fl 'make test-full'`; run full once if idle.
4. Run secret scan, inspect diff, commit on current branch. Do not push.
5. Run `cargo clean` when checks finish. Report SHA and any incomplete acceptance criteria.

## Resume point

Implementation and evaluation are complete. All 41 regenerated image hashes match. Forty development attempts produced zero publishable specs; report records coordinate-frame failures. Exact total: 646 model calls, 693285 prompt and 194311 completion tokens, reported USD 0, provider list USD 0.22041000. Full tier passed once, then explicit-worktree smoke passed after Makefile source-path correction. Final quick tier is running in `work/w12-final-quick.log`. Rust mutations caught/restored 5/5; setup 13/13; renderer 1/1. Stage final outputs/report, confirm quick plus secret scan, commit on current branch, then cargo clean. Do not push.
