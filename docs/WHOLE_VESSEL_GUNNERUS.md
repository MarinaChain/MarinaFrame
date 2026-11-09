# Whole-vessel step 1 on Gunnerus (development case)

Date 2026-11-09. Plan and fixed metrics: `docs/plans/2026-11-09-whole-vessel-scope.md` sections
3.4 (metrics, commit `1e34900`) and 3.5 (A/B protocol, commit `96b746e`). Both were committed
before the runs below. Gunnerus is a **development** case for whole-vessel work; the sealed hull
benchmark was not changed or run. All outputs are drafts; `engineering_approved` is false.

Inputs: `GA Gunnerus Rev1.dxf` (SHA-256 `c443cb5f…1bd5`). Truth: cached truth mesh of the hull
protocol (SHA-256 `0ceba4ad…7686`; hull and first superstructure tier, max z 6.622 m).
Scorer: `benchmarks/gunnerus/whole_vessel_metrics.py`. Drawings, renders, truth and run outputs
stay outside the repository.

## 1. Deterministic reading and build (no model call)

Code: `src/vessel_reconstruction/ga_reader.py` (profile levels, plan footprints from the region
the linework encloses), `benchmarks/gunnerus/whole_vessel.py` (component selectors, gap fills),
`src/vessel_reconstruction/ship_cad.py` (inline values and host guesses). The build ran in the
W13 Seatbelt worker in 10 s.

| Component | Op | Read from drawing (`traced`) | Filled (`guessed`) | Box x / y / z (m) |
|---|---|---|---|---|
| aft_deck | deck | outline (1-deck plan), top 4.114 (profile) | plate thickness 0.010 m | -0.99..14.49 / ±4.96 / 4.10..4.11 |
| main_deck | deck | outline, top 4.287 (label 1-DECK) | plate thickness 0.010 m | 14.51..30.39 / ±5.00 / 4.28..4.29 |
| house_t1 | deckhouse | outline (A-deck plan), 4.287..6.687 (labels 1-DECK, A-DECK) | none | 12.31..34.59 / ±4.84 / 4.29..6.69 |
| aft_bulwark | bulwark | outline, 4.114..5.114 | thickness 0.050 m | -0.99..14.49 / ±4.96 / 4.11..5.11 |
| house_t2 | deckhouse | outline (A-deck plan, inner walls), 6.687..9.087 | none | 14.51..24.13 / ±3.54 / 6.69..9.09 |
| wheelhouse | deckhouse | 9.087..11.487 | outline: tier-2 breadth over the roof extent (wheelhouse plan view not calibrated) | 13.57..21.27 / ±3.54 / 9.09..11.49 |
| fwd_rail | bulwark | outline, 6.687..7.712 | thickness 0.050 m | 26.69..35.19 / ±4.84 / 6.69..7.71 |

M7: 7 of 7 components built; argument values 11 `traced`, 5 `guessed`, 0 `ai_inferred`.

| Metric | Result | Target (not a gate) | Met |
|---|---|---|---|
| M1 aft deck level error (built minus truth) | +0.065 m; coverage 0.955 | abs <= 0.05 m; >= 0.90 | no; yes |
| M2 tier-1 footprint IoU | 0.796 | >= 0.90 | no |
| M3 tier-1 roof height error | +0.065 m | abs <= 0.10 m | yes |
| M4 tier-1 volume above 4.287 m | 487.8 vs 377.9 m³: +29.1 % | abs <= 10 % | no |
| M5 tier-1 x ends (aft, fwd) | 12.33 vs 15.53 m: -3.20 m; 34.58 vs 34.53 m: +0.05 m | abs <= 0.5 m | no; yes |
| M6 aft bulwark top | not measurable: the truth has no bulwark | | |

Not measurable (no truth): house_t2, wheelhouse, fwd_rail, main_deck (inside the house).

Causes (from the drawing and the truth, after the run):

- M2, M4, M5: the GA A-deck line starts at x = 12.3 m. Between 12.3 and 15.5 m the A-deck is a
  roof over an open "weather protected area" on the 1-deck plan. The reader takes the roof extent
  as the house extent. The truth house starts at 15.5 m. Fix: take the aft end of a tier from its
  walls on the deck below, not from its roof line. This one error gives most of the volume error
  (3.2 m x 9.7 m x 2.4 m is about 75 m³ of the 110 m³).
- M1 and M3: the truth deck and roof are 0.065 m below the drawn levels (4.049 vs 4.114 m and
  6.622 vs 6.687 m). The same offset on two decks suggests that the truth model surfaces lie at
  the underside of the deck plating or at a different datum. This is a content difference, not
  a reading error.

### 1.1 Development run 2: tier aft end from its end wall

This change was made **after** the truth comparison above, so run 2 is a development result on a
seen case, not a blind one. Rule: a deckhouse tier starts at its aftmost end wall on the plan of
the deck it stands on: a heavy (`S0CO3`) line across the ship, at least 0.4 x the moulded breadth
long, inside the roof extent (`ga_reader.transverse_walls`). Without such a wall the roof extent
stays. Tier 1: wall at x = 15.5 m (6.80 m long) on the 1-deck plan; a 2.77 m line at 14.5 m is
shorter than the limit. Tier 2: wall at 14.5 m, the same as its roof end.

| Metric | Run 1 | Run 2 | Target | Met (run 2) |
|---|---|---|---|---|
| M1 aft deck level | +0.065 m (cov 0.955) | +0.065 m (cov 0.955) | abs <= 0.05 m | no |
| M2 tier-1 footprint IoU | 0.796 | **0.940** | >= 0.90 | yes |
| M3 tier-1 roof height | +0.065 m | +0.065 m | abs <= 0.10 m | yes |
| M4 tier-1 volume | +29.1 % | **+9.4 %** (413.3 vs 377.9 m³) | abs <= 10 % | yes |
| M5 tier-1 x ends (aft, fwd) | -3.20 m, +0.05 m | **0.00 m**, +0.05 m | abs <= 0.5 m | yes |
| M7 built | 7 of 7 | 7 of 7 (11 traced, 5 guessed) | all | yes |

The remaining volume error comes mostly from the +0.065 m roof offset (about 11 m³ over the 162 m² truth footprint)
and the footprint outside the truth (IoU 0.94). M1 stays outside its target for the content
reason above.

