# Windows Portability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove Unix-only collection failures without weakening Linux or macOS security.

**Architecture:** Reuse the existing `file_lock` platform boundary. Keep unsupported OS security operations behind explicit call-time errors; do not replace them with weaker controls. Keep native Windows operations small and testable.

**Tech Stack:** Python, pytest, Windows CRT locks, POSIX locks, GitHub Actions.

---

## Fixed gates (before checking)

1. Windows Python suite collects with zero errors. Every test passes or has a stated platform skip reason. Failures remain failures; no broad skip of ordinary tests.
2. Linux and macOS CI remain green with their security tests unchanged in intent.
3. Local quick tier passes using the main virtual environment and private identity denylist. Targeted platform, lock and worker tests pass.
4. No CFD edits except import-time portability fixes. No restricted datasets opened. Push only `lane/windows-portability`, do not merge.

## Task 1: Import and lock boundary

Files: `src/vessel_reconstruction/parallel.py`, `src/vessel_reconstruction/file_lock.py`, `tests/test_worker_pool.py`, new `tests/test_platform_portability.py`.

- Add a subprocess regression that denies imports of Unix-only modules and imports `parallel` (expected initial failure: `fcntl`).
- Reuse `try_lock_exclusive`; make POSIX account lookup lazy. Keep POSIX ownership, permission and no-follow checks intact. If equivalent private-directory protection is unavailable, use the existing logged unshared-pool fallback rather than pretending the directory is safe.
- Run targeted tests with `PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python -m pytest -q tests/test_platform_portability.py tests/test_file_lock.py tests/test_worker_pool.py`.
- Commit the small tested change.

## Task 2: Audit call-time boundaries

Files: `src/vessel_reconstruction/isolation.py`, `process_limits.py`, `progress.py`, `transaction.py`, `exports/package.py`, `sandbox.py` where present, relevant tests.

- Trace resource limits, process groups, signals, no-replace publication, procfs, and locking. Add focused failing regressions before changing each affected boundary.
- Use explicit unsupported-platform errors for security features without equivalent implementations. Keep all supported-platform behavior intact. Add Windows implementations for ordinary filesystem features when semantics match.
- Run focused regressions after each small change and commit.

## Task 3: Windows evidence and quick tier

Files: `.github/workflows/ci-watch.yml`, platform-specific test files, this plan.

- Ensure the report-only Windows watch runs for these changes and reports collection plus actual failures and skip reasons; do not silently hide failures.
- Run `MF_IDENTITY_DENYLIST_FILE=/Users/jonathanjie/Documents/workspace/marinaframe-private/identity-denylist.txt MARINAFRAME_TEST_PYTHON=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` in background.
- Record exact local results and remote CI limits. Commit and push only this lane. Check remote CI no more often than every five minutes.
- Inspect and remove only this worktree's `target` after final push.

## Plan review

- Architecture: PASS — reuse existing locking boundary; explicit unsupported security operations.
- Quality: PASS — preserve ownership/no-follow and fail-closed security checks.
- Tests: WARN — local import simulation is not native Windows evidence. Windows gate requires Windows CI.
- Performance: PASS — no new dependencies or unbounded polling.

## Results and resume point

- Worktree created from local `continue/v0.5` at `dbb24f4`.
- Root cause found: `parallel.py` imports `fcntl` and `pwd` eagerly despite an existing Windows-capable lock helper.
- Baseline CI run `43467837975` confirms all 21 collection errors originate at the eager `parallel.py` import of `fcntl`.
- Task 1: regression failed on `fcntl`, then passed after reusing `file_lock` and moving `pwd` behind the POSIX directory check. Lock/pool/import tests: 16 passed.
- Task 2: four regressions showed unsupported lifecycle calls could reach process launch or POSIX APIs. Added a shared call-time refusal before those operations. Platform/lifecycle/runtime tests: 51 passed.
- Import-path audit: `resource` already uses `process_limits.posix_resource` and fails closed; sandbox entry already refuses unsupported OSs. `fcntl` in progress is call-time but still needs the shared blocking lock boundary. Atomic directory publication and directory durability, secure no-follow reads, review CLI process-group cleanup, and POSIX pool tests still need Windows treatment. CFD calls were not modified under the lane ownership rule.
- Full collection with `fcntl`, `pwd` and `resource` imports blocked after loading the lock backend: 2,899 tests collected, zero errors (8.38 s). This is an import-path probe on macOS, not native Windows evidence. Collection reads test code only; no holdout scorer was run.
- Workflow now triggers on source/tests and records collection exit code plus platform skip reasons.
- Local tracked identity scan with the private denylist: zero findings. `git diff --check`: clean.
- Quick tier running with the required environment. The Makefile uses the shared Rust target; this lane has no `target` folder. Never delete the shared target.
- Resume: finish quick tier, push the lane, inspect native Windows results, then address remaining platform failures without broad skips. Full Windows/Linux/macOS gate remains pending.
