# Independent evaluation of MarinaFrame 0.4

## Completed results

The frozen 0.4 Python, Rust and live DeepSeek arms each pass **8/8 supported drawing attempts, covering 4/4 paired design families**. Exact published 0.3 also passes 8/8; published 0.2 passes the four clean drawings and refuses the four grid variants. This cohort shows no supported-geometry success advantage for 0.4 over 0.3, or for the live policy over current deterministic operation. It does show different terminal handling of missing inputs and ambiguous source evidence. All candidates remain provisional and require human semantic review; engineering approval is false.

| CAD-capable automated arm | Attempted | Terminal records | Supported full pass | Both conventions pass | Explicit refusal: original negatives | Safe diagnostic nonacceptance | No-progress stops |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Published 0.2 | 15 | 15 | 4/8 | 0/4 | 4/4 | 4/4 | 0 |
| Exact published 0.3 | 15 | 15 | 8/8 | 4/4 | 2/4 | 3/4 | 4 |
| 0.4 Python deterministic | 15 | 15 | 8/8 | 4/4 | 2/4 | 3/4 | 4 |
| 0.4 Rust deterministic | 15 | 15 | 8/8 | 4/4 | 4/4 | 4/4 | 0 |
| 0.4 live DeepSeek | 15 | 15 | 8/8 | 4/4 | 4/4 | 4/4 | 0 |

The original negative set contains one scope-ambiguous interior-loop case. Its original refusal label is retained in the table, with a separate sensitivity analysis below. A no-progress stop with a relevant gap is counted as safe diagnostic nonacceptance, but not as an explicit correct refusal. A terminal record, successful process exit, CAD export, trace agreement and independent correctness are distinct outcomes. [Full machine results](../artifacts/v04/evaluation/scoring/summary.json)

The primary inventory has **92 executions**: 75 automated CAD-capable attempts, 15 source-only pixel predictions, and two separately reported assistant-operated attempts. The 30 initial legacy intake-preflight attempts comprise **24 procedural executions affected by fractional ROI bounds and six unchanged, intentionally incomplete authentic-partial executions**. Those 30 attempts remain additional retained evidence, for **122 launched case executions in this evaluation**, not 122 vessels. The six authentic-partial attempts encountered their expected missing-input diagnostics, not the ROI format defect. The failed launcher preflight before them launched zero cases. All five CAD-capable automated arms produced terminal records for all 15 inputs; there were no inference watchdog interruptions, execution failures or resource-limit terminations in these primary runs. [Attempt inventory](../artifacts/v04/evaluation/scoring/attempt_index.json)

The per-case exports contain [all 92 primary rows](../artifacts/v04/evaluation/primary_attempts.csv) and a [separate 30-row initial intake ledger](../artifacts/v04/evaluation/initial_intake_attempts.csv). They retain explicit units, cohort and completion denominators, recorded status, applicable accuracy/refusal fields, and empty values for unavailable or inapplicable measurements. These are exact derivations of the retained JSON, with no rescoring or gate change. [CSV definitions](../artifacts/v04/evaluation/csv_schema.md) and [source/output hash bindings](../artifacts/v04/evaluation/csv_derivation.json) document the mapping and verification.

### Supported geometry, every declared station

| Family / convention | Case | px/m supplied | Volume error % | RMS px | Max px | Trace max mm | Unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A clean | `q_87c132d9` | 96.0 | 0.647 | 0.643 | 1.150 | 0.931 | 0 |
| A grid | `q_04e5b3a1` | 96.0 | 0.680 | 0.679 | 1.238 | 0.925 | 0 |
| B clean | `q_6fa9d080` | 112.0 | 0.390 | 0.636 | 1.181 | 0.978 | 0 |
| B grid | `q_912adc37` | 112.0 | 0.397 | 0.648 | 1.120 | 0.935 | 0 |
| C clean | `q_3bd4178e` | 88.0 | 0.427 | 0.611 | 0.860 | 0.996 | 0 |
| C grid | `q_7c1052f4` | 88.0 | 0.428 | 0.618 | 0.850 | 0.959 | 0 |
| D clean | `q_ef943ab2` | 104.0 | 0.456 | 0.621 | 1.152 | 0.978 | 0 |
| D grid | `q_15a6d9c0` | 104.0 | 0.458 | 0.630 | 1.162 | 0.899 | 0 |

