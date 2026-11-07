# MarinaFrame 0.4: implementation, experiments and limits

**Report date: 7 November 2026, Asia/Singapore.** This release continues the published, unmerged 0.3 source in draft PR #2. It implements a Rust control plane around the retained Python/CadQuery/OpenCascade workers and exercises actual DeepSeek image-and-tool trajectories. It is a research system for provisional hull envelopes, with `engineering_approved=false` throughout.

This report distinguishes application behavior, selected-trace fidelity, independent shape accuracy and professional engineering review. They are different claims. A valid solid or a passing audit of a wrongly selected trace does not establish the intended hull.

## 1. Decision and scope

The foundational harness concept now works end to end: source evidence can drive constrained decisions, native construction, renders reimported from exported STEP, a model-visible comparison, a source-backed selection change, another build and fresh validation. The cache defect has been repaired and independently reviewed in both control planes. Actual browser interventions and process/crash recovery have also been exercised.

The strongest live revision evidence is a **controlled development fault**, with an explicitly seeded grid-line interpretation and actual initial STEP images. It is not an unassisted reconstruction benchmark. Independent STEP measurements of one successful revision found sampled half-breadth RMS improve from **2.880574 m to 0.048361 m**, while a **1.302507 m endpoint error remained**. Four earlier natural continuations of the historical centroid candidate retained it. Thus useful model-directed correction is demonstrated; reliable autonomous semantic interpretation is not.

Rust provides explicit state ownership, typed boundaries, immutable request/receipt accounting and supervised workers. It did not accelerate CAD in the controlled comparison: mean end-to-end time was **4.0–11.3% longer** on the three successfully paired case types. Geometry was unchanged, including byte-identical STEP `DATA` sections in all six successful pairs. Native workers remained the dominant memory users.

On the new sealed supported cohort, published 0.3, current Python, current Rust and live DeepSeek each passed all eight drawings from four paired families. This is no observed pass-rate gain over 0.3, and the current automatic arms produced identical geometry. Section 7 reports the small numerical differences, refusal outcomes and limitations.

Authentic acquisition and actual local weight training progressed. The additional six ALMA files represent one additional vessel, not six independent designs. The trained small classifier improves a narrow procedural pixel-labeling task and is not enabled in production reconstruction. No DeepSeek weights were fine-tuned; there is still no expert-reviewed authentic whole-hull ground truth.

### Supported task

A caller supplies a drawing plus section panels, longitudinal station positions, calibration, datum, elevation domains, symmetry and closure assumptions. MarinaFrame extracts source-backed alternatives and builds an interpolated envelope. It does not recover an arbitrary complete ship from an uncalibrated photograph or infer structure, compartments, thickness, systems or as-built condition. Blender is not used. The model never receives a general code-execution or arbitrary-coordinate tool.

The [README](../README.md) contains install and run commands. The detailed evidence is split across the reports linked below and the corresponding `artifacts/v04/` directories. Historical reports remain historical; their results are not counted as new experiments.

## 2. Exact baseline and implementation identity

