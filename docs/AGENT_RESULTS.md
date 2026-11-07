# MarinaFrame 0.3 — implementation and evaluation report

> **Historical (0.5):** the Python Harness, `vessel-reconstruct agent ...`, `agent_review` and `agent_provider` described here were removed. Rust (`rust-control/`) is the control plane; see `docs/RUST_CONTROL_PLANE.md`. Results below stay as recorded.

**7 November 2026, Asia/Singapore**

**Evaluation freeze:** `0ba5a49efd1a54bc62bbe5ff44ce219e70c705cb`

**Reviewed baseline:** `2b9ab4f905aff3dbbfed9a8c134ea85fad766546`

**Local branch:** `feat/agentic-hull-harness`

## Decision summary

MarinaFrame now contains a runnable domain-specific agent harness around the existing reconstruction engine. It has persistent task state, an allowlisted CAD tool interface, a real DeepSeek provider, bounded visual observations, revision history, cancellation and budget enforcement, exact offline decision replay, and an actual browser review/selection/regeneration workflow. Every candidate remains subject to human semantic review.

The deterministic end-to-end path is demonstrated. The final frozen test produced valid CAD on all eight numeric cases and met the predeclared independent accuracy limits on seven, compared with four passes for the reviewed baseline. A simple pixel-ordinates baseline also passed seven, so the result does not establish an accuracy advantage from model assistance or from CAD orchestration itself.

The live model demonstration is narrower. DeepSeek V4.1 Flash saw source-image pixels, selected source-bound contours, requested a CAD build, observed a publication-integrity failure, and abstained. That is actual model-driven CAD tool use and error feedback, but **not a successful live inspect/build/render/revise/final-candidate demonstration**. Automatic approval review blocked a proposed follow-up. Its interrupted reservation has no provider completion or billing receipt. No mock or offline result is counted as a live success.

The implementation is a research foundation. It does not prove arbitrary archival-plan reconstruction, shipyard manufacturing accuracy, or equivalence to a company's proprietary system. No new neural weights were trained.

## What was built

The model is one decision-making component inside the system. It receives bounded task/evidence observations and may propose one named operation. Trusted code executes that operation and returns measurements, conflicts, source references, rendered images, or a rejection. The next decision can respond to that result. The model cannot execute code, choose filesystem paths, change units or acceptance rules, invent coordinate edits, or grant engineering approval.

The six permitted operations are `inspect_source`, `select_contours`, `build_provisional`, `render_candidate`, `validate_candidate`, and `finish`. Selections use IDs for candidates already derived from frozen source pixels. Geometry is constructed with the existing CadQuery/OpenCascade engine. Render and audit workers reimport the actual exported STEP; they do not merely display an intermediate preview. Blender is not required.

`TaskStore` records a local hash chain of observations, decisions, tool starts/results, artifacts, revision state, operator interventions and termination. Controller events bind the mutable domain checkpoint and captured source manifest. The controller reserves requests/builds before dispatch, carries caps across resumes, charges interrupted time before starting a new deadline, and preserves unknown in-flight reservations. Missing checkpoints, changed sources, unknown operations, unsupported arguments and failed final validation stop the workflow. Local hashes are consistency checks, not signatures or proof of professional approval.

The fixed deterministic policy remains available offline. Mock policies exercise the protocol and are labeled as such. Replay verifies the exact recorded prompt/protocol, tools, observations, images and decisions; it makes zero model calls and executes zero CAD operations. It does not claim to regenerate a new task with different IDs or timestamps.

The source-grammar tools generate several contour hypotheses, preserve competitors and require a uniquely supported non-grid candidate before an automatic selection. Darkness generates a hypothesis; it does not certify contour identity. A faint unexplained stroke prevents automatic selection. A fractional-calibration corridor bug was fixed by using the actual retained raster-row bounds. The original engine's coverage, geometry and immutable-publication checks were retained.

## Final independent comparison

