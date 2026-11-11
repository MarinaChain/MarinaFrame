# CI Filters Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce jobs on feature pushes without hiding failed checks or weakening base-branch CI.

**Architecture:** A first `changes` job compares complete push/PR ranges with plain Git and emits suite flags. Unknown paths and shared configuration select all suites; base pushes and manual runs select all. Keep the secret scan unconditional and preserve existing job names.

**Tech Stack:** GitHub Actions, Bash, Git, Python, Cargo, Node, gh CLI.

---

## Acceptance gates (set before runs)

- Docs-only pushes: changes, secret scan, Linux aggregate only; no Rust/Python/UI suite or macOS runner.
- UI-only pushes: those three jobs plus UI tests; no Rust/Python suites or macOS runner.
- Python-only: Python and worker-integration Rust suites; no UI. Rust-only: Rust suites and package smoke; no UI/Python shards.
- Shared configuration: all Linux suites. Base pushes and manual dispatch: full suites including macOS. Relevant PRs permit macOS; feature pushes never do.
- Aggregate rejects failed/cancelled dependencies and a failed detector, but accepts intentional suite skips.
- No workflow-level path filter in CI. Every action uses a full SHA. No new continue-on-error.

## Task 1: Baseline and classifier

Files: `.github/workflows/ci.yml`, `scripts/ci_changes.sh`, `tests/test_ci_changes.py`.

1. Record baseline run 43080449506 at base 8f0d026, including job counts and elapsed time from gh.
2. Add table-driven classifier tests for docs/UI/Python/Rust/shared/unknown/mixed paths, including deleted and whitespace-containing names.
3. Run focused tests and observe failure before implementation.
4. Add a NUL-delimited Bash classifier and job-level dependencies. Compare push before/head and PR base/head with merge-base. Use full checkout history; for a new branch compare with continue/v0.5. Unknown or unavailable ranges select all.
5. Split cheap scan from conditional lint; update aggregate to accept intentional skips.

## Task 2: Caches and event gates

Files: `.github/workflows/ci.yml`; `.github/workflows/ci-watch.yml` only for consistency.

1. Preserve pip and Cargo lock-based caches; add npm lock-based cache plus npm ci to UI tests.
2. Preserve Cargo registry/git/target paths and key by lock, toolchain, runner, and job.
3. Do not cancel main or continue/v0.5; cancel feature runs. Apply the same concurrency protection to CI watch.
4. Gate macOS by suite relevance and PR/manual/base-push events.

## Task 3: Local checks and commits

1. Run classifier tests, parse YAML, and run `bash -n` on each Bash run block and classifier. Run actionlint if installed; otherwise record its absence.
2. Run `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` in background. Do not push unless it passes.
3. Commit implementation with the common lane attribution, then push lane/ci-filters.

## Task 4: Live evidence

1. Wait for implementation run; collect jobs, elapsed time, and cache log evidence.
2. Push a docs-only update to this report, wait for completion, and collect evidence.
3. Push a harmless UI comment, wait for completion, and collect evidence. Keep the comment.
4. Use the existing completed base full run as baseline; dispatch CI on continue/v0.5 if fresh evidence is needed. Never push to or merge the base. New base-push behavior cannot be exercised until PM merges.
5. Record exact run IDs, counts (executed versus skipped), wall times, conclusions, cache hits, and limits below. Commit and push the final report after quick checks.
6. Inspect and remove only this worktree's target/ as the final cleanup step.

## Resume point

Resumed from WIP a6c4227 and preserved its implementation. Clean commits `e890dbc` and `fb87cea` are pushed to lane/ci-filters. The fresh local quick tier passed. Implementation push run `43095522151` is in progress. Next: collect that run, then push this docs-only checkpoint, a harmless UI-only comment, and dispatch a full run on this lane. Wait for each run before another push to avoid feature-run cancellation. Record results, push the final report after quick checks, then delete only this worktree's target/.

## Results

### Baseline and local checks

- Baseline CI run [43080449506](https://github.com/MarinaChain/MarinaFrame/actions/runs/43080449506): push at `8f0d026`, **13 executed / 0 skipped jobs**, **349 seconds** (2026-11-11 18:43:24Z–18:49:13Z).
- Wall time means workflow creation to final completion, including runner queue and setup. Counts include matrix children and the Linux aggregate; skipped matrix jobs may appear as one unexpanded placeholder.
- Classifier tests: **21 passed**. Review found that `docs/dependency-scope-exclusions.json` is audit policy, not documentation. A new regression test failed before the explicit shared-configuration rule was added, then passed. The prior run's red-before-green test step cannot be established from the saved WIP; no historical failure is claimed.
- All three workflow YAML files parse. All action references have full 40-character commit SHAs. **52 Bash run blocks** and `scripts/ci_changes.sh` pass `bash -n` (Actions expressions replaced with inert text for syntax checking).
- `actionlint` is not installed, so that check was not run.
- Executed the actual detector Bash against isolated Git histories: **10 cases passed** (docs, UI, deleted whitespace path, multi-commit range, PR merge-base, new-branch fallback, missing history, main, continue/v0.5, manual dispatch).
- Executed the actual aggregate Bash: **6 cases passed** (intentional skip accepted; failure, cancellation, failed/skipped detector, and skipped scan rejected).
- Initial `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` completed with exit 0: **1,998 Python tests passed**, 84 CAD tests deselected; **269 UI tests passed**; Rust fmt, Clippy, quick tests, and secret scan passed (0 findings). The fresh quick tier after the audit-policy regression fix also completed with exit 0: **1,999 Python tests passed**, 84 deselected (543.91 seconds); **269 UI tests passed**; Rust checks and secret scan passed (0 findings). Only then was the lane pushed.
- Stable pre-existing job IDs and display names checked against `8f0d026`; no new `continue-on-error`.
- Docs-checkpoint local quick tier also passed; its commit/push was blocked by the subsequent remote-status check, not a local test failure.
- Live-run evidence: pending. At 2026-11-11 21:45Z, both overlapping default `gh run watch` commands stopped with HTTP 403 (shared 5,000-request API limit). This does not establish CI failure. Stop three-second watchers; resume after the 21:56:55Z reset with sparse checks. Implementation run `43095522151` remains the target. No docs-only push has occurred yet.

### Limits fixed before live runs

- A feature push deliberately omits macOS even when all Linux suites are selected. A manual dispatch on this lane will test the new full workflow, including macOS, without changing the protected base.
- Protected-branch push behavior cannot be demonstrated with the new workflow until the PM merges. No base branch push or repository setting change is permitted.
- Python changes retain Rust worker integrations and wheel smoke. UI remains independent. Unknown paths select every suite rather than risk a missed check.
