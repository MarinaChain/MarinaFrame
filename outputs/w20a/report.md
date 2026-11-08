# W20a — Read the vessel

## Current continuation status (PM request, 2026-11-08)

Checkpoint `b7ca986` was committed as-is after a fresh quick pass (855 Python tests). Happy-path changes now complete all 6/6 available descriptions in **two requests per case**, with no typed-output rejections. **Dimension target remains unmet:** R-body 2/4 acceptable dimensions, station sets 4/4, waterline sets 3/4. R-3view: 0/2 all-dimension passes, stations 2/2, waterlines 1/2. No further live round was run.

### Changes after the checkpoint

- Shared body view family accepts optional panels and inline scale/setup. First setup propagates to family members with panel-specific datums. This removes the per-panel request loop.
- Arbitrary description shapes and extra/odd fields are retained in `model_description` and metadata, coerced where numeric values are usable, and warned. Scale strings such as `1:100`, free-text ends/deck, null dimensions and stringified arguments no longer cause the observed shape refusals.
- Rust repairs misplaced notes/reason, absent reason, stringified arguments and extra outer metadata before operation parsing. Unknown operations are not executed.
- Named title blocks are attached on entering vessel description. Body-only LOA/draft stay unknown rather than invented numeric estimates.
- Waterline measurements use each declared panel's datum, merge the measured metric lattice, exclude baseline zero and warn on incomplete or unconfirmed sets. Original model sets remain available.
- Checker reports both strict numeric accuracy and PM's accepted warned unknowns. Only body-only LOA/draft are off-sheet unknown exceptions; wrong numeric values still fail. Three-view title-block dimensions have no unknown exception.

### Single round check table

| Case | Description | Dimensions acceptable | Stations | Waterlines | Requests | List cost USD | Wrong fields without warning |
|---|---|---|---|---|---:|---:|---|
| dtmb5415-L0 | complete | pass; LOA/draft warned unknown | pass | pass | 2 | 0.00512057 | none |
| shipd-1-00045-L2 | complete | fail: depth | pass | fail | 2 | 0.00537210 | none |
| shipd-1-00679-L0 | complete | pass; LOA/draft warned unknown | pass | pass | 2 | 0.00283980 | none |
| shipd-1-00683-L2 | complete | fail: beam | pass | pass | 2 | 0.00337890 | principal.beam |
| dtmb5415-3v-L0 | complete | fail: LOA, draft | pass | pass | 2 | 0.00365925 | none |
| shipd-1-00679-3v-L0 | complete | fail: draft unknown on printed sheet | pass | fail | 2 | 0.00369180 | none |
| **Total** | **6/6** | **target unmet** | **6/6** | **4/6** | **12** | **0.02406242** | **one uncovered field** |

00045 depth is 12.1898 m versus 12.5704 m (3.0% low); its degraded panel grid remains incomplete. 00683 beam is 17.1941 m versus 15.8497 m (8.5% high): annotation/competing ink is still misread as hull breadth, without a warning when the model leaves beam unknown. DTMB three-view reads LOA 30 m and draft 2.5 m instead of printed 100 m and 7.52 m. 00679 three-view uses normalized-looking coordinates as source pixels, so the title crop is wrong and draft stays null. These are measurement/identity errors, not tool-transport blockers. They are not tuned against truth in this checkpoint.

Evidence: `continue-checks.json`, `continue-traces.json`, `continue-digest.md`. Frozen runtime/source: main `work/w20a/round4-runtime/` and `round4-source/`. Arms `round4-body`, `round4-body-rest`, `round4-3view` contain one execution of each case. The runner stopped after the first two body cases because it misclassified the successful Phase 1 pause as a common failure; only the two unstarted cases were then launched with early-stop disabled. No retries or duplicate case requests. Generic draft-oriented digest success counts are not the Phase 1 acceptance result.

Continuation cost: **12 receipts, USD 0.02406242 nominal list cost, no missing cost records**. Total W20a including historical attempts: **105 receipts, USD 0.19715261**. OpenCode billing reports zero; nominal list cost is retained to show resource use.

### Verification and storage

