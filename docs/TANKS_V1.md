# Tanks v1: tank and compartment model, capacity plan and sounding tables

Date: 2026-11-09. Branch `feature/tanks`. Status: built; results in section 5 (metrics fixed in
`0d46612` before the build).
Why this feature: `docs/research/2026-11-09-beyond-hull-features.md` (item 1: buyers need a
compartment model with a capacity plan, tank tables and sounding tables; inputs are the GA, the
tank plan and the hull that MarinaFrame already reads). Plan context:
`docs/plans/2026-11-09-whole-vessel-scope.md` section 4.3.2 (G1 to G5) and section 5.

Every output is a draft: `engineering_approved` is false. No status uses the words "approved" or
"verified".

## 1. Deliverables

1. Product module `src/vessel_reconstruction/tanks.py` (no drawing-specific code):
   - tank solid from a plan outline and vertical limits, clipped to the hull (hull plane sections);
     a tank is a closed triangle mesh, so a tank from drawings and an exact solid from OCX go
     through the same code;
   - volume, centroid (LCG, TCG, VCG) and free-surface inertia (transverse and longitudinal
     moments of the free surface about its own centroid) against the fill level;
   - sounding and ullage table at a fixed interval;
   - capacity plan table: tank, type (content), frame range, volume at 100 % and 98 %, density,
     weight at 98 %, LCG, TCG, VCG at 100 %;
   - a source label on every value: `traced` (measured from drawing linework), `read` (printed
     text), `guessed` (a default or a convention).
2. Gunnerus fixes (development case, plan section 4.3.2 and `docs/WHOLE_VESSEL_GUNNERUS.md`
   section 7 item 0): region leaks (No 11, No 4) with the partitions drawn on other layers; tank
   heights from the drawn profile (No 12, hold); then G1 to G4 again.
3. Exports: capacity plan CSV and one sounding-table CSV per tank, also written by the existing
   export path (`src/vessel_reconstruction/exports/`). Tanks keep their parts in the whole-vessel
   assembly (STEP and GLB) as today.
4. Results section (section 5 of this file).

Definitions (fixed): the ship frame is x forward from the aft perpendicular (frame 0), y to port,
z up from the baseline (metres). Sounding is measured vertically from the lowest point of the tank
at even keel; the sounding pipe position is not drawn, so the sounding origin is `guessed`.
Ullage = tank height (highest minus lowest point) minus sounding. 98 % volume = 0.98 x 100 %
volume. Free-surface inertia i_T = integral of (y - y_c)^2 over the free surface; i_L likewise in
x. The free-surface moment of a tank is density x i_T (t m).

## 2. Data

| Ship | Files (git-ignored `work/sources/`) | Truth for this lane |
|---|---|---|
| Gunnerus (development) | `gunnerus/extended/CJOB/Tank Arrangement Rev0.dxf` (tank table: number, name, frame range, net volume, mass, group densities and group totals; profile; plans below the tank top and below the 1-deck); `Construction Plan Longitudinal Section Rev0.dxf`; built hull of the step 1 assembly (`work/whole-vessel/final`) | Printed table values (net volume, frame range, group totals). The truth STEP (`work/archived-runs/w1-gunnerus/gunnerus/truth/truth_mesh.npz`) has hull and tier 1 only: containment (G4) only. |
| D-VLCC 1-hold (OCX 3.0) | `ocx_models_platform/models/D-VLCC_1-HOLD-OCX-simple_v3.3docx`: 5 compartments (CO_C3, CO_P3, CO_S3, WB3P, WB3S) | Exact solids (NURBS faces with boundary curves). Method truth for T1 and T3. |
| NAPA OCX M9 | `ocx_models_ocxtools/tests/data/NAPA-OCX_M9.3docx`: 2 compartments (BALLASTP, BALLASTS) | Same as above. |

No drawings, crops or derived per-ship data enter the repository. Outputs go to the git-ignored
`work/tanks/`. No second ship with a tank plan is on disk; none is invented.

## 3. Metrics (fixed 2026-11-09, before the build; development targets, not gates)

