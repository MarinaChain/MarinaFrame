# Tanks v2: tank and compartment model from scanned (raster) tank and capacity plans

Date: 2026-11-09. Branch `feature/tanks-raster` (from `continue/v0.5` at `0388ff1`).
Status: metrics fixed (section 3) before the raster reader is built.
Builds on `docs/TANKS_V1.md` (tank model, sounding tables, capacity plan; vector DXF reader for
Gunnerus). Why: customer inputs are mostly old scanned PDFs, and the holdout (Arthur M. Huddell,
Liberty ship, `docs/TANKS_V1.md` section 3.1) has only raster sheets.

Every output is a draft: `engineering_approved` is false. No status uses the words "approved" or
"verified".

## 1. Deliverables

1. Product module `src/vessel_reconstruction/tank_plan_raster.py` (no ship-specific code):
   - an ink mask from a scan (1-bit TIFF read as in `body_plan_crossings.load_ink`, or a grey page),
     with a skew correction from the long drawn lines;
   - scale and x origin from a drawn axis: frame ticks with frame numbers (and a frame spacing read
     from the sheet), or a graphic scale bar; a tick is found by code, its number is read;
   - tank boundaries as closed regions of the ink (text removed, solid cross marks removed, dashed
     lines bridged) in each plan view and in the profile;
   - tank labels: code finds the text blocks and their positions; a model reads only the text of
     each block (Claude Sonnet 5.5 through the Claude Code CLI on the subscription,
     `benchmarks/thayer/holdout_value.claude_call`). A printed tank schedule may be read the same
     way for tank names and contents (never its volumes). Code does all geometry;
   - vertical limits from the profile (the profile region of the tank, or the tank-top line for a
     double-bottom tank), plan extents from the plan region, clip to the hull when a hull mesh is
     given (`tanks.tank_slabs_in_hull`), else a prism of the plan region (labelled `guessed`);
   - the `tanks.Tank` model, so capacity plan, sounding tables and exports are those of v1.
   Every value has a source label: `traced`, `read` or `guessed`.
2. Per-sheet host calibration (a person, without truth: view windows, which view is a profile or a
   plan and what the plan's vertical role is, frame spacing or scale-bar window) in
   `benchmarks/tanks/raster_cases.py`. No geometry is given by the host.
3. Scores on the rasterised Gunnerus plans (section 3), plausibility on two HAER ships, and the
   Huddell holdout protocol (section 4), fixed and committed before any Huddell run.

## 2. Data

| Case | Input (git-ignored `work/sources/`) | Truth |
|---|---|---|
| D1 Gunnerus tank plan | `gunnerus/polarkonsult/Tank Plan Rev1.pdf` (1:50, profile, tank-top plan, tank table) rendered to a raster at 300 and 200 dpi; and a "scan" variant at 200 dpi (below) | Printed table of the same sheet: tank number, frame range, net volume, content column (TW, FO, FW, LO, Misc) and the printed volume totals. The scorer reads it from the text entities of `Tank Plan Rev1.dxf` into `work/`; the reader never sees it. |
| D2 Gunnerus tank arrangement | `gunnerus/extended/CJOB/Tank Arrangement Rev0.pdf` (1:100; the drawing that the v1 vector reader reads) rendered at 300 dpi | The printed table used by v1 (`whole_vessel_internals.read_tank_table` on the DXF), so raster and vector are scored against the same truth |
| P1 Empire State V | HAER VA-131 sheets 6 (capacity plan inboard profile) and 8 (capacity plan double bottom) in `tanks-public/empire_state_v_haer_va131/` | None per tank. Sanity only: total fuel 13,762 bbl (HAER report) |
| P2 Saugatuck | HAER VA-128 sheet 4 (capacity plan profile, second deck and hold plan) in `tanks-public/saugatuck_haer_va128/` | None per tank (plausibility only) |
| Holdout | HAER VA-132 Arthur M. Huddell | Section 4; not run on this branch |

Hull for D1 and D2: the built Gunnerus hull of the step 1 assembly
(`work/whole-vessel/final/whole-vessel-draft.glb`), as v1. P1 and P2 have no built hull: tanks are
prisms of their plan regions (bilge not cut, labelled `guessed`).

Scan variant of D1 (fixed now): the 200 dpi grey render, rotated by 0.2 degrees, Gaussian blur
sigma 0.8 px, Gaussian grey noise sigma 12 grey levels, then thresholded at 160 to 1 bit, then
0.1 % of pixels flipped at random (seed 0). This imitates a bilevel scan with skew.

No drawings, crops or derived data enter the repository. Outputs go to the git-ignored
`work/tanks-raster/`. The HAER sheets are public domain; they still stay in `work/`.

## 3. Metrics (fixed 2026-11-09, before the build; development targets, not gates)

Matching: a built tank counts for a printed row when its label (as read) names the row's tank
number (or, for a row without a number, its name). Each row matches at most one tank. Frame
letters after frame 27 (Gunnerus lengthening, A to J) use `whole_vessel_internals.frame_x_m`.
Content groups for T2: D1 columns TW (technical water) = water ballast, FO = fuel oil, FW = fresh
water, Misc = misc; D2 the v1 groups.

| ID | Metric | Target |
|---|---|---|
| R1 | Coverage: printed rows with a volume that have a matched built tank, share (D1, D2) | >= 80 % |
| R2 | (G1) tank x ends against the printed frame range, median abs error over matched tanks | <= 0.5 m |
| R3 | (G2) volume of the built tank (in the hull) against the printed net volume, median abs relative error over matched tanks; also the counts within 10 % and within 3 % | <= 15 % |
| R4 | (T2) group volume totals against the printed totals; an unmatched row counts 0 m3; abs relative error per liquid group and for the grand total of the liquid groups | each group <= 15 %; grand total <= 10 % |
| R5 | Resolution and scan robustness: D1 at 200 dpi and the D1 scan variant | R1 to R3 targets met, and the R3 median within 3 points of D1 at 300 dpi |
| R6 | Raster against vector on D2 (same drawing, same truth): built tanks, R2, R3 against the v1 vector result (24 of 24 built; G1 0.019 m; G2 10.2 %) | R1 >= 80 %; R3 median within 3 points of the vector value (<= 13.2 %); R2 <= 0.5 m |
| R7 | Label reading: share of plan tank labels whose tank number the model read exactly (scorer check against the table) | report only |
| P | Plausibility on P1 and P2: scale read from the scale bar against the printed scale (1/20 in = 1 ft at the sheet dpi for P1, 1/16 in for P2), tanks built, tank volumes in a sensible range, P1 sum of the fuel/ballast tanks against 13,762 bbl (2,188 m3) | report only; the scale within 2 % of the printed scale |

R1 to R4 apply to each of D1 at 300 dpi and D2. Development runs may be repeated; the result
section reports the last run with all code fixed, and lists what each fix changed. The model
reads labels; a model answer is cached per crop image in `work/` so that a code change can be
replayed without new model calls, and a fresh-cache run is reported once at the end.

Rules: do not loosen a target after seeing a result. A missed target is reported with its cause.
No reader code may branch on a ship name.
