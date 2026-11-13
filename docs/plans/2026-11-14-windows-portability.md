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

## Continuation: fixed baseline groups (largest first)

Baseline `43483045382`: **498 failures + 64 errors = 562**. Counts assign each entry to its terminal root cause; wrapped assertions are traced, not counted twice.

| Root cause | Failures | Errors | Total |
|---|---:|---:|---:|
| Directory sync through POSIX directory open (including four assertion wrappers) | 373 | 64 | 437 |
| Secure no-follow reads: reexport 17, progress 15 | 32 | 0 | 32 |
| Unsupported secure process lifecycle (including one subprocess wrapper) | 21 | 0 | 21 |
| CI shell routing tests select Windows Bash/WSL without a distribution | 21 | 0 | 21 |
| Round admission lock calls unavailable geteuid | 7 | 0 | 7 |
| Path serialization/expectations | 5 | 0 | 5 |
| Unsupported private shared pool assertions | 5 | 0 | 5 |
| Restricted checkpoint metadata (summary only; not investigated) | 4 | 0 | 4 |
| FIFO tests call unavailable mkfifo | 4 | 0 | 4 |
| Tests patch unavailable killpg | 4 | 0 | 4 |
| POSIX child-status WNOHANG assumptions | 3 | 0 | 3 |
| Progress writer imports fcntl | 3 | 0 | 3 |
| Secure worker-result reader requires O_DIRECTORY | 2 | 0 | 2 |
| Explicit unsupported isolated worker profile | 2 | 0 | 2 |
| macOS profile string assertions with Windows paths | 2 | 0 | 2 |
| Windows-invalid wildcard filenames | 2 | 0 | 2 |
| Measurement fake POSIX command (exact child error not logged) | 2 | 0 | 2 |
| Foreign-owner test calls unavailable getuid | 1 | 0 | 1 |
| Default text encoding rejects Unicode minus | 1 | 0 | 1 |
| Ordinary frozen-reader byte-hash mismatch | 1 | 0 | 1 |
| Worker receipt expects resource handling past Windows refusal | 1 | 0 | 1 |
| Wheel environment lacks setuptools backend | 1 | 0 | 1 |
| Benchmark wrapper missing result (underlying error not logged) | 1 | 0 | 1 |
| **Total** | **498** | **64** | **562** |

### Fixed continuation gate and stop condition

Attempt the five largest groups above, in that order (tie order as listed), or stop sooner if Windows failures and errors both reach zero. After each group: run focused tests and required quick tier; commit; push only this branch; inspect one completed Windows job and record new failures/errors/passes/skips. Wait at least five minutes between GitHub status checks. New failures exposed by a fix remain visible and do not change the baseline group order. No broad skips and no restricted checkpoint investigation.

- Group 1 design: native `CreateFileW` with backup semantics and write access, then `FlushFileBuffers`. Where Windows rejects writable directory handles, confirm a read-only directory open and document the absent directory durability guarantee. Known unsupported flush results are a documented no-op; unexpected failures propagate. File fsync and POSIX directory fsync remain unchanged. API references: [FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers), [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
- Group 1 focused tests: 86 passed before final access-right refinement; seven refined adapter tests passed. Commit `9d14e27`. Required quick tier passed: 2,773 Python passed, 4 skipped, 129 deselected; 275 UI passed; Rust checks passed; secrets and private identity scans zero findings. Pushed through `247c1d2`. Native run `43490090302` is in progress; scheduled one result read after a 25-minute completion window. Native result: **234 failed, 2,605 passed, 24 skipped, 43 errors** (1,286.99 s); Linux **2,886 passed, 20 skipped**. Compared with baseline: 264 fewer failures and 21 fewer errors. Fixing directory opens exposed later publication/security failures; these remain visible.
- Group 2: added a shared call-time capability error before progress/reexport/worker-result secure descriptor opens on Windows. Native reparse-point plus descriptor-relative traversal parity is not implemented; do not substitute lstat-then-open. Explicit test-name capability requirements skip only tests that exercise that unavailable primitive; refusal regressions continue running on Windows. POSIX implementations are unchanged. Focused tests: 87 passed. Required quick tier: 2,777 Python passed, 4 skipped, 129 deselected; 275 UI passed, Rust passed, secrets/private identity zero findings. Pushed `d7d097f`; native run `43496185455`: **198 failed, 2,609 passed, 60 skipped, 43 errors** (1,263.99 s). Linux: **2,890 passed, 20 skipped**. Group 2 removes 36 failures with explicit capability reasons; no collection errors.
- Group 3: retain the existing shared call-time lifecycle refusal before child launch; add exact test-name requirements for the 21 baseline lifecycle failures. Windows job objects alone do not provide parity with the current identity, descendant cleanup and resource-limit contract; do not substitute terminate-only behavior. Refusal regressions remain active. Quick/native result pending.
- Plan review: architecture PASS (small platform layer); quality PASS (unexpected errors retained, native handles closed); tests WARN (native Windows required); performance PASS (bounded native calls).
- Process exception: a read-only classification agent was accidentally launched with tool worktree isolation. This created an extra worktree despite the lane rule; no implementation edits were delegated. All lane changes remain in this designated worktree. Do not create another worktree.

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
- Required quick tier completed with exit 0: Rust formatting/clippy/workspace tests passed; Python 2,766 passed, 4 skipped, 129 deselected (770.85 s); UI 275 passed, zero failed; bounded secrets scan zero findings. The required private denylist identity scan also returned zero findings separately.
- The Makefile uses the shared Rust target; this lane has no `target` folder. Never delete the shared target.
- Pushed through `81337b1` to `origin/lane/windows-portability`; no merge.
- Native CI run `43483045382` completed. Linux dependency probe: 2,879 passed, 20 skipped (1,044.17 s). Windows: 498 failed, 2,313 passed, 24 skipped, 64 runtime/setup errors (1,194.28 s). There are no `ERROR collecting` entries; execution reached the full suite. The report-only job returns success despite these failures; this does not satisfy the gate.
- Common native Windows root cause: `provenance.sync_directory` calls `os.open` on a directory, which the Windows CRT refuses with PermissionError. Other exposed groups include unsupported lifecycle/no-follow operations, POSIX-specific test assumptions, and path separator expectations. Do not suppress these with broad skips or replace durable publication with an unchecked no-op. Do not investigate restricted-data test failures in this development lane.
- Resume: implement and test an explicit Windows filesystem durability/publication boundary, then portable progress locking and safe reads; add precise platform reasons only for tests that exercise unavailable security features. Re-run local quick tier before each push and native Windows CI after each coherent batch. Full Windows gate remains FAILED; Linux probe and local macOS quick tier passed. Native macOS CI has not been established by this watch workflow.
