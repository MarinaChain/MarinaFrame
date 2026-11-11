# Provenance view: hover a part, see the drawing it came from (lane H)

Branch: `lane/provenance-view` from `origin/continue/v0.5` (960135e).
Positioning promise (docs/POSITIONING.md, "Honesty"): each surface and part shows where it came
from, read from the drawing or a labelled guess.

## Goal

1. Data: one small source record per section, part, tank and steel group in the run outputs:
   `read` (sheet regions), `guessed` (rule and inputs) or `unknown`. Never an invented region.
2. UI: hover (short delay) or select a part in 3D. The drawing pane shows the source sheet(s)
   after a short stacked-sheets animation, zoomed to the region, outlined, with a line from the
   part. Guesses: dashed amber "best guess" lines to each input (sheet regions and parts).
   Unknown: a note, no line. Older runs: "No source record. Run again …".

## Step 1: data (commit 640f21d)

Schema and producer table: docs/SOURCE_RECORD.md.

| Item | Record |
| --- | --- |
| Hull sections | `read` (ROI on the rendered page); `guessed` when model-authored, draft repaired, faired or interpolated (neighbours as inputs); `unknown` for the table reader |
| Ship-cad parts (GA, appendages, superstructure, revised parts) | from argument evidence in `ship_cad.resolve_program`; GA raster boxes from the inverse crop formula; DXF: sheet and view, no box |
| Construction-plan parts and vector tanks | DXF sheet and view per traced argument; guesses listed |
| Raster tank plans | label box on the sheet as drawn (deskew turned back, tested against cv2); `guessed` when the height is guessed; file `tank_tables/<stem>_source_records.json` |
| Steel groups | not written (structure/ belongs to lane F): the app shows `unknown` |

App core (`app/core/src/source_record.rs`): checks form and size, passes records on
`ComponentView`, `SectionView` (every build's `result.json`, not only drafts) and `CapacityRow`.

## Step 2: UI

- `app/ui/js/provenance.js`: record lookup (indexed once per view), sheet grouping, box scaling,
  view box (clamped to the page), summary text; `createSourceView` (peek over the drawing pane,
  paper-stack animation, SVG lines across the stage, redrawn per frame but DOM touched only when
  a point moves); `createSourceController` (220 ms hover delay, 320 ms leave delay, pointer on
  the peek keeps it open, selection shows at once, only in the split layout, Escape closes).
- `model3d.js`: `onItemHover` from the existing once-a-frame readout raycast (no extra raycast
  per pointer event), `anchorOf(item)` with cached world centres.
- `workspace.js`: wiring, sheet loading (the drawing page when the name matches, else
  `list_sources` + `read_source_page`, cached per task), fact card source link opens the view.
- Reduced motion: no paper stack, no fade (JS check and CSS).
- Keyboard: the 3D part list rows are buttons; selecting one shows its source.
- Mock: survey-launch records, synthetic GA sheet `mock/files/ga-1.png` (`make_ga_mock.py`),
  deck/deckhouse/bulwark parts in the GLB generator (`make_whole_vessel_mock.py`).

## Checks (2026-11-11)

- Python: `tests/test_source_record.py` 28 tests (schema, ship-cad, GA vector and raster,
  internals, raster tanks with cv2 deskew inverse, ingest sections, finish rules).
  Python quick tier: 1881 passed, 76 deselected.
- Rust: `source_record.rs` unit tests, parts and view tests extended; app core 134 lib tests pass.
- UI: `app/ui-tests/provenance.test.mjs` 9 tests (lookup, old runs, steel, sheets, scaling,
  clamp, hover delay, selection, peek keeps open, hidden pane, lookup speed on 80 sections and
  600 parts). `node --test app/ui-tests` passes.
- Browser (mock, 1440x900): screenshots in `work/provenance-view/` (git-ignored):
  `before-01` (text card only) and `after-00` to `after-08` (section guess, part guess with two
  regions, read part from the keyboard list, guess with part input ring, tank, hull with three
  regions, older run note, steel unknown note). No console errors. Reduced motion: no stack.
- Not measured: frame timing in the browser (the preview page ran in the background, where
  animation frames stop). The hover path adds one plane and one part raycast per frame to the
  existing readout raycast.

## Follow-ups

- Steel/structure records: lane F to write `source_record` per member group (sheet, view,
  `origin_drawing_mm` to pixels), then the app reads it from the GLB extras or a sidecar.
- Table-reader sections (`table_vision`): cell boxes exist (`cell_evidence`); turn them into regions.
- DXF sheets have no pixel boxes: a DXF-to-render transform would let the app zoom to them.
- Raster tanks found only in the profile have no label box (`box_px` null).
- Show steel group labels ("Bulkheads") instead of "Steel bulkhead" in the source view header.
- Interpolated sections list neighbour ids; label them "Section at x m".

## Resume point

Both steps are done and pushed. To continue: pick a follow-up above. To re-check the UI:
`PYTHONPATH=src .venv/bin/python app/ui/mock/make_whole_vessel_mock.py`, serve `app/ui`, open
`?mocktanks&mockglb&mockstructure#run`, Survey launch, Parts tab, "Show in 3D", then pick parts in
the 3D part list or hover parts and section planes.