For the Rust arm, the worst local independent error is **1.238103 pixels (12.897 mm)** at `q_04e5b3a1`, section `s3`, x=8.200 m and z=2.700000 m. The largest volume error is 0.680231%, the largest per-case pooled RMS is 0.679035 pixels, and the largest selected-trace distance is 0.995502 mm. The independent gates remain 3%, 2 pixels RMS and 4 pixels maximum; selected-trace consistency remains separately limited to 1.1 mm.

Every measured supported candidate is a valid single solid and resolves all five station cuts, including the exact terminal planes, at 4,097 elevations per station. Errors for absent exports are not assigned zero or included in success-only means. The four missing 0.2 grid exports remain reconstruction failures. [All 40 supported attempted-arm rows](../artifacts/v04/evaluation/all_supported_case_measurements.md)

![Independent STEP errors and fixed gates](../artifacts/v04/evaluation/visual/supported_geometry_errors.png)

The current Python, Rust and live outputs have identical selected-trace coordinates and identical raw STEP DATA sections on all eight supported inputs. This establishes output identity for these runs, not equal operation counts or general performance equivalence. Full STEP file hashes differ because headers differ. The exact 0.3 outputs are separately measured, with no claim of byte identity. [Output identity checks](../artifacts/v04/evaluation/output_geometry_identity.json)

### Refusals, ambiguity and authentic partial sheets

| Diagnostic | Case | 0.2 | 0.3 | 0.4 Python | 0.4 Rust | Live |
| --- | --- | --- | --- | --- | --- | --- |
| Missing declared pixel scale | `q_40bc6a8d` | blocked | no_progress + gap | no_progress + gap | blocked | blocked |
| Two equal competing contours | `q_68de09f5` | blocked | blocked | blocked | abstained | abstained |
| Interior loops: scope-ambiguous* | `q_b970f41e` | blocked | ready* | ready* | blocked | abstained |
| Missing middle trace interval | `q_a2538ce6` | blocked | blocked | blocked | abstained | abstained |
| Balclutha Frame 108: no 3D gold | `r_73b91d2a` | blocked | no_progress + gap | no_progress + gap | blocked | blocked |
| Monitor: no 3D gold | `r_85ac0f61` | blocked | no_progress + gap | no_progress + gap | blocked | blocked |
| Wapama: no 3D gold | `r_09d3ea47` | blocked | no_progress + gap | no_progress + gap | blocked | blocked |

Both Python harnesses stop with `no_progress` on the missing-scale specification and the three incomplete authentic specifications, while preserving relevant input-gap diagnostics. Rust and live terminate those four inputs explicitly as blocked. The three source-evidence diagnostics terminate with an explicit block or abstention under Rust/live. The terminal classifications come from recorded states and exact structured gap kinds, not exit-zero status or broad keyword matching.

**Scope qualification committed before outcome review:** `q_b970f41e` was authored and sealed as unsupported topology, but the actual image places small closed loops inside an otherwise continuous exterior profile. For an exterior-envelope task, accepting the outer contour is not established to be wrong hull geometry. The evaluator documented that defect at 22:20:42 UTC, before new deterministic execution and before reference scoring, and retained the original reference/label unchanged. The original refusal expectation is violated by the 0.3 and current Python ready candidates. In the sensitivity set excluding that one case, 0.2, Rust and live explicitly refuse 3/3; both Python harnesses explicitly refuse 2/3 and safely stop with a relevant missing-scale gap on the remaining case. Their safe diagnostic nonacceptance is therefore 3/3. [Pre-outcome note](../artifacts/v04/evaluation/source_label_quality_note.json) · [Earlier hash commitment](../artifacts/v04/evaluation/source_audit_note_commitment.json)

The calibration negative removes `pixels_per_metre` from the deployment specification even though a scale bar remains visible in its image. It tests the required supplied-calibration contract, not automatic calibration or OCR. The authentic images also omit required units, station correspondence, scale and symmetry commitments. All arms avoid an unsupported ready hull on all three authentic inputs, but the Python harnesses reach no-progress rather than explicit refusal. These are principally intake-contract results: they do not demonstrate that a model visually inferred the historical sheets' limitations, and no 3D or volume correctness score is assigned.

