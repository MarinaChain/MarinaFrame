# Linux Sandbox Implementation Plan

> **For Claude:** Use executing-plans to implement this approved plan task-by-task.

**Goal:** Run model-written CAD on Linux with the existing macOS policy and no unsafe fallback.

**Architecture:** Retain `ship_cad_worker.run` as the public interface. A Linux-only Rust launcher installs Landlock, seccomp and hard resource limits before executing the trusted Python worker. Keep macOS Seatbelt unchanged and reuse the existing supervisor for stop, output accounting, bounded progress checks and the model-only safety cap.

**Tech stack:** Rust/libc, Linux Landlock ABI 3+, seccomp BPF, POSIX rlimits, Python/pytest, GitHub Actions.

## Approval and resume point

2026-11-12: PM approved this design in conversation. The original uncommitted plan was lost when the worktree was removed. Restored here before implementation. Next: commit this plan, implement native launcher and tests, wire Python, run Mac quick tier, commit and push lane/linux-sandbox. Do not merge. Record evidence below.

## Options

1. Selected: native launcher with Landlock + seccomp + rlimits. No root or external sandbox package required.
2. Namespaces alone: insufficient filesystem/syscall policy and frequently unavailable.
3. Containers: unnecessary daemon/package and deployment requirements.

User/network namespaces are optional defense in depth where available; mandatory Landlock/seccomp controls never degrade. Avoid partial user-namespace credential changes. Preserve supervised PID/group identity.

## Policy table

| Policy | macOS | Linux |
|---|---|---|
| Network denied | Seatbelt deny-default | Architecture-checked seccomp denies socket/connect/bind and io_uring bypass |
| Declared inputs read-only | Task directory read rule | Landlock task read-only rule |
| Runtime read-only | Explicit interpreter, runtime and system libraries | Explicit interpreter, Python/runtime source and system library paths; no whole home/root grant |
| Scratch/output writes only | task/work write rule | Landlock write/create/remove/truncate rights only under task/work |
| Home/other files denied | No broad home rule | No broad home rule; explicit runtime within home permitted |
| Other program execution denied | Explicit interpreter executable | Landlock execute right only for interpreter |
| Process limits/escape | Seatbelt process policy | seccomp denies process creation, group/session escape, namespace changes and cross-process operations |
| CPU | Model-only CPU rlimit | Same hard CPU limit |
| Memory | macOS cannot enforce RLIMIT_AS | Hard RLIMIT_AS |
| File/descriptor/core limits | Existing limits | Same limits before exec |
| Stop | Supervisor process-group kill | Same group kill; deny group/session escape |
| Progress | Bounded trusted watchdog | Unchanged; no own-code wall timeout |
| Missing controls | Refuse launch | Clear setup error before model execution; no fallback |

## Launch sequence and security checks

1. Parent validates fresh task/work, writes input outside writable work and selects platform command. Missing launcher fails closed.
2. Linux launcher parses bounded configuration and canonical paths. Reject broad runtime roots, invalid path kinds and runtime/write overlap. Never invoke a shell.
3. Close inherited descriptors, null stdin, change cwd to work. No inherited host directory, file or socket handles.
4. Set parent-death handling, no-new-privileges, and hard model-only CPU, memory, file, descriptor and core limits.
5. Query Landlock ABI; require ABI >=3 for REFER/TRUNCATE coverage. Handle all supported filesystem rights, including newer applicable rights. No /proc or broad /etc grants.
6. Add read-only task/runtime rules, work write rights, interpreter-only execute right and narrowly scoped device exceptions. Symlinks must not grant their outside targets.
7. Install seccomp BPF with architecture and x32 checks. Deny network, io_uring, process creation, setsid/setpgid, mount/namespace mutation, ptrace/process_vm/pidfd access, kernel/module/BPF operations and host signal operations. Return EPERM for prohibited operations.
8. Exec the declared Python interpreter into the trusted worker. Distinct setup failures must not become successful empty CAD outcomes. No model code before all controls succeed.
9. Reuse Python limits/environment, progress watchdog and result collection. Supervisor cleans the full group before reading output and writes receipt outside work.

## Failure behavior

No Landlock, ABI too old, no seccomp, rule installation failure, missing executable, unsupported architecture, invalid configuration or rlimit failure: fail closed with a specific setup error. Never retry unsandboxed. Keep credentials out of arguments/logs. HOME/TMPDIR point to work. Do not change macOS profile or deterministic own-code timing.

## Design review

- Architecture PASS: existing hostile-code boundary, no separate supervisor.
- Quality WARN: use named kernel constants and short helpers; minimize unsafe syscall surface.
- Security WARN: explicitly test inherited descriptors, alternate ABI, broad runtime grants, setup failure propagation and symlink escape.
- Coverage WARN: Mac cannot run Linux kernel tests. Linux CI must not skip mandatory supported-kernel checks.
- Performance PASS: bounded configuration, one setup per worker, no daemon or new polling.

## Tasks and checks

### 1. Native launcher and Linux tests

