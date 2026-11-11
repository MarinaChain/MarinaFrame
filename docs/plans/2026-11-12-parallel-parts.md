# Parallel Parts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build independent whole-vessel parts in worker processes without changing geometry, output order, or floating-point reductions.

**Architecture:** Reuse `parallel.worker_tokens`, not a second scheduler or pool. Resolve inputs in the parent, map independent builds to supervised processes, and collect contiguous groups in input order. Keep aggregate writers and dependency-bearing Boolean operations serial.

**Tech Stack:** Python, CadQuery/OCP binary shape transport, existing process supervisor and flock worker pool.

---

## Boundaries

Work only on `lane/parallel-parts` in `sol-parallel-parts`. Do not open sealed, holdout, or truth inputs. No Gunnerus timing run in this task. Keep the model-code sandbox unchanged. No time-based token reclaim, own-code wall cap, CPU cap, or heartbeat-based progress increments.

## Dependency graph

| Stage / part | Requires | Independent work / ordering constraint |
|---|---|---|
| `whole_vessel.py` GA, appendage and detail readers | Source drawings | Mutate shared inputs; keep their current sequence (`:294-301`). |
| Ship CAD decks, bulwarks, houses | Resolved outline/height; optional read-only HullSide grid and per-part detail | Do not require the hull CAD solid or another deckhouse. Separate solids can build independently (`ship_cad.py`, `_build_component`). |
| Appendage prisms | Outline and asymmetric span | Independent of hull and other appendages. |
| Ship CAD hull | Resolved station sections | Independent of other solid builds. |
| Opening | Target already built; previous openings on that target | Changes `shapes[target]`; retain complete serial path for a program with openings. |
| Panel hull / hull-to-deck | Same completed `hull/sections.json`; deck heights from inputs | Existing concurrent hull branches now reserve shared pool tokens, including parent loft. Join before hull volume/export. |
| Assembly part STEP import and precise integration | Step 1 part file | Independent per `PART_IDS`; collect in that exact order after hull. |
| Assembly display meshes | Final part shapes | Independent per shape. STEP export remains serial and occurs before mesh mapping, as before. |
| Tank tops, bulkheads, tanks | Completed hull GLB triangles through HullSlicer; source readings | Calibration, first-view placement precedence (`setdefault`) and duplicate-ID allocation stay serial (`whole_vessel_internals.py:667-737`). After placement, solid, mesh and component record are independent per Part. |
| Hull-conforming steel | HullSections / slicer and its section cache | Hull sections must exist first; no shared mutable cache across threads. Not changed by this lane. |
| Structure block thin member boxes | Serial reading, stations, thickness/material labels (`block3d.build_block`) | Each placed member box is independent. Parent retains member order for STEP/IGES/3dm. |
| Structure section slices | Placed section members | Independent segment boxes, but currently retained serial (small builds). |
| Aggregate exports / totals | Ordered part results | Single writer; same compound order, same integration and `sum` order. No parallel reductions. |

## Design review

- Architecture **PASS**: existing tokens and `supervise_process`; one token per active CAD child; parent does not build CAD while part children run.
- Quality **PASS**: one process-map helper, top-level pickleable callables, private per-call temporary directory. Pickle only transports host-created objects between trusted own-code processes; it is not accepted from drawings or model code.
- Coverage **PASS**: process/order, occupied-pool bound, serial no-spawn, same exception, synthetic mesh/GLB/STEP DATA identity and component report identity.
- Performance **WARN**: process startup and shape transport have a cost; use contiguous groups, not one interpreter per part. Small steel boxes may not benefit; full timing remains pending.
- Security **PASS**: sandboxed ship-CAD worker defaults to serial (`workers=1`) and its sandbox/profile is untouched. Only explicit trusted development `--in-process` enables process builds. Do not unpickle model-worker output or grant the sandbox access to the home token directory.

## Tasks and checks

1. Add `tests/test_parallel_parts.py`; observe missing `process_parts` failures. Implement `parallel.process_parts` and private `part_process` entry. Tests must prove separate PIDs, input-order collection, no spawn in serial mode, occupied-pool bound, cleanup, and the first serial error.
2. Extract ship-CAD component builder without changing arithmetic or exceptions. Opt in through `execute(..., workers=None)` only on trusted development path. Keep openings serial. Preserve default sandbox behavior.
3. Use map for assembly per-part imports/volumes and display meshes. Wrap the existing two hull branches in `worker_tokens` so the parent and child count against the same pool.
4. Map already placed internal parts and structure block boxes. Keep export functions and aggregate operations in the parent.
5. Run small synthetic CAD tests and related regressions; run exactly:

   ```sh
   MARINAFRAME_TEST_PYTHON=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
   ```