An independent worker created and sealed twelve opaque cases before the inference code freeze: **eight numeric cases from eight analytic families and four expected refusals**. These are procedural synthetic drawings, not eight real vessels. They use three to five stations, a scale of 60 pixels/metre, length at most 12 m and depth at most 3 m. The test is substantially smaller and different from the older 25-station development cases.

The code was committed before any final inference. Source-only inputs were copied to isolated temporary working directories. All solver subprocesses finished before the scorer opened evaluator-only references. The source fingerprints remained unchanged, and there were no retries, target-informed revisions, operator corrections or external model calls. This is procedural input separation, not an OS-level assertion that privileged code could never read other files.

The predeclared numeric gates were: independently reimported STEP volume error at most **3%**; sampled half-breadth RMS error at most **2 pixels / 33.33 mm**; maximum local half-breadth error at most **4 pixels / 66.67 mm**; complete stations, source identity, finite geometry, valid single solid and valid artifact evidence. These are resolution-based proof-of-concept tolerances, not manufacturing tolerances. Extracted and declared CAD section polylines are checked against analytic references, while STEP validity and volume are measured by reimport. This is not a dense full-surface B-rep distance audit.

| Final arm | Numeric cases attempted | Valid STEP exports | Accuracy-qualified numeric results | Expected-refusal score | CAD withheld on expected negatives | Total solver time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Reviewed 0.2 engine | 8 | 5 | **4/8** | **4/4** | 4/4 | 41.04 s |
| Deterministic harness | 8 | 8 | **7/8** | **1/4** | 4/4 | 180.93 s |
| Simple pixel ordinates | 8 | Not produced | **7/8 numerical estimates** | **3/4** | Not a CAD-producing arm | 0.115 s |
| Live DeepSeek harness | Not run on final set | — | No final-set result | — | — | — |

Times cover all twelve cases for each solver arm, including refusals, and exclude later independent evaluator work. The simple arm produces section and volume estimates without CAD construction, provenance publication, STEP reimport or the review workflow; its time is not an equivalent product comparison.

All **13 emitted STEP files** across the two CAD arms independently reimported as valid single solids. That did not make them all accurate. Both CAD arms completed the same out-of-tolerance case: its maximum local half-breadth error was **133.33 mm**, above the **66.67 mm** limit, despite approximately **2.02%** volume error and valid topology. Among completed numeric outputs, correctness was 4/5 for the old engine and 7/8 for the harness; the table retains all attempted cases in the denominator.

The refusal distinction is equally important. All four harness negative cases withheld CAD and had valid task/source evidence, but three terminated through the repeated-operation/no-progress guard. The frozen refusal protocol did not credit that status as a clean refusal, so its score remains **1/4**, with exact diagnostic agreement on **2/4**. Those three cases are not relabeled as clean successes after seeing the outcome. The old engine's exact diagnostic agreement was 4/4; the simple baseline's was 2/4. The deterministic policy's handling of known input failures is a concrete remaining weakness.

Eight small synthetic families do not establish real-world generalization or justify a broad confidence interval. The final references are included for audit and reproduction; future tuning against them turns this set into development data.

**Raw evidence:** `artifacts/agentic/final-evaluation/comparison-0ba5a49/`, including per-case JSON/CSV, source hashes, solver receipts and STEP checks. The frozen protocol and references are in `artifacts/agentic/holdout/`.

## Reproducing and improving the older 0/42 result

The exact reviewed code reran the original frozen 47-case suite: **0/42 numeric completions**, with the five expected negative cases kept separate. Its suite manifest SHA256 was `67230410b389d46fbd3d02be94db7dd1122372d4ff89bb716b8bf5d0ca79381b`. Once inspected and used for iteration, this suite is development/regression data, not an untouched final holdout. Clean/degraded pairs share underlying hulls; the two external rasterizations share one DTMB source.