## 2. A/B: ship-cad JSON (arm A) vs CadQuery code (arm B)

One run of the fixed protocol (section 3.5 of the plan), 2026-11-09, `deepseek-v4.1-flash` on
OpenCode Go key 1, 18 requests, all receipted (outside the repository). Code:
`benchmarks/gunnerus/whole_vessel_ab.py`. The final turn of each repeat is scored.

| Repeat | Arm | Turns | Built (of 7) | Success | M1 deck (m) | M2 IoU | M3 roof (m) | M4 volume | Prompt / completion tokens | Wall time (s) |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | A JSON | 3 | 7 | yes | +0.065 | 0.796 | +0.065 | +29.1 % | 14,797 / 37,297 | 339 |
| 1 | B code | 3 | 0 | no | - | - | - | - | 13,920 / 48,000 | 543 |
| 2 | A JSON | 3 | 7 | yes | +0.065 | 0.796 | +0.065 | +29.1 % | 16,972 / 34,487 | 271 |
| 2 | B code | 3 | 0 | no | - | - | - | - | 13,938 / 48,000 | 447 |
| 3 | A JSON | 3 | 7 | yes | +0.065 | 0.796 | +0.065 | +29.1 % | 16,999 / 29,014 | 250 |
| 3 | B code | 3 | 0 | no | - | - | - | - | 13,926 / 48,000 | 513 |

Provider-reported cost: USD 0 for every request (Go subscription billing). Total tokens: arm A
48,768 prompt and 100,798 completion; arm B 41,784 prompt and 144,000 completion.

Decision by the fixed rule: **arm A (ship-cad JSON) wins, 3 repeat successes to 0.**

What the numbers show:

- Arm B never reached code. In all 9 turns the model used the whole 16,000-token reply budget
  on hidden reasoning and returned no text (one reply had 53 characters). The result is a
  result of the fixed budget, not a proof that code is worse. A larger budget is a new protocol.
- Arm A needed 3 turns every time. Turn 1 always ran out of tokens; turn 2 failed validation
  (truncated JSON once, an unknown `source.method` twice). Turn 3 built all 7 components.
- Arm A copied the deterministic reading. Its M1 to M5 are equal to the no-model build (M2 differs
  by 0.0001 through outline rounding). The model did not find the overhang error that a person
  sees in the GA (the open area under the A-deck aft end). The model added no accuracy here; it
  made the same envelope at the cost of about 3 turns and 45,000 tokens per repeat.
- Prompt tokens were about 4,700 per first request with three images. The provider may not count
  image tokens, or may not pass the images to the model. This is not checked.

### 2.1 Round 2: thinking disabled, 32,000 tokens (protocol section 3.5.1)

Same inputs, scorer and rule; request settings `thinking: disabled`, `max_tokens` 32,000, the
same for both arms. 2026-11-09, 12 requests, all receipted. The run used the step 1 reading of
commit `5bdbca0`, before the aft-end fix of section 1.1. It differs from round 1 only in the
breadth of the unscored tier 2 and wheelhouse (±3.54 m against ±3.46 m, from an edge-band fix);
the three images are byte-identical to round 1.

| Repeat | Arm | Turns | Built (of 7) | Success | M2 IoU | M4 volume | Prompt / completion tokens | Wall time (s) |
|---|---|---:|---:|---|---:|---:|---:|---:|
| 1 | A JSON | 1 | 7 | yes | 0.796 | +29.1 % | 4,675 / 2,581 | 27 |
| 1 | B code | 3 | 0 | no | - | - | 81,194 / 37,551 | 180 |
| 2 | A JSON | 1 | 7 | yes | 0.796 | +29.1 % | 4,673 / 2,604 | 14 |
| 2 | B code | 3 | 0 | no | - | - | 24,849 / 9,047 | 46 |
| 3 | A JSON | 1 | 7 | yes | 0.796 | +29.1 % | 4,673 / 2,604 | 18 |
| 3 | B code | 1 | 7 | yes | 0.796 | +29.1 % | 4,530 / 4,686 | 29 |

M1 (+0.065 m, coverage 0.955), M3 (+0.065 m) and M5 (-3.20 m, +0.05 m) are the same in every
successful repeat. Provider-reported cost: USD 0 (Go subscription billing).

Decision by the fixed rule: **arm A (ship-cad JSON) wins, 3 repeat successes to 1.**

- With thinking disabled both arms answer. Arm A then needs 1 turn, about 2,600 completion
  tokens and 14-27 s per repeat: about 13 times fewer completion tokens than in round 1.
- Arm B fails on the CadQuery API, not on geometry: `close().face()` (no such method),
  `Face.offset2D`, a pending-wire error and a wrong OCP builder call. Errors fed back for 2 more
  turns were not fixed in B1 and B2. B3 built all 7 in one turn.
- Both arms again copy the code reading: every successful repeat has the scores of the
  deterministic build. In this setup the model adds no accuracy; the accuracy gain of section 1.1
  came from a code rule.

Next model test (needs a new fixed protocol before running): keep thinking disabled and the
JSON form; test whether the model adds accuracy over the code reading, for example on a case
where the code reading is wrong or missing (the round 1 reading with the overhang, or a drawing
without vector layers), and ask the model to check each tier's ends against its walls.

## 3. Round 3: raster path, model value test (protocol section 3.5.2)

Code: `benchmarks/gunnerus/whole_vessel_raster.py` (page render, host calibration, `RasterReader`,
R1 driver), `ga_reader.raster_levels`, `ga_reader.raster_transverse_walls`,
`ga_reader.PlanRaster.from_ink`. The PDF page is rendered at 150 dpi (4,967 x 7,021 px); the
readers see only crops of that image.

Host calibration (registration of each crop to the GA vector file, not part of the test): one
scale of 0.08125 px per drawing mm for all three crops (0.0123 m per pixel), offsets within 1.4 px
of each other; match scores 0.69 (profile), 0.58 (1-deck plan), 0.61 (A-deck plan).

R0, raster code only, was developed on this case: two fixes came from R0 build failures before
the R1 run (an outline that touched itself was not a valid solid; raster levels merged the aft
deck line with a nearby line, so the open aft deck now ends at the first tier). R0 has seen the
truth scores; it is a development result.

