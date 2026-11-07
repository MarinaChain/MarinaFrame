> Source-only repository note: this document records the original research bundle. Large data, model weights, exports and frozen evidence referenced below are not included here. CI does not reproduce historical benchmark scores.

# Reconstruction benchmark

> **Historical scripts (0.5):** `live_harness_pilot.py`, `reaudit_preserved_native_run.py` and the Python arm of `v04_control_parity.py` import the removed `agent_harness`/`agent_provider` modules. They are kept as records and run only against a pre-0.5 checkout (commit `19afbeb` or earlier). The 0.3 validation probe was removed; see `docs/HISTORICAL_VALIDATION_PROBE.md`.

This benchmark tests a specific assisted workflow: an operator identifies one starboard section per panel, supplies its station position, scale, origin, vertical extent, symmetry and terminal closure, and the parser reconstructs the section from raster pixels. It does not test automatic interpretation of arbitrary ship drawings. The implementation uses computer vision and a CAD kernel; this suite neither trains nor evaluates an LLM.

## Frozen test design

`holdout_contract.json` was written before held-out scoring. Its original content is embedded in each generated suite manifest, so later edits to the working copy cannot retroactively change a saved suite's gates.

| Group | Cases | Geometry and purpose | Predeclared acceptance |
|---|---:|---|---|
| Clean | 20 | Ten multi-chine hulls and ten round/flare hulls, different parameterizations from the development family | At least90% pass; each passing case has volume error≤3%, section RMS/full beam≤1%, and one valid CAD solid |
| Degraded | 20 | The same held-out geometry under noise, light speckles, blur, JPEG compression and a paper gradient | At least80% pass; volume error≤5%, section RMS/full beam≤2%, and one valid CAD solid |
| Negative | 4 | Missing scale, negative scale, absent contour, insufficient sections | All four must block and produce no model exports |
| External | 2 | Newly rasterized sections of independently authored DTMB5415 CAD, clean/degraded | At least one passes; volume error≤5%, section RMS/full beam≤2%, and one valid CAD solid |
| Historical challenge | 1 | Unannotated Balclutha body plan with overlapping lines and annotations | Retain outcome; expected blocked because required panel/calibration declarations are absent. This is not a successful historical reconstruction |

Development uses a Wigley-like family and seeds17,23,41. Hold-out seed lists and rendering styles are explicit in the contract. Synthetic cases use25 drawing stations×129 ordinates. Their numerical reference volumes use a denser801×1025 integration. External cases use41 stations×257 ordinates, with reference volume integrated over241 independently extracted stations.

These are finite, flat-capped hull envelopes. The synthetic end sections deliberately have a small finite beam so terminal closure is explicit and nondegenerate. The external geometry is cropped as documented below. No output should be described as a complete vessel.

## Data boundary

Each case has two separate directories:

- `inference/<case>/`: `spec.json` and `drawing.png` only.
- `private_labels/<case>/`: numerical section curves, target volume, generator parameters and provenance.

The evaluator verifies hashes, snapshots the inference Python source, copies only the declared image/spec into a temporary input directory, and starts an independent CLI process. Numerical labels are first decoded for scoring after that case's inference ends. Source CAD and numerical answers never enter the reconstruction API. This is a checked data flow, not an operating-system access-control sandbox.

The spec contains explicit **operator assistance**: station identity and x coordinate, single-contour viewport, pixel scale and origin, z bounds, mirror symmetry, and terminal closure. These declarations are not inferred successes. The external source URL is retained as attribution metadata; inference loads the local raster, not the source CAD URL.

`inference_code_manifest.json` records a source snapshot, hashes and dependency versions. That frozen snapshot is used for every case in the run, preventing simultaneous workspace edits from mixing model versions. Each attempted case, timeout, exception and abstention is retained in `cases.jsonl`; reporting never drops difficult cases. An existing report/checkpoint cannot be overwritten.

## Metrics and baseline

A numerical success requires all of the following:

1. The result remains `review_required`, because no engineering approval has occurred.
2. OpenCascade reports a valid shape and exactly one solid.
3. Every ground-truth station is present once, at the correct longitudinal position, with its complete reference elevation range.
4. Absolute relative volume error is under the group's gate.
5. Section RMS is under the group's gate. Half-breadths are compared at257 common elevations, stations receive equal weight, and RMS is normalized by the **full** hull beam.

Volume is checked against dense numerical integration, not against the CAD model's own re-imported volume. A STEP round trip, when supplied by the pipeline, tests export fidelity separately.

The intentionally simple baseline takes the rightmost pixel darker than120 on65 rows in each operator-specified viewport. It uses the same calibration and station positions, but no continuity reasoning or CAD validity guarantee. Its errors and abstentions are retained; better aggregate volume alone does not establish a better reconstructed contour because local errors can cancel.

The evaluator allows90seconds per isolated case by default and two concurrent processes. Timeout is a failure, not an omitted measurement. `--no-cad` is useful for diagnosis but cannot meet the valid-CAD success gate.

## Reproduce

From the repository root, with package dependencies installed:

