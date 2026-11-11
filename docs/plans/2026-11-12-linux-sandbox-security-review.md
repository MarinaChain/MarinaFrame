# Linux sandbox independent review fixes

## Scope and resume point

PM requested fixes before merge. Branch: `lane/linux-sandbox`. Do not merge. Baseline CI at df688e7 passed but did not cover these escape routes. Current changes are committed; full Mac quick tier is running. After it passes, push this lane and require Linux/macOS CI.

## Fix-to-test mapping

| Review item | Source | Regression evidence |
|---|---|---|
| 1. Async signal escape | `rust-control/src/bin/sandbox/linux.rs:307` argument-filter helper; `:343` fcntl/ioctl command filters | `rust-control/tests/linux_sandbox.rs:168` `asynchronous_signal_ownership_is_denied`: F_SETOWN (PID and negative group form), F_SETOWN_EX, F_SETSIG, FIOSETOWN, SIOCSPGRP all return EPERM; ordinary O_ASYNC flag and pipe I/O still work without a signal owner |
| 1. ABI 6 scoping | `rust-control/src/bin/sandbox/linux.rs:243` ruleset scoped signal/abstract-socket bits when ABI >=6; ABI 3–5 use original attribute size | Native policy tests run through the runtime ABI-selected ruleset; ABI 6 branch execution depends on CI kernel version |
| 2. Host IPC | `rust-control/src/bin/sandbox/linux.rs:358` SysV shm/msg/sem and mq deny entries | `rust-control/tests/linux_sandbox.rs:175` `host_ipc_and_cross_process_calls_are_denied`: direct syscall probes require EPERM before invalid-argument validation |
| 3. Other cross-process operations | `rust-control/src/bin/sandbox/linux.rs:376` ioprio_set/move_pages/migrate_pages/kcmp/syslog/personality entries | Same direct syscall test covers each operation; no host process state is changed |
| 4. Truthful policy label | `src/vessel_reconstruction/ship_cad_worker.py:129` `linux-landlock-seccomp-deny-list` | `tests/test_linux_sandbox.py` command-selection assertion. `docs/plans/2026-11-12-linux-sandbox.md` records deny-by-default syscall allow-list as the next security step |
| 5. Child attestation | `src/vessel_reconstruction/ship_cad_worker.py:205` checks Seccomp 2 and NoNewPrivs 1; `:227` calls it before executor imports | Portable missing/valid-state tests; native `child_can_attest_kernel_controls_but_not_read_host_proc`; live `test_wrong_launcher_cannot_reach_executor` |
| 6. Broad roots/home | `rust-control/src/bin/sandbox/linux.rs:78` root rejection, `:101` getpwuid(getuid()) | `unsupported_and_broad_configurations_fail_before_payload` runs with HOME overwritten to scratch while trying to grant the account home; broad /opt task rejected |
| 7. Actual worker interface | `tests/test_linux_sandbox_live.py:50` | `test_live_run_denies_model_read_outside_task` uses production run(), native launcher, child main/attestation and receipt reader with a test-only injected model executor. The executor attempts an outside read and must receive PermissionError |

## Boundaries

- Architecture checks, mandatory Landlock/seccomp installation, descriptor closure, and no unsafe fallback are retained.
- Only `/proc/self/status` is readable for child attestation, not the procfs tree; native probe asserts `/proc/1/status` remains denied.
- Attestation is a minimum kernel-state check. Seccomp mode 2 and NoNewPrivs do not identify the complete policy or prove Landlock is installed. Exact policy evidence comes from the native launcher and live negative probes.
- The signal test never targets an actual supervisor or CI runner. A regressed filter must not turn a test into a host-kill primitive.
- Seccomp remains a deny-list. Migrating to a syscall allow-list with a deny-by-default final rule remains a follow-up; this patch does not claim otherwise.
- macOS still uses Seatbelt; Linux-only code and tests are cfg/skip gated.

## Verification

- Portable Python review tests: 11 passed, 4 Linux-only skips.
- Native Linux source and tests: cross-target type check and matching Clippy driver completed on Mac without warnings.
- Full Mac quick tier: exit 0. Python 1964 passed, 4 Linux-only skips, 84 deselected, 5 warnings (600.56 seconds). UI 266 passed. Rust formatting, Clippy and tests passed. Secrets scan: 0 findings across 1204 tracked text files.
- Pushed lane/linux-sandbox through 46971f6; live Linux and macOS CI pending.
