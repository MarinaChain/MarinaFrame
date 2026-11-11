# Pipeline Speed: Source Inspection and Parallel Work (Lane S)

**Goal:** Make the Gunnerus app run (code-only path: `inspect_source` calls, then `build_draft`)
and the whole-vessel assembly faster with the same results. Accuracy behaviour does not change.

**Branch:** `lane/pipeline-speed` from `origin/continue/v0.5` (6b3cd24). Run data is in the
git-ignored `work/pipeline-speed/` folder of the lane worktree (drawing derivatives: not in git).

## Resume point

Status: DONE for this lane (not merged). Commits: 087507c, 352bb7b, ff248cb, plus this file.

- [x] 1. Baseline and profiles (in-process controller copy `work/pipeline-speed/drive.py`).
- [x] 2. Parallel inspection: one `inspect_source` call inspects its batch in parallel workers.
- [x] 3. Exact speed-ups: stroke tracking (`investigation._track`), 5x5 dilation, Rhino 3dm export.
- [x] 4. Whole-vessel assembly: hull to deck beside the panel loft.
- [x] 5. Identity checks, quick test tier (Python, UI, secrets; no Rust file changed).
- [x] 6. Before/after app run through the controller, side by side (table in 4).
- [ ] Follow-ups (section 5), for the PM to assign.

To repeat a check: `PYTHONPATH=src python work/pipeline-speed/drive.py <new task> <spec>` runs the
controller's sequence in process; `work/pipeline-speed/compare.py A B` compares two tasks (catalog,
selections, guesses, every draft build file); `work/pipeline-speed/receipts_table.py` sums controller
receipts.

## 1. Where the time went (Gunnerus, before)

App run of 2026-11-11: 14 `inspect_source` calls (488.7 s wall), `build_draft` 636.5 s.

- **Inspection.** The deterministic controller asks for 12 sections per call, but
  `_inspection_batch` took only about 5 Gunnerus sections (4.3 Mpx ROI, 1 CPU s/Mpx estimate,
  22.5 s budget) into one worker process: 14-15 sequential workers. The budget is for
  responsiveness only ("it does not stop workers"). Per section about 2.4 CPU s.
- **build_draft, part 1: panel assignment (about 300-480 s).** `assign_shared_panels`
  (panel_assignment.py, lane O) enumerates the strokes of the 2 shared panels;
  `investigation.enumerate_strokes` follows 154 seeds with `_trace_best_path`. `_track` read ink
  one sample at a time in a Python generator: 49 M `_ink_at` calls, 100 M `round()` calls.
- **build_draft, part 2: the hull build (377-410 s).** `pipeline.reconstruct` in the isolated
  worker. `rhino_exports.export_3dm` took 256 s of it: `face.Wires()` for each of the 19,172 hull
  faces pays the slow end of an OCP iteration (about 6 ms; the lane D lesson, topology.py).
  cProfile showed only about 100 s of this build; direct stage timers found it
  (`work/pipeline-speed/cad_timing.py`).

## 2. Changes

1. `parallel.py` (new): `worker_count(pieces)` = `MARINAFRAME_WORKERS` if set (1-32), else
   cores - 2, at least 1, at most `pieces`; `run_in_order` (threads that each wait on one
   supervised process; results in input order); `split_evenly`.
2. `agent_tools._inspect_source`: the batch budget is the single-worker budget times the worker
   count; uninspected sections of the batch are split into contiguous groups, one supervised
   worker (`isolation.supervise_process`, no wall limit) per group. Results go into the catalog in
   request order; artifacts keep the one-worker order (all evidence files, then all model
   observations); only the first worker draws the source page, with every ROI of the call, so a
   call still has one page. With one worker the old path runs unchanged. A failed group fails the
   call as before; groups that succeeded are kept.
3. `investigation._track` and `_recentre`: `_ink_hits` reads the ink at all (angle, radius)
   samples of a fan in one array operation. Same arithmetic: the fan cosines and sines come from
   `math.cos`/`math.sin` as in `_rotate`, elementwise multiply and add as before, `np.rint` rounds
   half to even like `round`, scores and the strict `>` choice stay per angle in order.
4. `ingest._dilate_5x5`: shifted ors along each axis (same mask as the 5x5 maximum filter, 14x
   faster).
5. `rhino_exports.export_3dm`: `topology.faces`, `topology.wires` and `topology.face_triangulation`
   instead of `Faces()`, `Wires()`, `tessellate()` (same shapes, order and values). The structure
   exports (`structure/block3d.py`, `solid.py`) use the same function.