| Run | Built (of 7) | Success | M1 deck | M2 IoU | M3 roof | M4 volume | M5 ends (aft, fwd) | Turns | Prompt / completion tokens | Time (s) |
|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|
| R0 code only | 7 | yes | +0.082 m (cov 1.00) | 0.942 | +0.062 m | +9.0 % | 0.00, +0.70 m | - | - | 9 |
| R1-1 model | 0 | no | - | - | - | - | - | 3 | 21,798 / 5,208 | 26 |
| R1-2 model | 7 | yes | +0.082 m (cov 1.00) | 0.942 | +0.062 m | +9.0 % | 0.00, +0.70 m | 1 | 5,445 / 1,764 | 18 |
| R1-3 model | 0 | no | - | - | - | - | - | 3 | 23,852 / 7,275 | 44 |

R0 values: 11 traced and 5 guessed argument values, as on the vector path. Provider-reported
cost: USD 0. The R0 row is from the run that fed R1; R0 with the final code (an odd morphology
kernel, a one-pixel shift fix) gives the same scores.

Decision by the fixed rule: **the model does not add value on this raster case.** R1 built in 1
of 3 repeats (the rule needs 3 of 3), and the one build has the R0 scores (M2 differs by 0.0001).

- R1-1 and R1-3 failed validation in all 3 turns: the wheelhouse `source.method` was an invented
  value (`traced_extent`), and the error text did not name the component or the allowed values,
  so the model could not fix it. The error now names both (`ship_cad.validate_program`).
- The model again copied the code reading. It did not move the forward end of tier 1 (+0.70 m,
  from the raster reading of the A-deck extent) or correct the deck level.
- Raster versus vector code reading: IoU 0.942 vs 0.940, volume +9.0 % vs +9.4 %, forward end
  +0.70 m vs +0.05 m, deck level +0.082 m vs +0.065 m. On this clean plot, the raster code path
  is almost as good as the vector path. A scanned historic sheet will be harder.

## 4. Whole-vessel assembly (hull plus step 1 parts)

Code: `benchmarks/gunnerus/whole_vessel_assembly.py`. The hull comes from the current vector hull
path (`make_gunnerus_configs.vector_config`, `vector_path.run`, region loft) on the lines plan; the
parts come from development run 2 (section 1.1). Outputs stay in the git-ignored run folder.

### 4.1 Hull volume: cause and fix

The first assembly had a hull of 1,978.8 m³ against 1,302.3 m³ for the truth (+52 %). Checks:
units (mm, scaled by 1/1000 once: correct); symmetry (each region solid spans both sides once:
no doubling); end closure (flat end caps; the forward end is at x = 35.0 m against 34.55 m in the
truth: small). **Cause: the deck height.** The lines-plan station curves and the side line run up
to the bulwark and forecastle tops (top 7.59 m), so the loft held the bulwarks and the space of the
first tier as hull. The truth hull stops at the deck (aft deck about 4.05 m, 1-deck under the
first tier, which is a separate part in the whole vessel).

Fix: cut each read station at the deck at side from the GA reading (aft deck 4.114 m aft of the
first-tier end wall at x = 15.5 m, 1-deck 4.287 m forward of it) before the loft
(`cap_sections`). A CAD Boolean cut of the lofted solids was tried first and rejected: on this hull
it lost whole solids (volume below the waterline -17 %) and needed 5 GB of memory.

| Hull | Volume | Hull + tier 1 vs truth 1,302.3 m³ |
|---|---|---|
| Loft to the drawn tops (7.59 m) | 1,978.8 m³ | (hull alone +52 %) |
| Loft with station tops capped (forward curves still to 7.59 m) | 1,394.7 m³ | |
| **Loft of stations cut at the deck at side** | **966.7 m³** (15 solids, 68 stations) | **1,379.2 m³: +5.9 %** |

Hull score with the existing hull metrics (`benchmarks/gunnerus/score.py`, metric file
`config/metric_gunnerus.json`, cached truth sections). This is a development score of a new
build; the sealed result in `docs/BENCHMARK_GUNNERUS.md` does not change.

| Metric | Loft to drawn tops | Cut at the deck |
|---|---|---|
| Volume below T = 2.50 m (truth 486.3 m³) | 481.7 m³ (-0.96 %) | 483.0 m³ (-0.69 %) |
| Waterplane area at 2.50 m | -0.24 % | -0.06 % |
| Station half-breadth RMS, main band (median) | 0.509 m (0.279 m) | 0.468 m (0.279 m) |
| Station half-breadth RMS, below draft (median) | 0.276 m (0.051 m) | 0.277 m (0.063 m) |
| Between-station RMS, main band | 0.533 m (143 cuts) | 0.488 m (140 cuts) |

The remaining main-band RMS comes from the known content differences of section 6 of the hull
benchmark (thruster tunnel, aft step, skeg region). The +5.9 % whole-envelope error includes the
drawn deck and roof levels 0.065 m above the truth surfaces (section 1) and the first-tier volume
error of section 1.1 (+9.4 %).

### 4.2 Files and sizes

Sizes before (panel hull) and after the lighter hull of section 4.5 (with the appendages of
section 4.6):

| File | Before | After | Use |
|---|---|---|---|
| `whole_vessel/execution.json` | small | small | App parts list: ship-cad worker shape, plus `label`, `args`, `geometry`, and a per-argument `provenance` basis (docs/APP_SPEC.md "Whole-vessel parts") |
| `whole_vessel/hull.step` | 147.5 MB (21.1 MB gzip) | **15.4 MB** (3.4 MB gzip) | Hull to the deck, mm, no pcurves |
| `whole_vessel/<part>.step` | 7 parts, 7 kB to 158 kB | 11 parts, 7 kB to 158 kB | Decks, tiers, bulwark, rail; thrusters and skeg fins |
| `whole-vessel-draft.step` | 148.0 MB | **16.1 MB** | All solids in one compound (22 before, 26 after) |
| `whole-vessel-draft.glb` | 48.5 MB | **1.5 MB** | Display mesh for the 3D view (section 4.5), mm, Y-up, one node per part |
| `whole-vessel-draft.png` | | | matplotlib render of the display meshes |

STEP size: the first assembly STEP was 321 MB. Writing STEP without pcurves halves it (no change
to geometry). The hull is the rest: the region loft makes about 89,800 faces (shared knots of all
stations in a run times the stations). A coarser CAD bound does little (5 mm: 123.7 MB; 10 mm:
94.5 MB), and fewer section rows do not change the knots. For the app: load the GLB for the 3D view
and the small part STEP files; send the hull STEP gzip-compressed (21 MB, 1.3 s). Section 4.5
makes 28 of the 30 run-side pieces one side face each (2 stay panels): 3,151 faces, 15.4 MB.

