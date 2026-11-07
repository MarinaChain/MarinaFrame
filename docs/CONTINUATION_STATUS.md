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

**Audit identity (closed 2026-11-07):** the controller pins `audit_implementation_sha256` from the initialize receipt and `validation::ready` requires it. Tasks without a pin cannot finalize. Trust root: the worker at initialize.

**Open gaps (not fixed):**
- No Rust test for stale render observations.
- Removing `cancelled_before_finalization` alone fails no test: earlier cancellation checks shadow it.
- The controller takes `domain/lock` twice in a row; a process forked by another thread in
  between can fail the second take (`domain_operation_in_progress`). The Rust tests run serially;
  single-process production use cannot hit it.
- The Linux x86_64 rerun of this branch was stopped by the user's choice; GitHub CI covers Linux.

## Source acquisition, 2026-11-07

Downloaded with the user's approval into `work/sources/` (git-ignored; not committed, not
packaged). Every file matched the private inventory's byte size and SHA-256 exactly.

| Item | Vessel | Format, pixels | Bytes | Rights (inventory) |
|---|---|---|---:|---|
| `balclutha_ca54_s48` (Section at Frame 108) | Balclutha 1886 | TIFF, 9632 × 14434 | 1,201,246 | US public domain (NPS HAER) |
| `balclutha_ca54_s7` (Body plan, hull measurement table) | Balclutha 1886 | TIFF, 9632 × 14442 | 1,337,872 | US public domain (NPS HAER) |
| `monitor_nh50954` (General plan) | USS Monitor 1862 | JPEG, 1200 × 431 | 153,224 | US public domain, expired |
| `wapama_ca67_s5` (As-is lines, body plans) | Wapama 1915 | TIFF, 13600 × 17600 | 748,682 | US public domain (NPS HAER) |

Use: line identity and abstention work only. These sheets carry no reviewed whole-hull truth,
so they support no accuracy claim. Sending them to the DeepSeek provider is a separate
decision (inventory: `provider_inference: not_transmitted_by_data_worker`); none was sent.
Full-size TIFFs decode to several hundred MB in memory each.

## ALMA originals acquired, 2026-11-07

All six ALMA (1891) NPS Gallery originals downloaded to `work/sources/alma/` (736 MB,
git-ignored). Each matched the inventory byte size and SHA-256. Rights: local processing,
training and testing authorized; provider transfer and redistribution unresolved, so they are
not sent to any provider and not committed. Most useful: "Lines drawing and offsets" and
"Cross sections; sheet4".

## Candidate datasets: size estimates, 2026-11-07

The user states commercial-use licences are secured for all five. Provider transfer
(sending images to DeepSeek) is still decided per item. Not downloaded yet.

| Dataset | Size | Basis | Notes |
|---|---:|---|---|
| MiDShip (12,753 cargo-hold structures) | 430 GB | Hugging Face card total | About 34 MB per design; three subsets (6,020 random, 496 SGLD, 6,237 repaired) stored in batches. Does not fit the 31 GB free; needs a subset or an external disk. |
| R/V Gunnerus | about 1.4 GB | GitHub tree 316 MB + Rhino 396 MB + STEP 728 MB (Git LFS) | 15 production drawings (DWG/DXF/PDF), lines plan, 3D model. STEP import needs several GB of RAM. |
| HAER Wapama (22 sheets) + C.A. Thayer (38 sheets) | about 0.05–0.1 GB | Commons copies of HAER sheets are 0.7–1.3 MB each | loc.gov returned HTTP 403 to automated requests; use Wikimedia Commons copies as before. Rights checked per sheet. |
| Ship-D (30,000 hulls) | 0.32 GB | Harvard Dataverse file sum | Parameters and measures only. Meshes regenerate from the 45 parameters with the published code; rendered views about 0.3 GB per 1,000 hulls. |
| SIMMAN hulls (KCS, KVLCC2, DTMB 5415) | under 0.05 GB | IGES files of a few MB; inventoried DTMB 5415 files total 0.33 MB | Known IGES surface defects need repair. |

Everything except MiDShip totals about 2 GB, inside the 5 GB working target.

## Dataset acquisition, round 2, 2026-11-07

Downloaded with the user's approval into `work/sources/` (git-ignored; not committed, not sent to
any provider). Each folder has a `manifest.tsv` with bytes and SHA-256. Commercial-use licences
are confirmed by the user for these datasets; HAER sheets are additionally public domain.

