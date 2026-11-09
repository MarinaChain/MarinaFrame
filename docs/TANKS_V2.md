# Tanks v2: tank and compartment model from scanned (raster) tank and capacity plans

Date: 2026-11-09. Branch `feature/tanks-raster` (from `continue/v0.5` at `0388ff1`).
Status: built; development results in section 5; Huddell holdout protocol in section 4 (not run).
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

### 4.1 Truth file format and scorer (written before the truth file and before the run)

The independent agent writes `liberty_truth/truth.json` as one JSON object:

```json
{
  "source": "EC2-S-C1 capacity plan tables: file names and pages",
  "rows": [
    {"name": "No. 3 D.B. Tank", "number": 3, "side": "P", "kind": "double bottom",
     "content": "fuel oil or ballast", "printed_value": 1234.5, "printed_unit": "cu ft", "note": null}
  ]
}
```

| Field | Type and values |
|---|---|
| `name` | string, the printed name, as printed |
| `number` | positive integer, the printed tank number; `null` when none is printed |
| `side` | `"P"`, `"S"` or `"C"` (centre line, or one tank across the ship) |
| `kind` | `"double bottom"`, `"deep tank"`, `"peak"`, `"settling"`, `"other"` |
| `content` | `"fuel oil"`, `"fuel oil or ballast"`, `"ballast"`, `"fresh water"`, `"feed water"`, `"other"` |
| `printed_value` | positive number, the printed 100 % capacity as printed; `null` when none is printed |
| `printed_unit` | `"cu ft"` or `"US gal"` (section 4.2), the unit of `printed_value` |
| `note` | optional string or `null` (for example "printed 5P") |

All fields except `note` are required in each row; another field or a value outside the lists
stops the scorer (`ValueError`). Rows with `printed_value` `null` are left out (and counted).
`source` is free text. The scorer converts to m3 (section 4.2).

Scorer: `benchmarks/tanks/holdout_score.py`, run as
`python -m benchmarks.tanks.raster_run --case arthur_m_huddell --scorer holdout --truth <truth.json> ...`;
it writes `holdout_score.json` (H1 to H3, the decision, the per-row match table, unmatched tanks).
How it applies the matching rule above, fixed now:
- Tank number: the reader's `tank_key` of the built tank's label ("No 3 P" is number 3, side P;
  "S" or "SB" is side S). A row or a tank without a number does not match.
- Side: equal sides; a tank without a side matches a `"C"` row, or the single row with that
  number and that kind.
- Kind: from the label as read: "deep" gives deep tank, "peak" peak, "settling" settling,
  "D.B." or "double bottom" double bottom (first of these in that order). Without such a word, a
  tank of an inner-bottom plan (role `double_bottom`) is a double bottom; any other tank is
  `"other"`.
- Order: rows in file order; each row takes the first unused built tank (reader order) that
  matches. Each row and each tank is used at most once.
- H2 uses the matched rows only (`built / truth - 1`). H3 groups: fuel oil = "fuel oil" and
  "fuel oil or ballast"; ballast; fresh and feed water. The grand total is over all truth rows,
  "other" included; an unmatched row counts 0 m3. Targets are met at equality.

### 4.2 Amendment before the run, 2026-11-09

Made after the units of the truth tables were known (from the coordinator, without opening
`liberty_truth/` on this lane) and before any Huddell run. No target and no matching rule is
changed.

1. Units. The water ballast table (fore and after peaks included) prints cubic feet; the fresh
   water and fuel oil tables (settling and deep tanks included) print US gallons only. As first
   written, section 4 would have left out every gallon row. A row printed in US gallons is
   converted exactly: 1 US gal = 231 in3 = 231/1728 ft3 = 0.1336805556 ft3, then m3 = ft3 x
   0.0283168 as before. The truth file keeps the printed value and unit (`printed_value`,
   `printed_unit`); the scorer converts.
2. Repeated "No.5P". The water ballast table prints "No.5P" twice (on both the John W. Brown and
   the Peter Minuit tables). In the P/S order of that table the second occurrence is No. 5 S: the
   truth file records `"side": "S"` for it, with `"note": "printed 5P"`.

