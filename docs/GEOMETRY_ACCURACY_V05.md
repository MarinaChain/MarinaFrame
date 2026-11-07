# Semantic and local geometry accuracy (0.5, roadmap step 3)

Date: 2026-11-07. Base: `77dc6a8` (branch `continue/v0.5`). Host: macOS arm64, Python 3.12, CadQuery 2.7.0.
This is a development ledger. All cases are known development data. No gate or tolerance was
changed. No reference geometry entered inference. Every candidate keeps `engineering_approved=false`.

## 1. Evidence inventory

| Evidence | Where | Kind | Status on this machine |
|---|---|---|---|
| Procedural hull drawings (`development_wigley`, `holdout_roundflare`, `holdout_multichine`) | `benchmarks/generate.py`, seeds in `benchmarks/holdout_contract.json` and `confirmation_contract_v2.json` | Procedural | Regenerated deterministically. The known-47 case `holdout_roundflare-271097-drafting` regenerates with drawing SHA-256 `04a2c841f092651fdd299c1c51456ded41325129c6f3e151b9ed922b600b0dc9`; one source pixel is 0.0238992 m, as in the 0.4 record. |
| Agent and table examples | `examples/make_*_example.py` | Procedural | Present. |
| Unit-test rasters | `tests/test_source_endpoints.py`, `tests/test_source_sampling.py`, others | Procedural, drawn in the test | Present. |
| Validation fixtures | `tests/fixtures/validation_contract/*.json` | Recorded results, no pixels | Present. |
| 0.4 geometry evidence (`artifacts/v04/geometry`, comparisons, plots, visual ledger) | Recovered delivery `243beee…` | Recorded runs | **Missing.** Not in the repo or the handoff pack. |
| Former final-12 tangency case `f_48d25a23fca95e80` | Sealed evaluator tree of 0.4 | Procedural, sealed generator | **Missing.** Its generator and reference are not on this machine, so the case cannot be reproduced. |
| Inherited authentic previews (Balclutha, Wapama, Monitor; 1,888,468 bytes) | `artifacts/v04/data/*_preview.png` in the recovered delivery | Authentic, public domain | **Missing.** Not downloaded (see section 6). |
| ALMA originals (6 files, 725,271,046 bytes) | Licensed, private inventory | Authentic | **Missing.** Not downloaded (too large; out of scope). |
| DTMB 5415 IGES | mathLab repository | Authentic CAD, rasterized for tests | Not present; not needed here. |

Conclusion: all measurements below use procedural drawings. There is no authentic drawing with
geometric truth on this machine, and none exists in the recorded inventory.

Development set used for every hypothesis (38 drawings): roundflare seeds 271003…271097 in
`drafting` and `degraded`, multichine seeds 241001…241067 in `drafting` (and three in `degraded`),
`development_wigley` 17/23/41 `clean` and 17/41 `degraded`. All 15 `degraded` drawings are
unresolved by the source catalog (no unique candidate), before and after every change. That is a
recorded abstention, not a measurement.

## 2. Instruments

- Native probe: `benchmarks/source_fidelity_probe.py` (fresh task, inspection, selection, native CAD,
  STEP export, validation). Comparator: `benchmarks/source_fidelity_compare.py` (independent STEP
  reimport and section cuts at 4,097 heights).
- Fast probe (no CAD, same selection policies as the native probe): `inspect_source_worker` →
  policy choice → `extract_sections`. The evaluator then reads the reference.
- Two references, both evaluator-only, at 4,097 heights per section:
  - **analytic**: `procedural_sections(seed, family, samples=4097)`;
  - **drawn**: the 129-vertex polyline that `generate.py` actually draws (`ground_truth.json`).
    This is the shape information that is present in the image.
- Policies: `deterministic` (the Rust deterministic policy: `grid_evidence.unique_non_grid_candidate_id`),
  `centroid` (row-centroid candidate) and `endpoint` (the 0.4 endpoint-contact alternative).
- Pixel gates for reference (unchanged, from the 0.4 evaluation): RMS 2 px, local maximum 4 px,
  volume 3 %. Raw trace-to-STEP audit: 1.1 mm.