6. Whole-vessel assembly: `vector_path.run(..., after_read=)` calls back after `sections.json` is
   written; `whole_vessel_assembly.HullToDeckJob` then builds the hull to deck in a supervised child
   process while the parent lofts the panel hull (lane D's open item). `MARINAFRAME_WORKERS=1`
   keeps the sequential build.

## 3. Identity

- Panel stroke enumeration (both Gunnerus panels, old vs new code, separate processes):
  byte-identical JSON (344,188 bytes).
- App run, base vs new (in process and through the controller): catalog, selections, guesses and
  95 of 104 build files identical. The rest: the copied implementation source (expected), the IGES
  header timestamp, and the 3dm file (its created/edited time; all 19,172 objects decode to the
  same geometry, names and face indices; the same counts 19,140 exact surfaces, 32 trimmed planes,
  0 meshes). STEP, STL and mesh files are identical.
- Hull build alone, old vs new 3dm export: all objects, attributes and counts identical.
- Assembly, sequential vs parallel: `whole_vessel_compare.py`: 29 files, only `assembly.json`
  differs, in timing fields, the run folder path and `assembly_step_sha256` (STEP header time).
- Tests: `tests/test_parallel_inspection.py` (worker count, order, vectorized ink reading and
  dilation against the scalar forms, 1 vs 3 workers give the same catalog and artifact order).

## 4. Results

### 4.1 App run through the controller, side by side (same start, 19:33:07; load 6.7 at start, 9.3 when the new run ended, 10.7 when the base ended)

`marinaframe run --policy deterministic --on-ambiguity draft`, base = `git archive` of the branch
base, new = this branch. Wall seconds from the worker receipts.

| Stage | Before | After |
|---|---:|---:|
| inspect_source (all calls) | 309.6 (15 calls) | 91.4 (6 calls) |
| build_draft | 722.7 | 289.7 |
| **Whole run (controller start to exit)** | **1,056 (17.6 min)** | **389 (6.5 min)** |

The base ran alone for its last 11 minutes (lower load), so its numbers are if anything favoured.
CPU seconds (receipts): inspection 238.9 -> 268.2 (parallel startup cost), build_draft 691 -> 254.

### 4.2 Parts (single runs, load 7-17 each)

| Part | Before | After |
|---|---:|---:|
| Panel stroke enumeration, 2 panels | 523.9 | 139.1 |
| Hull build (`pipeline.reconstruct`), of which 3dm export | 377.1, 256.0 | 98.6, 10.0 |
| Whole-vessel assembly (side by side, load 5-17) | 446.7 | 390.7 |

## 4a. Machine-wide worker pool (PM decisions, 2026-11-11)

The controller clears the worker environment, so `MARINAFRAME_WORKERS` never reached the app's
worker. A per-slot split (cores - 2 divided by the native slots) gave 1 worker per run on this
10-core Mac (5 slots), so the PM chose a machine-wide pool:

- `parallel.worker_tokens`: max(1, cores - 2) tokens, each an exclusive `flock` on one file in
  the user's home cache, which other users cannot create: macOS
  `~/Library/Caches/io.marinachain.marinaframe/worker-pool`, else `~/.cache/marinaframe/worker-pool`
  (home from the password database, not HOME or XDG_RUNTIME_DIR: the controller clears the worker
  environment). Mode 0700, owner and links checked; token files opened with O_NOFOLLOW. If the
  folder or a token cannot be used safely (security review: a shared /tmp path could be
  pre-created by another user), the call logs a warning and runs with its own bound, without the
  shared limit; the pool never fails an inspection (tests: shared mode, symlinked folder, foreign
  owner, symlinked token). An inspection call takes every free token up to what it
  can use (at least 1; it waits while none is free; cancellation stops the wait) and gives them back
  when its workers end. The kernel drops the locks of a process that ends, so a crashed run's
  tokens come back at once; nothing expires on a clock. Every inspection on the machine (app,
  `marinaframe run`, scripts) uses the same pool.
- The batch of a call depends only on the bound, never on the free tokens, so the calls a
  controller makes do not depend on machine load; the tokens only decide how many processes
  share the batch (same catalog: tested).
- Upper bound: `Settings.inspection_workers` (app, optional) -> `Config.inspection_workers` (not
  serialized when unset; older ledger hashes stay) -> `--inspection-workers` (only when set) ->
  `DomainTools.inspection_workers`. `marinaframe run --inspection-workers 1..32` sets it on the CLI.
  `MARINAFRAME_WORKERS` stays for command-line scripts.
- Tests (`tests/test_worker_pool.py`, `tests/test_parallel_inspection.py`): a lone run gets
  cores - 2 (8 of 8 with 10 cores); 2 and 5 concurrent runs (separate processes) never hold more
  than the pool; a SIGKILLed holder's tokens come back; a waiting run stops on cancel; the pool
  folder must be private; a run that finds 1 of 2 tokens free inspects with 1 and gets the same
  catalog and batch. Rust: the bound reaches the worker as an argument only when set.
- Single run, Gunnerus inspection step in process (`work/pipeline-speed/inspect_only.py`):
  6 calls, 8 workers each: **95.0 s** at load average 11-23, and 161.0 s at load 24-30 (other
  lanes compiling); every inspected candidate identical to the earlier runs. Through the controller at load 7-10 the same path took
  91.4 s (section 4.1).

## 5. Not done / follow-ups

- Settings page control for `inspection_workers` (the field exists; the page does not show it).
- **Lane O (panel_assignment.py):** the shared panels are enumerated one after the other; they are
  independent and could run in parallel processes (2 panels: about half of the remaining 139 s).
  Not changed (lane O's file).
- `investigation.trace_in_source_corridor` (about 70 s of panel enumeration, profiled) is array
  code whose `_trace` parameters depend on the window width; it was left as is.
- `isolation.supervise_process` walks the output folder every 50 ms (`_output_bytes`): 6,586
  walks, about 48 s of supervisor CPU (profiled) during one hull build. It runs beside the child,
  not on its path; a slower check would weaken the output-size limit, so it was left.
- Step 1 part builds (`ship_cad` worker, about 30 s) and per-tank/steel builds were not
  parallelised.
