# Lines-sheet View Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Diagnose the nine development sheets and improve truth-free region and scale detection without changing the default reader.

**Architecture:** Retain `intake.survey_page` and `draft_fit.reference_views` unchanged. Add an experimental sheet detector and a development-only evidence runner. Reuse existing OCR and printed-scale parsing; report missing evidence rather than infer physical scale from pixels alone.

**Tech Stack:** Python, NumPy, SciPy, Pillow, existing Tesseract OCR, pytest.

## Authority and boundaries

Item 7 in `batch-2026-11-12b.md` and `common.md`. Work only on `lane/view-detection` in this worktree. No truth files, sealed material, blind sheets, model requests, scoring, default-reader change, merge, or main-checkout writes. `engineering_approved=false`. The original five sheet rasters are in permitted shared `work/sources/`, not their `work/dev-truth/` folders; use only the exact filenames from the prior lane's truth-blind preflight. The other four rasters are in `work/dev-truth/`.

Read prior report with `git show lane/polyline-naming:docs/plans/2026-11-12-polyline-naming.md` (not present on this base). Its recorded result: profile and plan on WHITE GULL only; physical scale supplied on all nine. The prior ignored evidence folder is absent in the main checkout.

## Pre-run checks and acceptance

- Save baseline regions, outline failures and annotated previews/crops for every sheet under ignored `work/view-detection/` before implementation.
- Record profile, half-breadth and body-plan presence separately. A proposed box is not automatically a correct view: inspect saved images.
- Retain explicit abstention for unclear view identity or scale. Do not claim a ratio is pixels/metre without scan DPI or measured paper units.
- Compare experimental versus legacy regions. Keep existing functions byte-identical so already-working reader outputs remain unchanged. Test legacy parity on synthetic inputs and compare WHITE GULL reference results.
- No gates will be relaxed after results. This lane measures detection, not hull correctness or numbered station identity.

## Design review before implementation

Architecture **PASS**: experimental API, no product imports. Quality **PASS**: existing helpers reused, no truth or model dependency. Tests **WARN**: cover touching panels, frame/text contamination, polarity and ambiguous scale; actual layouts still need inspection. Performance **PASS**: reduce sheet for morphology/OCR; avoid full-resolution float RGB copies for huge TIFFs.

## Tasks

1. Create `scripts/measure_view_detection.py`: fixed nine public development paths; legacy intake and reference detection, reduced annotated previews and crops, JSON under `work/` only. Never import benchmark truth modules. Run baseline and inspect every preview. Commit evidence runner and this protocol.
2. Write failing synthetic tests in `tests/test_lines_sheet_detection.py` for the diagnosed shared failure modes, and scale without DPI. Run to demonstrate failure. Implement minimal experimental helpers in `src/vessel_reconstruction/lines_sheet_detection.py`; use readable constants, explicit evidence and abstention. Run focused tests and commit.
3. Run experimental detection on all nine, inspect crops, and record per-sheet causes and before/after counts here. Preserve failures explicitly. Check legacy parity. No truth reads or model calls.
4. Run focused tests and full quick tier using main Python and shared Rust cache, then push only this branch. Delete only this worktree's local `target/` after successful push if present; do not delete shared cache.

Commands:

```sh
PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python scripts/measure_view_detection.py --work-root /Users/jonathanjie/Documents/workspace/MarinaFrame/work --out work/view-detection/before
PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python -m pytest tests/test_lines_sheet_detection.py tests/test_draft_fit.py tests/test_intake.py -q
CARGO_TARGET_DIR=/Users/jonathanjie/Documents/workspace/MarinaFrame/.claude/worktrees/shared-target-sol MARINAFRAME_TEST_PYTHON=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
```

## Checkpoint results (incomplete)

The fixed nine-sheet baseline and one experimental pass completed, with zero model calls and zero truth loads. Evidence is in this worktree's ignored `work/view-detection/{before,after}/`; each sheet has JSON, annotated overview and crops. The two contact sheets were inspected by eye. All existing intake/reference implementation files remain unchanged. Legacy reference outputs were exactly equal before/after on **9/9**, including WHITE GULL. The runner uses unit scale solely for ROI diagnosis; it does not claim that the legacy path detects scale.

**Ruling:** replace the proposed heading-based splitter with frame-suppressed candidate groups — local OCR did not recover headings on most sheets and read note mentions on Thayer instead — cost: candidates remain unlabelled and cannot satisfy the view-detection goal yet. No reader consumes these candidates. The experimental code explicitly labels all boxes `other`, rather than convert aspect ratios into false view identities.

