# Drawing-set intake: sheet types, checklist, scale

Status: built (steps 1 to 5), 2026-11-10. Branch `feature/drawing-set-intake`. `engineering_approved` is
false for every result here. No status in this feature says "approved" or "verified".

PM/CEO review section 2 item 2: a customer drops 10 to 40 mixed sheets, not one. The intake must
know what each sheet is, tell the person which drawings the set lacks, and check scale per sheet and
across sheets. Clean-room: this design comes from the lane brief and our own labelled sheets.

## 1. Sheet types

| id | Meaning | Short label |
|---|---|---|
| `lines_plan` | lines plan, sheer plan, half-breadth plan, body plan, table of offsets | Lines |
| `general_arrangement` | GA, deck and arrangement plans | GA |
| `profile` | outboard or inboard profile (no hull lines) | Profile |
| `midship_section` | midship or transverse section | Midship |
| `shell_expansion` | shell expansion, shell plating | Shell |
| `construction_profile` | structural profile, decks, framing plans | Structure |
| `tank_plan` | tank plan, capacity plan, sounding tables | Tanks |
| `hydrostatics` | hydrostatic booklet or tables, curves of form | Hydro |
| `other` | title sheet, rigging, machinery, details | Other |

A sheet has one type. A lines plan sheet that also shows a sheer profile counts as `lines_plan`
(see the checklist rule for profile).

Every type result is `{type, confidence, source, evidence, alternatives}`. `source` is one of
`text:<where>` (PDF text layer or OCR), `file_name`, `layout`, `model:claude-sonnet-5-5` or `person`.
Confidence is 0 to 1 and is a code proposal, not a certificate.

## 2. Checklist per output

Each item is `{output, need, drawing, level, status, met_by}`. `level` is `required` or `recommended`;
`status` is `met` or `missing`; `met_by` lists page ids. A missing required item does not block the
run: the run goes on and the output is labelled with what it lacked (product principle: fill gaps).

| Output | Required | Recommended |
|---|---|---|
| Hull | lines plan (lines or body plan); profile | general arrangement |
| Tanks | tank or capacity plan | general arrangement, profile |
| Steel | midship section; shell expansion | construction profile and decks |
| Booklet check | hydrostatic tables | lines plan, tank plan |

"Profile" is met by a `profile`, `construction_profile` or `general_arrangement` sheet, or by a
`lines_plan` sheet whose text names a sheer plan or profile. The `met_by` note says which.

## 3. Scale

Per sheet: the printed scale (`1:100`, `1/16" = 1'-0"`, `SCALE 1:50`) read from the PDF text layer or
OCR; `source` says which. With the page size (PDF points, or pixels and dpi) this gives millimetres of
paper per drawn millimetre. Status: `read` (printed scale found), `missing` (none found), `mixed`
(several scales on one sheet, as on a detail sheet; the main one is the most frequent).

Across sheets: sheets that show the whole hull length (lines, profile, GA, tank plan) give a length
estimate = drawn hull length x scale. Estimates are compared; the set agrees when the spread of the
estimates is within 5 %. A sheet whose estimate differs from the median by more than 5 % becomes a
check item (`scale_disagrees`) with both numbers; it is not a failure. A printed LOA or LBP in the
same text, when found, is a second reference.

## 4. Metrics (development sets)

Labels are ours, in the git-ignored `work/drawing_set/labels.json` (built by
`work/drawing_set/make_labels.py` from sheet titles and crops; README scale table for Gunnerus).

| Set | Sheets | Notes |
|---|---|---|
| Gunnerus polarkonsult PDFs | 6 | vector PDFs with a text layer; scale labelled from the set README |
| HAER sheets (`work/sources/haer`): C.A. Thayer, Wapama, Pardon Me, Bumble Bee, Bue Girl | 66 | 1-bit scans, no text layer |
| tanks-public: Huddell, Empire State V, Saugatuck, Liberty capacity plans | 42 | scans; Liberty are photographic |

Total 114 labelled sheets. There is no hydrostatic booklet in the development sets: `hydrostatics`
is tested only on synthetic text (unit tests), and the accuracy table says so.

Metrics:

1. Type accuracy: share of sheets whose proposed type equals the label, overall, per type (recall and
   precision), with and without the file name as a feature (a customer's file names are often useless).
2. Share of sheets that code settled alone, and how many needed the vision question (and its accuracy).
3. Scale: share of Gunnerus sheets whose printed scale read equals the label; share of sheets with a
   printed scale read at all; across-sheet agreement per set (spread of the length estimates, and how
   many sheets became check items).
4. Checklist: on each ship's set, the checklist computed from proposed types equals the checklist from
   the labels (items met / missing).

A result is only reported if the evaluation ran in this branch (`benchmarks/drawing_set/evaluate.py`).
Results are in section 7 (step 5).

## 5. Other lane

"Replace a bad sheet and resume" (run state, revisions, review UI) is another lane. This work only
exposes per-sheet results on the preview: `page.sheet = {type, confidence, source, evidence, scale}`
and `preview.set = {checklist, scale_agreement}`. They are plain JSON; a revised sheet is retyped by
calling the same functions on one page.

## 6. Interfaces

* `vessel_reconstruction.sheet_types.type_sheet(page) -> dict`
* `vessel_reconstruction.sheet_scale.read_scale(page) -> dict`, `scale_agreement(sheets) -> dict`
* `vessel_reconstruction.drawing_set.analyse(pages) -> dict` and `checklist(sheets) -> list[dict]`
* `intake.prepare` adds the results to each page and to the preview.

## 7. Results (development sets, 114 sheets, run 2026-11-10)

Commands: `PYTHONPATH=src:. .venv/bin/python -m benchmarks.drawing_set.evaluate_types` and
`... evaluate_scale`. The keyword weights and thresholds were set while looking at these same sheets, so
these are development numbers, not holdout numbers. Labels are ours and some are arguable (for example
exploded construction views of Wapama are labelled `other`; two HAER deckhouse sheets with an "inboard
profile" heading are labelled `other`).

### 7.1 Sheet type

| Mode | Correct | Settled by code (confidence 0.7 or more) | Correct among those | Unsure |
|---|---|---|---|---|
| Page lettering only (no file name) | 100 of 114 (87.7 %) | 94 | 89.4 % | 20 |
| Lettering and file name | 104 of 114 (91.2 %) | 105 | 91.4 % | 9 |

Per type, no file name (recall / precision): lines plan 18 sheets 1.00 / 0.95; general arrangement 12,
0.75 / 0.75; profile 9, 1.00 / 0.75; midship section 12, 1.00 / 0.80; shell expansion 1, 0.00 (read as
midship section: the sheet repeats "section frame"); construction profile 3, 0.67 / 1.00; tank plan 14,
0.93 / 0.93; other 45, 0.82 / 0.93. Hydrostatic tables: 0 sheets in the development sets, tested on
synthetic text only. Main confusions: HAER arrangement and profile sheets whose notes name tanks, and
exploded construction views (read as lines or midship).

The model question was **not measured**: the live call to the Claude CLI (`claude-sonnet-5-5`, subscription)
failed with the weekly limit (HTTP 429) on 2026-11-10 for all 20 unsure sheets. The transport, prompt and
fallback are covered by unit tests with a fake transport. `benchmarks/drawing_set/evaluate_vision.py`
measures it when the limit resets (it asks only the sheets code leaves below 0.7).

### 7.2 Scale

Printed scale read from the sheet text or OCR (the whole page, then the bottom and right strips at high
resolution):

| Set | Sheets with a printed scale read |
|---|---|
| Gunnerus (vector PDF) | 6 of 6 |
| C.A. Thayer (HAER scans) | 21 of 37 |
| Wapama | 2 of 21 |
| Huddell | 1 of 20 |
| Empire State V | 3 of 13 |
| Saugatuck, Liberty, Pardon Me, Bumble Bee, Bue Girl | 0 of 14 |
| All | 34 of 114 (30 %) |

On the six Gunnerus sheets with a labelled scale, the main printed scale equals the label on 5 and the
label is among the read scales on 6 (Shell Expansion prints 1:25, 1:50 and 1:10; the most frequent is
1:25 and the sheet is marked `mixed`). The HAER scans print the scale as a fraction ("1/16" = 1'-0"") and
a scale bar; OCR drops the fraction, so the scans mostly read as `missing`. Reading the scale bar on
scans is open (the calibration lane reads scale bars with model-labelled ticks, `calibration_reading.py`).

Cross-sheet agreement could **not** be shown on these sets: no set has two whole-hull sheets with a
printed scale (at most one length estimate per set). On the one sheet with both a scale and a printed
length (Gunnerus lines plan, printed length overall 36.25 m) the estimate is 81.8 m at the printed
1:100; at 1:50 it would be 40.9 m, 13 % above the printed length because the view box includes
dimension lines and overhangs. The sheet is probably drawn at 1:50 while its text says 1:100 in another
place; we have no truth for that. This is why the agreement tolerance is 15 % and why a difference is a
check item. Agreement and the check items are covered by unit tests on synthetic estimates.

### 7.3 Checklist

On the 13 ship sets (156 items), the checklist from proposed types (no file name) equals the checklist
from the labels on 149 items (95.5 %). The 7 differences are on two sets. Gunnerus (3 items): the shell expansion is read as a midship section,
so `steel_shell` shows missing. Wapama (4 items): exploded construction views are read as a midship section
and as a profile or arrangement sheet, so `steel_midship`, `hull_profile` and two recommended items show
met when the labels say missing. The list of missing required drawings equals the labelled list on 11 of
13 sets; both differences come from a wrong sheet type, not from the rules.

### 7.4 Open

* Model question for unsure sheets: measure when the subscription limit resets.
* Scale bars and fraction scales on scans (OCR drops the leading fraction).
* A drawn-length estimate that excludes dimension lines, then re-measure agreement on a set with several
  scaled whole-hull sheets (Gunnerus has six, but only one reads a length).
* No development set has a hydrostatic booklet.
* The replace-a-sheet lane can call `sheet_result` (in `intake.py`) for a single page.