```bash
python -m pytest tests/test_benchmark.py -q
python -m benchmarks.make_suite --out data/generated/new_development --suite development --without-external
python -m benchmarks.evaluate data/generated/new_development --out data/generated/new_development_results --jobs 2
python -m benchmarks.make_suite --out data/generated/new_holdout --suite holdout
python -m benchmarks.evaluate data/generated/new_holdout --out data/generated/new_holdout_results --jobs 2
```

Suite and report destinations must be fresh. Individual development cases can be selected with repeated `--case` arguments. A partial run is explicitly marked and cannot satisfy the full-suite gate.

`generate_section_sheet(sections, output_dir, label_dir=...)` accepts arbitrary known `x_m` plus `points_yz_m` section arrays and creates the image/spec without putting curve ordinates in the spec. It requires y≥0, strictly increasing z within each section, and increasing station positions. All raster bytes are encoded and atomically published before their hashes are frozen.

To regenerate the external CAD reference after verifying the retained source hash:

```bash
python -m benchmarks.external_hull
```

That script is a data-production utility, not an inference adapter.

## External reference scope

The source is the MIT-licensed `mathLab/WaveBEMapp-DTMB-5415` repository, pinned to commit `afad0f04a2ce5ee03f37dcefbe697a5281bc0168`. Its IGES file is a three-face half-hull surface rather than a closed solid. OpenCascade converts its metre units to millimetres; the extraction utility explicitly converts back.

We retain original longitudinal x∈[-2.5,+2.9]metres, shift this to x∈[0,5.4], mirror the starboard surface and cap the terminal planes. A farther-forward bulb section has two disconnected contours and falls outside the single-valued-section contract. It is explicitly excluded rather than joined. The dense reference volume is **1.3241133171266837m³**, for this cropped/mirrored/capped region only. Neither the actual tips nor appendages are tested. Source URLs, MIT text and content hashes are in `data/external/dtmb5415/source_manifest.json`.

## Historical evidence

Original Balclutha HAER sheet7 contains an independently authored body plan and hull-offset table. Sheet3 supplies station locations. Both are National Park Service public-domain works; exact URLs, file hashes and rights evidence are retained in `data/external/balclutha/`.

The numbered stations0–20 are **not equally spaced**. The manually transcribed printed dimensions are in `station_positions_manual.json`, with unaltered source and detail crops. The archival source describes the **inner** hull surface, only measured on starboard in1988, and states its own accuracy limitations. Any table-driven historical experiment must retain those distinctions and the manual calibration/transcription assistance.

The raw unannotated-sheet case here tests refusal to invent missing declarations. The separate independent real-scan and table-OCR experiments are owned by the parser/audit agent; their results must be reported separately from these numerical benchmarks.

## Interpretation limits

Synthetic held-out parameterizations are useful implementation evidence, but all raster styles come from the same renderer and do not cover arbitrary shipyard scans. The external geometry has independent authorship, while its input drawing is newly generated. The suite does not establish general historical drawing understanding, dimensional accuracy in the as-built vessel, shell thickness, engineering suitability, watertight physical construction, class compliance, or production readiness. Valid CAD is one check in a larger review process.

## Initial results and fresh confirmation protocol

The original 47-case evaluation is preserved in `data/generated/holdout_evaluation/`. It completed in 549.01 seconds and **failed** the original clean and degraded gates: 0/20 clean, 10/20 degraded, 2/2 external reconstructions, plus 5/5 correct information-related abstentions. See `data/INITIAL_BENCHMARK_FINDINGS.md`; conditional error means must always be reported with coverage.

After that run exposed grid segmentation and CAD loft failures, `confirmation_contract_v2.json` froze twenty fresh procedural seeds and the unchanged original gates. The confirmation suite uses the same generator families and renderer. External DTMB geometry and the historical sheet are explicitly reused regression cases; they are not fresh external holdouts. No confirmation case should be scored until the generic parser/CAD corrections are frozen.

```bash
python -m benchmarks.make_suite --out data/generated/fresh_confirmation --suite holdout --contract benchmarks/confirmation_contract_v2.json
python -m benchmarks.evaluate data/generated/fresh_confirmation --out data/generated/fresh_confirmation_results --jobs 2
```

The materialized confirmation inputs are already frozen at `data/generated/confirmation_v2/`; reproductions should use fresh destinations. Generation is deterministic under the recorded dependencies. Every case gets the same explicit annotation assistance as the original suite.

The first evaluation used append-only checkpoints; two append records were absent while the final in-memory report retained all 47 outcomes. The original checkpoint and an exact recovery receipt are preserved. Future evaluations atomically publish the complete checkpoint after each case and verify its bytes. This change affects persistence, not scoring. Original source snapshots and failed results remain available.

### Meaning of section accuracy

`rms_section_error_over_beam` compares extracted raster section coordinates against reference coordinates at their declared drawing stations. It does not directly measure the final STEP surface. The frozen gates additionally require global CAD volume accuracy and one valid solid. A supplementary actual-STEP cutting diagnostic is available in `audit_exported_step.py`; the initial diagnostic was incomplete and is reported as inconclusive in `data/INITIAL_BENCHMARK_FINDINGS.md`, without changing any original score. Group aggregates include any available partial extraction metrics; use per-case success-filtered metrics and their denominators when describing accuracy of completed reconstructions.
