# Concept preview: survey launch (lane R)

Goal: a complete, made-up example vessel for the web demo that shows MarinaFrame "at full
potential": a 3D model with internals and synthetic 2D drawings made from it, side by side, with a
source record from every part, tank and section to its exact region on a sheet.

Honesty (hard rule): every sheet has the banner and title block "CONCEPT PREVIEW - EXAMPLE
DRAWINGS GENERATED FOR THIS DEMO, NOT A REAL VESSEL". The run name, `state.json`
(`termination_reason`, `concept_preview`), `concept_preview.json`, the capacity-plan stamp, every
part's reason and the exports carry "Concept preview - example vessel and drawings made for this
demo. Shows how MarinaFrame presents a finished model; not a reading of real drawings."
The run records the generator (`benchmarks/concept_launch`), `read_by_marinaframe: false`, and
`engineering_approved: false`.

## Code

| File | What |
|---|---|
| `benchmarks/concept_launch/model.py` | Analytic hull offsets, CadQuery loft, 37 parts (decks, deckhouse, wheelhouse, bulwarks, 4 bulkheads, 7 web frames, girder, machinery, appendages, A-frame, mast, 9 tanks), hydrostatics |
| `benchmarks/concept_launch/structure.py` | 139 steel members (structure member form) |
| `benchmarks/concept_launch/sheets.py` | GA, lines plan, tank arrangement, construction (PIL, 3960 x 2800 px) drawn from the meshes; exact region per item |
| `benchmarks/concept_launch/run_folder.py` | App run folder: state, domain catalog, hull build, intake sheets, whole_vessel parts + GLB, tank tables, exports |
| `tests/test_concept_launch.py` | Quick: offsets, cuts, region clipping, labels. Cad: volumes vs CAD, regions on sheets, records |

Run: `PYTHONPATH=src:. .venv/bin/python -m benchmarks.concept_launch --out work/web-demo-runs/concept-survey-launch`
(about 50 s). Output (git-ignored): `runs/concept-survey-launch/` (runs folder for
`web_demo_export --runs <out>/runs concept-survey-launch`), `drawings/`, `model/`,
`manifest-entry.json`, `regions.json`.

## Results (2026-11-11)

- Hull loft 454.38 m3 against 454.10 m3 from the offsets (0.06 %). Displacement at the 1.6 m DWL
  196.1 t, KM 3.73 m, Cb 0.763.
- Tank capacities from the meshes are within 0.2 % of the CAD solids (gate 0.5 %, set before the
  run; the first run failed it at 0.5 % for DO1 with a 2 mm / 0.2 rad mesh, so the tank meshes are
  now 0.5 mm / 0.05 rad).
- Lane Q's exporter (`lane/web-demo`, built in a scratch copy) reads the run: 11 sections chosen
  with `read` records, 33 parts (wheelhouse and tank_fw1 `guessed` with inputs), 6 tanks, 3
  previewable sheets, exports (STEP, STL, hydrostatics CSV, tank tables).
- `scripts/build_web_demo.py` (lane Q, scratch copy, selection holding only this run) builds an
  18.4 MB bundle with every gate passed. In the browser: Parts tab, whole vessel in 3D (see-through
  hull, coloured tanks), hover a tank -> lines to its profile, plan and table-row regions; hover
  the wheelhouse -> dashed "best guess" with "Also used: Deckhouse tier 1".
- Entry for `scripts/web_demo_runs.json`: `<out>/manifest-entry.json` (slug, name, licence
  `synthetic`, source = the concept label, `drawing_sha256` of the three sheets; the lines plan
  is also the run's `domain/input/source.png`, same bytes).
- In the run page itself the app shows only the manifest name "(concept preview)"; the full label
  is on the Home card, every sheet, part reasons and the capacity stamp. A banner on the run page
  is lane Q's UI.
- Found in the exporter (lane Q owns it): `sounding_tables` collects `tank_id` fields from the
  view, but capacity rows name the tank `id`, so `tables.json` is empty for any run with tanks.

## Round 2 (PM feedback: internals too thin)

- Arrangement: engine room fr 7 to 18 (main engine, gearbox, shaft line, propeller), 4 watertight
  bulkheads (fr 7, 18, 33, 40), inner bottom fr 18 to 40, 9 tanks at different heights: aft peak,
  fuel side tanks P/S (z 0.5 to 2.8), a free-standing diesel day tank (z 1.7 to 2.9), double-bottom
  FW1, WB1/WB2, FO1, and the fore peak.
- Steel (`structure.py`): 139 members (bulkheads, inner bottom, centre girder, 7 web frames, 16
  floors, 68 side frames, 34 deck beams, 8 longitudinals), written with
  `structure.display.write_structure_glb` and `structure.steel.write_steel_tables` to
  `structure/Survey_launch_CONCEPT_DRAFT_structure.glb` (1.0 MB, 4 member groups) plus steel CSVs:
  the app shows "Steel 139". Bulkheads, web frames, girder and inner bottom keep their part entry
  and source record; their mesh is only in the steel GLB (no double drawing).
- Sheet 4, construction profile and midship section at fr 24: one region per steel member;
  `structure/..._source_records.json` holds a `read` record per member. The app shows its fixed
  "unknown" for steel groups in 3D (`STEEL_RECORD` in provenance.js); the part records of the steel
  parts show in the Parts tab.
- Bundle (scratch build with only this run): 20.7 MB. Tests: 15 pass (both tiers).

## Not done

- Step 5 (read the generated lines plan with the real pipeline into a separate real run): not
  attempted (time).

## Resume point

All steps above are done and pushed on `lane/concept-launch`. To change the vessel, edit
`model.py`, run the generator and `pytest tests/test_concept_launch.py` (both tiers), then give
lane Q the new `manifest-entry.json` (drawing SHA-256 values change with any sheet change).