| Folder | Content | On disk | Verification |
|---|---|---:|---|
| `gunnerus/` | shiplab/gunnerus at `8cd4683`: 15 production drawings (DWG/DXF/PDF), metadata, Rhino 3DM 415 MB, STEP 763 MB | 2.6 GB (LFS objects stored twice: cache + checkout) | LFS SHA-256 of both models matches the pointers |
| `shipd/` | Ship-D Dataverse files (249) + `code/` (GitHub, not executed) | 343 MB | 249/249 size and MD5 match |
| `simman/simman2008/` | Hull IGES: KCS (SVA), KVLCC1, KVLCC2, DTMB 5415 (two versions, one as DXF lines drawings) | 2.4 MB | No published hashes; SHA-256 recorded; no unsafe zip paths |
| `simman/dtmb5415_mathlab/` | 7 pinned DTMB 5415 reference files (MIT) | 0.3 MB | 7/7 match the inventory |
| `midship/` | 36 designs: 12 per subset, 4 per ship type; 12 with full 3D (`selection.md`) | 192 MB | 378/378 match HF size + SHA-1 or LFS SHA-256 |
| `haer/wapama/` | HAER CA-67: 21 of 22 sheets (sheet 8 not on Commons) | 36 MB | Commons size + SHA-1 |
| `haer/ca_thayer/` | HAER CA-61: 12 of 38 sheets (1, 5–14, 37); no lines plan or offset table on Commons | 12 MB | Commons size + SHA-1 |

Total under `work/sources/`: about 3.9 GB, inside the 5 GB working target; 26 GB free.
Missing from Commons: Wapama sheet 8 and 26 C.A. Thayer sheets. Later on 2026-11-07 the user
completed the loc.gov Cloudflare check in Arc, and the sheets were fetched through that browser
session (`manifest-loc.tsv` in each folder). Now held: Wapama 22 of 22, C.A. Thayer 37 of 38
(sheet 19 did not download).

## Next steps (resume here)

1. **Retire the legacy path** (done): removed `agent_harness`, `agent_cli`, `agent_review`, `agent_provider`, `server`, `jobs`, `review`, `web/`, their tests and the CI/installed-smoke steps. The CLI keeps `reconstruct` and `verify`. The 0.3 probe is recorded in `docs/HISTORICAL_VALIDATION_PROBE.md`.
   The three benchmarks that used the Harness (`live_harness_pilot.py`, `reaudit_preserved_native_run.py`, `v04_control_parity.py`) were deleted; they are in Git history at `19afbeb`.
2. Table reading: first slice done (`docs/VISION_TABLE_READING.md`). Next: a degraded/scanned synthetic table set with abstention
   counts, then (only with provider-transfer permission) an authentic table.
3. Keep data-pipeline and benchmark tests while roadmap steps 5–6 (licensed data, new evaluation)
   use them.
4. Optional: let the operator supply an expected audit identity (the controller pin is recorded from the initialize receipt; see `docs/RUST_VALIDATION_MATRIX.md`, "Audit identity pin").
5. Step 3 (semantic/local geometry accuracy), first pass done: `docs/GEOMETRY_ACCURACY_V05.md`.
   One narrow source change kept (boundary ordinate bounded by touching boundary-row ink); one
   reverted; two rejected by falsification. No documented failing gate passes. Next: obtain the
   sealed final-12 tangency generator/reference (in the 552 MB 0.4 evidence archive), then
   continue with step 4 (natural live correction).
6. Authentic line identity, second pass done: `docs/GEOMETRY_ACCURACY_V05.md` section 8.
   Balclutha s48/s7, Wapama s5 and ALMA sheet 4 and lines: 14 sections with provisional,
   assistant-read specs; all 14 abstain (correctly; overlaid or multi-line panels); no
   choice is made. Monitor: no spec possible. Kept: H5 (ruler tone texture is not a stroke) and
   H6 (rejected trace reasons disclosed). Open for the Rust owner: H7 (the sole-candidate
   fallback ignores non-grid competitors). Next: expert station labels and positions.

## Paused 2026-11-07 (usage limit) — resume here

Merged on `continue/v0.5`: macOS port, key rotation, OCR removal, Rust finalization guards,
legacy retirement, vision table reading, validation matrix, audit-identity pin, geometry and
line-identity passes, W3 structure, W4 rules, W1 Gunnerus benchmark, desktop app (Tauri) with
fixes, final Slipway logo, quick/full test tiers. HAER: Wapama 22/22, C.A. Thayer 37/38.

Stopped mid-work (partial work may exist in their worktrees under `.claude/worktrees/`):
- W8 draft mode (best-effort result, `draft_not_verified` status enforced in Rust) — branch `worktree-agent-a92eeed358588c336`.
- W9 Gunnerus gap fixes (multi-outline sections, midbody frame identity, side-line extent, raster limit) — branch `worktree-agent-aa8c1c2990156d231`.
- W2 benchmark factory (rendered drawings from Ship-D/SIMMAN/Series 60/DSYHS, sealed splits) — branch `worktree-agent-a5f2ca62d61c39481`.
To resume: inspect each branch (`git log a2608e1..<branch>`), keep sound commits, and restart each
workstream from its brief in this session's history or from docs/STRATEGY_2026Q4.md section 4.
Next after W8: W10 draft highlighting in the app. Run `make test-full` before each merge.

## Test stability under load (2026-11-07)

