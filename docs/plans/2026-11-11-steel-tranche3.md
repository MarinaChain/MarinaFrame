# Steel structure: tranche 3 development protocol (lane F, step 2)

Plan: `docs/plans/2026-11-09-whole-vessel-scope.md` section 4. Metrics and development targets
are those of section 4.3.1 and 4.3.3, unchanged. Development figures only; every output has
`engineering_approved=false`. This protocol is committed before any build or score.

## 1. Inputs and join

- CAD (truth geometry): tranche 3 development staging `work/midship-tranche3/staging/dev`, listed
  by `plan_dev.jsonl` (463 designs, each with full IGES, mesh IGES and Rhino on disk).
- Drawings and BOM: previously held, non-sealed files under `work/midship-remainder/loose`
  (`Repaired_Structures`, `SGLD_Gen_Structures`; drawings in `Dataset_Drawings`). Joined by subset
  and design id: `sgld_design_<id>_*` and `repaired_random_design_design_<id>_*`.
- A design is covered when it has all three CAD files, the three plain PDFs
  (`Midship Section of Long. Structure`, `Midship Section IWO of Web Frame`,
  `Transverse Bulkhead`) and the BOM (`*_Structural_Elements.csv`).

Coverage (2026-11-11; counts of development designs):

| Subset | Ship type | Dev designs | CAD (3 files) | Drawings (3 PDFs) | BOM | All three |
|---|---|---|---|---|---|---|
| Random | bulk_carrier | 51 | 51 | 0 | 0 | 0 |
| Random | container_ship | 51 | 51 | 0 | 0 | 0 |
| Random | tanker | 51 | 51 | 0 | 0 | 0 |
| Repaired | bulk_carrier | 52 | 52 | 14 | 51 | 14 |
| Repaired | container_ship | 51 | 51 | 17 | 51 | 17 |
| Repaired | tanker | 51 | 51 | 20 | 51 | 20 |
| SGLD | bulk_carrier | 52 | 52 | 48 | 52 | 48 |
| SGLD | container_ship | 52 | 52 | 46 | 52 | 46 |
| SGLD | tanker | 52 | 52 | 47 | 52 | 47 |
| All | all | 463 | 463 | 192 | 309 | 192 |

Missing: the loose area has no `Random_Structures` folder, so the three Random cells have no
drawings and no BOM. 117 Repaired designs have a BOM but no drawings.

No loose IGES has the same id as a staging IGES, so the CAD and the BOM come from different
folders. Identity check (fixed now): per design, the share of BOM `struct_rsObject` keys found as
IGES entity names. A design below 0.95 is listed; below 0.5 the pair is taken as not the same
design and is excluded from pooled figures and listed.

## 2. Fixed sample

All 192 covered designs minus the W3 sealed test split (`midship_eval.SPLIT["test"]`: SGLD 17,
257, 308, 205, 381 are in the join; the scorer refuses W3 sealed designs). 187 designs, none in
the W3 development split or the step 2 development set of section 4.3.1:

| Subset | Ship type | n | Design IDs |
|---|---|---|---|
| Repaired | bulk_carrier | 14 | 558, 5343, 5344, 5485, 5608, 5609, 5661, 5702, 5714, 5779, 5782, 5994, 6180, 6232 |
| Repaired | container_ship | 17 | 751, 755, 945, 950, 984, 5412, 5424, 5530, 5540, 5805, 5856, 5857, 5918, 6110, 6114, 6115, 6205 |
| Repaired | tanker | 20 | 564, 585, 685, 707, 861, 938, 5210, 5211, 5250, 5337, 5360, 5512, 5581, 5595, 5670, 5681, 5802, 5934, 5950, 6170 |
| SGLD | bulk_carrier | 46 | 1, 15, 36, 43, 103, 131, 132, 136, 139, 140, 153, 156, 164, 182, 216, 217, 223, 234, 236, 239, 243, 246, 252, 255, 258, 285, 286, 356, 364, 368, 371, 390, 394, 397, 399, 415, 421, 422, 434, 438, 443, 449, 457, 463, 481, 485 |
| SGLD | container_ship | 45 | 11, 20, 31, 39, 47, 102, 105, 110, 141, 143, 163, 175, 177, 180, 190, 199, 221, 226, 293, 297, 303, 309, 314, 324, 332, 339, 348, 349, 357, 360, 377, 388, 389, 405, 408, 409, 411, 432, 440, 452, 455, 459, 460, 475, 482 |
| SGLD | tanker | 45 | 22, 29, 121, 122, 145, 152, 154, 169, 187, 188, 193, 195, 207, 219, 224, 232, 233, 242, 247, 249, 250, 266, 269, 277, 283, 294, 299, 329, 334, 335, 337, 342, 378, 384, 387, 395, 403, 420, 425, 428, 446, 450, 454, 478, 479 |

This replaces the earlier draft sample of 7 per cell (it included the uncovered Random cells and
was never run).

