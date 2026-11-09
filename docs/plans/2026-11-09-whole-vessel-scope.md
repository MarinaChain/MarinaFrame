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

#### 3.5.4 Round 5: Balclutha sheet 7 on full-resolution tiles (fixed before running)

Why: round 4 sent one 1600 x 1096 px image of the whole body plan and the model read nothing.
The vision probe (`work/vision-probe/REPORT.md`) shows that the provider makes every side larger
than about 2,048 px smaller and that 12 px features are marginal. Round 5 is the fair test: the
model sees the sheet's own pixels, one waterline at a time.

Unchanged from section 3.5.3: sheet `balclutha_ca54_s7.tif` (SHA-256 `32f09c60…a8`); truth
(the same 151 half-breadth cells, stations 0 to 20 at the 4 to 32 ft waterlines, file outside the
repository, not checked by a person); metrics (cells given of 151, RMS and maximum error, share
within 0.05 m and 0.15 m, station identity errors; median and range over repeats); decision rule
(all 3 repeats give at least 60 % of the truth cells **and** the median RMS is at most 0.15 m).
The table is not in any image.

- Pixels: the source TIFF at full resolution (9632 x 14442 px, 1-bit, 400 dpi), as greyscale.
  No resampling of the tiles.
- Host calibration (the sheet's own grid; it stands in for a person's calibration): centreline
  column 4824, 491.48 px per metre (section 3.5.3 values times 4). Grid rows and columns measured
  on the full sheet (darkest row or column within 20 px of the prediction): waterlines 0 to 32 ft
  at rows 6860, 6261, 5659, 5059, 4459, 3858, 3258, 2662, 2066; buttock lines at 2, 4, 8, 12, 16,
  18, 20 ft at columns 5124, 5421, 6020, 6618, 7216, 7517, 7814 (forebody, right) and 4526, 4225,
  3627, 3027, 2429, 2130, 1825 (aftbody, left). All within 6 px (12 mm) of the calibration.
- Tiles: one per side (aftbody stations 0 to 10 left, forebody 11 to 20 right), per waterline
  (4 to 32 ft) and per position: inner tile from 48 px across the centreline to 2,000 px out;
  outer tile from 1,002 px to 3,050 px out (998 px overlap; the outer edge is past the 20 ft
  buttock). Each tile is 2048 x 1024 px, centred on the waterline row. Thus 2 x 8 x 2 = 32 tiles.
  A tile cannot isolate one station (the stations are overlaid), so the reading is waterline by
  waterline.
- Request per tile (one call; at most 3 turns, turns 2 and 3 only for an invalid reply): image 1,
  the whole side of the body plan at 1/4 scale (station numbers legible, the tile drawn as a red
  box) for station identity; image 2, the tile. Text: the side and its stations, the target
  waterline row in the tile, the centreline column in tile pixels (may lie outside the tile), the
  pixels per metre, the waterline and buttock rows and columns inside the tile with their values,
  and what to ignore (half stations 11 1/2 and 12 1/2, diagonals, sheer, rub rail, deck edge,
  lettering). Reply: JSON, the crossings of station curves with the target waterline inside the
  tile, each as station number and x pixel, labelled `ai_inferred`. Invalid: a station outside
  the side, a repeated station, or x outside the tile.
- Merge (host, deterministic): half-breadth = |x_tile + tile_left - 4824| / 491.48. A cell given
  by both tiles of its waterline takes the mean; the count of such cells that differ by more than
  0.15 m is reported.
- R1: DeepSeek V4.1 Flash, thinking disabled, `max_tokens` 32,000, temperature 0.2, 3 repeats
  of all 32 tiles. Key 1 only.
- R0 (code only, same tiles): the existing tracer (`ingest.extract_sections`, one section per
  tile, z range = the tile rows) where it can run. It needs the centreline inside the panel, so
  the 16 outer tiles are refused by design. An inner tile that returns a curve gives one value at
  the waterline row; the tracer gives no station number, so the value is assigned to the station
  whose truth is nearest (an upper bound for R0). Deterministic, 1 run.
- Report also: tokens, turns, invalid replies, wall time per repeat. If the model adds value by
  the rule, the integration plan for the hull path (where tiles go in the agent loop) is written
  in `docs/WHOLE_VESSEL_GUNNERUS.md`; the controller does not change in this round.

#### 3.5.5 Round 6: stronger vision models on the round-5 task (fixed before running)

