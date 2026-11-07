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
3. **Drop Tesseract OCR**; DeepSeek vision replaces it (not yet implemented).
4. **Cut unnecessary Python tests** after the port. See "Next steps".

## macOS port

Python packages are installed at the exact versions of the Linux hash locks, without hashes
(`work/macos-constraints.txt` is generated from `requirements-linux-py312.lock` and
`requirements-data-linux-py312.lock`). `pip check` is clean. Tesseract 5.5.4 from Homebrew was
installed only to prove the current OCR code before it is removed.

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
- The Python `agent_provider.py` (legacy harness only) still uses one key.

## Verification matrix (macOS arm64, Python 3.12, Rust 1.99.1)

See the commit message of the port commit for the final run. Logs: `work/*-3.log` (not tracked).

## Next steps (resume here)

1. **Test cut, phase 1 (no code removal needed):** remove OCR tests with the OCR path
   (`test_table_ingest`, `test_table_pipeline`, `test_model_proposals`, `table_ingest.py`,
   `model_proposals.py`, the `offset_table_ocr` branch in `pipeline.py`) and historical experiment
   tests (`test_proposal_experiment`, `test_pixel_corridor_proposals`).
2. **Port the finalization guards to Rust first**: 5 Harness tests in `test_validation_cache` and 4
   in `test_validation_finalize_independent` are the only guards for the 0.3 cached-failure
   finalization defect on the Harness side.
3. **Then retire the legacy path**: `agent_harness`, `agent_cli`, `agent_review`, `agent_provider`,
   `server`, `jobs`, `review`, `web/` with their tests (~100 tests).
4. Keep data-pipeline and benchmark tests while roadmap steps 5–6 (licensed data, new evaluation)
   use them.
5. Then continue `handoff/MarinaFrame_Claude_Code_Handoff.md`, "Next work in order", from step 2.
