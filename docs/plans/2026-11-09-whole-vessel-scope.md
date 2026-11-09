# From hull only to whole-vessel CAD (scope and plan)

Date 2026-11-09. Base `continue/v0.5`. Branch `whole-vessel-scope`.
Status: plan. Step 1 metrics in section 3.4 are fixed before the step 1 build.
Resume point: section 9.

All outputs are drafts. `engineering_approved` is always false. The Rust controller alone decides
review readiness. No output status uses the words "approved" or "verified".

## 0. Summary

Today MarinaFrame builds only the hull. A ship-repair customer needs more: the decks and
superstructure (to locate work), the structure with plate identities and thicknesses (to plan
steel renewal), and a repair workflow (gauging, wastage, renewal list, work package).

The founder direction for this plan:

- The AI fills gaps and writes geometry. The old W13 rule "the model never provides coordinates"
  is superseded. Every value has a source label: `traced` (read from drawing ink), `ai_inferred`
  (written by the model) or `guessed` (filled by code). A guess is built, not left out.
- Happy paths first. A missing input makes a labelled guess, not a failed build.
- Accuracy over cost. Progress before line-by-line provenance.
- Each step fixes its metrics before it builds, and reports them against ground truth.

Order by value to a ship-repair customer:

| Step | Scope | Customer value | Ground truth on disk | Effort |
|---|---|---|---|---|
| 1 | Whole-vessel envelope from GA and profile | Model that looks like the ship; locates spaces | Gunnerus STEP (hull and first superstructure tier) | 1-2 weeks |
| 2 | 3D structure: frames, bulkheads, tanks, plates with IDs and thickness; OCX export | Steel quantities, plate IDs for repair | MiDShip (midship), Gunnerus construction plans (no 3D structure truth), OCX samples | 4-6 weeks |
| 3 | Repair workflow: gauging to plate IDs, wastage vs rule minimums, renewal list, work package | The product a repair yard pays for | None. Needs design-partner gauging data | 3-4 weeks after data |
| 4 | Outfitting, piping, machinery | Later | Gunnerus engine room arrangement (2D only) | later |
| 5 | App: component tree, per-component review, mark-and-revise | Makes 1-4 usable | n/a (product work) | runs in parallel |

## 1. Competitor facts (checked 2026-11-09 on forgeshipyard.com)

- Marketing text: "hull today, engine, machinery, and outfitting parts next".
- Their research case is Balclutha (HAER). It shows hull, decks, bulkheads, framing, deckhouses
  and rigging. 44 of 114 identities have geometry.
- They publish no accuracy figures and no comparison with ground truth.
- They refuse to fill gaps: an identity without drawing evidence stays without geometry.

Our position: we fill gaps with labelled guesses (the customer gets a complete model), and we
publish error figures against ground truth for each component. `docs/STRATEGY_2026Q4.md`
section 1 is updated to match these facts.

## 2. Data

On disk under `work/sources/` (git-ignored; manifests per folder):

| Folder | Content | Use |
|---|---|---|
| `gunnerus/polarkonsult` | GA Rev1 (DXF/PDF/DWG), Lines Plan, Midship Section, Profile and Plan, Shell Expansion, Tank Plan | Steps 1, 2 |
| `gunnerus/extended/CJOB` | Construction plans (deck and double bottom, longitudinal section, transverse section), tank arrangement, freeboard plan, fire zone plan, engine room arrangement, diver platform; 3D model STEP and 3DM | Steps 1, 2, 4 |
| `gunnerus/metadata` | GA coded by SFI group (JSON) | Step 1 component names, step 5 tree |
| `midship` | MiDShip sample (36 designs: midship drawings, BOM, slice tables, some 3D) | Step 2 (W3 reader), step 3 rules |
| `ocx_schema`, `ocx_models_*` | OCX schema 2.8.6, 3.0.0, 3.0.1; sample models (VLCC one hold, TR02 test cases, viewer data) | Step 2 export and its validation |
| `rules` | ABS MVR Part 3 (Jul 2023), MiDShip rule code | Step 3 rule minimums (W4) |
| `haer` | C.A. Thayer and Wapama sheets (profiles, deck plans, midship sections, construction frames, engine) | Steps 1, 2 on messy drawings; no 3D truth |
| `balclutha_ca54_s7.tif`, `balclutha_ca54_s48.tif` | Two Balclutha HAER sheets | Like-for-like demo against Forge's case |
| `alma`, `dsyhs` | Historic sheets | Line identity, abstention |
| `shipd`, `simman`, `series60_freecad` | Parametric hulls, benchmark hulls | Hull only |