Founder decision 2026-11-09: test GPT 6.1 Sol, GPT-6 Astra, Claude Sonnet 5.5 and Claude Opus 5.5
on the round-5 task where DeepSeek V4.1 Flash failed. Accuracy over cost.

Access (checked 2026-11-09, before this section): the models are called only through the local
codex-router (OpenAI Responses API, `/v1/responses`; caller secret read into the process
environment, never printed or stored). The router lists `gpt-6.1-sol` and `gpt-6-astra` (input
modalities text and image). It has **no route for Claude Sonnet 5.5 or Claude Opus 5.5**
(`claude-sonnet-5.5`, `claude-opus-5.5` and `openrouter/anthropic/claude-opus-5.5` are refused:
not in the ChatGPT model list, no OpenRouter route). These two models are **not tested**; no
personal account or browser is used instead.

Image size probe (synthetic images, same design as `work/vision-probe`, reasoning effort low;
both models gave identical numbers):

| Square PNG | `detail: high` tokens | `detail: original` tokens | 8 px text read of 12 (high / original) |
|---:|---:|---:|---:|
| 1,024 | 1,229 | 1,229 | - |
| 2,048 | 3,001 | 4,916 | Sol 11 / 12, Astra 12 / 12 |
| 3,072 | 3,001 | 11,060 | 6 / 12, 5 / 12 |
| 4,096 | 3,001 | 19,661 | 0 / 12, 12 / 12 |
| 5,120 | 3,001 | 30,734 | 0 / 12, 12 / 12 |
| 6,000 and larger | - | refused | - |

`detail: high` downscales to about 2,048 px; `detail: original` keeps the pixels (token cost
linear in the pixel count, 8 px text read 12 of 12 at 5,120 px). Effective resolution with
`original`: 5,120 px per side for both models.

Fixed for the run (everything else as section 3.5.4: sheet and SHA-256, host calibration and grid,
truth of 151 cells outside the repository, context image, prompt text, reply form and validity,
merge, metrics, decision rule; R0 is not run again, its round-5 result is 0 cells):

- Tile size per model (at most the effective resolution): **4096 x 2048 px for both models**,
  one tile per side and waterline, from 48 px across the centreline to 4,048 px out (past the
  20 ft buttock at 2,990 px), centred on the waterline row. Thus 2 x 8 = 16 tiles; no tile pair
  overlaps, so "tile pairs > 0.15 m apart" is not applicable. The prompt names the tile size.
- Both images are sent with `detail: original` (no resampling by the provider).
- Models: `gpt-6.1-sol` and `gpt-6-astra` through the router. Reasoning effort **high** for both
  (the user's Codex default `model_reasoning_effort = "high"`; the catalog defaults are low for
  Sol and medium for Astra). `max_output_tokens` 32,000. No temperature (the reasoning models
  do not take one). At most 3 turns per tile (turns 2 and 3 only for an invalid reply).
- 3 repeats of all 16 tiles per model, 4 tiles in parallel.
- Report per model and repeat: cells given of 151, RMS, max, share within 0.05 m and 0.15 m,
  station identity errors, invalid replies, input / output (reasoning) tokens, cost, wall time;
  DeepSeek round 5 for comparison. Cost: both models run on the ChatGPT subscription through the
  router (no per-call charge); the report gives tokens.
- Decision rule per model (unchanged): the model adds value on scanned body plans if all 3 repeats
  give at least 60 % of the truth cells and the median RMS is at most 0.15 m. If a model passes,
  the integration option for the hull path is written in this plan; the controller does not
  change in this round.

**Amendment 2026-11-09 (founder addition, committed before any Crouton call on Balclutha):**
also test Crouton Alpha Free on OpenCode Go (model id `crouton-alpha-free` in the Go model list;
the Go list has no Claude Sonnet 5.5 or Opus 5.5 either, only `claude-haiku-5-5`). Endpoint and
key handling as DeepSeek in round 5 (chat completions, `x-opencode-session`), key 1 only.

Image probe (synthetic, same design): the usage reports 28 prompt tokens with or without an image,
so token cost cannot set the size; readability does. `detail` has no effect.

| Square PNG | 8 / 12 / 16 px text read of 12 |
|---:|---|
| 1,024 | 12 / 12 / 12 |
| 2,048 | 11 / 12 / 12 (10 with `original`) |
| 3,072 | 5 / 11 / 12 |
| 4,096 | 1 / 9 / 10 |
| 5,120 | 0 / 0 / 0 to 9 |

