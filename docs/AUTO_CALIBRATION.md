# Automatic body-plan sheet calibration

Status: plan (step 1), 2026-11-09. Branch `feature/auto-calibration`. `engineering_approved` stays
false for every result here.

## 1. Goal

The scanned body-plan reader (`body_plan_crossings`, `body_plan_reader`, `body_plan_identity`,
"code measures, model identifies") gave 1.4 mm RMS on the BUE GIRL holdout. It runs only in
benchmark harnesses, and every run used a `SheetLayout` written by an agent or a person. This work:

1. calibrates a body-plan sheet automatically (new module, no change to the frozen reader);
2. runs the frozen reader with that calibration in the app's hull path, with the current model
   path as the fallback, and shows the calibration overlay to the person as one item to confirm.

PM/CEO review, section 2 item 1 (`docs/plans/2026-11-09-pm-ceo-review.md`).

## 2. Freeze rule

`body_plan_reader.py`, `body_plan_crossings.py`, `body_plan_identity.py` and
`benchmarks/balclutha/crossing_value.py` are pinned by SHA-256 in the holdout tests
(`tests/test_bue_girl_holdout_value.py`, `tests/test_bumble_bee_holdout_value.py`, PARDON ME).
They are not edited. Calibration and integration are new modules that call the reader. If a reader
change is needed, the work stops and reports it.

## 3. What a calibration is

The reader needs a `SheetLayout`: centre column, pixels per metre, waterline rows, a search
half-span (`max_offset_px`) and, per half, its sign (left -1 / right +1), the station numbers
outermost first and the buttock grid columns. The automatic calibration gives these, each with a
source label, plus the baseline row (the datum for waterline heights).

Division of work (rule: code does geometry, a model only reads printed labels and numbers):

| Field | Code (geometry) | Model (reading, Claude CLI on the subscription) |
|---|---|---|
| Body-plan box | refines the box: hull ink, grid | coarse box on a whole-sheet overview |
| Centreline column | symmetry axis of the vertical grid lines; check: centre of the hull's widest extent | none |
| Horizontal lines | rows of long horizontal ink lines in the box | the printed label of each numbered line (height, "base") |
| Baseline row | the line labelled base, or the lowest full-width line | the label |
| px/ft, measure 1 | buttock line offsets from the centreline | the printed buttock offsets or spacing |
| px/ft, measure 2 | scan dpi x printed scale ratio, or scale-bar tick positions | the scale text or the scale-bar tick values |
| Station numbers per half | which half each label lies on | the station labels in each half |
| Side, check A | none | station numbering direction (which number is at the bow) from the profile, plan or table header |
| Side, check B | none | which half shows the stern (transom, counter, deadwood, shaft) or the stem, without numbers |

Rules:

- The two px/ft measures must agree within 1 %; otherwise the scale is flagged.
- The two side checks must agree; otherwise the side assignment is flagged for a person
  (BUMBLE BEE lesson, `tasks/lessons.md`: "Check the body-plan side assignment twice").
- Every value carries a source label (`code:...`, `model:...`, `person`); a disagreement is a
  flag in the result, never silent. A flagged calibration still produces a provisional layout, so
  that the person sees an overlay to correct.

## 4. Development truth (not holdouts any more)

Five hand calibrations, as written in the harnesses (whole-pixel rows, as run):

| Sheet | File (main checkout `work/sources/`) | Hand calibration source |
|---|---|---|
| Balclutha s7 | `balclutha_ca54_s7.tif` | `benchmarks/balclutha/crossing_value.py` + `tiled_value.py` |
| C.A. Thayer s4 | `haer/ca_thayer/loc_ca1506_sheet_04.tif` | `benchmarks/thayer/holdout_value.py` |
| BUE GIRL s2 | `haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif` | `benchmarks/bue_girl/holdout_value.py` |
| BUMBLE BEE s2 | `haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif` | `benchmarks/bumble_bee/holdout_value.py`, sides corrected (below) |
| PARDON ME s4 | `haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif` | `benchmarks/pardon_me/holdout_value.py` |

BUMBLE BEE sides. The round-13 calibration put the curves labelled STA 1-6 (left) as the forebody.
The truth table's station numbers fit the opposite halves (round-13 diagnosis): the left curves fit
table stations 9-14 and the right curves fit 1-8. The corrected development calibration is: aft
half left, outermost first 9, 10, 11, 12, 13, 14; fore half right, outermost first 8, 7, ..., 1;
all other values unchanged. (A plain swap that keeps 1-6 and 7-14 per half scores 0.429 m and is
not used.) The drawing's own labels put STA 1-6 on the left, so a label reading alone gives the
as-run (wrong) sides on this sheet; the second, independent side check must catch it.

