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

## W14 localisation merged (2026-11-08)

docs/LLM_LOCALISATION.md. A harness coordinate-frame bug was real: read as source pixels,
DeepSeek's setup answers were off by 938.6 px median; through the actual attachment transform
they were off by 20.2 px. The harness now requests 0–1000 normalized attachment coordinates and
converts them. Setup errors fell (panel components 370.5 → 71.4 px median; centreline 209.4 →
40.5 px; baseline 471.6 → 171.4 px), but fewer proposals passed (32 → 15 of 40) and no complete
spec passed. Localisation on factory drawings (crop mode): points about 45–51 px median;
half-breadth about 1.1 m median vs 0.02 m for the deterministic tracer; no answers on overlaid
body plans. Conclusion for deepseek-v4.1-flash: the model chooses WHAT and roughly WHERE;
deterministic code measures HOW MUCH. W13 (ship CAD language) follows this split.
Usage: 874 requests, 2.80 M prompt tokens, list cost $0.541.

## CI fix, MiDShip tranche 2, sealed split decision (2026-11-08)

- PR #4 Linux CI: the parent-death reliability test timed out because the controller hashes its
  own executable, and unoptimised SHA-256 on the 65 MB debug test binary took longer than the 5 s
  readiness wait. Fix: `[profile.dev.package.sha2] opt-level = 3` (ee7f924). Reproduced and
  verified in a Linux container (53 passed).
- MiDShip tranche 2 is complete: 3.03 GB, 13,590 files, every file hash-checked. Held now:
  1,536 designs (Random 519, Repaired 521, SGLD 496, all 496 SGLD no-3D packages), plus 30
  full-3D designs. Data only, in work/sources/midship; selection notes in its selection.md.
- Sealed split v2: all 44 Ship-D families already occur in the frozen splits, so a split with
  unused families is not possible. Decision (PM): use a new fixed-seed partition, exclude every
  cluster with a previously rendered hull, and call it "hull-disjoint (v2)", not family-disjoint.
  Target: 288 drawings (36 hulls x 2 layouts x 4 levels). Generation job 20261108-045443-36168.

## sysser45 fix and W13 merged (2026-11-08, 844c842, test-full passed)

- sysser45 (Sol): mixed ruler/hull traces are refused before deterministic builds. The silent
  wrong build `sysser45-L1` now abstains. Factory development: 0 newly wrong builds, 0 new correct
  builds, the 4 correct controls unchanged. Details: docs/GEOMETRY_ACCURACY_V05.md section 9.
  Raw fingerprints (5.6 MB) are in work/archived-runs/sysser45/, not in git.
- W13 ship CAD language (Sol): `ship-cad/v1` JSON with six operations; every dimension refers to
  a host measurement. CAD runs in a deny-default macOS sandbox (fails closed elsewhere). Gunnerus:
  hull built as a draft (-0.9% volume at 2.5 m draft, 0.82 m breadth RMS, profile check failed by
  3.8 m); deck, deckhouse, bulwark and store not built (ambiguous outlines). docs/SHIP_CAD_LANGUAGE.md.
- W15 plan-view corridors started (Sol job 20261108-050559-48031, worktree w15-plan-corridors).

## Sealed split v2 merged; head-to-head started (2026-11-08)

- Security review fixes for the W13 sandbox: narrower Seatbelt profile, worker writes only
  `task/work`, results read with O_NOFOLLOW and O_NONBLOCK (3e2e123, 10a2eb2).
- Sealed split hull-disjoint (v2) merged (7c2d4f6): 288 drawings, 36 Ship-D hulls, seed
  20261108, manifest SHA-256 856a37fa…. Inputs and truth are in work/factory-sealed-v2/ (ignored).
- Head-to-head protocol and decision rule pre-registered in
  docs/plans/2026-11-08-h2h-sealed-v2.md (d9d8609) before any v2 result. Run: Sol job
  20261108-051711-53879, worktree h2h-sealed-v2. After it, the v2 split is spent for model selection.