| Identity | Value and meaning |
| --- | --- |
| Published continuation base | `5b0b48e3dd9bcef25427d27ce800118935f58d1a`, `harness/v0.3-source-reviewed`, draft [PR #2](https://github.com/MarinaChain/MarinaFrame/pull/2) |
| Reviewed historical comparison | `2b9ab4f905aff3dbbfed9a8c134ea85fad766546`, draft PR #1 |
| Original 0.3 delivered revision | `49d98550557f77dffd0e97cffa0a9f7a6eae88b0`; different history from the later source publication |
| Original 0.3 application freeze | `0ba5a49efd1a54bc62bbe5ff44ce219e70c705cb` |
| Current application freeze | `8916e68f4c175bdab291d7c0bf2978862be8915d` |
| Frozen optimized Rust binary SHA-256 | `071d76828b845d0134e57a3f4c14e48fc2843027cfa45806de5d67767d5b6f72` |
| Frozen runtime inventory SHA-256 | `a7aea135d54d3873715dc6849dacfd87ae67ab882064add8c708370983a24684` |
| Local continuation branch | `feat/rust-visual-harness-v0.4` |

The two old draft PRs were verified open and unmerged. Exact-head remote CI for published 0.3, run `42286809166`, succeeded. That result belongs to the historical head and does not validate this new work or disprove the reproduced cache defect. No new changes have been pushed, no PR merged and no application deployed. New verification is local.

The delivered 0.3 archive's 4,482 manifest entries were checked. All 54 compared application/test files matched published source; two documentation files had been sanitized for publication. The baseline suite was rerun unchanged: **411 passed in 96.03 seconds**. The archive SHA-256 is `65773e91a1a392f6f549e97fb9d83d26a8f6869d64bc4e171255c39627be43b2`. The separate known47 raw archive identity is retained in the baseline evidence. Application freeze, later documentation commits and final archive identities are recorded separately.

Evidence: [baseline inventory](../artifacts/v04/baseline/), [validation fix report](VALIDATION_FIX_RESULTS.md), and the local commit history/patch delivered with this release.

## 3. Cached failed validation: reproduced, fixed and reviewed

The unmodified 0.3 controlled probe reproduced the reported defect using original product methods and an injected failed CAD audit. Its first validation returned false; the cached second validation returned true despite `geometry_checks_passed=false`. The controller then reached `awaiting_human_review`, with one audit and `engineering_approved=false`.

This is a state/contract defect, not evidence that a professionally approved real hull was produced. The minimal repair was landed before migration. In the repaired probe, fresh and cached results both remained false and finalization was blocked.

The complete repair is stronger than changing one envelope boolean. The versioned `marinaframe.validation.v1` contract binds the conclusion to source/specification hashes, selected alternatives, current generation and revision, immutable run inventory, exported STEP, implementation identity, tolerances, measured values and referenced evidence. Exact booleans and finite numeric values are required. A cached conclusion must still match its authoritative raw audit and artifacts. Python canonical comparison does not allow `True == 1` to substitute a Boolean for a numeric field.

Both controllers now treat a cache hit as a reuse property, never as evidence of passing geometry. Finalization checks the full current contract. Selecting A, then B, then A again does not resurrect old render or audit readiness under a newer revision. Source, STEP, validation or inventory changes fail closed.

Author-separated Python review found and drove corrections to a finalization/domain-lock race, cancellation during predicate checking, and Boolean revision acceptance. Independent Rust review exercised contradictory and malformed native receipts, invalid numeric/Boolean values, changed source/STEP identities, stale generations and revisions, missing evidence and altered context. The new Rust predicate independently interprets the native result rather than trusting the bridge's `ok` field.

A retained actual native failure provides a separate geometry-backed check: the raw source audit reported **43.264475 mm against 1.1 mm** at terminal retraced spurs. Fresh validation, cache reuse, restart and finalization all retained failure, with one actual audit and no repeat audit on the cache path. A separate actual passing case measured **0.896516 mm**, reached provisional review readiness and remained unapproved for engineering.

The raw-spur result was not waived. Cap construction removes retraced zero-area strokes; raw source samples still include them. The current release preserves the mismatch and original metric. A future material-boundary interpretation would need a separately versioned definition and both scores, not a retrospective pass.

Evidence: [contract](VALIDATION_CONTRACT_V1.md), [independent Python review](INDEPENDENT_PYTHON_VALIDATION_REVIEW.md), [independent Rust review](INDEPENDENT_RUST_REVIEW.md), [validation artifacts](../artifacts/v04/validation/), and [author-separated native review](../artifacts/v04/data-author-validation-review/).

## 4. What Rust owns, and what Python still does

The executable Rust controller owns task states, decisions, durable event commits, request intent/receipt reconciliation, checkpoints, provider calls, cancellation, resource admission and finalization. Its Python bridge invokes `DomainTools`; it never delegates task authority to the previous Python `Harness`. The Python domain checkpoint is subordinate worker state. The old harness remains available only as an explicit separate comparison/fallback command.

| Boundary | Authoritative behavior |
| --- | --- |
| Input and decisions | Strict versioned types; finite values, units, IDs, bounds and permitted operations checked at both sides |
| Tools | `inspect_source`, `select_contours`, `build_provisional`, `render_candidate`, `validate_candidate`, `finish` |
| Persistent task | Hash-linked immutable events with committed state; checkpoint is recoverable only from an exact committed prefix |
| Native worker | Narrow JSON protocol, private child process group, scrubbed environment, CPU/memory/wall/log limits |
| Provider | Fixed integration, explicit transfer basis, durable request intent, bounded image payloads and typed response validation |
| Review readiness | Current complete validation plus required current render receipts; never a model assertion or actor label |

The model can choose retained source-supported contour alternatives. It cannot invent coordinates, change calibration/units/tolerances, choose arbitrary paths, run shell/Python, edit scoring, hide failures or approve engineering. A candidate with unresolved non-grid competing components requires explicit operator interpretation rather than silently adopting the darkest line.

Structured source observations persist across tool results, bounded to 12 sections and 96 KB with omissions recorded. At most four images of at most 196,608 bytes each enter a request. Source/candidate identity, pixel dimensions, image hashes and the exact request payload are retained. Model derivatives are downsampled/palette-reduced display images; original pixels remain in evidence and geometry is not measured from the derivative. Faint detail can be lost at that boundary and is disclosed.

Render workers independently reimport the exported STEP. Body, plan, profile and oblique views are available. Live finalization requires completed requests containing both **current body and current oblique pixels**, plus a current passing audit. Older renders are retained for comparison but cannot satisfy current readiness. This guard rejected an actual model attempt to finish after claiming it had seen CAD when the required current views had not yet been transmitted.

Input geometry uses metres; CAD, STEP and STL coordinates use millimetres. STL has no inherent unit declaration. Station `x` is supplied, half-breadth `y` is measured and elevation `z` is positive upward. Symmetry, terminal caps, top closure and nonzero lower closure remain explicit assumptions.

### Execution bounds and accounting

The campaign explicitly has no aggregate request/token/spend ceiling. The previous eight-/six-call pilot allowances are not reused. Operating bounds remain: 90 seconds and 2,048 output tokens per provider call; 210 seconds wall, 180 seconds CPU and 5 GiB address space for the outer worker; retained inner native limits of 180 seconds wall, 120 seconds CPU and 4 GiB. Native admission is serialized, with a bounded queue; task disk and worker logs are bounded. No-progress detection tracks operation, arguments and generation rather than allowing artificial revision changes to evade it.

Each provider action records intent before launch. Credential/preflight failures remain `not_sent`; once transmission may have begun, an interrupted operation remains unknown until a receipt supports a stronger conclusion. Unknown requests are not blindly retried. An explicit continuation acknowledgement preserves the old uncertainty while permitting a new decision. Completed, failed, not-sent and unknown counters are separate; missing cost is never coerced to zero.

Transient 429/502/503/504 responses have at most three bounded retries. Supported numeric `Retry-After` values up to 30 seconds are respected; longer or unsupported forms defer. There is no alternate identity/endpoint bypass. Invalid response bodies retain an error and body hash rather than the complete invalid text; valid decisions, sanitized requests, image identities and usage receipts are retained. This limits verbatim diagnosis of malformed provider text.

Evidence: [Rust architecture and operations](RUST_CONTROL_PLANE.md), [provider contract](agent-provider.md), [Rust source](../rust-control/src/), and [worker bridge](../src/vessel_reconstruction/rust_worker.py).

## 5. Live development experiments and useful revision

All new live runs used the provisioned OpenCode Go integration and returned identity `deepseek-v4.1-flash`. The authorized credential was supplied in the launcher environment and never passed to native workers or placed in source/arguments/evidence. Only source material with established provider-transfer scope was sent. Synthetic project-generated CC0 drawings were used for the development revisions.

The full experiment ledger preserves every earlier failure and the hypothesis behind each change. Live provider evidence is distinct from mock/replay protocol testing.

Across 46 original development/final-live task attempts, the new campaign recorded **224 intended provider requests: 223 completed decisions and one failed schema response**. Receipts report **2,196,623 prompt tokens and 15,871 completion tokens**, with all 224 explicitly reporting observed cost 0. There are zero new unknown or not-sent requests, no duplicate request IDs and no counter discrepancies. Tasks blocked before calling the provider remain in the task denominator with zero requests. The original 0.3 six completed calls and one unresolved follow-up reservation are separate historical evidence; the unresolved transmission/completion/cost remains unknown. There are 800 image-attachment receipt entries across 200 requests, of which 199 completed. Overall, 39 of 46 histories pass the current strict reader, with 20 current review-ready labels; seven older incompatible histories remain rejected. These are integrity/status counts, not independent accuracy counts.

| Development phase | Observed outcome and interpretation |
| --- | --- |
| First protocol/native probes | An optional-field serialization defect was found and fixed before successful deterministic construction. No failed probe is counted as a live success. |
| First complete live source/CAD attempt | Source pixels, actual body and oblique pixels and a passing audit were reached; an overlong final response failed the bounded schema. Terminal status was provider failure. |
| Early retention/tangency/ambiguity cohort | Six apparent review-ready trajectories and two missing-calibration blocks. Two ambiguity cases were false acceptances. Old numeric receipt incompatibility is separately preserved below. |
| Historical centroid, two repetitions | Both retained the initial interpretation after actual CAD inspection; neither corrected the endpoint. |
| Same centroid with retained source-observation memory, two repetitions | Both again retained it. Four natural continuations across the two experiments did not solve the endpoint defect. |
| Frozen guarded regression cohort | Two easy retentions and two initial endpoint selections reached review; two ambiguities abstained and two missing-calibration cases blocked before provider calls. All eight strict histories verified. |
| Controlled grid prior without prepared initial CAD images | Both revised and rebuilt, but revision occurred before seeing the initial CAD pixels. Useful source correction, not proof of repair prompted by initial CAD inspection. |
| Controlled grid prior with prepared body and oblique images | A genuine pixel-visible revision workflow. Five explicit assistant setup actions per attempt are counted; initial two attempts produced one useful revision and one abstention. A fixed four-trial extension was declared before those additional outcomes. |

<!-- LIVE_RESULTS_BEGIN -->
The fixed four-trial extension produced one further revised review-ready candidate and three abstentions. Across all six attempts, **two revised and reached review; four abstained**, with all six current task histories verifying. The initial two-attempt cohort remains separately reported as one revision and one abstention. The two successful revisions selected identical candidate IDs and produced identical CAD-section bytes; they are repeats of the same controlled interpretation, not two independent vessel results. No attempt was dropped, repeated for a preferred result or stopped on a desired success count. Every attempt used the same source, frozen runtime, prompt and five setup actions. The first completed request in all six trials included prior body and oblique pixels bound to that trial's initial STEP, including the four attempts that subsequently abstained. This is repeated but unreliable controlled visual correction, not a natural reconstruction success rate.
<!-- LIVE_RESULTS_END -->

### What the successful controlled trial actually proves

The assistant deliberately selected a retained vertical grid stroke, built it and requested body/oblique renders before live continuation. The model was not given the hidden reference shape, an accuracy score, a correct candidate ID or a fault-answer label. It received ordinary source/candidate evidence and actual prior STEP image pixels. In trial 02 it inspected source evidence, validated the old candidate, selected curved alternatives, rebuilt, requested new views and finished through the host's current validation predicate. Seven live requests and two total builds were recorded. The five setup actions are not credited to the model.

The model sometimes described checks more strongly than its explicit operation sequence justified. Finalization performed a current audit; the report credits that host action, not the model's assertion of having already validated the revision.

An independent evaluator reimported both actual STEP files and intersected all three supplied stations at 4,097 heights each: **24,582 resolved ordinates**. The known development reference supplies 129 declared ordinates per station, linearly interpolated at those same heights; the dense sampling does not create denser independent ground truth.

| Three-station actual STEP comparison | Initial grid interpretation | Revised curved interpretation |
| --- | ---: | ---: |
| Half-breadth ordinate RMS | 2.880574 m / 120.5301 px | 0.048361 m / 2.0235 px |
| Absolute error, 95th percentile | 3.998633 m / 167.3124 px | 0.030322 m / 1.2688 px |
| Maximum absolute ordinate error | 4.108849 m | **1.302507 m / 54.5 px** |

This is a 98.32% RMS reduction for the controlled pair, with a large unresolved endpoint. The station-08 render comparison below uses identical physical axes; it avoids the misleading impression that independently autoscaled renders have the same scale. There is no three-station volume-accuracy comparison against the original 25-station reference hull.

![Actual STEP cuts before and after the controlled live revision](../artifacts/v04/live/independent-measurement/plots/frame08-step-before-after.png)

Evidence: [independent measurement](INDEPENDENT_LIVE_MEASUREMENT_V04.md), [all-station comparison](../artifacts/v04/live/independent-measurement/plots/all-stations-step-comparison.png), [complete live accounting](LIVE_ACCOUNTING_V04.md), and [root visual ledger](../artifacts/v04/live/root-visual-ledger.json).

## 6. Source fidelity: narrower improvements and retained failures

The geometry kernel and acceptance gates were not changed to improve a score. Source processing now preserves connected centreline endpoint evidence as an explicit alternative, with supporting pixel witnesses and the original centroid interpretation retained. It does not infer the known analytic family. Uniform ruler lines, disconnected marks and flat-bottom corners are excluded from that endpoint rule. An adaptive source representation preserves measured row features under a 0.25 px loss bound, with a 1,025-point bound rather than a fixed grid that can erase narrow chines.

The deterministic default still uses the unique centroid interpretation where that is its selected policy. Having a better retained endpoint alternative does not mean every autonomous trajectory selects it. This distinction explains why a pipeline diagnostic can improve a known case while the live centroid continuation still fails.

| Known development experiment | Before | After | Remaining limitation |
| --- | ---: | ---: | --- |
| Published final tangency case, maximum local ordinate error | 133.333 mm | 105.006 mm | Still fails unchanged 66.667 mm / 4 px gate |
| Same case, endpoint error | 133.333 mm | 16.667 mm | First subpixel row and near-tangent region remain underresolved |
| Same case, RMS | 18.417 mm | 19.283 mm | Small RMS regression despite better endpoint |
| Same case, volume error | 2.0201% | 2.0598% | Enclosed-envelope metric, not certified displacement |
| Known47 roundflare diagnostic, maximum trace-to-reference ordinate error | 1.302507 m | 0.089033 m | Explicit endpoint policy, known development input |
| Same roundflare diagnostic, trace-to-reference RMS | 64.418 mm | 23.501 mm | No claim of unseen archival accuracy |
| Same roundflare diagnostic, STEP-to-reference RMS | 64.420 mm | 23.505 mm | Measured sections, not a continuous surface guarantee |
| Same roundflare diagnostic, volume error | 0.6022% | 0.7367% | Small aggregate regression retained |
| Original terminal spur raw audit | 43.264475 mm | 43.264475 mm | Fails unchanged 1.1 mm gate; no waiver |

Actual STEP intersections were used in the geometry studies. The tangency study resolved all 12,291 samples across three sections. Source image/crop inspection, endpoint overlays, section cuts and renders were actually opened, with file hashes and observations in the visual ledgers. Fourteen geometry-study image views and the separate root/browser ledgers are evidence of assistant inspection, not professional review.

A maximum half-breadth ordinate error is a difference at matched elevation; near a horizontal tangent it can be large while nearest-curve distance is smaller. The report does not rename it surface distance. The retained 1.1 mm audit measures CAD approximation to the selected trace and is independent of whether that trace is semantically correct.

Evidence: [source fidelity report](SOURCE_FIDELITY_V04.md), [geometry evidence](../artifacts/v04/geometry/), and 47 focused geometry/source tests plus eight independent STEP comparator tests.

## 7. Independent final evaluation

An author-separated evaluator prepared and sealed new inputs/references before the final application freeze. The input set contains eight supported procedural drawings from **four underlying families**, paired clean/scanned, four expected negatives and three public authentic partial scans. The authentic items are known development sources with no full-hull truth; they are not an unseen real-vessel holdout. Licensed modern complete drawings remain absent.

The isolation mechanism is separate agent ownership and directories, plus committed hashes and frozen runtime copies. It is not an OS-enforced sandbox. Implementation and live execution read only opaque input/transfer indices; scoring and reference geometry were withheld until all solver outputs and the separately preselected assisted attempts were locked. No final scores were used to tune the frozen application.

The evaluator initially supplied fractional ROI coordinates that violated the engine's integer-ROI intake requirement, which the schema-only check had missed. The original seal and all 30 initial intake-preflight attempts are preserved: 24 procedural executions were affected by those bounds, and six authentic-partial executions used unchanged intentionally incomplete specifications. A recorded v2 amendment changed only floor/ceil ROI bounds on 60 rectangles across 12 procedural cases; images, reference geometry, calibration, thresholds and authentic inputs stayed unchanged. That preflight cohort remains separate from the amended-input primary comparison.

The v2 seal SHA-256 is `5a19eb80366f187a63876ac643070d9ad339d5cdd5fae0494a3e19e09c57f52e`; the implementation input-tree digest is `56faaf412e89105aac3628792152749d0099106192049d6394cbb30420c438e1`. Gates were declared as volume error at most 3%, half-breadth RMS at most 2 source pixels and maximum at most 4 pixels, plus geometry/provenance requirements. They are coarse proof-of-concept gates tied to source resolution, not manufacturing tolerances. The selected-trace audit remains a distinct 1.1 mm condition.

Arms include reviewed 0.2, published 0.3 deterministic, current Python deterministic, current Rust deterministic, current Rust live DeepSeek, a CAD-free pixel baseline and a separately counted two-case assistant workflow. The assisted sample was committed by a result-independent selection rule before handoff; it is a diagnostic sample, not a population estimate. Every intervention and elapsed effort is recorded.

<!-- EVALUATION_RESULTS_BEGIN -->
All primary inference outputs locked before reference scoring. The evaluator completed **92 primary executions**: 75 automated CAD-capable attempts, 15 source-only pixel predictions and two fresh assistant-operated attempts. All five automated CAD arms produced terminal records for their 15 inputs. There were no primary inference execution failures, watchdog interruptions or resource-limit terminations. The 30-attempt initial intake preflight cohort remains separate: 24 procedural legacy attempts were affected by fractional ROI bounds, while six authentic-partial attempts used unchanged intentionally incomplete specifications. The total is 122 launched case executions across this evaluation, not 122 vessels.

| Automated CAD arm | All attempts | Correct / all supported attempts | Correct / completed supported exports | Both conventions pass | Explicit refusal, original four negatives | Safe diagnostic nonacceptance, original four |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Published 0.2 | 15 | 4/8 | 4/4 | 0/4 families | 4/4 | 4/4 |
| Published 0.3 | 15 | 8/8 | 8/8 | 4/4 families | 2/4 | 3/4 |
| 0.4 Python deterministic | 15 | 8/8 | 8/8 | 4/4 families | 2/4 | 3/4 |
| 0.4 Rust deterministic | 15 | 8/8 | 8/8 | 4/4 families | 4/4 | 4/4 |
| 0.4 Rust + live DeepSeek | 15 | 8/8 | 8/8 | 4/4 families | 4/4 | 4/4 |

**This set shows no supported-geometry success gain over published 0.3 and no live-model accuracy gain over current deterministic processing.** The four missing 0.2 grid-case exports count as reconstruction failures, even though every exported supported candidate passed. Current Python, Rust and live outputs have identical selected-trace coordinates and raw STEP DATA sections on all eight supported inputs. The 0.3 outputs were measured separately and are not claimed byte-identical. Current RMS is slightly higher on seven cases and lower on one: the largest increase is **0.002791 pixels / 0.024919 mm**, from 0.645162 to 0.647953 pixels on `q_912adc37`. The largest increase in a case's local maximum is **0.037919 pixels** on `q_3bd4178e`. These small regressions remain visible in the paired results, while all cases stay well within the fixed gates. Four paired families are too few and too narrowly authored for a population success estimate.

For current Rust, the worst independent local error is **1.238103 pixels / 12.897 mm**, at the upper endpoint of section s3 in `q_04e5b3a1` (x=8.2 m, z=2.7 m). Maximum case volume error is **0.680231%**, maximum case pooled RMS is **0.679035 pixels**, and maximum selected-trace-to-STEP distance is **0.995502 mm**. These remain below the predeclared 3%, 2-pixel RMS and 4-pixel local gates and the separate 1.1 mm trace gate. Thirty-nine actual exports across all arms were independently measured, including ready candidates on the scope-ambiguous diagnostic and the one assisted export: **195 station cuts, 798,915 required ordinates and 25,243 source-centre trace samples**, with no unresolved ordinates or instrument failures. The reference curves are independently authored procedural truth, not surveyed vessel truth.

![Independent STEP error against the fixed source-resolution gates](../artifacts/v04/evaluation/visual/supported_geometry_errors.png)

The refusal improvement is chiefly clearer terminal handling. Both Python harnesses reach `no_progress` with relevant input-gap diagnostics for missing declared scale and the three authentic incomplete specifications. Rust/live explicitly block these four inputs. A safe diagnostic no-progress stop is counted separately from an explicit correct refusal; it is not called a crash or a successful reconstruction.

One original negative label requires a qualification recorded **before outcome review**. `q_b970f41e` contains closed interior loops inside a continuous exterior profile. Its original refusal expectation is retained, and the ready 0.3/current-Python candidates violate that expectation. However, an exterior envelope that ignores interior loops is not thereby established to be incorrect hull geometry. On the separate three-case sensitivity set excluding this case, 0.2/Rust/live explicitly refuse **3/3**; the two Python harnesses explicitly refuse **2/3** and safely stop with the appropriate missing-scale gap on the third, giving **3/3 safe diagnostic nonacceptance**. The current Rust refusal of the interior-loop source may be conservative rather than an accuracy improvement. Disconnected exterior topology remains unmeasured by this diagnostic.

All arms withheld a ready hull on the three authentic partial sheets. Those inputs lack complete required station/calibration/symmetry declarations; the result demonstrates input-contract handling, not visual recognition of every historical drawing limitation. No authentic 3D/volume success rate is assigned. The scale-negative image even retains a visible scale bar: its missing specification field tests the supplied-calibration contract, not automatic OCR.

The simple pixel baseline resolved **10,451/10,460 source rows (99.914%)**, with per-case RMS **0.634–0.714 pixels** and maximum **1.137–1.389 pixels** on resolved rows. Nine unresolved rows remain in coverage. It produced no CAD and is not counted as a correct 3D reconstruction. Its strong source tracing also shows how tractable these supplied, single-trace procedural panels are.

The final live arm's 15 cases used **74 completed requests**, 752,723 prompt tokens and 5,590 completion tokens, with all 74 explicitly reporting observed cost 0. The separately reported nominal `list_cost` sum is $0.11304483; invoice/subscription cost is unknown. Outcomes were eight ready, three abstained and four blocked. Each supported case used one build. Thus these final live trials establish tool use and current-pixel review, not a new repair or model-accuracy advantage. Actual STEP pixels were included on 27 completed requests; three premature finish attempts were rejected and remain in the accounting. The controlled development repair in Section 5 is a separate experiment.

The fresh reference-blind assistant passed **1/1 supported case** and explicitly abstained on **1/1 equal-contour case**, with six recorded interventions across two primary attempts and no extra attempts. This is an assistant sample, not a human or naval-architect arm. Its 554.012-second session includes measured subprocess wait and unmetered viewing/orchestration; zero external task-provider calls does not mean zero assistant conversation cost.

Product-default latency includes different render schedules, queue accounting and live admission/provider pauses, so it is not used to claim Rust speed or model efficiency. The separately controlled comparison in Section 8 aligns operations. The evaluator and root actually viewed source and STEP pixels, including the worst current case and the interior-loop diagnostic. The complete independent report includes every case, per-case CSV/JSON, exact metric definitions, resources, missing spans, false refusals, scope sensitivity, instrument corrections and verification of all original output/runtime hashes after scoring.
<!-- EVALUATION_RESULTS_END -->

The live runner captured and checked every source/specification against an explicit transfer-rights mapping before first provider use. The 15 live outputs were locked at `2026-11-06T22:32:50.751893+00:00`, output-lock SHA-256 `aa6c7fb5a6cb333b68ee9b1f2d1ba3a33f7ba063cc4aba0c1917fe73fa79070d`. All 15 completed task histories passed current integrity verification. This statement does not imply all 15 produced correct CAD. Its capture/pause step adds recorded overhead and is not the same schedule as a raw default deterministic run.

The evaluator's 900-second external backstop is an experiment interruption limit, not a product refusal category or the user's aggregate provider budget. Any interruption is reported as such. The pixel baseline produces no CAD; its latency is not compared as feature-equivalent product performance.

Evidence: [independent evaluation report](INDEPENDENT_EVALUATION_V04.md), [complete per-case evidence](../artifacts/v04/evaluation/), and [locked live evidence](../artifacts/v04/live/final-evaluation/).

## 8. Controlled Python/Rust parity and performance

The parity study used the identical frozen Python geometry engine, installed dependencies, source selections, operation arguments and body/oblique render counts. Python ran a named aligned policy in its persistent harness; Rust used its deterministic policy. The comparison does not impose an artificial separate-Python-process penalty on every Python step.

Twenty main trials cover five case types, two arms and two fresh-task repetitions: three straight stations, the known47 25-station source, a separate degraded 25-station development drawing, unequal section-height domains and a genuine partial archival input. Twelve trials reached review readiness and eight refused. All 20 main histories and four cache/queue probe histories verified. Six successful pairs qualify for timing ratios; refused pairs are excluded.

| Case | Python first / second wall seconds | Rust first / second wall seconds | Rust mean overhead |
| --- | ---: | ---: | ---: |
| Straight, 3 stations | 14.70 / 14.38 | 15.81 / 16.53 | 11.2% |
| Known47, 25 stations | 134.26 / 131.65 | 139.09 / 137.44 | 4.0% |
| Unequal height domains, 3 stations | 18.50 / 16.84 | 20.50 / 18.83 | 11.3% |

All six successful pairs have identical normalized decisions, candidate IDs, CAD-section bytes and mesh bytes. STEP `DATA` sections are byte-identical; full file bytes differ in export timestamp headers. Independently reimported length, beam, depth and volume deltas are zero. Selected-trace maximum deviations match: 0.896516, 0.855503 and 0.957704 mm respectively.

The degraded source led both controllers to inspect one batch and abstain without CAD because there was no unique supported contour choice. The genuine Balclutha partial input was blocked because the caller had not supplied a complete calibrated station set and explicit closure/symmetry assumptions. This is input validation, not autonomous visual recognition of whole-vessel incompleteness.

Sampled controller-only memory was lower for Rust, approximately 7.1–22.5 MiB versus Python's 22.9–47.8 MiB case maxima. Rust also had bridge processes of about 32.2–44.1 MiB. Common native workers dominated at 531–1,211 MiB. Separate sampled maxima are not summed into a fictional whole-service peak. CPU accounting preserves waited-descendant semantics rather than double-counting overlapping receipts.

Explicit cached validation took 0.164 seconds for Python and 0.490 seconds for Rust, both `reused=true`, with zero new builds or audits. Under a deliberately approximately one-second held native admission lock, measured waits were 0.934 and 1.006 seconds, with no CAD. Original cache task bytes were independently inventoried before copying, matched the copy and remained unchanged. The clean and degraded 25-station cases use different procedural seeds, so their comparison does not isolate degradation of one identical hull.

There was no OS page-cache flush; first/second fresh tasks are not controlled cold-hardware trials. Two repetitions on a shared host support this bounded comparison, not a universal language ranking. Independent review strengthened eligibility checks before publishing ratios; fourteen positive/negative analysis-gate checks passed without rerunning timed native work.

Evidence: [parity report](CONTROL_PLANE_PARITY_V04.md), [analysis](../artifacts/v04/control-parity/analysis.json), [independent review resolution](../artifacts/v04/control-parity/publication/independent-measurement-review.json).

## 9. Authentic data and actual training

The acquisition ledger reconstructs the named sources: Balclutha HAER CA-54, Wapama HAER CA-67, USS Monitor NH50954, the mathLab DTMB 5415 reference, ALMA HAER CA-60 including its third-party-hosted files, and Hercules HAER CA-62. No previously named modern commercial vendor, account or download entitlement was present in the accessible project/context. That specific missing information remains a gap; the user's local training/testing authorization was not re-requested.

Six ALMA originals were downloaded, **725,271,046 bytes**: five drawing files and one cover, one new vessel. The resulting authentic inventory has **11 items, 10 drawings, four vessels and three source families**, all development material. Hercules and a prior ALMA HAER path returned 403; attempts and denials were retained, without bypass or unauthorized mirrors. A drawing mention is not counted as a download.

Rights are recorded per purpose. The ALMA local use basis is owner-authorized training/testing, contract not independently inspected. External-provider inference and unrestricted redistribution are not inferred from that permission. ALMA originals and derivatives remain in the restricted local evidence tree and are omitted from unrestricted archives. The exact public-data release allowlist supplies 485 permitted files with hashes. Acquisition metadata and limitations remain available without distributing restricted imagery.

The annotation workflow covers views/panels, station positions, datum/scale, literals/units, contour alternatives, semantic identity, missing spans, feature landmarks, assumptions, source links, roles and unknowns. Eleven annotations passed installed full Draft 2020-12 schema validation. They contain 73 features, 43 newly added; 45 raw offset literals remain unresolved rather than being promoted to measurements. Schema validity does not establish semantic correctness. There are **zero expert-reviewed gold sets and zero authentic whole-hull ground truths**.

The strict training exporter emits zero rows where professional-quality label requirements are unmet. A separate provisional export contains 61 rows and was not used for the weight experiment. Review packets retain overlays, questions and source ambiguities for an eventual qualified reviewer; no naval architect was impersonated, contacted or hired.

### Local classifier experiment

A small NumPy multilayer perceptron with **18,594 learned parameters** was trained on procedural local ink-label features. Each run made **4,320 gradient updates**. The split used 144 training panels/6,912 queries, 36 validation panels/1,728 queries and 36 final-test panels/1,728 queries. The two experiments together cover 252 unique procedural panels. Inputs were already isolated supplied ink locations represented by two pixel patches, without coordinates, family IDs or reference CAD supplied to the learner. Crossings and locations within three pixels of the other class were excluded. This is not full-page detection, dense-crossing segmentation, OCR or whole-hull reconstruction.

The second experiment's final balanced accuracy was **96.5856%**, against **80.7870%** for the strongest expanded deterministic heuristic: +15.7986 percentage points, panel-bootstrap 95% interval 11.2269–20.8912. It still made 56 contour-to-grid and three grid-to-contour errors. Both optimizer runs reused the same training/validation panels and selected identical learned weights. Run 1's heuristic search reached its original upper bound; run 2 expanded that search and reserved a new tumblehome test family. The earlier reverse-flare test is now development knowledge. This is one learned configuration evaluated in two procedural experiments, not two independent training replications. Labels came from the procedural renderer, not independently interpreted archival drawings.



A late security review found that the historical learning environment used Pillow 12.3.0. Its official audit returned 59 advisory records forming 41 alias-connected groups. The recommended optional learning lock now uses the base environment's Pillow 13.0.0 pin/hash; its two-package NumPy/Pillow requery returned no findings. This is a security correction to optional learning setup after the inference freeze, not a change to the evaluated reconstruction runtime. Historical environments, input images, labels and weights were preserved. A compatibility replay of 36 original PNGs / 1,728 queries under old/new Pillow produced byte-identical decoded pixels, features, normalized arrays, probabilities and predictions, matching recorded metrics exactly; all 43 original artifacts remained unchanged. It did not retrain the model or establish a new untouched final test. Fresh data regeneration/training under the updated dependency was not independently repeated. The standalone five-item public subset was separately installed from eight exact, hashed Python dependencies in a fresh minimal environment (NumPy 2.3.5, Pillow 13.0.0, JSON Schema validator 4.26.0). Installation, `pip check` and strict dataset construction all passed; it correctly emitted zero gold/training rows. No CAD job, provider request or training execution was needed for that check.

This is actual local weight training, with initialization, configuration, checkpoints, split identities and logs retained. It is not DeepSeek fine-tuning, retrieval-augmented generation or demonstrated real-scan accuracy. No provider training endpoint was invented. The model remains experimental and disabled in reconstruction because cross-domain labels/evidence are insufficient.

Evidence: [data and learning report](DATA_LEARNING_V04.md), [rights/acquisition inventory](../artifacts/v04/data/), [public release allowlist](../artifacts/v04/data/release-allowlist.json), and the data acquisition/annotation/training scripts under `scripts/`.

## 10. Recovery, compatibility and workspace publication

Author-separated controlled process tests exposed a real worker-lifecycle defect: a normally exiting worker leader could leave descendants alive. The fix observes completion using `waitid(WEXITED | WNOHANG | WNOWAIT)`, terminates the remaining process group while the unreaped leader pins its identity, then reaps it. Cancellation uses the same identity-preserving approach. This is a product fix, separate from the external workspace issue.

Six new independent tests cover normal-exit descendant cleanup, TERM-resistant cancellation, parent SIGKILL/death signaling, missing and late worker receipts, unknown-provider acknowledgement/restart without duplicate counters and source changes before intent. The TERM-resistant case took about 2.06 seconds; controlled parent-death cleanup about 0.154 seconds. These used real controlled processes and fake protocol workers, not live service attacks or CAD-accuracy claims.

A second product bug was exact float round-tripping. Enabling `serde_json`'s `float_roundtrip` feature prevents a value from being read as a different finite float and then changing exact evidence comparison. A permanent 12,000-value test passes. One previously rejected development event chain now verifies with its original bytes unchanged.

Seven older development histories remain rejected by the final reader at `cached_raw_audit_disagrees`. Independent offline diagnosis reproduced all fifteen numerical differences with the old parser; one example drifted from `20.849681027691894` to `20.849681027691897`. All 1,231 inspected old files remained unchanged. These records are preserved as incompatible old evidence, not rewritten into stronger current assurances. Four of the seven were accepted by their older readers; three also suffered old event-chain mismatch.

### Workspace anomaly: mitigation, not solved root cause

The fresh installed legacy-agent smoke reproduced a publication anomaly when active output was placed in the workspace. Native build and render succeeded, then validation found restored run-lock/staging debris and failed closed. A marker's modification time preceded publication while its change time followed publication; no matching worker was found during later inspection. The original task and debris remain preserved. A separately labeled copy of just the published run verified, but it was not used to promote the original failed task.

The same unchanged wheel/source passed when active output was under `/tmp`. Completed-only imports verified across later tool boundaries. An independent 48-round, four-lane probe checked 192 trees/576 files, 2,304 repeated hash checks over six minutes, without reproducing the native anomaly; its positive corruption control was detected. That controlled probe does not prove the external behavior is fixed or identify its actor. A release-stage observation also found a temporary ZIP path reappearing at a later workspace boundary after its successful rename. Both completed auxiliary archives still matched their exact hashes and every member. The incomplete duplicate is retained as forensic evidence outside the delivery, with its identity recorded; final source-archive construction uses `/tmp` and a completed-only verified copy. This is additional evidence of the unresolved publication behavior, not proof of its root cause.

All subsequent native experiments ran under `/tmp`, with completed-only copies into evidence and checks before/after transport. No integrity guard was relaxed, no manifest was regenerated over changed historical bytes and no refused tracing mechanism was bypassed. `/tmp` is execution scratch, not durable storage; deliverable copies and manifests preserve completed evidence.

Mutation of a task requires its captured controller and worker identities. After an upgrade, use a new task or retain the matching runtime. `recover-checkpoint` accepts an absent checkpoint or an exact older committed prefix; it does not adopt arbitrary corruption, partial worker state or an unknown provider outcome. The repaired current Python controller is an explicit fallback with a separately recorded authority, never an automatic replacement inside a Rust task. Frozen 0.2/0.3 versions remain comparison baselines. Completed tasks verify after relocation, as the copied-evidence checks demonstrate; continuing a historical task still requires its recorded runtime identities, paths and dependencies. This release does not implement automatic cross-machine checkpoint migration. Create new tasks using the installed local runtime paths. The integrity CLI also acquires its task lock in writable mode. The fresh assistant sealed its outputs with read-only file permissions; post-seal CLI verification therefore returned `task_lock_open` until a separate exact-byte copy made only the two empty lock files writable. Both copied histories then verified; all 274 original/copied file bytes stayed unchanged, and the original read-only evidence was preserved. This permission requirement is a usability limitation, not a repaired or waived content-integrity result.

Evidence: [independent reliability report](INDEPENDENT_RELIABILITY_V04.md), [Python installed verification](PYTHON_VERIFICATION_V04.md), [Rust operations](RUST_CONTROL_PLANE.md), and [reliability artifacts](../artifacts/v04/reliability/).

## 11. Actual review workflow and visual inspection

The local `rust_review` server displays Rust state and invokes typed Rust CLI actions. It is not another authoritative controller. It binds loopback Host/Origin, a session/CSRF mechanism, restrictive content policy and resource limits. Live-provider tasks are read-only in this UI. Action requests bind task ID, event head, generation and revision, checked atomically under the Rust lock.

An actual browser session changed a contour alternative from 2.483333 m to 3.0 m beam, built and inspected the candidate, rejected a stale tab with HTTP 409, restored the source selection through A→B→A, and exercised cancel/resume. The final task had three builds, five typed assistant interventions, 17 operations, 12 deterministic decisions, 80 events and 344 verified artifact references. It made zero provider calls and ended at provisional review with engineering approval false. The final selected-trace audit maximum was 0.896516 mm.

Eleven screenshots were actually viewed, covering desktop/mobile layouts and state transitions, with zero page errors or external network requests in the recorded session. Seventeen review tests passed, including independent rerun after fixing stale-resume atomicity and malformed surrogate input. Generic resume/cancel acknowledgements do not preserve a separate free-text actor note; the five typed interventions are correctly labeled assistant actions. Local actor strings are not authenticated professional identities.

Root and workstream visual ledgers record exact image paths/hashes, actual viewing, observations and limits. Creating a PNG alone is not counted as inspection. The controlled revision renders reveal the initial rectangular sections and revised curves; the independent same-scale figures also reveal the remaining endpoint gap. Source pages, readable crops, alternatives, raw spur failures, STEP section cuts and review states are retained. Source downsizing and omitted observations are visible in metadata.

Evidence: [review guide](RUST_REVIEW.md), [browser/native review evidence](../artifacts/v04/review/), [geometry ledgers](../artifacts/v04/geometry/), and [root live ledger](../artifacts/v04/live/root-visual-ledger.json).

## 12. Verification, dependencies and release conditions

The exercised target is Linux x86_64 with Python 3.12.14, Rust 1.99.1 and CadQuery 2.7.0. Other operating systems/architectures are untested. The optimized executable is dynamically linked to the system runtime. The runtime deliverable includes that executable, this project's wheel, lockfiles, instructions and notices; it does not redistribute the full Python/native environment.

| Verification | Result and scope |
| --- | --- |
| Published 0.3 baseline | 411 Python tests passed, 96.03 s |
| Current complete Python suite | **670 passed**, 112.90 s; no failures, errors or skips; source hashes unchanged |
| Current complete Rust suite | **26 distinct substantive tests / 54 executions**, 94.99 s; one ignored helper is executed within the parent-death test |
| Formatting and lint | `cargo fmt --all --check` and locked Clippy with warnings denied passed |
| Clean Python environment | 59 unique locked packages matched; `pip check` passed; non-editable installed module identity verified |
| Installed engine smoke | 9 checks passed, actual native construction/reimport |
| Installed old Python-agent path | Original workspace attempt failed closed; unchanged `/tmp` rerun passed six checks |
| Installed optimized Rust path | Nine checks passed without `PYTHONPATH` or provider key; actual STEP build, body/oblique rendering and audit |
| Browser workflow | 17 tests plus actual desktop/mobile intervention session; separate from geometry accuracy |
| Optional old Python live replay | Not run: optional historical transcript absent from this checkout |
| New remote CI | Not run: new work was not pushed; local results are not remote CI |

The tested wheel's SHA-256 is `7c2ac885d9c49fbe7478b6c1bcddc35f1ef90e3ae0e2edba8fa1cbb2749869fb`. A later delivery wheel refreshes README metadata only; its executable package and data bytes are compared member-by-member against the tested wheel. The delivery wheel is 195,930 bytes, SHA-256 `6b422e6b84280440c1164aea0767078936d8b9ce814fc0157abbac130fdd6e59`; only `METADATA` and `RECORD` differ. Both identities and the comparison are retained. This is not described as a second independent native environment validation. The final runtime ZIP was then extracted to a fresh path, every one of its 460 payload members was verified, and the packaged executable/help plus all nine installed Rust smoke checks passed in 16.20 seconds of smoke execution. That check reused the already validated native dependency environment without changing it; it is a package/path verification, not another independent dependency installation or accuracy trial.

The separate historical learning Pillow finding and corrected current optional install are documented above and in the dependency addendum. The older Pillow results are not silently relabeled as a clean historical environment.

The Rust dependency audit queried all 155 locked packages and reported no known findings at audit time. A Tokio advisory found during the work was addressed by the pinned update; the final Cargo lock SHA-256 is `06350565d56dc32368f51b7f47f79ac6c0bd14e59cfa5b7727d83b825cfd0e7e`. The CycloneDX 1.6 document passed full schema/format validation. These are time-scoped dependency results, not proof that the application or operating system is vulnerability-free.

Three VTK 9.3.1 advisories remain: `PYSEC-2025-224`, `PYSEC-2025-225`, `PYSEC-2025-226`. They are documented with source-routing/GLTF scope, no owner waiver, and review date 7 December 2026. The current supported input routes do not deliberately expose those unrelated import paths, but the installed dependency is not patched by that observation.

Dependency notices distinguish PyMuPDF AGPL/commercial, CasADi LGPLv3+, OpenCascade LGPL2.1 with exception and the OCP wrapper's Apache license. Repository rights, dependency obligations and dataset permissions are separate. The repository's license/visibility remain unchanged. Inspected Cargo archives/manifests and Python wheel/toolchain notices are retained; 32 off-target Cargo package license texts were not independently inspected. No blanket redistribution/security clearance is asserted.

<!-- RELEASE_REVIEW_BEGIN -->
The author-separated preflight scanned 18,960 item visits, 1.960 GB of raw bytes, 62 expanded archive members and 378 reachable Git objects, with no confirmed credential or read/limit error. The completed six-trial addendum covered another 2,744 visits / 76.60 MB, and the accounting/UI addendum 459 visits / 17.48 MB, with no findings. These overlapping item visits are not unique-file counts. The only two initial heuristic hits were the same safely classified FakeTransport test fixture in source and Git; no redaction was required. Exact-key comparison used the authorized credential only in memory, without outputting the value or a key hash. Restricted data was excluded by exact path/hash allowlist. Screenshot OCR, arbitrary encrypted/obfuscated data and exhaustive personal-data analysis are outside the scan.

Release packaging also requires a fresh scan of final source, newly admitted locked evaluation, reachable Git history and then the actual archives. The accompanying `MarinaFrame-0.4-Verification.json` records the completed exits, exact cutoffs, findings and final file identities for those gates. The earlier preflight does not stand in for that final pass. The archive contains the source/history scan; the actual-archive receipt is delivered separately to avoid a self-referential archive hash.

Author-separated packaging review found and drove corrections to post-allowlist supplementation/replacement, mutation between admission and ZIP writing, and report-figure/HTML boundaries. The revised source packager compares tracked bytes with the named Git commit, binds a reviewed completed-evidence snapshot, rechecks exact data identities after transformations, verifies the Git bundle contains the delivery head, and compares admitted hashes/modes during writing. Auxiliary packages require an exact reviewed inventory of the whole staged tree. A final replacement-race follow-up and its valid unchanged control passed; the 17-case review's original failures remain in evidence. All 11 renderer probes passed, including reference-style images, outside symlinks, raw HTML/scripts and external assets. These checks address actual release-tool defects and do not change the frozen inference system.
<!-- RELEASE_REVIEW_END -->

Evidence: [secret/privacy review](RELEASE_SECRET_REVIEW_V04.md), [dependency and license report](DEPENDENCIES_V04.md), [Python verification](PYTHON_VERIFICATION_V04.md), [Rust verification logs](../artifacts/v04/release/rust-verification/), and [installed Rust evidence](../artifacts/v04/release/installed-rust-smoke/).

## 13. Remaining engineering and research work

The next highest-value accuracy work is reliable semantic line/end-point interpretation using independent real annotations, followed by evidence-supported geometry where the present single-valued half-breadth representation is insufficient. A model can faithfully operate the tools and still select the wrong source line. More token supply does not repair absent ground truth or unresolvable calibration.

The tangency case remains above its unchanged local-error gate, the raw terminal-spur case remains above 1.1 mm, and natural centroid continuations retained a large endpoint defect. These plateaus are documented instead of prompting identical repeated calls. The final evaluation is frozen; any future tuning from its errors must reclassify it as development and reserve a new final set.

The specific data gap is a named accessible modern licensed collection/account and independently reviewed reference labels, not a request to reauthorize already cleared local training. The specific provider/distribution gap for ALMA is the uninspected contract scope. The specific engineering gap is qualified review of source semantics, calibration, hull assumptions and any consequential use. No professional has signed off on these candidates.

MarinaFrame remains an assisted hull-envelope reconstruction system. It has not established stability, structural adequacy, seaworthiness, class approval, fabrication readiness or legally sufficient engineering certification. A model, local actor label, valid solid, passing numerical test and hash chain cannot supply those judgments.