Truth files (outside the repository):

| Sheet | Truth | Found |
|---|---|---|
| Balclutha | `<scratchpad>/wv-agent/balclutha/truth_s7.json` | yes |
| Thayer | `<scratchpad>/wv-agent/thayer/truth_s4.json` | yes |
| BUE GIRL | `/private/tmp/claude-501/bue-girl/truth_s2.json` | yes |
| BUMBLE BEE | `/private/tmp/claude-501/bumble-bee/truth_s2.json` | yes |
| PARDON ME | `/private/tmp/claude-501/pardon-me/truth_s4.json` | yes (extra, reported) |

`<scratchpad>` is this session's scratchpad folder; the paths are recorded in the measurement
script's output, not committed.

## 5. Metrics and targets

### 5.1 Per field, auto vs hand (all five sheets)

| Metric | Definition | Target |
|---|---|---|
| Centreline | abs(auto - hand) column, px | <= 3 px |
| Waterline rows | max over the hand waterline labels of abs(auto row - hand row), px; auto row = auto baseline - height x auto px/ft, snapped by the reader as usual | <= 4 px |
| px/ft | abs(auto - hand) / hand, % | <= 0.5 % |
| Side assignment | exact match of which half is fore; or flagged | exact or flagged on all 5; never wrong and unflagged |
| Station order | exact match of `stations_outer_first` per half | exact on 4 of 5; any miss flagged |

### 5.2 End to end, reader RMS with auto vs hand calibration

Code-only identity (R0, nesting order), the frozen reader, the harness scorer of each sheet, on the
four development sheets with truth (Balclutha, Thayer, BUE GIRL, BUMBLE BEE with corrected sides;
PARDON ME also reported). The truth's waterline heights are mapped to rows through the auto
calibration (baseline and px/ft), so a calibration error shows up in the score.

Hand-calibration baseline (code arm, measured 2026-11-09 on this branch):

| Sheet | Cells given | RMS m |
|---|---:|---:|
| Balclutha | 151 | 0.1480 |
| Thayer | 149 | 0.0116 |
| BUE GIRL | 37 | 0.0014 |
| BUMBLE BEE, as run (sides wrong) | 50 | 0.1141 |
| BUMBLE BEE, sides corrected | 50 | 0.1486 |
| PARDON ME | 34 | 0.1347 |

Target: on each sheet whose auto calibration is not flagged, auto RMS within 10 % (or 2 mm, the
larger) of the hand RMS, with the same cells given +-2. A flagged sheet is reported with the
provisional result and with the result after the person's choice of the flagged value.

### 5.3 Live app path

