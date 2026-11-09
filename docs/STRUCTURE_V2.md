# Structure v2: a 3D cargo-hold block from the MiDShip drawings (whole-vessel step 2)

Plan: `docs/plans/2026-11-09-whole-vessel-scope.md` section 4; metrics S1 to S6 fixed in section
4.3.1 before the build (commit `7225a67`). Development figures only: there is no sealed 3D split.
Every output has `engineering_approved=false`. Resume point: section 5.

## 1. Method

Code: `src/vessel_reconstruction/structure/block3d.py` (layout) and `block_eval.py` (scorer).
Input per design: the three plain PDFs. Nothing else reaches the reader.

1. View 3 (longitudinal structure): the frozen W3 reader (`docs/STRUCTURE_V1.md`) gives plates,
   girders, stiffener webs and flanges in the section plane. Each member is swept over the block.
2. Tables of views 1, 2 and 3 (now with the spacing column): web-frame spacing; `Webframe`,
   `Floor` and `Deck_Transvere_Beam` scantlings; bulkhead stiffener count, spacing and scantling;
   `Trans. BLKHD`, `Upper Bracket` and `Lower Bracket` plate thickness.
3. Stations: 4 bulkheads (3 holds) centred in the block, 9 web spaces per hold at the printed
   spacing, 5 ordinary frame spaces per web space.
4. Transverse members, each an axis-aligned mid-plane box with its thickness: bulkhead plate
   (section extent from view 3), vertical and horizontal bulkhead stiffeners with flanges (web on
   the +x side), floor (base to inner bottom), web frame on the side shell span with its flange,
   deck beam with its flange, lower and upper brackets, and an ordinary frame on every plate that
   carries longitudinal stiffeners in view 3 (scantling of that plate's stiffener row; an open
   floor from the bottom to the inner bottom in a double bottom; outboard webs on an inner side
   shell).
5. IDs are stable: `L/<host>/<role>/<n>` for longitudinal members, `BH<k>/...` for bulkheads,
   `FR<nnn>/...` for members at frame `nnn` counted from the first bulkhead.

Labelled guesses (the drawings do not print them): block length 40 m, 3 holds, 9 web spaces per
hold, 5 frame spaces per web space, bracket legs 0.6 and 0.5 of the web depth, ordinary-frame
scantlings, stiffener side. The first four are the generator conventions of a BOM survey of the
488 SGLD designs outside the W3 sealed split (plan section 4.3.1).

## 2. Results (12 development designs, SGLD with 3D: 18,244 truth members)

Command: `python -m vessel_reconstruction.structure.block_eval --root work/sources/midship --out
work/step2/dev_final.json` (8 s). The diagnostic row replaces the two generator guesses (block
length, frame spaces per web space) with the values from the truth BOM (`--oracle-guesses`): it
shows what the guesses cost and is not a product result.

| Metric | Result | Diagnostic: true block length and frame count | Target |
|---|---|---|---|
| S1 detection P / R / F1 | 0.480 / 0.474 / **0.477** | 0.784 / 0.711 / 0.746 | F1 >= 0.80: **missed** |
| S1 longitudinal recall (precision) | **0.997** (1.000) | same | >= 0.95: met |
| S1 transverse recall (precision) | **0.346** (0.350) | 0.641 (0.724) | >= 0.60: **missed** |
| S2 typed macro F1 | 0.779 | 0.912 | report |
| S3 centre error median / p95 / max (mm) | **10.4** / 197 / 1,050 | 5.5 / 133 / 1,926 | median <= 50: met |
| S3 transverse x error median / p95 (mm) | 2.1 / 62 | 0.8 / 4.8 | report |
| S4 printed thickness exact, longitudinal (cut to mm) | 0.695 (0.997) | same | report |
| S4 printed thickness exact, transverse | 0.999 (3,324 members) | 0.998 | report |
| S4 guessed thickness exact (diagnostic) | 0.045 | 0.118 | report |
| S5 steel volume, median abs relative error | **4.1 %** (range -15.1 % to -0.2 %) | 4.3 % | <= 10 %: met |
| S6 members by placement source | 4,773 section and spacing traced; 13,256 use a guess | | report |

Typed F1 (main result): bottom shell, side shell, shell strake 1.000; stiffener web 0.969;
girder 0.911; deck 0.917; hopper plate 0.923; longitudinal bulkhead 0.933; bulkhead stiffener
0.904; transverse bulkhead, floor, web frame 0.750; deck beam 0.656; bracket 0.350; flange 0.399;
ordinary frame 0.249.

Findings:

- The longitudinal structure carries over from W3 unchanged: recall 0.997, precision 1.000.
- Where the guesses hold, the transverse members sit within millimetres (bulkheads, floors, web
  frames, deck beams: typed F1 1.000 in the diagnostic). The misses come from two values the
  drawings do not print: the block length (3 of 12 designs are 0.12 to 1.66 m longer than 40 m:
  their bulkheads and webs shift by half the excess and fail the 50 mm pad) and the frame spaces
  per web space (5 in 5 designs, 4 in 7: all ordinary frames of a design fail when it is wrong). An AI reader
  cannot fill these either: no sheet shows them.
- The printed web spacing is cut to 1 mm; over 26 web spaces the x error grows to about 13 mm.
- Thickness: printed transverse values are exact (0.999). Longitudinal values match the truth cut
  to whole millimetres (0.997); the exact rate is lower because the BOM holds fractions (as W3).
- Remaining structural gaps: deck girders interrupted by hatch openings (bulk carriers),
  container-ship brackets (four-sided, not the guessed triangle), the open-floor flange.
- Steel volume is within 4.1 % (median) although only half the members match: the volume is
  dominated by plates and printed scantlings.

## 3. OCX export

Not done in this step (no time left). `xmllint` is on the machine for the XSD check; the export
needs a Panel/Plate writer for the block members (plan section 4.3.3).

## 4. Data and rules

- MiDShip is GPL-3.0 data; it stays in `work/sources/midship` (git-ignored). Only metrics are here.
- The W3 sealed designs (SGLD 118, 215 with 3D) are refused by the scorer and were not opened.

## 5. Resume point

1. A sealed 3D split from the next MiDShip tranche, drawn before any new code.
2. Read brackets, the floor openings and hatch openings from view 2 and view 3 linework
   (now guessed or missing).
3. OCX export of the block (plan section 4.3.3).
