# MarinaFrame

A working local system that reads **calibrated 2D hull-section drawings**, measures their curves from image pixels, and constructs a source-linked 3D CAD hull envelope. It includes an interactive workbench, an independent evaluation harness, acquired public reference data, CAD exports, and retained success and failure evidence.

The supported task is precise: a person identifies the section panels, longitudinal stations, pixel scale, datum and vertical extent. The software measures the section shapes and constructs the envelope. It does not yet infer all those facts from an arbitrary shipyard drawing set.

MarinaFrame 0.3 adds a **persistent domain-specific agent harness** around that engine. A policy or pretrained DeepSeek model can inspect source images, select inspected contour candidates, build provisional CAD, render the exported STEP and request independent checks. The controller owns budgets, cancellation, state, provenance and review boundaries. It never executes model-generated code. The deterministic pipeline remains available without credentials or a GPU; Blender is not required. **No new model was trained.**

## Agent harness quick start

Use Linux / Python 3.12 and the locked installation below. A small source-only example is generated with:

```bash
python examples/make_agent_example.py --out data/examples/agent
vessel-reconstruct agent run data/examples/agent/spec.json \
  --out /tmp/marinaframe-agent-task --policy deterministic
vessel-reconstruct agent verify /tmp/marinaframe-agent-task
vessel-reconstruct agent review /tmp/marinaframe-agent-task --out agent-review.html
```

The review file shows source overlays, contour choices, reimported STEP views and the full decision history. It downloads a typed selection decision that can be applied with `agent step`; the next `agent resume` regenerates and validates the candidate. Every output still requires human semantic review. A recorded assistant intervention is not expert approval.

See [the measured results and remaining limitations](docs/AGENT_RESULTS.md), [the harness contract and runnable workflows](docs/AGENT_HARNESS.md), [provider setup and exact replay](docs/agent-provider.md), [authentic data and annotation](docs/AGENT_DATA.md), and [the publication investigation](docs/AGENT_PUBLICATION_INVESTIGATION.md). Evidence from actual experiments is separate from mock tests. The live development trajectory inspected pixels, selected contours and requested CAD, then correctly abstained after a publication integrity failure. A further live experiment was stopped by automatic approval review; it is not presented as a successful live CAD completion.

Active run directories in this managed execution environment must be outside its synchronized workspace. The bounded investigation reproduced delayed restoration of deleted transaction files in workspace runs. Executing under `/tmp`, then importing only completed verified artifacts, preserved the existing checks. This is an environment-specific mitigation, not proof that an external synchronizer has been repaired.

## Repository scope

This is the source-only public research repository for MarinaFrame. It includes the
reconstruction application, tests, procedural data generators, evaluation code and
historical research documentation. It is not a fabrication-ready vessel modeler.

The original research bundle also contained large generated datasets, archival
scans, pretrained OCR weights, CAD exports and frozen evaluation evidence. These
are **not included in this repository**. Historical reports and source inventories
in `VALIDATION.md` and `DATA_SOURCES.md` describe that original bundle; paths into
`data/external`, `data/public_scan`, `data/generated` and `artifacts` refer to omitted
material. Their benchmark numbers are historical claims, not reproduced by CI.
Restoring the exact recorded inputs is required to replay those evaluations.

The quick start generates its own procedural development drawing locally.
Unit/integration tests generate their own fixtures and do not need the research
bundle. No third-party datasets or pretrained weights are redistributed here.

## Install and run

Version 0.3 supports the exercised Linux x86_64 / Python 3.12 profile, using CadQuery 2.7.0. The reference patch version is Python 3.12.14. macOS (including M5) and Windows are not yet validated; the bounded worker and atomic publication profile require Linux.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-linux-py312.lock
python -m pip install --no-build-isolation --no-deps -e .

python examples/make_development_example.py
python -m vessel_reconstruction reconstruct \
  data/examples/development/spec.json \
  --out artifacts/my-development-run

python -m vessel_reconstruction verify artifacts/my-development-run
python -m vessel_reconstruction serve --artifacts artifacts --port 8765
```

Open the **one-time login URL printed by the server**, including its `#session=...` fragment. It exchanges for a local HttpOnly session cookie and is removed from the address bar. Plain localhost API access is unauthenticated until that exchange. Remote binding is refused. Installation downloads Python dependencies; ordinary reconstruction and inspection then work offline. The optional OCR experiment additionally requires the system `tesseract` executable and the recorded language model.

Each reconstruction uses a new output directory. Existing runs are not overwritten. Exit code `0` means a bounded worker published verified geometry that still requires review. Exit code `2` means a blocked, failed, cancelled, interrupted, timed-out or resource-limited outcome; the CLI prints the actual state. Storage failure can prevent a terminal file, in which case private staging is retained for recovery. Existing runs are never replaced.