One run on BUE GIRL from intake, no hand steps, through the app's hull path (`scripts/run_round.py
--sheet-only` or the controller command it wraps). Report: whether the reader path was taken, the
calibration flags, and the RMS of the hull's station half-breadths at the truth cells vs the 1.4 mm
holdout result.

## 6. Steps (one commit each, with tests)

1. This plan.
2. `src/vessel_reconstruction/sheet_calibration.py` (code geometry) and
   `src/vessel_reconstruction/calibration_reading.py` (model questions and the Claude CLI
   transport). Unit tests on synthetic drawings and with a fake model.
3. Integration: intake runs the calibration and the frozen reader on a sheet with a body plan,
   writes the result and an overlay PNG beside `intake.json`; the worker's first hull uses the
   reader's station offsets for the stations it read (labelled as read from the drawing by code),
   and the model path for the rest. Behind a setting (off by default when risky). The review UI
   shows the overlay as one confirm item.
4. Measure: section 5 tables, then the live BUE GIRL run.

Resume point: the last committed step; the measurement script is
`benchmarks/auto_calibration/measure.py` (outputs outside the repository).

## 7. Rules for this work

No drawings or derived data in the repository; truth and runs stay outside it. Claude only through
the `claude` CLI on the subscription (API key variables removed). Never print keys. Status words
"approved" or "verified" are not used for results.

## 8. Integration (step 3, as built)

- Setting: `MARINAFRAME_BODY_PLAN_READER=1` in the environment of the app (or of
  `python -m vessel_reconstruction.intake write-spec`). Off by default: the intake then makes up to
  six `claude -p` label questions on the subscription (about 1 to 2 minutes per sheet).
- Intake (`intake.write_spec` -> `body_plan_intake.read_at_intake`): calibrates the spec page,
  runs the frozen reader with code-only identity (nesting order), and stores
  `body_plan_reading` in `intake.json` (calibration with source labels, flags and notes; per station
  the waterline cells and the drawn curve in metres). The overlay PNG and the cached answers stay in
  the intake folder. A failure is recorded, never raised.
- Worker (`first_hull_tools.build_first_hull` -> `body_plan_intake.reader_anchors`): when the
  calibration has no open flag, each section whose id names a station the reader read
  (`S7`, `sta_07`, `7`) gets the reader's curve as its anchor (row source `read`, built as an
  authored curve labelled `traced`, basis "Body-plan reader ..."). Other stations keep the model
  path (traced candidates, form fit). Station positions (x) still come from the model's reading.
  A flagged calibration is not used; the first hull's warnings say why.
- Review: the worker writes `domain/body-plan-check.json` and `domain/body-plan-check.png`. The
  app shows them at the top of the Checks tab ("Body-plan calibration": overlay with centreline,
  baseline, waterlines, FORE/AFT halves and their stations, the flags, and whether the reader was
  used). The person clicks "Calibration is right" or "Something is wrong"; the decision is saved
  like a part review (`review_component`, id `body_plan_calibration`), in app state, not in the run.
- Open: a person's "Something is wrong" does not yet re-run the build with a corrected calibration
  (for example swapped halves); it records the decision only.

## 9. Results (step 4, 2026-11-10)

Measured with `benchmarks/auto_calibration/measure.py`; two independent sets of model answers
(repeat 1 and repeat 2, each 4 to 6 `claude -p` calls per sheet on Claude Sonnet 5.5, subscription);
both repeats give the same table below. Outputs and truth stay outside the repository.

### 9.1 Per field, auto vs hand

| Sheet | Centreline px | Baseline px | Waterline rows max px | px/ft % | Side | Station order | Open flags |
|---|---:|---:|---:|---:|---|---|---|
| Balclutha | -0.8 / +0.5 | +4.5 / +0.8 | 5 / 2 | +0.13 | exact | exact | none |
| Thayer | 0.0 | -0.5 | 1 | 0.00 | exact | exact | none |
| BUE GIRL | 0.0 | 0.0 | 0 | 0.00 | exact | exact | none (note: baseline unlabelled) |
| BUMBLE BEE (sides corrected) | 0.0 | 0.0 | 9 (a) | 0.00 | wrong, **flagged** | differs (b) | sides: labels say fore left, shapes say fore right |
| PARDON ME | 0.0 | 0.0 | 0 | 0.00 | exact | exact | none |

(a) The 1-6-0 row is put on the drawn line 9 px below the nominal row; the reader searches +-20 rows
and snaps there in both calibrations. (b) The drawing labels STA 1-6 left; the truth's numbering
puts 9-14 left and 1-8 right (section 4). The automatic calibration cannot renumber; it flags.

Targets met: centreline <= 3 px, px/ft <= 0.5 %, side never wrong and unflagged, station order
exact on 4 of 5 (miss flagged). Missed: waterline rows <= 4 px on Balclutha repeat 1 (5 px; scale
from the printed 3/8" ratio, 0.13 % above the drawn grid) and BUMBLE BEE (9 px, see (a)).

### 9.2 End to end, frozen reader with code-only identity

| Sheet | Hand: cells, RMS m | Auto: cells, RMS m | Auto geometry + corrected sides |
|---|---|---|---|
| Balclutha | 151, 0.1480 | 151, 0.1480 / 0.1479 | same |
| Thayer | 149, 0.0116 | 149, 0.0116 | same |
| BUE GIRL | 37, 0.0014 | 37, 0.0014 | same |
| BUMBLE BEE | 50, 0.1486 (corrected sides) | 51, 0.1273 (provisional, flagged, not used for a build) | 51, 0.0129 (c) |
| PARDON ME | 34, 0.1347 | 34, 0.1347 | same |

(c) Better than the hand calibration because the automatic grid includes a near-vertical stretch of
the outer aft curves at column 4786 as a grid column; the reader then skips one duplicated chain.
This is luck of one sheet, not a method: a station curve read as a grid line can also lose cells.

### 9.3 Fixes found on the way (all in new modules, the reader is unchanged)

- A model-tagged centreline can be a keel or post edge next to it (BUE GIRL live: 66 px off, 5 cm
  RMS). Without a symmetric grid the longest vertical line next to the tag is used, with a note.
- Unlabelled waterlines: only the evenly spaced lattice is read (a painted waterline or another
  view's lines changed the nesting order: 0.24 m RMS in the first live intake).
- Vertical frame lines inside a grown box are not buttocks and bound the reader's search.
- The worker reads at most 16 Mpx; a full HAER scan is 138 Mpx and stopped the run at
  survey_sheet. Intake now gives the worker a reduced page and keeps the original for the reader.