6. Review changes, record results here, commit with required attribution, push `lane/parallel-parts`; do not merge.

## Identity criteria

- Compare STEP **DATA bytes**, not timestamp-bearing headers. Use fresh interpreter runs: OCC keeps process-global STEP product/assembly counters, so two exports in the same process are not a valid serial/parallel baseline.
- Compare complete GLB bytes, mesh array bytes and JSON bytes. Timing/path/header hashes in CLI assembly receipts retain their existing meaning; do not remove or round fields to hide a difference.
- Preserve known pre-existing pcurve repeatability caveat from `2026-11-11-build-speed.md`; a full-data mismatch must be reported, not tolerated silently.

## Exact later timing commands (not run now)

Run after the PM releases the machine (not before 10:00 SGT). Source and STEP 1 input locations must be the approved development paths. These commands create only this worktree's own outputs. No truth option is used.

```sh
PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
S=/Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources/gunnerus
R=work/parallel-parts/timing-001
mkdir -p "$R"
PYTHONPATH=src:. MARINAFRAME_WORKERS=1 "$PY" -m benchmarks.gunnerus.whole_vessel_timing step1 --sources "$S" --out "$R/serial/step1" --in-process
PYTHONPATH=src:. MARINAFRAME_WORKERS=8 "$PY" -m benchmarks.gunnerus.whole_vessel_timing step1 --sources "$S" --out "$R/parallel/step1" --in-process
PYTHONPATH=src:. MARINAFRAME_WORKERS=1 "$PY" -m benchmarks.gunnerus.whole_vessel_timing assembly --sources "$S" --step1 "$R/serial/step1" --out "$R/serial/asm"
PYTHONPATH=src:. MARINAFRAME_WORKERS=8 "$PY" -m benchmarks.gunnerus.whole_vessel_timing assembly --sources "$S" --step1 "$R/parallel/step1" --out "$R/parallel/asm"
PYTHONPATH=src:. "$PY" -m benchmarks.gunnerus.whole_vessel_compare "$R/serial" "$R/parallel"
PYTHONPATH=src:. MARINAFRAME_WORKERS=1 "$PY" -m benchmarks.gunnerus.whole_vessel_internals --sources "$S" --assembly "$R/serial/asm" --out "$R/serial/internals"
PYTHONPATH=src:. MARINAFRAME_WORKERS=8 "$PY" -m benchmarks.gunnerus.whole_vessel_internals --sources "$S" --assembly "$R/serial/asm" --out "$R/parallel/internals"
PYTHONPATH=src:. "$PY" -m benchmarks.gunnerus.whole_vessel_compare "$R/serial/internals" "$R/parallel/internals"
```

Record machine load, granted workers and stage timings. Do not infer speed-up from unit tests.

## Resume point / results

- Focused synthetic CAD / ship-CAD / internals / structure / shared-pool regressions: **66 passed in 46.74 s**. STEP DATA, GLB, saved mesh arrays and provenance JSON equality passed; internal records and meshes match; steel volumes match.
- Initial quick-tier attempt stopped in Rust `real_worker_replaces_one_unreadable_extra_sheet_without_a_hull_rebuild`: `worker_implementation_changed`. Source was still being refined while that test froze its worker identity. This is the intended identity guard, not a weakened gate. The unchanged-source rerun passed Rust, then the tool stopped the process at its 600-second background allowance with Python at 29% and no reported failures. This was not a completed quick-tier pass. A fresh unchanged-source run used the tool's longer 7200-second allowance and wrote `work/parallel-parts/quick-complete.log`; it also ended during Python tests with `Terminated: 15` (tool exit 144), after Rust passed. The log does not identify the signal sender. No application timeout was added. **The required quick tier was run but did not complete; Python-wide, UI and secret-scan completion are not established by this run.** Do not treat this branch as merge-ready on this evidence.
- Final new identity suite: **7 passed in 31.64 s**. Related step-one, comparison and parallel-inspection regressions: **34 passed in 13.73 s**. Smooth-mesh and structure-display regressions: **14 passed in 5.64 s**. An earlier optional related-test command named a nonexistent `test_display_mesh.py`; no tests ran in that invocation, and the corrected list passed.
- No full Gunnerus run started. No speed-up claim yet. Sandboxed step 1 remains serial by design; trusted development mode is explicit.
- No `.codesight` tree exists in this worktree; refresh helper dry-run accepted this path, but no stale generated index was found to update.

Resume: rerun the required quick tier in a session that is not externally terminated; inspect `work/parallel-parts/quick-complete.log` for the interrupted evidence. The implementation and focused regressions are complete; commit/push this lane without merging. Then the PM can run the exact timing commands above on a free machine. Full-vessel output identity and speed remain unmeasured.