### Using your own drawing

In the workbench, upload a PNG, JPEG or other supported raster drawing and use the calibration editor:

1. Select one starboard half-section panel per station. The contour must be a single-valued half-breadth as a function of height.
2. Mark the centreline and baseline origin in the original image coordinates.
3. Set scale using a known drawing distance, or enter pixels per metre.
4. Enter the longitudinal position of that station and the measured vertical interval.
5. Repeat for at least three distinct stations. Declare the symmetry assumption and terminal closure.
6. Reconstruct, then inspect the recovered curves over their source image and review every listed assumption or gap.

You can also upload a drawing plus a JSON specification. Supporting station-reference documents must be uploaded as actual bytes; the browser API does not accept arbitrary existing server file paths. The CLI accepts explicitly named local input files.

PDF pages can be rendered by the CLI adapter with the `documents` extra. Pixel coordinates then refer to the selected rendered page at the declared DPI. DXF/DWG must first be exported to a calibrated raster view. 3D reference files are not inference inputs.

## What is built

| Component | Behavior |
|---|---|
| Curve reader | Tracks measured source pixels while retaining plausible alternatives across contrast bands; unresolved identity blocks extraction. Explicit pixel corridors select evidence without inventing a curve. |
| Geometry builder | Preserves significant knots under a default 1 mm half-breadth approximation bound, establishes shared correspondence across elevation domains, mirrors declared symmetry and builds bounded ruled CAD faces. |
| CAD validation | Requires one valid positive-volume solid; exports STEP and STL, reloads STEP and verifies volume and dimensions. |
| Evidence pipeline | Atomically publishes a complete schema 2 run; the manifest covers result metrics, input/replay specs, observations, CAD sections, source copies, implementation and exports. Verification also recomputes identity and geometry consistency. |
| Review model | Successful geometry remains `review_required`; blocking gaps suppress published geometry. Named local review entries never establish authenticated engineering approval. |
| Workbench | Authenticated loopback session, bounded durable SQLite queue, cancellable isolated workers, source/candidate overlays, CAD deviation, separate local review state and integrity-gated downloads. WebGL has a software fallback. |
| Data and evaluation | Procedural drawing generation, independent dense numerical references, an externally authored CAD reference, isolated image/spec inference subprocesses, frozen manifests, baseline comparison and complete case reports. |
| Experimental table OCR | Reads feet/inches/eighths from declared image cells using two Tesseract configurations; disagreement, malformed tokens or insufficient confidence block required cells. |

## Coordinates, exports and meaning

Input specifications, JSON meshes and reported dimensions use **metres**. The geometry kernel, STEP and STL use **millimetres**. STEP round trips are checked. STL does not carry an embedded unit declaration, so select millimetres when importing it elsewhere.

- `x`: supplied longitudinal station position.
- `y`: observed starboard half-breadth; port geometry comes from the declared mirror assumption.
- `z`: measured elevation, positive upward.

The result is an **enclosed hull envelope** over the supplied stations and height range. Its volume is not steel volume and is not automatically vessel displacement. The terminal planes, top and any nonzero-width lower edge receive mathematical closures. The system does not infer shell thickness, material, frames, decks, compartments, piping, machinery or current as-built condition.

STEP contains an actual boundary-representation solid. Its ruled faces are not a native shipbuilding part hierarchy or a parametric CAD feature history. The measured sections and replay specification remain editable inputs for regeneration.

## Reproduce the tests and evaluation

```bash
python -m pytest -q

# Requires the omitted original frozen fresh-confirmation inputs:
python -m benchmarks.evaluate data/generated/confirmation_v2 \
  --out artifacts/my-confirmation-evaluation --jobs 2 --timeout 90

# Requires the external source files described in DATA_SOURCES.md:
python -m benchmarks.make_suite --suite holdout \
  --contract benchmarks/confirmation_contract_v2.json \
  --out data/generated/my-confirmation-copy
```

The evaluator rejects modified manifests, drawings, specifications or reference labels. Each inference subprocess receives only a source image and the permitted calibration specification. Reference points and volumes are decoded by the evaluator after inference completes. This is an auditable data-flow separation, not an operating-system sandbox.

Both numerical error gates must be met for a reconstruction case to pass. Missing required sections, invalid CAD and timeouts count as failures. Clean and degraded versions of a given geometry are paired observations, not independent hulls. The initial and fresh confirmation runs use different procedural seeds; the external DTMB hull is reused for confirmation and is identified as a regression repeat.