Files: `rust-control/Cargo.toml`, `rust-control/src/bin/marinaframe-sandbox.rs`, Linux-only implementation module, `rust-control/tests/linux_sandbox.rs`.

- Write Linux-gated direct interpreter probes first; assert a marker before each denied operation.
- Implement validated config, hard limits, descriptor cleanup, Landlock and seccomp helpers.
- Compile kernel implementation only under `cfg(target_os = "linux")`; other platforms refuse launcher use.
- Positive probes: runtime reads, work writes and interpreter launch.
- Negative probes: bind/connect, home reads, outside writes, input modification, symlink escape, other executable, process creation and group escape.
- Resource probes: CPU exhaustion, memory allocation, descriptor/file limits.
- Lifecycle probes: supervisor stop/group cleanup and setup failure before payload marker.
- Unsupported-kernel seam may force refusal only, never bypass controls.

### 2. Python integration

Files: `src/vessel_reconstruction/ship_cad_worker.py`, `src/vessel_reconstruction/part_revise.py`, related Python tests.

- Keep Seatbelt command unchanged on macOS.
- Select native Linux launcher explicitly, derive narrow runtime grants (not broad sys.prefix such as /usr), pass existing model limits.
- Remove obsolete macOS-only part-revision gate; unsupported platforms refuse.
- Surface launcher setup errors distinctly; preserve safe environment, output/progress paths and worker receipt behavior.
- Mock command selection and fail-closed behavior on Mac; skip live Linux tests cleanly there.

### 3. CI and delivery

Files: `.github/workflows/ci.yml`, this plan.

- Explicit Linux job builds launcher and runs live Linux policy tests with no required-feature skips. Add Python integration checks with launcher path configured.
- Run formatting/build and required quick tier on Mac. Every cargo command, including make subprocesses, uses shared target:

```sh
CARGO_TARGET_DIR=/Users/jonathanjie/Documents/workspace/MarinaFrame/.claude/worktrees/shared-target-sol MARINAFRAME_TEST_PYTHON=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
```

- Review policy and maintainability; record exact test outcomes and Linux/Mac limits here. Report DNS/infrastructure failures separately.
- Commit often with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push lane/linux-sandbox only, no merge.
- Never delete the shared Cargo target or other lanes' output. Work/write only in this worktree.

## Results

### Implementation checkpoints

- `f0dfbea`: restored plan committed before implementation.
- `b206fce`: Python platform selection and fail-closed receipts; targeted tests: 41 passed, 9 CAD tests deselected.
- `c604dee`: Linux-only native launcher, native policy probes, Python runtime/stop probes, and explicit Linux CI step.
- `734214e`: deny model-created symlinks, including protection for later host artifact consumers; test a trusted pre-existing symlink cannot escape.
- Linux x86_64 launcher and native tests cross-type-check successfully on this Mac using the installed Linux Rust standard library and an ignored minimal check harness under `work/linux-sandbox-check/`. Matching Clippy driver also completes without warnings. Full workspace cross-check needs a Linux C compiler for ring, unavailable here. These checks do not execute Linux kernel policy.
- First required quick-tier attempt passed Mac formatting, Clippy and Rust tests, then the tool killed the command after its 600-second allowance during Python tests. No test failure was reported before interruption. Re-run uses the tool's two-hour allowance; no production timeout was added.
- Final full Mac quick tier: **exit 0**. Formatting, Clippy and Rust tests passed; Python **1958 passed, 2 skipped (Linux-only), 84 deselected**, 5 warnings, 407.61 seconds; UI **266 passed**; bounded secrets scan **0 findings** across 1203 tracked text files. After final Linux-only syscall additions: cross-target source/probes and matching Clippy check passed again; Mac targeted Rust test binaries built (0 Linux tests selected), portable Python checks **5 passed, 2 skipped**; formatting/diff checks passed.
- Live Linux kernel/real-CAD behavior: pending Linux CI, cannot run on this Mac.

### Deployment and resume

Build `marinaframe-sandbox` with the controller. Set `MARINAFRAME_SANDBOX_LAUNCHER` to its absolute installed path, or install it beside the worker Python executable. Rust's Linux worker environment retains that trusted deployment setting for nested part revisions. Python does not pass it into model code. Missing launcher or kernel policy support refuses execution.

Landlock ABI 3 or newer, seccomp filters, and close_range are mandatory. Runtime grants come from Python sysconfig and explicit library/device paths, not the whole interpreter prefix. Model process/thread creation is denied; numeric library thread settings remain one. New syscall numbers >=449 are denied until reviewed. User namespaces are not entered because credential changes would invalidate existing same-uid supervisor identity/stop assumptions; a network namespace is attempted without credential changes and seccomp is required regardless of availability.

The Linux controller CI job builds the launcher, runs all native policy tests, then runs portable command-selection tests plus live Python stop/real-CAD tests. Live tests are excluded from generic Python shards without a launcher and skipped only on non-Linux. Required Linux features are never a skip condition. No local `target/` folder was created; the shared target is retained.