- Data loss and restore (2026-11-08): removing merged worktrees with `--force` deleted their
  ignored `work/` folders: the sealed v2 inputs/truth, and the raw sysser45 and W13 trace evidence
  (committed summaries remain). Sealed v2 was regenerated with the frozen generator: cases.jsonl,
  hulls.json and selection.json are byte-identical; `sealed_v2 --verify` passes against the frozen
  manifests. Data now in the main checkout's work/factory-sealed-v2/. No case had run. Head-to-head
  resumed as job 20261108-052534-56428. Lesson recorded in ~/tasks/lessons.md.
- Head-to-head driver stopped after 65 abstain cases when its router session ended (the
  process was not detached). Resumed with `scripts/resume_h2h_sealed_v2.py` in the h2h worktree,
  started with nohup from the main checkout (log: work/h2h-sealed-v2/resume.log). The 2 cases in
  progress are counted as failed (`interrupted_by_harness_stop`), never retried. The LLM arm now
  passes `--model-review true`, as the pre-registered protocol requires (W12 veto); no LLM case
  had run before this. Recorded in work/h2h-sealed-v2/campaign.json under `resumes`.

## W15 plan-view corridors merged (2026-11-08, da6a1fe)

Opt-in adapter `plan_corridors.py`: derives contour corridors from plan-view waterline crossings
of the same drawing. Synthetic overlaid body plan: picks the right station; refuses ambiguous,
missing or clipped crossings. **Gunnerus: no improvement.** All 792 anchor attempts were refused
(648 competing crossings, 144 missing endpoint-waterline identity); still 0 unique candidates and
no build in abstain and draft. The 4 factory controls are unchanged; 0 newly wrong builds.
test-full passed on the branch; quick tier passed after merge (709). Raw data: work/w15/.

Next idea (W16, after the head-to-head): let DeepSeek identify which waterline each plan-view
crossing belongs to (the model chooses WHAT), and let the W15 adapter measure. Do not start it
while the head-to-head LLM arm runs: it shares the provider keys, and a rate-limit failure in the
campaign counts as a failure.

## 2026-11-08 09:50 SGT: head-to-head on sealed v2 finished and published; W17 started

- **Result (288 cases per arm, frozen gate):** abstain 7 correct, deterministic draft 13 correct
  (75 built, 62 labelled wrong drafts), LLM-first 9 correct (14 built, 5 labelled wrong drafts).
  No silent wrong build in any arm. Pre-registered rule: **deterministic draft becomes the default**;
  LLM-first stays an explicit option. Report: `docs/BENCHMARK_FACTORY.md`, section
  "Head-to-head, hull-disjoint (v2)"; rows in `outputs/h2h-sealed-v2/`. Split v2 is now spent.
- **Deviations recorded:** 2 abstain cases interrupted by the harness (counted as failures); the
  W12 model review was added for the LLM arm before any LLM case ran.
- **Why the LLM arm stalled (270 of 288 `no_progress`):** (1) 87 L1/L2 cases: inspection hit an
  evidence-budget `resource_limit`, the model saw no reason and every tool refused; (2) the rest:
  the observation history always sent `"reason": null` (controller read the wrong field), there is
  no working memory for what the model read, and temperature 0 / thinking off made it repeat the
  same action until the repeat limit.
- **W17 (running):** Sol, router job `20261108-093458-14738`, worktree
  `.claude/worktrees/w17-llm-progress`, brief `work/w17/brief.md`. Fixes the causes above and
  measures before/after on ~24 non-sealed dev cases. Results to `outputs/w17/`.
- **Open:** apply the app default change (draft) from the rule; W16 after W17; a new held-out
  split is needed before any claim that W17 improves the LLM arm.
- **W18 (approved by the founder; queued after W17):** build a native agent loop with memory into the
  MarinaFrame harness, not an external framework. Brief: `work/w17/w18-brief.md`. It resumes the
  same Sol session on `w17-llm-progress` when W17 reports.

## 2026-11-08 10:15 SGT: product principle — the AI fills the gaps

- Founder: MarinaFrame is agentic so that AI fills in what is not in the data; it must not stop on
  missing or bad data. In draft mode the model may now propose section shapes and missing sheet data;
  code builds them and labels each section `traced`, `repaired`, `interpolated` or `ai_inferred`.
