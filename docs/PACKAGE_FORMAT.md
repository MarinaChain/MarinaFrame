# Draft vessel package, schema 1.0

The export package is a ZIP file for loading a draft into another vessel-record tool.
It contains the selected hull revision and the tank, steel, frame and display inputs
available at export time. It is not a complete copy of the task or its revision history.
The writer is `src/vessel_reconstruction/exports/`.

Every delivery remains a draft. `engineering_approved` stays `false` in the manifest,
hydrostatics JSON and spatial JSON records. Source labels, review states, file hashes,
an IMO check digit and successful tests do not give engineering sign-off. The package
is not evidence of class acceptance, construction readiness or the current as-built
condition. Engineering sign-off happens outside MarinaFrame.

## Container and files

`<stem>` means `<safe-vessel-name>_<rNNNN>_DRAFT`. The name is a file-name label,
not the vessel UUID. `<source-name>` is the original structure file name, including
its extension. Paths in the manifest and asset map are relative to the ZIP root,
with `/` separators. Generated JSON and CSV use UTF-8; copied structure files
keep their source encoding.

The writer creates a private sibling staging directory, checks the staged file
hashes and ZIP contents, then publishes the directory in one filesystem
operation. An existing directory is exchanged atomically on macOS and Linux;
its existing files, including a viewer capture, are copied into the stage.
Task and build evidence cannot be used as the destination. A failed write leaves
the destination unchanged.

| File | Manifest role | Contents and presence |
| --- | --- | --- |
| `<stem>_manifest.json` | Not in its own `files` list | Always. Identity, units/axes, review context and the file inventory. |
| `assets.json` | `asset_map` | Always. Asset UUID to display-file/node links and labels. |
| `spaces.json` | `spaces` | Always. One space per tank with a non-empty built mesh; otherwise an empty list. |
| `frames.json` | `frames` | Always. Stored frame spacing, zero and rows; missing data stays unknown. |
| `glb/hull.glb` | `display_glb` | If the selected build records `exports.glb`. |
| `glb/whole-vessel-draft.glb` | `display_glb` | If the selected build records `exports.whole_vessel_glb`. |
| `glb/tanks.glb` | `display_glb` | If the selected build records `exports.tanks_glb`. |
| `glb/<source-name>` ending `_structure.glb` | `display_glb` | Each existing structure display GLB supplied through `structure_dir`. |
| `<stem>_offsets.csv` | `offsets_table` | Always. Station half-breadths and their source labels. |
| `<stem>_hydrostatics.json` | `hydrostatics` | Always. Computed summary, or `null` with a reason. |
| `<stem>_hydrostatics.csv` | `hydrostatics_table` | Always. The same summary as quantity/value rows. |
| `<stem>_report.pdf` | `review_report` | Always. Draft summary, limits, open guesses and available station overlays. |
| `<stem>_model.step` | `step_model` | If built. STEP model; a matching header gets the draft stamp. |
| `<stem>_model.iges` | `iges_model` | If built. Draft IGES trimmed surfaces, copied without changes. |
| `<stem>_model.3dm` | `rhino_model` | If built. Draft Rhino model, copied without changes. |
| `<stem>_model.stl` | `stl_mesh` | If built. STL mesh; binary headers get the draft stamp. ASCII STL stays unchanged. |
| `<stem>_capacity_plan.csv` | `capacity_plan` | When a non-empty tank list is supplied. Includes unbuilt tanks. |
| `<stem>_sounding_<safe-tank-id>.csv` | `sounding_table` | For each supplied tank with a mesh. |
| `<stem>_<source-name>` ending `_steel_members.csv` | `steel_members` | Matching files in the supplied structure folder, copied without changes. |
| `<stem>_<source-name>` ending `_steel_totals.csv` | `steel_totals` | Matching files in the supplied structure folder, copied without changes. |
| `<stem>_<source-name>` ending `.3docx` | `ocx_structure` or `ocx_structure_tanks` | Structure OCX. Tanks are added when the one source OCX file can hold them; the combined file has the latter role. |
| `<stem>_tanks.3docx` | `ocx_tanks` | Built tank compartments when they were not added to a structure OCX file. |
| `<stem>_booklet_check.csv` | `booklet_check` | Only when a booklet is supplied. Every comparison cell, including unavailable values. |

`<stem>_package.zip` is the outer container; it is not inside itself. The ZIP contains
the manifest plus exactly the paths in `manifest.files`. The manifest does not hash
itself. The Python return value and CLI JSON add `package` (the ZIP file entry) and
`manifest_file` after writing the archive; those two keys are absent from the stored
manifest. ZIP entry dates are fixed at 2026-01-01. Identical effective inputs, options
and tool versions give identical bytes, including on repeated exports to other folders.

