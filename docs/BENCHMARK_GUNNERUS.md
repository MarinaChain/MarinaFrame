# Gunnerus real-ship hull benchmark (W1)

Date: 2026-11-07. Base: `2e30c6f` (branch `continue/v0.5`). Host: macOS arm64, Python 3.12,
CadQuery 2.7.0, OCP (OpenCascade). This is the first comparison of MarinaFrame hull output with
a real ship's true CAD model. Every candidate keeps `engineering_approved=false`.

Sections 1-5 were written and committed **before any Gunnerus run**. Section 6 records the runs.

## 1. Question and protocol

How close is a MarinaFrame hull, made from the R/V Gunnerus lines plan, to the hull in the
C-JOB 3D model? Two input paths are scored separately:

| Path | Input | Stages measured |
|---|---|---|
| (a) Vector | `polarkonsult/Lines Plan Rev0.dxf`, body plan station curves | Station reading from vector data, `geometry.build_hull` (ruled loft, flat terminal caps) |
| (b) Raster | `polarkonsult/Lines Plan Rev0.pdf`, body plan rendered at 500 dpi | Full product: provisional spec, Rust controller, deterministic policy, raster tracing, CAD |

Rules followed:

1. Metrics first (this file). 2. Development only on DTMB 5415 (SIMMAN) and procedural cases;
Gunnerus is sealed. 3. Freeze: all code and configuration committed, commit SHA recorded,
then one run per path. 4. Every run is recorded, including failures and abstentions. No code
change after a Gunnerus result; a bug found then is recorded, fixed in a new commit, and both
runs are reported. 5. Drawings, renders, truth data and overlays stay in the git-ignored
`work/` folder; only hashes enter this file. Nothing is sent to any provider.

Licence: shiplab/gunnerus is CC BY-NC 4.0 (sheets: non-commercial research and teaching).

## 2. Truth extraction

| Item | Value |
|---|---|
| Truth file | `extended/CJOB/3d models/Gunnerus 3D Model STEP Rev0.stp` (shiplab/gunnerus `8cd4683`) |
| SHA-256 / bytes | `297a35c99551efc054a651b08413b1e1bac3e2b34c747e7260ab3a3f1fc91d9e` / 762,726,813 |
| Content | One product, one `MANIFOLD_SOLID_BREP`, 1 closed shell, 145 faces (120 B-spline, 23 planes, 2 cylinders), 8.15 M control points |
| Load | `benchmarks/gunnerus/load_truth_step.py`: STEP read once (235 s), cached as binary BRep `work/gunnerus/truth/truth_hull.brep` (SHA-256 `e4fd7df1…6ea6e`) |
| Extent (m) | x −1.150 … 34.549, y ±4.813, z −0.547 … 6.622 |
| Solid volume (OpenCascade) | 1302.28 m³ (whole closed hull, up to its top) |
| Reduced form | `truth_cache.py`: tessellation with 0.5 mm chord deflection (820,768 triangles), then plane cuts x = −1.20 … 35.40 m every 0.05 m (733 cuts). Stored as `truth_sections.npz` (SHA-256 `2aeb1253…cb090`). Direct B-spline plane sections were too slow (> 7 min CPU for the first cut). |
| Mesh check | Mesh volume 1303.86 m³, +0.12 % against the OpenCascade solid volume. This is the stated truth uncertainty for volumes. |

**Datum rule (fixed before any run):** truth coordinates = STEP millimetres / 1000, used as is:
x forward from frame 0 (AP), y from the centreline, z from the baseline. Drawing coordinates use
the same datum (frame 0 from the profile grid, BASELINE, CL). No alignment is fitted.
Known differences seen only in extents before the runs: STEP half-breadth 4.813 m vs the drawn
moulded 4.800 m (+13 mm, probably plating outside the moulded line); STEP keel/skeg bottom
−0.547 m vs drawn −0.532 m; STEP forward end 34.55 m vs drawn stem 35.29 m (buttock) and
frame 60 at 35.0 m; STEP aft end −1.15 m vs drawn waterline end −1.0 m. These differences are
not corrected. They enter the errors.

## 3. Metric definitions

All lengths in metres, areas in m², volumes in m³. Implementation: `benchmarks/gunnerus/hull_metrics.py`
and `score.py`. Truth and reconstruction are measured the same way: both are triangle meshes
(reconstruction meshed at 0.1 mm), cut by planes x = const, and evaluated on one height grid
z = −0.600 … 7.600 m in 5 mm steps.

- **Outer half-breadth** hb(x, z): the largest |y| where the cut at x crosses height z; 0 where
  the cut does not reach z. For an appendage below the hull (skeg), hb is the skeg's outer edge.
