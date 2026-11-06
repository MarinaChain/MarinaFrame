# MarinaFrame implementation contract (0.2)

## Scope and coordinates

The supported input is an assisted, calibrated set of starboard half-sections,
with a single half-breadth y at each height z. Input/output measurements and JSON
meshes use metres; OpenCascade, STEP and STL use millimetres. STL carries no unit
metadata. An envelope is not thickness, structure, material, compartments, a
complete vessel, present-day condition or automatically displacement.

The input specification remains `schema_version: "1.0"`; the immutable **result**
contract is now schema 2. These are different schema namespaces.

## Drawing specification

Supply `vessel_id`, `source.file`, `units: "m"`, `symmetry: "port_starboard"`,
`symmetry_evidence`, `end_closure: "flat_at_terminal_stations"`, and at least three
sections with distinct IDs/stations. Optional `components` does not supply hidden
geometry. Each curve section has `id`, `x_m`, `roi_px: [left,top,right,bottom]`,
`calibration: {centerline_px, baseline_px, pixels_per_metre}`, `z_min_m`, `z_max_m`
and evidence text. Coordinates are global pixels; ROI right/bottom are exclusive.

`y=(pixel_x-centerline_px)/pixels_per_metre` and
`z=(baseline_px-pixel_y)/pixels_per_metre`. Stations, scale, datum, view rectangles
and symmetry are supplied assistance, not inferred achievements. No numeric
half-breadth arrays, target meshes, hull parameters or evaluation answers may
enter an inference specification.

PDF inputs additionally declare a selected `page_index` and `render_dpi` (default
144, bounded36–300). Optional `station_reference` retains a supporting document
and its provenance; web submissions upload its bytes. The CLI may name explicit
local files, but only regular bounded files are captured. All source snapshots,
including references, undergo resource preflight before previews or extraction.

Strict typed validation rejects unexpected fields, duplicate JSON keys, booleans
as numbers, nonfinite/overflow values, malformed nesting, invalid references,
duplicate stations and excessive work. See `schema.py`/`resources.py` for exact
bounds rather than relying on UI hints.

### Explicit contour identity assistance

An optional section field selects a corridor in source pixels:

```json
{"contour_selection":{"anchors_px":[[271,60],[271,360]],"half_width_px":5}}
```

Use2–64 finite anchors in the ROI with distinct pixel elevations spanning the
complete calibrated interval, and a half-width in(0,128]px bounded by ROI width.
This is supplied metadata, not authenticated human signoff. The corridor excludes
other candidates but never becomes geometry: empty pixels or two sustained
candidates inside it still block. Excluded alternatives remain in diagnostics.
Candidates outside the selection are not silently erased from the evidence.

### Experimental table mode

Set `input_mode: "offset_table_ocr"` and
`table_value_units: "feet_inches_eighths"`. Each station declares its column ROI
and at least five cells containing only `roi_px` and known `z_m`. Numeric widths
are read from source text. Two correlated Tesseract passes must agree exactly on
a valid feet/inches/eighths literal at the fixed quality threshold. No carry,
digit repair, neighboring-cell inference or hull prior is used. Total cells and
enlarged crop work are bounded. Uncertain required cells block the model.

## Geometry contract

Observed polylines remain intact. Adaptive CAD correspondence uses a union of
normalized-height knots across stations and a default maximum half-breadth error
of 0.001 m relative to each observed piecewise-linear section. All source/CAD knots
are checked; height-weighted RMS, section area and beam errors are recorded.
Endpoints and zero transitions are retained. The optional `samples` Python
argument supplies minimum density, not a feature-erasing cap. Bounds are300
stations,1,025source points per section,513 common knots and20,000estimatedfaces.
Conflicting elevations, interior pinches and unsupported topology block.

Ruled interpolation between stations remains an assumption. The1mm bound is not
a bound on semantic identity, calibration, scan distortion or a physical ship.
Actual STEP is reloaded for validity/dimensions/volume; analytic diagnostic tests
also cut STEP at stations and between stations. STL meshing uses explicit
absolute millimetre deflection rather than CadQuery's relative default.

## Atomic inference API and immutable files

`reconstruct(spec_path, output_dir, export_cad=True)` is a synchronous trusted
Python API. `output_dir` must be absent, including empty directories. The CLI and
server call `run_isolated` for supported bounded native execution. A direct Python
call does not itself supply the worker's CPU/address-space/wall restrictions.

A run reserves an exclusive destination and stages privately on the same
filesystem. Required evidence is completed, fsynced, sealed and verified before
atomic no-replace publication. No non-success record retains model exports.
If storage cannot persist a failure record, publication raises explicitly and
leaves discoverable staging; interruption recovery removes partial geometry.

`result.json` schema 2 is immutable. Terminal statuses are `review_required`,
`blocked`, `failed`, `cancelled` and `interrupted`. Success always means only
`review_required`; `engineering_approved` remainsfalse. Worker/queue states also
distinguish timeout/resource limits. An already-durable verified publication is
reconciled as committed if a worker dies before returning its receipt.

`manifest.json` hashes every immutable file, including the entire result record.
The result does not hash its manifest. Required files include `input_spec.json`,
`replay_spec.json`, `result.json` and submitted source/spec/implementation evidence
when capture succeeded. Success additionally requires `extracted_sections.json`,
`cad_sections.json`, `mesh.json` and requested STEP/STL exports. `--no-cad` still
builds the kernel solid/mesh but explicitly omits STEP/STL.

`verify_run` rejects missing/empty/stripped manifests, unsealed reservations,
unknown schemas, traversal and symlink escapes. It checks all hashes, recomputes
identity, source/replay/section relationships, CAD approximation, analytic ruled
volume, bounds and mesh counts. It distinguishes integrity against a local
manifest from authenticity: an actor replacing the entire record/manifest is not
detected as a forged external signature. Verification never certifies a ship.

## Review, migration and rollback

`review_history.json` is a separate locally chained event log bound to the
immutable manifest; `review_state.json` is only a cache. Current review state is
derived from checked history. A name is not an authenticated professional identity.
Concurrent reviews serialize. Review never changes `result.json` or authorizes
blocked geometry.

Schema 1 runs are recognized as `legacy_unsealed`, with `valid=false` and no new
export assurance. Preserve old folders unchanged. Reconstruct the retained
original input (or replay specification with its source copies) into a new
directory; do not modify a v1 manifest to pretend stronger evidence. Record the
relationship in the correction/review notes. Full automatic revision-lineage
management and an in-browser contour editor remain future work.

To replay archived Python source, set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH`
to its `implementation_source` directory, and install the recorded environment.
Never add bytecode caches inside a sealed run. Roll back code in a separate
checkout and keep separate artifact roots; old software must not modify schema 2
runs or the new SQLite queue. Stop the server before restoring a quiescent backup
as described in `docs/OPERATIONS.md`.