Effective resolution about 2,048 px, so Crouton uses the **round-5 layout unchanged** (2048 x
1024 px, inner and outer tile per side and waterline, 32 tiles, tile pairs reported). Request:
`max_tokens` 32,000, temperature 0.2, at most 3 turns, 3 repeats, 4 tiles in parallel (as round
5). Reasoning: the model reasons internally and reports no reasoning tokens; the `thinking` and
`reasoning` objects are refused (HTTP 400); `reasoning_effort: "high"` is accepted and is sent
(its high-quality setting; no measurable change on a probe). Cost: free model (the Go usage
reports cost 0). Metrics, decision rule and report as above.

#### 3.5.6 Integration option for the scanned-hull path (round 6 result; controller not changed)

Round 6 (`docs/WHOLE_VESSEL_GUNNERUS.md` section 5.2): GPT-6 Astra passes the fixed rule (median
RMS 0.149 m); GPT 6.1 Sol misses it by 0.04 mm (0.15004 m) with the same reading quality. For both,
every error above 0.15 m is one truth cell (24 ft, station 18), which is probably a transcription
error (the models read 2.37 m = 7-9-4; the truth has 1-9-4). Without it both read at 13 mm RMS.
Option (not built; for a founder decision):

1. Code: calibrate the sheet from its own grid (centreline, base, waterline rows, buttock columns),
   and cut one 4096 x 2048 px tile per side and waterline at full resolution, plus the 1/4-scale
   context image with the red box. A person confirms the calibration (one check per sheet).
2. Model, step "read station crossings": **GPT-6 Astra**, reasoning effort high, `detail:
   original`, the round-5 prompt. About 190k input and 9k output tokens and 100 s per sheet.
3. Model, step "second reader": **GPT 6.1 Sol** on the same tiles (same accuracy, 2.5x the output
   tokens and 2x the time). A cell where the two readers differ by more than 0.05 m, or that only
   one gives, is flagged for a person; the rest is taken as the mean.
4. Code: merge to the offset-table form, every value labelled `ai_inferred`, then the existing
   fairing and validation. `engineering_approved` stays false.
5. Not used for reading: DeepSeek V4.1 Flash (round 5) and Crouton Alpha Free (section 5.2).
   The deterministic tracer stays first for clean, non-overlaid drawings.

Before a build: the truth cell above checked by a person, and one more scanned sheet with
printed offsets as a holdout (the rule was met on one sheet only).

#### 3.5.7 Round 7: Claude Sonnet 5.5 and Opus 5.5 as Claude Code subagents (fixed before running)

Amendment to section 3.5.5 (founder rule 2026-11-09): Claude models are called only through the
Claude subscription as Claude Code subagents; never through OpenCode Go or the codex-router (which
has no route for them, section 3.5.5). A person (the PM) starts the readers. Section 3.5.5's "not
tested" for these two models is replaced by this round.

Fixed for the run (everything else as sections 3.5.4 and 3.5.5: sheet and SHA-256, host calibration
and grid, the 151-cell truth file outside the repository, prompt text, merge by waterline, metrics,
decision rule):

- Readers: Claude Sonnet 5.5 and Claude Opus 5.5, each a Claude Code subagent that reads image files
  with its file Read tool. 3 repeats per model (6 runs), each a fresh subagent with no earlier answer.
  Default effort of the subagent definition; no tool except file Read and one file Write.
- Pack (outside the repository, built by `benchmarks/balclutha/claude_value.py pack`): Claude
  downsamples an image whose long edge is over 1,568 px, so the tiles are at most 1568 px on the long
  edge and keep the sheet's own pixels (no resampling, the drawn lines keep the round-6 scale). One
  waterline per tile, both sides: 1568 x 784 px tiles, three per side and waterline (near: 48 px across
  the centreline to 1,520 px out; mid: 1,232 to 2,800; far: 2,512 to 4,080; 288 px overlap, past the
  20 ft buttock at 2,990 px), centred on the waterline row. Thus 2 x 8 x 3 = 48 tiles. Each tile has
  its 1/4-scale side context image with the red box (as rounds 5 and 6) and a text file with the
  round-6 prompt text, the tile's calibration (centreline x in tile pixels, 491.48 px per metre) and
  the grid rows and columns inside the tile. `TASK.md` gives the reading order and the answer form.
