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
path (`make_gunnerus_configs.vector_config` and `vector_path.run`, region loft) on the lines plan;
the parts come from development run 2 (section 1.1). No hull score was computed; the sealed hull
benchmark was not touched. Outputs (`whole-vessel-draft.step`, `whole-vessel-draft.png`, a
matplotlib render, and `components.json` for the app component tree: id, kind, box, volume,
source counts, review state `needs_review`, STEP path) stay in the git-ignored run folder. The
`components.json` shape (`marinaframe.components.v0`) must follow the TaskView `components`
field in `docs/APP_SPEC.md` when that lands.

| Item | Value |
|---|---|
| Solids | 24 (hull 17, parts 7), one STEP compound, 321 MB |
| Bounding box | x -1.00..35.19 m, y ±5.00 m, z -0.52..11.49 m |
| Hull volume (region loft) | 1,978.8 m³ |
| Parts volume | 712.1 m³ (house_t1 412.5, house_t2 160.9, wheelhouse 130.9, decks, bulwark, rail 7.8) |
| Build time | 393 s (hull loft, assembly and render) |

The hull volume equals the W13 region-loft hull (1,978.766 m³). That is +52 % against the hull
truth (1,302.3 m³; `docs/SHIP_CAD_LANGUAGE.md`). The cause is not checked here (overlapping
region solids are one candidate). The sum of the parts is therefore not a whole-vessel volume.
Find and fix the hull volume error before the app shows volumes.

## 5. Resume point

1. Done: tier aft-end rule (section 1.1), raster code path (section 3), assembly (section 4).
2. Hull volume: find why the region-loft hull is +52 % (section 4).
3. Appendages (rudder, skeg, thrusters) and openings in step 1 (not started).
4. Raster path on a scanned historic sheet (Balclutha, C.A. Thayer): code-first, the model as gap
   filler only (section 3 decision). A new model test needs a case where the code reading is
   wrong, and invalid metadata must not block a build (section 3).
5. Rust `ship_cad` vision schema: accept labelled inline values (Python accepts them now).
