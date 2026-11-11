# Windows CAD Sandbox Design and Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Contain model-written CAD code on Windows x86_64 and arm64 without elevation, with the same file, network, trust, and stop policy as the macOS worker.

**Architecture:** A trusted native Rust launcher creates a capability-free Less-Privileged AppContainer (LPAC) and places its Python process in a private Job Object before any child instruction runs. Explicit file ACLs grant read access to declared inputs and the worker runtime, and write access only to the fresh run output tree. Trusted controllers and deterministic CAD remain outside the model-code resource-limited job.

**Tech Stack:** Rust `windows` (windows-rs), Win32 process attributes, LPAC tokens, NTFS ACLs and mandatory labels, Job Objects; existing Python/CadQuery/OpenCascade worker.

---

## 1. Decision and scope

**Recommend LPAC + explicit per-run ACLs + an unnamed Job Object.** Use Windows' built-in AppContainer network isolation with **no network capabilities**, not app-installed firewall rules. Do not use a restricted token or low integrity alone as the sandbox. Do not add an elevated service, driver, Windows Sandbox dependency, VM, or UAC prompt.

This is a **design only**, not a claim that Windows model-code execution is safe today. Keep the current Windows refusal until every release gate below passes on native x86_64 and native arm64. Unsupported systems fail closed. Initial product baseline: supported Windows 11 desktop releases on local NTFS; Windows Server GitHub runners provide additional coverage, not desktop parity.

**Critical feasibility gate:** A normal `CreateAppContainerProfile` creates writable state beneath the real user's profile. That violates the literal policy, even if `HOME` is changed. Prototype a fresh SID derived with `DeriveAppContainerSidFromAppContainerName`, launched without creating a persistent profile. Prove that launch works and that neither profile storage nor a registry/COM broker supplies additional writable authority. The API reference documents SID derivation, but does not establish that this profile-less launch is a supported complete sandbox. This is an open question, not an assumed guarantee. If it cannot meet the policy, keep Windows execution disabled and return for a revised design; do not silently permit an AppContainer private profile.

Threat model: model code can call native APIs through Python extensions or `ctypes`, corrupt its outputs, start threads, and attempt process/file/network escape. It is not trusted because the current CAD interface is structured JSON. Kernel compromise, a malicious administrator, and a malicious same-user host process that changes ACLs or tampers with the trusted runtime are outside this boundary. Input parsers and trusted deterministic workers do not become sandboxed merely by using supervised spawn. `engineering_approved` stays false.

## 2. Existing source and policy anchors

Read against repository HEAD `fc5c780` before writing this design:

| Source | Current behavior and implication |
| --- | --- |
| `src/vessel_reconstruction/ship_cad_worker.py:20-74` | Seatbelt deny-default; only Python executables may execute; declared runtime and task are readable; only `task/work` is writable; parent metadata and selected OS runtime paths are readable. Windows needs a bounded OS-loader allowance too, not permission to read all of `C:\\Windows` or the user profile. |
| `src/vessel_reconstruction/ship_cad_worker.py:80-139` | Fresh task, read-only input/profile, protected host receipt, bounded no-follow result reader. Non-macOS fails before execution. Preserve this contract; POSIX result-reader calls need a Windows implementation. |
| `src/vessel_reconstruction/isolation.py:22-63,296-394` and `worker.py:17-45` | Model defaults: 120 CPU seconds, 4 GiB nominal memory, 128 MiB per file, 256 MiB output, 64 open files; trusted environment allowlist; model-only four-hour absolute security backstop. Memory enforcement is currently Linux-only. `wall_seconds=180` is a legacy setting, not permission to restore a 180-second default timeout for deterministic CAD. |
| `rust-control/src/supervised.rs:1-40,178-305,344-429` | Single spawn boundary, clean environment, Unix sessions/process groups, drop cleanup and descendant cleanup even after leader exit. Unix imports and process-group APIs need platform separation. No default total CPU/wall limit for own code. |
| `src/vessel_reconstruction/part_revise.py:433-454,481-505` | Trusted revision worker invokes the inner sandbox; currently explicitly macOS-only. A Unix SIGTERM handler is not a Windows cancellation mechanism. |
| `rust-control/src/part_revision.rs` and `app/core/src/part_revise.rs:479` | Revision orchestration must retain one supervised path rather than add an app-specific Windows launcher. |
| `tests/test_ship_cad.py:151-196,253-315` | Real CAD and direct OS denial probes; tests must reach the forbidden operation, not pass on failed Python initialization. |
| `.github/workflows/ci.yml:302-331`, `.github/workflows/ci-watch.yml:21-47` | Required macOS probes exist; Windows portability watch uses `windows-2022` and is not evidence of a Windows security boundary. |
| `docs/plans/2026-11-08-w13-ship-cad.md`, `docs/CONTINUATION_STATUS.md:333-345`, `docs/OPERATIONS.md:7,78` | OS containment is distinct from resource isolation; unsupported model execution remains closed. |
| `tasks/lessons.md:3-11,38-42,227` | Model-only caps, untrusted progress, positive operation controls, no skipped required worker tests, and proof that all descendants stopped. |