## 3. Reproduction at the current code (`77dc6a8`)

### Known-47 roundflare `holdout_roundflare-271097-drafting`

| Run | STEP SHA-256 (prefix) | Volume error | Max ordinate error (analytic, 4,097 heights) | RMS | Where |
|---|---|---:|---:|---:|---|
| centroid / deterministic | `d603109c2b764562` | 0.6283 % | **1.302507 m (54.50 px)** | 0.040866 m | `frame-08`, z = 0 |
| endpoint alternative | `72983b56b3ee9ad8` | 0.7367 % | 0.432197 m (18.08 px) | 0.033298 m | `frame-12`, z = 0.18 px |

Both reproduce the 0.4 record: 1.302507 m centroid endpoint error and 0.7367 % endpoint volume error.
Against the drawn polyline the endpoint run has a maximum of **3.73 px = 0.089 m**. That equals the
0.4 value 0.089033 m, so the 0.4 figure was measured against the 129 drawn vertices, not the
analytic curve. All 4,097 ordinates resolved at the three cuts (`frame-00`, `frame-08`, `frame-24`).
Both STEPs are valid single solids; validation status `validated_review_required`.

The first endpoint native build timed out at 180 s while another probe ran at the same time. A
repeat without concurrent load completed in 136.5 s. Both attempts are retained under
`/tmp/mf-v05/rf-base-endpoint*` during this session only.

### Raw terminal-spur audit

`holdout_multichine-241001-drafting` (deterministic policy) reproduces the mechanism: the terminal
stations `frame-00` and `frame-24` have y = 0 at z = 0, 0.0216, 0.0433 and 0.0512 m (the 0.4 text
lists the first three values). The current audit reports **51.164 mm** at both terminal stations
against the unchanged 1.1 mm gate: `validation_failed`, `geometry_checks_passed=false`. Interior
stations are 0.635–0.907 mm. The 0.4 figure 43.264475 mm equals two output-grid steps
(2 × 0.0216 m). The current output also has a zero ordinate at 0.0512 m (two source pixels), and
the measured distance equals that height. I did not establish which source version produced the
0.4 figure. The gate still fails. STEP SHA-256 prefix
`23c38066417f165d`.

### Former final-12 tangency gate

Not reproducible (section 1). Its recorded failure (105.006 mm at z = 0.0054 m, inside the first
source row, gate 66.667 mm) stays as recorded.

## 4. Images inspected

All images were opened and looked at in this session. Generated images live in the session scratch
directory; the hashes identify them.

| Image | SHA-256 | What I saw |
|---|---|---|
| Source crop, roundflare `frame-08`, x 972–1080, y 690–741, 9× nearest | `8077c5e1f882c01e5bdad73c9385a1b6f296d0aace9c89f41d629ccd22aeb850` | The dark hull stroke lies on the pale baseline ruler from the centreline to x ≈ 1026 on the boundary row (y = 732). Then it climbs in a one-pixel staircase: row 731 x 1026–1039, row 730 x 1039–1048, and so on. The boundary-row stroke and the pale ruler form one broad run. |
| STEP cuts over source, `frame-08`, 11× (centroid red, endpoint blue) | `8d3819b2b012d6d14ab2e20e79b790f1bb4a294584d4e7e762ccf23958fac80d` | The endpoint STEP follows the dark boundary-row ink from the centreline and then the staircase. The centroid STEP starts at x = 1032.5 on the boundary row, where there is only pale ruler; the dark ink between the centreline and x = 1026 is not covered. |
| Body view of the centroid STEP reimport (`render.png`, body) | `fdf3d1b6c7c1cb592186e3dc14fe36df009ef773fd306a1ffbcdd6e8bb05ae67` | The keel is a flat horizontal strip about 2.6 m wide at z = 0. Round sections that should meet the keel at a point end on this flat strip. |
| STEP cuts over source after H3, `frame-08`, 11× (base red, H3 blue) | `4c5cab29aef1a4f0ec0c8b49ba6781ba97c0c14709e9fbc04952913475077bb3` | The H3 STEP now meets the boundary row at x ≈ 1026, at the end of the dark boundary ink. The base STEP stops at 1032.5 above pale ruler only. The centreline-to-1026 ink is still not covered: that part is the unresolved tangency/flat-keel ambiguity. |
| STEP cut over source, multichine `frame-00`, x 42–72, y 360–386, 24× | `3e03d79eace60841763c1349299715c60341a31bc59e1196f3e2da61072d90ce` | The dark stroke is a two-pixel staircase that reaches the baseline on the centreline columns 47–48 over the lowest two rows. The independent STEP cut follows the ink and the centreline down to the baseline. The cut is within 1.45 px of the analytic curve at this station, yet the raw audit reports 51.164 mm for the same STEP. |