To procure (see `docs/STRATEGY_2026Q4.md` section 3): the next MiDShip tranche (3D for SGLD
designs, about 12 GB) for step 2; all Balclutha HAER sheets (loc.gov, a person downloads them)
for the like-for-like demo; design-partner fleet drawings, gauging, survey and repair records for
step 3 (PARTNER); expert labels (PAID) for authentic gold sets.

Licences: Gunnerus is CC BY-NC 4.0, and MarinaChain now holds a commercial licence for it. The
repository is public: never commit drawings, renders, truth or derivatives. Only hashes and
numbers go into docs.

## 3. Step 1: whole-vessel envelope from GA and profile

### 3.1 Scope

Read the GA (DXF vector path first; raster and model later). From the profile: deck levels,
deckhouse tier levels and their x extents. From the plan views: deck outlines and deckhouse
footprints. Build decks, deckhouses and bulwarks as solids on top of the hull with the W13
ship-cad operations. Openings and appendages (rudder, propeller or azimuth thrusters, bilge
keels) come in step 1b.

Changes to the W13 executor (`src/vessel_reconstruction/ship_cad.py`):

- An argument can be a measurement reference (as before) or an inline value with a source label
  (`ai_inferred` or `guessed`) and a basis text. A bare number stays rejected.
- The host can give a guess for each measurement reference. When the measurement fails, the
  executor builds from the guess and labels the component `draft_guess`. A component stays unbuilt
  only when it has neither a measurement nor a guess.

### 3.2 Development case

Gunnerus is a **development** case for whole-vessel work. No other ship on disk has a GA and 3D
truth. The sealed Gunnerus hull benchmark (`docs/BENCHMARK_GUNNERUS.md`) is not changed and not
run again. Results on Gunnerus show progress, not generalisation. A sealed whole-vessel case needs
a second ship with GA and 3D (design partner or a public research vessel).

### 3.3 Truth content (known before the build)

The STEP truth is one solid, 145 faces, bounding box z from -0.547 m to 6.622 m
(`docs/SHIP_CAD_LANGUAGE.md`). The GA gives A-deck at 6.687 m. Thus the truth has the hull and
the first superstructure tier (1-deck to A-deck). It has no tier on the A-deck and no wheelhouse.
Those components are built but are **not measurable**; we report them as not measurable, never
as zero error.

### 3.4 Step 1 metrics (fixed before the build)

Truth representation: the cached truth mesh (`truth_mesh.npz`, 0.5 mm chord deflection,
820,768 triangles, metres; from the sealed hull protocol, read only). Coordinates: x from frame
0 (aft positive forward), y to port, z from baseline, metres, as in the hull protocol.

Top-height map: on a grid of 0.05 m cells, x from -2.0 to 36.0 m and y from -5.2 to 5.2 m, the
height `T(x, y)` is the highest truth surface on the vertical line at the cell centre. The built
map `B(x, y)` is made in the same way from the tessellated built solids (one map per component).

Truth regions (truth only; constants fixed now):

- Tier-1 house region `H_T`: cells with `T >= 5.5 m`, opened with a 0.30 m square (removes
  rails and bulwarks), largest connected part. 5.5 m lies between the bulwark top and A-deck.
- Open aft deck region `D_T`: cells with `3.8 <= T <= 4.4 m` and x less than the minimum x of
  `H_T`, eroded by 0.30 m.
- Aft bulwark cells `W_T`: cells with x less than the minimum x of `H_T` and
  `4.6 m < T < 5.5 m`.

