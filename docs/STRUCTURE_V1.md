# Structure v1: members from the MiDShip midship section drawing

Workstream W3. Owner of `src/vessel_reconstruction/structure/` and `tests/test_structure_*.py`.
Sections 1 to 4 were written and committed **before** the extraction code. The results in
section 6 come from one run of frozen code on the sealed split. Resume point: section 8.

## 1. What the data contains (from inspection of development designs only)

Source: `work/sources/midship/` (36 designs, see `selection.md`; git-ignored, never committed,
never sent to a provider). Inspected visually: Random 5597 (all three views, plain and
annotated), Random 2870, Random 3498, Repaired 2313, SGLD 37, SGLD 473 (annotated).

**Drawings.** Each design has three single-page A3 landscape PDFs (1190.64 x 841.92 pt =
420 x 297 mm), each with a plain and a `_with_BBoxes` version:

| View | Shows |
|---|---|
| `Transverse Bulkhead` (dwg 1 of 3) | Bulkhead outline; vertical and horizontal bulkhead stiffeners as dashed lines |
| `Midship Section IWO of Web Frame` (2 of 3) | Outline at a web frame: deck, side, double bottom, brackets, web frame, floor |
| `Midship Section of Long. Structure` (3 of 3) | Half-breadth section between frames: plates as single lines; longitudinal stiffeners as web + flange lines |

Every view has a printed scale (`1 m = 12.91 mm`), a title block, a plate table
(plate, thickness [mm], material) and a stiffener table (class, number, spacing [m],
`Shape-H x W x t`, material). The section is half-breadth: centreline at the left, side shell
at the right, baseline at the bottom. Plates and stiffener webs are drawn as zero-width
centre-lines. Thickness is **not drawn**; it is printed only in the tables. Web height and flange
width are drawn to scale.

**Vector status.** All 108 plain PDFs are vector: a count-only check (no content read) found at
least 20 paths from PyMuPDF `get_drawings()` and no embedded image on every page. Design 5597
has 59 (view 2) to 1,929 (view 1) paths. In design 5597, view 3: 216 stroked paths, all
black, width 0.24 pt; 211 are single straight lines; the bottom shell with its bilge is one
path of Bezier curves and a line. Text is a real text layer.

**Ground truth (per design).**

- `*_Slice_Elements.csv`: one row per structural element per view, with `struct_elem_idx`
  (row of the BOM), `Ship2Dwg_Scale [1m:Xmm]`, and the element's axis-aligned box in ship
  metres (`bbox_y`, `bbox_z`, `bbox_Ly`, `bbox_Lz`) and in drawing millimetres
  (`bbox_dwg_mm_*`). Boxes are padded by 1 drawing-mm on each side (a zero-width line has a
  2 mm box). Rows with an empty box are not drawn in that view (for example deck girders in a
  hatch opening). On the development designs no two drawn rows share a box.
- `*_Structural_Elements.csv` (BOM, 33 fields): `Class`, `Type`, `Thickness` (m), `L1`
  (length along the ship), `L2` (web height or flange width, or plate breadth), location,
  direction, section properties. Example: Side shell `Thickness=0.034` matches the printed
  `34 mm`.
- `*_Drawing_Annotations.csv`: drawing furniture only (borders, title, table cells).
- `.3dm`/`.igs` (12 designs): the same Rhino model as the BOM. v1 does not need them; the
  BOM and slice table are exports of that model with the same object IDs.

**Drawing to ship coordinates.** With page point (x, y) and printed scale s (mm per m):
`x_mm = x * 25.4/72`, `z_mm = 297 - y * 25.4/72`, and
`y_ship = (x_mm - o_y)/s`, `z_ship = (z_mm - o_z)/s`, where (o_y, o_z) is the drawing position
of the centreline at the baseline. Checked on 5597: the main-deck line at page y = 85.11 pt
predicts z = 18.36 m against BOM 18.361 m. The origin is not printed; v1 takes the centreline
as the leftmost point of the section geometry and the baseline as its lowest point.

**Drawn element classes on the development designs** (view 3, BOM `Class`): bottom shell,
side shell, shell strake, deck (main deck, inner bottom, container-step deck), longitudinal
bulkhead (also inner side shell), hopper panel, bottom/deck longitudinal girder, longitudinal
stiffeners (bottom, inner bottom, deck, side shell, inner side shell, longitudinal bulkhead,
hopper), stiffener flange.

**Data defects seen.** The stiffener table prints `Spacing 0.000 m` for deck girders and deck
stiffeners in several designs. Bottom girders print as `I-H x 0 m x t`. v1 does not use the
spacing column.

## 2. v1 task