## Manifest schema

`schema_version` is the string `"1.0"`. The current JSON shapes are documented here;
the package does not include separate JSON Schema files.

| Field | Type and meaning |
| --- | --- |
| `vessel_id`, `vessel` | UUID string; display-name string. |
| `revision`, `parent_revision` | Revision string; preceding revision string or `null` for r0000. |
| `assets` | Array of `{ asset_id: UUID string, kind: string, part_id: string }`. Kinds are `hull`, `tank`, `steel_group`. |
| `particulars` | Known intake fields and spec constraints. May contain `vessel_name`, `loa_m`, `lpp_m`, `length_m`, `beam_m`, `depth_m`, `draft_m`, `scale`, `imo`. Lengths use metres; `scale` is text. Unknown fields are omitted. No model metrics are substituted. |
| `imo` | Optional seven-digit string, also in `particulars.imo`; see identity rules below. |
| `tool`, `run_id`, `build`, `result_sha256` | Tool/version string, source run ID, build-folder name and SHA-256 of its `result.json`. The source result file is not packed. |
| `review_state`, `draft_status`, `open_guesses` | Copied review state, draft status or `null`, and integer open-guess count. These do not change the engineering flag. |
| `engineering_approved` | Always `false`. |
| `stamp`, `footer`, `datum` | Draft notice and human-readable coordinate notes. Use `units_axes` for format-specific units. |
| `units_axes` | The format-specific coordinate block described below. |
| `not_built` | Missing native export roles: `step_model`, `iges_model`, `rhino_model`, `stl_mesh`. Missing GLBs are represented by absent files and null asset links, not by this list. |
| `files` | Array of file entries, defined below. |
| `booklet_check` | Optional integer-count object: `within`, `outside`, `not_comparable`, `comparable`, `total`. |

A file entry is `{ file: relative path, role: string, bytes: integer, sha256: hex string }`.
The digest covers the exact packed file bytes. Additional fields depend on the role:

- STEP/STL: `source_sha256` and boolean `header_stamped`. A false value means the
  original header could not be stamped; the file was still copied.
- IGES/Rhino: `source_sha256`, `units: "mm"`.
- GLB: `source_sha256`, `source_units` (`mm` or `m`), `units: "m"`.
- Capacity plan: integer `tanks`; sounding table: `tank` ID and `interval_m`.
- Copied structure files: `source_file`; combined or tanks-only OCX also has an
  integer `compartments` count.

## Identity and revisions

A new task receives one UUIDv4 in `domain/state.json` as `vessel_uuid`. Old tasks
without that field receive `domain/vessel_identity.json` on first export. That
sidecar contains `{ "vessel_id": "<UUID>" }`; it leaves the pinned checkpoint and
build evidence unchanged. Keep the state or sidecar when moving or continuing the
task. Exporting again, reopening the task or changing its display name keeps the UUID.
Independent new tasks receive new UUIDs, even if their vessel names are the same;
there is no global registry that merges them by physical vessel.

Each asset ID is UUIDv5 with the vessel UUID as namespace and the exact string
`<kind>:<part_id>` as name. Hull part IDs come from the build's `hull_envelope`
parts, with `hull` as the legacy fallback. Tank part IDs are the tank model IDs,
including unbuilt tanks. Steel part IDs are display node names such as
`structure_shell` and `structure_primary`; table labels supply groups when no
structure GLB exists. Geometry, labels, input order and revision number do not enter
the UUID calculation. The same vessel UUID, kind and part ID keep the same asset
ID across revisions. Changing a part ID or kind creates a different asset identity.

`revision` is the normalized domain counter (`r1` becomes `r0001`). Its parent is
the immediately preceding counter, including revisions with no successful build.
Use `(vessel_id, revision)` as the revision key. Only the selected revision is
packed; a parent link does not mean that its files are in this ZIP.

An IMO is used only from typed intake `particulars.imo`. Empty or absent values
produce no `imo` key. A string may have an `IMO` prefix and surrounding whitespace;
the stored value is seven ASCII digits. The first six digits use weights
`7, 6, 5, 4, 3, 2`; their sum modulo ten must equal the last digit. Invalid input
stops export. A checksum match does not establish a registry assignment or vessel
identity. No number is inferred from drawings, names, slugs or build fields.
The intake UI and Rust `Particulars` contract do not collect IMO yet.

## Units and axes

The manifest distinguishes model coordinates from GLB coordinates:

| Block/format | Units | Axes |
| --- | --- | --- |
| `units_axes.model`; offsets, spaces, frames, tank tables | m | Z up from the baseline. With a whole-vessel display model, X forward and Y port. Otherwise X is `along_length_as_drawn` and Y is `transverse_sign_not_recorded`; direction is not invented. |
| `units_axes.glb`; all packaged GLBs | m | glTF Y-up: model `(x, y, z)` becomes GLB `(x, z, -y)`. Inverse: `(x, -z, y)`. |
| `units_axes.cad`; STEP, IGES, Rhino 3dm | mm | Model axes, Z up. `formats` lists `step`, `iges`, `3dm`. |
| `units_axes.stl`; STL | Source-declared unit, normally mm | Model axes, Z up. STL has no intrinsic length unit; read this block. |
| OCX `.3docx` | Per XML unit reference | Model axes. MarinaFrame OCX 3.0.1 uses metre coordinates, kg mass, kg/m3 density, rad angles and N/mm2 stresses. Do not apply the CAD millimetre block to OCX. Copied source OCX retains its own declarations. |

The source display GLBs normally use millimetres. The exporter adds a 0.001 scene
scale to copies in the ZIP, including existing node translations. Mesh buffers,
materials and part node names remain available. A source container named `world`
can be renamed to avoid importer origin-name conflicts; asset mesh nodes keep
their names. A build GLB declared in metres is not scaled again. Do not apply the
app viewer's millimetre-to-metre scaling to these package GLBs. Source files are
not changed, and missing display geometry is not generated.

## Spatial JSON schemas

All three files have `schema_version: "1.0"` and `engineering_approved: false`.

`assets.json` has `assets`, an object keyed by asset UUID. Each value has:
`part_id`, `kind`, `label`, `source_label`, `source_labels` (a field-to-label object),
`glb_file` and `node_name`. Both link fields are `null` if no matching display node
exists. Links use exact part/node IDs, not labels or array positions. The first
matching node wins in this order: build hull GLB, whole-vessel GLB, tank GLB, then
structure GLBs sorted by file name. A whole-vessel GLB can also contain nodes
outside the three indexed asset kinds.

Tank `source_label` describes geometry. Hull labels combine section sources.
Steel group labels combine the member thickness sources from GLB metadata. Mixed
sources use `mixed`; missing evidence uses `unknown`. A printed thickness label
does not establish the source of every geometric property.

`spaces.json` has `units: "m"`, `axes: "model"` and a `spaces` array. Each row is
`{ asset_id, name, content_class, bounds_m: { min: [x,y,z], max: [x,y,z] }, source }`.
Bounds are finite mesh extrema in model metres. `source` retains the tank's field
labels, with geometry `unknown` when absent. Content classes are `fuel_oil`,
`diesel_oil`, `lube_oil`, `oily_residue`, `water_ballast`, `fresh_water`, `feed_water`,
`sewage`, `cargo`, `void`, `other`. Unbuilt tanks have asset IDs but no space rows.
Bounds are not a replacement for the tank solid or its exact boundary.

`frames.json` has `units: "m"`, `spacing_m`, `zero_x_m`, `source`, `source_file`,
`frames`, and optional `source_sha256`. It reads the task's existing `frames.json`.
Spacing must be positive when supplied; zero may be any finite model X coordinate.
Each retained frame row is an object with finite `x_m`; row labels or numbers are
preserved. `source` is copied as supplied (a label or field-source object), not
promoted to a stronger label. Without a table, spacing and zero are `null`,
`source` is `unknown`, `source_file` is `null` and `frames` is empty. The UI's
size-based spacing guess is not used to fill these fields.

## Other file schemas

CSV files have a header row after draft/metadata comment records whose first field
starts with `#`. Use a CSV parser: quoted cells can contain commas and newlines.
Potential spreadsheet formulas in text cells get a leading apostrophe. Empty
numeric cells mean unavailable data, not zero.

- **Offsets:** `station, x_m, source_label, keel_z_m, top_z_m`, then
  `hb_at_z_<height>_m` for each waterline. All coordinates and half-breadths use
  metres, written to three decimals. An empty breadth means the station does not
  reach that waterline.
- **Hydrostatics JSON:** `{ stamp, vessel, revision, datum, engineering_approved,
  hydrostatics, not_computed_reason }`. `hydrostatics` is `null` on computation
  failure. Otherwise it has `method`, `draft_basis`, `coefficient_basis`, `checks`
  (object), `warnings` (string array), and the following quantities: metre fields
  `draft_m, lcb_m, vcb_m, kb_m, lcf_m, bmt_m, bml_m, waterline_length_m,
  waterline_beam_m, keel_z_m, largest_breadth_below_waterline_m, largest_section_x_m`;
  `density_t_per_m3`; `volume_m3`; `displacement_t`; square-metre fields
  `waterplane_area_m2, largest_section_area_m2, wetted_surface_m2`; dimensionless
  `cb, cp, cm, cwp`. Unsupported quantities can be `null`. `draft_m` is the
  waterline's model Z coordinate. LCB/LCF use model X; VCB uses model Z; KB is
  height above the built keel, and BM values are metacentric radii.