### Source-only pixel baseline

| Family / convention | Resolved / required rows | Coverage % | RMS on resolved rows, px | Max on resolved rows, px |
| --- | --- | --- | --- | --- |
| A clean | 1295/1300 | 99.615 | 0.660 | 1.137 |
| A grid | 1299/1300 | 99.923 | 0.714 | 1.182 |
| B clean | 1320/1320 | 100.000 | 0.641 | 1.389 |
| B grid | 1320/1320 | 100.000 | 0.665 | 1.251 |
| C clean | 1279/1280 | 99.922 | 0.634 | 1.205 |
| C grid | 1280/1280 | 100.000 | 0.655 | 1.189 |
| D clean | 1328/1330 | 99.850 | 0.635 | 1.215 |
| D grid | 1330/1330 | 100.000 | 0.665 | 1.201 |

The fixed threshold/row-median method resolves **10,451/10,460 rows (99.914%)** across the eight supported images. Its small source errors show that these well-calibrated single-trace drawings are also tractable for a simple pixel method. The nine unresolved rows remain visible in coverage. It ran on all 15 inputs and has no CAD, closed-solid, volume, or 3D success claim. This baseline does not establish robustness to arbitrary archival drawing conventions. [Pixel per-case index in the machine summary](../artifacts/v04/evaluation/scoring/summary.json)

### Live provider and source-blind assistant operation

The live arm used the frozen optimized Rust application and the already authorized OpenCode Go `deepseek-v4.1-flash` provider. It completed **74/74 actual provider requests**, with no failed, unknown or not-sent requests and no provider retries or no-progress stops. Receipts record **752,723 prompt tokens and 5,590 completion tokens**. Usage reports record $0 observed cost on every request; nominal `list_cost` totals $0.11304483 and is recorded separately, while invoice or subscription cost is unknown. This is live evidence, not replay. No other provider or purchase was introduced. Zero runtime operator interventions excludes preparation of the supplied scale, centreline, baseline, ROIs, station positions, symmetry and closure metadata. [Independent live resource accounting](../artifacts/v04/evaluation/v04_live_resources.json)

Eight live tasks became ready for human review, three abstained, and four were blocked at input admission. Each supported live task used one geometry build, so this sealed cohort demonstrates no geometry-repair success or accuracy uplift over current deterministic operation. The live evidence includes 16 render operations and actual STEP-derived pixels on 27 completed provider requests. Three finish attempts were rejected for missing current-pixel review; those attempts remain counted. The 19 validation operations include 11 explicit reuses, so they are not 19 distinct new geometric audits. The live capture-and-transfer workflow intentionally adds a recorded pause after initialization, before provider inference. Concurrency was two provider tasks with one serialized native operation, and there was no aggregate request ceiling.

The fresh, reference-blind assistant operated two new tasks selected by the precommitted rule. Its scanned supported case passes 1/1 independently; its equal-contour case correctly abstains. The supported task required five explicit interventions—selection, two renders, validation and finish—and the ambiguous task required one finish/abstain intervention: **six interventions, two primary attempts, no extra attempts**. This is assistant operation, not a human or naval-architect comparison, and it is not pooled with autonomous results.

The assistant session lasted **554.012 seconds**, including 35.464 seconds of measured subprocess wait; the 518.547-second remainder is a collaboration-effort proxy containing image viewing, orchestration and context handling, not measured human labor or pure model inference time. Its tasks made zero external provider requests, but the assistant conversation's tokens and cost are unmetered here. Both tasks had valid pre-seal verification. Original sealed tasks remain read-only; the publication copy changes only empty `controller.lock` modes to permit verification, with every file byte preserved. [Assistant accounting](../artifacts/v04/evaluation/v04_assistant_resources.json) · [Transport record](../artifacts/v04/evaluation/assistant-transport.json)

### Resources and interpretation