G1 to G4 are those of plan section 4.3.2, unchanged (same code:
`benchmarks/gunnerus/whole_vessel_internals_metrics.py`). Tanks that are not built count as
misses where stated.

| ID | Metric | Target |
|---|---|---|
| G1 | Gunnerus tank x extents (built aft and forward ends) against the table frame range; abs error per end, median over built tanks; also the count of tanks built | median <= 0.5 m |
| G2 | Gunnerus tank volume (built solid inside the built hull) against the table net volume; median abs relative error over built tanks with a printed volume; also the count within 10 % and within 3 % (research pilot test: 80 % of tanks within 3 %, report only) | median <= 15 % |
| G3 | Main transverse bulkheads (tank arrangement profile) against the nearest bulkhead of the longitudinal-section construction plan | <= 0.25 m each |
| G4 | Share of the built internal volume (tank tops, bulkheads, tanks) outside the truth solid, 0.10 m point grid | <= 5 % |
| T1 | Sounding table check on the 7 OCX compartments: our table (the exact solid tessellated, then the `tanks.py` level integration) at a fixed 0.10 m sounding interval against the direct volume at each level (OpenCASCADE Boolean of the exact solid with the half-space below the level, `GProp` volume). Relative error at every level where the direct volume is at least 1 % of the full volume; max over all levels and compartments. Also reported: max abs error as a share of the full volume over all levels | max rel error <= 0.5 % |
| T2 | Capacity plan totals per tank group against the printed Gunnerus group totals (water ballast 62.30, fresh water 11.14, fuel oil 59.76, misc 13.42 m3; masses likewise). A tank that is not built counts as 0 m3. Abs relative error per group; also the grand total of the four liquid groups | each liquid group <= 10 %; grand total <= 10 % |
| T3 | Centroid at 100 % fill on the 7 OCX compartments: LCG, TCG, VCG from `tanks.py` against the exact solid (`GProp` centre of mass of the OCX solid). Also reported, not a target: the gap to the centre of gravity and volume printed in the OCX file (`CompartmentProperties`) | each coordinate <= 0.02 m; volume <= 0.1 % |

Unit tests (exact answers): box and wedge solids for volume, centroid and free-surface inertia
against fill level; sounding table rows; capacity plan rows; prism tank from an outline clipped to
a box hull.

Rules: do not loosen a target after seeing a result. A missed target is reported with its cause.

### 3.1 Holdout (not run)

- Inputs: HAER VA-132 Arthur M. Huddell (Liberty ship, public domain) in
  `work/sources/tanks-public/arthur_m_huddell_haer_va132/`: capacity plans (deep tank top and inner
  bottom, inboard, upper and second deck; sheets 7 to 9), hold plan, inboard profile, lines
  (sheet 19), midship sections. All are raster scans (TIFF), not vector DXF.
- Truth: US Maritime Commission EC2-S-C1 capacity-plan tables in
  `work/sources/tanks-public/liberty_truth/`: per-tank volumes (cu ft, gallons, tons). No LCG, VCG
  or frame limits are printed, so only volume metrics (G2 and T2 style) apply.
- Rules: nobody on this lane opens, reads or uses `liberty_truth/`; an independent agent transcribes
  it after the protocol is fixed. The Huddell sheets were only listed by file name here, to check
  that the design is not Gunnerus-specific; nothing was tuned on them.
- Design note: `tanks.py` (solids, tables, capacity plan, exports) takes any closed mesh or plan
  outline and is not ship-specific. The Gunnerus reader
  (`benchmarks/gunnerus/whole_vessel_internals.py`) is: it reads DXF layers, cross marks and text
  positions. A Huddell run needs a raster reader for the plan outlines and the capacity tables
  (the vision-table reader is a candidate) and imperial units.
- Protocol (tank set, unit conversion, per-tank and per-group volume targets, what counts as not
  built): to be fixed and committed in this file before the run.

## 4. Resume point

Done: metrics (section 3, commit `0d46612`), `tanks.py` with unit tests, OCX check (T1, T3),
Gunnerus fixes and re-measure (G1 to G4, T2), exports, results (section 5).