- Answer (one JSON file per run): the round-4 form, per station 0 to 20 a list of 8 half-breadths in
  metres (waterlines 4 to 32 ft) or null, `source: "ai_inferred"`. The reader converts pixels with the
  given calibration and takes the mean over overlapping tiles; the scorer is the round-4/6 scorer
  (`model_value.score`) and the unchanged decision rule (`router_value.decide`): all 3 repeats at least
  60 % of the 151 cells and median RMS at most 0.15 m. An invalid answer file scores 0 cells.
- The pack holds no truth value, no score and no earlier answer; readers are told to use only the pack.
  The truth file is read only by the scorer, after all runs.
- Scoring: `PYTHONPATH=src python -m benchmarks.balclutha.claude_value score --answers <folder>` with
  files named `<model>-<repeat>.json`.
- Report per model and repeat: cells given of 151, RMS, max, share within 0.05 m and 0.15 m, station
  identity errors; the PM adds subagent tokens and wall time. Controller not changed.

#### 3.5.8 Round 8: code measures, low-cost model identifies (fixed before running)

Why: founder strategy 2026-11-09: the product must work with low-cost models (Crouton Alpha Free
on OpenCode Go while it is free; DeepSeek V4.1 Flash when Crouton is rate limited); GPT and Claude
are a bonus path. Rounds 5 and 6 showed that the low-cost models fail at placing thin, overlaid
lines (DeepSeek counts curves it cannot see, 1.68 m; Crouton 0.29 m), not at reading. Round 7
splits the job: code places every line, the model answers only a small visual question.

Method (`src/vessel_reconstruction/body_plan_crossings.py`, `body_plan_reader.py`,
`body_plan_identity.py`; harness `benchmarks/balclutha/crossing_value.py`):

1. Code, full resolution, per half and waterline: trace the drawn waterline (the sheet is skewed
   a few px), mask its ink, follow every ink line through 40 rows above and below, fit it, and
   give the crossing column (sub-pixel), slope and line width. Sort each crossing into a kind:
   grid (thin, or vertical on a buttock column), stem or sternpost (vertical within 70 px of the
   centreline), lettering (more than 2.2 line widths), shallow (more than 6 columns per row),
   diagonal (an oblique straight line, within 5 px of one line, that runs at least 1,500 px to the
   centreline), else a station-curve candidate.
2. Code: follow each candidate's ink to the neighbouring waterline (row by row, moving line fit,
   passing crossing lines on the prediction) and link it to the crossing where it arrives (within
   8 px). Unlinked crossings enclosed by two links pair in order, or join the nearer neighbour
   when the other waterline has none there (curves drawn together). The links form one chain per
   drawn curve, swept bottom-up (chains may pass through one crossing where curves are drawn
   together, and fork where they part). Chains are ordered outermost first.