Build time before: 366 s (capped loft 80 s, exports, mesh and render), peak memory about 5 GB
(9.6 GB in a rerun on 2026-11-09). After section 4.5: 184 s, peak memory 4.6 GB.

### 4.3 Happy path for invalid metadata

`ship_cad.triage_program` (used by `execute`, the worker and the A/B arm A driver): one invalid
component no longer rejects the program. A component whose only problem is an unknown
`source.view` or `source.method` builds from its values with source `unspecified` and status
`draft_guess`, and its reason names the problem. A component with invalid geometry arguments is
listed as unbuilt with the reason; the others build. The program header stays strict, and
`validate_program` stays strict for the Rust provider path. The 6 W13 safety mutations are still
caught.

### 4.4 Re-run one part from a mark (CLI)

The worker is now in the product: `python -m vessel_reconstruction.part_revise --task <run> --part
<id> --note=<text>` (the app's "Re-run with this note" runs it; it makes its own crops from
`whole_vessel/views.json`, see docs/APP_SPEC.md "Whole-vessel parts").
`benchmarks/gunnerus/whole_vessel_revise.py --folder <run> --sources <gunnerus sources> --part <id>
--note "..."` is a thin wrapper that writes `views.json` for an older Gunnerus run first. It
takes a person's mark (part id and note, 1 to 500 characters, as the app saves it), gives DeepSeek
the drawing crops, the part's current values with their source labels and the note (ship-cad JSON,
thinking disabled, at most 3 turns), rebuilds only that part in the ship-cad worker, and rewrites its
entry in `whole_vessel/execution.json`: new `geometry`, `args`, `source_labels` (`ai_inferred`),
`revision`, `revision_note`, `revision_history` (the old values) and the request receipts. The old
STEP stays as `<id>.r<n>.step`; the other parts do not change. The hull cannot be revised this way
yet (it is a loft, not ship-cad values).

One live check, 2026-11-09: part `wheelhouse` (outline guessed), note "The wheelhouse outline is a
code guess (tier-2 breadth). Read its breadth and both ends from the drawings; its roof runs from x
13.57 to 21.27 m in the profile." Result: revision 1 built in 1 turn, 4.8 s; the model returned the
same outline (x 13.57 to 21.27 m, y ±3.54 m) and height (9.087 to 11.487 m). The path works end to
end; the model again kept the values it was given (as in sections 2 and 3). A note with a number
("make it 5.2 m wide") is the useful case.

Second live check, 2026-11-09, through the app path (`part_revise.rs`, key from `model_keys.rs`,
product worker with its own crops: profile, 1-deck plan and A-deck plan around the wheelhouse), on
a copy of `work/whole-vessel/final`: note "Make it 6.0 m wide (y from -3.0 to 3.0 m); keep its
length and its height." Revision 1 built in 1 turn, 23 s: y ±3.00 m (was ±3.54), x and height
unchanged, volume 130.88 → 110.92 m³. Undo put back the entry and the STEP byte for byte. The
model had labelled the unchanged height `ai_inferred`; the worker now keeps the old label and
evidence of a value given back unchanged.

### 4.5 Lighter hull: reached

Target (plan section 3.7, fixed before the build): hull STEP below 30 MB, GLB below 10 MB, hull
metrics of section 4.1 no worse by more than 0.5 percentage points. **Reached.**

First tries (no result): station decimation (0 to 2 of 68 stations can go: this hull has no
parallel midbody) and one smooth loft per run side through spline-approximated station curves
(an invalid solid, +33 % and +212 % volume: the approximated curves do not keep the common-knot
correspondence).

Method (`geometry.build_region_hull(..., one_face_per_side=True)`, `geometry._bilinear_side_faces`):
a ruled panel between two corresponding polygon edges is a bilinear patch. A B-spline surface of
degree 1 in both directions, with the polygon vertices (ring x stations) as poles and periodic
around the ring, is the same surface as all the panels of a run side. It is one face, not one
face per panel. The end caps are planar faces bounded by the end curves of the surface. The
geometry does not change, so no fit tolerance is necessary. Details:

- Volume: the default volume integration of the kernel is not exact on this face (-16 % on a
  test box). `geometry.precise_volume_mm3` uses adaptive integration. The volume audit stays:
  each solid against its polygon prismatoid, at 1e-5 relative for this face type (the
  integration differed by up to 4.4e-6 relative on Gunnerus; a malformed solid is wrong by whole
  percents).
- Happy path: when the one-face solid is not a valid closed shell or fails the audit, that piece
  is built from ruled panels (the same geometry). On Gunnerus 2 of 30 run-side pieces (offset
  region, frames 18 to 25, port and starboard) use panels: their end polygon touches itself, and
  a cap bounded by the B-spline end curve is then not valid. Polygon caps sewn to the side face
  are valid, but they split the end curve into one STEP curve copy per polygon edge (1.4 GB STEP).
- GLB: `src/vessel_reconstruction/display_mesh.py` makes a display mesh separate from the STEP.
  The kernel mesher is not reliable on a one-face side (at 20 mm it lost 18 % of the volume; at
  5 mm, 0.4 %). The mesh of a degree-1 face comes from its poles: a ring column is left out when
  it stays within 1 mm of the chord at every station; each remaining cell gives two triangles.
  End caps are meshed from their polygon. Display hull volume 966.62 m3 against 966.71 m3 for the
  solid (-0.01 %). The GLB keeps the app contract (mm, Y-up, one node per part named by its id)
  and has vertex normals.
- Hull score: `benchmarks/gunnerus/whole_vessel_hull_score.py` runs `score.py` unchanged except
  for the mesher. On the one-face STEP, the kernel mesher at 0.1 mm gave no result in 20 minutes;
  the wrapper uses the exact triangulation of the same faces (two triangles per bilinear patch).