| Arm, all 15 attempts | Median CLI/task wall, s | Sum native queue, s | CLI waited CPU sum, s | Max descendant RSS, MiB | Retained task bytes, MiB |
| --- | --- | --- | --- | --- | --- |
| Published 0.2 | 1.004 | 8.300 | 37.818 | 710.5 | 18.3 |
| Exact published 0.3 | 19.222 | 23.071 | 252.683 | 711.8 | 54.1 |
| 0.4 Python deterministic | 19.633 | 16.247 | 254.157 | 720.5 | 56.3 |
| 0.4 Rust deterministic | 23.224 | 106.180 | 263.369 | 720.5 | 60.0 |
| 0.4 live DeepSeek | 83.312 | 426.517 | not collected by this wrapper | — | 82.5 |

These are observed product-default workloads under a shared serialized native queue. Python holds an outer whole-task lock, so its recorded CLI execution excludes that outer queue; Rust's task wall includes its separately logged per-operation waits. Python defaults render oblique, Rust defaults render body plus oblique, and live adds provider latency, the capture pause and repeated validation/review operations. These numbers are not an identical-operation speed comparison. RSS is a maximum individual waited-for process, not a summed concurrent process-tree peak. Native evaluator measurements are separate and are excluded from inference resources. [Controlled identical-operation study](CONTROL_PLANE_PARITY_V04.md)

The live worker ledger records 86 completed operations, 426.517 seconds of admission waits and 251.325 seconds of supervised worker execution; overlapping task durations must not be interpreted as campaign elapsed time. Per-case logs retain all requests, rejections, operation receipts and resource fields. The current deterministic wrapper's 900-second watchdog was an external evaluation bound; it was not triggered and is not described as a product default.

### Independent instrument review and pixel review

The original measurement code and its first box/frustum calibration are preserved. A separate reviewer, reading only generic excerpts, identified unsafe near-horizontal extrapolation, ambiguity hidden by an outermost-hit selector, and insufficient binding of measured files to finalized attempts. The revised instrument clamps tolerance-admitted queries to segment endpoints, explicitly measures the nonnegative outer envelope, records competing/interior-horizontal intersections, and binds case, specification, selected trace and STEP bytes to a finalized attempt. Exact terminal planes are never moved inward.

The expanded generic calibration covers a box, a ruled frustum and an internal tunnel over 45,067 required ordinates. It resolves all ordinates, exposes 6,147 competing interior ordinates and six interior horizontal overlaps in the tunnel, and rejects wrong case/spec/unlisted-STEP probes. The trace extension independently queries nearest distance to the actual OCCT section boundary at every retained source-centre sample; known distances of 0, 0.5 and 1.2 mm verify both the numerical result and the unchanged 1.1 mm threshold. A further generic review required exact finite full-span monotone grids, equal array lengths, unique station IDs and exact blocking-diagnostic kinds; all synthetic contract probes pass. No application or gate was changed by these instrument corrections. [Instrument results](../artifacts/v04/evaluation/instrument_calibration_v3.json) · [Preserved review and calibration bundle](../artifacts/v04/evaluation/instrument_evidence.tar.gz)

Cut edges request 0.01 mm geometric sampling deflection. The generic ruled-shape calibration's maximum half-breadth error is below 10⁻⁶ mm, but requested deflection is not a separately certified y-ordinate error bound near arbitrary horizontal tangencies. The measured envelopes here have large margins to the 2/4-pixel source gates. Outer-envelope coverage does not prove that arbitrary multivalued or internal topology has been reconstructed correctly. The nearest-boundary trace metric is separately evaluated on actual OCCT geometry.

The evaluator viewed all 14 unique source images, verified the missing-calibration image's exact duplicate identity, and viewed one original actual-STEP render per design family before consulting numerical source errors. Original source/CAD hashes and observations are in the [visual review ledger](../artifacts/v04/evaluation/visual_review_ledger.json). A [post-score supplement](../artifacts/v04/evaluation/visual_review_postscore.json) records body/oblique views of the worst current supported case and the accepted 0.3 exterior envelope for the scope-ambiguous interior-loop diagnostic. These are assistant observations and do not replace qualified semantic or professional review.

![Actual STEP body view, rounded-bilge grid case](../artifacts/v04/evaluation/visual/q_912adc37-rust-body.png)

### Evidence and reproducibility