## 3. Candidate mechanisms and privilege requirements

| Mechanism | What it gives | What it does not give | Admin requirement / decision |
| --- | --- | --- | --- |
| Ordinary AppContainer | Token-based file, object, process and network isolation; capability-driven access; low integrity | Ambient access via `ALL APPLICATION PACKAGES`; private profile storage; not a path allowlist by itself | Desktop `CreateProcessW` with security capabilities needs no elevation. Reject as the final boundary; prefer LPAC. |
| **LPAC** | Opts out of ordinary `ALL APPLICATION PACKAGES` access using `PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY`; supports narrow package-SID ACLs | Still has OS resources accessible to restricted packages; capabilities and ACLs can broaden authority; profile-less behavior needs proof | No elevation for creation from a normal user process. Selected, with empty capabilities and explicit release gates. |
| Restricted token | `CreateRestrictedToken`, disabled privileges/SIDs, restricting SID access check | Ordinary user read access can survive an incomplete design; no independent network denial, namespace isolation, or process-tree resource policy | Restricting one's own token needs no admin. Avoid a `CreateProcessAsUserW` path that might require privileges. Not selected as a second custom token layer: LPAC already supplies the relevant token boundary. |
| Low integrity / MIC | Prevents many writes to higher-integrity objects; limits UI interaction | **Does not prevent reading user documents or using the network**; low-labeled shared locations can remain writable | Lowering one's token and labeling owned output can be done without elevation; no relabeling of system/user trees. Defense in depth only. |
| **Job Object** | Aggregate resource accounting/limits, process cap, unbreakable ordinary child membership, kill-on-last-handle-close | No file/network isolation; service-brokered process creation is not automatically part of the job | Creating/configuring a private job for owned processes needs no admin. Selected; no breakaway flags. |
| Custom WFP filters / Windows Firewall rules | Can block traffic at filtering layers | Not a file or process sandbox; policy installation adds machine-global state and cleanup/privilege complexity | Default WFP filter-add rights are not granted to an ordinary user. Requires elevation or prior privileged delegation; reject. Merely opening a BFE session is not filter-install permission. |
| **No AppContainer network capability** | Windows network isolation denies network authority without installing rules | Not proof against a pre-existing loopback exemption, inherited connected handle, or a broker that forwards requests | No admin. Selected; no `internetClient`, `internetClientServer`, or `privateNetworkClientServer`, no exemption, no broker. Probe IPv4/IPv6 and loopback. |

No selected setup operation may request elevation, enable `SeDebugPrivilege`, modify global firewall policy, loosen a user's existing ACLs, or install a service. On access denial, fail the launch rather than request admin rights.

## 4. Mapping the policy to enforcement