3. Station identity:
   - R0 (code only): nesting order. The outermost chain is station 10 (aftbody) or 11 (forebody);
     a chain that crosses only one waterline is not counted.
   - R1 (model): one question per chain. Image: a crop around the chain's curve (its followed
     path, extended up to 1,200 rows past its end crossings, plus 300 px, kept to its own half),
     scaled so that the longer side is at most 1,536 px (station numbers about 20 px tall), with
     the curve traced in semi-transparent red. Question: which station number labels the red curve
     (or null); reply `{"station": <int or null>, "reason": ...}`, a number outside the half is
     invalid. Code then numbers the chains in nesting order with the offset that agrees with the
     most labels (ties: the code's own count); a one-waterline chain is kept only if the model
     numbers it. Each chain whose label disagrees is asked once more (a fresh request), and the
     offset is chosen again.
   - Values in both arms: the code-measured column only, half-breadth = |x - 4824| / 491.48 m.
4. Fairness checks, reported only (they do not change values): nesting order at each waterline,
   bends above 1.0 m (second difference over three waterlines), cells more than 0.6 m from the
   mean of their neighbouring stations.

Unchanged from sections 3.5.3 to 3.5.5: sheet `balclutha_ca54_s7.tif` (SHA-256 `32f09c60…a8`), full
resolution; host calibration (centreline column 4824, 491.48 px per metre, the nominal waterline
rows and buttock columns of section 3.5.4); truth (the same 151 cells, file outside the repository,
not checked by a person, the doubtful cell at 24 ft station 18 kept); metrics (cells given of 151,
RMS and maximum error, share within 0.05 m and 0.15 m, station identity errors, median and range
over repeats); decision rule per arm (all 3 repeats give at least 60 % of the cells **and** the
median RMS is at most 0.15 m). The RMS without the doubtful cell is reported as extra information.

Correction found while building (from the sheet at full resolution): the forebody labels that the
round-5 prompt called half stations 11 1/2 and 12 1/2 are the numbers 11 and 12 with leader arrows.
The forebody has stations 11 to 20 only; this round has no half stations.

Arms (the measurement of steps 1 and 2 is computed once and shared by all arms and repeats):

- R0, code only: deterministic; run 3 times (the same result is expected).
- R1, base model: `crouton-alpha-free` on OpenCode Go, key 1, `reasoning_effort: high`,
  temperature 0.2, `max_tokens` 32,000, at most 3 turns per question (turns 2 and 3 only for an
  invalid reply), 4 questions in parallel, 3 repeats. A failed Crouton request (rate limit or
  error) is retried once after 5 s, then sent to `deepseek-v4.1-flash` (thinking disabled, same
  limits); the report counts the answers per model.
- Bonus, only if the local codex-router answers: `gpt-6-astra` through the router (as
  `router_value.py`, reasoning effort high, `detail: original`), same questions, 3 repeats. Never
  through OpenCode Go.

Report per arm and repeat: cells given, RMS, max, within 0.05 / 0.15 m, identity errors, RMS
without the doubtful cell; questions, re-asks, invalid replies, answers per model, labels equal to
the code's nesting count, identities that differ from R0, fairness flags, tokens, wall time.

Disclosure: the measuring code and its thresholds were developed on this sheet's image (overlays
of the chains checked by eye against the printed station numbers by the developer, Claude); the
truth file was not opened before the scoring run. There is no holdout sheet, so a pass is a pass
on the development sheet only; a second scanned sheet with printed offsets is needed before a
build decision.

#### 3.5.9 Round 9: holdout sheet for the round-8 reader (fixed before running)

Why: round 8 (section 3.5.8) passed on the sheet that the reader was developed on. This round
tests the same reader, without changes, on a second scanned body plan with a printed offset table.