| ID | Component | Metric | Development target (not a gate) |
|---|---|---|---|
| M1 | Aft working deck | Median of `B - T` over `D_T` inside the built deck; coverage of `D_T` | abs <= 0.05 m; coverage >= 0.90 |
| M2 | Tier-1 deckhouse (1-deck to A-deck) | Plan footprint IoU of `H_T` and the built footprint (`B >= 5.5 m`) | >= 0.90 |
| M3 | Tier-1 deckhouse | Roof height error: median of `B - T` over the intersection | abs <= 0.10 m |
| M4 | Tier-1 deckhouse | Volume above z = 4.287 m (title-block depth to 1-deck): sum of `(top - 4.287) x cell area` over each region; relative error | abs <= 10 % |
| M5 | Tier-1 deckhouse | x extent errors (built minus truth, aft and forward ends) | abs <= 0.5 m |
| M6 | Aft bulwark | Top height error: built top minus median `T` over `W_T` | abs <= 0.10 m |
| M7 | All | Count of components built, by source label (`traced`, `ai_inferred`, `guessed`) | all requested components built |

Not measurable (no truth): tier on A-deck, wheelhouse, forward rail on A-deck, 1-deck plating
inside the house (covered). Hull metrics: not run (sealed).

Scoring code: `benchmarks/gunnerus/whole_vessel_metrics.py`. Results: `docs/WHOLE_VESSEL_GUNNERUS.md`.

### 3.5 A/B protocol: ship-cad JSON vs CadQuery code (fixed before running)

Founder decision 2026-11-09. Question: which output form gives the model better geometry for the
same step 1 components? Gunnerus drawings may go to DeepSeek (commercial licence, 2026-11-09).

| | Arm A: ship-cad JSON | Arm B: CadQuery code |
|---|---|---|
| Model output | `ship-cad/v1` program; every argument an inline value with source `ai_inferred` (or `guessed`) and a basis | One Python module with `build()` that returns `{component id: cadquery shape}` in metres |
| Execution | Existing executor (`ship_cad.execute`) in the W13 Seatbelt worker | Normal Python subprocess with the repo venv in its own work folder; wall-clock timeout 120 s; the prompt forbids network and file access outside the folder (no OS-level block, founder decision) |
| Output | One STEP per component (mm), `execution.json` | Same files, same format (the runner writes them) |

Same for both arms:

- Model: DeepSeek V4.1 Flash (`deepseek-v4.1-flash`) through the OpenCode Go endpoint, key 1, one
  Python client with a receipt per request (time, tokens, request and reply hashes).
- Inputs: three renders of GA vector linework and labels (profile, 1-deck plan, A-deck plan), each
  with its pixel-to-metre calibration; the title-block dimensions; the deterministic step 1
  reading (levels with x extents, footprints, which values are guesses) as text; the list of
  component ids to build (`aft_deck`, `main_deck`, `house_t1`, `aft_bulwark`, `house_t2`,
  `wheelhouse`, `fwd_rail`) with one-line meanings. No truth data.
- Limits: at most 3 turns per repeat (turn 2 and 3 only feed back the build errors and the
  component volumes and boxes), `max_tokens` 16,000 per reply, temperature 0.2.
- Repeats: 3 per arm, arms run in turn (A1, B1, A2, B2, A3, B3). No retry outside the 3 turns.
- Hull: not included in either arm (the step 1 metrics use top-height maps and do not need it).

Metrics (per repeat, then median and range over the 3 repeats):

1. Build success: components built of 7; repeat success = at least the 3 scored components built.
2. Accuracy: M1 to M6 of section 3.4 with the same scorer
   (`benchmarks/gunnerus/whole_vessel_metrics.py`, unchanged).
3. Model turns, prompt and completion tokens, provider-reported cost if the reply gives it.
4. Wall time (model plus build).

Decision rule (fixed now): the arm with more repeat successes wins; on a tie, the arm with the
higher median M2 IoU; on a tie, the lower median absolute M4 volume error. The deterministic step 1
result is the reference line, not an arm. With 3 repeats the result is a direction, not proof.

Code: `benchmarks/gunnerus/whole_vessel_ab.py`. Results: `docs/WHOLE_VESSEL_GUNNERUS.md`.

#### 3.5.1 Round 2 (arms A2 and B2), fixed before running

Round 1 did not test arm B fairly: every arm B reply spent the 16,000-token budget on hidden
reasoning and returned no code. Round 2 changes only the request settings, the same for both arms:

- thinking disabled in the request (`"thinking": {"type": "disabled"}`, `"stream": false`, as the
  Rust provider sends for table and vision reading in `rust-control/src/vision.rs`);
- `max_tokens` 32,000 (the shared cap); temperature 0.2 as before.

