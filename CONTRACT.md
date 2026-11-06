# Shared implementation contract (v1)

Package: `vessel_reconstruction`, source layout `src/`. All distances are metres.
Root owns schemas/core/geometry/provenance/CLI. Parser agent owns `ingest.py`.
Dataset agent owns `benchmarks/` + `data/`. Workbench agent owns `server.py` + `web/`.

## Drawing specification

```json
{
  "schema_version": "1.0",
  "vessel_id": "example",
  "source": {"file": "drawing.png", "url": null, "license": "generated"},
  "units": "m",
  "symmetry": "port_starboard",
  "symmetry_evidence": "Explicit assumption; review required",
  "end_closure": "flat_at_terminal_stations",
  "sections": [
    {
      "id": "frame-01", "x_m": 0.0,
      "roi_px": [20, 40, 300, 340],
      "calibration": {"centerline_px": 45, "baseline_px": 310, "pixels_per_metre": 50},
      "z_min_m": 0.0, "z_max_m": 5.0,
      "evidence": "Human-declared viewport and scale; curve reconstructed from pixels"
    }
  ],
  "components": []
}
```

Paths resolve relative to the specification. All pixel coordinates are **global image coordinates**, ROI is left/top/right/bottom exclusive. Section is a starboard half-section, y >= 0, z upwards, with `y=(pixel_x-centerline_px)/pixels_per_metre`, `z=(baseline_px-pixel_y)/pixels_per_metre`. Curves can lie on the centreline near the keel. Region and calibration metadata are user assistance, not extracted geometry, and must be disclosed. No source offsets, shape-generating parameters, GT arrays, or reference mesh in this specification. Missing/invalid calibration must fail explicitly. Each panel has one hull contour; arbitrary overlaid body plans are outside the default parser contract.

## Parser API

`from vessel_reconstruction.ingest import extract_sections`

`extract_sections(spec: dict, base_dir: Path) -> dict`

Return JSON-compatible:
```json
{
  "sections": [{"id":"frame-01","x_m":0,"points_yz_m":[[0,0],[1,1],[2,5]],"confidence":0.98,"coverage":0.99,"evidence":{"roi_px":[20,40,300,340],"calibration":{},"source_file":"drawing.png"},"warnings":[]}],
  "gaps": [{"id":"...","kind":"missing_scale","severity":"blocking","section_id":"...","message":"..."}],
  "diagnostics": {},
  "method": "raster_curve_tracking"
}
```

Parser returns measurements/observations, not engineering approval. Structured errors preferred to unhandled errors. `confidence` is a heuristic quality score, never a probability of correctness. Any required section failure is a blocking gap (do not silently loft through it). Target >=65 evenly spaced z points per section where data supports it. Root can resample for CAD. All optional adaptors clearly identify their input form.

## Core API (root implements)

`from vessel_reconstruction.pipeline import reconstruct`

`reconstruct(spec_path: str | Path, output_dir: str | Path, *, export_cad: bool = True) -> dict`

Writes `result.json`, `model.step`, `model.stl`, `mesh.json`, source image copy, extracted sections, and evidence. Result schema:
```json
{
  "schema_version":"1.0", "run_id":"...", "vessel_id":"...",
  "status":"review_required", "review":{"state":"unreviewed","engineering_approved":false},
  "method":"raster_curve_tracking+section_loft", "sources":[{"id":"source-1","file":"source.png","sha256":"...","url":null}],
  "parts":[{"id":"hull","name":"Reconstructed hull envelope","kind":"hull_envelope","source_ids":["source-1"],"section_ids":[],"status":"review_required","mesh_file":"mesh.json"}],
  "sections":[], "gaps":[], "assumptions":[],
  "metrics":{"volume_m3":1,"surface_area_m2":1,"length_m":1,"beam_m":1,"depth_m":1,"cad_valid":true,"solid_count":1,"step_roundtrip_relative_error":0},
  "exports":{"step":"model.step","stl":"model.stl","mesh":"mesh.json"},
  "timing_seconds":1
}
```
Blocked runs also produce result.json, with status `blocked` and no misleading geometry. Mesh JSON: `{ "vertices": [[x,y,z],...], "faces": [[i,j,k],...], "parts": [{"id":"hull","face_start":0,"face_count":123}] }`.

## Benchmark separation

`benchmarks/generate.py` may create source images, view specifications and **separate** `ground_truth.json`. Only spec/image flow to inference. Evaluation reads ground truth after reconstruction. Holdout families/seeds and public-source hashes freeze before final evaluation; all attempted cases, abstentions and failures stay in the report. No changing gates after observing failures.

## Core command

`python -m vessel_reconstruction reconstruct input/spec.json --out artifacts/run-name`

`python -m vessel_reconstruction serve --artifacts artifacts --port 8765`

No engineer signoff automatically; explicit symmetry/end-cap assumptions remain in all outputs. A closed hull **envelope** does not imply steel thickness, complete internal structure, current as-built condition or structural certification.

## Final construction and evidence additions

The final geometry implementation uses `explicit_correspondence_ruled_panels_v2`: standard ruled BRep faces connect the same measured half-section indices at neighbouring stations. Source measurements are linearly resampled to33 elevations for CAD, with the original measurements preserved. This avoids automatic closed-wire correspondence when zero-width keels and finite flat bottoms have different edge counts. No minimum-width epsilon is inserted.

New runs retain `implementation_source/vessel_reconstruction/*.py` with hashes in `provenance.implementation_snapshot`; `verify` checks these as well as source/spec/output hashes. A separate `station_reference` may declare a supporting source file, SHA, URL, license and description. That original document is copied and linked as `source-2`. Browser submissions must upload its bytes rather than reference an arbitrary local path.

## Experimental table input mode

Set `input_mode` to `offset_table_ocr`, `units` to `m`, and `table_value_units` to `feet_inches_eighths`. Keep the same source, symmetry and end-closure declarations. Each of at least three stations supplies `id`, `x_m`, a station-column `roi_px`, evidence text, and at least five `cells`. Each cell contains only its source `roi_px` and its known elevation `z_m`. Half-breadth values are not permitted as input fields. Cell rectangles must be inside the station column; elevations must be unique, finite and bounded.

Table half-breadths come from recognized source text. Pixel scale/centreline/baseline do not determine these numeric widths. Two Tesseract passes must agree on a valid feet/inches/eighths literal and meet the fixed confidence threshold. Uncertain required cells block the station and any resulting hull. Each accepted cell retains raw OCR text, confidence, source crop and converted value. Table observations use their measured row count, rather than pretending to supply129 independent curve samples.

The included historical table experiments remain blocked; the table adapter's successful geometry integration tests use controlled printed measurement fixtures. No human engineering approval or successful full archival hull reconstruction is asserted.
