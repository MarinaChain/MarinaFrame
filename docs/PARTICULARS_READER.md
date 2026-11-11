# Printed principal particulars

`particulars.py` reads LOA, LBP/LPP, beam, moulded depth, design draft,
scantling draft, displacement, built year, builder and IMO. Dimensions are metres;
displacement is metric tonnes. It accepts metric suffix units and bracketed heading
units, decimal commas, and feet with inches and fractional inches. Dimensions need
an explicit unit. It does not derive values from hull geometry.

The reader uses PDF words first, including short text layers. It also uses the
words that intake already gets from whole-page and strip OCR. Each reading has
`field`, `value`, `status: read`, and `source` with file, page, sheet, matched text,
`bbox` and `bbox_space: page_px`. PDF rotation and OCR reduction/crop offsets are
included in the box mapping. A caller that supplies only text gets a null box;
the reader does not invent a position.

`page.sheet.particulars` holds the readings. `preview.set.particulars` holds
`values`, per-field `fields`, and `check_items`. At write-spec time these are
recomputed from kept pages and the person's current typed values. The app's
existing opaque `sheet` and `set` fields preserve the readings; no UI change is
required. Typed values remain in `intake.particulars`; the resolved record is in
`intake.particulars_reading`. Printed values are not put into the typed fields.

Typed values always win. Different printed values, including different values on
one sheet, produce `particulars_conflict` check items with all readings. Without a
typed override no conflicting value is selected. An unambiguous design draft goes
to `spec.design_draft_m` with `design_draft_source`. Exports read the current
intake fields and label a read draft with its sheet ids. Only when no draft is
available does the existing `0.6 x depth` assumption apply. A stale spec draft does
not resolve a printed conflict. Explicit export drafts still take priority.

Manifest particulars retain scalar values and add `sources` for printed fields
and `check_items` for conflicts. A printed IMO is kept literally; an invalid check
digit becomes a check item. Typed IMO validation keeps its existing strict rule.

Deck-specific depths and operational or maximum-loaded drafts are not renamed to
moulded depth, design draft or scantling draft. `Built in YEAR` is accepted as a
labelled line, not in a narrative sentence about an unidentified vessel. General
prose descriptions of builders and construction dates remain a limitation.

Development measurements and their limits are in
[outputs/particulars-results.md](../outputs/particulars-results.md). The fixed
benchmark command is:

```sh
PYTHONPATH=src:. .venv/bin/python -m benchmarks.drawing_set.evaluate_particulars
```

Raw extracted text, word boxes and evaluation JSON stay in `work/particulars/`.
No sealed or holdout files are used by the benchmark.
