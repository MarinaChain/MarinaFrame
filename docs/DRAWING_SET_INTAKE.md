# Drawing-set intake: sheet types, checklist, scale

Status: plan (step 1), 2026-11-10. Branch `feature/drawing-set-intake`. `engineering_approved` is
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

## 7. Results

(To be written in step 5.)
