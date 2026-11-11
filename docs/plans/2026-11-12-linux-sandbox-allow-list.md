# Linux Sandbox Allow-list Implementation Plan

> **For Claude:** Use executing-plans and test-driven-development for each task.

**Goal:** Replace the syscall deny-list with a measured deny-by-default allow-list, strengthen child attestation, and close the remaining home/probe gaps.

**Architecture:** Preserve the native Linux launcher and Python interface. Collect strace summaries from contained real CAD on Linux before selecting allowed syscalls. Retain architecture guards, argument-level signal-owner denials, Landlock and hard limits. macOS Seatbelt remains unchanged.

**Tech Stack:** Rust/libc/seccomp BPF, Landlock, Python/pytest, strace, GitHub Actions.

## Review

Architecture PASS: same boundary and no unsafe discovery mode. Quality PASS: explicit named syscall groups with provenance comments. Coverage WARN: this Mac cannot execute Linux; trace and policy checks require CI. Performance PASS: fixed small filters and one-time attestation.

## Tasks

1. Add `scripts/trace_linux_cad.py`, invoked in the Linux controller CI job with strace installed. Run the actual sandboxed interpreter through import, solid creation, STEP/STL export and import probes. Keep per-probe summary files as CI artifacts and print syscall summaries. Do not disable containment or trace user data. Run x86_64 and aarch64 jobs where supported.
2. Add portable and live attestation regressions. After checking Seccomp 2/NoNewPrivs 1, require root listing to fail EACCES and kcmp to return EPERM. A host container filter alone must not satisfy the filesystem challenge. No new procfs grants.
3. Reject write roots which contain the real account home, including homes outside /home. Test the rejection with scratch HOME and a simulated account home not covered by fixed root strings. Replace syslog EPERM probe with SYSLOG_ACTION_SIZE_BUFFER (10), requiring seccomp EPERM before the kernel permission-independent size query.
4. Run full Mac quick tier before the first push. Retrieve bounded CI trace evidence. Build named architecture-specific syscall lists from observed successful calls plus documented CPython needs. Retain fcntl/ioctl argument filters inside allowed syscalls. Default final action EPERM, label `linux-landlock-seccomp-allow-list`. Add a negative probe for an innocuous formerly allowed syscall such as getcpu.
5. Test native filter structure and live CAD/attestation/probes on Linux; run full Mac quick tier before final push. Record missing-call additions with a specific reason and real trace evidence, not a broad fallback.
6. Report item-by-item file:line, regression test, CI result, and architecture coverage. Commit often; push only lane/linux-sandbox-2, never merge.

## Commands and boundaries

Every cargo command uses `CARGO_TARGET_DIR=/Users/jonathanjie/Documents/workspace/MarinaFrame/.claude/worktrees/shared-target-sol`.

Required Mac check:

```sh
CARGO_TARGET_DIR=/Users/jonathanjie/Documents/workspace/MarinaFrame/.claude/worktrees/shared-target-sol MARINAFRAME_TEST_PYTHON=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
```

Work only in this worktree. Keep temporary trace/check artifacts under work/. Preserve shared target. Do not access sealed/holdout inputs. No production own-code wall limits.

## GitHub budget

No polling watchers. At most one CI status check every five minutes, at most 40 total gh calls. Record each call below with time, purpose, and count. Stop on rate-limit HTTP 403. No gh calls used at plan creation.

## Resume point and evidence

2026-11-12: discovery checkpoint 20443ce pushed to lane/linux-sandbox-2. Stronger attestation, account-home ancestor predicate/tests, syslog size probe and contained strace fixture implemented. Full Mac quick tier exit 0: 2011 Python passed, 4 Linux-only skips, 84 deselected; 269 UI passed; Rust format/Clippy/tests passed; secrets scan 0 findings. Linux cross-target check/Clippy passed. Next: collect trace evidence from CI, implement allow-list, repeat full checks. Allow-list selection must wait for real trace evidence.

GitHub ledger:
- Call 1/40: 2026-11-12 06:18:27 +08, `gh run list` after discovery push, no run registered yet. Session scheduling did not resume work; PM resumed explicitly.
- Call 2/40: fetched complete logs for cancelled run 43110649775. No summary exists: CAD trace stalled after import font warnings until the 30-minute job cancellation. Do not invent a measured set from this run. Trace now emits incremental evidence and stage markers; fixture uses exportStl(parallel=False) instead of the default thread-creating mesher. Required Mac quick tier rerun is active before discovery retry push. No watchers or new scheduling.
- Call 3/40: 2026-11-12 06:59:05 +08, run list immediately after b282864 push still showed only the old cancelled run. Do not check again before 07:04:05 +08. Retry checkpoint Mac quick tier exit 0: 2011 Python passed, 4 skipped, 84 deselected; 269 UI passed; Rust checks passed; secrets scan 0 findings. Corrected incremental trace checkpoint b282864 pushed; await PM resumption/CI registration. No measured set yet.