## 5. Hypotheses (one at a time)

Fast-probe numbers are over the 23 drawings that produce output (15 degraded drawings abstain
in every attempt). "px" is source pixels.

### H0 — The remaining endpoint-variant tangency error is in the source pixels (measurement, no code)

Falsifiable claim: the analytic-reference maximum of the endpoint variant (18.08 px) is larger than
the error of the drawn polyline itself. Result: the drawn 129-vertex polyline differs from the analytic
curve by **18.17 px** at `frame-12`, z = 0.16 px (271003: 14.11 px; 271049: 5.18 px; wigley-17:
6.41 px; multichine-241001: 0.34 px). The generator draws straight chords between vertices 0.83 px
apart in height; the analytic shape inside the first chord is not in the image. **Confirmed.** No
faithful source reading can pass a 4 px analytic gate at a sub-row tangency in these drawings. This
is very probably also the mechanism of the final-12 failure (error inside the first source row), but
that case cannot be checked here. The gate is not changed; this is documented as an instrument
limitation.

### H1 — Row-boundary crossings of a staircase stroke reduce tangency error (code, **reverted**)

Change: add a knot at the boundary between two observed adjacent rows when their unclipped
source runs touch (patch SHA-256 `83e16edce3e4d88976439a70c3f78c59efbe2b6d3826e2722609d3fad2087f5a`,
not kept).

| Policy / reference | Before mean RMS / worst max | After |
|---|---|---|
| deterministic / analytic | 1.145 / 54.50 px | 1.181 / 54.50 px |
| deterministic / drawn | 1.160 / 54.50 px | 1.201 / 54.50 px |
| endpoint / analytic | 1.143 / 18.08 px | 1.155 / 15.47 px |
| endpoint / drawn | 1.075 / 8.77 px | 1.136 / **18.72 px** |

Multichine RMS also worsened (241001: 0.926 → 0.977 px). The analytic maximum fell only because
the junction knot moves toward the analytic curve, away from the drawn chord. Against the image
content it is worse. **Falsified; reverted.**

### H2 — The deterministic policy should prefer the endpoint alternative (no code, **rejected**)

The grid-supported ranking sorts by `maximum_step_px_per_row`, which penalizes the endpoint
candidate for its witnessed boundary step. Preferring the endpoint would remove the 54.5 px defect
in the roundflare case. Falsification test: a procedural flat keel (40 px half-width) with a 60 px
bilge radius. The endpoint rule fires and gives y(0) = 1 px, an error of 39 px, while the centroid
gives 51.5 px. One boundary row cannot separate a tangent approach from a flat keel plate, so this
is a semantic choice that the source does not support. **Rejected.** Both candidates stay in the
catalog; the choice still needs review.

### H3 — An unobserved boundary ordinate must stay inside touching boundary-row ink (code, **kept**)

Cause found in pixels: on `frame-08` the lowest calibrated row has no trace observation (the dark
stroke shares one broad run with the pale ruler; the 0.4 contrast split keeps it as eligible ink, but
the tracer rejects runs wider than 16 % of the panel). Sampling then holds the row-731 centroid
(x = 1032.5) down to the boundary, where only pale ruler exists.