`benchmarks/external_hull.py` regenerates section references from the retained and hash-checked DTMB IGES. Dense references are used only in dataset generation and scoring. They do not enter the inference package.

## Outputs and review

A successful schema 2 run contains `manifest.json`, immutable `result.json`, `input_spec.json`, `replay_spec.json`, the exact source files, `extracted_sections.json`, `cad_sections.json`, `mesh.json`, `model.step`, `model.stl`, and `implementation_source/`. The result records source regions, calibration, assumptions, gap messages, metrics, environment versions and content hashes.

Create a portable view of a verified schema 2 run:

```bash
python -m vessel_reconstruction snapshot artifacts/my-development-run \
  --out artifacts/my-dtmb-workbench.html
```

Record a local review decision only after inspecting the output. Obtain the exact run ID from `result.json`:

```bash
python -m vessel_reconstruction review artifacts/my-development-run \
  --decision needs_information --reviewer 'Reviewer name' \
  --notes 'Verify the original longitudinal station datum.' \
  --expected-run-id RUN_ID_FROM_RESULT_JSON
```

Review events live separately in `review_history.json`; `review_state.json` is a derived cache. Reviews do not edit the inference record and are locally hash chained. Names are not authenticated and no decision sets `engineering_approved` to true. Content hashes detect changes relative to a local manifest; they are not an external signature.

## Important limits established by testing

The numerical proof concerns calibrated, isolated section views with a known scale. It does not establish reliable understanding of arbitrary overlapping body plans, dimension conventions, faint competing lines, revision conflicts or all historical scan defects.

A real Balclutha frame drawing exposed a semantic failure: the first contour heuristic accepted a trace that switched between different physical lines. The erroneous trace and its rejection by AI visual review are retained; no human or engineer signoff occurred. The real historical measurement-table attempts also remain blocked because too many required cells are uncertain. These are substantive remaining capabilities, not successful reconstructions.

Moderate synthetic degradation consists of the documented blur, image noise, sparse speckles, brightness gradient and JPEG compression. It does not cover rotation, severe stains, handwriting, perspective distortion or missing pages. The independently authored DTMB CAD test is rasterized into new drawings and cropped to a supported continuous hull region; it is not an original paper drawing or a reconstruction of the entire vessel.

## Source and license information

`DATA_SOURCES.md` describes every acquired source and derived dataset. The original bundle retained source files, hashes and license notices; data files are not redistributed in this source-only repository. The DTMB source repository provides an MIT license; the Balclutha HAER drawings are documented as US federal government public-domain works; the optional official Tesseract language model is Apache-2.0. Those notices retain their own scope.

The project is publicly viewable research software, with all rights reserved under `LICENSE`. Public visibility does not grant an open-source license. No hosted application is deployed by this repository. See `ARCHITECTURE.md` for implementation choices and extension points, and `CONTRACT.md` for input/output schemas.

## Continuous integration

GitHub Actions runs the complete test suite on Linux / Python 3.12, checks the
package build and CLI entry point, and runs a generated-development reconstruction
and export verification. It does not replay the historical benchmark.
The main job installs exact wheel hashes from `requirements-linux-py312.lock`;
`requirements-lock.txt` remains the original reference. Dependency-range updates
run separately on manual dispatch. Actions are commit-pinned and permissions read-only.
A fresh wheel environment, bounded secret-pattern scan and OSV check are included.
Three VTK GLTF advisories remain explicitly scoped and time-limited; this is not
a claim that every installed dependency is vulnerability-free. Tesseract OCR and DejaVu fonts are installed in CI.

## Hardening continuation (0.2)

See [current validation and dispositions](docs/HARDENING_RESULTS.md),
[local operation and backup](docs/OPERATIONS.md),
[optional model experiments](docs/OPTIONAL_MODELS.md), and
[dependencies and unresolved licensing decisions](docs/DEPENDENCIES_AND_RIGHTS.md).
The repository license and public visibility are unchanged. No application is deployed.

Schema 1 research runs are recognized as legacy and do not pass the stronger
schema 2 verifier. Preserve them, then reconstruct into a new directory; see
`CONTRACT.md` for migration. The new contour policy intentionally abstains on
some light-grid fixtures previously accepted automatically. An explicit
`contour_selection` in image coordinates can resolve identity, with the original
source and excluded alternatives retained. Download the replay specification,
make a documented correction and submit a new run; never edit a sealed result.

The optional OpenCode Go adapter remains outside reconstruction. A read-only
metadata request used the supplied credential; no live generation or paid call
was made. The frozen mock harness and unchanged Tesseract baseline are executable
offline. Provider overflow/budget permission is still needed for live comparison.
