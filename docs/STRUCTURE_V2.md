# Structure v2: a 3D cargo-hold block from the MiDShip drawings (whole-vessel step 2)

Plan: `docs/plans/2026-11-09-whole-vessel-scope.md` section 4; metrics S1 to S6 fixed in section
4.3.1 before the build (commit `7225a67`). Development figures only: there is no sealed 3D split.
Every output has `engineering_approved=false`. Resume point: section 9.5 (after round 3).

## 1. Method

Code: `src/vessel_reconstruction/structure/block3d.py` (layout) and `block_eval.py` (scorer).
Input per design: the three plain PDFs. Nothing else reaches the reader.

1. View 3 (longitudinal structure): the frozen W3 reader (`docs/STRUCTURE_V1.md`) gives plates,
   girders, stiffener webs and flanges in the section plane. Each member is swept over the block.
2. Tables of views 1, 2 and 3 (now with the spacing column): web-frame spacing; `Webframe`,
   `Floor` and `Deck_Transvere_Beam` scantlings; bulkhead stiffener count, spacing and scantling;
   `Trans. BLKHD`, `Upper Bracket` and `Lower Bracket` plate thickness.
3. Stations: 4 bulkheads (3 holds) centred in the block, 9 web spaces per hold at the printed
   spacing, 5 ordinary frame spaces per web space.
4. Transverse members, each an axis-aligned mid-plane box with its thickness: bulkhead plate
   (section extent from view 3), vertical and horizontal bulkhead stiffeners with flanges (web on
   the +x side), floor (base to inner bottom), web frame on the side shell span with its flange,
   deck beam with its flange, lower and upper brackets, and an ordinary frame on every plate that
   carries longitudinal stiffeners in view 3 (scantling of that plate's stiffener row; an open
   floor from the bottom to the inner bottom in a double bottom; outboard webs on an inner side
   shell).
5. IDs are stable: `L/<host>/<role>/<n>` for longitudinal members, `BH<k>/...` for bulkheads,
   `FR<nnn>/...` for members at frame `nnn` counted from the first bulkhead.

Labelled guesses (the drawings do not print them): block length 40 m, 3 holds, 9 web spaces per
hold, 5 frame spaces per web space, bracket legs 0.6 and 0.5 of the web depth, ordinary-frame
scantlings, stiffener side. The first four are the generator conventions of a BOM survey of the
488 SGLD designs outside the W3 sealed split (plan section 4.3.1).

## 2. Results (12 development designs, SGLD with 3D: 18,244 truth members)

Command: `python -m vessel_reconstruction.structure.block_eval --root work/sources/midship --out
work/step2/dev_final.json` (8 s). The diagnostic row replaces the two generator guesses (block
length, frame spaces per web space) with the values from the truth BOM (`--oracle-guesses`): it
shows what the guesses cost and is not a product result.

| Metric | Result | Diagnostic: true block length and frame count | Target |
|---|---|---|---|
| S1 detection P / R / F1 | 0.480 / 0.474 / **0.477** | 0.784 / 0.711 / 0.746 | F1 >= 0.80: **missed** |
| S1 longitudinal recall (precision) | **0.997** (1.000) | same | >= 0.95: met |
| S1 transverse recall (precision) | **0.346** (0.350) | 0.641 (0.724) | >= 0.60: **missed** |
| S2 typed macro F1 | 0.779 | 0.912 | report |
| S3 centre error median / p95 / max (mm) | **10.4** / 197 / 1,050 | 5.5 / 133 / 1,926 | median <= 50: met |
| S3 transverse x error median / p95 (mm) | 2.1 / 62 | 0.8 / 4.8 | report |
| S4 printed thickness exact, longitudinal (cut to mm) | 0.695 (0.997) | same | report |
| S4 printed thickness exact, transverse | 0.999 (3,324 members) | 0.998 | report |
| S4 guessed thickness exact (diagnostic) | 0.045 | 0.118 | report |
| S5 steel volume, median abs relative error | **4.1 %** (range -15.1 % to -0.2 %) | 4.3 % | <= 10 %: met |
| S6 members by placement source | 4,773 section and spacing traced; 13,256 use a guess | | report |

