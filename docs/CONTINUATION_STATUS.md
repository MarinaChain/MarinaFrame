# MarinaFrame continuation status (post-0.4)

Started 2026-11-07 from `MarinaFrame_Claude_Code_Handoff_Pack.zip`.
This file is the resume point. It does not depend on chat history.

## Base used

- Repository: https://github.com/MarinaChain/MarinaFrame (cloned to `~/Documents/workspace/MarinaFrame`).
- Local branch `continue/v0.5`, created from PR #3 head `862c2e6c2f08cd805812a4d688a5f1407d5deb5f`.
- PR #3 (draft, stacked on PR #2) is unchanged. Nothing pushed. No merge or deployment.
- Recovered delivery `243beeee592ae0da27bc650a6a285486ac625e17`, its Git bundle and the 552 MB
  source/evidence archive are **not on this machine**. Only the handoff pack is present.
- Handoff pack: stored in `handoff/` (excluded through `.git/info/exclude`; it holds the private
  source inventory). All 8 files match `handoff/MANIFEST.json`.

## Decisions by the user

1. **Native macOS port** (2026-11-07), not a Linux container. Host: macOS arm64.
2. **Rotate three OpenCode Go keys by usage limits** (2026-11-07). See "Key rotation".
3. **Drop Tesseract OCR**; DeepSeek vision replaces it (first slice done: `offset_table_vision`,
   see `docs/VISION_TABLE_READING.md`).
4. **Cut unnecessary Python tests** after the port. See "Next steps".

## macOS port

Python packages are installed at the exact versions of the Linux hash locks, without hashes
(`work/macos-constraints.txt` is generated from `requirements-linux-py312.lock` and
`requirements-data-linux-py312.lock`). `pip check` is clean. Tesseract 5.5.4 from Homebrew was
installed only to prove the OCR code before its removal; it is no longer used.

| Change | Linux behaviour | macOS behaviour |
|---|---|---|
| Atomic no-replace publication (`transaction.rename_no_replace`) | `renameat2(RENAME_NOREPLACE)` | `renamex_np(RENAME_EXCL)`; same guarantee |
| Non-reaping exit check (`isolation.child_has_exited`) | `os.waitid(WNOWAIT)` | libc `waitid(WNOWAIT)` through ctypes |
| Process identity for PID-reuse checks | `/proc` start ticks | `ps` start time (1 s resolution) |
| Orphan-group ownership proof after restart | `/proc/<pid>/environ` token | `ps -E` token, same uid and pgid |
| `killpg` on a zombie-only group | succeeds | returns EPERM; treated as gone only if no live member |
| Label font | system DejaVu Sans | DejaVu Sans from locked matplotlib (`fonts.py`, bound into validator identity) |
| Server request deadline | timer shuts the socket | same; read timeout now 0.5 s later so the timer always wins (was a race) |
| Task root under a symlinked parent (`rust_worker.execute`) | n/a in practice | `/tmp` → `/private/tmp` broke `relative_to()` in validation; root is now resolved. Regression test added. |
| Peak RSS (`resources.peak_rss_kib`) | `ru_maxrss` in KiB | `ru_maxrss` in bytes; converted to KiB |
| Native resource profile | `linux_rlimit_process_group_v1` | `darwin_rlimit_process_group_v1`; both validators (Python and Rust) accept both |

**Known macOS gaps (not provided):**
- No parent-death signal (`PR_SET_PDEATHSIG`). If the controller is killed, a worker is bounded
  only by `RLIMIT_CPU`. The Linux-only test is excluded on macOS.
- No worker memory limit: macOS `RLIMIT_AS` is an alias of `RLIMIT_RSS`, which the kernel
  refuses to lower and does not enforce. The memory assertion in `test_runtime` runs on Linux only.

## Key rotation

- `rust-control/src/credentials.rs`: keys come from `OPENCODE_API_KEY`, `OPENCODE_API_KEY_2`,
  `OPENCODE_API_KEY_3`. Before each generation the provider worker reads every account's Go usage
  meters (`/zen/go/v1/usage`, no generation) and uses the key whose highest window is lowest.
  Accounts with any window not `ok` or at 100 % are skipped. One key: no usage read.
- The receipt field `credential_selection` records the slot and meter percentages, never a key.
  Old receipts without the field stay readable.
- `scripts/load_opencode_keys.sh` (source it) exports the keys from
  `~/.config/marinaframe/opencode-go-keys.txt` (mode 600). It prints no key.
- Live check 2026-11-07 (usage GETs only): slot 1 usable (max 46 %, weekly); slots 2 and 3 at
  monthly 100 % (`rate-limited`).
- The Python `agent_provider.py` was removed in 0.5; only the Rust provider worker remains.

## Verification matrix (macOS arm64, Python 3.12, Rust 1.99.1)

See the commit message of the port commit for the final run. Logs: `work/*-3.log` (not tracked).

## Tesseract OCR removed (done)