| Metric (section 4.1 scorer) | Panel hull (before) | One face per side (after) | Change |
|---|---|---|---|
| Hull volume (solid) | 966.712 m3 | 966.712 m3 | 0 |
| Volume below T = 2.50 m (truth 486.3 m3) | 482.96 m3 (-0.69 %) | 482.96 m3 (-0.69 %) | 0 |
| Waterplane area at 2.50 m | -0.06 % | -0.06 % | 0 |
| Station half-breadth RMS, main band (median) | 0.468 m (0.279 m) | 0.468 m (0.279 m) | 0 |
| Station half-breadth RMS, below draft (median) | 0.277 m (0.063 m) | 0.277 m (0.063 m) | 0 |
| Between-station RMS, main band | 0.488 m (140 cuts) | 0.488 m (140 cuts) | 0 |
| Hull + tier 1 vs truth 1,302.3 m3 | +5.9 % | +5.9 % | 0 |
| Hull STEP | 147.5 MB | 15.4 MB | -90 % |
| GLB | 48.5 MB | 1.5 MB | -97 % |

The scores agree to the printed digits because the surfaces are the same. The "before" column is
a rerun of section 4.1 on 2026-11-09 with the same result.

### 4.6 Appendages (development case)

Code: `benchmarks/gunnerus/whole_vessel_appendages.py` (the reader; `whole_vessel.py` adds its
components to the step 1 inputs, `--no-appendages` leaves them out) and
`benchmarks/gunnerus/whole_vessel_appendage_metrics.py` (metrics A1 to A3 of plan section 3.7,
fixed before the build in commit `8182deb`). Each appendage is a ship-cad `appendage`: a profile
outline (x, z) over a transverse span (y). The parts are in the assembly, in
`whole_vessel/execution.json` (label, args, geometry, per-argument basis) and in the GLB.

What the GA gives (selectors read by a person, snapped to ink by code):

- Azimuth thrusters, two: the profile block (side view) and the tank-top plan blocks at
  y = ±2.70 m. Outline `traced`: convex hull of the block linework below the drawn stern bottom
  (centre lines and phantom lines left out), x -1.02 to 0.99 m, z -0.76 to 2.23 m. Span
  `guessed`: centre ±2.70 m (traced), underwater breadth not drawn, half breadth 0.25 m.
- Skeg fins: S0CO2 linework under the profile keel line, x 1.56 to 7.94 m, down to z -0.91 m.
  Outline `traced` (closed by the keel line). Span `guessed`: breadth 0.30 m.
- Not built: rudder (none drawn: azimuth propulsion); bow thruster (a tunnel inside the hull:
  an opening, not an appendage); drop keel (marked "optional" on the GA).

| Metric | Run 1 | Run 2 (development) | Target |
|---|---|---|---|
| A1 built | 3 of 3 (outline `traced`, span `guessed`) | 4 of 4 (outline `traced`, span `guessed`) | all: yes |
| A2 thruster, max gap to the hull | 1.17 m (90 % of cells within 0.05 m) | 1.17 m (90 %) | <= 0.05 m: no |
| A2 skeg, max gap to the hull | 2.28 m (one fin on the centreline) | 2.51 m (89 % of cells within 0.05 m) | <= 0.05 m: no |
| A3 volume where the truth has none | thrusters 2.26 m3 each; skeg 0.46 m3 | thrusters 2.26 m3 each; fins 0.43 m3 each | report |

Truth: the truth STEP has no thruster, skeg fin or rudder (plan section 3.7). No appendage shape
is measurable. A3 is a content difference, not an error.

Causes (after the run):

- Run 1 put one skeg on the centreline (a guess). The built hull has twin skegs and a centre
  tunnel: the hull bottom at the centreline is about 1.7 m above the base at x 1 to 3 m, so the
  fin was 2.3 m below the hull. The profile keel line is the side view of the twin-skeg bottom
  (built hull bottom at y = 2.7 m: -0.484, -0.414, -0.345 m at x 3, 5, 7 m; keel line -0.482,
  -0.413, -0.344 m), and the thrusters are at the aft end of the twin skegs. Run 2 puts one fin
  under each twin skeg at the thruster centre y. This change came after the run 1 score: run 2 is
  a development result.
- Remaining A2 gaps: (a) the fins start at x 1.56 m, where the drawn skeg ends, but the twin skeg
  of the built hull starts at about x 3 m (truth: about x 2 m); the largest gap is at x 1.6 m.
  (b) The thruster outline is a convex hull: its aft edge slopes from the hull at z 2.23 m down
  to the propeller at x -1.0 m, so the top of the part there is 1.2 m below the hull. At the
  thruster mounting the contact is good (90 % of the top cells within 0.05 m).
- The guessed breadths (thruster 0.50 m, fin 0.30 m) and the convex outline make the volumes
  rough. The next step is a pod, a strut and a propeller disc as separate shapes.

## 5. Round 4: Balclutha sheet 7, model value on a scanned body plan (protocol 3.5.3, option B)

Code: `benchmarks/balclutha/model_value.py`. Run 2026-11-09, 3 repeats, `deepseek-v4.1-flash`,
thinking disabled, 32,000 tokens. Image: the body-plan crop of sheet 7 at 1/4 scale, 1600 x 1096 px,
without the table. A calibration check (drawn waterlines 0, 16 and 32 ft and two table cells plotted
on the image) put the cells on their station curves.

Truth: 151 half-breadth cells (stations 0 to 20, 4 to 32 ft waterlines) of the printed table,
transcribed twice by Claude from different crops; all 151 cells agree; not checked by a person.
One cell (24 ft WL, station 18) reads 1-9-4 in both reads, against neighbours 10-11-0 and 4-1-0;
it is kept as printed. The truth file stays outside the repository.

| Repeat | Cells given (of 151) | RMS | Station identity errors | Turns | Prompt / completion tokens |
|---|---:|---:|---:|---:|---:|
| R1-1 | 0 (every value null) | - | - | 1 | 1,387 / 463 |
| R1-2 | 151 (every value 0.0) | 4.35 m | 17 | 1 | 1,387 / 950 |
| R1-3 | 0 (every value null) | - | - | 1 | 1,387 / 463 |
| R0 (code, documented abstention) | 0 | - | - | - | - |

Decision by the fixed rule: **the model adds no value on this scanned body plan.** It did not read
the curves at all.

Cause (checked with one probe request): the image reaches the model (it read "7342" from a test
image), but an image costs only about 200 prompt tokens, so the provider passes it at low
resolution. A 1600 px body plan with 21 overlaid station curves is then not readable. This also
explains the low prompt-token counts of rounds 1 to 3 and why the model copied the code reading.
A new test needs tiles (one waterline band or a few stations per image, at full resolution) and
must check the image size the provider accepts; fix its protocol first.

