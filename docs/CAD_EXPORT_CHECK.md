# CAD export check

This check uses **OCC and rhino3dm**, not Rhino or other CAD tools. It tests
synthetic exports and kernel edits. It does not establish how an external CAD
application imports or edits these files. All outputs remain drafts;
`engineering_approved` stays false.

## Run

From the project root:

```sh
PYTHONPATH=src:. .venv/bin/python scripts/check_cad_exports.py --out work/cad-export-check
```

The script writes the three formats for each fixture, `results.json`, and a
Markdown results table under `work/cad-export-check/`. The CLI restricts output
to the project's git-ignored `work/` folder. Exit code 0 means every check passed;
1 means a format check failed. The JSON includes individual edit results,
representation counts, tolerances, tool versions, and import/rebuild errors.

Focused tests:

```sh
PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/test_cad_export_check.py \
  tests/test_iges_exports.py tests/test_rhino_exports.py tests/test_rhino_trims.py \
  --basetemp=work/cad-export-check-tests
```

## Fixtures

- `flat_deck_hull`: a loft through sections at x = 0, 5, and 10 m, with
  half-breadths 0.8, 2, and 1.2 m and a flat deck at z = 3 m. It has one closed
  solid, 10 faces, and volume 90 m³. Its deck and bottom include trapezoidal
  planar trims rather than rectangular support surfaces.
- `steel_block`: three separate thin steel members: a 4 m × 2 m × 20 mm lower
  plate with a radius-300 mm hole, an upper plate, and a 20 mm web. It has three
  closed solids, 19 faces, and volume about 0.434345133 m³. The two perforated
  planar faces exercise the `.3dm` mesh fallback; the hole wall exercises
  rational NURBS reconstruction.

All CAD coordinates and edits use millimetres. The fixtures use no ship drawings
or derived per-ship data.

## Method

1. Export each original OCC fixture to STEP, IGES trimmed surfaces, and `.3dm`.
   Keep the representation counts returned by `export_3dm` as a separate baseline.
2. Re-import STEP with `STEPControl_Reader`. Require a valid shape with the
   original number of closed solids.
3. Re-import IGES with `IGESControl_Reader`. Require millimetre unit flag 2,
   valid faces, and the original face count. Sew those imported faces, require
   every resulting shell to close, and orient each shell as an OCC solid. The
   hull closes as one solid; the steel members close as three separate solids.
4. Read `.3dm` with rhino3dm. Require millimetre model units and valid objects.
   Count NURBS surfaces, trimmed-plane Breps, and labelled mesh fallbacks; compare
   these counts with both the export return value and document user text. Their
   total must equal the original face count. Rebuild each written object in OCC:
   transfer NURBS poles, rational weights, degrees, knots, and multiplicities;
   rebuild planar trim wires from the written Brep edges; rebuild mesh triangles
   as planar OCC faces. The rebuild does not consult the original source face.
5. Compare all six geometric bounding coordinates with the source, including
   position rather than extents alone. OCC `AddOptimal` measures geometric
   extrema; Rhino's conservative rational control-point bounds are not used.
   Compare solid volume for STEP and the solids reconstructed from sewn IGES.
   As an additional reconstruction check, compare total `.3dm` surface area
   using adaptive OCC integration, allowing the documented mesh approximation.
6. For STEP and sewn IGES, independently intersect the imported solids with a
   half-space below the midpoint waterline and behind the midpoint frame plane.
   Each result must contain valid closed solids, retain positive volume, remove
   material, and stay on the retained side of the plane. Offset the largest
   planar face by 1 mm with `BRepOffsetAPI_MakeOffsetShape`; require one valid
   face, unchanged area, and a 1 mm centroid displacement. This is an isolated
   face edit, not a claim that the offset face forms a closed solid.

`valid` in the table means that topology and representation checks passed.
Overall success also requires errors within tolerance and all applicable edits
to pass. `.3dm` is checked as a face/mesh exchange representation: solid volume
and edit operations are **not applicable**, not counted as passed edits.

## Named tolerances

The constants live in `scripts/check_cad_exports.py`.

The hull writer records an `ok` or `failed` outcome for each requested STEP,
IGES, 3dm and STL output. A format failure records a reason and removes that
format's incomplete file; other successful outputs remain in the run. The
package records display GLB and OCX outcomes when those formats are attempted.

| Constant | Value | Purpose |
| --- | --- | --- |
| `VOLUME_RELATIVE_TOLERANCE` | `1e-6` | One part per million for solid round-trips and unchanged offset area |

| `BOUNDING_BOX_TOLERANCE_MM` | `0.01 mm` | Ten micrometres for exchange-file roundoff |
| `SEWING_TOLERANCE_MM` | `0.001 mm` | Join coincident exported edges without closing physical gaps |
| `SURFACE_AREA_RELATIVE_TOLERANCE` | `0.005` | Allow the labelled mesh approximation in `.3dm` |
| `FACE_OFFSET_MM` | `1 mm` | A measurable isolated-face edit |
| `FACE_OFFSET_TOLERANCE_MM` | `0.001 mm` | Check actual offset displacement |
| `REBUILD_TOLERANCE_MM` | `1e-7 mm` | Construct imported OCC faces |
| `AREA_INTEGRATION_RELATIVE_TOLERANCE` | `1e-8` | Avoid coarse quadrature errors on rational surfaces |

The structure OCX round-trip check reads each written plate contour. It compares
its area with the source outline and compares corresponding points within one
micrometre, the precision of the written coordinates. A missing or open contour
fails the check; a copied `NetArea` cannot replace this geometry check.

## Results

Measured on 2026-11-10 with CadQuery 2.7.0, cadquery-ocp 7.8.1.1.post1, and
rhino3dm 8.35.0. The script exited 0. Volume errors below are relative errors,
not cubic-millimetre differences. IGES volume is measured after sewing and solid
reconstruction. A reported zero means the computed values matched in this run.

| Fixture | Format | Imported | Valid | Volume error (relative) | Bbox error (mm) | Edits ok |
| --- | --- | --- | --- | --- | --- | --- |
| flat_deck_hull | STEP | yes | yes | 0 | 0 | yes |
| flat_deck_hull | IGES | yes | yes | 0 | 0 | yes |
| flat_deck_hull | 3dm | yes | yes | n/a | 0 | n/a |
| steel_block | STEP | yes | yes | 0 | 0 | yes |
| steel_block | IGES | yes | yes | 0 | 0 | yes |
| steel_block | 3dm | yes | yes | n/a | 1e-07 | n/a |

Each of the four STEP/IGES rows passed all three edits. `.3dm` counts matched
the export return values, document user text, and imported objects:

| Fixture | Exact untrimmed | Exact trimmed plane | Mesh fallback | Total objects |
| --- | --- | --- | --- | --- |
| flat_deck_hull | 6 | 4 | 0 | 10 |
| steel_block | 17 | 0 | 2 | 19 |

The rebuilt `.3dm` surface-area relative errors were 0 for the hull and about
`5.30e-6` for the steel block, including the two mesh fallbacks. These are
fixture results for OCC and rhino3dm only.