- Work order on `w17-llm-progress` (Sol, one session): W17 (committed by Sol in W17b step 0), W17b
  (build CAD through gaps, router job `20261108-100601-60204`), W17c (AI gap filling, brief
  `work/w17/w17c-brief.md`), then W18 (memory loop). Testing in 4-case rounds, not big campaigns.
- **Founder correction (later the same day):** the model writing geometry is a main capability, not
  only a gap fallback. It may author or correct any section or sheet value; code fairs, builds,
  renders back and labels the source. The old rule "model chooses WHAT, code measures HOW MUCH" is
  superseded. W17c brief updated.
- **Founder direction (later):** happy path first. No new refusals or blocked states; in draft mode
  checks become warnings whenever a solid can be made. W17c is on branch `w17c-model-geometry`
  (pushed); Sol merges it after W18 and rewrites the prompt.

## 2026-11-08 13:05 SGT: lanes and results

- **Dev results (24 non-sealed cases):** before W17: 1 draft, 1 correct, 92% no_progress.
  W17b: 10 drafts, 2 correct, 58% no_progress, 0 silent wrong, $0.76 list cost.
  W18b 4-case round (conversation mode, merged W17c, short prompt): 2/4 drafts, 0 correct, 61
  `propose_section` calls, $0.27.
- **Wrong-draft analysis** (`work/w17/wrong-drafts-analysis.md`): partial strokes 27 sections,
  grid lines as hulls 15, missing sections 6, plus a deck-closure overshoot. Calibration was never
  the cause.
- **Branches:** `w17-llm-progress` (Sol; W17, W17b, W17c merge, W18 prototype, W18b),
  `w17c-model-geometry`, `w18-cad-complexity` (knot-limit simplification, deck-edge closure),
  `app-llm-draft-view` (labels, warnings, model activity in the app) — all pushed; Sol merges them
  into `w17-llm-progress` in W18c (running, router job `20261108-130002-99421`).
- **Running:** Opus `w18-stroke-discovery` (fragment linking, grid tagging, ranking, graceful noise
  handling); GLM `tools-run-round` (standard small-round runner with early stop); GLM analysis of
  deterministic draft errors (app default) to `work/deterministic-draft-analysis.md`.
- **Founder directions today:** progress before provenance; AI fills gaps; the model writes
  geometry; happy path first (no new build failures); small rounds before any campaign.
- **Cleanup:** h2h-sealed-v2 worktree removed (data stays in main `work/h2h-sealed-v2/`). PR #4 CI
  green at 37113d7/40601cc.

## 2026-11-08 13:35 SGT: LLM-first app default (PM decision, founder "up to you")

- Decision: the desktop app uses AI drafting by default; deterministic draft only when AI drafting is
  off or no key is found. v3 will be run later as a check, not as a gate. Branch `app-llm-first`
  (1a9fb88, on top of `app-llm-draft-view`): setting `ai_drafting` (default on), key lookup from
  env or `~/.config/marinaframe/opencode-go-keys.txt`, `provider-worker` handled by the app binary,
  AI status in Settings and New run. `make test-quick` passes; UI checked on mocks.
- Not yet verified: a real AI run started from the built desktop app (needs the merged W17-W18
  controller; do it after the integration merge).
- GLM analysis of deterministic drafts: `work/deterministic-draft-analysis.md` (uncaught
  `resource_limit` at agent_tools.py:882 kills inspection; blocking gaps abort draft mode before
  guesses; overlay panels give every station the same curve).

## 2026-11-08 17:50 SGT: everything integrated into continue/v0.5 (595cb78)

- Merged: W17-W18d (Sol: memory, happy-path drafts, model geometry, W19 first hull, combined score,
  keep rule, loop controls), w19-0 (CAD fix, stroke discovery, C2, F1+security fix, D1, three-view
  factory), w19a/w19b, app LLM-first + UI polish. `make test-full` passes (839 quick, 24 CAD, smoke).
- R-body round (W18d, 4 cases): 4/4 drafts, 0/4 correct, $0.056 total (W18c: $0.85). RMS: DTMB L0
  4.47 %, 00045 L2 4.56 %, 00679 L0 10.89 % (first hull 10.13 %), 00683 L2 33.88 %.
