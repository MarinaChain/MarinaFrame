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
| `benchmarks/concept_launch/model.py` | Analytic hull offsets, CadQuery loft, 33 parts (decks, deckhouse, wheelhouse, bulwarks, 4 bulkheads, 10 web frames, girder, rudder, skeg, sonar gondola, A-frame, mast, 6 tanks), hydrostatics |
| `benchmarks/concept_launch/sheets.py` | GA, lines plan, tank arrangement (PIL, 3960 x 2800 px) drawn from the meshes; exact region per item |
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
- Found in the exporter (lane Q owns it): `sounding_tables` collects `tank_id` fields from the
  view, but capacity rows name the tank `id`, so `tables.json` is empty for any run with tanks.

## Not done

- Step 5 (read the generated lines plan with the real pipeline into a separate real run): not
  attempted (time).

## Resume point

All steps above are done and pushed on `lane/concept-launch`. To change the vessel, edit
`model.py`, run the generator and `pytest tests/test_concept_launch.py` (both tiers), then give
lane Q the new `manifest-entry.json` (drawing SHA-256 values change with any sheet change).
