# W15 plan-view contour corridors implementation plan

> **For Claude:** Use executing-plans to implement this plan task-by-task.

**Goal:** Use unique, declared plan-waterline crossings as selection evidence for crowded raster body plans, without supplying hull geometry.

**Architecture:** A small drawing-only adapter reads station-column ink runs within caller-declared waterline regions. It maps unique crossings through the supplied plan/body calibration into the existing `contour_selection` contract. Every attempted anchor has an evidence or refusal record. A corridor is emitted only when accepted anchors cover the existing complete calibrated range; missing endpoints are not extrapolated. Existing tracing, CAD, validation and Rust readiness authority are unchanged.

**Tech stack:** Python, NumPy, existing raster ingest and strict JSON specs; synthetic pytest tests; native Rust controller for evaluation.

## Boundaries and design review

- Architecture PASS: separate input-evidence adapter; no changes to inference gates.
- Quality WARN: unidentified plan ink cannot be assigned a waterline by sorted order or nearest body candidate. Require explicit per-waterline source regions and identity evidence. Record ambiguity instead of guessing.
- Coverage PASS: test unique selection, multiple/no crossings, clipping, mapping, duplicate elevations, endpoint coverage, existing-selection preservation, and approval flags.
- Performance PASS: bounded column reads, at most 64 waterlines per section; no repeated full-panel tracing in the adapter.
- No STEP, reference offsets, or scorer input enters adapter or input preparation.
- Do not commit source drawings, source-derived coordinates, crops, or overlays. All raw data, frozen source, executables and run folders belong under `/Users/jonathanjie/Documents/workspace/MarinaFrame/work/w15/` only.

## Tasks and checks

1. Read current source and existing comparison/selection contracts. Add failing synthetic tests in `tests/test_plan_corridors.py` for the drawing-only adapter and overlaid body-plan selection. Run focused pytest with main `.venv/bin/python` and `PYTHONPATH=src`.
2. Implement `src/vessel_reconstruction/plan_corridors.py`. Reuse existing ink contrast rules; reject invalid setup, ambiguous/no crossings, unsupported extent and missing waterline identity. Return evidence separately from spec geometry. Integrate optional declared plan evidence into `benchmarks/gunnerus/raster_path.py`; no change for inputs without it.
3. Freeze source and controller under main `work/w15/`. Reproduce current Gunnerus raster abstain and draft runs, then run same inputs with declared plan evidence. Preserve every refused anchor. Do not fabricate full-height anchors to satisfy the selection contract. If drawing identity is unresolved, record the limitation and retain unchanged spec.
4. Replay the four authorized factory development controls before/after. Compare measured candidates and independent scores. Native runs use immutable executables and explicit worker source; scoring starts only after the read. Do not open sealed evaluation data.
5. Run `make test-quick PY=<main>/.venv/bin/python`. Run `make test-full` once at end only after `pgrep -fl 'make test-full'` reports none. Set temporary-output environment to main `work/w15/` where supported. Do not edit worker source during pinned tasks.
6. Review with demand-elegance; add aggregate W15 results and limits to `docs/BENCHMARK_GUNNERUS.md`. Add a lesson only for an actual correction, through self-improvement-loop and required backup checks.
7. Commit code, synthetic tests, documentation and aggregate scores on `w15-plan-corridors`; do not push. Run `cargo clean` after all native consumers end.

## Resume point

Implementation complete: new adapter, optional raster preparation, 21 adapter tests plus five unchanged stroke-identity controls pass (26 focused tests). Review correction counts each scan column separately; regression failed before correction and passes after. Project lesson added with backup at main `work/w15/lessons-before.md`.

Gunnerus72 before/after inputs are prepared. All792 anchor attempts refused (648 ambiguous crossings,144 missing identity), zero corridors, specs semantically unchanged. All four native Gunnerus arms finished; after draft matches before exactly (72/72 source records, excluding implementation hash). Baseline draft inspected72 sections:36 resource_limit,36 ambiguous_curve, zero unique candidates, blocked invalid candidate and no STEP. Initial59-section probe retained and excluded.

Four factory development drawings regenerated from authorized sources; all frozen drawing hashes match. Eight native before/after control runs are running under main `work/w15/factory/`. Post-read scorer is scheduled after reads. Initial quick tier invalidated by source edit (`worker_implementation_changed`); stable-source quick tier passed (701 Python,17 CAD deselected; Rust,format,Clippy,secrets). Implementation committed as dceb3ec. One full-tier command is queued after evaluations and stable quick completion and will check `pgrep` before starting. No further Python source edits until all tests end.

Completed: eight native control builds and independent scores; four controls correct before/after with exactly unchanged scores, zero newly wrong builds. `outputs/w15/results.json` holds aggregate-only results. Full tier ran once after empty pgrep preflight and PASSED (701 quick Python,44 Rust controller CAD,app real task,17 Python CAD,smoke valid). Stock smoke's temporary `/tmp` folder moved to main `work/w15/smoke-full/`. Both task build targets cleaned after consumers ended (4.8GiB and1.1GiB). Documentation and aggregate results ready for final commit; no push. No remaining implementation step. Open drawing-identity/full-range limits are explicit in benchmark section9.