- Open: the model adds little over the first hull and still worsens 00679; the combined score accepts
  some truth-worsening edits; 00683-L2 first hull is 33.9 % after integration vs 23.4 % in W19a alone;
  DTMB 4.47 % comes from the hull tops (~1 px); image-enhancement test blocked (no image tool headless).

## 2026-11-08 22:05 SGT: founder priority — accuracy and coverage over model cost

- Model cost is a tiny fraction of a naval architect's time. Optimise for correct drafts and for how
  much ground the tool helps them cover; report cost but do not trade accuracy for it.
- Running: end-to-end 24-case dev measurement of a12d0a5 (work/e2e-a12d0a5/, driver.log), 2 jobs.
- Next experiments to try after it (accuracy levers previously held back for cost): thinking on
  for the investigator, higher request budget, several independent passes with the best draft kept
  by the score, and a stronger model for the editing step.

## 2026-11-09 00:40 SGT: app milestones merged (M1 shell, M2 intake, M3 live backend, M5 exports)

- `continue/v0.5` has: MarinaChain-palette shell with Home/Settings (M1), drawing-set intake with
  the sheet-only live draft path (M2: intake.py, materialize.py, app/core intake.rs, controller
  phase-1-first for sheet-only specs, hash-bound materialized spec), live steps API (M3 backend),
  exports (M5: offsets CSV with formula escaping, hydrostatics, PDF report, package). make test-full
  passes (912 quick, 24 CAD, smoke).
- Running: M3 UI (live run screen) lane; 48-case measurement of 9e7161f (baseline vs thinking).
- Follow-ups: sheet-only intake without an AI key is blocked (only the model reads stations);
  intake drafts are far off (dtmb5415-L0 43 %, 3-view 42 %: scale read 2x too high in one case);
  round_digest needs the 3-view truth naming (looks for "dtmb5415-3v").

## 2026-11-09 01:30 SGT: first real live run watched in the desktop app