Change (`ingest.py`, `_lower_boundary_run_end`): when the trace has no observation on the boundary
row but the next row is observed, and exactly one run on the boundary row of the **unclipped**
eligible source mask touches the run of that lowest observation, the boundary ordinate is the
touching end of that run. A corridor cannot create or hide this run. The centroid interpretation is
kept (no centreline contact is claimed); the original lowest centroid is recorded in
`diagnostics.lower_boundary_run_end.lowest_centroid_local_px`. Candidate IDs and the catalog are
unchanged, because anchors still come from the trace.

Fast probe, 38 drawings: only `holdout_roundflare-271097-drafting` changed (all other outputs are
identical, including the endpoint variant everywhere).

| Native, 271097 centroid/deterministic | Before | After H3 |
|---|---:|---:|
| STEP SHA-256 prefix | `d603109c2b764562` | `f27cff6c7f148675` |
| Max ordinate error (analytic) | 1.302507 m (54.50 px) | **1.147162 m (48.00 px)** |
| Max ordinate error (drawn) | 54.50 px | 48.00 px |
| Ordinate RMS | 0.040866 m | 0.036084 m |
| `frame-08` cut RMS | 0.052052 m | 0.044289 m |
| Volume error | 0.6283 % | 0.6390 % (slightly worse) |
| Trace-to-STEP audit | passed (max 0.856 mm) | passed (max 0.856 mm) |
| 4 px local gate | FAIL | **FAIL** |

The flat-keel control is not changed by H3 (y(0) stays 51.5 px). **Kept** as a narrow, measured
improvement. It does not pass any documented gate.

Tests: `tests/test_source_boundary_run.py` (3 tests, deterministic, no network): the boundary
ordinate equals the last dark boundary-row pixel and lies inside boundary ink where the old value
lay beyond it; no record without contrast-separated boundary ink; the touching rule refuses
separated runs, two touching runs and an observed boundary row.

### H4 — Terminal spur fixable in source processing (no code, **rejected**)

Pixels show the hull stroke on the centreline columns for the lowest two rows; the analytic
half-breadth there is 0.4–0.8 px. y = 0 is an honest measurement within the 0.75 px uncertainty.
Removing the spur in source processing would need either invented breadth or a changed z range;
both are forbidden. The STEP cut follows the ink and is within 1.45 px of the analytic curve, while
the raw audit reports 51.164 mm. The conflict is between a zero-width raw trace and a material
boundary, inside the validation definition (`validation_contract.py`, not changed). A separately
versioned material-boundary metric that keeps the raw score is still needed; this is a gate-definition
question for the validation owner.

## 6. Result

- Documented failing gates, unchanged gates: **none now passes.** Tangency (final-12): not
  reproducible here. Known-47 centroid local error: 1.302507 → 1.147162 m, still above 4 px.
  Raw terminal spur: 51.164 mm vs 1.1 mm, FAIL.
- Main finding: in these procedural drawings the sub-row tangency error is mainly generator chord
  error that is absent from the pixels (H0), plus a semantic ambiguity that one boundary row cannot
  resolve (H2). More source processing alone will not pass an analytic 4 px gate there.
- Data needed next (not downloaded):
  - The sealed final-12 generator/reference for `f_48d25a23fca95e80` from the recovered 0.4 delivery
    (`artifacts/v04/geometry`, part of the 552 MB evidence archive), to test H0 on that case.
  - Small public-domain authentic sheets for line-identity work, with recorded hashes in the private
    inventory: `monitor_nh50954` (153,224 bytes), `wapama_ca67_s5` (748,682 bytes),
    `balclutha_ca54_s48` (1,201,246 bytes), `balclutha_ca54_s7` (1,337,872 bytes). They have no
    geometric truth, so they can test identity and abstention only, not accuracy.
  - Reviewed calibration and line labels on any authentic sheet; there are still zero.

## 7. Verification (final code)

- Python: `pytest -q` 515 passed (includes the 3 new tests).
- Rust: `MARINAFRAME_TEST_PYTHON=… cargo test --locked --workspace --no-fail-fast` 157 passed,
  1 ignored. A first run had 3 `finalization_guards` failures with `worker_implementation_changed`,
  because `ingest.py` was edited while that run was in progress; the rerun on unchanged files passed.