Visual inspection found real regular grid strokes competing with hull contours. Degraded traces could also jump onto horizontal rulers. The response was explicit source hypotheses and conservative grid grammar, with unresolved alternatives retained. The engine's ambiguity gate was not disabled.

The completed domain-toolchain development run yielded:

- **20/42 CAD exports passing the original volume/RMS gates**: all twenty clean synthetic cases.
- **22/42 numeric cases abstained**: twenty degraded drawings and two DTMB rasterizations.
- **5/5 expected negative cases abstained**.
- **20/20 completed native records** passed immutable verification and the unchanged original numeric gates.

These are domain-toolchain export results, **not twenty full controller trajectories passing the newer strict source-to-STEP audit**. One full-vessel strict audit was performed and failed; the other nineteen were not run through that additional audit.

Post-inference local metrics exposed weaknesses hidden by the old pass criteria:

| Metric among the twenty completed development exports | Median case | Worst case |
| --- | ---: | ---: |
| Half-breadth RMS error | 27.22 mm | 81.15 mm |
| 95th-percentile absolute half-breadth error | 32.37 mm | 40.68 mm |
| Maximum sampled half-breadth error | 167.42 mm | **1,302.51 mm** |
| Maximum error in source pixels | 8.25 px | **54.5 px** |
| Relative enclosed-volume error | 1.021% | 1.420% |
| Relative beam error | 0.643% | 0.861% |

All supplied station positions were reproduced exactly; those positions were provided inputs, not inferred facts. Length/depth agreement similarly does not validate contour identity.

The worst sampled ordinate error occurs at the baseline of a round-flare section. A broad horizontal raster row was excluded; interpolation then clamped the lowest half-breadth to the next observed row. The saved before/reference overlay shows the 54.5-pixel horizontal discrepancy. This is a **half-breadth ordinate error at a sampled elevation**, not a measured 1.3 m Euclidean whole-surface distance. Near a nearly horizontal curve, row quantization can make that distinction important. The error remains reported without changing the old gates. Post-hoc descriptive counts were 20/20 case maxima above 1 px, 18/20 above 2 px and 14/20 above 4 px; these are diagnostics, not a retroactively chosen acceptance rule.

The separate full-vessel STEP audit found a **43.2645 mm** raw discrepancy at terminal zero-width centreline spurs. The geometry kernel's existing terminal-cap procedure removes retraced zero-area segments, while the raw source samples include them. Interior sampled stations remained within 0.9071 mm. The raw 1.1 mm fidelity gate failed and was preserved. A future material-boundary metric could classify such spurs separately, but this work does not silently waive them or call the full audit successful.

**Raw evidence:** compact reports, per-case/per-station metrics, visual iterations and the separately compressed complete native evidence are under `artifacts/agentic/development/known47-v3/`. The raw archive is supplied separately to keep the runnable package manageable.

## Actual live DeepSeek experiment

Credentials were provided only in memory. No credential is included in source, receipts or deliverables. The verified provider was OpenCode Go, model identity **`deepseek-v4.1-flash`**, through its documented OpenAI-compatible endpoint.

Two live capability probes succeeded. The text probe answered 4+3; the vision probe read “PORT” and counted three red circles from actual image pixels. Both returned model identity, Go billing and observed cost 0. Catalog advertising alone was not treated as proof of access or vision.

The actual source-only development task then used four live decisions:

1. `inspect_source` — request source observations.
2. `select_contours` — select inspected source-bound candidates after seeing image pixels and structured evidence.
3. `build_provisional` — request trusted native CAD construction.
4. `finish` with abstention — respond to `invalid_published_evidence`, preserving the failed build and review requirement.

This run had **zero operator corrections**, **one image-bearing decision**, 13,812 reported prompt tokens, 310 completion tokens and **73.34 s** elapsed time. All four completed model responses reported Go billing and observed cost **$0**. Exact offline replay verified all four recorded decisions with zero generation requests and zero CAD executions.