Typed F1 (main result): bottom shell, side shell, shell strake 1.000; stiffener web 0.969;
girder 0.911; deck 0.917; hopper plate 0.923; longitudinal bulkhead 0.933; bulkhead stiffener
0.904; transverse bulkhead, floor, web frame 0.750; deck beam 0.656; bracket 0.350; flange 0.399;
ordinary frame 0.249.

Findings:

- The longitudinal structure carries over from W3 unchanged: recall 0.997, precision 1.000.
- Where the guesses hold, the transverse members sit within millimetres (bulkheads, floors, web
  frames, deck beams: typed F1 1.000 in the diagnostic). The misses come from two values the
  drawings do not print: the block length (3 of 12 designs are 0.12 to 1.66 m longer than 40 m:
  their bulkheads and webs shift by half the excess and fail the 50 mm pad) and the frame spaces
  per web space (5 in 5 designs, 4 in 7: all ordinary frames of a design fail when it is wrong). An AI reader
  cannot fill these either: no sheet shows them.
- The printed web spacing is cut to 1 mm; over 26 web spaces the x error grows to about 13 mm.
- Thickness: printed transverse values are exact (0.999). Longitudinal values match the truth cut
  to whole millimetres (0.997); the exact rate is lower because the BOM holds fractions (as W3).
- Remaining structural gaps: deck girders interrupted by hatch openings (bulk carriers),
  container-ship brackets (four-sided, not the guessed triangle), the open-floor flange.
- Steel volume is within 4.1 % (median) although only half the members match: the volume is
  dominated by plates and printed scantlings.

## 3. OCX export

Not done in this step (no time left). `xmllint` is on the machine for the XSD check; the export
needs a Panel/Plate writer for the block members (plan section 4.3.3).

## 4. Data and rules

- MiDShip is GPL-3.0 data; it stays in `work/sources/midship` (git-ignored). Only metrics are here.
- The W3 sealed designs (SGLD 118, 215 with 3D) are refused by the scorer and were not opened.

## 5. Resume point

1. A sealed 3D split from the next MiDShip tranche, drawn before any new code.
2. Read brackets, the floor openings and hatch openings from view 2 and view 3 linework
   (now guessed or missing).
3. OCX export of the block (plan section 4.3.3).

## 6. Round 2 (2026-11-09): material, steel table, OCX export, Gunnerus plates

Written before the round 2 code (branch `feature/structure-3d`). Sections 1 to 5 above are round 1
(commit `8e50146`); their numbers stay as the round 1 record.

### 6.1 Deliverables

1. Every block member carries: a stable ID (section 1 item 5), thickness with a source (`printed`
   from a table row, else `guessed`: no member is left without a thickness), material with a
   source (`printed` from the table material column of the row that gives the thickness, else
   `guessed`: the most common printed material of the design), and the existing placement source
   labels.
2. Steel weight: per member `area x thickness x density`; density 7.85 t/m3 (carbon steel,
   `guessed`: the drawings print a grade, not a density). Totals per scoring label, per group
   (longitudinal / transverse) and per thickness source, and a grand total. Export as CSV with the
   draft stamp lines (same rules as `exports/tank_tables.py`: formula-safe text cells).
3. OCX 3.0.1 export of a block: one `Plate` per member (as built: plates sit directly under
   `Vessel`, which the schema allows; a block zone holds members in several planes, so it is not
   one OCX `Panel`, and a panel per member would only repeat the plate) (stiffener webs and flanges are written as plates: the block model holds
   them as flat parts; an OCX `Stiffener` with a section catalogue is later work). Each plate has
   its outer contour (closed polyline of the mid-plane rectangle), `PlateMaterial` with thickness
   and a material catalogue entry, net area and dry weight. The ID goes in `name`; source labels
   go in `Description`.
4. OCX reader: streams `Plate` elements (name, thickness, area from the contour or `NetArea`),
   memory-flat so that the 22 MB VLCC sample reads.
5. Schema check: `xmllint` against the local OCX 3.0.1 XSD (`work/sources/ocx_schema/ocx/ocx_301`).
   The XSD imports UnitsML and the W3C `xml.xsd` by URL; the check rewrites both imports to local
   files (the UnitsML file shipped with the schema; a minimal `xml.xsd` that declares `xml:lang`,
   `xml:space`, `xml:base` and `xml:id`). No network access.
