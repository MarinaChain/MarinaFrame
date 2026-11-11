# Principal particulars: development check, 2026-11-10

Measured 11 sheets from six development sets in the main checkout's `work/sources/`:

- Gunnerus: the first page of each of the six PDFs in `gunnerus/polarkonsult/` (GA, Lines Plan, Midship
  Section, Profile and Plan, Shell Expansion, Tank Plan).
- C.A. Thayer: `haer/ca_thayer/ca_thayer_s01_title_sheet.tif`.
- Wapama: `haer/wapama/wapama_s01_s_s_wapama_as_is_lines_2010.tif`.
- Pardon Me: `haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif`.
- Bumble Bee: `haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif`.
- Bue Girl: `haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif`.

This is a parser check on PDF text and whole-page OCR at a longest side of 6000
pixels. It does not measure the full intake OCR path, which also reads strips.
Labels were transcribed from the extracted text in this same development sample.
No sealed or holdout files were opened for this measurement.

| Field | Labelled | Read | Correct | Wrong | Missed |
|---|---:|---:|---:|---:|---:|
| LOA | 1 | 1 | 1 | 0 | 0 |
| LBP/LPP | 1 | 1 | 1 | 0 | 0 |
| Beam | 1 | 1 | 1 | 0 | 0 |
| Depth | 0 | 0 | 0 | 0 | 0 |
| Design draft | 0 | 0 | 0 | 0 | 0 |
| Scantling draft | 0 | 0 | 0 | 0 | 0 |
| Displacement | 0 | 0 | 0 | 0 | 0 |
| Built year | 1 | 0 | 0 | 0 | 1 |
| Builder | 1 | 0 | 0 | 0 | 1 |
| IMO | 0 | 0 | 0 | 0 | 0 |

Gunnerus Lines Plan text gives `LENGTH OVER ALL 36.25 [m]`, `LENGTH BETV. PERP.
33.90 [m]`, and `BREADTH MOULDED 9.60 [m]`. All three readings equal the labels.
The C.A. Thayer title prose names Hans D. Bendixsen and says he built C.A. Thayer
in 1895; these are missed. The same notes say he built another vessel in 1897.
The reader abstains on that narrative year after a regression test caught a wrong
1897 reading during development.

Gunnerus also prints depths to named decks and normal-operative/maximum-loaded
drafts. These are retained in raw text but are not labelled as moulded depth,
design draft or scantling draft. Zero labelled cases means that field's development
accuracy is unmeasured. Synthetic fixtures cover all ten fields, units, sources,
conflicts, skipped sheets, typed overrides and export draft selection.

Reproduce with `benchmarks/drawing_set/evaluate_particulars.py`; detailed rows and
matched boxes are in `work/particulars/evaluation.json`. The benchmark code contains
the fixed source list and labels. No accuracy claim extends beyond this sample.

Changed files:

- `src/vessel_reconstruction/particulars.py`
- `src/vessel_reconstruction/intake.py`
- `src/vessel_reconstruction/drawing_set.py`
- `src/vessel_reconstruction/sheet_types.py`
- `src/vessel_reconstruction/sheet_scale.py`
- `src/vessel_reconstruction/exports/identity.py`
- `src/vessel_reconstruction/exports/package.py`
- `src/vessel_reconstruction/exports/hydrostatics.py`
- `tests/test_particulars.py`
- `benchmarks/drawing_set/evaluate_particulars.py`
- `docs/APP_SPEC.md`
- `docs/PARTICULARS_READER.md`
- `outputs/particulars-results.md`
- `tasks/lessons.md`

Validation:

- New particulars tests: **38 passed** (`tests/test_particulars.py`).
- Full Python suite: **1769 passed, 9 failed, 11 setup errors, 1 skipped**;
  1790 collected, 5 SWIG deprecation warnings, 1969.11 seconds. Command:
  `PYTHONPATH=src:. .venv/bin/python -m pytest -q -rs`.
- An unchanged baseline from HEAD `3afcf462d778983c29dcc90c76bce6a7bb6a68b3`
  reproduced all **9 failures and 11 setup errors** (6 other selected tests
  passed). The baseline source and five relevant test files were read with
  `git archive` into `work/particulars-baseline/`; no checkout or commit was made.
- Eleven review-server setups cannot bind `127.0.0.1` in this session
  (`PermissionError: Operation not permitted`). Four process-control tests
  depend on `/bin/ps`, which this session blocks. Three CAD sandbox tests fail
  with `sandbox-exec: sandbox_apply: Operation not permitted`. Two part-revision
  tests call the same sandbox worker; their baseline worker receipts show exit 71.
- The skipped Gunnerus containment test did not run because
  `MARINAFRAME_GUNNERUS_SOURCES` was unset. It is not counted as a pass.
- Fresh PDF/OCR extraction reproduced the per-field counts above in
  `work/particulars-fresh/evaluation.json`; there were no unlabelled reads.
- `git diff --check` passed. No pip command or commit was run.

Full-suite and baseline logs are in `work/python-full.log` and
`work/baseline-failures.log`. The full suite is not green in this restricted
session; the same failing checks reproduce without this lane's changes.
