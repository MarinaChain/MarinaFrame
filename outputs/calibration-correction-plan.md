# Calibration Correction Implementation Plan

> **For Claude:** Use executing-plans to implement this plan task by task.

**Goal:** Make a person's calibration correction change the hull without changing the frozen reader.

**Architecture:** Reuse the intake reader with a supplied corrected calibration. Reuse the first-hull path for new curves and preserve prior revisions. Save the person's structured choice in the existing review note contract.

**Tech Stack:** Python, plain JavaScript, Rust app core.

## Review
- Architecture: PASS — reuse the reader and hull paths; no new geometry engine.
- Quality: WARN — corrections must not reuse stale builds or clear unrelated flags.
- Tests: PASS — synthetic sheets, review/revision records, UI interaction tests, Rust command tests.
- Performance: PASS — one local reader pass per explicit correction; no model label calls.

## Commit checkpoints
1. Choice UI: bow/stern swap, order reversal with named half, Other with text. Save a structured review note. Tests: `tests/test_body_plan_intake.py`, all UI tests.
2. Correction pipeline: re-read using corrected calibration, rebuild through first-hull path, preserve old revision and add person history; Other disables reader anchors and rebuilds through model path. Test corrected mappings and revisions, command dispatch, failures.
3. Suggest swap only for an automatic side-disagreement flag. Never submit until Apply. Test suggestion and explicit click.
4. Extend integration and regression tests, check frozen hashes, update integration documentation.

## Checks before every commit
Start test command chains with `set -o pipefail`. Run touched Python tests with `PYTHONPATH=src:. .venv/bin/python -m pytest`, and `node --test app/ui-tests/`. If Rust changes, run `cargo test -p marinaframe-app-core` and `cargo fmt --all --check` at this worktree root. Stage explicit paths and commit on `feature/calibration-swap`. Never push, merge, or switch branches.

## Resume
Read `git log` to find the last completed checkpoint. Step 1 implemented and tested (17 Python tests; full UI suite). Next: checkpoint 2. Keep `engineering_approved` false. Do not edit `body_plan_*.py` frozen modules.
