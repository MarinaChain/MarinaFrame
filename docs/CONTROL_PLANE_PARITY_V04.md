# Current Python and Rust controller parity and resource study

## Result

The current Rust controller reproduced the current Python harness's successful geometry in **all six paired successful comparisons** across a three-station fixture, a 25-station development drawing, and a three-station case with unequal vertical extents. Every pair used identical selected candidate IDs, logical tool arguments, CAD section bytes and mesh bytes. Reimported STEP dimensions and volume agreed exactly. The STEP `DATA` sections also matched byte for byte; the retained complete STEP files have different timestamp headers.

Rust took longer in every successful measured pair. Across each case's two repetitions, its mean wall time was **11.2% higher for straight3, 4.0% higher for known47_25, and 11.3% higher for mixed_height3**. Its sampled controller process was smaller, while the shared CAD workers dominated memory. These observations support orchestration and geometry parity. They do not establish a CAD speed improvement, a whole-service memory saving, or a general language-performance result.

There were **20 main trials: 12 review-ready outcomes and 8 controlled refusals**. All 20 task-integrity verifiers passed. Four additional cache/admission probes also verified. Execution totals were **12 builds, 24 actual STEP renders, 12 fresh native audits and 24 source-inspection workers**. The twelve final validation checks reused their current audits. The explicit cache probes added no build or audit. There were **zero provider calls**, and every candidate remains unapproved for engineering use.

Primary evidence is in [analysis.json](../artifacts/v04/control-parity/analysis.json), [results.json](../artifacts/v04/control-parity/results.json), [study-status.json](../artifacts/v04/control-parity/study-status.json), and the complete task directories beside them. No failed or refused timed arm was discarded.

## Fixed runtime, inputs and policy

The optimized Rust binary and frozen Python worker source came from `8916e68f4c175bdab291d7c0bf2978862be8915d`. Binary SHA-256 is `071d76828b845d0134e57a3f4c14e48fc2843027cfa45806de5d67767d5b6f72`. Both arms used the same locked, non-editable Python 3.12.14 environment and the same frozen `DomainTools`, parser, geometry, native worker and validation code. The binary and all 29 Python module hashes were checked again after execution and remained unchanged. [runtime.json](../artifacts/v04/control-parity/runtime.json) records the complete identities and host metadata.

The host exposed nine CPUs with an eight-CPU cgroup quota, on an AMD EPYC 9V74 system. Native work ran serially during an exclusive admission window. This was a shared host; unrelated nonnative activity was not eliminated. First and second trials each used fresh processes and fresh task directories. OS/filesystem caches were not flushed, so “first” denotes the first fresh-task trial rather than a cold machine. Arm order alternated by case and repetition. All active output was under `/tmp`; only completed evidence was copied to the workspace.

| Case | Supplied input | Purpose |
|---|---|---|
| straight3 | Three simple generated contours on grids, 600 × 230 pixels | Small successful baseline |
| known47_25 | Previously used round-flare development drawing, 25 stations, 1598 × 1860 pixels | Larger retained-engine comparison |
| degraded25 | Separate procedural development drawing with artificial raster degradation, 25 stations | Ambiguity/refusal behavior |
| mixed_height3 | Same raster as straight3; explicit ranges 0.2–2.5 m, 0–3 m, and 0.4–2.8 m | Unequal-height input behavior |
| genuine_partial | Authentic Balclutha structural section at frame108, 1068 × 1600 pixels; no calibrated station set supplied | Incomplete-request refusal |

The two 25-station inputs were explicitly designated development data. No sealed evaluator index, reference geometry or hidden numerical truth was accessed. The genuine sheet is retained archival evidence from the acquisition workstream, not a newly invented drawing. Its source and hashes are in [cohort.json](../artifacts/v04/control-parity/cohort.json). All four distinct source images and one actual STEP render were viewed; [pixel-inspection.json](../artifacts/v04/control-parity/pixel-inspection.json) records those observations. The partial request deliberately supplied neither station extraction/calibration nor symmetry/terminal-closure assumptions. Its refusal is evidence of input validation, not autonomous visual recognition that the sheet is incomplete.

Python's ordinary deterministic policy renders only oblique. This study therefore used the explicitly named benchmark policy `benchmark_rust_aligned_v1`, which mirrors Rust's tool-choice order and early failure/abstention logic and requires **body and oblique** before validation. It ran inside one persistent current Python `Harness.run`. Rust used one optimized `run --policy deterministic` process. Neither arm used an LLM.