## 3. Measurement

Builder input: the three plain PDFs only (`block3d.build_block`, no BOM, no slice table, no CAD).
Truth: the staging full IGES and the loose BOM, read by `block_eval.load_truth`; matching,
labels, groups and pads of section 4.3.1 through `block_eval.score_design` and `summarise`.

Reported pooled and per subset and ship-type cell:

| ID | Metric | Development target (section 4.3.1, not a gate) |
|---|---|---|
| S1 | precision, recall, F1; recall per truth group, precision per predicted group | F1 >= 0.80; longitudinal recall >= 0.95; transverse recall >= 0.60 |
| S2 | typed F1 per label and macro | report |
| S3 | centre distance median, p95, max; transverse x error | median <= 50 mm |
| S4 | printed thickness exact rate by group, cut-to-mm agreement, abs error; guessed diagnostic | report |
| S5 | per-design steel volume relative error; median abs | <= 10 % |
| S6 | members by placement source | report |

Also: build errors (designs with no block), identity join rate, and OCX (section 4.3.3): every
block exported, checked against the OCX 3.0.1 XSD and read back (plate count, thickness, area).
The VLCC parser check is repeated only if its sample file is on disk; otherwise reported missing.

Scantling statistics per ship type and per cell, predicted block against BOM (counts, units,
missing values and denominators stated):

- Plates (BOM `Type` not `Stiffener`; predicted labels bottom_shell, side_shell, shell_strake,
  deck, longitudinal_bulkhead, hopper_plate, transverse_bulkhead, floor, bracket): thickness in
  whole mm, by count and by area share; median; total variation distance (TVD) between the two
  normalised distributions.
- Stiffener webs (BOM `Type` `Stiffener` without flanges; predicted other labels except flange):
  profile `web height (10 mm bins) x thickness (mm)`, counts, TVD; flanges separately as
  `width x thickness`. Predicted web height: the printed table row of the member when it has a
  height, else the member's in-section box extent.

Script: `benchmarks/steel_t3/run.py` (metrics) and `benchmarks/steel_t3/scantlings.py`
(statistics). Outputs in this worktree's git-ignored `work/steel-t3/`; no per-ship data in git.

## 4. Iteration rule

1. Baseline on the full sample with the committed code.
2. Take the first common failure: the largest loss in S1 transverse recall or typed F1 shared by
   several cells. Fix it in `src/vessel_reconstruction/structure` with a unit test on synthetic
   data. A guess changes only when a printed or drawn value replaces it, never from the BOM.
3. Re-run the same sample and metrics. Repeat while a fix moves a pooled metric.
   Amendment (2026-11-11, after the baseline, before fix 1; no target changed): "never from the
   BOM" means never from the BOM of a sample design. A generator convention may come from a BOM
   survey of designs outside the sample and outside the W3 sealed split, as the section 4.3.1
   guesses did. Fix 1 uses such a survey (812 loose BOMs).
4. The targets above do not change. Lane boundaries: no edits to body_plan readers,
   `panel_assignment.py`, `form_fit.py` or the model reading path.

## 5. Results (2026-11-11; 187 designs, 186 built)

Commands (outputs in git-ignored `work/steel-t3/<label>/`; 40 s without OCX, about 4 min with):

    PYTHONPATH=src:. <venv>/python -m benchmarks.steel_t3.run --label final --ocx
    PYTHONPATH=src:. <venv>/python -m benchmarks.steel_t3.scantlings --label final

Build error in every run: Repaired 6205 (view 3 gives no plate). Identity: every design joins
all BOM objects to the staging IGES (join rate 1.0); none excluded.

Pooled (targets of section 4.3.1, unchanged):

| Metric | Baseline | Fix 1 | Fix 2 | Fix 3 (final) | Target |
|---|---|---|---|---|---|
| S1 P / R / F1 | 0.431 / 0.396 / 0.413 | 0.462 / 0.424 / 0.442 | 0.473 / 0.434 / 0.453 | 0.475 / 0.447 / **0.461** | F1 >= 0.80: missed |
| S1 longitudinal recall (precision) | 0.908 (0.911) | 0.995 (0.998) | same | **0.995** (0.998) | >= 0.95: met |
| S1 transverse recall (precision) | 0.272 (0.302) | 0.286 (0.318) | 0.299 (0.332) | **0.314** (0.339) | >= 0.60: missed |
| S2 typed macro F1 | 0.667 | 0.701 | 0.731 | 0.734 | report |
| S3 centre median / p95 (mm) | 15.9 / 9,066 | 19.1 / 539 | 17.9 / 517 | **16.2** / 509 | median <= 50: met |
| S3 transverse x median (mm) | 2.6 | 2.7 | 2.7 | 2.6 | report |
| S4 printed exact, longitudinal (cut to mm) / transverse | 0.758 (0.997) / 0.996 | 0.766 (0.997) / 0.993 | 0.766 / 0.994 | 0.766 (0.997) / 0.996 | report |
| S5 volume, median abs rel. error | 5.1 % | 4.7 % | 3.6 % | **3.1 %** | <= 10 %: met |
| S6 traced / guessed members | 82,192 / 224,504 | same | 86,200 / 220,496 | 86,200 / 227,952 | report |
| OCX schema valid / round trip equal | 186 / 186 | | | 186 / 186 | all |