6. Gunnerus (development, plan section 4.3.2 G5): plate records (ID, thickness, source) for the
   internals that the existing reader builds (tank tops and main transverse bulkheads). Extrusion
   of the Gunnerus midship section along the parallel body with clipping to the hull at the ends
   is in scope only if time is left after items 1 to 5; otherwise it is an open item.

### 6.2 Metrics (unchanged from plan section 4)

- S1 to S6 (plan section 4.3.1) on the 12 development designs, same scorer and targets. Round 2
  must not lower them (it adds attributes, not geometry). S5 is the steel-volume check of the
  steel table: the table total divided by the density equals the S5 built volume.
- OCX (plan section 4.3.3): schema validation passes on every export (the 12 development blocks);
  round trip of our own export: plate count, thickness per plate and area per plate equal
  (area within 1e-6 relative: the contour is written with 6 decimals in metres); the VLCC sample
  `D-VLCC_1-HOLD-OCX-simple_v3.3docx` is read by the same reader without error (plate count and
  thicknesses reported).
- G5 (plan section 4.3.2): Gunnerus internal parts by source label; plates with an ID and a
  thickness (printed or `guessed`). G1 to G4 belong to the tanks lane (`docs/TANKS_V1.md`) and are
  not re-measured here.

### 6.3 Data

As section 4: MiDShip development designs only (SGLD 118 and 215 refused); OCX samples in
`work/sources/ocx_models_*`; Gunnerus drawings in `work/sources/gunnerus` (licensed). Outputs to
git-ignored `work/step2/`. No drawing or derived data in the repository.

### 6.4 Checks

Unit tests: material and thickness labels, steel totals on a synthetic block, OCX export of a
synthetic block validates and round-trips (skipped when `xmllint` or the XSD is missing).

### 6.5 Resume point (round 2)

Order: 6.1 items 1, 2, 3 to 5, then the scored run (S1 to S6 and OCX on all 12 designs), then G5,
then results in section 7. Command for the scored run:

    PYTHONPATH=src:. .venv/bin/python -m vessel_reconstruction.structure.block_eval \
        --root ../../../work/sources/midship --out work/step2/round2.json \
        --ocx-dir work/step2/ocx --steel-dir work/step2/steel

## 7. Results, round 2 (2026-11-09)

Commands (outputs in git-ignored `work/step2/`; 20 s and 8 s):

    PYTHONPATH=src:. .venv/bin/python -m vessel_reconstruction.structure.block_eval \
        --root ../../../work/sources/midship --out work/step2/round2.json \
        --ocx-dir work/step2/ocx --steel-dir work/step2/steel \
        --ocx-schema ../../../work/sources/ocx_schema/ocx/ocx_301
    PYTHONPATH=src:. .venv/bin/python -m benchmarks.gunnerus.structure_plates \
        --sources ../../../work/sources/gunnerus --assembly ../../../work/whole-vessel/final \
        --out work/step2/gunnerus --ocx-schema ../../../work/sources/ocx_schema/ocx/ocx_301

### 7.1 What is built

- `structure/block3d.py`: material read from the material column of the plate and stiffener
  tables; every member has a thickness and a material, each labelled `printed` or `guessed`
  (`label_thickness_and_material`). On the 12 designs no member was left without a thickness
  before the guess (the guesses are the ordinary frames and their flanges, as in round 1).
- `structure/steel.py`: steel weight per member (area x thickness x 7.85 t/m3, density `guessed`)
  and totals by label, group, thickness source and in all; two CSV files per block with the draft
  stamp.
- `structure/ocx.py`: OCX 3.0.1 writer (plates with closed polyline contour, thickness, material
  catalogue with OCX grade names, net area, dry weight, centre of gravity, x reference planes at
  the block stations, UnitsML units), streaming plate reader, offline `xmllint` schema check, round
  trip. `block_eval` gains `--ocx-dir`, `--steel-dir`, `--ocx-schema`.
- `benchmarks/gunnerus/structure_plates.py`: Gunnerus tank tops and main bulkheads (hull-clipped by
  the existing internals reader) as block members, with steel table and OCX export.