Unchanged: inputs (the same evidence pack and prompts), model, at most 3 turns per repeat, 3
repeats per arm in turn (A1, B1, A2, B2, A3, B3), scorer, metrics and decision rule of section 3.5.
Round 1 results stay as they are; round 2 is reported beside them.

#### 3.5.2 Round 3: raster path, model value test (fixed before running)

Question: on a drawing without vector layers, does the model add accuracy over the code reader?
This is the product path for old drawings (Balclutha, HAER).

- Input drawing: `GA Gunnerus Rev1.pdf`, rendered to one raster page at 150 dpi. No DXF content
  reaches either reader. Crops: inboard profile, 1-deck plan, A-deck plan.
- Host calibration (stands in for a person's calibration, not part of the test): page pixels to
  ship metres per crop, found once by registering the PDF raster to the GA vector file (scale and
  offset), with the residual recorded. The same calibration goes to both arms.
- Arm R0, raster code only (deterministic, 1 run): levels from long horizontal ink runs in the
  profile crop, snapped to the same level hints as the vector path; footprints from the region
  that the ink encloses in the plan crops; tier aft ends from long transverse ink runs on the deck
  below; labelled guesses where the raster gives nothing. No printed-label snapping (the PDF text
  is outlines).
- Arm R1, model (DeepSeek V4.1 Flash, arm A JSON form, thinking disabled, `max_tokens` 32,000,
  temperature 0.2, at most 3 turns, 3 repeats): the three crops with calibration, the title block,
  the R0 reading as text (guesses marked), the component list, and one added instruction: check
  each tier's levels and both ends against the walls on the deck below, correct the code reading
  where the image shows otherwise, and fill every gap.
- Scorer, metrics M1 to M7 and truth: unchanged (section 3.4).

Decision rule (fixed now): the model adds value if R1 builds the 3 scored components in all 3
repeats **and** its median beats R0 on at least 3 of these 4: abs M1, M2, abs M3, abs M4.
Otherwise the raster product path stays code-first, with the model as gap filler only. Report
also turns, tokens, provider cost and wall time.

#### 3.5.3 Round 4: Balclutha (HAER, scanned), protocol draft, not run

Data check (2026-11-09): only two Balclutha sheets are on disk: sheet 7 (overlaid body plan and an
offset table of the inner hull) and sheet 48 (section at frame 108). There is no outboard profile,
no deck plan and no 3D truth. Thus the step 1 parts (decks, deckhouses) cannot be read or scored on
Balclutha with the data on disk. Two options; the founder or CEO chooses one before a run:

- Option A (step 1 on Balclutha): a person downloads the HAER CA-54 profile and deck plan sheets
  from loc.gov. Truth: the printed dimensions on those sheets (deck heights, house lengths and
  breadths) and a person's reading of the house outlines, fixed before the run. Arms R0 (raster
  code only) and R1 (model, JSON, thinking off, 32k, 3 repeats) as in section 3.5.2. Metrics:
  per part, level error and footprint IoU against the person's reading; parts built of requested.
- Option B (data on disk now, hull only): sheet 7. Truth: the printed offset table (half-breadths
  at stations and waterlines), which the readers do not see (the table area is masked in the
  image). R0: the existing deterministic raster station reader; R1: the model reads the station
  curves (arm A JSON form with per-station half-breadth lists, thinking off, 32k, 3 repeats).
  Metrics: half-breadth RMS and max error at table cells, cells read of cells in the table, wrong
  station identity count. Decision rule: as section 3.5.2 (3 builds in 3 repeats and better on 3
  of 4: RMS, max, coverage, identity errors).

Recommendation: option B now (no download, independent printed truth), option A when the sheets
arrive. Neither is run until this section names the chosen option and is committed.

**Chosen 2026-11-09: option B.** Fixed before the run:

- Image: `balclutha_ca54_s7.tif` (SHA-256 `32f09c60…a8`), greyscale at 1/4 scale (2408 x 3611 px).
  The model sees only the body-plan crop (rows above the scale bars); the table is not in the image.