- Deterministic smoke (`examples/make_agent_example.py` → `marinaframe run --policy deterministic`
  → `verify`): `awaiting_human_review`, `valid: true`, `engineering_approved: false`.
- `scripts/scan_secrets.py`: 0 findings.

## 8. Authentic line identity and abstention (second pass, 2026-11-07)

Base: `333f371`. Same method as sections 2–5: one hypothesis at a time, inspect the pixels, keep
or revert. **These sheets have no reviewed truth.** The coding assistant read every calibration
value below from visible marks. All values are **provisional** (not gold, not reviewed). The
results are line-identity and abstention evidence only. No accuracy figure is claimed. No image,
crop or derivative is committed. No image was sent to any provider.

### 8.1 Inputs

The full sheets exceed the source policy (16 Mpx, 128 MB decoded). HAER TIFFs are 1-bit 400 dpi
(139–239 Mpx). ALMA TIFFs are RGB 300 dpi (78 Mpx). The person-supplied input is therefore the
whole sheet, box-averaged by an integer factor (Pillow `Image.reduce`), in greyscale. All
coordinates below are derivative pixels (= full-sheet pixels / factor).

| Sheet (source SHA-256 prefix) | Content | Derivative (factor, size, SHA-256 prefix) |
|---|---|---|
| Balclutha CA-54 s48 (`4e6344f077c9`) | Structural section at frame 108, metre bar | ×4, 2408×3609, `33e6e612b115` |
| Balclutha CA-54 s7 (`32f09c60a39d`) | Body plan (stations 0–20 overlaid), hull measurement table | ×4, 2408×3611, `1f6c4c5cd172` |
| Wapama CA-67 s5 (`5c774e860309`) | As-is body plans, stations 0–5 and 5–10, port and starboard | ×4, 3400×4400, `7f0defdb91ac` |
| Monitor NH50954 (`a7238e16043c`) | General plan: inboard profile, deck plan, two small inboard sections | none (no spec possible) |
| ALMA sheet 4 (`2365ec63c8fc`) | Cross sections A-A, B-B, C-C (structural), scale bars | ×3, 3592×2419, `1847e066d39d` |
| ALMA lines (`b7423f85d547`) | Body plan (labelled "half breadth view"), profile, plan, offsets table | ×3, 3584×2422, `d8e52523abd3` |

Monitor: the scale note under "GENERAL PLAN" cannot be read at 1200×431 px. The two transverse
views are inboard sections about 55 px high and full of machinery. **No provisional spec was
made.** This sheet is not a lines or section drawing in the supported sense. ALMA sheets 1–3 and
the cover were not processed (sail plan, deck/outboard and hold/inboard profiles: no section
panels).

### 8.2 Provisional specs (assistant-read; `x_m` is a station ordinal, not metres)

| Section | ROI px | Centreline px | Datum px | px/m | z range m | Where each value comes from |
|---|---|---:|---:|---:|---|---|
| s48 `frame-108` | 1195,860,2070,2605 | 1204.75 | 2601 | 163.0 | 0–10.6196 | metre bar 0 m @389, 10 m @2019; mid of keel sides 1198/1211.5; **datum = keel bottom ink, no baseline is drawn** |
| s48 `frame-108-lower` | 1195,1940,2070,2605 | 1204.75 | 2601 | 163.0 | 0–4.0 | same; panel below the hatched orlop deck |
| s7 `forebody-half-st11-20` | 1200,650,1975,1725 | 1206 | 1714.4 | 122.87 | 0–8.5344 | waterline grid, base row 1714.4 to 32 ft row 516 (metre bar gives 122.75); centre line between keel-box sides |
| s7 `forebody-band-16-28ft` | same | 1206 | 1714.4 | 122.87 | 4.8768–8.5344 | same |
| Wapama `port-half-st0-5` / `-st5-10` | 1690,1300,2720,2172 / 1690,2800,2720,3672 | 1699.5 | 2162.5 / 3662.5 | 164.04 | 0–5.1816 | 2 ft grid = 100 px (metre bar 164.0); BASE rows; the right half is the **port** side |
| Wapama `port-side-band-st0-5` / `-st5-10` | same | 1699.5 | same | 164.04 | 2.7432–5.1816 | 9 ft WL to 17 ft WL |
| ALMA `midship-AA-to-deck` / `-to-rail` | 1250,1510,2160,1960 / 1250,1405,2160,1960 | 1258.5 | 1951.6 | 246.7 | 0–1.7491 / 0–2.1751 | A-A scale bar 0 ft @1417.6, 15 ft @2545.6; "C of vessel" line; line labelled BASE LINE |
| ALMA `body-right-half` | 1945,580,2560,840 | 1955.5 | 833 | 164.2 | 0.1218–1.4799 | plan-view station spacing 4→12 = 40 ft over 2002 px, **assumed** equal in the body plan; datum = unlabelled line under the body plan |