The [public input/reference publication ledger](../artifacts/v04/evaluation/input_reference_publication.json) binds exact-byte copies of both input versions, the independently authored renderer, sealed mathematical references, the pre-outcome scope note and the assistant sampling rule. References were released only after all automated and assistant outputs locked. All original attempts remain intact. The terminal [0.2/0.3 archive](../artifacts/v04/evaluation/legacy_outputs_v2.tar.gz), [new Python archive](../artifacts/v04/evaluation/new_python_outputs_v2.tar.gz), [new Rust archive](../artifacts/v04/evaluation/new_rust_outputs_v2.tar.gz), [pixel archive](../artifacts/v04/evaluation/pixel_predictions_v2.tar.gz), and [original intake-preflight archive](../artifacts/v04/evaluation/intake_preflight_v1.tar.gz) each have an archive ledger and byte-for-byte verification. The live and assistant original output locks remain separately preserved.

Execution records deliberately retain their original absolute paths; archive manifests identify the corresponding member roots. Published inputs and all numerical reference/measurement arrays are sufficient to inspect the scoring independently. Re-execution needs the recorded native environment and appropriate path mapping; it is a new known-data run, not another untouched holdout. The full inference image/spec tree remains separate from the reference tree. The cohort is small, calibrated and procedurally authored; it provides no measured success rate for complete historical vessel reconstruction, automatic scale/station inference, unobserved bow/stern completion or engineering approval.

### Requirements not measured by this cohort

- **Complete authentic-vessel accuracy:** the three public sheets have no complete independent 3D gold. Their blocked intake does not validate full interpretation of those drawings.
- **Automatic drawing setup:** supported-case ROIs, scale, centreline, baseline, station positions, symmetry and closure convention are supplied. Rotation, perspective distortion, severe degradation and multi-sheet station matching are not tested.
- **Disconnected exterior topology:** the originally labelled topology diagnostic contains interior loops and does not establish a valid negative for disconnected outer hulls. That capability remains unmeasured here.
- **Geometry repair or assistance advantage:** supported live cases use one build, and current automatic arms produce identical geometry. The two-case assistant sample is neither a human comparison nor a population estimate.
- **Naval or structural validity:** volume means the declared closed envelope, not automatically displacement or steel volume. The tests do not establish unseen bow/stern form, hydrostatics, structural adequacy, professional semantic approval or safety certification.

## Predeclared protocol and execution record

The first evaluation input/reference seal was created on **2026-11-06 at 21:07:56 UTC**, before the implementation freeze. At that first seal the independent evaluator had not executed the production solver on these inputs. The source of the production solver was not inspected to design this cohort; the published deployment schema and project documentation were read to prepare calibrated input files. The renderer and mathematical reference definitions were independently authored in a separate agent, with Pillow and NumPy, without importing the benchmark generator or reconstruction implementation.

The exact published 0.3 comparison source is `5b0b48e3dd9bcef25427d27ce800118935f58d1a`. The previously known 47 cases and former 0.3 final 12 cases are development data. They are not included in the count of new sealed procedural families.

Original input tree digest: `6489faceb15ebd5a75d12a06f4fc7a09de63000557454488453e9c4c4db0d196`.

Amended v2 input tree digest: `56faaf412e89105aac3628792152749d0099106192049d6394cbb30420c438e1`.

Reference tree digest: `7a168ed7cdc53b1efa053280d45169c8eaeba07cacdcda2773aecac33057f472`.

Individual image/specification hashes, byte sizes and author-script/reference-manifest commitments are recorded in [the seal receipt](../artifacts/v04/evaluation/seal_receipt.json). A hash commitment detects later modification relative to this record. It is not an external timestamp, signature or security boundary.

## Intake-only amendment before implementation freeze

The evaluator's schema-only admission check missed the stricter requirement that crop rectangles contain integer pixel coordinates. The original procedural specifications used fractional ROI coordinates. After the first 30 frozen-legacy attempts were locked, the evaluator inspected an intake diagnostic and identified this authoring defect. Those original inputs and every original attempt remain preserved as intake preflight evidence. They are not silently replaced or represented as valid-input geometry trials.