The retained native build limits were 180 seconds wall time, 120 CPU seconds and 4 GiB. Render/audit limits were 120 wall seconds and 90 CPU seconds. Rust additionally imposed its 210-second/180-CPU-second/5-GiB outer bridge boundary. Python's global admission lock was benchmark-added around the task; Rust's admission is implemented per worker operation. The largest observed native receipt wall time was **43.5931 seconds**.

Rust also starts a fresh bridge per operation, maintains its stricter event/receipt boundary, and creates supplemental section-observation images on validation, including cache hits. Those are real implementation differences. The comparison aligns the requested geometry operations and outputs, while retaining and disclosing this extra work.

## Wall time and CPU

Values below are seconds, shown as **first / second fresh-task trial**. CPU is `wait4` whole-command accounting, including accounted waited descendants. It must not be added to the overlapping bridge or native-worker CPU receipts.

| Successful case | Python wall | Rust wall | Python CPU | Rust CPU |
|---|---:|---:|---:|---:|
| straight3 | 14.70 / 14.38 | 15.81 / 16.53 | 15.99 / 15.89 | 17.09 / 17.88 |
| known47_25 | 134.26 / 131.65 | 139.09 / 137.44 | 138.55 / 136.71 | 144.07 / 142.78 |
| mixed_height3 | 18.50 / 16.84 | 20.50 / 18.83 | 20.12 / 18.25 | 22.05 / 20.14 |

Individual Rust/Python wall ratios were 1.076 and 1.149 for straight3, 1.036 and 1.044 for known47_25, and 1.108 and 1.118 for mixed_height3. Two samples per case do not support confidence intervals or a broad performance ranking. The observed native-stage variation also contributes to end-to-end differences.

For the first Rust known47_25 run, the native receipts report 43.59 seconds for the build, 18.34 and 19.55 seconds for the two renders, 40.34 seconds for audit, and 8.12 seconds across source inspections. Their serial internal wall total is 129.95 seconds within the 139.09-second command. The corresponding Python internal total is 128.36 seconds within 134.26 seconds. Startup, serialization, hashing, supervision and other control work occupy the remainder; this residual is not a separately isolated language microbenchmark. Full per-operation, queue, bridge and native receipts are retained for every trial.

### Fixed successful-operation counts

| Per successful task | straight3 / mixed_height3 | known47_25 |
|---|---:|---:|
| Logical decisions, including finish | 7 | 13 |
| Source inspection calls | 1 | 3 |
| Selection calls | 1 | 5 |
| Native build | 1 | 1 |
| Actual STEP renders | 2 | 2 |
| Fresh audit / final cache validation | 1 / 1 | 1 / 1 |

The larger drawing's selection batches were 6, 6, 7, 5 and 1 candidates in both controllers. Rust additionally records one initialization bridge; Python initializes locally. Counts and complete normalized arguments match within every successful pair.

## Memory accounting

These are MiB, using the largest observed value across the two repetitions for each process category. Controller values are sampled self `VmHWM` at a 20-ms interval and are observed lower bounds. Bridge and native values are each process's reported self peak. No column is a simultaneous process-tree or container peak, and these columns must never be summed.

| Case | Python controller | Rust controller | Largest Rust bridge | Largest native process, either arm |
|---|---:|---:|---:|---:|
| straight3 | 23.51 | 7.32 | 32.22 | 531.42 |
| known47_25 | 47.83 | 22.46 | 44.10 | 1211.11 |
| mixed_height3 | 22.91 | 7.11 | 32.45 | 547.71 |

The Rust controller itself was smaller in these samples. Its additional Python bridge processes and the common native CAD processes prevent interpreting that result as an equivalent reduction in total service memory. Raw OS `wait4` maximum-RSS values are retained separately and described as individual-process maxima with waited-descendant accounting, not a concurrent tree total.

## Geometry, integrity and refused work

All six successful pairs passed the explicit comparison gate: zero command exits, both task verifiers valid, both review-ready, identical nonempty decision/selection sets, one build per arm, exact valid CAD/mesh hashes, successful closed-single-solid STEP reimports, and matching audited metrics and sample identities. Ratios are absent for every excluded pair. The gate requires complete finite positive metric fields and proper SHA-256 strings; absent fields cannot pass through empty equality.

