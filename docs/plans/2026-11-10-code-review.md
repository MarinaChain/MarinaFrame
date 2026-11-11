# Code-quality review (2026-11-10): band-aids or elegant?

Founder request. Four independent read-only reviewers on two models, each on one area; findings checked by the PM
where marked. Full reports: `work/research/code-review/` (git-ignored; opus-readers.md, opus-harness.md, and the two
Sol reports pasted from the session).

## Verdict

Not band-aid code. No product module special-cases a named ship; constants are mostly named and explained; guards,
receipts, sandboxing and run publication are careful. The debt is **structural**: the same facts defined in two or
three places, improvements added beside old code instead of replacing it, a few oversized modules, and tests whose
*execution* is weaker than their design (some pass without checking, skip on CI platforms, or sit outside the tiers).

| Area | Grade | Reviewer |
|---|---|---|
| Body-plan reader v1 / hard-chine variants / calibration / intake / view+fairing | B- / C / C+ / B / B- | Opus |
| Core geometry, GA reading / ship CAD, superstructure / tanks, structure / exports, hydrostatics / pipeline | B, B / C / C / C / C | Sol |
| rust-control / validation+store / app core / Tauri / Python harness / UI JS | B / B / B / A- / C+ / C+ | Opus |
| Python tests / Rust tests / app-core integration tests / UI tests / tiers+CI | B / B / C / C / C | Sol |

## Ranked fix list

P0 = wrong result or unprotected boundary; P1 = structural debt that blocks progress; P2 = cleanup.

| # | P | Finding | Fix | Effort |
|---|---|---|---|---|
| 1 | P0 | `tests/test_runtime.py:19` `stopped()` returns True when `/proc` is absent; macOS has no `/proc`, so process-cleanup tests always pass on the shipping platform (PM confirmed) | platform-aware liveness check, first proven on a live child | S |
| 2 | P0 | CI never runs the macOS sandbox probes (`test_ship_cad.py:176-196, 264-283` skip on Linux/Windows) | required macOS CI job for sandbox probes and part-revision integration | M |
| 3 | P0 | App integration tests return early: `MARINAFRAME_TEST_PYTHON` is set after the plain cargo step (`ci.yml:68-79`); `draft_task` not in any tier | set it first; fail on missing prerequisites in required runs | S |
| 4 | P0 | UI tests in neither `make` nor CI | add `node --test app/ui-tests/` to the quick tier and CI | S |
| 5 | P0 | App starts Python five ways; export and part-revise kill only the leader on timeout (orphans, full env); intake has no timeout and cannot be cancelled | Done in `f66f5ff`: one supervised spawn builder (`rust-control/src/supervised.rs`) for all five sites; progress watchdog, no wall timer; intake Cancel | M |
| 6 | P0 | `part_revise.py` calls the model directly (hardcoded model, no budget/receipts, regex JSON) | Done in `32e0067`: route through the Rust provider worker | M |
| 7 | P1 | Product reader source pinned by sha256 in three holdout tests, so every improvement became a wrapper; three hard-chine readers exist, none in the product path | freeze a benchmark copy or git tag; choose one reader by benchmark, integrate, move the rest out | S + M |
| 8 | P1 | Fixed pixel thresholds in the product reader path (`body_plan_crossings.py:25,48,52,78`, `sheet_calibration.py:44`) tuned on HAER scans; low-res uploads can misread with no flag | Done on `lane/reader-thresholds`: stroke measured from the reader's own crossings; every drawing distance in the crossings, reader and calibration modules scales outside the checked 4.0-7.5 px band (ingest needs none, measured); native readings byte-identical to frozen v1 on five development sheets; at 50 %/35 % size 127/114 cells within 5 cm vs 15/2 (frozen v1); low resolution flagged. See `docs/BODY_PLAN_CHINE.md` | M |
| 9 | P1 | Tool catalog defined in Rust and Python (texts differ); third operation list in `rust_worker.py` | Done: `src/vessel_reconstruction/tool_catalog.json`, read by Rust and Python | M |
| 10 | P1 | Revision export can package another revision's display GLB (`exports/spatial.py:23`) | `32333d6` plus follow-up: bind producer outputs to the build and check their hashes | M |
| 11 | P1 | One export-format failure drops all CAD (`geometry.py:745`, `pipeline.py:230`) | Done in `082725f`: per-format results; keep valid formats | M |
| 12 | P1 | Package written in place, manifest last (`exports/package.py:225,292`) | Done in `c31a040`: stage privately, publish atomically | M |
| 13 | P1 | OCX check compares copied NetArea, not exported contour (`structure/ocx.py:573,734`) | Done in `cb00afe`: compare contour geometry | M |
| 14 | P2 | Tank mesh spans gaps between separate hull pieces at one height (volume is correct) (`tanks.py:418,497`; PM checked) | Done: separate regions through lofting; unmatched spans flagged `tank_loft_span_omitted` | L |
| 15 | P2 | Table hydrostatics uses the outer half-breadth; wrong for sections with inner voids (`exports/hydrostatics.py:268`; PM checked) | Done in `8f5fe2f`: integrate occupied intervals | M |
| 16 | P2 | Display mesh may mesh trimmed faces as their support patch (`display_mesh.py:49,141`) | Done in `8f5fe2f`: grid path only for proven-untrimmed faces | M |
| 17 | P2 | Silent triangle-fan fallback (`tanks.py:304`); calibration "noted" string decides blocking; model id missing from answer cache key | Done in `fc070c1`: typed repair result, typed severity, model id in key | S each |
| 18 | P2 | Oversized modules: `controller.rs` (~2,600 lines), `pipeline.py` main function, `agent_tools._execute_verified`, `app.js` (~2,700 lines, global state), ~1,000 lines of mock in `api.js` | Done: `controller/` module folder; `app.js` modules with mocks outside the bundle; named stages in `reconstruct` and `_execute_verified` | L |
| 19 | P2 | Tests that check source text instead of behaviour (`details.test.mjs:22-25,83-86`); quick tier still builds CAD (`test_geometry*.py` unmarked); Rust test targets recompile modules by path | Done: behaviour tests in `details.test.mjs`; CAD tests marked; Rust tests import the library | M |
| 20 | P2 | Artifact names in several lists (`pipeline.py:208`, `transaction.py:178`, `run_record.py:431`); particulars 1e-6 m tolerance flags feet vs metres as a conflict; fairing modules import each other's privates | Done in `fc070c1`: one descriptor table, unit-aware tolerance, shared fairing module | S each |

## Reader work status

- Item 7: benchmark reader isolation started in `b90c166`. Real-sheet equivalence and published-score reproduction are still pending.
- Item 8: done on `lane/reader-thresholds` (results and limits in `docs/BODY_PLAN_CHINE.md`). Reduced Thayer and Balclutha sheets still read with many identity errors; they are flagged and not used without a person.

## Well designed (keep)

Process supervision and the macOS Seatbelt sandbox; exclusive run publication with sealed records
(`transaction.py:30`, `run_record.py:81`); bounded section simplification (`geometry.py:32`); explicit booklet
comparison limits; thin Tauri layer; independent analytical tests and failure-semantics tests; injected-timer UI tests.

## Proposed order

1. Test protection first (fixes 1-4): small, and they make the green ticks honest.
2. Process and model boundaries (5, 6) with the watchdog work.
3. Reader structure (7, 8) before wiring any new reader into the product.
4. Export integrity (10-13), then the rest as each area is next touched.