The implementation coordinator authorized an intake-only amendment while the new implementation was still unfrozen. On **2026-11-06 at 21:24:25 UTC**, the evaluator created a separate v2 input seal using `floor(left/top)` and `ceil(right/bottom)` for all ROI coordinates, with JSON integer types. This changed 60 rectangles across the 12 procedural cases. Source image bytes, calibration, station positions, vertical intervals, all other specification fields, reference geometry and the predeclared gates are unchanged. All amended rectangles were independently checked for integer type and image bounds. No production code was adapted to this error, and no geometry or accuracy result was disclosed to the implementation agent.

The [v2 seal receipt](../artifacts/v04/evaluation/seal_receipt_v2.json) and [exact input-format amendment](../artifacts/v04/evaluation/input_format_amendment_v2.json) preserve the original commitments and the retained preflight output lock. Valid-input comparison attempts use v2 and receive distinct attempt identities and output locks. The report will disclose the original 30 attempts separately. The suite is an explicitly amended procedural evaluation, not an unqualified claim that no intake execution preceded the final input seal.

## Cohorts and denominators

| Cohort | Independent units | Attempts | Purpose |
| --- | ---: | ---: | --- |
| New procedural supported geometry | 4 design families | 8 | Two drawing conventions per geometry; full independent mathematical reference |
| New procedural expected refusals | 4 diagnostic cases | 4 | Missing calibration, equal competing contours, the originally labelled unsupported-topology diagnostic and missing source intervals; see the pre-outcome scope qualification above |
| Authentic partial public scans | 3 vessels, 3 sheets | 3 | Evidence limitations and refusal/request behavior; no complete independent 3D truth |

The eight supported images comprise clean half-section sheets and paired scanned-ledger sheets with pale orthogonal rules, paper variation, antialiasing and light blur/noise. The five section positions per sheet are explicit. There is no arbitrary rotation or perspective distortion. Each pair shares one underlying geometry and is one unit for family-level reporting. This small selected cohort does not estimate a population success rate or professional vessel accuracy.

The procedural reference is a symmetric, single-valued transverse half-breadth graph, with a declared finite station set, piecewise-linear longitudinal interpolation and flat terminal closures. It tests finite envelope reconstruction. It does not constitute a complete ship design, engineering approval or externally measured naval-architecture gold standard.

The authentic images are inherited development assets: **Balclutha Section at Frame 108**, **USS Monitor NH50954**, and **Wapama as-is body plans, sheet 5**. They are deliberately reported as a separate authentic partial cohort, not three new untouched real-vessel holdouts. The evaluator viewed the exact hashed pixels. Frame 108 supplies only one structural section; Monitor supplies selected machinery sections without validated station correspondence; Wapama explicitly shows port and starboard separately due to distortion. No complete 3D hull, numeric volume or unobserved geometry is invented for them. [Source provenance](../artifacts/v04/evaluation/source_provenance.json) retains item-specific public-domain records and limitations. Restricted ALMA/Tri-Coastal source content and derivatives are excluded.

## Input/reference separation and freeze

The runtime receives only a case's source image and deployment `spec.json`. No reference half-breadths, target volumes, family parameters, correct candidate IDs or evaluator drawings are placed in the inference tree. The input and reference directories are separate under `/tmp/marinaframe-v04-independent/`. References remain in `sealed_reference` until scoring. The implementation runner handoff uses an index containing only opaque case IDs and input/image paths. The initial path handoff also named the evaluator's index, which contains case-level cohort fields; it was superseded by the stripped implementation index before the new implementation freeze. Any confirmed exposure to those cohort fields must be disclosed in the freeze record. The initial index is preserved for audit, not silently rewritten.

This is **procedural separation by agent and directory, not an operating-system sandbox**. All agents share filesystem authority, and an implementer could deliberately open the answer directory. The evaluator also authored the procedural reference, so independence here means independent of the implementation agent and renderer. It does not mean an externally commissioned benchmark or qualified human adjudication.