- Tests: `tests/test_structure_export.py` (steel arithmetic, draft stamp, labels, contour area,
  grade names, OCX round trip, schema pass and a broken file that fails).

### 7.2 S1 to S6 (12 development designs, 18,244 truth members)

Unchanged from round 1 (section 2): round 2 adds attributes, not geometry.

| Metric | Result | Target |
|---|---|---|
| S1 detection P / R / F1 | 0.480 / 0.474 / **0.477** | F1 >= 0.80: **missed** |
| S1 longitudinal recall (precision) | 0.997 (1.000) | >= 0.95: met |
| S1 transverse recall (precision) | 0.346 (0.350) | >= 0.60: **missed** |
| S2 typed macro F1 | 0.779 | report |
| S3 centre error median / p95 (mm) | 10.4 / 197 | median <= 50: met |
| S4 printed thickness exact, longitudinal / transverse | 0.695 (0.997 cut to mm) / 0.999 | report |
| S5 steel volume, median abs relative error | 4.1 % (all 12 low: -0.6 % to -11.1 %) | <= 10 %: met |
| S6 members by placement source | 4,773 traced; 13,256 use a guess | report |

The causes of the two misses are in section 2 (block length and frame spaces per web space are
not printed). Steel weight per block: 772 t to 1,185 t (12 designs; 40 m block). The steel table
total divided by the density equals the S5 built volume (same members, same area x thickness).

### 7.3 OCX (plan section 4.3.3)

| Check | Result |
|---|---|
| Schema (OCX 3.0.1 XSD, `xmllint`) on every export | **12 / 12 MiDShip blocks valid** (18,029 plates); Gunnerus internals export valid |
| Round trip of our own export: plate count, thickness, area per plate | **all equal on 12 / 12** (and on Gunnerus, 12 plates) |
| VLCC sample `D-VLCC_1-HOLD-OCX-simple_v3.3docx` read by the same reader | 523 plates, all with thickness and area, no error (1.4 s); most common thicknesses 10, 12, 20, 15, 30 mm |

The first schema run of the unit test found a real error: OCX grade names are `A36`, not `AH36`
(the writer now maps them).

### 7.4 Gunnerus (development, G5)

G1 to G4 are the tanks lane's (`docs/TANKS_V1.md` section 5), not re-measured.

| G5 item | Result |
|---|---|
| Internal parts built / requested | 36 / 36 (24 tanks, 7 main transverse bulkheads, 5 tank-top runs) |
| Source labels over the parts' arguments | 64 `traced`, 20 `guessed` |
| Plates with an ID and a thickness | 12 / 12; thickness source: 12 `guessed` (10 mm) |
| Steel weight of these plates | 29.5 t (draft; 10 mm guessed) |

The Gunnerus construction plans print profile sizes (for example HP 100x7, HP 140x8) and a few
plate thicknesses (PL. 8,0, PL. 12,0, PL. 15,0), but no printed plate thickness is tied to a tank
top or bulkhead by text this reader follows; so the thickness stays `guessed`.

### 7.5 Open (resume point after round 2)

1. Gunnerus 3D structure from its midship section (DXF): extrude the section members (shell,
   tank top, girders, frames with the printed HP sizes) along the parallel body at the 500 mm frame
   spacing and clip them to the built hull at the ends (`tanks.HullSlicer` does the hull section).
   Not built in round 2.
2. Plate thickness from construction-plan labels (leaders to plates) for Gunnerus.
3. OCX `Stiffener` elements with a section catalogue (today webs and flanges are plates), and
   `Panel` grouping by surface.
4. Transverse recall on MiDShip (block length and frame-space guesses; brackets, openings), as
   section 5.
5. A sealed 3D split from the next MiDShip tranche.

## 8. Round 3 plan (2026-11-09): Gunnerus 3D internal structure from its own drawings

Written before the round 3 code (branch `feature/gunnerus-structure` from `continue/v0.5`
`80d5fa5`). Sections 1 to 7 are rounds 1 and 2; their numbers stay as their record. Development
case only: the Gunnerus truth STEP has no internals, so every metric compares printed sources with
each other (as G1 to G3 in `docs/WHOLE_VESSEL_GUNNERUS.md` section 6). No model call.