### 4.3 Truth conversion (PM, 2026-11-09, before the run)

Source: two independent transcriptions of the SS John W. Brown EC2-S-C1 capacity plan (Sonnet 5.5,
row crops; Opus 5.5, column crops) agree on every quantity cell; all 13 printed totals equal their
column sums; the Peter Minuit plan prints the same quantities (standard design). Frozen file and
hash: `liberty_truth/frozen/` (git-ignored). Conversion code: `benchmarks/tanks/huddell_truth.py`.

Rules, fixed before the run:
- One row per physical tank. Double-bottom tanks 1 to 6 and deep tanks 3 P/S are printed in both
  WATER BALLAST (cu ft) and FUEL OIL (US gal): they are one dual-use tank each, content `fuel oil or
  ballast`, value = the cu ft figure (the protocol's 100 % capacity unit); the gallons go in `note`.
- Reserve feed 4 P/S: kind `double bottom`, content `feed water` (US gal). Fresh water P/S: kind
  `other`. Settling tanks P/S: kind `settling`, content `fuel oil` (US gal). Fore peak: `peak`,
  `ballast`. After peak (culinary water): `peak`, `fresh water`. Rows printed without a side: `C`.
- The scorer is not changed: rows without a printed number (2 peaks, 2 fresh water, 2 settling;
  6 of 22) cannot match under 4.1, so coverage is at most 16/22 (73 %). This makes the holdout
  harder, not easier, and is stated here before the run.

Truth file: 22 rows, sha256 d780c3e82d32075c919013f1c62a160703e7d641dd7fd4d6326332e6155965a7.

## 5. Development results (2026-11-09)

Code: `src/vessel_reconstruction/tank_plan_raster.py` (reader), `benchmarks/tanks/raster_cases.py`
(host calibration, renders, scan variant), `benchmarks/tanks/raster_run.py` (run and scorer),
`tests/test_tank_plan_raster.py` (synthetic drawings). Outputs in git-ignored
`work/tanks-raster/runs/` (reading record, tank model, capacity plan and sounding tables).

### 5.1 What the reader does

- Lines by morphological opening; straight non-axis lines by a Hough transform, joined over dash
  gaps (drawn solid so dashed boundaries close) and over labels (for cross marks).
- Cross marks: two diagonals with opposite slopes that cross; each is cut to its arms (to the
  next horizontal or vertical line, or a little past a dashed line's end); the crossing lies near
  both middles, the x ends agree, and both end sides of the box are drawn. The arms are erased.
- Text: small components that are not thin straight strokes; blocks are the words of a line; the
  blocks of one region (each side of a plan's centre line) are one label, read from one crop.
- Frame axis: the long horizontal line with the most regular ticks; hidden ticks are counted;
  one crop per tick is read; frame 0 from the lowest numbers that agree (inserted lettered frames
  of a lengthened ship work). Scale-bar sheets: the bar's numbers give the scale; plans are
  aligned to the profile by their bulkheads.
- Tank = plan region at a tank label (a region with two different tank numbers is a room, not a
  tank). Height: the profile region with a shared label word or tank number whose x extent agrees
  (60 % of the longer), else, in a double-bottom plan, the tank-top line (median of the lowest
  horizontal line above the baseline), else (gap fill, `guessed`) tank top to the deck above.
  Baseline: the line at a "BL"/"Baseline" label (a line ending at the label first, else at or
  below it). Clip to the hull (`tanks.tank_slabs_in_hull`) or a prism without a hull.
- Model use: 168 Claude Sonnet 5.5 calls over all development runs (all completed; 1.19 M
  prompt and 0.12 M completion tokens), text only. A fresh-cache run of D1 at 300 dpi gave the
  same scores as the cached run (81 s).

### 5.2 Metrics (last run of each case with the final code)

| Case | R1 coverage | R2 ends (median) | R3 volume (median; within 10 % / 3 %) | R4 groups WB / FW / FO / misc; total | R7 numbers read |
|---|---|---|---|---|---|
| D1 300 dpi | **0.83** (20 of 24; 21 built) met | **0.008 m** met | **8.3 %** (15 / 1 of 20) met | -19.6 / -5.9 / -10.2 / -17.7 %; **-14.3 %** missed (WB, misc, total) | 0.83 |
| D1 200 dpi | 0.88 (21) met | 0.009 m met | 9.2 % (12 / 0 of 21) met | -29.2 / -6.0 / -16.8 / -17.5 %; -20.5 % missed | 0.87 |
| D1 scan variant (200 dpi) | **0.79** (19) missed | 0.004 m met | 11.1 % (9 / 0 of 19) met | -34.7 / -6.1 / -27.2 / -6.2 %; -25.2 % missed | 0.78 |
| D2 300 dpi | 0.86 (18 of 21; 24 built) met | 0.011 m met | **40.9 %** missed | -44.3 / -21.5 / +488 / +250 %; +201 % missed | 0.79 |

Raster against vector on the Gunnerus tank arrangement (D2, same drawing and truth, R6):

| | Vector (v1, DXF) | Raster (D2, 300 dpi) |
|---|---|---|
| Tanks built | 24 of 24 | 24 regions built; 18 of 21 rows with a volume matched |
| G1 / R2 ends, median abs | 0.019 m | 0.011 m |
| G2 / R3 volume, median abs rel | 10.2 % | 40.9 % (R6 target <= 13.2 %: **missed**) |
| T2 / R4 grand total | +4.2 % | +201 % |

R5 (resolution and scan): 200 dpi meets R1 to R3 and its R3 is within 3 points of 300 dpi
(9.2 against 8.3 %); the scan variant misses R1 by one tank (0.79), so **R5 is missed**.

Causes of the misses (from the reading records):

- D1 R4: the unbuilt tanks count 0 m3 (No 13 sb/p wing tanks, No 11 p, No 4, No 9; small crossed
  boxes whose cross marks are not found, or labels split over two regions), and every
  double-bottom tank is about 7 % low. The low bias is a datum: the reader takes the line
  labelled "Ny BL." as the baseline, which lies 0.09 m above the hull's datum (the solid line just
  below it). A development run that took that solid line gave R3 0.8 % (16 tanks within 3 %); the
  rule that picks the labelled line is kept because it follows the drawing, not the truth.
- D1 R1 on the scan variant: noise opens small gaps, so two more labels fall in the wrong region.
- D2 R3: the profile's tank-top lines measured from the line labelled "Baseline" (the frame axis
  on that sheet) lie 0.37 to 0.47 m above the v1 longitudinal-section levels (TANKTOP 1250 AB.BL),
  so every double-bottom tank is about +40 %; the drawings disagree on the datum. The "Engine
  room" region holds the label of No 11 sb (the label reaches out of its small box), so one
  225 m3 "tank" is built (fuel oil +488 %).
- Hold (D1 -31 %, D2 -32 %): the profile region at "CARGO HOLD" is cut by the sloping hull lines;
  v1 noted the two printed hold volumes differ by 11 %.
- G1 No 5 (D1, -2.0 m aft end): the drawn tank starts at frame 28; the table prints 32.

### 5.3 Plausibility (no per-tank truth)

| Check | Saugatuck (sheet 4) | Empire State V (sheets 6 and 8) |
|---|---|---|
| Scale from the drawn bar | 25.003 px/ft; printed 1/16 in = 1 ft at 400 dpi = 25.0 px/ft (+0.01 %) | 20.029 px/ft; printed 1/20 in at 400 dpi = 20.0 (+0.15 %) |
| Labels read | 35 plan labels ("WING TANK NO.6", "CARGO TANK NO.5", "FUEL OIL TANK", ...) | 49 schedule rows; 23 double-bottom labels ("DBL. BOT. TANK NO.3 O.B. PORT", ...) |
| Plan geometry | 31 tank regions; cargo tank lengths 11.04 to 11.07 m against the printed bay 36 ft 6 in (11.13 m); beam over the wing tanks 20.65 m (T2 tanker, 68 ft) | plan aligned to the profile (+3.8 m, 19 bulkhead bins agree); double-bottom tank top 1.49 m |
| Heights and volumes | only 3 tanks built: the profile's dashed bulkheads do not close, so the cargo tanks are one region; the built heights (5.4 m) are a cross-mark piece, not the 12 m depth | 23 built (prisms, no hull); fuel/ballast tanks 1,668 m3, of which 845 m3 with the tank-top height; the rest took hold regions of the profile (wrong). HAER report: 13,762 bbl = 2,188 m3 of fuel in all tanks; same order |

Plausibility verdict: the scale, label and plan steps carry over to the HAER sheets; the profile
step does not yet (dashed bulkheads, hold regions matched to double-bottom tanks).

### 5.4 What is open

1. Profile: dashed bulkheads (close them without closing dashed hull lines), and in a
   double-bottom plan prefer profile regions on the bottom.
2. Datum: register the profile baseline to the hull (keel or deck) when a hull is given.
3. Small crossed boxes whose diagonals do not meet the corners; a label that reaches out of its
   small box (take the smallest region under the label).
4. Huddell holdout: write the `arthur_m_huddell` host calibration (sheets 7, 8, 9) blind to the
   truth, have the truth transcribed independently, then run once by section 4. The reader is
   frozen at commit `53f35c4` (the commit that added this section).

Commands (outputs git-ignored):

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.tanks.raster_run --case gunnerus_tank_plan \
        --dpi 300 --sources ../../../work/sources \
        --hull ../../../work/whole-vessel/final/whole-vessel-draft.glb \
        --truth work/tanks-raster/truth/d1_tank_plan_rev1.json --out work/tanks-raster/runs/d1-300
    (--scan for the scan variant; --case gunnerus_tank_arrangement --truth d2 for D2;
     --case saugatuck or empire_state_v without --hull and --truth)

Checks before each commit: `tests/test_tank_plan_raster.py` and `tests/test_tanks.py`.

## 6. Huddell holdout result (one run, 2026-11-09)

Reader frozen at `96af891` (unchanged; `git diff 96af891 -- src/vessel_reconstruction/tank_plan_raster.py`
is empty). Host calibration `20f1617`, scorer `5c7544d`, truth conversion `5fc2cb2`, all before the run.
Label reading: Claude Sonnet 5.5 via the CLI subscription, empty cache. Run time 197 s. No error, so no repeat.

| ID | Result | Target |
|---|---|---|
| H1 coverage | **0 of 22 rows (0 %)** | >= 60 %: missed |
| H2 volume, median abs rel | not measurable (no matches) | <= 20 %: missed |
| H3 grand total | -100 % (unmatched rows count 0 m3) | <= 15 %: missed |

**Decision: the raster reader fails the Huddell holdout.** The holdout is spent; any fix is a new
development round.

Causes found in the reading record (`work/tanks-raster/runs/huddell/reading.json`, git-ignored):
1. **Frame axis not found on any view.** Every view reports "x from the sheet edge (guessed origin)",
   so plan and profile x positions do not line up. The one double-bottom tank linked to a plan region
   (No. 6, label "FUEL OIL OR WATER BALLAST TANK NO.6") got no height from the profile and was not
   built (0 m3).
2. **Tank labels read but not tied to regions.** The profile labels include F.O. or water ballast
   tanks No. 2, 3, 5 P/S and 6, deep tanks No. 1 and 2 P/S, fore and after peaks; none became a
   built tank. The inner-bottom plan read 22 labels, mostly girders and voids.
3. **Hatches built as tanks.** In the deck plans (role `above`) the reader built closed outlines with
   hatch and girder labels (No. 1, 2, 4 HATCH; "GIRDER OVER WEB NO.2 HATCH") as tanks; a label needs
   no tank word to become a tank. Schedule matching by number alone then linked "NO.1 HATCH" to fuel
   oil tank No. 1.
4. The two settling tanks were built (77 and 88 m3) but carry no number, so they cannot match under
   4.1 (as stated in 4.3).

Next development round (new data; Huddell is no longer a holdout): frame axis from the drawn frame
numbers on scanned plans; tie profile labels to plan regions by frame range; require a tank word (or a
schedule tank row) before a plan region becomes a tank; match the schedule by number and kind.