### 5.1 Round 5: full-resolution tiles (protocol 3.5.4)

Protocol committed first (`6336d72`), then the harness `benchmarks/balclutha/tiled_value.py`
(`9e38369`, tests `tests/test_balclutha_tiled_value.py`, no model call). Run 2026-11-09, key 1,
`deepseek-v4.1-flash`, thinking disabled, 32,000 tokens, temperature 0.2. 32 tiles per repeat
(2048 x 1024 px, sheet pixels, one waterline per tile, inner and outer tile per side), each with
a 1/4-scale context image of that side (station numbers, red box). About 2,170 prompt tokens per
call, so the two images reached the model at the resolution the probe found (about 1,000 tokens
for a 2,048 px image). One addition to the prompt beyond the protocol list: one sentence on the
nesting order of the stations at a waterline (general body-plan knowledge, no value).

| Arm | Cells given (of 151) | RMS | Max | Within 0.05 / 0.15 m | Identity errors | Tile pairs > 0.15 m apart | Invalid replies | Tokens in / out | Wall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1-1 | 98 (65 %) | 1.56 m | 5.09 m | 10 % / 24 % | 11 | 38 | 0 | 69,590 / 2,880 | 57 s |
| R1-2 | 100 (66 %) | 1.68 m | 5.22 m | 11 % / 20 % | 12 | 48 | 0 | 69,606 / 3,014 | 170 s |
| R1-3 | 98 (65 %) | 2.13 m | 5.66 m | 8 % / 22 % | 15 | 41 | 0 | 69,618 / 2,857 | 237 s |
| R0 (tracer per tile) | 0 | - | - | - | - | - | - | - | - |

Median RMS 1.68 m (rule: at most 0.15 m). Coverage passes (at least 60 % in all repeats), RMS
fails by a factor of 11. **Decision by the fixed rule: the model adds no value on this scanned
body plan, also at full resolution.** No integration plan for the hull path is written; the
scanned-hull path stays code first, with the model as a gap filler with low weight.

R0: the tracer needs the centreline inside the panel, so the 16 outer tiles are refused
(`invalid_calibration`); of the 16 inner tiles, 13 abstain `resource_limit` (too many runs per
row: overlaid stations, diagonals, lettering) and 3 `missing_curve`. No cell read.

Failure mode (checked by hand on tile `fore-wl16-inner`, where the stations 19, 18, 17, 16 cross
the 16 ft waterline near x = 425, 885, 1325, 1715 px): the three repeats gave 4 crossings with
the wrong stations (15 to 18 at x 1430 to 1870), and twice 6 crossings (stations 14 to 19, x 410
to 1620) where the tile has 4. The model counts curves it cannot see and spreads them evenly. The
two tiles of one waterline disagree by more than 0.15 m on 38 to 48 cells. The limit is the
model's localisation of thin lines, not the image size. Run outputs (not in the repository):
the session scratchpad `r5/round5-001`.

### 5.2 Round 6: stronger vision models (protocol 3.5.5 and its amendment)

Protocol committed first (`fb254b5`; Crouton amendment `a2e44f3`), harness
`benchmarks/balclutha/router_value.py` (`0258bee`, `d5a999e`; tests
`tests/test_balclutha_router_value.py`, no model call). Run 2026-11-09. Same sheet, truth (151
cells), prompt, merge, metrics and decision rule as round 5.

- GPT 6.1 Sol and GPT-6 Astra: local codex-router (Responses API, ChatGPT subscription),
  reasoning effort high, `detail: original`, 4096 x 2048 px tiles (one per side and waterline,
  16 tiles; effective resolution 5,120 px by the probe).
- Crouton Alpha Free: OpenCode Go, key 1, `reasoning_effort: high`, temperature 0.2, round-5
  tiles (2048 x 1024 px, 32 tiles; effective resolution about 2,048 px by the probe).
- **Claude Sonnet 5.5 and Claude Opus 5.5: not tested in this round (tested in round 7, section 5.4).** The router has no route for them, and
  OpenCode Go lists only `claude-haiku-5-5`. No personal account was used.

| Model, repeat | Cells (of 151) | RMS | Max | Within 0.05 / 0.15 m | Identity errors | Tile pairs > 0.15 m | Invalid | Tokens in / out (reasoning) | Cost | Wall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT 6.1 Sol R1-1 | 147 (97 %) | 0.1500 m | 1.81 m | 99 % / 99 % | 0 | - | 0 | 187,566 / 22,388 (20,550) | subscription | 217 s |
| GPT 6.1 Sol R1-2 | 143 (95 %) | 0.1521 m | 1.81 m | 99 % / 99 % | 0 | - | 0 | 187,566 / 22,646 (20,848) | subscription | 267 s |
| GPT 6.1 Sol R1-3 | 151 (100 %) | 0.1481 m | 1.81 m | 99 % / 99 % | 0 | - | 0 | 187,566 / 21,421 (19,543) | subscription | 200 s |
| GPT-6 Astra R1-1 | 151 (100 %) | 0.1481 m | 1.81 m | 99 % / 99 % | 0 | - | 0 | 187,566 / 8,194 (6,316) | subscription | 97 s |
| GPT-6 Astra R1-2 | 149 (99 %) | 0.1489 m | 1.81 m | 99 % / 99 % | 0 | - | 0 | 187,566 / 8,852 (6,994) | subscription | 113 s |
| GPT-6 Astra R1-3 | 149 (99 %) | 0.1490 m | 1.81 m | 99 % / 99 % | 0 | - | 0 | 187,566 / 8,679 (6,821) | subscription | 95 s |
| Crouton Alpha Free R1-1 | 148 (98 %) | 0.2824 m | 1.83 m | 37 % / 70 % | 3 | 13 | 0 | 10,922 / 2,190 (0) * | free (0) | 797 s |
| Crouton Alpha Free R1-2 | 150 (99 %) | 0.3163 m | 1.84 m | 45 % / 72 % | 2 | 10 | 0 | 10,922 / 2,165 (0) * | free (0) | 648 s |
| Crouton Alpha Free R1-3 | 147 (97 %) | 0.2907 m | 1.82 m | 40 % / 70 % | 1 | 8 | 0 | 10,922 / 2,171 (0) * | free (0) | 752 s |
| DeepSeek V4.1 Flash (round 5), median | 98 to 100 (65 %) | 1.68 m | 5.09 to 5.66 m | 8 to 11 % / 20 to 24 % | 11 to 15 | 38 to 48 | 0 | 69,600 / 2,900 | not reported | 57 to 237 s |