The comparable final deterministic run used the exact same captured input specification and pixels, completed six controller decisions and one build in **13.06 s**, and reached `awaiting_human_review`. Its independent analytic-prism reference had volume 21 m³; reconstructed volume was 20.85293 m³, error **0.7003%**. Sampled half-breadth RMS was **6.25 mm**, p95 **8.04 mm**, and maximum **9.64 mm**. The unchanged reviewed engine blocked all three required contours as ambiguous. These are small development demonstrations; they are not an independent fleet benchmark.

The live attempt did not reach a verified render or final candidate, and DeepSeek did not inspect a rendered CAD image in that trajectory. Its selection and error-response capabilities are demonstrated; an accuracy or intervention-effort gain over the deterministic policy is not.

A proposed additional six-call experiment was **rejected by automatic approval review** because it would exceed the documented eight-call pilot allowance and a hard zero-dollar account cap had not been verified. No retry or further provider request was made after rejection. One follow-up policy call had been durably reserved before interruption, with **no completion or billing receipt**, so its transmission and cost are unconfirmed. The completed-call count remains six: two probes and four task decisions, all reporting observed cost 0. The interrupted task is separately recorded and excluded from quality totals. Further live validation requires approval of a concrete additional request budget or a verified applicable zero-cash guard.

## Browser review and operator intervention

A separate three-station synthetic example added a faint competing vertical stroke. The deterministic policy abstained before CAD construction. In actual Chromium, the source and overlays were inspected, the three sloping candidates selected, and the review interface downloaded a typed decision file. That file was applied through the CLI with actor **`assistant_operator`**, then the task resumed to build, render and validate.

This was **one explicit selection batch containing three contour choices**, one build, and six total deterministic policy decisions across the initial and resumed phases. There were no provider calls. The final candidate had one valid closed STEP solid and reached `awaiting_human_review`. Maximum measured selected-trace-to-STEP distance was **0.8965 mm / 0.05379 px**. That establishes representation fidelity to the selected trace, not independent real-vessel accuracy.

Desktop/mobile browser checks passed with no JavaScript errors, external requests or horizontal overflow after fixing wrapping. The selected candidate IDs persisted through download and regeneration. A large-export notice now states how many images are displayed and warns if the bounded HTML omits any. The actor label is a local record, not identity verification; no qualified naval architect participated. A preserved early overlay has a minor footer overlap, retained in the failure ledger rather than overwritten.

## Publication reliability investigation

The reviewed code showed the same publication anomaly as the earlier continuation. In eight bounded ordinary probes, every run initially verified. **All four workspace runs later failed integrity**, while **all four temporary-directory runs stayed valid**. One delayed probe verified at 0 and 0.5 seconds, then failed at 1, 2 and 3 seconds inside the same observing command. Deleted lock/staging files reappeared beside unchanged completed output hashes. Another failed manifest contained a transient `.rsync-tmp/transaction.json` path that subsequently vanished while another transaction file reappeared.

This localizes the behavior to delayed workspace synchronization/state restoration, but the external actor is not identified. Six attempted syscall-tracing launches were denied before reconstruction began; they are excluded from the eight ordinary-run counts. No tracing restriction was bypassed.

The verified mitigation was active execution outside the synchronized workspace, then copying only completed terminal artifacts into fresh destinations. **Three of three completed-only imports** retained identical inventories and verified after another tool boundary. This is an environment-specific mitigation, not proof that the external synchronization mechanism is repaired. Failed records and their stages remain preserved, and no verification rule was weakened.

## Authentic data and learning choices

The acquired/reverified development collection contains **five authentic drawing items from three vessels and two source families**. Two new items from two new vessels were downloaded: Wapama HAER CA-67 sheet 5, with its original TIFF and official preview, and USS Monitor NH50954. Three existing Balclutha pages were reverified. The exact count is two new items and three downloaded files; existing pages are not relabeled as new acquisitions.