- Host calibration (the sheet's own grid, as in `docs/GEOMETRY_ACCURACY_V05.md` section 8.2):
  centreline column 1206, base row 1714.4, 122.87 px per metre (32 ft waterline at row 516).
  The forebody (stations 11 to 20) is drawn right of the centreline, the aftbody (0 to 10) left.
- Truth: the table rows "half-breadths" at the 4, 8, 12, 16, 20, 24, 28 and 32 ft waterlines for
  stations 0 to 20 (inner surface of hull; feet, inches, eighths, converted to metres). The
  assistant (Claude, not DeepSeek) transcribes the table twice from high-resolution crops; a cell
  whose two reads differ is left out; crossed or empty cells are left out. The truth is not
  checked by a person; the report says so. The truth file stays outside the repository.
- R0 (code only): the existing deterministic raster tracer with the section 8.2 specs. Its last
  run abstained on both sheet 7 specs (`ambiguous_curve`: overlaid stations); R0 is not run again,
  its cells read are 0. Any R1 build is therefore compared with the truth, not with R0 values.
- R1 (model): DeepSeek V4.1 Flash, thinking disabled, `max_tokens` 32,000, temperature 0.2,
  at most 3 turns (turns 2 and 3 only for an invalid reply), 3 repeats. Reply: JSON with, per
  station 0 to 20, the half-breadth in metres at each of the 8 waterlines (or null where the
  station does not cross that waterline), each value labelled `ai_inferred`.
- Metrics per repeat: cells given of truth cells; RMS and maximum error (m) over cells given;
  share of cells within 0.05 m and within 0.15 m; station identity errors (a station whose
  values fit a neighbouring station's truth better, by RMS). Report median and range over repeats.
- Decision rule (fixed now): the model adds value on scanned body plans if all 3 repeats give
  at least 60 % of the truth cells with a median RMS at most 0.15 m (about 1.5 % of the 8.5 m
  half-breadth). Otherwise the scanned-hull path stays code first with the model only as a
  gap filler with low weight.

### 3.6 Effort, checks, resume

Effort: 1-2 weeks (reader, executor change, scoring, Gunnerus run; then raster path and a
model pass for HAER sheets). Checks: synthetic unit tests for the reader, the executor guesses
and the height-map metrics (`tests/test_whole_vessel_*.py`); `make test-quick`; one Gunnerus run
with the frozen metric file. Resume: `docs/WHOLE_VESSEL_GUNNERUS.md` "Resume point".

### 3.7 Lighter hull and appendages: metrics (fixed before the build, 2026-11-09)

Lighter hull (development, `docs/WHOLE_VESSEL_GUNNERUS.md` section 4.5):

- Size targets: hull STEP below 30 MB; whole-vessel GLB below 10 MB.
- Accuracy: the score of section 4.1 of that document (`benchmarks/gunnerus/score.py`,
  `config/metric_gunnerus.json`, cached truth sections), each metric no worse than the "cut at
  the deck" column by more than 0.5 percentage points: volume below T = 2.50 m, waterplane area
  at 2.50 m, and the station and between-station half-breadth RMS (the RMS as a percentage of the
  truth half-breadth at the design draft, 4.8 m: 0.5 points is 0.024 m).
- Volume audit: each hull solid passes the polygon prismatoid check.
- GLB display mesh: its hull volume within 0.5 % of the solid volume.

Appendages. Truth content (checked before these metrics, as in section 3.3): the lowest truth
point in each 1 m x slice follows the hull bottom (x 1 to 2 m: -0.547 m; x 0 to 1 m: 1.632 m). The
truth has no azimuth thruster, no skeg or fin under the keel, and no rudder. Thus no appendage
shape is measurable against the truth; we report "not measurable", never zero error.

| ID | Metric | Development target (not a gate) |
|---|---|---|
| A1 | Appendages built, by argument source label (`traced`, `guessed`) | all requested built |
| A2 | Hull contact: the largest vertical gap between the appendage top and the built hull bottom, over the appendage top | at most 0.05 m |
| A3 | Truth: appendage volume where the truth has none (content difference, reported only) | report |

Next in step 1: appendages from the profile (rudder, skeg, thrusters) and the lines plan; openings
(hatches) from the plan views; model pass (DeepSeek, now authorized for Gunnerus) to name tiers
and fill gaps on drawings without vector layers (HAER Balclutha, C.A. Thayer).

## 4. Step 2: 3D structure

### 4.1 Scope

1. Extend the W3 midship reader (`docs/STRUCTURE_V1.md`: vector F1 0.9986, placement median
   4.4 mm on the sealed MiDShip split) along the ship. Use the frame spacing (GA title block:
   500 mm for Gunnerus) and the construction plans (longitudinal section, deck and double bottom,
   transverse section) to place transverse members at each frame and to run longitudinals between
   bulkheads.
2. Bulkheads and tank boundaries from the GA, tank arrangement and construction plans: positions
   in x from the profile, extents from the plan views, tank names and volumes from the tank
   arrangement (the volumes are a check).
3. Plates with stable IDs (zone, frame range, strake) and thickness from plate tables or
   construction-plan labels; a guessed thickness is labelled `guessed`.
4. OCX export (schema 3.0.1 in `work/sources/ocx_schema`), checked with the schema and with the
   sample models (`ocx_models_platform`, `ocx_models_ocxtools`, `ocx_models_viewer`).

### 4.2 Data

HAVE: MiDShip sample (midship only, with BOM truth), Gunnerus construction plans and shell
expansion (2D only), OCX schema and samples. PROCURE: MiDShip next tranche with 3D (12 GB,
founder decision), a ship with a 3D structural model (OCX or class model) from a design partner.

### 4.3 Metrics (fixed 2026-11-09, before the step 2 build)

#### 4.3.1 MiDShip 3D cargo-hold block

Input per design: the three plain PDFs only (view 3 members by the frozen W3 reader; printed
tables of views 1, 2 and 3). The reader sees no BOM, no slice table, no CAD file.

What the drawings do not give, and the fixed guesses (labelled `guessed`): block length 40 m
(x from 0 to 40 m); 4 transverse bulkheads (3 holds) centred in the block, 9 web-frame spaces per
hold at the printed web-frame spacing; 5 ordinary frame spaces per web-frame space. These are the
generator conventions found in a BOM survey of the 488 SGLD designs outside the W3 sealed split
(block length 40.0 m in 239, 40.0 to 43.7 m in the rest; 4 bulkheads and 9 web spaces in all 488;
5 frame spaces in 269, 4 in 204, 3 in 15). A printed value always wins over a guess.

Design set (development, all SGLD designs with 3D on disk except the W3 sealed ones):
tanker 107, 168, 292, 379, 391; container 37, 66, 80, 191; bulk 60, 230, 445 (12 designs). SGLD
118 and 215 have 3D but are W3 sealed designs: the scorer refuses them. There is no sealed
3D split; these are development figures. A sealed 3D set needs the next MiDShip tranche.

Truth: the design's full IGES (`sgld_design_<id>.igs`): one trimmed surface per BOM row, joined
to the BOM by `struct_rsObject`. Truth unit: one BOM row; its box is the tight axis-aligned
box of its surface (metres). Label from the BOM `Class`: the nine W3 labels, and for transverse
members `transverse_bulkhead` (`Transverse_Bulkhead`), `floor` (`Transverse_Floor`), `web_frame`
(`Vertical_Web_Frame`), `deck_beam` (`Deck_Transvere_Beam`), `frame` (`Vertical_Side_Frame`,
`Transverse_Bottom_Frame`, `Inner_Bottom_Transverse_Beam`, `Deck_Transverse_Stiffener,`),
`bulkhead_stiffener` (`Transverse_Bulkhead_*_Stiffener`), `bracket` (`Bracket_*`), `flange`
(every `Stiffener_Flange`), `other`. Group: `longitudinal` when the truth box is longer than
20 m in x, else `transverse`.

Matching: predicted and true boxes, each padded by 50 mm on every side (about the 1 drawing-mm
pad of W3 at the MiDShip scales), 3D IoU >= 0.5 candidates, one-to-one assignment maximising
total IoU (Hungarian), label-agnostic.

| ID | Metric | Development target (not a gate) |
|---|---|---|
| S1 | Detection precision, recall, F1, pooled over the 12 designs; recall per truth group, precision per predicted group | F1 >= 0.80; longitudinal recall >= 0.95; transverse recall >= 0.60 |
| S2 | Typed F1 per label (match and equal label) and macro over labels with truth | report |
| S3 | Placement of matched pairs: 3D centre distance (mm) median, 95th percentile, max; x centre error of matched transverse members | median <= 50 mm |
| S4 | Thickness of matched members with a printed thickness: exact rate (whole mm, as W3), by group; diagnostics: equal to truth cut to whole mm, abs error | report (W3 sealed plate rate was 0.892) |
| S5 | Steel volume: sum of built member volumes (area x thickness) against the sum of BOM `volume_pannel`, per design; median abs relative error | <= 10 % |
| S6 | Members by placement source label (`traced`: section and x from print; `guessed`: x from a guessed convention) | report |

#### 4.3.2 Gunnerus internals (development case)

The STEP truth is the hull and tier 1 as one solid (section 3.3): it has no internal structure.
Thus only containment is measurable against it; the other checks compare one printed source with
another printed source that the builder did not use for that value.

| ID | Metric | Development target (not a gate) |
|---|---|---|
| G1 | Tank x extents: built tank aft and forward ends (from the tank plan linework) against the frame range in the tank table (frame x from the drawn frame axis, ends at the frame lines); abs error, per tank and median | median <= 0.5 m (one frame) |
| G2 | Tank volume: built tank solid (inside the built hull) against the table net volume; relative error per tank, median abs | median abs <= 15 % (net volume excludes structure) |
| G3 | Main transverse bulkheads: built x (tank arrangement profile) against the nearest bulkhead line of the longitudinal-section construction plan; abs error | <= 0.25 m each |
| G4 | Containment: share of built internal volume (decks, double bottom, bulkheads, tanks) outside the truth solid, from points on a 0.10 m grid | <= 5 % |
| G5 | Internal parts built by source label; plates with an ID and a thickness (printed or `guessed`) | all requested built |

#### 4.3.3 OCX

Schema validation (OCX 3.0.1 XSD) pass on every export; round trip of our own MiDShip block export
(export, read back, compare plate count, thickness and area: all equal). The VLCC sample is read
with the same reader as a parser check (plate count and thickness parsed without error).

Effort 4-6 weeks. Checks: unit tests per reader; OCX schema validation in the quick tier (small
sample). Resume point: a new `docs/STRUCTURE_V2.md` written before the code.

## 5. Step 3: repair workflow

Scope: thickness gauging readings mapped to plate IDs; wastage = original thickness minus gauged
thickness; compare with W4 rule minimums (`docs/RULES_V1.md`: 25 ABS rules, pass/fail agreement
98.89 % on 12,753 designs) and class renewal criteria; steel-renewal list (plate ID, area,
weight); drydock work package (list plus model views).

Data: none on disk. Needs a design partner: gauging reports (TM reports), survey and repair
records, and the drawing set of the same ship. Until then, use a synthetic gauging set on a
MiDShip design (random wastage on plate IDs) to test the mapping and the list, and say so.

Metrics (fix with the partner data): mapping rate of gauging points to plate IDs; agreement of the
renewal list with the yard's actual renewals (precision and recall by plate, steel weight error).

Effort 3-4 weeks after the data arrives. Checks: synthetic end-to-end test; partner review.
Resume point: partner data request in `docs/partners/` (W7).

## 6. Step 4: outfitting, piping, machinery (later)

Gunnerus has an engine room arrangement (2D, DXF). Start with equipment footprints and heights as
labelled boxes (engine, generators, thrusters), then pipes as centre lines. No 3D truth on disk.
Do this after steps 1-3 and step 5 have a customer.

## 7. Step 5: app

Component tree (hull, decks, tiers, bulwarks, appendages, structure, plates), per-component review
(source label counts, metric if truth exists, evidence crop), and mark-and-revise for every
component: the user marks a component, writes the change, and the system re-runs only that
component with the change as an `ai_inferred` or user value. The ship-cad provenance gives each
component its source labels already. Owned by the app workstream (`app/`); this plan only defines
the data it needs.

## 8. Rules for all steps

- Fix metrics before the build; commit them first.
- Development and sealed cases are separate. Do not change sealed results.
- No widened gates after seeing results.
- At most 2 CPU-bound processes at once on the shared machine. Warn if free disk is below 6 GB.

## 9. Resume point

Step 1 on Gunnerus: see `docs/WHOLE_VESSEL_GUNNERUS.md`. Next actions in order: (a) appendage shapes (first run: section 4.6 of that document)
and openings in step 1; (b) model pass on Balclutha HAER sheets for a like-for-like comparison;
(c) step 2 plan (`docs/STRUCTURE_V2.md`) with metrics.
