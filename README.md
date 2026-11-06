# MarinaFrame

A working local system that reads **calibrated 2D hull-section drawings**, measures their curves from image pixels, and constructs a source-linked 3D CAD hull envelope. It includes an interactive workbench, an independent evaluation harness, acquired public reference data, CAD exports, and retained success and failure evidence.

The supported task is precise: a person identifies the section panels, longitudinal stations, pixel scale, datum and vertical extent. The software measures the section shapes and constructs the envelope. It does not yet infer all those facts from an arbitrary shipyard drawing set.

This implementation uses deterministic computer vision and the CadQuery/OpenCascade geometry kernel. It does not require an LLM service, Blender, API credentials or a GPU. The experimental offset-table adapter uses an existing Tesseract OCR model. **No new neural model was trained.**

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

Tested on Linux with Python 3.12.14 and CadQuery 2.7.0. Python 3.11–3.13 is declared by the package; other platforms and Python versions have not been exercised in this release.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,documents]'

python examples/make_development_example.py
python -m vessel_reconstruction reconstruct \
  data/examples/development/spec.json \
  --out artifacts/my-development-run

python -m vessel_reconstruction verify artifacts/my-development-run
python -m vessel_reconstruction serve --artifacts artifacts --port 8765
```

Open **http://127.0.0.1:8765**. The server binds to localhost by default. Installation downloads Python dependencies; ordinary reconstruction and inspection then work offline. The optional OCR experiment additionally requires the system `tesseract` executable and the recorded language model.

Each reconstruction uses a new output directory. Existing runs are not overwritten. Exit code `0` means geometry was built and still requires review; exit code `2` means the run was blocked. A blocked run still contains evidence and gap explanations, but publishes no CAD model.

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
| Curve reader | Separates ink contrast tiers, filters fragments and traces a continuous section through source pixels; records coverage, stroke width and ambiguity diagnostics. |
| Geometry builder | Resamples measured half-sections, mirrors the declared symmetry and connects corresponding boundaries with ruled CAD faces; adds explicit envelope closures. |
| CAD validation | Requires one valid positive-volume solid; exports STEP and STL, reloads STEP and verifies volume and dimensions. |
| Evidence pipeline | Copies original source bytes, hashes sources/specifications/outputs, saves the exact inference Python source, and associates each section with its image region and calibration. |
| Review model | Successful geometry remains `review_required`; blocking gaps suppress published geometry. Named local review entries never establish authenticated engineering approval. |
| Workbench | Orbit/zoom, section selection, drawing overlays, supporting sources, uncertainty and gaps, CAD downloads, calibration editor and new reconstruction. WebGL has a software fallback. |
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

A successful run contains `result.json`, `input_spec.json`, `replay_spec.json`, the exact source files, `extracted_sections.json`, `cad_sections.json`, `mesh.json`, `model.step`, `model.stl`, and `implementation_source/`. The result records source regions, calibration, assumptions, gap messages, metrics, environment versions and content hashes.

Create a portable view of any real run:

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

Reviews are locally hash chained. Names are not authenticated and no decision sets `engineering_approved` to true. Content hashes detect changes relative to a local manifest; they are not an external signature.

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
Dependencies are resolved from the supported package ranges;
`requirements-lock.txt` preserves the original bundle environment as a reference,
not the CI dependency lock. Tesseract OCR and DejaVu fonts are installed in CI.
