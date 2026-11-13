# Port Landing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide private identity checks, neutral source intake and portable native calculation bindings.

**Architecture:** A standard-library Python scanner checks tracked paths and contents without printing matched text. An offline intake tool transforms a private source tree into a new output directory, scans it, and publishes only clean output. A small C ABI library has C, Rust and Python tests, independent of desktop dependencies.

**Tech Stack:** Python standard library and pytest; C99/CMake/CTest; Rust FFI; GitHub Actions.

## Scope and review

Only lane-owned new modules, identity cleanup in current files, and CI wiring change. No history rewrite, pilot, holdout or sealed data access. Do not edit PRD or ROADMAP; report any blocked cleanup there to the PM. Private list and mapping values never enter tracked files or diagnostics. Synthetic tests use invented tokens only. Do not call original programs.

Architecture PASS: standalone kernels avoid coupling to other lanes. Quality PASS: redacted diagnostics, exact symbol mapping, path and collision checks, fail-closed staging. Coverage PASS: negative and positive scanner/intake tests plus all three ABI callers. Performance PASS: one tracked-tree pass; no extra dependencies.

## Gates (fixed before checks)

- G0: baseline `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` passes, with lane-local `CARGO_TARGET_DIR=target` and the main interpreter passed inline. Record any pre-existing failure; do not change thresholds.
- G1: synthetic denied phrases fail regardless of punctuation/case; `cs:` entries match whole words with case; missing lists warn and pass identity checks; native long addresses and 64-hex hashes fail unless explicitly allowed. Tracked path names and binary bytes are checked. No private values or matched source lines appear in diagnostics.
- G2: synthetic intake renames symbols and filenames, strips contaminated comments, and emits clean compilable C. It rejects residual identities, links, invalid mappings, overlapping paths, output replacement and output collisions. No partial output on failure. Input and mapping remain unchanged.
- G3: sample kernel computes rectangular volume (m3); finite nonnegative dimensions required; overflow, non-finite input and null C pointers return errors without replacing output. C, Rust and Python callers pass locally. CI runs these callers on macOS arm64, Linux x64 and Windows x64; remote results remain pending until actually observed.
- G4: scan the whole tracked tree using the external list; zero current-file hits after neutral edits. Report every file changed to remove identities. If protected PM files contain hits, stop that edit and request PM action.
- G5: final quick tier, focused tests, CTest, Rust binding tests, Python binding tests and diff whitespace check pass before push. Push only `lane/port-landing`; no merge. Name CI secret `MF_IDENTITY_DENYLIST`; do not set it. Inspect then remove only this lane's `target/` as the last step.

## Task 1: Scanner

Create `scripts/check_identity.py`, `scripts/identity_allowlist.json`, `tests/test_identity_check.py` and identity CI workflow. Write negative tests first; run the focused test and record expected missing-module failure. Implement list parsing from `MF_IDENTITY_DENYLIST` and `MF_IDENTITY_DENYLIST_FILE` (comment lines ignored); normalized phrase and case-sensitive whole-word rules. Use git tracked paths by default and explicit tree scan for intake. Allowlist only native fingerprints by path, kind and exact value; do not allow identity exceptions. Reject unreadable or linked tracked content safely. Log counts, rule categories and line numbers, never matched names, paths or snippets.

## Task 2: Intake

Create `tools/cleanroom/intake.py`, package markers and `tests/test_cleanroom_intake.py`. Private mapping is a JSON object from original C identifier to neutral C identifier outside the repository. No execution of recovered source. Token-aware replacement must not modify substrings or strings; contaminated comments are removed without changing line structure. Reject remaining identities in strings or code. Validate the output before an atomic rename from adjacent staging. Run focused tests including synthetic output compilation.

## Task 3: Native kernel

Create `kernels/CMakeLists.txt`, `kernels/include/mf_kernels.h`, `kernels/src/volume.c`, `kernels/tests/test_volume.c`, `kernels/python/mf_kernels.py`, `kernels/tests/test_python.py`, `kernels/rust/Cargo.toml`, `kernels/rust/build.rs`, `kernels/rust/src/lib.rs`. Standalone Rust crate excluded from the root workspace by its own workspace declaration. Build script invokes CMake and links the same C source as a static library; Python loads the shared library from an explicit path. Add a three-runner kernel matrix to `.github/workflows/native-targets.yml` without expanding the desktop app's platform claims.

