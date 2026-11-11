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

## 5. Results

(Filled after the runs.)

## 6. Resume point

Protocol committed. Next: write `benchmarks/steel_t3/run.py` and `scantlings.py`, run the
baseline, record it in section 5.
