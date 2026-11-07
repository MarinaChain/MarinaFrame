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
