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

Frozen commit: to be recorded below, with each run.