Freeze records must identify the exact executable/entrypoint, source revision or complete module inventory, native worker, configuration and dependency environment for every arm. New Python deterministic and Rust deterministic runs use the same frozen Python domain/geometry engine and geometric validation contract. Before new-arm execution, the coordinator clarified that these are separate product-default workflow arms: Python's default oblique view and Rust's default body-plus-oblique views are retained. Their raw latency is not an identical-operation comparison. A separate controlled experiment addresses identical operations. Any binary or worker change after a holdout result is opened creates a new development version; it cannot retain this cohort's untouched status. No aggregate score or case-level numeric error is disclosed before all selected automated arms have finalized their outputs.

Native CAD workers run serially, coordinated with the implementation agent. Active tasks live under `/tmp` because the project previously documented mutable workspace publication artifacts. Completed outputs, original stdout/stderr, process exit codes, wall time, task resource counters, source manifests and file hashes are retained. Failed attempts are never deleted or silently replaced. A rerun receives a new attempt identifier and records why it occurred.

## Predeclared comparisons

1. Frozen published 0.2 deterministic engine, when its preserved runtime is runnable.
2. Frozen published 0.3 deterministic harness at the exact published base.
3. Frozen new Python deterministic harness with its raw product-default policy and retained TaskLimits.
4. Frozen new Rust deterministic control plane with the same new domain/geometry engine, its raw product-default policy and its own original resource guards. Default view workflows differ as disclosed above.
5. Live OpenCode Go DeepSeek on the same sealed inputs, subject to the already authorized provider and finite per-request/resource controls. Replay and scripted runs are recorded separately and are never labelled live. Provider calls, retries, tokens, network failures, and actual admission/usage receipts are counted. There is no arbitrary eight-call campaign ceiling and no claim that a zero monetary estimate establishes provider availability. No additional purchase or other provider is authorized by this protocol.
6. A deliberately simple contrast/row-pixel baseline. It produces source traces only, not CAD, and therefore cannot be included as a completed or correct CAD reconstruction.
7. A small assistant-assisted source-only sample, with at most two primary attempts: one paired scanned supported sheet and one ambiguous sheet. Assistance is performed by an agent that receives source pixels and runtime candidate evidence without numeric references. The actor is an assistant, not a human engineer. Candidate selections, time, actions and all attempts are logged; assisted outcomes are not pooled with autonomous outcomes.

A failed/inaccessible preserved arm is reported as unavailable with its execution evidence, rather than simulated or replaced by a newer engine. Live provider authentication/transport failure is a failed live attempt or unavailable arm, never replayed evidence of model quality. The caller coordinating authorized live access retains the credential; the evaluator does not read or expose it.

## Confirmed application and current-arm configuration

The confirmed current application source is `8916e68f4c175bdab291d7c0bf2978862be8915d`, with optimized executable SHA-256 `071d76828b845d0134e57a3f4c14e48fc2843027cfa45806de5d67767d5b6f72` and runtime-freeze SHA-256 `a7aea135d54d3873715dc6849dacfd87ae67ab882064add8c708370983a24684`. The evaluator checked all 46 frozen runtime files and recorded the release Python environment and executable, source resolution path, evaluator tools and exact per-arm command templates in [the current execution plan](../artifacts/v04/evaluation/current_execution_plan_v1.json).

Native deterministic execution has an explicit **900-second external evaluation backstop**. This is not a Rust product default: the authorized Rust research controller has finite worker/provider timeouts and no aggregate task wall cap. A triggered evaluation backstop is recorded as an interrupted/truncated attempt, not a domain refusal or domain failure. The Python harness retains its original task limits. Native queue time is recorded separately; Rust accounts for its own per-operation admission, while Python uses the shared outer lock for the whole task. Rust CLI exit zero can include blocked or abstained outcomes, so workflow classification uses the recorded task status rather than exit code alone.

The simple pixel arm runs the originally committed independent threshold/row-median method on exactly the v2 bytes. It has no CAD capability. Its 15 predictions were locked before numeric scoring; source error and coverage will be reported separately from CAD success.

The two-case assistant selection was committed before new-arm results were opened: choose the source with the lexicographically smallest image SHA-256 among the four scanned supported sources, and include the sole predeclared ambiguity diagnostic. This is result-independent stratified diagnostic sampling, not a population-rate estimate. The [sampling commitment](../artifacts/v04/evaluation/assistant_sampling_commitment.json) seals the private selection. A fresh assistant context receives only opaque source inputs and current task evidence after automated output lock and before scoring. Original automated tasks remain immutable; assistance uses fresh tasks and counts every intervention, viewed image, action, elapsed time and retained attempt.