Input: the plain PDF `Midship Section of Long. Structure` of one design, nothing else.
Output: a list of members. For each: role, host plate (for stiffeners), placement in ship
coordinates (y, z box and end points, mm), scantling where the drawing establishes it, and the
evidence (page path indices). Each section path that the rules cannot explain is reported as
an abstention with a reason; it is not converted into a member. No geometry is invented: the
3D slice contains only drawn members, with printed thicknesses.

Not in v1: views 1 and 2 (transverse structure), brackets, openings, lengths along the ship.

## 3. Metrics (fixed before building)

**Ground-truth unit.** One row of `Slice_Elements.csv` with view
`Midship Section of Long. Structure` and a non-empty box. Its label comes from the BOM `Class`:

| Label | BOM `Class` |
|---|---|
| `bottom_shell` | `Bottom_Shell` |
| `side_shell` | `Side_Shell` |
| `shell_strake` | `Shell_Strake` |
| `deck` | `Deck` |
| `longitudinal_bulkhead` | `Longitudinal_Bulkhead` |
| `hopper_plate` | `Hopper Pannel` |
| `girder` | `*_Longitudinal_Girder` |
| `stiffener_web` | `*_Longitudinal_Stiffener` |
| `flange` | `Stiffener_Flange` |
| `other` | anything else |

Coarse groups: plate = first six labels; girder; stiffener_web; flange.
Host of a web (girder or stiffener) = the BOM class prefix: `Bottom`, `Inner_Bottom`, `Deck`,
`Side_Shell`, `Inner_Side_Shell`, `Longitudinal_Bulkhead`, `Hopper_Pannel`.

**Matching.** Predicted and true boxes are compared in drawing millimetres, both padded by
1 mm on each side (the dataset convention). Pairs with IoU >= 0.5 are candidates; a one-to-one
assignment maximises total IoU (Hungarian). Matching ignores the label.

**Reported numbers** (pooled over all test designs, and per design, per subset, per ship type):

- M1 detection precision, recall, F1 (label-agnostic). Abstentions are not predictions; they
  lower recall.
- M2 typed F1 per label and macro over labels: a true positive needs a match and an equal label.
- M3 host accuracy for matched webs (girder and stiffener).
- M4 placement error for matched pairs, in ship millimetres: centre distance and largest edge
  deviation of the unpadded boxes; median, 95th percentile and maximum.
- M5 scantlings for matched pairs:
  - plate thickness from the plate table vs BOM `Thickness`: coverage and exact-match rate
    (integer mm);
  - web thickness from the stiffener table vs BOM `Thickness`: coverage and exact-match rate;
  - web height and flange width measured from the drawn line length vs BOM `L2`:
    median and 95th-percentile absolute error (mm).
- M6 abstentions: count and reasons; and the share of section paths explained.
- Origin check: error of the inferred (centreline, baseline) origin against the origin implied
  by the true boxes, in ship mm.

**Targets** (written before building; not changed after results): M1 F1 >= 0.95; M2 macro
F1 >= 0.85; M4 median centre error <= 50 mm; plate-thickness exact match >= 0.95 of covered
plates. A miss is reported as a miss.

**Secondary run (raster fallback).** Each test drawing is rendered at 200 dpi with PyMuPDF; the
raster path extracts line segments from pixels and runs the same rules; scale and tables still
come from the PDF text layer (no OCR in v1). The same metrics are reported separately.

## 4. Sealed split

Unit: design. Lineage groups: a Repaired design is grouped with its nearest Random parameter
vector (its seed), an SGLD design with its nearest Random vector. Designs that share a seed
stay in the same split. In this sample no Repaired or SGLD seed is one of the 12 Random designs;
SGLD 379 and SGLD 429 share the nearest seed (Random 5091, distance 25.4 vs typical
seed distances 8 to 80), so they are grouped.

Rule: in each subset x ship-type cell (4 designs), one development design is chosen by the
lowest SHA-256 of `marinaframe-w3-structure-v1:<subset>:<id>`, except Random tanker, where 5597
was already inspected before the split was drawn and is therefore development. Lineage groups
then pull SGLD 379 into development.

| Subset | Development (10) | Sealed test (26) |
|---|---|---|
| Random | 5597 tanker, 3498 container, 2870 bulk | 5942, 1253, 4270, 6018, 4660, 1571, 5718, 5088, 2787 |
| Repaired | 2313 tanker, 2203 container, 1383 bulk | 3835, 3460, 1332, 5156, 2176, 1698, 5643, 2564, 2082 |
| SGLD | 429 tanker, 379 tanker, 37 container, 473 bulk | 205, 381, 118, 71, 308, 215, 17, 257 |

During development no test drawing, annotation, BOM or count is opened or computed. The test
run happens once, after the code commit is recorded below.

## 5. Implementation

(Filled in after building.)

## 6. Results on the sealed split

(Filled in after the single frozen run.)

## 7. More MiDShip data

(Filled in at the end.)

## 8. Resume point

Section 5 onward is open until the frozen run is recorded.
