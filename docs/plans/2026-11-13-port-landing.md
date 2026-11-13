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

## Results

Not run yet. Gate definitions committed before checks.

## Resume point

Start G0 baseline, then Task 1 negative tests. All work stays in `.claude/worktrees/port-landing` on `lane/port-landing`. Keep this section current after each checkpoint.