The [inference-only transfer mapping](../artifacts/v04/evaluation/provider_transfer_authorization_v2.json) names exact source/spec bytes for the existing user-authorized OpenCode Go DeepSeek campaign, with source-specific public-domain or original-author CC0 bases. It contains no case-level evaluation labels or reference geometry. The root launcher retains the credential and binds each captured source manifest; current-task source-derived evidence is the only permitted derived transfer.

## Source-resolution gates, fixed before evaluation

All three independent procedural geometry gates must pass:

- Absolute relative volume error at most **3%**, using independently integrated reference sections and the frozen reference's longitudinal interpolation convention.
- Transverse half-breadth RMS error at most **2 source pixels**, converted separately with each supplied panel's pixels-per-metre calibration.
- Worst local transverse half-breadth error at most **4 source pixels**, using the same conversion. Report the worst location, station, elevation, error and source resolution.

The 2/4-pixel limits preserve the earlier pixel-based contract. They are appropriate here as drawing-resolution gates because the renderer's subpixel positions are known, the final strokes are approximately 1.5–1.95 pixels wide, and grid/noise/antialiasing remain at raster scale. They are not dimensional accuracy claims for an original historical vessel. At the supplied scales the RMS allowance is approximately 18–23 mm and the maximum allowance approximately 36–45 mm. The 3% volume gate is retained as an additional global check, not derived as a universal bound from those pixel tolerances. A local error can fail despite a small volume error.

Evaluate the actual exported and reimported STEP. Use every declared station including terminal closures, at 4,097 uniform elevations, with horizontal closures handled explicitly. Record unresolved cuts and endpoints rather than removing them from the denominator. Geometric cut discretization error must be documented and substantially below the source-resolution gates. Section RMS is pooled over all required ordinates; maximum is over every required ordinate. Missing required stations, unresolved cuts, invalid/non-single-solid CAD, timeouts, or absent exports fail supported reconstruction regardless of other metrics.

The **selected-trace-to-STEP limit of 1.1 mm remains unchanged and separate**. It measures whether CAD reproduces the selected source trace, not whether the selected trace is the correct contour or the original vessel. Report that consistency result next to the independent source/reference errors. Do not weaken that check, substitute trace agreement for truth, or accept a stale candidate revision.

The simple pixel baseline is evaluated on its resolved source ordinates with explicit coverage. Its source RMS/maximum and coverage are separate from the STEP and volume tables. It cannot produce a CAD success, export score or 3D truth claim.

## Classification, failures and reporting

For each arm and cohort, report **attempted, terminally completed, exported candidate, geometrically correct, correctly refused/requested evidence, incorrectly accepted, unresolved, timed out, resource limited and execution failed**. The attempted denominator includes every launched case. Completion is a process/workflow result and does not imply correctness. A supported case that abstains counts as a false refusal and a reconstruction failure. A negative case counts as correctly refused only when it avoids a ready candidate and surfaces a relevant blocking diagnostic; a crash alone is not a correct diagnostic refusal. A wrong candidate with successful CAD construction is an incorrect acceptance.

The authentic cohort has no volume/3D correctness denominator. It is scored only for avoiding unsupported ready claims and surfacing source limitations, with the provenance and evidence completeness shown. Correct schema-level refusal does not establish successful visual understanding of a drawing.

Preserve per-case metrics and all resource records. Report paired-convention differences per family, family-level all-attempt success, median/RMS as useful, and the worst error/case. Do not hide failures in success-only averages. With four families, descriptive counts are more useful than a precise population confidence interval. Any additional exploration after opening results is marked development and kept separate from this sealed primary result.
## Final execution and scoring status

All selected inference arms completed and locked before references were used for scoring. The final assistant lock is dated 2026-11-06 at 22:56:27 UTC; the coordinator then authorized scoring. Separate generic instrument reviews and calibration were completed before the first accuracy scores. No production tuning followed outcome review. The v1/v2 protocol commitments remain immutable historical copies, and all scorer revisions/admission records are retained.
