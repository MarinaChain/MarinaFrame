# Tanks v1: tank and compartment model, capacity plan and sounding tables

Date: 2026-11-09. Branch `feature/tanks`. Status: metrics fixed before the build (this commit).
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

## 4. Resume point

1. Done when this section says so: metrics (this file, section 3).
2. Next: `src/vessel_reconstruction/tanks.py` with unit tests (`tests/test_tanks.py`).
3. Then the OCX check `benchmarks/ocx/compartment_check.py` (T1, T3) and the Gunnerus fixes in
   `benchmarks/gunnerus/whole_vessel_internals.py` (G1 to G4, T2).
4. Then exports (CSV, export path) and the results in section 5.

Checks before each commit: the tests touched and
`PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/test_whole_vessel_step1.py`.

## 5. Results

Not run yet.