\* The Go usage for Crouton does not count image tokens (28 prompt tokens with or without an image
in the probe), so its input tokens are text only. Sol and Astra have no tile pairs (one tile per
side and waterline).

Decision by the fixed rule (all 3 repeats at least 60 % of the cells and median RMS at most
0.15 m):

| Model | Median RMS | Coverage (min) | Decision |
|---|---:|---:|---|
| GPT-6 Astra | 0.1489 m | 99 % | **adds value** (passes) |
| GPT 6.1 Sol | 0.15004 m | 95 % | **no value by the rule** (misses by 0.04 mm) |
| Crouton Alpha Free | 0.2907 m | 97 % | **no value by the rule** (RMS twice the limit) |
| Claude Sonnet 5.5, Claude Opus 5.5 | - | - | not tested here (no route); see section 5.4 |

The margin is set by one cell. For Sol and Astra, the only cell more than 0.15 m off is 24 ft
waterline, station 18 (error 1.81 m in all 6 repeats); without it the RMS is 13 mm in every repeat
(12.7 to 13.3 mm). The truth has 1-9-4 (0.556 m) there, already flagged in section 5 as out of line
with its neighbours (10-11-0 and 4-1-0); both models read 2.368 to 2.370 m, which is 7-9-4
(2.375 m) within 7 mm. The cell is probably a transcription error (1 for 7); the fixed truth and
the decisions above are not changed. Sol gave fewer cells in two repeats (it left out stations 11 and 12, next to the half stations
at 4 to 28 ft), so the one bad cell weighs more in its RMS. A person should check the printed
cell. With the cell corrected, Sol and Astra would both pass with about 13 mm RMS, ten times
better than the rule. Crouton fails also without that cell (RMS 0.24 to 0.28 m; 37 to 45 % within 0.05 m; identity errors at stations 11 to 13), but it reads far better than DeepSeek (1.68 m).

Integration option: plan section 3.5.6 (Astra reads, Sol is the second reader; the controller
is not changed). Run outputs (not in the repository): the session scratchpad `r6/`.

### 5.4 Round 7: Claude Sonnet 5.5 and Opus 5.5 (subagents on the Claude subscription)

Protocol: plan section 3.5.7, committed first (`ba6e04c`). Scorer and pack builder:
`benchmarks/balclutha/claude_value.py` (`d2f4277`; tests `tests/test_balclutha_claude_value.py`,
synthetic data). Run 2026-11-09. This replaces the "not tested" line for the two Claude models in
section 5.2. Each reader is a Claude Code subagent on the Claude subscription (not the router, not
OpenCode Go). It reads image files of a tile pack with its file Read tool and writes one answer JSON.
Pack (outside the repository): 48 tiles of 1568 x 784 px at the sheet's own pixels (three per side
and waterline, 288 px overlap, because Claude downsamples a long edge over 1568 px), each with its
1/4-scale context image and a text file (round-6 prompt text, calibration, grid). Same sheet, truth
(151 cells), metrics and decision rule as rounds 4 to 6. 3 repeats per model, a fresh subagent each.
Scores: the scorer output was saved by the coordinator (session scratchpad `claude-scores.json`).

| Model, repeat | Cells (of 151) | RMS | Max | Within 0.05 / 0.15 m | Identity errors |
|---|---:|---:|---:|---:|---:|
| Claude Sonnet 5.5 R1-1 | 151 (100 %) | 0.14785 m | 1.81 m | 98.7 % / 99.3 % | 0 |
| Claude Sonnet 5.5 R1-2 | 151 (100 %) | 0.14799 m | 1.81 m | 97.4 % / 99.3 % | 0 |
| Claude Sonnet 5.5 R1-3 | 151 (100 %) | 0.14787 m | 1.81 m | 98.7 % / 99.3 % | 0 |
| Claude Opus 5.5 R1-1 | 151 (100 %) | 0.14787 m | 1.81 m | 98.7 % / 99.3 % | 0 |
| Claude Opus 5.5 R1-2 | 151 (100 %) | 0.14845 m | 1.81 m | 97.4 % / 99.3 % | 0 |
| Claude Opus 5.5 R1-3 | 151 (100 %) | 0.14795 m | 1.81 m | 98.7 % / 99.3 % | 0 |

Each run gave one extra cell that is not in the truth. Reader token use was about 176k to 191k
per run (from the subagent reports; wall time and a split into input and output tokens were not
recorded). Cost: the Claude subscription.

Decision by the fixed rule (all 3 repeats at least 60 % of the cells and median RMS at most 0.15 m):

| Model | Median RMS | Coverage (min) | Decision |
|---|---:|---:|---|
| Claude Sonnet 5.5 | 0.14787 m | 100 % | **adds value** (passes) |
| Claude Opus 5.5 | 0.14795 m | 100 % | **adds value** (passes) |

As for Sol and Astra, the margin is set by one cell: the maximum error 1.81 m (1.8079 m) is the
same doubtful truth cell (24 ft waterline, station 18; truth 1-9-4, probably a transcription error
for 7-9-4, section 5.2) in every run of both models. It is the only cell more than 0.15 m off in
every run (99.3 % within 0.15 m = 150 of 151). Without it the RMS is about 15 mm (computed from the
RMS above). The truth and the decisions are not changed; a person still has to check the printed cell.

Comparison of all models on this task (same 151-cell truth; rounds 4 to 7):