Next, in order:
1. Holdout protocol (section 3.1) fixed and committed, then a raster reader for the Huddell
   capacity plans; run once.
2. Gunnerus: No 11 service-tank heights (engine-room arrangement or the deck plan above), the hold
   volume gap (section 5), plate thickness from construction-plan labels.
3. Trim and heel in the sounding table (today even keel) and sounding-pipe positions when drawn.

Commands (outputs in git-ignored `work/tanks/`):

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.gunnerus.whole_vessel_internals \
        --sources ../../../work/sources/gunnerus --assembly ../../../work/whole-vessel/final \
        --out work/tanks/gunnerus-NNN \
        --truth-mesh ../../../work/archived-runs/w1-gunnerus/gunnerus/truth/truth_mesh.npz
    PYTHONPATH=src:. .venv/bin/python -m benchmarks.ocx.compartment_check --out work/tanks/ocx-check.json \
        <D-VLCC_1-HOLD-OCX-simple_v3.3docx> <NAPA-OCX_M9.3docx>
    python -m vessel_reconstruction.exports --task DIR --revision rN --out DIR --tanks tanks.npz

Checks before each commit: the tests touched and
`PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/test_whole_vessel_step1.py`.

## 5. Results (2026-11-09)

### 5.1 What is built

- `src/vessel_reconstruction/tanks.py`: a tank is a closed mesh. Fill properties use the same
  clipped-mesh divergence-theorem integrals as the hull hydrostatics (exact for the mesh). Also:
  sounding/ullage table, capacity-plan rows with source labels, group totals, tank solids from a
  plan outline and vertical limits clipped to the hull, and an `.npz` tank model file. Unit tests
  (`tests/test_tanks.py`): box, wedge, L-section prism, stacked slabs, hull clip and capacity rows
  against closed-form answers.
- Exports: `exports/tank_tables.py` writes `<stem>_capacity_plan.csv` and
  `<stem>_sounding_<tank>.csv` (draft stamp, formula-safe text cells). `export_draft(..., tanks=)`
  and the CLI `--tanks FILE.npz` add them to the manifest and the zip, and add a capacity-plan
  section to the PDF report. Tanks stay parts of the whole-vessel assembly (one STEP and one GLB
  node per tank).
- `benchmarks/ocx/compartment_check.py`: OCX compartments built as exact OpenCASCADE solids.
  Degree-1 boundaries are split into one edge per segment so that sewing matches the corners.
  The sewn solids match the volume and centre of gravity printed in the files (largest gap 0.0001
  relative, 0.8 mm).