| Policy item | Enforcement | Acceptance gate |
| --- | --- | --- |
| No network | LPAC empty capability list; unique per-run identity; no loopback exemption; no inherited socket or network-capable RPC broker | Actual TCP connect, UDP send, bind/listen, IPv4/IPv6 loopback and non-loopback denial. Parent listeners/endpoints must prove reachable in unsandboxed controls. Test DNS activity separately; a failed external route is not evidence of isolation. |
| Read-only declared inputs | Host stages fresh regular-file copies; package SID receives only read rights; protected DACL; child cannot change parent ACL or replace directory entries | Read exact input bytes; fail create/write/rename/delete/ACL-change in input and task parents. Never grant runtime/input `WRITE_DAC`, `WRITE_OWNER`, `DELETE`, or parent `FILE_DELETE_CHILD`. |
| Read-only worker runtime | Staged architecture-matched Python, source, DLLs and extensions; package-SID read/execute ACEs only; approved OS loader resources | Python initialization, native CAD import/export succeed; attempts to overwrite `.py`, `.pyd`, DLL and executable fail. No runtime read grant on the complete install parent or profile. |
| Write only run output | Grant package SID write/create/delete only in fresh `task/work`; low mandatory label with no-write-up where required; do not permit label/ACL changes outside output | Positive output write/rename; forbidden writes in sibling runs, input, runtime, real temp, public low-integrity folders and AppContainer profile. DACL + MIC, not environment variables, enforce this. |
| No user profile access | No profile-wide ACL grant, no broad capabilities; profile-less identity gate; runtime and input copies never depend on user-site Python | Host plants random canaries in real home, Documents, AppData and another run. Native opens fail, including paths obtained through Known Folder APIs. Reject launches with a runtime/input root covering the home directory. Declared copies under output are not authority over original files. |
| CPU / memory / process caps for model code only | Separate inner job: CPU budget, aggregate commit cap and active process cap; job configuration lives in trusted Rust | Small-budget CPU and memory fixtures stop; second process creation fails in production configuration. Own-code fixtures outlive these model budgets. |
| Kill whole process tree on stop | Atomic job assignment at creation; `TerminateJobObject`; kill-on-close; child never receives job handle | Cancel, stall, leader exit, setup error and supervisor crash leave zero active job processes and no surviving PID/birth-identity canaries. |
| Fail closed | All launch attributes, ACLs, limits, identity checks and runtime checks must succeed before resume; RAII cleanup | Inject failure at each setup step; marker proving model entry must remain absent. Missing Windows/worker features are errors, never skips in required jobs. |

LPAC is not an arbitrary path-filter engine like Seatbelt. Audit the effective OS read surface, including `ALL RESTRICTED APPLICATION PACKAGES`, and bound it to required system runtime resources. If ambient grants allow undeclared user data or writable locations, this design does **not** meet policy on that system. Do not solve it by recursively changing unrelated host ACLs. Reject the configuration and keep execution disabled.

## 5. Launch and lifecycle design

### 5.1 Trusted layout and ACL preparation

1. The host creates a fresh task and separate protected receipt/control directory. Layout remains `task/input.json` (read-only), `task/work/` (writable output, progress and temp), and host-only receipt. Runtime staging is a separate read-only tree. Never accept an existing output directory.
2. Use a random per-run AppContainer moniker and derive its SID. Do not reuse an identity across runs. Do not call `CreateAppContainerProfile` in the recommended strict path. Query token identity and effective access in the pre-model native probe.
3. Stage declared input copies and runtime files without following reparse points. Reject UNC, mapped network drives, device paths, alternate data streams, untrusted hard links, junctions and reparse points in all path components. Use local NTFS, stable directory handles and file identities; string canonicalization alone is insufficient. Hold trusted parents against replacement. Do not modify original user documents or their ACLs.
4. Build protected DACLs on owned staging trees; retain required host/SYSTEM access and add only the per-run SID. Use file/directory-specific rights, inheritance flags, and traverse-only ancestor grants where needed. Do not grant ancestor listing or deletion just to reach a leaf. No grants to `Everyone`, `ALL APPLICATION PACKAGES`, or a shared capability on user data.
5. Apply a low mandatory label only to the owned writable output tree as required by MIC. Do not add write ACEs to a medium-integrity object and assume that is enough. Read back security descriptors and test effective access. Preserve task parent protection against output rename/reparse attacks.
6. First prototype may copy the runtime per launch for simple authority accounting. Optimize later with an immutable, versioned runtime and carefully managed per-run read ACEs, only after concurrency and ACL removal tests. No hard-link shortcut from a mutable user installation.

### 5.2 Start suspended, in the job, with the LPAC token

The native launcher, not Python startup code, installs the boundary:

1. Create an **unnamed**, non-inheritable Job Object. Set a host-only DACL; do not expose its handle or a named job that model code can open.
2. Set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, `JOB_OBJECT_LIMIT_JOB_MEMORY`, `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`, and the CPU budget policy before adding a process. Never set `BREAKAWAY_OK` or `SILENT_BREAKAWAY_OK`.
3. Build `STARTUPINFOEXW` attributes: `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` with the fresh SID and zero capabilities; `PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY` with `PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT`; `PROC_THREAD_ATTRIBUTE_JOB_LIST` for atomic job membership; and `PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY = PROCESS_CREATION_CHILD_PROCESS_RESTRICTED` in production. The child policy reinforces the one-process cap; test-only descendant fixtures omit it.
4. Call `CreateProcessW` with an explicit absolute `lpApplicationName`, correct Windows argument quoting, `EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT`, and an explicit environment block/current directory. Use atomic job-list assignment: a create-suspended-then-assign-only design leaves an orphan if the supervisor dies between those operations. If the job-list attribute fails or nested job constraints prevent it, fail closed; do not retry unsandboxed or break away from the runner's job.
5. Prefer no inherited handles. If stdout/stderr pipes are needed, use `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` to inherit only those specific write ends (and required null stdin); never the job, host files, tokens, sockets or broad IPC handles. Bound/drain logs in the host. Child pipes must not keep privileged control channels open.
6. While suspended, check `TokenIsAppContainer`, `TokenAppContainerSid`, integrity, capabilities and `TokenIsLessPrivilegedAppContainer`; check job membership and configured limits. Any mismatch terminates the suspended process and closes the job.
7. Resume only after every check passes. A trusted initialization probe must complete Python startup, dependency loading and a small CAD operation before model code is accepted for that runtime version. Probe results are host-owned, not declarations in a worker-written JSON file.