- Fresh pre-change `make test-quick`: passed (855 Python tests, Rust workspace/format/Clippy, secret scan).
- Focused post-change tests: 23 Python tests and 77 Rust library tests passed.
- Post-change `make test-full`: **passed, exit 0**. Rust workspace, format and Clippy passed; 862 non-CAD Python tests passed; real-CAD Rust groups passed (8 audit identity, 8 draft guards, 8 finalization, 1 investigation, 4 region pipeline, 15 validation matrix); app real-task test passed; 24 Python CAD tests passed; release build and deterministic smoke passed (`awaiting_human_review`, verify `valid:true`). Full log: main `work/w20a/continue-test-full.log`.
- Protected fitting/scoring files remain unchanged. No sealed evaluation. No push or merge.
- Removed inspected bytecode caches only; no duplicate runtime/build folders existed under work/w20a. Kept one runtime/source for each cited round, all reports and JSON. Work/w20a is about 104 MB versus 84 MB at continuation start: new data about 20 MB, below 2 GB. Existing Cargo cache is reused.

Verification is complete. This report is included in the continuation commit (see `git log -1`). No push or merge. The dimension target is not met; next work is measurement/coordinate identity and the uncovered beam warning, not more transport gates. No additional campaign was run.

---

## Historical checkpoint (before PM continuation)

Implementation checkpoint, **acceptance targets not met**. Phase 1 completes on 2/4 R-body cases and 0/2 available R-3view cases within a seven-request attempt budget. Do not treat this as an accuracy success or held-out validation. No sealed v2/v3 inputs were opened. No push or merge.

## Changes

- Added `vessel_description.py`: bounded sheet tiles, C1 lattice evidence, W18 direction-following stroke summaries, text candidate boxes, datum snapping, pixel dimensions and field-specific warnings.
- Added `survey_sheet`, `describe_views` and `describe_vessel` through Python worker dispatch and Rust typed tools/catalog.
- Survey runs without a model request. Model names regions, proposes per-view scale/datums and writes the vessel description. Description and original model readings persist in domain state and `domain/vessel.json`.
- Controller asks for the next read-phase tool only and delays the first hull. `--phase1-only true` pauses after a complete description, before CAD.
- First-hull adapter uses usable station positions, undisputed dimensions and waterline grids through public fitting/table functions. Disputed dimensions do not become hard constraints. Body-only profile claims remain inferred.
- Harmless provider `type=json_object` response-format echoes are stripped before typed decision parsing. Other unknown fields still fail the existing contract.
- Fixed review defects: small named crops expand with warnings, padded dark grids are removed from extents, missing design fields receive named warnings, and unknown principal dimensions may remain null rather than cause refusal.

Protected files unchanged: `vessel_model.py`, `form_fit.py`, `panel_assignment.py`, `fairness.py`, `investigation.py`, `view_measure.py`, `whole_vessel_score.py`.

## Final Phase 1 check table

Final frozen code: main `work/w20a/round3-runtime/marinaframe` and `round3-source/`. Each attempt ran detached through `scripts/run_round.py` with `--policy live --on-ambiguity draft --phase1-only true --steps 7`. Each trace was inspected. Costs below include every provider receipt in that attempt, including rejected model outputs; the generic digest can undercount rejected requests.

| Set / case | Description complete | Dimensions <=2% | Stations right | Waterlines right | Requests | List cost USD | Every wrong field warned |
|---|---|---|---|---|---:|---:|---|
| R-body / dtmb5415-L0 | no | fail: unavailable | no result | no result | 7 | 0.01678847 | no result |
| R-body / shipd-1-00045-L2 | yes | fail: draft unknown | yes | no | 7 | 0.01408067 | no: waterlines missing warning |
| R-body / shipd-1-00679-L0 | no | fail: unavailable | no result | no result | 7 | 0.01038377 | no result |
| R-body / shipd-1-00683-L2 | yes | fail: beam, draft | yes | no | 4 | 0.00644745 | yes |
| R-3view / dtmb5415-3v-L0 | no | fail: unavailable | no result | no result | 7 | 0.01298213 | no result |
| R-3view / shipd-1-00679-3v-L0 | no | fail: unavailable | no result | no result | 7 | 0.01368045 | no result |
| R-3view / 00045 and 00683 | unavailable | not run | not run | not run | — | — | — |

Authoritative exact costs/values: `phase1-checks.json`. Checks compare LOA, beam, depth and draft against development hull metadata, station identities/positions against the supplied spec, and printed waterline sets against development render metadata. Baseline is a datum, not a labelled waterline. No STEP or mesh truth is used by this checker. The investigator receives drawing/specification pixels only, not checker reference dimensions or `views.json` metadata.