Gaps recorded, not invented: station positions in metres (all sheets except the ALMA plan view);
the Balclutha s48 baseline; the s7 aft half (drawn left of the centreline: MarinaFrame traces only
the right side, and no mirrored derivative was made); Wapama port/starboard distortion (the sheet
says that the sides differ). One source-internal check (ALMA): the section bottom is 20 px =
4.8 in above the assumed baseline. The offsets table, as transcribed by the assistant, gives chine
height 0-5-0 amidships. This supports the datum reading only. It is not reviewed truth.

### 8.3 Results

Deterministic policy = Rust `controller.rs`: the grid-unique ID, else the only selectable
candidate, else abstain. Instrument: `inspect_source_worker` plus `extract_sections`, no CAD.
Every section has the same result before and after the kept changes, except the s7 abstention
reason (H5).

| Section | Baseline engine | Competing sustained strokes | Catalog candidates | Lattice | Deterministic | Visible hull line, and what confuses the trace |
|---|---|---:|---:|---|---|---|
| s48 `frame-108` | abstain `resource_limit` | – | 0 | no | abstain | Outer shell from keel to deck edge. One row has 89 runs: deck-plank hatching, berths, bins, lettering, ceiling and frame lines parallel to the shell, the drawn waterline. |
| s48 `frame-108-lower` | abstain `ambiguous_curve` | 4 | 0 | no | abstain | The trace follows the outer shell for most rows. It leaves the shell at the bilge-stringer bracket and at the "Sister Keelson" and "Floor" leaders that touch the shell, so it cannot be a corridor. Inner shell, frame and ceiling lines are the competitors. |
| s7 `forebody-half-st11-20` | abstain; before `resource_limit`, after **`ambiguous_curve`** | 5 | 0 | no | abstain | Ten forebody stations overlaid; the ROI isolates none. The trace hops between stations 11½–15, buttock verticals, station numerals and waterline crossings. |
| s7 `forebody-band-16-28ft` | abstain `ambiguous_curve` | 11 | 0 | no | abstain | As above; the trace follows the numerals "15", "14", "13", "12½". |
| Wapama `port-half-st0-5` | abstain `ambiguous_curve` | 2 | 0 | no | abstain | The trace follows the outermost stations (4/5) to the bilge. Then it leaves the floor for a 2 ft grid line, "DIAGONAL B/C" lettering and the 12'-6⅜" dimension text. |
| Wapama `port-half-st5-10` | abstain `ambiguous_curve` | 1 (one linked component across the panel) | 0 | no | abstain | Same pattern: outer stations 5/6/7 at the side, then lettering and diagonals. |
| Wapama `port-side-band-st5-10` | abstain `ambiguous_curve` | 2 | 2 | no | abstain | Stations 5, 6 and 7 run 3–5 px apart at the side. Candidate 1 follows the outermost strand. Candidate 2 changes to an inner strand and back (14 px/row step). The panel does not show which station either one is. |
| Wapama `port-side-band-st0-5` | abstain `ambiguous_curve` | 1 | 2 | **yes** | abstain | Outer stations at the side; both candidates have a non-grid competitor. |
| ALMA `midship-AA-to-deck`, `-to-rail` | abstain `resource_limit` | – | 0 | no | abstain | Outer side planking and flat bottom planking. Wood-grain hatching in every timber, dimensions, lettering, rub rails, frames and ceiling. |
| ALMA `body-right-half` | abstain `ambiguous_curve` | 2 | 3 | no | abstain | Two overlaid end sections on one flat bottom: a vertical slab side and a raked side. Candidate 1 = vertical side, candidate 3 = raked side, candidate 2 jumps between them. The stem/centreboard rectangle next to the centreline is a further competitor. |