- Built the app, wrapped the debug build as `work/app-live-check/MarinaFrame.app` (ad-hoc signed,
  bundle id io.marinachain.marinaframe; added to the Computer Use allowlist at the founder's request),
  and drove it with Computer Use. A real DeepSeek run (shipd-1-00679-L0, started from the CLI into the
  app's runs folder) appeared live: Thinking cards, propose_section "Kept: fit 0.8737 to 0.9671",
  first hull growing, fit dial, revision ladder r0 0.87 > r1 0.97. 9 requests, $0.018, 4 min 47 s.
  Score vs dev truth: RMS 3.02 % of half-beam, volume -1.2 % (gate 2 % / 5 %); first hull was 3.13 %.
- Fixed during the check (ab6466c): live screen froze on an empty event batch; 3D guess bands hid the
  hull; stacked amber fill on shared panels; state chip truncated on cards.
- Still to do: drop-a-drawing-set UI wired to intake (backend exists); section strip's second chip row
  is clipped by its scrollbar; vessel names for factory drawings are hash ids; a full `tauri build`
  release bundle with icon; runs started from the CLI show "a different build made this run" (expected).

## 2026-11-09 04:30 SGT: app features, sheet-only accuracy, whole-vessel step 1 (continue/v0.5 e63ece1)

Founder decisions this stretch: commercial licence for all acquired data (Gunnerus included; see
`docs/DEPENDENCIES_AND_RIGHTS.md`), so drawings may go to DeepSeek but never into the public repo;
model output format for whole-vessel parts is ship-cad JSON (A/B below); arm B sandbox kept light
by founder choice (timeout, own folder, env allow-list); a standing Opus UI/UX lane works in rounds.

| Area | State | Where |
|---|---|---|
| Export (M5) | Export tab: STEP, STL, offsets, hydrostatics, PDF, package, draft stamp | `app/core/src/export.rs`, `app/ui/js/export.js` |
| Mark and revise | box/lasso/strip/3D pick + instruction; focused pass; keep rule checks the marked sections first; force keep | `rust-control/src/revision.rs`, `app/ui/js/mark.js` |
| UI rounds 1-24 | intake stage, vessel tabs, review counter + A/O/M keys, ⌘K palette, Changes, section-area check, evidence cards, a11y (`npm run test:a11y`), sample vessel, loading states | map: `docs/design/2026-11-08-app-design-plan.md` section 10; research `docs/research/2026-11-09-uiux-research.md` |
| Sheet-only accuracy (live, dev) | series60-3v-L0 1.70 % RMS / +0.9 % volume (passes); dtmb5415-3v-L0 9.5 % / +3.5 % | fixes: mirrored aft half, label-row cut, deck line, printed scale, station lines; `scripts/run_round.py --sheet-only` |
| Whole vessel (Gunnerus, dev) | 7 parts from the GA; deckhouse IoU 0.94, volume +9.4 %; JSON beats CadQuery 3-1 (thinking off); model adds no accuracy on vector input | `docs/WHOLE_VESSEL_GUNNERUS.md`, plan `docs/plans/2026-11-09-whole-vessel-scope.md` |
| Controller | repeated refusals: strong hint, stop at 2x limit; tool errors undo and refuse instead of ending the run | `rust-control/src/controller.rs`, `agent_tools.py` |

Keys: OpenCode keys 2 and 3 are at their monthly limit until 14-15 Nov; key 1 carries all runs.
Real-app check of rounds 5-24 and the sample vessel is not done (app rebuilt and running; screen
was not reachable). Memory measured in a live app run: app 54-120 MB, web view 34-117 MB, CAD
worker peak 1.7 GB, total peak about 1.9 GB.

Resume: (1) trace lane: profile baseline snap, worsening edits kept on dtmb, 6-case dev round;
(2) whole-vessel lane: raster round 3 (protocol c2a5e2f), hull + parts assembly, components.json;
(3) UI lane: rounds 25-32 starting with the component tree; (4) real-app check of the sample run.

## 2026-11-09 05:30 SGT: baseline vs thinking (e2e-9e7161f, frozen binary, w17 factory, 24 dev cases each)

| Arm | Drafts scored | Both gates | Median RMS half-beam | Median abs volume | Main end reason |
|---|---|---|---|---|---|
| Baseline (thinking off) | 21 | 2 | 21.6 % | 6.1 % | repeated_identical_action_refusals (13) |
| Thinking on | 22 | 2 | 21.8 % | 6.1 % | open_guesses_block_review (15) |

Paired on 20 cases, thinking is better on 4 and the medians are equal. Thinking changes how runs
end (1 repeated-refusal stop instead of 13), not accuracy: the score comes mostly from the code's
first hull. Decision: keep thinking off by default (faster, same accuracy); accuracy work stays on
the readers (see the sheet-only fixes, which this frozen binary does not have). The disk filled
during this run (watcher stopped at 1 GB free); results are complete for both arms.

## 2026-11-09: DeepSeek image resolution (probe, work/vision-probe/REPORT.md)

DeepSeek V4.1 Flash through OpenCode Go ignores the image `detail` field (omitted, low, high and
original give the same tokens and answers). Image tokens: 184 at 256-512 px, 652 at 1024 px, 994 at
2048 px; images above about 2048 px per side are downscaled silently (12 px text: 11 of 12 read at
2048 px, 2 at 3000 px, 0 at 4096 px). Rule for all vision code: send tiles of at most 2048 px per
side, with the smallest feature to read at 16 px or more. The Balclutha round 4 sent a 2408 x 3611
crop, so the model saw it downscaled; a tiled rerun needs a new fixed protocol.

## 2026-11-09 08:30 SGT: app product features, packaging, whole-vessel lighter hull

- UI lane rounds 25-72 merged: Parts tab (component tree, per-part Accept/Mark, sign-off "usable as a
  starting model", whole vessel in 3D from a GLB), key usage per OpenCode slot, batch queue (folder
  drop, native-slot pump, saved queue), multi-page intake, run notifications, places instead of ids,
  a11y test (`npm run test:a11y`, 18 screens), UI tests (`npm run test:ui`).
- Packaging (docs/plans/2026-11-09-packaging.md): release build passes (app about 19 MB, arm64, ad
  hoc); the worker Python is found at run time (env, Settings, inside the bundle, dev .venv; nothing
  beside the bundle); every build embeds only the checked `ui-release` copy. Step 3 (bundled
  Python runtime) is in progress. Owner decisions before distribution: PyMuPDF (AGPL or commercial)
  and VTK licences; Developer ID signing and notarization.
- Whole vessel (docs/WHOLE_VESSEL_GUNNERUS.md): hull cut at the deck (+52 % volume error fixed),
  lighter hull (STEP 15.4 MB, GLB 1.5 MB, scores unchanged), 4 appendages (contact gaps remain),
  part re-run from a mark (CLI), Balclutha model test: no value at whole-image size.
- DeepSeek images: `detail` is ignored; images over about 2048 px per side are downscaled.
- Sheet-only accuracy: series60 L0 passes live; blurred L1 sheets fail; lane "trace-fix-2" works on
  centreline detection, curve identity, first-hull rebuild and run-to-run variance.
- Real-app check still not done (app window not reachable by Computer Use).

## 2026-11-09: sheet-only accuracy on blurred L1 sheets (lane commits 5345d70..c4169f2)

| Case | L0 before | L0 live ba8114c | L1 before | L1 live (5345d70 / ba8114c) | L1 replay c4169f2 |
|---|---|---|---|---|---|
| dtmb5415 | 5.4 % | 9.3 % (twice; top-cell residual) | 29.7 % | 18.6 / 18.5 % | 18.5 % |
| series60 | 1.4 % | 1.4 % (passes) | 74.8 % | 28.1 / crash (fixed df2faa7); 34.9 % on df2faa7 | 4.3 % |
| shipd-1-00679 | 6.8 % | 6.8 % | 9.5 % | 9.9 / 8.9 % | 9.9 % |
| shipd-1-08158 | 2.8 % | 0.75 % (passes) | 16.0 % | 3.5 / 2.1 % | 10.5 % (s01 end-face slice) |
| shipd-1-09867 | 3.4 % | 3.4 % | 12.5 % | 11.5 / 12.5 % | 2.1 % |

RMS of half-beam, development truth. Replays run the model's recorded phase-1 reading through
`build_first_hull` with the current code (script pattern in `tasks/lessons.md`); live L1 numbers
for c4169f2 are not measured yet. Fixed: body-plan centreline and light grid/station lines read
by local contrast (dash-dot centreline), first hull rebuilt when a later reading changes its
setup, station lines on grey scans and with no x origin, tops continued to the profile deck,
model-read body-plan sides kept, printed scale before a grid guess, datums on the intake's
ink-measured rows. Variance (same code ba8114c): dtmb5415-L1 18.5 / 13.8 / 18.5 %;
shipd-1-08158-L0 0.75 / 0.73 % plus two runs lost to bugs fixed in df2faa7. Best-of-N not added.
Open: dtmb5415-L1 fore-half identity (curve 9 weak, a mixed contour takes the outermost slot;
filtering mixed strokes broke the aft half, reverted); dtmb5415 top-cell residual; aft/fore ends
beyond the terminal stations are not modelled.

## 2026-11-09 12:15 SGT: hull-accuracy lane (hull ends, readings best of 2; commits 8870405..)

| Case | Before (live ba8114c) | Replay same reading: HEAD -> ends | Live 7f25122 (delivered draft) |
|---|---|---|---|
| dtmb5415-L0 | 5.4-9.3 % | 9.32 / +2.1 -> 6.00 / +0.8 | 5.06 % / +0.6 % |
| series60-L0 | 1.4 % (pass) | 1.40 / +0.6 -> 1.40 / +1.3 | 4.62 % / -0.8 % (s04 trace dip) |
| shipd-1-00679-L0 | 6.8 % | 6.81 / -1.5 -> 6.71 / -1.3 | 6.17 % / -0.4 % |
| shipd-1-08158-L0 | 0.75-2.8 % | 0.75 / -1.6 -> 0.75 / -2.1 | 0.74 % / -1.9 % (pass) |
| shipd-1-09867-L0 | 3.4 % | 3.42 / -2.6 -> 3.42 / +0.6 | 10.39 % / -3.0 % (first hull 3.42 %) |
| dtmb5415-L1 | 18.5 % | 18.51 / +14.0 -> 14.92 / +13.4 | 14.92 % / +13.4 % |
| series60-L1 | 34.9 % (df2faa7) | 4.34 / -0.1 -> 4.34 / +0.5 | 4.32 % / -1.5 % |
| shipd-1-00679-L1 | 8.9 % | 8.86 / -2.7 -> 8.73 / -2.8 | 8.72 % / -2.6 % |
| shipd-1-08158-L1 | 2.1 % | 2.09 / -3.1 -> 2.09 / -3.0 | 2.94 % / -2.8 % |
| shipd-1-09867-L1 | 12.5 % | 12.45 / +1.0 -> 12.45 / +5.5 | 14.12 % / +6.6 % |

RMS half-beam / in-range volume, development truth; gates unchanged. Rounds:
`work/round-3view-L{0,1}-7f25122` (snapshot `work/snap-7f25122`), 173 requests, list $0.86, key 1
meter 59 %. Changes: (1) hull ends: end sections from the end stations to the profile outline's
ends (checked against LOA), keel/deck from the profile outline, breadth taper from the half-breadth
plan outline, shape from the end station, labelled ai_inferred; full-length volume error now equals
in-range error (09867-L0 -12.7 -> +0.6 %). A profile with no read baseline uses the outline's lowest
line (dtmb deck cut: 9.3 -> 6.0 % on replay); a reading with no profile setup uses the intake's profile.
(2) dtmb L0 stations 5/6 shared only the top of one stroke; the deck cut removes it. L1 fore identity
(7<-6, 8<-7, 9<-8 shift) is open: description waterline heights are unreliable, so a plan-crossing
identity check was not added. (3) best of 2 readings by drawing fit (ties keep the earlier one): it
chose the better first hull in 3 of 4 differing cases (dtmb-L0 13.8 vs 32.6 %, 00679-L0 6.7 vs 22.3 %).
Fixed on the way: set-aside readings' builds were reused by build_draft (equal generation ids), and
the digest scored the newest STEP instead of the task's last valid candidate.
Open: model section edits that the fit keep rule accepts but that worsen truth (09867-L0 s08 7 -> 30 %);
series60 midship trace dips; dtmb top-cell residual (deck within 1 px still costs one 0.05 m sample).

## 2026-11-09 12:55 SGT: drafting model setting; Crouton development round (commit 66cf8f8)

`marinaframe run --model` takes an ordered OpenCode Go list (allow-list DeepSeek V4.1 Flash,
Crouton Alpha Free; never Claude or GPT). On a rate-limit or usage-exhausted answer the run moves
to the next model (`model_switched` event). The per-model request table is in
`rust-control/src/models.rs`. The app default stays DeepSeek. `run_round.py` defaults to
`crouton-alpha-free,deepseek-v4.1-flash`. Details: `docs/AGENT_HARNESS.md`, "Drafting model".

Live sheet-only round `work/round-3view-L0-crouton-66cf8f8` (snapshot `work/snap-66cf8f8`, key 1):

| Case | Crouton: RMS / volume | DeepSeek latest | Wall (model time) | Requests (completed) | Tokens in / out | Cost / list cost | End |
|---|---|---|---|---|---|---|---|
| series60-3v-L0 | 3.95 % / +0.5 % (fails) | 1.4-4.6 % | 203 s (102 s) | 16 (10) | 169,933 / 21,873 | 0 / 0 | runaway reply |
| shipd-1-08158-3v-L0 | 15.60 % / +19.4 % (fails) | 0.74 % / -1.9 % | 295 s (127 s) | 19 (11) | 176,974 / 20,794 | 0 / 0 | runaway reply |

RMS of half-beam, development truth. All requests went to Crouton and it answered as Crouton; no
rate limit, so no switch. Crouton was fast here (5-15 s per request). Its replies were often
refused: 4 of 16 and 6 of 19 broke the tool contract (invalid JSON, out-of-bounds arguments,
operation contract). Both runs ended when one reply ran to the token limit (`finish_reason`
length, about 16-18k tokens of repeated text; `provider_incomplete_or_unexpected_choice`), and each
kept its last valid draft. Image tokens are not counted by OpenCode Go (input tokens are text only).
No further rounds: the founder moved the happy path to Claude Sonnet 5.5 (subscription `claude` CLI);
that provider will plug into the same model list and settings table.