VLCC parser check: 523 plates read, all with thickness.

Final per cell (S1 F1; longitudinal recall; transverse recall; S3 median mm; S5):

| Cell | n | F1 | Long. R | Trans. R | S3 med | S5 |
|---|---|---|---|---|---|---|
| Repaired / bulk_carrier | 14 | 0.236 | 0.978 | 0.021 | 336 | 5.1 % |
| Repaired / container_ship | 16 | 0.248 | 0.986 | 0.052 | 443 | 10.6 % |
| Repaired / tanker | 20 | 0.288 | 0.995 | 0.109 | 246 | 9.3 % |
| SGLD / bulk_carrier | 46 | 0.525 | 0.997 | 0.393 | 13.6 | 1.5 % |
| SGLD / container_ship | 45 | 0.623 | 0.998 | 0.515 | 4.7 | 3.1 % |
| SGLD / tanker | 45 | 0.503 | 0.998 | 0.379 | 15.6 | 3.3 % |

Baseline per cell F1: Repaired 0.128 / 0.193 / 0.159; SGLD 0.483 / 0.599 / 0.492 (same order).

Scantlings (final; whole mm and 10 mm bins; counts are built members against BOM rows; no
missing thickness on either side):

| Ship type | Designs | Plate TVD count / area | Plate median mm built / BOM | Web profile TVD | Flange TVD |
|---|---|---|---|---|---|
| bulk_carrier | 60 | 0.013 / 0.037 | 21 / 21 | 0.456 | 0.283 |
| container_ship | 61 | 0.030 / 0.077 | 20 / 20 | 0.502 | 0.412 |
| tanker | 65 | 0.004 / 0.010 | 21 / 21 | 0.508 | 0.365 |

Plate thickness distributions agree (most common built 21/22/18 mm against BOM 21/22/18 mm for
bulk carriers). Stiffener web profiles do not: the most common built profiles are the guessed
ordinary-frame scantlings (for example 320x10 mm against BOM 260x10 and 270x10 mm); web counts
are 82 % of the BOM rows (162,441 against 199,085).

Fixes (each with a unit test in `tests/test_structure_block3d.py`):

1. `b010539` Block length guess: 40 m when 27 web spaces at the printed spacing fit with 0.8 web
   spaces at each end, else holds plus 1.2 web spaces at each end (BOM survey of 812 loose designs
   outside the sample and W3 sealed split; exact lengths on the survey 269 against 220 for a
   median-only rule). Repaired blocks are 41 to 80 m; the 40 m guess put bulkheads outside the
   block. A first version (always holds plus 1.2 margin) lost SGLD transverse recall (0.382 to
   0.299), so the 40 m point mass was kept.
2. `bd5ff77` Brackets fill the hopper spaces of view 3 (167 of 168 hopper designs then match the
   truth bracket section; 7 before); deck beams span the upper deck plate of view 3.
3. `fdbe22c` Bulkhead stiffener rows from the bulkhead sheet: the web-frame sheet's
   "Vert. BLKHD Stiff." row replaced it in 53 of 186 designs.

Findings:

- Repaired transverse recall stays low (0.02 to 0.11): the end margin is random (0.7 to 1.5 web
  spaces) and not printed, so bulkheads and webs shift by more than the 33 mm that IoU 0.5 allows
  for a padded plane. 34 of 460 surveyed Repaired designs also have 6 to 8 web spaces per hold.
- The largest remaining losses (flanges 105,541, ordinary frames 54,724 truth members missed) come
  from the frame spaces per web space (5, 4 or 3; not printed) and the guessed frame scantlings.
- Repaired container ships: transverse thickness exact 0.28 is a pairing effect (shifted floors
  match ordinary bottom frames under label-agnostic matching), not a thickness misread.
- Not done: deck girders interrupted at hatches (truth pieces only near bulkheads; hatch length not
  printed), the web-frame sheet's own "Vert. BLKHD Stiff." member, Random cells (no drawings).

## 6. Resume point

Done: join, protocol (`235dea6`), scripts (`f5d5f59`), baseline, fixes 1 to 3, final run with OCX.
Next, in order: (1) read ordinary-frame count or spacing if any sheet linework shows it (check
view 2 and view 1 linework before guessing again); (2) model the web-frame sheet's
"Vert. BLKHD Stiff." member (truth class `Longitudinal_Bulkhead_Vertical_Stiffener`?); (3) get
Random drawings and BOMs into permitted development staging to cover the three Random cells.
Check after each step: `python -m benchmarks.steel_t3.run --label <next>` and compare with
section 5.