| Round | Model (access) | Image / tiles | Cells (of 151) | Median RMS | Max | Within 0.15 m | Identity errors | Decision |
|---|---|---|---:|---:|---:|---:|---|---|
| 4 | DeepSeek V4.1 Flash (OpenCode Go) | whole body plan, 1600 px | 0 or 151 (all null or all 0) | 1.68 m | 4.35 m or no value | - | 17 or none | no value |
| 5 | DeepSeek V4.1 Flash (OpenCode Go) | 2048 x 1024 tiles, 32 | 98 to 100 | 1.68 m | 5.09 to 5.66 m | 20 to 24 % | 11 to 15 | no value |
| 5 | Code only (R0 tracer) | same tiles | 0 | - | - | - | - | abstains |
| 6 | Crouton Alpha Free (OpenCode Go) | 2048 x 1024 tiles, 32 | 147 to 150 | 0.2907 m | 1.82 to 1.84 m | 70 to 72 % | 1 to 3 | no value |
| 6 | GPT 6.1 Sol (router) | 4096 x 2048 tiles, 16 | 143 to 151 | 0.15004 m | 1.81 m | 99 % | 0 | no value (misses by 0.04 mm) |
| 6 | GPT-6 Astra (router) | 4096 x 2048 tiles, 16 | 149 to 151 | 0.1489 m | 1.81 m | 99 % | 0 | **adds value** |
| 7 | Claude Sonnet 5.5 (subagent) | 1568 x 784 tiles, 48 | 151 | 0.14787 m | 1.81 m | 99.3 % | 0 | **adds value** |
| 7 | Claude Opus 5.5 (subagent) | 1568 x 784 tiles, 48 | 151 | 0.14795 m | 1.81 m | 99.3 % | 0 | **adds value** |

Result: all four models that read the curves well (Astra, Sol, Sonnet, Opus) are within about
2 mm of each other in median RMS (0.1479 to 0.1500 m) and have the same 1.81 m maximum at the one
doubtful cell; the pass or miss of the rule depends on that cell and the rounding, not on reading
quality. The Claude models are the only ones with all 151 cells in every repeat and no identity
error. Integration (plan section 3.5.6) is not changed by this round; a holdout sheet with printed
offsets and a person's check of the cell are still needed before a build. `engineering_approved`
stays false.

## 6. Step 2: internals (development case, metrics G1 to G5 of plan section 4.3.2)

Code: `benchmarks/gunnerus/whole_vessel_internals.py` (reader and build) and
`benchmarks/gunnerus/whole_vessel_internals_metrics.py` (G1 to G5; metrics fixed in `7225a67`
before the build). No model call. Run 2026-11-09, 340 s, one process; output in the git-ignored
`work/whole-vessel/internals-002` (the step 1 `final` assembly plus the internals).

Reading:

- Frame axis: the frame-0 line is the frame-grid line (phase of the structure lines mod 500 mm)
  nearest to the axis-label estimate; lettered frames A to J follow frame 27.
- Longitudinal-section construction plan: baseline, 1-deck level, tank-top runs (lines at each
  "TANKTOP nnnn AB.BL" level), main bulkheads (moulded lines from at most 2 m above the base up to
  the deck).
- Tank arrangement: tank table (number, name, frame range, net volume); tank outlines as enclosed
  regions of the "below tank top" and "below 1-deck" plans at each label (a region with a port
  and a starboard label is split at the centre line); bulkheads in the profile.
- Clip to the built hull: plane sections of the hull display mesh (a CAD Boolean took minutes on
  this hull). Tank volume by integration (0.05 m in x, 0.01 m in z); solids are 0.25 m slabs.

Built and added to `whole_vessel/execution.json` (op `deck`, `bulkhead`, `tank`; `kind`
`structure`), one STEP per part and one GLB node per part (GLB 5.8 MB): 4 tank-top runs, 7 main
bulkheads, 22 of 24 tanks. Not built: No 11sb (its label lies in the engine-room region) and No 4
(its outline is not closed off from No 3sb).

| ID | Metric | Result | Target |
|---|---|---|---|
| G1 | Tank end x vs table frame range, median abs (22 tanks) | **0.04 m**; 18 tanks within 0.05 m; misses: No 6sb/6p forward end -5.0 m, No 11p -2.5/+7.5 m (region leaks into the engine room), black water new -1.0/-2.0 m | <= 0.5 m: met |
| G2 | Tank volume vs table net volume, median abs relative error (20 tanks) | **8.2 %**; 12 of 20 within 10 %; misses: No 12 roll damping +102 % (height to the deck guessed), No 11p +757 % (leak), No 2sb/2p -54 %, No 3sb +23 % (holds No 4) | <= 15 %: met |
| G3 | Profile bulkheads vs longitudinal-section bulkheads | 7 of 7 at 0.00 m; the section's aft-peak bulkhead at x 1.0 m is not in the profile | <= 0.25 m: met |
| G4 | Built internal volume outside the truth solid | **13.1 %** (282,127 points); tanks and tank tops mostly below 1 %; aft parts high: cargo hold 31 %, No 12 21 %, bulkhead x 4.0 m 22 % (heights guessed to the 1-deck level where the truth deck is lower, and the aft hull shape) | <= 5 %: **missed** |
| G5 | Parts by label | 17 traced, 16 with a guessed value, 2 not built; 11 plates with an ID and a thickness (thickness guessed 10 mm: no plate label read) | all built: no (33 of 35) |

Not measurable against the truth: positions and thicknesses of the internals (the truth STEP has
no internal structure). G1 to G3 compare printed sources with each other.

## 7. Resume point

0. Step 2 internals (section 6): next fix the region leaks (No 11, No 4) with the drawn
   partitions on other layers, tank heights from the profile (No 12, hold), plate thickness from
   construction-plan labels, then G4 again.

1. Done: tier aft-end rule (section 1.1), raster code path (section 3), assembly and hull volume
   fix (section 4), app parts folder (section 4.2), happy path for invalid metadata (section 4.3),
   lighter hull (section 4.5: STEP 15.4 MB, GLB 1.5 MB, same scores), appendages run 2
   (section 4.6).
2. Appendages: thruster as pod, strut and propeller disc; fins from the x where the twin skeg of
   the built hull starts; bow-thruster tunnel as an opening in the hull. Then check A2 again.
3. Openings (hatches) in step 1 (not started).
4. Balclutha: option B run (section 5) and the tiled round 5 (section 5.1): no model value at
   whole-image resolution or on full-resolution tiles (median RMS 1.68 m). Do not repeat a
   reading round with this model. Round 6 (section 5.2): GPT-6 Astra passes (median RMS 0.149 m;
   13 mm without one probably mistranscribed truth cell), GPT 6.1 Sol misses by 0.04 mm with the
   same quality. Next: a person checks truth cell 24 ft / station 18, a holdout sheet, then the
   founder decides on the integration option (plan section 3.5.6).
5. Rust `ship_cad` vision schema: accept labelled inline values (Python accepts them now).
