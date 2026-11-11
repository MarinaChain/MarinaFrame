# Pipeline Speed: Source Inspection and Parallel Work (Lane S)

**Goal:** Make the Gunnerus app run (code-only path: `inspect_source` x N, then `build_draft`)
faster with the same results. Accuracy behaviour does not change.

**Branch:** `lane/pipeline-speed` from `origin/continue/v0.5` (6b3cd24). Run data is in the
git-ignored `work/pipeline-speed/` folder of the lane worktree.

## Resume point

Status: IN PROGRESS. Steps done are marked [x].

- [ ] 1. Baseline: in-process copy of the controller sequence (`work/pipeline-speed/drive.py`),
      current code, profile of build_draft.
- [ ] 2. Parallel inspection: one `inspect_source` call inspects its whole batch in parallel
      workers; same catalog.
- [ ] 3. Exact per-section speed-ups in `ingest.py` (dilation).
- [ ] 4. build_draft hot spots (from the profile in step 1).
- [ ] 5. Identity check (catalog and build outputs, base vs new), quick test tier, push.
- [ ] 6. Before/after full run, same machine state, table below.

## 1. Facts at the start

Gunnerus app run of 2026-11-11 (heavy load): 14 `inspect_source` calls, 488.7 s wall in all;
child CPU 8.6-21.9 s per call. `build_draft` 636.5 s wall (327 s worker CPU, 271 s child CPU).

- The deterministic controller asks for 12 sections per call. `_inspection_batch` takes only
  about 5 Gunnerus sections (ROI 4.3 Mpx, estimate 1 CPU s/Mpx, budget 22.5 s) and runs them in
  one worker process, so the run needs 14 sequential worker processes.
- The budget is for responsiveness only ("it does not stop workers").
- One worker, 5 sections, in process: 12.3 s. `_trace` 4.4 s, `_foreground` 3.3 s (twice per
  section), 5x5 dilation 1.4 s, evidence PNGs 1.7 s, whole page image 0.5-0.9 s.