Removed `table_ingest.py`, `model_proposals.py`, the `offset_table_ocr` pipeline branch, the
OCR resource budget, the OCR benchmarks (`proposal_experiment`, `archived_table_experiment`,
`prepare_archived_table`), their tests, `TESSDATA_PREFIX` from both worker environments and
`tesseract-ocr` from CI. New specs with `input_mode: offset_table_ocr` are rejected
(`unsupported_input_mode`). `run_record.py` still reads the value so archived OCR runs verify.
Homebrew Tesseract can be removed with `brew uninstall tesseract`.

## Vision table reading, first slice (done)

New input mode `offset_table_vision` (not the old OCR semantics). Python
`table_vision prepare` writes hash-bound cell crops; the Rust command `marinaframe read-table`
sends them through the provider worker (`purpose: table_transcription` on the existing
`ProviderInput`/`Receipt`); the batch pipeline binds receipts to recomputed crops, parses strict
feet-inches-eighths tokens and blocks on any doubt. The reading record is captured in the run
and verified. Live check on a synthetic 20-cell table: 6 requests, all completed, 20/20 exact
tokens, reported cost 0.0 USD (Go). Design, limits and out-of-scope items:
`docs/VISION_TABLE_READING.md`. Not wired into the live controller loop.

## Finalization guards ported to Rust (done)

`rust-control/tests/finalization_guards.rs` drives the real Rust finish path over the real
worker protocol. `tests/rust_controlled_worker.py` runs real `DomainTools` (inspection,
selection, native build, STEP export); only the native audit result is injected. One prepared
task is built once per run and copied per test (about 70 s for the file).

| Ported Python Harness test | Rust test |
|---|---|
| cached failed audit, then finish | `failed_audit_stays_failed_when_cached_and_finished` |
| restart, then finish on cached failure | `restart_finalization_does_not_promote_failed_cache` |
| permissive envelope over failed contract | `permissive_envelope_cannot_override_failed_contract` |
| selection race at predicate / event commit (2 files) | `selection_is_excluded_after_the_passing_predicate`, `..._until_the_review_ready_commit` |
| cancellation after passing predicate (2 files) | `cancellation_after_passing_predicate_prevents_review_ready_commit` |
| elapsed deadline after predicate (2 files) | not ported: the Rust controller has no task wall-clock deadline |

Mutation check (2026-11-07): accepting any well-formed audit at finish fails the 3 failure-path
tests; removing the domain guard fails both race tests; removing the pre-commit cancellation
check fails the cancellation test. The controller has a `cfg(test)`-only hook
(`FINALIZATION_HOOK`) for these interleavings; release builds contain none.

Rust is stricter than the Python predicate: `validation::ready` re-verifies the immutable run
manifest, so the old fabricated-build fixture cannot pass it.

## Rust validation matrix (done)

`rust-control/tests/validation_matrix.rs` (15 tests, about 150 s) covers 16 of the 18 matrix
rows in `docs/RUST_VALIDATION_MATRIX.md`, with a real passing build and a real failing build
(`tests/rust_matrix_worker.py`; the failing build raises the CAD bound in its build subprocess
only, and the unmodified audit fails it). Each guarded check was mutated once to prove the tests
fail without it.

**Open gaps (not fixed):**
- `audit_implementation_sha256` is checked for format and for equality with the worker's own
  context only. A worker that reports a different well-formed value consistently is accepted.
  Closing it needs a controller-pinned value (a design change).
- No Rust test for stale render observations.
- Removing `cancelled_before_finalization` alone fails no test: earlier cancellation checks shadow it.
- The controller takes `domain/lock` twice in a row; a process forked by another thread in
  between can fail the second take (`domain_operation_in_progress`). The Rust tests run serially;
  single-process production use cannot hit it.
- The Linux x86_64 rerun of this branch was stopped by the user's choice; GitHub CI covers Linux.

## Next steps (resume here)

1. **Retire the legacy path** (done): removed `agent_harness`, `agent_cli`, `agent_review`, `agent_provider`, `server`, `jobs`, `review`, `web/`, their tests and the CI/installed-smoke steps. The CLI keeps `reconstruct` and `verify`. The 0.3 probe is recorded in `docs/HISTORICAL_VALIDATION_PROBE.md`.
   The three benchmarks that used the Harness (`live_harness_pilot.py`, `reaudit_preserved_native_run.py`, `v04_control_parity.py`) were deleted; they are in Git history at `19afbeb`.
2. Table reading: first slice done (`docs/VISION_TABLE_READING.md`). Next: a degraded/scanned synthetic table set with abstention
   counts, then (only with provider-transfer permission) an authentic table.
3. Keep data-pipeline and benchmark tests while roadmap steps 5–6 (licensed data, new evaluation)
   use them.
4. Decide whether to pin the audit implementation identity in the controller (gap above).
5. Step 3 (semantic/local geometry accuracy), first pass done: `docs/GEOMETRY_ACCURACY_V05.md`.
   One narrow source change kept (boundary ordinate bounded by touching boundary-row ink); one
   reverted; two rejected by falsification. No documented failing gate passes. Next: obtain the
   sealed final-12 tangency generator/reference, then continue with step 4.
