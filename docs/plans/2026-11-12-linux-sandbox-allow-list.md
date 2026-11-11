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
- Call 3/40: 2026-11-12 06:59:05 +08, run list immediately after b282864 push still showed only the old cancelled run. Do not check again before 07:04:05 +08. Retry checkpoint Mac quick tier exit 0: 2011 Python passed, 4 skipped, 84 deselected; 269 UI passed; Rust checks passed; secrets scan 0 findings. Corrected incremental trace checkpoint b282864 pushed; await PM resumption/CI registration. No measured set yet at that checkpoint.
- Call 4/40: fetched successful run 43116216695 logs on PM resumption. No more gh calls will be made for this push; PM will check CI.

## Measured allow-list implementation

Run 43116216695 completed the x86_64 trace (CPython 3.12.14, OCP/CAD import, box, STEP export/import, serial STL export), exit 0. Measured names:

```
access arch_prctl brk chdir close close_range connect dup2 epoll_create1 execve exit_group fcntl fstat futex getcwd getdents64 getegid geteuid getgid getpid getppid getrandom gettid getuid ioctl kcmp landlock_add_rule landlock_create_ruleset landlock_restrict_self lseek mbind mkdir mmap mprotect mremap munmap newfstatat openat pipe2 poll prctl pread64 prlimit64 read readlink rseq rt_sigaction rt_sigprocmask sched_getaffinity set_robust_list set_tid_address sigaltstack socket stat statx times uname unshare vfork wait4 write writev
```

This trace includes the trusted supervisor/launcher and failed calls. Excluded from permissions: socket/connect/kcmp (denied probes), Landlock/prctl/unshare (launcher setup), vfork/wait4 (supervisor subprocess), prlimit64 (cross-process interface), mbind (NUMA policy; not required for successful CAD). All other measured worker-safe calls are allowed. fcntl/ioctl signal-owner command filters execute before allow rules. Unknown calls end in EPERM; alternate ABI guards still kill.

Beyond-trace additions are commented beside their entries: vDSO clock fallbacks, nanosleep for Python time.sleep, exit/signal-return, buffered/vector I/O, confined atomic CAD publication, and aarch64 native equivalents for absent legacy x86 calls. aarch64 uses libc's native syscall constants but has no measured real-run evidence yet; do not claim otherwise.

Receipt label is `linux-landlock-seccomp-allow-list`. Regression `unlisted_harmless_syscall_is_denied_by_default` requires EPERM for getcpu, which the previous deny-list permitted. Existing signal-owner, IPC, cross-process, home, attestation and real CAD tests remain mandatory in Linux CI. Mac targeted tests 13 passed, 4 Linux-only skips; Linux cross-type-check and Clippy passed. Full Mac quick tier completed exit 0: 2011 Python passed, 4 Linux-only skips, 84 deselected, 5 warnings (353.22 seconds); 269 UI passed; Rust format/Clippy/tests passed; secrets scan 0 findings. Push includes 4968838 and measured allow-list commit 8379e9a. PM checks subsequent CI; no further GitHub calls, watchers or schedules. API usage remains 4/40. New allow-list runtime result remains pending CI.
