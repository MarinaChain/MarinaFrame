# Source records

Every section, part, tank and steel group of a run can carry one small `source_record`. It
says where the item came from: read from a drawing region, a labelled guess and its inputs, or
unknown. The app uses it for the source view: point at a part in 3D and the drawing pane shows
the sheet and region it came from (docs/POSITIONING.md, "Honesty").

Schema id: `source-record/v1`. Code: `src/vessel_reconstruction/source_record.py` (writer and
checker), `app/core/src/source_record.rs` (app reader and checker).

## Form

```json
{"kind": "read",
 "regions": [{"sheet": "GA Rev1.pdf", "page": 0, "view": "plan",
              "box_px": [812.0, 340.5, 1290.0, 611.0], "page_px": [7016, 4961]}]}

{"kind": "guessed",
 "method": "aft_bulwark_thickness: GA gives no bulwark thickness",
 "inputs": [{"sheet": "GA Rev1.pdf", "page": 0, "view": "plan", "box_px": null},
            {"part": "aft_deck"}]}

{"kind": "unknown", "reason": "The reader of this section does not record its sheet region yet."}
```

- `kind`: `read`, `guessed` or `unknown`. Never "approved" or "verified".
- A **region** has `sheet` (the file name as the run's sources list it), `page` (from 0),
  `view` (`profile`, `plan`, `section`, `body plan`, `table`, or null) and `box_px`
  ([left, top, right, bottom]) with `page_px` ([width, height], the pixel frame of the box).
  The app scales the box to the page image it shows by `page_px`.
- `box_px` is null when the reader knows the sheet and view but not the pixels (a DXF has no
  pixels). A producer never invents a box.
- A guessed record's `inputs` are regions and `{"part": id}` items (another part, or another
  section for an interpolated section).
- Size limits: at most 8 regions, 12 inputs and 240 characters of text. Both checkers refuse
  records outside the form; the app then treats the item as having no record.

## Where the records are written

| Item | Producer | Record |
| --- | --- | --- |
| Hull section (traced) | `ingest.extract_sections` | `read`: the section's `roi_px` on the rendered page (`page_index`, image size) |
| Hull section (model-authored) | `ingest.extract_sections` | `guessed`: the model's basis; input is the section region |
| Hull section (draft repaired, faired) | `source_record.finish_sections` (pipeline) | `guessed` with the section region |
| Hull section (interpolated) | `source_record.finish_sections` | `guessed`: inputs are the neighbouring sections |
| Hull section (table reader) | `source_record.finish_sections` | `unknown` (follow-up) |
| Whole-vessel part (ship-cad) | `ship_cad.resolve_program` | from each argument: a traced measurement with a `sheet_region` gives a region; a guess or model value makes the record `guessed` |
| GA measurements, vector | `whole_vessel.VectorReader.sheet_region` | sheet and view, `box_px` null (DXF) |
| GA measurements, raster | `whole_vessel_raster.RasterReader.sheet_region` | box from the inverse of the crop pixel formula |
| Appendages | `whole_vessel_appendages` | GA sheet, profile view, `box_px` null |
| Construction-plan parts and tanks | `whole_vessel_internals.part_source_record` | sheet and view per traced argument (DXF), guesses by argument |
| Raster tank plan tanks | `tank_plan_raster.tank_source_record` | label box on the sheet (deskew turned back); `guessed` when the height is guessed |
| Steel groups | not written (structure is another lane) | the app shows `unknown` (follow-up) |

`result.json` (build) and `extracted_sections.json` carry `sections[].source_record`.
`whole_vessel/execution.json` carries `result.components[].source_record`. A raster tank run
writes `tank_tables/<stem>_source_records.json` (`{"schema", "records": {tank id: record}}`)
beside `<stem>_capacity_plan.csv`.

## Older runs

A run made before source records has none. The app reads such a run as before and says
"No source record. Run again to record where this came from."