### 8.1 Sources (licensed, `work/sources/gunnerus/polarkonsult`, never committed)

- `Midship Section Rev0.dxf`: section `#I` (a plain frame of the 5,000 mm new part, frames A to J
  between frames 27 and 28) is the section to extrude. Moulded lines (layer `S0CO5`): 1-deck,
  tank top, shell contour, centre girder, double-bottom girders and deck girders. Labels: `PL`
  blocks with thickness attributes, flat-bar and HP profile labels, `nnnn FCL.` stiffener
  positions, `1250 O/BL.` tank-top level. Section `#G` (a bulkhead in the new part) gives the
  bulkhead plate and its stiffeners.
- `Shell Expansion Rev0.dxf`: shell strake thickness of the new part between the printed seams
  (`1875 FCL.`, `3525 FCL.`, `T.T. 1075 OBL.`, `1-DECK`); the side-frame key (`SECTION FRAME:`
  lists with their profiles).
- `Profile and Plan Rev0.dxf`: frame axes (frame spacing), tank-top plate labels, deck plate label,
  the new-part note (`LONG. GIRDERS ... DECK BEAMS: HP140x8`), girder elevations
  (`SECTION 3525 FCL ...`).
- The built hull (`work/whole-vessel/final/whole-vessel-draft.glb`) and the step 2 internals
  reader (`benchmarks/gunnerus/whole_vessel_internals.py`: main bulkheads and tank-top runs).

### 8.2 Build

1. Read section `#I`: members in the section plane (y from the centre line, z above the new
   baseline: old baseline from the `1250 O/BL.` tank-top line, new baseline 86.51 mm below it as
   printed). Thickness and profile of each member from the nearest label of its kind; a member
   with no label gets a labelled guess.
2. Parallel body: the frames (drawn frame axis, 500 mm, lettered frames A to J after 27) around the
   new part whose built-hull section is one piece (no skeg) with area within 3 % of the new-part
   mean. The members run over these frames.
3. Longitudinal members (one per plate panel and run): 1-deck, tank-top panels between girders,
   centre and side girders of the double bottom, deck girders (stiffener), shell strakes between
   the printed seams. Every outline is cut to the built-hull section at each frame (clip at the
   ends and wherever the hull narrows).
4. Transverse members at each frame: floor (hull section below the tank top), floor stiffeners,
   side frames, deck beam; at a bulkhead station of the internals reader the bulkhead plate (hull
   section from the tank top to the deck) and its vertical stiffeners replace frame and beam.
5. Thickness per member labelled `printed` (with the sheet and label) or `guessed`; IDs
   `G/<zone>/<member>/<frame>` stable across runs.
6. Steel table (round 2 writer) and OCX 3.0.1: plates with their real outline (not a box) and,
   where feasible, `ocx:Stiffener` elements (trace line, material, section from an
   `XSectionCatalogue` with `FlatBar` / `BulbFlat`), schema-checked against the local XSD.

### 8.3 Metrics and targets (printed vs printed; development figures)

| ID | Metric | Target |
|---|---|---|
| G6a | Girder and seam y positions: midship section linework vs printed FCL labels (midship, shell expansion, profile and plan), median abs | <= 10 mm |
| G6b | Tank-top and deck z: midship linework vs printed levels (`1250 O/BL`, `4200 AB.BL`, depth 4.287 m) and vs the internals reader's tank-top run at the same x | <= 25 mm |
| G6c | Drawn section `#I` shell vs built-hull section at frame I, median (p95) abs normal offset | median <= 30 mm |
| G7a | Steel weight with a printed thickness, share | >= 70 % |
| G7b | Members printed on two sheets: agreement of the values (list every pair) | report |
| G8 | Frame spacing from the drawn frame axes vs printed `FRAME DISTANCE 500` | median abs <= 5 mm |
| G9 | Steel weight vs a printed lightweight or steel weight | compare if printed, else "not found" |
| G10 | OCX: schema valid; round trip of plates (count, thickness, area) and stiffeners (count, section, length) | all valid and equal |
| G11 | Members inside the built hull (outline points within 10 mm of the hull section) | 100 % |

### 8.4 Checks and resume point

