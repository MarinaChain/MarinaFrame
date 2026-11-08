# W20a2 — Read dimensions right

## Outcome

Both available three-view sheets now pass LOA, beam, depth and draft within 2%. R-body dimensions improve from 2/4 to **3/4 acceptable** (off-sheet LOA/draft are null with warnings); stations remain 4/4 and waterline sets 3/4. **00683-L2 beam remains inaccurate, but is no longer silent.** All wrong fields have named warnings. No sealed inputs or reference STEP/mesh were opened by inference.

## Changes

Owned files only:
- `vessel_description.py`: accepts exact labelled `dimension_text` transcribed by the model; parses LOA separately from LWL and DRAFT (DWL), and prefers printed values over approximate extents. Raw model description and each measurement remain available.
- Pairwise comparisons cover model reading, body/plan/profile ink, declared drawing depth and printed readings. Every >2% disagreement produces a named `principal.<field>` warning. Missing model beam/depth readings also warn rather than silently certify the sole pixel extent.
- Declared drawing `z_max_m` supplies depth when no printed depth is available; a cropped/degraded ink extent cannot silently replace it. Pixel disagreement remains warned.
- Existing `describe_table` public hook checks draft-table beam/depth against the read dimensions and measured body extents. It adds warnings and does not alter geometry. This is the pre-build draft table, not a claim that exported STEP extents were independently checked during Phase 1.
- Rust describe-tool schema requests exact dimension text. Vessel phase permits `read_region` to correct an unreadable/wrong title crop. Instructions convert normalized thumbnail positions to source pixels and distinguish LOA/LWL/grid intervals.

Protected files unchanged: `form_fit.py`, `vessel_model.py`, `first_hull_tools.py`, `whole_vessel_score.py`, `view_measure.py`. No new refusal paths.

## Single six-case development round

Runtime and Python source frozen under main `work/w20a2/runtime/` and `source/`. Body arm completed before the three-view arm started, jobs=2, `--phase1-only true --steps 7 --no-early-stop`. Every trace inspected. No case retry. No CAD build in these Phase 1 checks.

| Case | Dimensions acceptable | Stations | Waterlines | Requests | List cost USD | Wrong fields without warning |
|---|---|---|---|---:|---:|---|
| dtmb5415-L0 | pass | pass | pass | 2 | 0.00511530 | none |
| shipd-1-00045-L2 | pass | pass | fail | 3 | 0.00780945 | none |
| shipd-1-00679-L0 | pass | pass | pass | 3 | 0.00448320 | none |
| shipd-1-00683-L2 | **fail: beam** | pass | pass | 4 | 0.00624645 | none |
| dtmb5415-3v-L0 | pass | pass | pass | 2 | 0.00374445 | none |
| shipd-1-00679-3v-L0 | pass | pass | fail | 3 | 0.00546495 | none |
| **Total** | **5/6** | **6/6** | **4/6** | **17** | **0.03286380** | **0** |

Body-only LOA/draft remain null + warning. They count as acceptable only because absent from these body-only sheets; incorrect numbers do not pass. Strict numeric checks and unknown exceptions are both saved by the unchanged checker in `checks.json`.

Three-view readings: DTMB LOA 100.00, beam 13.41, depth 12.53, draft 7.52 m; 00679 LOA 99.98, beam 17.21, depth 14.15, draft 8.49 m. Printed text beats the conflicting approximate pixel readings. 00683 body beam is still 17.1941 versus reference 15.8497 m (8.5% high), now explicitly warned because no independent model/text reading supports the ink extent. It is not corrected using evaluator truth.

The two remaining waterline-set failures are warned and unchanged in scope: degraded 00045 body grid and 00679 three-view grid. No new campaign was run to tune them.

Cost uses all provider receipt list costs, including rejected decisions (none in this round); missing cost receipts: zero. OpenCode reports billed cost zero; nominal list cost is retained. Artifacts: `checks.json`, `traces.json`, `digest.md`. Raw logs/receipts in main `work/w20a2/body`, `threeview`, `round.log`.

## Verification

- Regression red run: 3 failures demonstrate missing printed priority, silent missing beam/depth inconsistency and absent draft-table warning.
- Focused Python description/tool tests: 23 passed after fixes.
- `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`: passed with existing project Cargo cache: 873 Python tests, Rust workspace, format, Clippy and secret scan.
- A first quick build was stopped because a new per-task dependency cache exceeded the planned disk budget; that cache was removed. It is not reported as a pass.
- `make test-full`: **passed, exit 0**. Rust workspace/real-CAD tests, app real-task test, 873 non-CAD Python tests, 24 CAD Python tests, release and deterministic smoke all passed. Smoke ended `awaiting_human_review` and verify `valid:true`. No other full run was active when it started (`pgrep -f 'make test-full'` checked). Full log: main `work/w20a2/test-full.log`.

## Storage and commit

Retained task data about 23 MB, one cited runtime/source, no uncited runtime. Fresh task build cache was deleted; existing project cache reused (`CARGO_TARGET_DIR`, no incremental build). A temporary ignored `target` symlink supplies the Makefile smoke path and will be removed after tests; it is not committed. No protected code edits, push or merge.

Full verification passed. This report is included in the W20a2 commit (`git log -1`). No push or merge. Body dimension accuracy is not 4/4; beam identity remains the next issue.