Use a bundled isolated Python configuration (`python._pth` / equivalent tested bootstrap) and disable user site packages, `sitecustomize`, startup hooks, bytecode writes and untrusted current-directory imports. `-I` ignores `PYTHONPATH`; do not combine the current `-m vessel_reconstruction...` path with `-I` and assume it still imports. Test the actual bundle's trusted search path.

Environment: construct from an allowlist, not inherited `PATH`. Keep only required Windows loader values such as a validated `SystemRoot`, fixed runtime paths, numerical thread settings, and run identifiers. Point `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, and `TMP` at owned output subdirectories when needed. Remove credentials, proxy variables, arbitrary Python paths, and the real user's environment. These are compatibility measures, not file access controls. Known Folder APIs can ignore them, hence the profile probes.

### 5.3 Limits and Python descendants

- **CPU:** Preserve the model's configured 120-second budget. `JOB_OBJECT_LIMIT_JOB_TIME` is aggregate **user-mode** job CPU in 100 ns units, not total user+kernel time. Configure terminate-on-end behavior, not a notification-only action. In addition, the host polls aggregate `TotalUserTime + TotalKernelTime` accounting (including exited descendants) and terminates at the total CPU budget. Document bounded polling overshoot. A CPU-rate hard cap (`JobObjectCpuRateControlInformation`) can bound instantaneous consumption, but is not a substitute for a total CPU budget. Keep the four-hour model-only monotonic backstop and current bounded progress/stall policy in the trusted supervisor.
- **Memory:** Set `JobMemoryLimit` to 4 GiB for the initial policy; optionally also set a per-process commit cap. This is committed virtual memory, not RSS. The kernel can reject an allocation rather than kill the process; a caught `MemoryError` is possible. Host accounting and watchdog handling must produce a clear limit outcome and cleanup. Do not describe working-set limits as a hard memory budget.
- **Processes:** Set `ActiveProcessLimit = 1` for the initial CAD worker. OpenCascade/BLAS threads do not need child processes. This also avoids permitting arbitrary executable children, which would be weaker than Seatbelt's Python-only exec rule. If CAD requires Python subprocesses, do not simply increase the cap: add and prove an executable policy first. A separate test-only job with a small cap above one exercises descendant inheritance and teardown.
- **Inheritance:** Ordinary Python `subprocess` and `multiprocessing` children inherit the AppContainer token boundary and job membership. They must not receive stronger handles. Test token/SID/LPAC state again in children; deny attempts to select a stronger token, parent process or breakaway flag. Job inheritance does not cover work requested from an external service; expose no COM/WMI/process-launch broker or network proxy capability.
- **Other existing limits:** Job Objects do not directly replace POSIX per-file size and open-file-count limits. The 128 MiB file, 256 MiB output and 64-handle policies need explicit decisions. Host output-size polling has race/overshoot and is not a hard disk quota. Do not label it equivalent. If hard equivalents are required for release, this is an additional blocker; do not install an elevated quota/filter service. Bound host result/log reads regardless.

Trusted deterministic CAD and provider workers remain outside this resource-limited job. They can use a separate **lifetime-only** job (kill-on-close, no model CPU/memory/process caps). Ensure outer ownership still kills the inner worker when a revision controller stops or crashes. No default fixed total timeout is added to trusted work.

### 5.4 Stop, finish and recovery

`ProcessGroup` becomes a platform-neutral owned worker handle with Unix and Windows backends; preserve one spawn abstraction. Windows uses job/process handles, not console control events or `taskkill /T`. A trusted cooperative cancel channel may allow a short grace period, but forced job termination is authoritative and does not depend on Python handling SIGTERM.

On cancel, model stall/security cap, error, or natural leader exit, call `TerminateJobObject` and establish that `ActiveProcesses == 0` with `QueryInformationJobObject` before reading outputs or returning success. Completion-port messages are useful for prompt observation, but most are not guaranteed delivery: poll/query the job as the source of truth. Use a bounded cleanup wait; if cleanup cannot be established, return a containment error and do not publish outputs. Keep owned handles until cleanup completes. RAII closes the last job handle on host crash, triggering kill-on-close; the model must never hold a duplicate handle.

After quiescence, read artifacts with a Windows no-reparse reader, bounded lengths, regular-file checks and file identity checks relative to retained trusted roots. `FILE_FLAG_OPEN_REPARSE_POINT` on the final component alone does not protect intermediate directories. Reject reparse points throughout traversal; use handle-relative opens where needed. Do not follow output junctions, mount points, device names or alternate streams. Treat provenance and progress as untrusted JSON. Keep the current 2 KiB progress and 16 MiB result bounds and finite host-counted progress advances. Host receipts remain outside the child-writable tree.

Crash recovery records run ID, architecture, policy version, effective limits, SID and host-owned exit/cleanup evidence; do not kill by a stale PID alone. A job's last-handle-close semantics are the primary crash mechanism. Cleanup removes only this run's owned staging resources after quiescence; it does not sweep shared temp folders by age.

## 6. Rust API and crate plan

Use target-specific `windows` dependencies in `rust-control/Cargo.toml`, pinned through `Cargo.lock`; select the current compatible version at implementation time, not an untested version in this design. No new dependency on a third-party sandbox wrapper is needed.

| windows-rs feature / namespace | APIs and types |
| --- | --- |
| `Win32_Foundation` | `HANDLE`, `CloseHandle`, Win32 errors; wrap ownership in RAII and preserve last-error before cleanup. |
| `Win32_System_Threading` | `CreateProcessW`, `STARTUPINFOEXW`, `InitializeProcThreadAttributeList`, `UpdateProcThreadAttribute`, `DeleteProcThreadAttributeList`, `ResumeThread`, process waits and creation flags; restricted handle inheritance. |
| `Win32_Security`, `Win32_Security_Authorization` | `SECURITY_CAPABILITIES`, `GetTokenInformation`, token information classes, SID helpers, `GetSecurityInfo`/`SetSecurityInfo`, ACL/ACE construction, mandatory label support. `CreateRestrictedToken` is for comparison/probes, not the recommended spawn path. |
| `Win32_Security_Isolation` | `DeriveAppContainerSidFromAppContainerName`; `CreateAppContainerProfile` and `DeleteAppContainerProfile` only for feasibility comparisons/owned test cleanup, not normal strict launch. `GetAppContainerFolderPath` is available through `Win32_UI_Shell` for profile-storage probes. Confirm these namespaces in the pinned crate. |
| `Win32_System_JobObjects` | `CreateJobObjectW`, `SetInformationJobObject`, `QueryInformationJobObject`, `IsProcessInJob`, `TerminateJobObject`; extended/basic limits and accounting, end-of-job-time action, completion-port association. |
| `Win32_System_IO` | `CreateIoCompletionPort`, `GetQueuedCompletionStatus` where exposed by the pinned bindings. |
| `Win32_Storage_FileSystem` | `CreateFileW`, `GetFileInformationByHandleEx`, final-path and reparse-tag checks, file identities, controlled share modes. |
| `Win32_System_Memory` / security SID functions | Correct allocator-specific cleanup (`LocalFree`, `FreeSid`, attribute buffers). Never free a SID with the wrong allocator. |

Isolate unsafe FFI in a small Windows module with typed owners for process/thread/job handles, SID allocation, attribute-list storage and security descriptors. Keep SID/capability/attribute buffers alive through `CreateProcessW`. Use checked 64-bit budget conversions and `SIZE_T` bounds on both target architectures. No pointer-sized assumptions copied from x64 examples. If handle-relative traversal requires `NtCreateFile`, isolate it and review its support contract; do not substitute an unsafe string-only traversal to avoid that review.

Proposed source boundaries (not created in this lane):

- `rust-control/src/supervised.rs`: shared trust class, lifecycle and watchdog contract; gate Unix imports.
- `rust-control/src/supervised/unix.rs`: existing behavior, moved without policy changes.
- `rust-control/src/supervised/windows.rs`: lifetime-only Windows job backend.
- `rust-control/src/sandbox/windows.rs` and `rust-control/src/sandbox.rs`: LPAC, ACL staging, model-job limits and native launch contract.
- `rust-control/src/bin/marinaframe-sandbox.rs`: narrow trusted helper for standalone Python entry points if required; no arbitrary broker operations. Its parent-death/lifetime ownership must be tested too.
- `src/vessel_reconstruction/ship_cad_worker.py`, `isolation.py`, `worker.py`, `part_revise.py`: dispatch to that native boundary, remove Windows-incompatible setup only behind platform gates; no Python-created unconfined model process.
- `app/core/src/part_revise.rs`, `rust-control/src/part_revision.rs`: retain shared orchestration and error reporting; do not duplicate security policy in the app.

The desktop and standalone Python path must share the same native sandbox implementation. Any helper starts as trusted code and must install LPAC/job protections before model input is interpreted. It must not create a gap in the outer worker's lifetime job.

## 7. Test strategy and GitHub runners

### Required matrix

Add a **required security job**, separate from the current portability watch. Run native x86_64 on `windows-2022` and a supported Windows 11 x64 runner; run native arm64 on `windows-11-arm` if available to this repository, otherwise a dedicated GitHub self-hosted Windows 11 ARM64 runner. Verify current runner label availability at implementation time. Missing ARM capacity blocks arm64 release; cross-compilation or x64 emulation is not equivalent.

Use native Rust MSVC targets `x86_64-pc-windows-msvc` / `aarch64-pc-windows-msvc` and matching Python/CadQuery/OpenCascade/DLLs. An unavailable arm64 CAD wheel is a release blocker, not a reason to run the sandbox probes under an unrelated x64 interpreter. Architecture-neutral API design does not establish native kernel compatibility.

GitHub images can use an administrator account. Run security fixtures with a **non-elevated standard-user token**, assert no enabled administrative membership/privileges, and log only token facts, OS build, architecture and policy version. Test setup may provision a temporary ordinary test account on a disposable runner, but the sandbox invocation itself must use no elevated rights. Also run an unelevated desktop-account test outside CI. If CI cannot launch this account safely, fail the required job rather than claim an admin-token pass proves no-admin operation.

Native security probes need only Python plus the Rust helper. The real-CAD lane additionally requires the packaged runtime and sets `MARINAFRAME_TEST_PYTHON` and `MARINAFRAME_REQUIRE_WORKER=1`. No required lane may skip because the worker, LPAC attribute, job-list attribute, architecture, dependency or filesystem is missing. Never weaken ACLs to accommodate a runner job. Test nested runner-job compatibility explicitly.

### Fixtures and acceptance gates, fixed before runs

| Fixture | Required observation |
| --- | --- |
| Positive controls | Native probe and isolated Python reach a marker immediately before the tested operation. Declared bytes read correctly; output file and CAD export succeed. A child initialization failure is never a successful denial test. |
| Files/profile | Deny real home/Documents/AppData, sibling task, host receipt, undeclared file and broad runtime-parent reads. Deny input/runtime writes and deletion. Test mixed case, long paths, traversal, junctions, symlinks, hard links and alternate streams. Probe reads through Win32 and Python APIs. |
| Ambient authority | Enumerate candidate LPAC-accessible writable paths and probe private profile, registry, shared low-integrity temp, named pipes, COM/WMI broker launch and device namespaces. No undeclared user-data read or out-of-output file write may succeed. |
| Network | Controlled reachable endpoints: TCP connect and listen, UDP send/bind, IPv4/IPv6, loopback and non-loopback, plus DNS side-effect observation. Assert operation-specific denial, not timeout, import error or mere socket creation failure. Deny network-share paths too. |
| Token/inheritance | Record and assert LPAC/package SID/capabilities/low IL/job membership. In a test-only process-cap>1 job, Python child/grandchild retain the boundary; breakaway, token selection and privileged parent selection cannot escape. Production cap=1 rejects a second process. |
| Limits | Use small fixture limits (for example 1 CPU second, 128 MiB commit, one process) and controlled allocators/spinners. Validate kernel denial/accounting and cleanup rather than exact scheduler timing. Production limits are separately asserted from host configuration. A trusted deterministic fixture runs past those small budgets. |
| Stop and parent death | Stop a live worker, an exited leader with live descendants, a leader ignoring cooperative cancel, and the supervising host. A separate observer checks all recorded process identities are dead and the job has no active processes. Merely seeing the leader exit is insufficient. |
| Startup races | Inject failure after each ACL/job/attribute/create/validation step and kill the host during process creation. No model-entry marker and no orphan may remain; job membership is atomic. |
| Output reader | Planted reparse point, oversized/special file, malformed progress and fabricated counters cannot redirect host reads, block the reader or extend the security cap. No output is published while a child is live. |
| Concurrent runs | Separate SIDs cannot read/write each other's trees or reopen job/control handles. A failed run cannot remove another run's ACEs or staging tree. |
| Mutation controls | In disposable test-only configurations, deliberately grant a forbidden file ACE or network capability and show the corresponding probe becomes reachable/succeeds. Mutations never run model input and never ship. They prove tests exercise the permission under test. |

Proposed implementation-time commands, with the fixture names below created first:

```powershell
$env:MARINAFRAME_REQUIRE_WORKER = '1'
$env:MARINAFRAME_TEST_PYTHON = '<absolute native bundled python.exe>'
cargo test --locked -p marinaframe-control --test windows_sandbox -- --test-threads=1
& $env:MARINAFRAME_TEST_PYTHON -m pytest -q -p no:cacheprovider tests/test_windows_sandbox.py
& $env:MARINAFRAME_TEST_PYTHON -m pytest -q -p no:cacheprovider tests/test_ship_cad.py -k sandbox
```

Expected: all applicable security and real-worker assertions pass, **zero skipped required probes**, and no unowned live processes. Existing macOS sandbox and Unix supervision suites must continue to pass. The commands describe future implementation checks; none were run in this design lane, and no Cargo build is authorized here.

## 8. Risks, open questions and release blockers

1. **Profile-less LPAC:** Prove support and no private profile/registry write surface on every supported Windows build. A private AppContainer folder under home is still user-profile access. If proof fails, Windows remains unavailable under this policy.
2. **Ambient OS grants:** LPAC opts out of `ALL APPLICATION PACKAGES`, not every globally readable or restricted-package resource. Define the minimal system read surface and test it. Broad capabilities such as `registryRead`, `lpacCom`, or file access capabilities are not automatic fixes for loader failures.
3. **Python/native loader compatibility:** Python startup, OpenCascade, OpenMP and DLL search behavior can require filesystem/registry access. Resolve by bundling a minimal runtime or a narrow reviewed system allowance, not opening the profile, COM or the whole system drive.
4. **Network guarantees:** Confirm no-capability behavior across IPv4/IPv6, DNS and loopback; inspect exemption state and use fresh SIDs. Unknown or altered filtering policy is unsupported until probes pass. Custom WFP policy is not a no-admin fallback.
5. **Resource semantics:** Windows commit limits differ from POSIX address-space limits; job user-time differs from total CPU; polling overshoots. Agree and record explicit tolerances before implementation tests. Hard disk/file/open-handle equivalents remain unresolved and must not be advertised as provided by Job Objects.
6. **Process policy:** Initial process count is one. If CAD needs helper executables, revising the executable policy is a security change, not a performance switch. CPU and memory limits are aggregate over the inner job, not the app.
7. **Reparse/ACL races:** Protect intermediate directories and host result opens; avoid shared mutable staging. Same-user host tampering is outside the threat model, but model-created output links are inside it.
8. **Lifetime nesting:** Runner job restrictions and revision nesting can prevent job assignment. Fail closed. No `CREATE_BREAKAWAY_FROM_JOB` compatibility fallback. Crash/stop tests need an independent observer.
9. **ARM64 availability:** Native CAD dependency packaging and hosted runner capacity are separate from Windows API support. Keep arm64 disabled until both gates pass on native hardware.
10. **No-admin proof:** Successful launch from an elevated CI session is insufficient. All production operations must work under the ordinary token without privileged service installation or policy changes.

## 9. Review and implementation handoff

Plan-review result:

- **Architecture — PASS:** one native security boundary and shared supervisor; no machine-global firewall modifications or privileged service. Windows support remains gated, not presumed.
- **Code quality — WARN:** FFI ownership, ACL construction and reparse-safe traversal need narrow unsafe modules and explicit setup-failure paths. No implementation exists yet.
- **Test coverage — WARN:** the matrix above is specified, but no Windows probe has run. Profile-less launch, effective authority, native arm64 CAD and cleanup races are release blockers until demonstrated.
- **Performance — WARN:** per-run runtime staging and ACL walks may be costly. Begin with a correct prototype; do not add runtime caches or shared capability grants before isolation/concurrency tests.

**Resume point: design complete; no implementation started.** Next authorized lane starts at Task 1 below. Do not remove the current non-macOS refusal merely because the document exists.

### Task 1: Resolve the feasibility blockers before product changes

Files: add `rust-control/tests/windows_sandbox.rs` plus small trusted test probes under `rust-control/tests/fixtures/windows_sandbox/`; record outcomes in this plan. Add target-specific test dependencies in `rust-control/Cargo.toml` only when implementation is authorized.

1. Write failing standard-user tests for profile-less LPAC, empty capability networking, output-only ACLs and ambient profile access.
2. Build the smallest native test launcher with job-list assignment; use no CAD/model input.
3. Run on native Windows x64 and arm64. Record OS build, token facts, accessible OS surface and exact failures.
4. Stop if any policy item lacks enforcement. Revise the design before touching production dispatch. Commit test evidence only, without private paths or secrets.

### Task 2: Add the shared native boundary, test first

Files: the Rust modules in section 6 and `rust-control/tests/windows_sandbox.rs`.

1. Add failing lifecycle, inheritance, limit, handle-leak and failure-injection tests.
2. Separate Unix/Windows supervision with unchanged Unix behavior; implement native owned handles and lifetime-only Windows jobs.
3. Implement LPAC staging and atomic limited-job spawn; keep model dispatch closed until all tests pass.
4. Run platform suites and review the FFI/ACL boundary independently before committing.

### Task 3: Integrate and prove the real worker

Files: Python dispatch/call paths listed in section 6; create `tests/test_windows_sandbox.py`; update existing sandbox tests without weakening macOS expectations.

1. Add failing Windows standalone and desktop revision integration tests.
2. Route both through the same native helper/library; preserve host receipts and untrusted-result checks.
3. Package/test native runtime search paths, then run real CAD on both architectures.
4. Run stop/crash tests around the outer trusted revision worker and inner model worker. No orphan or extra caps on deterministic CAD are acceptable.

### Task 4: Make the security matrix required, then decide release support

Files: `.github/workflows/ci.yml`, `.github/workflows/ci-watch.yml`, `docs/OPERATIONS.md`, `docs/CONTINUATION_STATUS.md` and this plan.

1. Add required standard-user security jobs and native architecture checks with zero required skips.
2. Run positive, negative and disposable mutation controls; retain sanitized evidence.
3. Review every blocker in section 8. Enable Windows model execution only for configurations with all gates satisfied; otherwise retain explicit refusal.
4. Document tested Windows builds, architectures, dependency versions and precise resource semantics. Do not merge or enable support on the strength of cross-compilation alone.

## 10. Design-lane checks and sources

This lane changes only this document. No application implementation, Cargo build, Windows launch, or release enablement is performed. `make test-quick` includes Cargo clippy/test builds (`Makefile:18-32`), so the direct no-Cargo instruction takes precedence: run its Python, UI and secret-scan targets separately and report any failures. Document test outcomes below before committing. There was no `target/` directory at task start; do not create one for this design lane.

Primary references consulted on 2026-11-12:

- [Microsoft: Launch an AppContainer / LPAC](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer) — security-capabilities attributes, LPAC opt-out, dual-principal ACL checks, profile storage and network capabilities.
- [Microsoft: Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) — inheritance, nested jobs, breakaway, accounting, kill-on-close and notification caveats.
- [Microsoft: DeriveAppContainerSidFromAppContainerName](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deriveappcontainersidfromappcontainername) — SID derivation API/ownership; does not settle the profile-less launch question.
- [Microsoft: WFP access control](https://learn.microsoft.com/en-us/windows/win32/fwp/access-control) — default rights and why opening BFE is not permission to add filters.
- Implementation references to check against the pinned SDK: [process attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute), [job basic limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information), [extended limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information), [windows-rs](https://github.com/microsoft/windows-rs), [GitHub-hosted runners](https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners).

### Local check results

- `make python-quick ui-quick secrets PY=<shared project venv>/bin/python`: exit 0. Python: **1,953 passed, 84 deselected, 5 warnings**, 319.34 seconds. UI: **266 passed, 0 failed, 0 skipped**. Secret scan: exit 0.
- `git diff --cached --check`: no whitespace errors.
- Full `make test-quick` was not run because its Rust lint/test targets build Cargo artifacts, which this lane forbids. No Cargo command or Windows security probe ran. No implementation or release enablement is included.
- Resume at Task 1 under a separate implementation authorization; profile-less LPAC and native architecture gates remain open.