Unit tests on synthetic data: extrusion and clipping on a box hull, stiffener OCX validates and
round-trips. Order: 8.2 items 1 to 6, then the run and section 9 (results). Command (outputs in
git-ignored `work/step3/`):

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.gunnerus.structure_3d \
        --sources ../../../work/sources/gunnerus --assembly ../../../work/whole-vessel/final \
        --out work/step3/gunnerus --ocx-schema ../../../work/sources/ocx_schema/ocx/ocx_301

## 9. Results, round 3 (2026-11-09): Gunnerus parallel-body structure

Command (7 s, one process, no model call; outputs in git-ignored `work/step3/gunnerus`: steel
tables, `gunnerus_structure_DRAFT.3docx` 2.9 MB, `structure_3d.json` with every member):

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.gunnerus.structure_3d \
        --sources ../../../work/sources/gunnerus --assembly ../../../work/whole-vessel/final \
        --out work/step3/gunnerus --ocx-schema ../../../work/sources/ocx_schema/ocx/ocx_301

### 9.1 What is built

- `structure/extrude.py` (product code): hull section queries on the built-hull mesh (breadth,
  bottom, top, shell line, inside test), shell seams, and builders for flat plates along x,
  longitudinal plates down to the bottom shell, shell strakes between seams, transverse plates and
  stiffeners. Every outline is cut to the hull section at each frame.
- `structure/ocx.py`: plates are written with their real outline (`contour`); members with a
  trace and a profile are `ocx:Stiffener` elements (trace polyline, `MaterialRef`, `SectionRef` to
  an `XSectionCatalogue` with `BulbFlat`, `FlatBar` and `TBar`, web direction). Reader and round
  trip cover stiffeners. `steel.py` takes a stiffener's own volume (section area x length; HP bulb
  area guessed as 1.25 x web area).
- `benchmarks/gunnerus/structure_3d_reading.py`: reader of the three polarkonsult sheets (blocks
  exploded; `PL` labels from the `XX.X` attribute, flat bars from `FL.ST`).
- `benchmarks/gunnerus/structure_3d.py`: build, steel table, OCX and metrics.