Counts over 14 authentic sections, before → after: chosen-and-plausible **0 → 0**; abstained
**14 → 14**; chosen-but-visibly-wrong **0 → 0**. Every abstention is on a panel that is
ambiguous in the pixels (overlaid stations, or a structural section with several lines parallel
to the shell). The Wapama 2 ft grid is mostly not detected as a lattice, because the 3 ft base
interval and the keel box make it irregular. This changes no choice here: the station curves are
non-grid competitors.

The catalog was empty on 9 of 14 sections. Before H6 the inspection gave no reason for this.

Images opened and inspected (SHA-256 prefix; work directory only): overlays s48 `52b968c8b19bb720`,
s48-lower `24849f0f6a0b9833`, s7 `8fe676de48c99011`, s7-band `b72d920f93f6f0a9`, Wapama
`2426b8fced4746e0` / `e6bb44790944c58b` / `68dd5db6003c6d37`, ALMA A-A `8db3cba3025f1adc`,
ALMA body `be2aa56c1e924f1f`; trace debug views `8b75067d5f2512dc` (s48-lower), `052c3b1139776a2a`
and `906e9f9bbd52b4f8` (s7), `6cebc462a3d07402` and `e5c2dd0c3dce25de` (Wapama); candidate zooms
`64607256ce15b901` (Wapama side band), `46d2607501fc5ef0` (ALMA body); waterline texture
`081936b8206603a0`.

### 8.4 Hypotheses

**H5 — Contrast islands inside a scanned 1-bit ruler are tone texture, not strokes (code, kept).**
Pixels (s7, row 1413, x 1490–1680, 7×): the 8 ft waterline has a dark core row and a pale aliased
fringe with dark specks. `_contrasting_subruns` kept each speck as a separate observation. That
row had 65 trace runs, and the panel was refused as `resource_limit` ("select a smaller panel"),
not on its strokes.

- First form (H5a, **reverted**): retain a contrast island only when ink outside every broad run
  touches it in the row above or below. Falsification test: the procedural fingerprint (8.5).
  Result: 12 sections of 4 degraded roundflare drawings changed their candidate catalogs, and
  `holdout_roundflare-271067-degraded` `frame-17` changed its deterministic choice. Against the
  drawn polyline (evaluator only) the new choice was worse: maximum horizontal error 20.00 →
  27.48 px at the boundary row. Pixels (10× crop x 660–760, rows 1405–1438; images
  `76274aadf0542027` before, `1e42a5728124652a` after): the dark stroke runs along a two-row
  ruler before it climbs away. The lower island touches only the upper ruler row, so H5a removed
  real stroke ink.
- Second form (H5b, **kept**): support starts at ink outside every broad run and grows, row by
  row, through accepted islands in adjacent rows. A stroke that crosses, leaves or runs along a
  ruler stays connected; tone specks in an aliased line edge are never reached. Result: frame-17
  is identical to `333f371` again (same candidates, same choice, same 20.00 px). s7 now abstains
  as `ambiguous_curve` with 5 sustained competitors (124 and 221 unsupported islands in its two
  panels). All other authentic results are unchanged. s48 is still over the run budget because
  of hatching.

Tests: `tests/test_source_ruler_texture.py` (4 synthetic tests). The 3 texture tests fail on
`333f371`; the thick-ruler test fails on H5a.