The inventory retains collection/item identity, source URL, date, hash, resolution, transformations, calibration evidence, conditions, rights basis and separate permitted-use assessments for local evaluation, redistribution, provider inference and training eligibility. An actual ALMA access denial is recorded; unclear-rights material remains URL-only. These are measured heritage drawings and an historical engraving reproduction, not a manufactured claim of modern proprietary shipyard data.

The source inspections matter. Wapama explicitly presents both sides because the hull is distorted, so automatic symmetry is unsupported. Balclutha describes an inner hull, starboard-only measurement, fairing and explicit shape assumptions. Monitor lacks a complete calibrated station set. These documents therefore support tracing/label/calibration research and ambiguity testing, not an independent proof of whole-hull reconstruction accuracy.

Five provisional annotation documents and overlays use the included schema for view panels, stations, datum/centreline, scales, alternatives, occlusions, dimensions, revisions and unknowns. Hashes, bounds, unique IDs, null unknowns and inference provenance were checked. Full Draft 2020-12 schema validation was not run because no schema-validator package was installed in the checked environments; this limitation is recorded. There are **zero expert-reviewed gold annotation sets and zero authentic whole-hull ground truths**. All five items are development data, grouped by vessel and source family. Crops and pages do not inflate the vessel count.

Calling pretrained DeepSeek is **inference**, not training. Prompt engineering, tool schemas and deterministic image processing do not change model weights. This work used neither fine-tuning nor retrieval-augmented examples. OpenCode Go access does not establish a supported fine-tuning service. The immediate data investment should be independent expert annotation of diverse development sources, with disagreement/adjudication records, and a reserved authentic evaluation group. Active learning can prioritize uncertain development examples; it must not choose examples from a sealed final set. Three authentic vessels without gold contour labels do not justify a training claim.

## Validation, delivery and practical use

The final frozen source passed **411 tests, 0 failures, 0 skips**, in 107.41 s. A new environment installed all 55 locked dependency wheels with hashes; dependency consistency passed. The final wheel passed **9 installed-engine checks and 7 installed-agent checks**, including a real reconstruction, verification, review export and exact live-transcript replay. All **25 application source modules** in the installed wheel match the frozen source hashes. One initial test invocation used isolated Python for repository-only benchmark tests and failed collection; its log is retained, and the corrected standard source-test command passed. Isolated imports were correctly used for the installed-wheel checks.

Provider tests include mocked network failures, malformed/schema violations, image bounds, cancellation, reservation accounting and replay mismatches. Controller tests cover unknown/code-bearing operations, invalid arguments, unsupported dimensions via the engine, no-progress loops, blocked final approval, missing/changed artifacts, interrupted recovery, operator limits and persistent live caps. Existing security, geometry, review and publication regressions remain in the full suite. Actual local browser workflow checks are separate from pytest and from live provider evidence.

The implementation supports the exercised Linux x86_64 / Python 3.12 profile, with CadQuery 2.7.0. Other operating systems were not validated. Results and source are delivered as a local commit series/patch and downloadable evidence; no new remote CI result is claimed for this revision.

A minimal offline command sequence is:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-linux-py312.lock
python -m pip install --no-build-isolation --no-deps -e .
python examples/make_agent_example.py --out data/examples/agent
vessel-reconstruct agent run data/examples/agent/spec.json \
  --out /tmp/marinaframe-task --policy deterministic
vessel-reconstruct agent verify /tmp/marinaframe-task
vessel-reconstruct agent review /tmp/marinaframe-task --out agent-review.html
```

The next useful live experiment is a small, explicitly budgeted comparison on the same frozen development inputs, using the proven temporary execution context, in which the model actually receives a reimported STEP view and responds to its validation. The next algorithm/data work is to handle known input refusals directly, investigate baseline-row/tangency measurement and raw-versus-material-boundary semantics, and obtain independently reviewed authentic labels. Those changes should use development data and a new final evaluation group. No current artifact grants engineering approval.