Parallel body: frames 26 to 30 (x 13.0 to 20.0 m, 15 frames at 500 mm): the new part A to J and
the neighbours with a one-piece section within 3 % of the new-part mean area (37.3 m2). Members:
310 (51 plates, 259 stiffeners): 8 shell strakes (keel to 1875 FCL PL 10; to 3525 FCL PL 8; to
T.T. 1075 OBL PL 8; to the deck PL 7), 3 deck plates (two levels and the step), 12 tank-top panels
and the tank-top step (1075 O/BL aft of frame G, 1250 O/BL forward, from the plan `STEP`),
10 double-bottom girders (CL PL 7.5, 1875 FCL PL 8, 3525 FCL PL 9 from the girder elevations),
4 deck-girder runs (FB 150x8), 15 floors (PL 8), 180 floor stiffeners (FB 100x8), 26 side frames
(side-frame key; HP 100x6 guessed where the key does not list the frame), 13 deck beams
(HP140x8), 2 main bulkheads at frames A and G (from the step 2 longitudinal-section reader;
PL 8 and 18 HP 100x7 stiffeners each, from section #G).

Steel weight (draft, density 7.85 t/m3 guessed): **33.3 t** for the parallel body; printed
thickness 25.8 t, guessed 7.5 t. By label: floor 8.1, bottom shell 4.7, inner bottom 4.6, deck
3.8, bulkhead 3.6, side shell 2.4, girder 2.2, deck beam 1.4, floor stiffener 1.1, bulkhead
stiffener 0.7, frame 0.6, deck girder 0.1.

### 9.2 Metrics (printed vs printed; development figures)

| ID | Result | Target |
|---|---|---|
| G6a girder, stiffener and seam y vs printed FCL values (35 pairs) | median **0.0 mm**, max 0.0 mm | <= 10 mm: met |
| G6b levels (7 checks) | tank top 1250 O/BL 0.0 mm; deck 4200 O/BL 0.0 mm; deck vs printed depth 4.287 m 0.5 mm; deck vs built hull frames D to 30 0.5 mm. Misses: built-hull deck frames 26 to D at 4.114 m (**172.5 mm** below section #I); step 2 internals tank top **113.5 mm** (frame I) and **88.5 mm** (frame C) above ours | <= 25 mm: **missed** |
| G6c drawn section #I shell vs built hull at frame I (44 points) | median **13.5 mm**, p95 36.5 mm, max 39.1 mm | median <= 30 mm: met |
| G7a steel weight with a printed thickness | **77.6 %** | >= 70 %: met |
| G7b members printed on two sheets | 4 of 8 pairs agree (floor plate, floor stiffener, deck-girder web on port, tank-top level). Disagree: deck girder `8.0x150` (port) vs `8.0x100` (starboard) with both drawn 150 deep; plan note `W:200x8 / FL:150x10` vs section `8.0x150`; deck beam plan `HP140x8` vs section #I `HP 80x8` (marked EXIST) | report |
| G8 frame spacing from three drawn frame axes (51 label pairs) | median abs error **0.0 mm** (median 500.0 mm on every axis); max 28 mm, where a letter label sits off its frame (`A`, `I`) and between labels 20 and 25 (484 mm per frame) | <= 5 mm: met |
| G9 steel weight vs a printed lightweight or steel weight | **not found** (three construction sheets and the GA metadata: deadweight 164 t only) | compare if printed |
| G10 OCX | schema **valid** (OCX 3.0.1, `xmllint`); round trip 51/51 plates (count, thickness, area) and 259/259 stiffeners (count, section, length) equal | met |
| G11 member outline and trace points inside the built hull (10 mm) | **100 %** of 30,104 points; 0 members outside | 100 %: met |

Findings:

- The section linework and its labels agree exactly (G6a): the sheets are CAD drawings at full
  size, so positions read from the moulded lines need no tolerance.
- The built hull (whole-vessel step 1) has its 1-deck at 4.114 m aft of frame D and 4.287 m
  forward. Section #A prints 4113.5 there, so the step is in the drawings too; the members follow
  the built hull at every frame (deck in two levels with a step plate). The 86.51 mm offset between
  the old and new baselines is read at section #I and used for every frame; whether it changes
  aft of frame D is not read (open).
- The step 2 internals reader puts the tank top at the longitudinal section's `TANKTOP 1250` and
  `1450 AB.BL` levels; the polarkonsult sheets print 1075 and 1250 above the old baseline (1161.5
  and 1336.5 mm above the new). The two sources differ by 88 to 114 mm; the cause (another
  baseline or a revised tank top) is open. This lane does not edit the tank code.
- Thickness labels conflict between sheets in 4 of 8 pairs; each member keeps the label of the
  sheet named in its `thickness_basis`.

### 9.3 Labelled guesses

Density 7.85 t/m3; HP bulb area 1.25 x web area; web-frame depth 200 mm for the key's "PL 8.0
KN.FL. 50" frames; HP 100x6 for frames not in the side-frame key; tank-top thickness of the
outboard panel (no label: most common plan label, 10 mm); bulkhead at frame A takes section #G;
section #I scantlings carried to frames 26, 27, 28 to 30 outside the new part (labelled guessed);
floors at every frame; the section view is taken as seen from aft (starboard on the right).

### 9.4 Checks

`tests/test_structure_extrude.py` (box and V-bottom hulls, profiles, seams, OCX stiffener schema
and round trip), `tests/test_gunnerus_structure_3d.py` (frame labels, level runs, reader on the
licensed sheets: skipped when absent).

### 9.5 Open (resume point after round 3)

1. Frames outside the parallel body: extrude the old-part sections (#22, #23, #32) and the
   transverse sections of the C-JOB construction plan towards the ends.
2. The tank-top level difference to the step 2 internals (G6b) and the baseline offset aft of
   frame D.
3. Lightening holes in floors (drawn circles and slots), brackets (Det. B, C), the deck transverse
   girders `W:150x8 / FL:120x10` and the flat bar `FL. 100x8` of the side-frame key: not built.
4. OCX `Panel` grouping (plates and stiffeners by surface) and `ConnectionConfiguration`.
5. Section 7.5: items 1 and 2 are done for the parallel body; item 3 is done for Gunnerus (the
   MiDShip blocks still write stiffener webs as plates); items 4 and 5 stay open.