| Sheet | Legacy profile/plan returned | Cause of legacy failure / limitation | Experimental groups | Identified new views |
|---|---|---|---:|---|
| PARDON ME | 0/0 | Frame, grid and annotations merge profile, plan and body panels into one compact group | 5 | none; body halves split but profile/plan outlines fragmented |
| BUE GIRL | 0/0 | Long dimension/frame strokes connect the long views and lower body plan | 6 | none; profile group separated but plan ink fragmented |
| BUMBLE BEE | 0/0 | Profile, half-breadth, body and table join through frame/grid ink | 7 | none; horizontal views still split into several groups |
| C.A. Thayer | 0/0 | Dense body-plan construction grid and notes make one sheet-sized group; aspect is not view identity | 5 | none; only lower table and fragments separate reliably |
| Balclutha | 0/0 | Portrait body-plan sheet with full sheet/grid connectivity; no clear separate long views in preview | 7 | none; grid groups are not complete panels |
| E. C. COLLIER | 0/0 | Dimensions, grid and drawing ink bridge the stacked long views, body and notes | 13 | none; several partial views and text groups remain |
| WHITE GULL | 1/1 | Returned boxes are not sufficient: main profile/plan/body share one body-labelled group; returned plan is lower table ink | 7 | none; useful long-view groups exist but identities/datums unresolved |
| COLLEEN | 0/0 | Connected central body grid and profile/plan construction strokes form one compact group | 5 | none; fragments separate but complete long views are missing |
| CALEB JONES | 0/0 | Profile, body and half-breadth meet through common construction lines; title/frame also connect | 8 | none; outlines remain split |

Do not count candidate groups as found regions. By-eye review shows that unconditional long-line removal also removes real straight hull/grid strokes and fragments some views. This checkpoint does **not** improve identified-view coverage. It establishes the component-merging cause and a bounded experimental base; Item 7 remains incomplete.

Local OCR plus the existing parser produced printed-ratio/file-DPI proposals on **3/9** (PARDON ME, COLLEEN, CALEB JONES); **6/9** remain missing. Those are proposals only, not checked physical calibrations. Per-sheet values stay in ignored JSON. A scanner's DPI tag may not describe a resized raster; no benchmark calibration or truth was used to confirm it. Mixed ratios and anisotropic DPI abstain in tests.

Focused checks: **26 passed**, five existing SWIG deprecation warnings. Initial synthetic tests exposed two fixture defects: a rectangular synthetic hull consisted entirely of the straight strokes intentionally removed, and 1:24 is not in the reused metric ratio whitelist. Fixtures now use a curved outline and supported 1:25 ratio; parser rules were not widened. Initial runner-only failures were Pillow's crop size guard and TIFF rational DPI JSON encoding; preview crops now come from the bounded preview and DPI is serialized as float.

Initial quick tier failed in the app proc macro: the shared cache skipped UI staging and this worktree had no `app/ui-release`. Cleaned only package `marinaframe-app` in the mandated shared cache and restarted the tier. No source workaround or second target folder was added.

**Resume point:** finish independent panel identity and complete ROI recovery, retain real straight drawing strokes, improve small-print/graphical-scale measurement, and inspect every proposed view crop before any integration. No numbered stations, no correct-view coverage gain, and no physical scale accuracy claim exist. Product/default reader unchanged. Final quick-tier outcome to be appended below before push.

## Independent review and fix

A fresh reviewer read all four initial additions and relevant helpers without opening drawings or truth. One P2 boundary issue: symlinked evidence directories could redirect writes outside the worktree. Added a failing symlink test, rejected symlink components, and applied the check to case directories, crops, previews and JSON outputs. The original local-directory test also demonstrated RED before its implementation. No other high-confidence review findings; no deferred minors. Frame/straight-ink removal remains an explicit experimental limitation, not a successful detector.

The planned heading splitter was not implemented; no heading fixtures are claimed as coverage. This is an early checkpoint, not completion of the implementation plan. The initial detector collection failure was the absent experimental module, followed by the recorded fixture failures and passing focused run.

## Final checkpoint validation

Required quick tier exited **0** after rebuilding stale app staging: Rust format, clippy and tests passed; **2,290 Python tests passed**, 4 skipped, 87 deselected, five existing SWIG warnings; **275 UI tests passed**, zero failed; secret scan passed. Log: ignored `work/view-detection/test-quick.log`. The final focused run passed **29 tests**. The evidence boundary fix was completed while the full tier ran and was separately checked with its focused tests. A duplicate full-tier invocation was stopped to avoid concurrent duplicate work; the original tier completed normally. No local `target/` exists, so no local Rust folder requires removal. The mandated shared cache is retained.

Checkpoint commits: `bcf0397` (protocol/runner), `d3ba1ef` (experimental proposals/tests), `ad56d9b` (evidence boundary/review). Push only `lane/view-detection`; no merge. **Item 7 remains incomplete**, at the resume point above. No coverage improvement is claimed.