R-body denominator stays four: 0/4 pass all dimensions; 2/4 station sets; 0/4 waterline sets in the final round. R-3view denominator is two available cases, with the two missing requested hulls disclosed. The request target is bounded, but completeness/accuracy targets fail.

### Completed descriptions

- 00045 L2: LOA 100 m, beam 21.508 m and depth 12.57 m are within 2%; draft null. Waterlines `[0,1]` are wrong and not flagged because no regular body grid was found for the broad named crop.
- 00683 L2: LOA 100 m and depth 14.53 m are within 2%; measured beam 17.194 m vs reference 15.850 m is wrong; draft null. Returned waterlines include baseline 0 in addition to the printed 2–14 m set. These wrong fields have warnings.

### Remaining blockers

1. The model names each of nine separate body panels as a distinct view; individual setup requests consume the seven-request budget. Reuse common scale across those panels before adding further campaigns.
2. The model still emits malformed outer/argument fields or free-text end/scale structures that do not match the current description shape. Two R-3view cases reach `describe_vessel` but are not accepted before the budget. For example, a scale string `1:100` inside principal dimensions is rejected by the numeric principal-field validator; this should become preserved extra metadata plus a warning, not repeated failed requests.
3. On degraded body plans, dark annotation/grid/curve ambiguity corrupts measured extents. Pixel measurement is not a guarantee of hull identity.
4. LOA/draft are not independently observable in body-only sheets without dimension text. Keep those claims inferred/unknown; do not tune them to development truth.
5. Waterline checks need separate panel calibrations and explicit handling of baseline versus labelled waterlines. Missing-grid paths must warn on incomplete sets, not merely empty sets.

No larger campaign was run.

## All attempts and cost

| Attempt group | Provider receipts | Known list cost USD | Missing list cost |
|---|---:|---:|---:|
| Initial smoke: venv resolution failure | 0 | 0 | 0 |
| First retry: disk full | 0 | 0 | 0 |
| Round 1 resumed (2 cases) | 14 | 0.02755969 | 0 |
| Round 2 body smoke | 12 | 0.02045402 | 0 |
| Round 2 body remainder | 14 | 0.02590729 | 0 |
| Round 2 three-view | 14 | 0.02480625 | 0 |
| Round 3 body smoke | 11 | 0.02323592 | 0 |
| Round 3 body remainder | 14 | 0.02446444 | 0 |
| Round 3 three-view | 14 | 0.02666258 | 0 |
| **Total** | **93** | **0.17309019** | **0** |

Final round total: 39 provider requests, USD 0.07436294 list cost. All six final tasks have zero CAD build events; these are Phase 1 checks only.

All-attempt cost per case: DTMB body $0.04283931; 00683 body $0.02841032; 00045 body $0.02899069; 00679 body $0.02138104; DTMB three-view $0.02584388; 00679 three-view $0.02562495. Raw attempts and frozen runtimes stay under main `work/w20a/`; compact totals are in `all-attempt-costs.json`. OpenCode reported billed cost zero; the table uses nominal list cost, not a claim of zero resource use.

## Verification

- Focused description/tool tests: 14 passed after final fixes.
- Rust phase-catalog and response-format regression tests passed.
- Offline checker tests: 2 passed separately (missing descriptions remain failures; warnings do not turn wrong dimensions into passes). These tests were added after the full suite started and are reported separately from its Python count.
- `make test-quick`: passed on final source: Rust workspace, format, Clippy, 853 Python tests, 24 CAD tests deselected, secret pattern scan zero findings.
- Initial `make test-quick` failed on disk exhaustion during Rust compilation. A later retry was stopped intentionally for review fixes; it is not a pass.
- `make test-full`: running; final outcome will be recorded before commit/report completion.
- Automatic security review of the initial Python commit did not complete (HTTP 404); details in `~/.claude/security/log.txt`.

## Commits

- `2d21065` — Python survey/description, persistence, first-hull adapter and tests.
- `bc17323` — Rust tool types/catalog, phase sequencing and Phase 1-only CLI option (cherry-pick of `28c7cb4`).
- Final corrective/report commit: the commit containing this report (see `git log -1`); phase-scoped tools, response-format normalization, review regressions and full development evidence.

## Resume

Do not expand evaluation. Next work is to finish full verification and commit this checkpoint; then improve common-panel setup reuse, description shape guidance and per-panel waterline measurements. Keep the acceptance failure visible. Use only development inputs and retain failed-attempt costs.