- **Per-station half-breadth error**, at every station that the path read: e(z) = hb_recon − hb_truth
  on the grid, reported as RMS, maximum |e|, the z of the maximum and its sign, in two bands:
  - *main*: from the lowest truth point of that station to z = 4.287 m (depth to 1-deck);
  - *below draft*: from the lowest truth point to z = 2.50 m (normal operating draught).
  A reconstruction that does not reach a height counts as hb = 0 there (coverage error).
  The summary gives the RMS over stations of the station RMS, the median station RMS and the
  maximum |e| over all stations.
- **Between-station half-breadth error**: the same main-band RMS and maximum at every 5th truth
  cut (0.25 m spacing) strictly inside the reconstructed x range. This includes loft error.
- **Section area error** at each read station: area below z = 2.50 m (even-odd rule on the cut),
  reconstruction minus truth, absolute and relative.
- **Displacement volume and waterplane area at the design draft** T = 2.50 m: section areas below
  T (and widths at T) integrated over x with the trapezoid rule on the same x grid for both:
  - *full*: against the whole truth hull;
  - *within range*: against the truth between the first and last reconstructed station.
  Volumes are moulded-envelope volumes, not displacement in tonnes.
- **Abstentions**: every station that a path did not read is listed with its reason. A path that
  builds no model has no geometric score; this is a result, not a missing value.

## 4. Inputs, read before any run

All values below were read from the drawing by an assistant (`make_gunnerus_configs.py`) and are
provisional. No truth data enter them.

**Body plan (DXF, layer `03_Lines_Frames1`):** centreline X = 58433.8, baseline Y = 25121.5
(WL 250 grid at 25371.5), 1000 units per metre (BT grid 500 units apart), side lines at
53633.8 / 63233.8 (y = 4.800 m), top of station curves Y = 32708 (z = 7.5865 m). Station curves
that end on the vertical side line follow it to that top (declared wall-side reading).

**Frame positions:** from the profile grid ticks and labels: frame n at 0.5 n m (n ≤ 27),
A–J at 14.0–18.5 m, frame n ≥ 28 at 0.5 (n + 10) m.