- Gunnerus reader (`benchmarks/gunnerus/whole_vessel_internals.py`), fixes for section 7 item 0
  of `docs/WHOLE_VESSEL_GUNNERUS.md`:
  - Phantom cross marks (layer S0PH1) bound a tank. A rectangular cross is the tank plan (No 4,
    No 11sb/11p, black and grey water new). A cross with a corner on the hull curve cuts the region
    at the label (No 3sb no longer holds No 4).
  - Labels are placed at their text centre, and a full name wins over a shortened one ("Black
    water" is No 7sb).
  - The centre-line tank top has a 2.5 m gap (HIPAP trunk, x 26.5 to 29.0 m) between two 1.8 m
    runs. It is bridged and labelled `guessed` (No 2sb/2p).
  - Hold and No 12 floors come from the profile, measured below its 1-deck line. This applies only
    to tanks across the centre line.
  - The table gives content groups and densities (header "FUEL OIL TANKS ρ = 0.83", or printed
    mass / volume) and the group totals (T2).

### 5.2 Metrics

Before: `work/whole-vessel/internals-002` (`docs/WHOLE_VESSEL_GUNNERUS.md` section 6). After:
`work/tanks/gunnerus-002` (5 min, 87 MB) and `work/tanks/ocx-check.json` (43 s, 7 compartments).

| ID | Before | After | Target | Result |
|---|---|---|---|---|
| Tanks built | 22 of 24 | **24 of 24** | all | met |
| G1 tank ends, median abs | 0.04 m (22 tanks) | **0.019 m** (24 tanks); misses: No 6sb/6p forward end -5.0 m | <= 0.5 m | met |
| G2 volume, median abs rel | 8.2 % (20 tanks; 12 within 10 %) | **10.2 %** (21 tanks; 9 within 10 %, 0 within 3 %) | <= 15 % | met |
| G3 bulkheads | 7 of 7 at 0.00 m | 7 of 7 at 0.00 m (section bulkhead at x 1.0 m not in the profile) | <= 0.25 m | met |
| G4 containment | 13.1 % | **2.4 %** (199,371 points) | <= 5 % | **met** (was missed) |
| T1 sounding table vs direct Boolean, max rel | first run (fixed 2 mm tessellation, M9 only): 1.0 % | **0.22 %** (WB3P at 0.10 m sounding; 1,475 levels; max abs 0.010 % of full) | <= 0.5 % | met |
| T2 group totals | not measured | water ballast -6.5 %, fresh water -7.8 %, fuel oil +5.4 %, misc **+57.7 %**; grand total of the four groups +4.2 % | each <= 10 %, total <= 10 % | **missed** (misc) |
| T3 centroid at 100 % | first run (2 mm): 1.6 mm, volume -0.16 % | **0.72 mm** max, volume -0.0097 % max | <= 0.02 m, <= 0.1 % | met |

Notes on the results:

- G2 per tank. All 24 tanks are built now; the old leaks are gone (No 11p was +757 %, No 12
  +102 %, No 2 -54 %). The median rose from 8.2 % to 10.2 %, for three reasons. Tanks from a
  rectangular cross use the moulded lines (line centres), and the old region reader cut 20 to
  40 mm of line ink on each side, so No 7 to No 10 are now +5 to +11 % against a net table volume
  that excludes structure. The new tanks are included. No 11sb/11p are +36 %: their heights are
  `guessed`, tank top to deck. Hold -24.6 % (32.0 against 42.45 m3): the built hull deck at the
  stern is 4.11 m, not 4.2 m, a stair trunk ("Up") is cut out, and the plan's own label prints
  37.8 m3, so the two printed sources differ by 11 %.
- G1 No 6sb/6p. The table prints "20...28". Frame 28 comes after the lettered midbody frames A to
  J, so it lies at x 19.0 m. The drawn tank ends at frame 27/A (14.0 m), and the new fuel oil tanks
  fill A to I. The range is pre-lengthening numbering. The metric is unchanged and still counts
  this as -5.0 m.
- G4. The parts still above 5 % are bulkhead x 4.0 m (22 %, aft hull shape) and No 12 (7 %).
- T1 and T3. The first run used a fixed 2 mm chord deviation. The volume came out 0.16 % low and
  T1 was 1.0 % at low fill. Finer meshes (0.5 mm: 0.19 %; 0.1 mm: 0.04 %) showed that the error is
  the tessellation, not the level integration. The check now tessellates at 1e-5 of the bounding
  diagonal. The targets did not change.
- T2 misc missed. The printed "Total misc" (13.42 m3) leaves out black water new and grey water
  new, which the table lists without a volume. The metric counts every built tank of the group,
  and these two add 6.55 m3. Without them, misc is +8.9 %. The metric stays as fixed, so T2 is
  reported as missed.
- G5: 36 parts built (18 traced, 18 with a guessed value), 12 plates with an ID and a guessed
  10 mm thickness.

### 5.3 What is missing

- Sounding tables are at even keel; there is no trim or heel table and no sounding-pipe position
  (the origin is the lowest point of the tank, labelled `guessed`).
- No 11 heights, plate thicknesses, and the hold gap (above).
- The plan reader is Gunnerus-specific (DXF layers, cross marks, text positions). A raster
  reader is needed for the holdout (section 3.1).
- Tests that start the macOS Seatbelt CAD worker (5 in the suite, including
  `test_whole_vessel_step1.py::test_revise_rebuilds_only_the_marked_part`) fail in this agent
  session: `sandbox-exec` exits with code 71 inside the session sandbox. They fail the same way on
  the base commit. All other tests pass (1,137).