`make test-full` on the merged W8+W9 code (`0bed930`) passed except one `draft_guards` test per run,
a different one each time (`a_policy_cannot_confirm_its_own_guess`, then
`worker_forged_guess_is_rejected_at_the_receipt`). Each passes when run alone. The machine load
average was 29–33 on 10 cores (benchmark factory plus three agents building), so worker processes
reached their wall/CPU limits and ended blocked for a different reason than the test expects.
Not a logic failure in draft mode, but the worker limits are tight under contention. Follow-up:
rerun `make test-full` on a quiet machine before any release; W9b is fixing the known flaky
cancellation test; consider test-only timeouts that scale with load, never weaker checks.

## Provider transfer decision (2026-11-07)

The founder, in chat: "yes you can send any of them to deepseek". Sending crops or pages of
any acquired drawing (HAER, ALMA, Gunnerus, MiDShip, Ship-D renders, SIMMAN/DSYHS renders) to
the DeepSeek provider through the Rust provider worker is authorized for development and
evaluation. Receipts must still record every image sent (hash, size, crop box). This does not
change redistribution: no drawing or derivative is committed or published.

## Benchmark factory result (W2, 2026-11-07) — key finding

1,080 rendered body-plan drawings (Ship-D, SIMMAN, Series 60, Wigley, DSYHS; 4 degradation levels;
separate-panel and overlaid layouts), deterministic abstain policy at `64a434d`: **12 built**,
1,041 abstained, 27 failed. Built cases are nearly all clean, separate-panel drawings and are
accurate (sealed: 6/6 correct, station RMS median 34 mm = 0.32 % of half-beam, in-range volume
1.05 %). One validation build silently followed a wrong stroke (27 % volume error). All 216
overlaid body plans abstained; degradation levels 2–3 built nothing.
Meaning: the deterministic reader is accurate when it reads, but it reads almost nothing on
realistic drawings. Line identity on crowded/degraded sheets is the main product gap; W11 (LLM
line identity) and draft mode target it. The factory sealed split is used up: generate a fresh
sealed split (new Ship-D clusters and held-back named hulls) before the next final comparison.
Investigate the silent wrong build (`sysser45-L1`) as a priority: a confident wrong answer is
worse than an abstention.

## Founder decisions, night of 2026-11-08

- Push and pull requests: the CEO session may push, open, update and merge its own PRs and keep
  branches tidy ("you have full reign"). Still asked first: force-push, rewriting published
  history, deleting remote branches it did not create, repo settings/visibility, releases.
- All project documents may go to the public repository; the founder will make it private later.
- Auto-fix is on for PR #4.
- MiDShip tranche 2 (about 3.5 GB) approved.
- CAD direction ("mostly agree"): the vision LLM may write vessel models as programs in a
  restricted ship language (not free Python), run in an isolated worker without network or file
  access, with every number measured from the drawings and every result checked against all
  views; unresolved parts are draft guesses. Supersedes the 0.4 rule "model-generated code is
  never executed" for this restricted language only.
- The founder expects DeepSeek to extract numbers from pixels well. To be measured before
  deciding how freely the model may set numbers: DeepSeek localisation accuracy vs factory truth
  and vs the deterministic tracer (after W12's vision-request command merges).

## W11 + W12 merged (2026-11-08, GPT Sol via router-task)

- W11 LLM line identity (docs/LLM_LINE_IDENTITY.md): investigation tools with ink-snapped
  verification; 11/11 guard mutations caught. Three arms on 360 factory development sections:
  abstain 0 lines; deterministic draft 138 (45 visibly hull-side); LLM live 34 (25 hull-side,
  36 no-progress stops). Authentic sheets: live 20/105 lines, no complete station identity.
  Gunnerus: no model in any arm. LLM did not improve the geometry gate.
- W12 LLM setup + veto (docs/LLM_SETUP_AND_REVIEW.md): setup not usable yet (layout 22/40,
  centreline median 209 px, baseline 472 px, panel corners 370 px, 0 publishable specs). Veto
  reviewer: on the silent wrong build 4 true vetoes, 3 misses; 0 false vetoes on 18 correct
  stations. Root cause of `sysser45-L1`: global z=0 requirements reach below local hull
  bottoms; traces fill those rows with buttock-grid strokes, then switch to the hull line.
  Proposed fix: source-supported local endpoints and whole-stroke identity checks.
- Usage (list cost; reported charge $0): W11 488 requests, 3.78 M prompt tokens, $0.544;
  W12 646 calls, 0.69 M prompt tokens, $0.220.
- Three W12 overlays of restricted or unclear-licence drawings (ALMA, Gunnerus) were removed from
  the branch history before merging (kept locally in work/archived-runs/w12-restricted/).
- Hypothesis under test (W14): the large setup errors and "upper-left" placements may be a
  coordinate-frame bug in the harness (normalized or downscaled coordinates), not a model limit.