**Station identity rules** (full text in `make_gunnerus_configs.py`): forward straight keel by
the keel rake anchored on labels #40/#45/#50 (17.47 units per frame, label #45 agrees within
1.5 %); stem and upper bow pieces by order anchored on #55/#58 and #55/#60; aft body by order
anchored on #0/#5/#10/#15/#20. Labelling convention: a label is written just above its curve;
the labels with independent identity (#40, #45, #50, #58, #60, upper #55) all follow it, and it
resolves the aft labels, which otherwise fit two orderings one frame apart.

**Station list (59):** frames −2 … 20 (aft), H, I, J, 28 … 60 (forward). Not identified (14):
frames 21–27 and A–G: their keel heights converge and no label anchors them. Rejected: one
forward curve whose keel height is 0.48 frame from any whole frame.

**Raster calibration** (500 dpi render of the PDF clip 1950, 790, 2450, 1290 pt): BT −4500 /
+4500 at columns 328 / 3182, WL 7500 / WL 250 at rows 376 / 2675, so 317.1 px/m in both
directions; centreline column 1755.5; baseline row 2754.28 (WL 250 + 0.25 m). The printed sheet is not at 1:100 of
A0 (that would be 196.9 px/m at 500 dpi), so scale is read from the grid. The aft half is
mirrored into a second panel; every station panel is the whole half body plan; z range
0.0 … 7.5 m. The raster spec uses the same 59 stations and positions as the vector path.

**Expectations stated before the runs** (from the drawing and the development runs below):
aft frames 5–20 cross a twin skeg, so their curves are not single-valued in height and the
vector reader will refuse them; frames 55–58 are drawn as separate bulb and bow pieces and will
be refused; the vector loft will therefore span the skeg region from about frame 4 to frame H
(x 2.0 → 17.5 m), and its between-station and volume errors there will be large. The raster path
is expected to abstain: in development the deterministic policy abstained on every body plan
with a black centreline or grid (section 5).

## 5. Development results (DTMB 5415, never Gunnerus)

Truth: SIMMAN 5415 IGES (FORCE/IIHR/INSEAN, model scale, LPP 5.72 m, x aft from the FP),
SHA-256 `dac17b47…bbc28`, 3 faces, exact plane sections every 0.0286 m. Draft 0.248 m;
main band to z = 0.40 m. Values in model-scale metres.

| Case | Stations read | Station hb RMS (median) | Station hb max | Between-station RMS / max | Volume error full / in range | Waterplane error full / in range |
|---|---:|---:|---:|---:|---:|---:|
| Synthetic DXF cut from the truth (identity exact) | 20 of 21 (FP: 2 curves) | 0.39 mm (0.40) | 0.99 mm | 10.9 / 125 mm | −0.25 % / +0.42 % | −2.34 % / +1.58 % |
| MARIN 5415 lines DXF (full scale, scaled 1:24.824), **oracle identity** | 13 of 15 identified (2 ambiguous picks) | 1.78 mm (1.85) | 14.1 mm | 5.5 / 36 mm | −3.25 % / +1.20 % | −5.35 % / +0.65 % |

The synthetic case checks the reader, the loft and the scorer: station errors stay inside the
1 mm CAD approximation bound. The between-station maximum (125 mm) is the ruled loft near the
sonar dome. The MARIN case measures a real lines drawing against independent CAD, with station
identity taken from the truth (oracle), so it is not an identity test. At ship scale its station
RMS is about 44 mm.

Raster development (5415 stations drawn into a PDF at 1:5, processed by `raster_path.py` and the
Rust controller, deterministic policy, commit of this file):

| Drawing | Outcome | Reason recorded by the product |
|---|---|---|
| 2 stations, black BT/WL grid | abstained | centreline stroke and a BT grid line retained as alternative contours; the hull curve rejected for row coverage 0.54 |
| 2 stations, centreline and baseline only | abstained | the centreline stroke is a second sustained candidate (forward panel); two hypotheses (aft panel) |
| 20 stations, black grid (crowded) | abstained | 12 sections inspected, 1–2 candidates each |

These runs confirmed the composite layout and calibration: the product's grid detector found the
0.1 m lattice at 236 px spacing and the declared centrelines at both panels. They also show that
the deterministic raster path does not resolve contour identity on lines-plan body plans.

## 6. Gunnerus runs

Frozen commit: **`399e071`** (metrics, configuration rules and both paths). Every run is listed.
Runs 2–4 of the vector path follow code fixes made **after** a failure that produced no geometry
and no score, so no Gunnerus truth comparison was seen before any fix. Outputs are in
`work/gunnerus/runs/` (not tracked). Truth sections SHA-256 `2aeb1253…cb090` in every run.

### 6.1 Run ledger

| Run | Path | Commit | Outcome | Record SHA-256 |
|---|---|---|---|---|
| V1 | vector | `399e071` | **blocked**: 31 of 59 stations read; `build_hull` refused, 1983 common knots > 513 at the 1 mm bound | `3c4458fb…` |
| R1 | raster | `399e071` | **abstained**: controller `inspection_worker_failed`, worker state `resource_limited` (48 s) on the first batch of 12 sections; 10 partial inspection records, each with 0 selectable candidates and 8 retained competitors; no model | `6d911e77…` |
| V2 | vector | `640ab57` (fix: try CAD bounds 1, 2, 5, 10 mm) | **blocked**: 617 knots > 513 even at 10 mm | `bae78724…` |
| V3 | vector | `96c9fb8` (fix: split the loft into station groups that fit, as the build error advises) | **failed in scoring**: model built (5 groups, all at 1 mm); the scorer raised on an empty height band at frame 59; no score written | `ee44aa7e…` |
| V4 | vector | `1cc64ed` (fix: an empty band is recorded as null) | **scored** | `c92d96d4…` |

The raster path was not run again: no fix touched it. Its single run stands.

### 6.2 Vector path result (V4)

Stations: 59 requested, **31 read**, 28 refused: 23 `multi_valued_section` (frames −1, 0, 1,
3–5, 7–20: twin-skeg loops; frames 45, 46, 53: height reverses on the picked curve, cause not yet inspected),
1 `incomplete_curve` (frame 6, split at a skeg junction), 4 `multiple_pieces` (frames 55–58,
bulb and bow drawn apart). 14 frames (21–27, A–G) were not identified. Read stations: −2, 2,
H, I, J, 28–44, 47–52, 54, 59, 60. The loft spans x = −1.0 … 35.0 m in 5 groups at the 1 mm
CAD bound (largest CAD deviation 0.999 mm). Model SHA-256 `745189351a17…`, score SHA-256
`16bff4a7e61b…`, comparison plot SHA-256 `47d48793fe79…`.

| Metric | Value |
|---|---|
| Station half-breadth, main band (to 4.287 m), 30 stations: RMS of station RMS / median station RMS / max | 0.403 m / **0.024 m** / 4.80 m |
| Same, below draft (to 2.50 m): RMS / median / max | 0.232 m / **0.033 m** / 2.20 m |
| Section area below 2.50 m, 29 stations: mean / max relative error | 3.0 % / 24.4 % |
| Between-station half-breadth, 143 cuts every 0.25 m: RMS / max (at x) | 1.357 m / 4.80 m (x = 15.3 m) |
| Volume below T = 2.50 m: truth / reconstruction | 486.3 m³ / 402.1 m³ |
| Volume error, full / within range | **−17.3 %** / −17.3 % |
| Waterplane area at 2.50 m: truth / reconstruction | 279.4 m² / 276.8 m² |
| Waterplane error, full / within range | **−0.92 %** / −0.66 % |

Per-station main-band RMS (mm): H 63, I 70, J 69, 28 72, 29 48, 30 31, 31–40 19–25, 41–43 30–35,
44 21, 47–51 13–18, 52 358, 54 279, −2 1585, 2 1458. Frames 59 and 60 have no truth below
4.287 m (frame 60, x = 35.0 m, lies forward of the STEP hull).

### 6.3 What the comparison plots and overlays show

- **Forward body and midbody (frames H–51, x 17.5–30.5 m):** the read station curves lie on the
  truth sections. Station RMS 13–72 mm; section area errors −0.7 % … +1.9 %. The station maximum
  (110–260 mm) sits 0.08–0.42 m above the baseline, just above the keel, where the bottom line is nearly horizontal.
  There a small height difference gives a large half-breadth difference, so this maximum is
  mostly a bottom-height offset of a few centimetres, not a breadth error.
- **Frames 52 and 54:** the truth has a horizontal slot at z ≈ 1.9–2.1 m (most likely the bow
  thruster tunnel). The lines plan has no tunnel. This gives the 1.1–1.4 m maxima.
- **Aft frames −2 and 2:** the truth hull ends at about z = 4.1 m (aft deck) and has a step at
  z = 2.0 m. The reconstruction follows the side line up to 7.59 m, as declared in section 4.
  The side-line rule came from the forward body and is wrong aft. This gives the 4.8 m maxima.
- **Skeg region (x ≈ 1 … 17.5 m):** no station is read between frame 2 and frame H, so the
  loft is one ruled span of 16.5 m across the twin skegs and the run of the hull. This is the
  main cause of the −17.3 % volume error and of the 4.8 m between-station maximum at x = 15.3 m.
- **Raster:** `calibration_check.png` (SHA-256 `a73b59d0…`) shows the declared centreline,
  baseline, 4.8 m side line and 2.5 m draft line on the drawn grid in both composite panels.
  The overlay of retained candidates is empty, because the failed inspection wrote no candidate
  traces. The body plan holds 30–40 overlaid station curves per side plus a black BT/WL grid.

### 6.4 Biggest error sources (measured, in order of effect on volume)

1. Stations not read: twin-skeg sections are not single-valued in height, and 14 midbody frames
   have no identity anchor. The 16.5 m loft gap dominates the volume error.
2. Drawing and truth differ in content: bow thruster tunnel, aft deck height, forward end
   (frame 60 at 35.0 m vs STEP end 34.55 m), plating offset (+13 mm half-breadth).
3. A declared assumption (side line to the top) that holds forward and fails aft.
4. Raster: the deterministic pipeline does not resolve contour identity in an overlaid body plan
   with a black grid (also in development), and on this sheet its inspection hit a resource limit.

### 6.5 Limits of these figures

One ship, one drawing, assistant-read identity rules. The good forward figures hold only where a
station was read; they are not a whole-hull accuracy. Volumes are moulded envelopes, with a
truth uncertainty of about 0.12 %. Nothing here is engineering approval.

### 6.6 Next steps

1. Represent multi-valued sections (skeg, bulb as separate closed regions) or abstain per region,
   so the aft body can be read instead of lofted over.
2. Anchor midbody frame identity with the profile and half-breadth views (cross-view matching).
3. Read the side-line extent per station from the drawing instead of one declared top.
4. Raster: supply per-station contour corridors (operator or assisted), and investigate the
   inspection resource limit on large overlaid sheets (owner: pipeline/Rust streams).
5. Use the transverse construction-section drawings (one section per panel) as raster input
   that matches the supported input.

## 7. Round 2 (W9): reading the hull gaps

Date: 2026-11-07. Base `a2608e1`. **Gunnerus is now development data**: its truth was seen in
round 1 and was inspected again during this work (section plots, aft deck height). All Gunnerus
numbers in this section are DEVELOPMENT numbers, not a fair accuracy score. The fair score is in
section 7.6, on held-out DTMB 5415 inputs, with the protocol fixed before the run.

### 7.1 What changed

| Task | Change | Files |
|---|---|---|
| Multi-outline sections | A station may have several pieces and several material intervals per height. Each piece is closed into a ring (centreline, side line to the station top, or the top); the rings are cut at every vertex height into *regions* with one interval `[y_in, y_out]` per height: `centreline` regions (the hull) and `offset` regions (one skeg per side). The decomposition is exact (region area = ring area, checked). Regions are matched one-to-one between neighbouring stations (same kind, mutual best intersection-over-union ≥ 0.2) and each matched run is lofted with ruled faces between corresponding polygon edges (normalized-height correspondence, 1 mm knot bound, as `build_hull`). A region without a match ends with a flat closure and, if it exists at one station only, is listed in `unlofted_regions` with its area. Every solid passes an exact volume audit (kernel volume = Simpson prismatoid volume of its station polygons within 1e-6). Output: a compound of solids that meet on shared faces. Single-curve reading and `build_hull` are unchanged (backward compatible); region mode is opt-in (`read_stations(regions=True)`, `geometry.build_region_hull`). `schema.py` rejects `regions`, `rows_m` and `outline_rings_yz_m` in a drawing spec (geometry is an output, never input). | `section_regions.py` (new), `geometry.py`, `lines_dxf.py`, `schema.py` |
| Midbody identity | `lines_dxf.cross_view_identity`: an unlabelled body-plan curve takes a frame only if its outer half-breadths at the labelled plan waterlines (WL 250–1800) match the plan at that frame (RMS ≤ 0.05 m), the second-best frame is ≥ 2× worse, and no other curve claims the frame. Rule 5 in `make_gunnerus_configs.py`. | `lines_dxf.py`, `make_gunnerus_configs.py` |
| Station top | `StationRequest.top_z_m`: a curve that ends on the side line follows it to the station's own top. Rule 6 reads that top from the drawing: the upper crossing of the centreline profile outline (the closed curve on the buttock layer) at the station. | `lines_dxf.py`, `make_gunnerus_configs.py` |
| Scorer | A cut of the reconstruction is the union of cuts 0.1 µm aft and forward of the plane, so a region solid that ends on a station plane counts there. Re-scoring the round 1 V4 model with it reproduces V4 exactly (402.09 m³, −17.32 %, waterplane −0.92 %, station medians 0.024 / 0.033 m). | `score.py`, `hull_metrics.py` |

Tests: `tests/test_section_regions.py` (twin rectangular skegs 80.000 m³ exact, twin circular
skegs = polygon area × length, tapered skeg = prismatoid, bulb run with flat closure, ledge step,
region at one station reported, legacy sections equal to `build_hull` within 1e-4, overlapping
pieces refused); `tests/test_lines_dxf.py` (twin skeg and split bulb read in region mode, station
top, open piece refused, cross-view assignment and ambiguity refusal); `tests/test_contract.py`
(regions refused in a spec).

### 7.2 Midbody identity evidence (rule 5)

13 aft-side curves after frame 20 had no anchor (keel heights of two families interleave, so the
round 1 ordering rule could not work). Cross-view result: 13 of 13 curves assigned, to frames
21–27 and A–F; best RMS 3.4–16 mm, second-best frame 2.8–13× worse. Frame G (x = 17.0 m) has
no curve in the body plan and is not read. Full ledger: `identity_ledger.json` of the run.

### 7.3 Station top (rule 6): what the drawing shows

The drawing has no deck line at the side. The centreline profile outline gives tops of 5.97 m
(frame −2) rising to 7.59 m by frame 20; forward of that the station curves reach the drawn top.
The truth hull ends at about 4.1 m from the transom to x ≈ 16 m (a deck that the lines plan does
not draw). So rule 6 is the drawing's evidence, but it does not change the main-band maxima
(band top 4.287 m): those 4.8 m maxima above 4.1 m remain, as a drawing-versus-truth content
difference, like the bow thruster tunnel. Volume and waterplane below 2.5 m are not affected.

### 7.4 Gunnerus development results (vector path)

Same metric file, truth cache and scorer (union cuts) for every row.

| Run | Stations read | Volume error (full) | Waterplane error | Between-station RMS / max | Station hb median RMS main / below draft (round 1 station set) |
|---|---:|---:|---:|---:|---:|
| Round 1 V4 (`1cc64ed`), re-scored | 31 of 59 | −17.32 % | −0.92 % | 1.357 / 4.80 m | 0.024 / 0.033 m |
| Regions only (round 1 stations) | 57 of 59 | −3.30 % | −0.24 % | 0.887 / 4.80 m | 0.024 / 0.032 m |
| Regions + midbody identity + station top | 70 of 72 | **−0.90 %** | **−0.24 %** | 0.832 / 4.80 m | 0.024 / 0.033 m |

Last row: model SHA-256 `953843af611b…`, score `3745e8d53fe8…`, configuration `c158aab60976…`;
17 solids, 6 region runs, CAD deviation ≤ 0.99 mm. Refused: frame 6 and frame 16 (`incomplete_curve`,
the curve is split at the skeg junction into pieces that the identity rules do not pick).
Unlofted regions: only slivers (largest 0.008 m², the skeg-tip notch at frame 3).

Section area below 2.5 m at the skeg stations (frames 4–20): −0.4 … −3.0 %; midbody frames
21–F: −0.7 … +0.2 %; bulb stations 55–58: −0.7 … +2.9 % (round 1: not read). Remaining large
errors are content differences: frames −2…1 (truth bottom step at 2.0 m and a centre notch at the
transom; −9 … −24 %) and frame 53 (+192 %, the truth's thruster tunnel). Over all 69 scored
stations, the median main-band RMS is 0.279 m, because 36 aft and midbody stations now include
the 4.1–4.287 m band where the truth has no hull. The below-draft maximum (2.9 m) is at the
skeg bottoms: a 15 mm bottom-height difference at a flat skeg bottom (fr12: drawn −0.379 m,
truth −0.395 m).

Images inspected: `station_comparison.png` of both region runs (all skeg, midbody and bulb
stations lie on the truth below 4.1 m; the aft tops follow the profile outline), Gunnerus body
plan with picks, aft zoom, profile and plan views, truth sections at x = −1 … 17.5 m.

### 7.5 Raster resource limit (investigation; nothing changed)

Measured on the round 1 composite (drawing SHA-256 `2acd43a7…`, same as R1) by calling the
inspection worker directly with large limits: one station 3.4–3.9 CPU s (0.63 GB peak RSS);
three stations 8.2 CPU s; the first batch of 12 stations (`INSPECTION_BATCH = 12`, frames −2…9)
**50.4 CPU s**, 0.68 GB. `AgentTools._worker` gives an inspection 45 CPU s (`RLIMIT_CPU`) and
60 s wall. So R1's `resource_limited` was the CPU limit: every section ROI is the whole half body
plan (≈1.8 Mpx with 30–40 overlaid curves) and 12 such sections need more than 45 CPU s.
Memory (4 GiB) is not the limit.

Proposal (needs a change in `agent_tools.py`, which this stream does not own; no budget is raised):

1. Size each inspection batch by work, not by count: estimate CPU per section from its ROI pixel
   count (here ≈ 4 s per full half body plan) and put sections into a batch only while the
   estimate stays under half of the 45 s budget (here 5 sections). The budget and gates stay.
2. Per-station contour corridors from declared evidence: the spec already accepts
   `contour_selection` (anchors at distinct rows, half width ≤ 128 px). For a lines plan the
   anchors can come from the half-breadth plan (station x and waterline heights give one point
   per waterline, rule 5's data) — a narrow corridor per station cuts traced pixels and also
   resolves which of the 30–40 overlaid curves is the station. This must be stated as declared
   input evidence (it uses another view of the same drawing, not truth).

### 7.6 Held-out evaluation protocol (fixed before the run)

Code frozen at the commit that adds this section. Cases not used to tune round 2 code:

- **H1, DTMB 5415 synthetic body plan**: `holdout_5415.py synthetic` cuts the FORCE/IIHR/INSEAN
  5415 truth at the 21 stations and writes every cut curve as a piece of its station (round 1
  skipped the FP station, which has two curves). Identity exact by construction. Read in
  region mode. This measures reading, region decomposition, loft and scorer.
- **H2, MARIN 5415 lines DXF** with the round 1 oracle identity configuration (15 stations), read
  once in single-curve mode (round 1 reader) and once in region mode, to show whether region mode
  changes results on a real drawing it was not tuned on.

Metric: `metric_dev5415.json` (model scale; draft 0.248 m). One run per case; every run is
recorded. Series 60 / Wigley and DSYHS were not run in this round (time); they stay open.

### 7.7 Held-out results (frozen commit `0e43324`, clean tree)

Runner `work/holdout/run_all.sh` (not tracked); one run per case, all three listed. Values in
model-scale metres.

| Case | Read | Station hb RMS median / max | Section area error mean / max | Between-station RMS / max | Volume error full / in range | Waterplane full / in range |
|---|---:|---:|---:|---:|---:|---:|
| H1 synthetic, region mode | **21 of 21** (round 1: 20) | 0.02 mm / 1.2 mm | 0.15 % / 2.9 % (st00, area 3e-5 m²) | 12.8 / 125 mm | +0.38 % / +0.38 % | +0.63 % / +0.70 % |
| H2 MARIN lines, single-curve (round 1 reader) | 13 of 15 | 1.85 mm / 14.1 mm | 0.55 % / 0.94 % | 5.5 / 36.4 mm | −3.25 % / +1.20 % | −5.35 % / +0.65 % |
| H2 MARIN lines, region mode | 13 of 15 | 1.83 mm / 14.1 mm | 0.48 % / 1.05 % | 5.4 / 36.7 mm | −3.13 % / +1.32 % | −5.29 % / +0.71 % |

Model SHA-256 (first 16): H1 `9d60e9144d38d2cb`, H2 single `9389fc3f43a85dbc`, H2 regions
`614ba639d3dad9ec`. In H1 the forward-perpendicular station (two curves) and the sonar-dome
stations with height reversals are read; the station curves lie on the truth within the 1 mm CAD
bound (`station_comparison.png` inspected). In H2, region mode reproduces the round 1 reader
within 0.1–0.2 percentage points (it evaluates every source point at the knots instead of
interpolating each station from its own kept knots); the two `ambiguous_curve` refusals are
identity, not shape. Region mode therefore adds the multi-region stations without a loss on
single-valued drawings. H1 and H2 have no twin skeg, so the twin-skeg accuracy is shown only on
Gunnerus (development, 7.4).

### 7.8 Open items

1. Frames 6 and 16: the curve is split at the skeg junction into several chains; an identity
   rule that picks all pieces (junction following) is needed.
2. Gunnerus content differences stay: aft deck at 4.1 m, thruster tunnel (frames 52–54), transom
   step and notch (frames −2 … 1).
3. Raster: the two proposals in 7.5 (owner of `agent_tools.py`).
4. Product path: `build_region_hull` is not yet wired into `pipeline.py` / the validation
   contract (not owned here); the raster reader still gives one curve per section.
5. Held-out twin-skeg case (for example a render of a twin-skeg CAD hull) and Series 60 / DSYHS.

## 8. Round 2b (W9b): raster batching and region wiring

Date: 2026-11-07. Gunnerus is development data (section 7); these runs are not a fair score.

**Changes.** (1) `agent_tools`: an inspection batch takes sections while the ROI-area CPU estimate
(1.0 CPU s per megapixel, from 7.5) stays within half of the unchanged 45 CPU s limit; the
whole-half-body-plan ROIs (4.18 Mpx) now inspect 5 per call. (2) The deterministic policy names the
next uninspected sections in each `inspect_source` call (`controller::inspect_next`): with 5 per
call, 72 sections need 15 calls, and the repeat limit (3 identical actions) stopped the first draft
run after 15 sections (`no_progress`, run `raster-0a81809-draft`). (3) Open item 7.8-4 is done:
section specs may declare `pieces`, and region runs go through `build_region_hull`, STEP export
and the v2 audit (`docs/VALIDATION_CONTRACT_V1.md`, "Region runs"). The raster Gunnerus spec does
not declare pieces, so (3) does not change these runs.

**Raster runs at `3c05737`** (clean tree; outputs `work/w9b/raster-3c05737-*`, not tracked):

| Mode | Outcome | Inspection | Model |
|---|---|---|---|
| abstain | `abstained`: "multiple or no supported contour interpretations" after the first batch (5 sections) | 5 sections, 1 worker call, no resource limit | none |
| draft | `abstained`: the draft build is `blocked` (`insufficient_sections`) | all 72 sections in 15 worker calls, 3.8–12.1 CPU s each (limit 45) | none |

In draft mode every section has 0 selectable candidates: 36 sections stop at the tracing candidate
budget (`resource_limit`, "Contour candidate complexity exceeds the bounded tracing budget"), and the
other 36 are `ambiguous_curve` whose traced hypotheses jump between overlaid curves
(`not_representable_as_bounded_corridor`). All 72 become `dropped_end` guesses, so the draft spec
has no section. The CPU limit is no longer the cause; contour identity in an overlaid body plan is.
Next: per-station corridors from the plan-view waterline anchors (7.5, proposal 2).

## 9. Round 3 (W15): declared plan-waterline corridors

Date: 2026-11-08. Gunnerus remains development data. This is a conservative
input-evidence adapter, not autonomous waterline identity recognition. All
outputs keep `engineering_approved=false`; Rust retains readiness authority.
No CAD, validation, correctness gate or tolerance changes.

`plan_corridors.derive_contour_selection` reads a station column in explicitly
declared plan-waterline regions. The plan setup supplies scale, station origin,
x direction, centreline and breadth direction. Each waterline supplies a height,
region and drawing-identity evidence. Only one complete ink run in **each** of
three adjacent columns can support an anchor; its ordinate is measured in the
actual station column. Multiple, absent, clipped or unidentified crossings give
no anchor and retain a refusal reason. A review regression caught the unsafe
alternative: unioning the columns can merge two diagonal strokes into one run.

Accepted anchors map through the existing section calibration to body pixels.
They select a corridor only; the normal reader still measures source ink and
keeps its ruler/coverage checks. No endpoint extrapolation is allowed. Anchors
must span the complete existing calibrated range, have distinct rows and obey
the existing 128-pixel half-width bound. A prior selection is never replaced.

The raster preparer optionally accepts `plan_corridors` in its local config:
`clip_pt`, `setup`, `waterlines_by_section` and `half_width_px`. Both views come
from the same PDF page at the declared DPI. It writes the source-PDF hash,
render mapping and every anchor outcome to `plan_corridors.json`, outside the
strict geometry spec. Inputs without this option take the unchanged path.

### Drawing evidence and limits

The raster plan inspection could read labelled waterlines from 0.5 to 4.5 m,
but could not establish isolated, uniquely identified crossing regions. Broad
label-linked regions retain competing curves and the station grid rather than
assigning heights by ink order. The inspected plan did not establish waterlines
at 0 or 7.5 m, the endpoints of the current body range. The centreline is not a
substitute for a missing waterline. No local height range or endpoint is invented.
Calibration is provisional operator-read evidence, not independent metrology.
The 72-station list is the existing drawing-derived W9b setup, not newly inferred
by this adapter; no DXF shape or reference geometry enters the new anchor read.

Across 72 stations, **792 attempted anchors were refused**: 648 for competing
crossings and 144 for missing endpoint-waterline identity. **0 corridors** were
emitted. Before/after specs are semantically identical. This does not establish
that plan anchors cannot help; it establishes that unidentified plan ink and
missing endpoints cannot safely produce them under the current contract.

Raw drawings, crops, coordinates, frozen workers, executables and native task
records are retained only under the main checkout's `work/w15/`. No such source
data is committed. An initial archived-input probe used 59 stations and is kept
as an excluded attempt; the comparison uses the frozen W9b **72-station** config.
No provider request or DeepSeek call is used.

### Native results and verification

Native runs use an immutable controller built from `844c842` and separate frozen
before/after Python sources. The existing raster drawing hash matches W9b.

| Arm | Mode | Inspected / requested | Unique selectable sections | Built | Volume error | Station RMS |
|---|---|---:|---:|---|---|---|
| Before | abstain | 5 / 72 | 0 | no | not measurable | not measurable |
| After | abstain | 5 / 72 | 0 | no | not measurable | not measurable |
| Before | draft | 72 / 72 | 0 | no | not measurable | not measurable |
| After | draft | 72 / 72 | 0 | no | not measurable | not measurable |

All four runs end `abstained`. Both draft arms reproduce **36 resource-limit**
and **36 ambiguous-curve** sections. Their draft candidate is invalid/blocked
(`insufficient_sections`), with no STEP. A blocked candidate record is not a
build. Abstain mode stops after its first five-section batch; uninspected
sections are not claimed as measured. Gunnerus newly wrong builds: **0**, because
neither arm builds. No truth data was needed for these `no_model` scores.
All source inspection records match between arms (5/5 abstain, 72/72 draft),
excluding only the intentionally changed worker implementation hash.

The four authorized factory development inputs were regenerated from the
published sources, outside inference. Their drawing, spec and parameter hashes
all match the frozen development manifest (12/12 checks). Only the drawing/spec
package enters each native controller task. Reference hulls are used only by
input generation and the separate post-read scorer; they are never available
as input evidence to the reader. No sealed evaluation case was run.

All four controls build before and after (8 native builds), and independent
STEP reimport scoring is exactly unchanged at the fixed factory gates:

| Development control | Station RMS before / after, mm | In-range volume error before / after | Correct before / after |
|---|---:|---:|---|
| `shipd-1-01410-L0` | 30.8201 / 30.8201 | −0.3769% / −0.3769% | yes / yes |
| `shipd-2-01040-L0` | 31.5757 / 31.5757 | −0.8978% / −0.8978% | yes / yes |
| `shipd-2-05051-L0` | 34.4416 / 34.4416 | −0.8079% / −0.8079% | yes / yes |
| `wigley-L0` | 7.5068 / 7.5068 | −1.3286% / −1.3286% | yes / yes |

**0 newly wrong builds** in the requested Gunnerus/four-control comparison.
This is not a full factory or held-out claim. Legacy worker modules are byte
identical; the after worker adds only `plan_corridors.py`. The first aggregate
scorer driver failed on Python multiprocessing bootstrap (missing main guard);
that attempt is retained. The independent scorer was then invoked successfully
without changing scorer code or gates.

Verification: **26 focused tests passed**, including 21 new adapter tests and
five existing mixed-stroke controls. Stable-source `make test-quick` **passed**:
701 Python tests, 17 CAD deselected, Rust quick suites, formatting, Clippy and
bounded secret scan. A separate Python real-CAD tier **passed 17 tests**.
The initial quick tier failed one Rust test with `worker_implementation_changed`
while the crossing correction changed Python source; it is retained as an
invalidated attempt, not hidden. No worker source changed during the successful
rerun. No `.codesight` index is present in this worktree, so no generated index
was refreshed or committed.

The single `make test-full` invocation **passed**, exit 0, after its preflight
found no other full-tier run: 701 Python quick tests, **44 Rust controller CAD
tests**, the app real-task test, **17 Python CAD tests**, and smoke
`awaiting_human_review, valid`. The stock smoke target hard-codes `/tmp`; its
completed folder was moved to main `work/w15/smoke-full/`. All W15 development
runs and retained raw evidence are under main `work/w15/`, never this worktree's
`work/`. No second full-tier invocation was made. After all consumers ended,
`cargo clean` removed 4.8 GiB from the worktree target and 1.1 GiB from the
W15 baseline target. No push was made.

Open: source-supported waterline identity at station crossings, sufficient
full-range anchors (or a separately designed partial-evidence contract), and
local endpoints/pieces for this drawing. These are not solved by rank matching,
truth offsets, extrapolated anchors, or wider gates. W15 demonstrates correct
synthetic corridor selection and honest refusal, **not improved Gunnerus reads**.