- **Hydrostatics CSV:** `quantity, value`, one row per summary key. Object/array
  values are JSON in a CSV cell. Computation failure gives `not_computed_reason`.
- **Capacity plan:** `id, name, content, frames, built, volume_100_m3, volume_98_m3,
  density_t_m3, weight_98_t, lcg_m, tcg_m, vcg_m, max_free_surface_moment_tm,
  printed_volume_m3`, then `source_name, source_content, source_frames,
  source_volume, source_density, source_centroid, notes`. Units follow suffixes:
  metres, m3, t/m3, tonnes, tonne-metres. Weight is at 98% fill. `frames` is label
  text, not a substitute for the spatial frame table.
- **Sounding tables:** `sounding_m, ullage_m, volume_m3, fill_pct, lcg_m, tcg_m,
  vcg_m, free_surface_m2, i_transverse_m4, i_longitudinal_m4`. Units are metres,
  m3, percent, m2 and m4. Levels are even-keel, vertical from the tank's lowest
  point; the sounding origin is a labelled guess, not a surveyed pipe position.
- **Steel members:** `member_id, label, group, area_m2, thickness_mm,
  thickness_source, material, material_source, volume_m3, weight_t, table_row,
  placement_sources`. Units are m2, mm, m3 and tonnes. The default steel density
  is the labelled guess 7.85 t/m3.
- **Steel totals:** `group_by, key, members, area_m2, volume_m3, weight_t,
  weight_share`. `members` is a count; `weight_share` is dimensionless. Groups
  are by label, group, thickness source and total. Both steel CSV types are
  copied, so source headers remain authoritative.
- **Booklet comparison:** `row, draft_m, waterline_z_m, quantity, unit, printed,
  computed, error, relative_error_percent, tolerance, label, reason, method`.
  `row` is one-based. Each quantity states its unit. Labels are `within tolerance`,
  `outside tolerance`, `not comparable`. Datums, density and trim are in metadata.
  See [BOOKLET_CHECK.md](BOOKLET_CHECK.md) for comparison limits.
- **PDF:** Human review report, not a JSON or geometry interchange schema. It
  includes particulars, hydrostatics, source labels, open guesses, accuracy limits
  and available overlays; tank/booklet sections depend on supplied inputs.
- **STEP:** ISO 10303-21 model from the build. Header-only draft stamping does
  not regenerate the model. **IGES:** trimmed-surface exchange; STEP remains the
  solid format. **Rhino 3dm:** Rhino 8 format, named layers, exact untrimmed NURBS/trimmed planes
  and labelled mesh fallbacks for curved trims or unsupported planar holes.
  **STL:** binary or ASCII triangles, without intrinsic units or asset IDs.
  See [CAD_EXPORT_CHECK.md](CAD_EXPORT_CHECK.md) for representation limits.
- **GLB:** glTF 2.0 binary scene with embedded buffers, materials and part mesh
  nodes. Part extras can carry labels and member source data. `assets.json` is
  the package link map; binary geometry alone is not the asset registry.
- **OCX:** MarinaFrame-generated files use OCX 3.0.1 XML with UnitsML definitions,
  plates/stiffeners and optional tank compartments. A single writable structure
  OCX receives the built tanks; otherwise a tanks-only file is added. Copied
  source files keep their XML schema and unit declarations.

## Not included yet

The package does not include raw drawings/source pages, a document index or
sheet/region-to-asset links; the PDF can contain rendered station overlays.
It does not include the source `result.json`, task state/specs, the vessel UUID
sidecar, `tanks.npz`, raw booklet input or all parent revisions. Hashes identify
bytes; they are not signatures or a complete evidence chain.

There is no dated review/sign-off snapshot, assistant facts file, maintenance
record, hosted vessel registry, live co-viewing or chat. Assets currently index
hull, supplied tanks and steel groups, not every other node in an assembly GLB.
The exporter does not generate missing display GLBs or update a stale run-level
GLB after a part edit. Do not treat display links as a new CAD validation. A
stored frame table is optional; the exporter does not recover one from drawings
or infer its zero. The intake IMO text field is still pending.

## Existing test coverage

`tests/test_exports.py` tests package contents/hashes, identity persistence across
two revisions and display-name changes, valid/invalid IMO input, and absent IMO
when it was not typed (even if an unrelated build field looks like an IMO).
`tests/test_package_spatial.py` tests file/node links, metre scaling and existing
translations, space bounds, frame sources and missing data, stable IDs across a
geometry revision, and repeatable archives. `tests/test_booklet_exports.py` tests
the optional comparison CSV, report and manifest summary.