**H6 — An empty catalog must state why (disclosure only, kept).** Pixels (Wapama, s7, s48-lower,
ALMA A-A): every rejected trace hops between strokes. Change (`agent_tools.py`): each traced
interpretation that does not enter the catalog is listed in `rejected_trace_hypotheses`, with its
reason (`not_representable_as_bounded_corridor`, `insufficient_row_coverage`, or the trace
refusal kind), row coverage and maximum step. Candidates, IDs and the choice do not change. Test:
`tests/test_inspection_rejections.py` (synthetic hopping strokes).

**H7 — The sole-candidate fallback can choose a contested trace (finding, no change).** The Rust
deterministic policy selects the only selectable candidate, also when that candidate has non-grid
competitors and the baseline engine abstained as `ambiguous_curve`. On these sheets no section
had exactly one candidate (0, 2 or 3), so the fallback did not fire. A panel that admits one
smooth trace among overlaid curves would be chosen. The fix belongs in `rust-control` (outside
this task): for example, require `non_grid_competing_components == 0` for the fallback. Python
cannot prevent it without making candidates unselectable for explicit human selection, which
would be wrong.

**H8 — Raise the 64-run row budget for structural sections (rejected, no code).** s48 and ALMA
A-A still refuse because of hatching. A larger budget would only reach `ambiguous_curve` on the
same panels (s48-lower already shows 4 competitors). It widens a resource bound for no identity
gain.

### 8.5 Procedural regression

Instrument (work directory, not committed): for each drawing, `extract_sections`, then
`inspect_source_worker`, then the Rust-equivalent deterministic choice, then `extract_sections`
with the chosen candidate's contour selection. The fingerprint records, per section, the catalog
candidate IDs, the choice, the gap kind and a SHA-256 of the measured points. Set: 45 drawings
(roundflare 271003…271097 and multichine 241001…241067, each `drafting` and `degraded`;
`development_wigley` 17/23/41 `clean` and 17/41 `degraded`; a superset of the 38 in section 1)
plus the agent example and its ambiguous variant. The drawings are generated as
`benchmarks/make_suite.py` does (`vessel_id` = case name); the known-47 drawing has SHA-256
`04a2c841…`, as in section 1.

| Class | Sections | Chosen and measured (`333f371`) | After H5b + H6 |
|---|---:|---:|---:|
| clean | 75 | 75 | identical |
| drafting | 500 | 500 | identical |
| degraded | 550 | 189 | identical |
| agent example / ambiguous | 3 / 3 | 3 / 0 | identical |

Result: **0 of 1,131 sections differ** in candidates, choice, gap or measured points of the chosen
candidate. H5a (reverted) changed 12 degraded sections and 1 choice (see H5 above). The
earlier native measurements in sections 3–5 therefore still apply unchanged.

### 8.6 What a human expert must supply next

- For each body plan: which drawn curve is which station (one contour selection per station), and
  the station positions in metres (Balclutha sheet 3; Wapama sheets 2–4 and 10).
- For structural sections: which line is the hull line to measure (shell outer, shell inner or
  frame line), and the datum (Balclutha s48 has no baseline).
- Review of every provisional value in 8.2, in particular the ALMA body-plan scale assumption.
- Reviewed transcriptions of the Balclutha and ALMA offsets tables. These could then serve as an
  independent check of a selected station curve.
- A decision on H7 by the Rust owner.

### 8.7 Verification (final code)

- Python: `pytest -q` 520 passed (includes 5 new tests in `tests/test_source_ruler_texture.py`
  and `tests/test_inspection_rejections.py`).
- Rust: `MARINAFRAME_TEST_PYTHON=… cargo test --locked --workspace --no-fail-fast` 188 passed,
  1 ignored. No Python source was edited while it ran.
- Deterministic smoke (`examples/make_agent_example.py` → `marinaframe run --policy deterministic`
  → `verify`): `awaiting_human_review`, `valid: true`, `engineering_approved: false`.
- Procedural fingerprint: 0 of 1,131 sections differ (8.5).
- `scripts/scan_secrets.py`: 0 findings. `git status` shows no drawing or derivative.