[step-text-comparison.json](../artifacts/v04/control-parity/step-text-comparison.json) independently checks the retained actual STEP files against their recorded hashes. In all six pairs, STEP `DATA` bytes match exactly and full-file headers differ in their export timestamps. Audited length, beam, depth and volume differences are all zero. The maximum sampled selected-source-to-STEP deviations were **0.896516 mm** for straight3, **0.855503 mm** for known47_25, and **0.957704 mm** for mixed_height3, identical between controllers and repetitions. These measure approximation of the selected supplied traces. They do not establish vessel accuracy, contour identity, calibration correctness or between-station truth; the larger audit samples five of 25 stations.

| Refused workload | Python wall, first / second | Rust wall, first / second | Recorded behavior |
|---|---:|---:|---|
| degraded25 | 13.99 / 14.36 s | 14.09 / 14.82 s | Both inspect one batch and choose finish-abstain; zero selections/builds. Python calls the terminal state `blocked`, Rust `abstained`. |
| genuine_partial | 0.123 / 0.125 s | 0.144 / 0.128 s | Both block on insufficient sections and unresolved assumptions, before inspection/CAD. Rust stops at admission; Python records one finish-abstain decision. |

The archival arm is explicitly unequal in controller decision count. Neither refusal workload is used for a successful-CAD timing ratio. Their complete records remain available and all eight refusal task histories verify.

## Cache and admission probes

The cache probe copied a successful straight3 task independently for each arm. It captured the original inventory before copying, required exact copy equality, verified the copied task, performed one explicit current-candidate validation, and compared the original inventory again afterward. Both original tasks remained unchanged. Audit/build artifacts were unchanged and no new native audit or build directories appeared.

| Probe | Python | Rust |
|---|---:|---:|
| Explicit cached validation wall | 0.164 s | 0.490 s |
| Current-audit cache flag | `reused=true` | `reused=true` |
| New native audits / builds | 0 / 0 | 0 / 0 |
| Initialization command wall under deliberate hold | 1.037 s | 1.162 s |
| Reported admission wait | 0.934 s | 1.006 s |

The admission test held the same global lock for approximately one second and ran initialization only. Both arms demonstrably contended, both verified, and neither launched CAD. Import/startup occurs before admission, so the actual waits differ. The probe reports the observed delay; it is not a throughput comparison or a contention stress test. [probe-results.json](../artifacts/v04/control-parity/probe-results.json) retains all metrics and inventories.

## Independent review and evidence publication

A separate reviewer identified the need to enforce the declared comparison gate, distinguish actual contention from a timer consumed by startup, and separate original-before from copy-before inventories. Those analysis/probe corrections were applied before publishing ratios or running probes. A follow-up review found empty-metric and absent-hash equality gaps in the analysis; those were tightened. Fourteen controlled report-record checks passed: one real matched pair and thirteen negative mutations. They launch no worker and do not modify actual task evidence. The main timed driver remained frozen throughout; its exact version, the corrected probe driver and final analysis snapshot are all retained with their distinct hashes.

The completed payload contains **2,737 files / 198,728,445 bytes**, excluding only Python bytecode caches. The initial workspace copy matched every source hash, and a separate later invocation verified all **24 copied task histories** and all payload hashes before and after verification. [publication/copy-manifest.json](../artifacts/v04/control-parity/publication/copy-manifest.json) and the publication pass records retain the checks. No active native job ran in the workspace, and no original run was repaired or promoted by changing evidence.

## Reproduction

The source entry points are [v04_control_parity.py](../benchmarks/v04_control_parity.py) and [v04_control_parity_analysis.py](../benchmarks/v04_control_parity_analysis.py). The original runtime/commands and all inputs are retained in the evidence. The benchmark's `prepare` command uses the explicit original development paths; the preserved cohort is the portable record of the actual inputs.

To recalculate report eligibility from the completed evidence without running CAD:

```sh
python benchmarks/v04_control_parity_analysis.py artifacts/v04/control-parity
python artifacts/v04/control-parity/analysis-gate-probe.py
python artifacts/v04/control-parity/step-data-comparison.py
```

Fresh execution uses `v04_control_parity.py prepare`, then `run --out /tmp/NEW_STUDY --runtime FROZEN_RUNTIME`, followed by `probes`. Supply an equivalent installed environment and update the explicitly recorded environment/source paths for another machine. Acquire the native admission window before timing. Keep the frozen source and optimized binary fixed across both arms, preserve all outcomes, and apply the eligibility gate before interpreting any ratios.