Sheet: Schooner C.A. Thayer, HAER CA-61, sheet 4 of 38 ("Body Plan" and "Table of Offsets", drawn
2004 from William Doll's lines), `work/sources/haer/ca_thayer/loc_ca1506_sheet_04.tif`, SHA-256
`94c2f86a…8d9b70`, 17,618 x 13,617 px, 1 bit, 400 dpi, scale 3/8 in = 1 ft. US public domain (HAER,
Library of Congress). Chosen because it is the only sheet on disk with a body plan and a printed
offset table that may be sent to a provider: Wapama (HAER CA-67) has lines but no printed table;
the ALMA "Lines drawing and offsets" sheet has a table, but provider transfer is not cleared
(docs/CONTINUATION_STATUS.md); Balclutha sheet 7 is the development sheet.

Truth (made before any reader run, outside the repository, next to the Balclutha truth:
session scratchpad `wv-agent/thayer/truth_s4.json`): the printed half-breadths (feet-inches-eighths,
outside of planking) of stations 1 to 22 at the 3'-7" to 17'-7" waterlines (8 rows). Crossed cells
and the transom column (not a station curve) are left out: 151 cells. Two reads by Claude from
different high-resolution crops agreed on every cell (0 dropped); not checked by a person.

Host calibration (the inputs a person gives once per sheet; measured from the drawn grid, not from
the station curves): centreline column 8857.5; base row 6081.5; the grid is 600 px per 4 ft, so
150 px per ft = 492.13 px per metre; waterline rows 3'-7" 5543.5, 5'-7" 5243.5, 7'-7" 4943.5,
9'-7" 4643.5, 11'-7" 4343.5, 13'-7" 4043.5, 15'-7" 3743.5, 17'-7" 3443.5; grid columns at 4, 8,
12 ft and the 20 ft frame each side (centreline ± 600, 1200, 1800, 3000 px). Halves: aftbody left
of the centreline, stations 12 to 22 (outermost first 12, 13, ..., 22); forebody right, stations
11 to 1 (outermost first 11, 10, ..., 1). Unchanged from round 8: `MAX_OFFSET_PX` 3150,
`CROP_ACROSS_CENTRE_PX` 40, every threshold in `body_plan_crossings.py`, `body_plan_reader.py` and
`body_plan_identity.py`, the label prompt and the question image.

No change to the reader before scoring. The harness (`benchmarks/thayer/holdout_value.py`) only
adds this sheet's calibration, the truth loader, a scorer with this sheet's stations and
waterlines, and the Claude call. A failure is reported with its causes; fixes are a later round.

Arms (one shared measurement):

- R0, code only: deterministic, 1 run (identity by nesting order, as round 8).
- R1, Crouton: `crouton-alpha-free` on OpenCode Go, key 1, as round 8 (reasoning effort high,
  temperature 0.2, at most 3 turns per question, 4 in parallel, re-ask on disagreement); a failed
  request is retried once after 5 s, then sent to `deepseek-v4.1-flash`. 3 repeats.
- R1, Claude Sonnet 5.5: the same questions through the Claude subscription with the Claude Code
  CLI in print mode: `claude -p --model claude-sonnet-5-5 --tools "" --input-format stream-json
  --output-format stream-json --no-session-persistence --strict-mcp-config` and a fixed one-line
  system prompt; one image and the question in, no tools, default effort; `ANTHROPIC_API_KEY`
  removed from the environment (never an API key, never OpenCode Go). 3 repeats.

Metrics and decision rule (unchanged from rounds 4 to 8): cells given of 151, RMS and maximum
error, share within 0.05 m and 0.15 m, station identity errors (a station whose values fit a
neighbouring station's truth better), median and range over repeats; an arm passes if every
repeat gives at least 60 % of the cells **and** the median RMS is at most 0.15 m (R0: its one
run). Also reported: chains per half, questions, re-asks, invalid replies, answers per model,
labels equal to the code's count, fairness flags, tokens, wall time.

Reading of the result, fixed now: the reader **generalises** if R0 and the Crouton arm both pass
(the product path needs no strong model); it generalises **only with a strong identifier** if only
the Sonnet arm passes; otherwise it **does not generalise**, and the failure causes found on the
sheet are listed (no reader change in this round).

Known from the printed table before running (not used to change anything): stations 12 and 13
have equal offsets at 3'-7" to 13'-7" (drawn as one curve, labelled "13,12"); station 11 lies
inside station 10 at 13'-7" only; the sternpost and stem are drawn about 100 px from the
centreline (round 8 treats verticals within 70 px as stem).

#### 3.5.10 Round 11: ALMA holdout (stopped at the eligibility check, not run)

Planned: the round-10 reader, unchanged, on the ALMA "Lines drawing and offsets" sheet, with the
round 4 to 9 metrics and decision rule, arms code only (1 run), Crouton (3 repeats, DeepSeek
fallback) and Claude Sonnet 5.5 through `claude -p` on the subscription (3 repeats), and only the
sheet calibration (centreline, base, scale) set by a person.

Stopped before the protocol was fixed, before any truth and before any run: the sheet has no body
plan with station curves (its "half breadth view" is an end view of a hard-chine scow, with no
drawn waterlines), and its table gives sheer and chine heights and the sheer half-breadth only (45
cells, no half-breadth at a waterline). No cell can score the reader. Details:
`docs/WHOLE_VESSEL_GUNNERUS.md` section 5.8. The next holdout uses a sheet from section 5.7 of
that document with this same protocol.


#### 3.5.11 Round 12: BUE GIRL holdout (fixed before running)

Sheet: gillnet boat BUE GIRL (1957), HAER OR-166 sheet 2, "Lines and table of offsets",
US public domain. Source outside this worktree:
`work/sources/haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif` in the main checkout,
14,400 x 9,600 px, 1-bit, SHA-256
`f8950140c4ff2683801363acd7e60c126fa322ad4e571dcceb6e39d9c9f12196`.

Truth fixed before any run: PM supplied two independent Claude transcriptions (Sonnet 5.5 row
crops; Opus 5.5 column crops, different scripts), agreeing on all 175 non-empty printed cells
(0 differences after whitespace normalisation). Frozen source:
`/private/tmp/claude-501/bue-girl/truth-frozen/table_as_printed.json`, SHA-256
`355138afccaf13a1bad1bca2d801b13e5f386cba1f92027918586ad712a6c30c`.
The earlier session's pass1/pass2 reads were withdrawn and are not used. No new transcription.
Only the **Half Breadths From CL** block, stations 1 to 12, waterlines 2-6-0, 3-6-0 (designed
waterline), 4-6-0, 5-6-0 and 6-6-0 is scored: **39 nonblank cells**. Heights key the truth in
`/private/tmp/claude-501/bue-girl/truth_s2.json`. Feet-inches-eighths: trailing `+` adds 1/16 inch
(PM interpretation; the sheet does not define it). Leading `-` is treated as a sign/separator
convention, with magnitude used as half-breadth: the Transom column prints the same quantity
without that leading mark. This interpretation and a parser accepting `+` are harness-only.
Excluded cells remain listed with their printed contents and reasons: blank station/waterline
cells; all Transom cells (innermost unlabelled aft curve assumed transom, not a numbered station);
Sheer and Rabbet/Keel rows (not waterline half-breadths), including the doubtful Sheer station 12
font/sign and Keel ditto cells at 11, 12 and Transom. The Heights From Baseline block is not used
and remains intact in the frozen source. No nonblank numbered-station waterline cell is removed.

Host calibration supplied by an independent agent without truth/transcription access, from drawn
ink, grid and labels only; constants accepted as given, not re-derived here. Disclosure: its first
low-resolution overview included the table; it did not use table values. Calibration evidence:
`/private/tmp/claude-501/bue-girl/calibration/calibration.json`, README and crops beside it.
Centreline column **3266.5**, baseline row **9082**, **400.0 px/ft** (1312.335958 px/m).
Two independent drawn spacings: waterlines 400.25 px/ft and feet scale bar 400.0 px/ft agree
within 0.06 %. The centimetre scale bar is 2.5 % off and is not used. Whole-pixel waterline rows:
2-6-0 **8081**, 3-6-0 **7681**, 4-6-0 **7281**, 5-6-0 **6880**, 6-6-0 **6480**. There are no
printed waterline labels on the body plan; heights follow from baseline and scale. Fore half is
**left**, sign -1, stations outermost first **6, 5, 4, 3, 2, 1**, grid columns **2966, 2698, 2430,
2162, 1894**, plus dashed projection column **1693**. Aft half is **right**, sign +1, stations
outermost first **7, 8, 9, 10, 11, 12**, grid columns **3566, 3834, 4102, 4370, 4638**.
Maximum search half-span **1650 px** is sheet calibration, replacing Balclutha's 3150 px.
Aft curves cross only the lowest three waterlines. Short aft horizontals at 7349/7749 are not
waterlines. Use the same fixed waterline rows on both halves: no alternate aft-row run, no masking
of those segments or painted waterline, and no image preprocessing beyond `bpc.load_ink`.

Frozen reader: the source at **dabaa13**, including round-10 development changes already present
there; no claim that this is the historical pre-round-10 implementation. No changes to
`src/vessel_reconstruction/body_plan_*` or `benchmarks/balclutha/crossing_value.py`. All reader
thresholds, prompts, question images, candidate rules and naming remain unchanged. Harness adds
only calibration, truth conversion/parser, scorer and run orchestration; reuses round-8 functions
and Thayer's `claude_call`. A frozen-source guard test is included with this protocol so the
required pre-commit test command can run before the harness exists. No scores before protocol
and harness commits. A failure is reported, not repaired in this round.

Arms: R0 code only, **1 run**; R1 Crouton Alpha Free via `round8.crouton_with_fallback`, **3 repeats**
(one failed-request retry after 5 s, then DeepSeek V4.1 Flash); R1 Claude Sonnet 5.5 via Thayer
`claude_call`, **3 repeats**, `claude -p` subscription, no tools or API key, never OpenCode Go.
Four question workers, temperature/effort, invalid-reply retries and disagreement re-asks unchanged.
Each arm measures the same fixed sheet/layout deterministically. Outputs outside the repository:
`/private/tmp/claude-501/bue-girl/runs/<arm>`. No repeat to improve a score. If access/quota fails,
record it and continue the other arms.

Metrics and decision rule copied from 3.5.9: cells given of 39, RMS and maximum error, share within
0.05 m and 0.15 m, station identity errors (values fitting a neighbouring station better), median
and range over repeats. An arm passes if **every repeat gives at least 60 % of cells and median
RMS is at most 0.15 m** (R0: its one run). Also report chains per half, questions, re-asks, invalid
replies, answers per model, labels equal to code, fairness flags, tokens and wall time.
The reader **generalises** if R0 and Crouton both pass; **only with a strong identifier** if only
Sonnet passes; otherwise **does not generalise**. Do not widen this rule after results. A metrics
pass does not establish correct identities or engineering use. `engineering_approved` stays false.

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

### 3.8 Superstructure detail: metrics (fixed before the build, 2026-11-10)

Problem (founder review): decks, bulwarks and deckhouses are their GA plan outline extruded
straight up (`ship_cad._prism`). The GA plan outline is the outermost drawn line (rail, forecastle
top), so at the bow and the stern the parts stand out past the hull side at the deck. Nothing reads
sheer, flare, camber, end rake or windows.

Change (development case Gunnerus; results in `docs/WHOLE_VESSEL_GUNNERUS.md` section 7):

1. Decks and bulwarks from the hull: the deck edge is the hull half-breadth at the deck (the
   built hull's deck at side); a bulwark is that edge carried up to the read bulwark top with the
   drawn shell above the deck, and above the drawn top with the flare of the top rows continued.
   Deck camber from the midship section when the deck line is drawn there, else B/50 labelled
   `guessed`. A GA outline outside the hull is a check item with its distance, not geometry.
2. Deckhouses: the base on the deck; the sides follow the hull where the tier reaches it (the
   forecastle tier at the bow); end walls follow the drawn end contour in the profile (rake, raked
   wheelhouse windows); window recesses where the profile draws windows; rounded plan corners where
   the plan is not read (labelled `guessed`).
3. A containment test: no shaped part is outside the hull side by more than the tolerance.

Hull side reference: the lines-plan station envelope (`superstructure.HullSide`): half-breadth
at (x, z) from the station rows; above a station's drawn top, the top offset plus the flare of the
last 0.5 m of rows, for at most 1.5 m. Overhang tolerance: **0.02 m** (two deck plate thicknesses).
Scorer: `benchmarks/gunnerus/whole_vessel_superstructure_metrics.py` (20,000 area samples per part
plus every tessellation vertex).

| ID | Metric | Before (run 2, `work/whole-vessel/step1`) | Development target (not a gate) |
|---|---|---|---|
| S1 | Overhang of each deck, bulwark and deckhouse: max plan distance outside the hull side at its own height; share of area outside by more than 0.02 m | max 3.33 m (house_t1 at x 32.8 m, z 4.287 m); main_deck 1.71 m, fwd_rail 1.01 m, aft_deck and aft_bulwark 0.16 m; share up to 55 % (bulwarks) | max <= 0.02 m for every part; share 0 |
| S2 | GA/hull disagreement as check items: count and largest distance per part | none recorded | every part whose GA outline is outside the hull has a check item with the distance |
| S3 | Step 1 metrics M1 to M7 (section 3.4) | M2 0.940, M3 +0.065 m, M4 +9.4 %, M5 0.00 / +0.05 m, M1 +0.065 m (coverage 0.955) | not worse: M2 >= 0.940, abs M4 <= 9.4 %, abs M5 <= 0.05 m, M1 and M3 unchanged |
| S4 | Tier-1 half-breadth at the bow (x 28, 31, 33, 34 m) from its top map against the truth tier-1 region | +0.20, +0.60, +0.85, +1.15 m | abs <= 0.10 m at each station |
| S5 | Read values against the drawing: camber against the midship section deck lines; end rake (dx/dz) against the profile end lines as a person measures them (wheelhouse front: lower -0.70, upper +0.70; aft upper -0.70; tier-2 front curve from x 24.13 m at the roof to about 26.6 m at z 7.67 m); bulwark top against the GA (5.114 m) | not read | camber exact (0 when the deck line is straight); rake within 0.05; end x within 0.10 m |
| S6 | Count of values by source label (`traced`, `ai_inferred`, `guessed`), including the new detail values | 15 traced, 9 guessed (all parts incl. appendages) | report; every value has a label |
| S7 | Hull + tier 1 volume against the truth solid (section 4.1 of the results) | +5.9 % | report; expected closer to 0 |

Not measurable (no truth): the bulwarks (truth has none), tier 2, wheelhouse, forward rail, window
recesses. The truth deck is flat (top map: 4.049 m across the aft deck at every station), which a
camber of 0 must not change (M1).

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

Step 2 (2026-11-09): MiDShip 3D block results in `docs/STRUCTURE_V2.md`; Gunnerus internals in
`docs/WHOLE_VESSEL_GUNNERUS.md` section 6. OCX export (section 4.3.3) not started.
