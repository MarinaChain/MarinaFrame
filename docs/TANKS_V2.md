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

### 3.1 Notes added during the build (no target changed)

- D1 truth: the table of `Tank Plan Rev1` is drawn as linework, not text (the DXF has no text
  entities for it and the PDF has no text layer). The scorer's truth was therefore transcribed
  by hand by this lane from a 75 dpi render into `work/tanks-raster/truth/d1_tank_plan_rev1.json`
  (24 rows, the printed volume totals). The reader never reads that file. Section 2 said "from
  the DXF text"; that was not possible.
- The schedule question asks for tank names and contents only. The reader takes the content of a
  tank from the schedule row of its tank number; volumes are never asked.

## 4. Holdout protocol: Arthur M. Huddell (fixed 2026-11-09, before any run on Huddell)

Status: not run. Nobody on this lane has opened `liberty_truth/` or looked at the Huddell sheets
beyond their file names. This section replaces the open points of `docs/TANKS_V1.md` 3.1.

**Reader.** `vessel_reconstruction.tank_plan_raster.read_sheets` as frozen by the commit that
adds the development results (section 5; its hash is written there). The reader is not changed
between that commit and the run. Label reading by Claude Sonnet 5.5 through the Claude Code CLI on the
subscription (`claude_asker`), with a new, empty answer cache. One run. If the run stops on an
error, only that error may be fixed (no threshold, rule or geometry change), the fix is committed
and reported, and the run is repeated once.

**Inputs.** HAER VA-132 sheets in `work/sources/tanks-public/arthur_m_huddell_haer_va132/`, raster
TIFF as downloaded (bilevel, 400 dpi):
- sheet 7, Inboard Capacity Plan: the profile view;
- sheet 9, Deep Tank Top and Inner Bottom Capacity Plan: the inner-bottom plan (role
  `double_bottom`) and the deep-tank-top plan (role `above`);
- sheet 8, Upper Deck and Second Deck Capacity Plans: plans with role `above` (peaks, deep tanks
  and settling tanks when they are drawn there).
Host calibration (a `SheetSpec` per sheet: view windows, view kind and plan role, the graphic
scale-bar window, the schedule-of-rooms window) is written by the person or agent that runs the
holdout, from the Huddell sheets only, without access to `liberty_truth/`, and committed to
`benchmarks/tanks/raster_cases.py` (case `arthur_m_huddell`) before the run. It holds no
geometry. Scale comes from the drawn scale bar (feet); there is no hull mesh, so each tank is a
prism of its plan region between its vertical limits (labelled `guessed`; the bilge is not cut).

**Truth.** The US Maritime Commission EC2-S-C1 capacity-plan tables in
`work/sources/tanks-public/liberty_truth/`, transcribed by an independent agent (not this lane)
into `liberty_truth/truth.json` before the run: one row per tank with the printed name, the tank
number, the side (P, S or C), the kind (double bottom, deep tank, peak, settling, other), the
content (fuel oil, fuel oil or ballast, ballast, fresh water, feed water, other) and the printed
100 % capacity in cubic feet. Volumes in m3 = cu ft x 0.0283168. Rows without a cubic-foot value
are left out. Only volume metrics apply (no LCG, VCG or frame limits are printed).

**Matching (scorer, fixed).** A built tank matches a truth row when the tank numbers agree, the
sides agree (a label without a side matches a centre-line row, or a single row of that number),
and the kinds agree. The kind of a built tank comes from its label words ("deep", "peak",
"settling", "D.B." or "double bottom"); without such a word it is the plan role (an inner-bottom
plan gives "double bottom"). Each row matches at most one tank.

**Metrics and targets (fixed).**

| ID | Metric | Target |
|---|---|---|
| H1 | Coverage: truth rows with a matched built tank, share | >= 60 % |
| H2 | Volume of the matched tanks against the truth, median abs relative error; also the counts within 10 % and within 25 % | <= 20 % |
| H3 | Totals by content group (fuel oil including "fuel oil or ballast", ballast, fresh and feed water) and the grand total of all truth rows; an unmatched row counts 0 m3 | grand total <= 15 % (groups reported) |

**Decision rule.** The raster reader passes the Huddell holdout when H1, H2 and H3 all meet their
targets in the one run. Otherwise it fails; the result names the metric(s) missed and the cause
found in the reading record. The result is reported as measured, in a new section of this file;
targets are not changed after the run, and any later fix makes a new development round (the
holdout is then spent).