## Task 4: Integration and delivery

Read scanner findings in redacted form. Make neutral prose edits without changing meaning; list paths here. Write `kernels/README.md` for ABI, bindings, private inputs, CI secret and pending remote gates. Stage intended files before final tracked-tree scan. Run G5, record counts and caveats here, commit and push. No CI polling.

## PM decision before final run (2026-11-13)

The PM defined the binary identity policy explicitly before the final run. This records a PM policy decision, not a widened numerical gate. G4 still requires zero findings under the policy.

1. UTF-8 text files and all file paths/names retain all rules unchanged.
2. Binary files use only case-insensitive denylist entries of at least six characters after normalization. Match raw bytes and any extractable text layer already read. Skip short and case-sensitive binary entries; print the skipped entry count only, never tokens.
3. `kernels/` and every intake output must contain text only. Any binary file fails the check, even if no denylist is set.
4. Add synthetic regressions for binary rule filtering, raw-byte matching, skipped counts, unchanged path/text rules and native/intake binary refusal. Then rerun full tracked-tree G4, focused/native checks and the final quick tier before commit/push. Remote platform results remain pending until observed.

## Results

Gate definitions committed before checks in `f9e5b34`.

- G0: quick tier completed with exit 0 (background task `b0ws3rx5m`, log `/tmp/port-landing-baseline.log`). Root Rust formatting, clippy and Rust tests passed. Python: 2552 passed, 4 skipped, 92 deselected, 5 warnings. UI: 275 passed, zero failures. Bounded secret scan: 1343 tracked text files, zero findings. This baseline run started before implementation; a stable-source final run remains pending.
- G1/G2: initial tests failed because implementation files did not exist. Current focused suite: 13 passed. Includes seeded CLI rejection with redacted output, phrase normalization, whole-word case, fingerprints, exact allowlist, binary strings, symlink refusal, synthetic intake compilation, mapped includes, residual strings, output collisions, unchanged private mapping, overlapping paths and unsupported syntax refusal.
- G3 local macOS arm64: CTest 1/1 passed; Python binding 2/2 passed; Rust binding 2/2 passed; standalone Rust clippy passed. Remote macOS/Linux/Windows matrix is configured but not run or observed. Rust is usable as an optional path dependency; no edits to app/core or rust-control.
- G4 FAIL: latest full tracked-tree run reports 66 binary-string findings after prose cleanup. Short case-sensitive tokens coincide with random printable runs in compressed images, font, mesh and archive bytes. Rules are not weakened and identity exceptions are not added. Assets are not rewritten or removed. PM decision is required on the binary acceptance policy; no claim of a clean full-tree scan. Diagnostics contain only file ordinal, line and category. No private identities enter logs or this report.
- Identity removal files (complete list): `docs/plans/2026-11-11-run-view-focus.md`, `docs/plans/2026-11-12-design-from-scratch.md`, `docs/research/2026-11-09-uiux-research.md`. Changes replace product-specific references and links with neutral method descriptions. PRD and ROADMAP are unchanged.
- G5: focused tests and whitespace checks pass; final quick tier, implementation commit, push and target cleanup are pending. Founder must set repository secret `MF_IDENTITY_DENYLIST`; this lane has not set it.

Review refinements: fail closed on raw literals and line splices; map include filenames alongside renamed headers; keep private scan diagnostics redacted. All binary matches remain reported instead of changing rules after observing results.

## Resume point

G0 finished with exit 0; counts are recorded above. Await the binary identity-policy decision, then run the final quick tier on stable source with the same main interpreter and lane-local target. Re-run C/Rust/Python and focused tests. G4 remains blocked on binary policy; do not silently waive it. Do not push a success claim or merge. Commit/push only this branch with explicit failed-gate notes when permitted by the lane's delivery policy. After the final push inspect and remove only this lane's `target/` as the last step. All work stays in `.claude/worktrees/port-landing` on `lane/port-landing`.
