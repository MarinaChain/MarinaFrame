# W18d: protect the fitted first hull

## Governing order

Follow PM 16:30 override. Merge only w19-0-integration, w19a-form-fit, w19b-view-measure; canonical geometry is W19a VesselTable. No truth in inference. Keep scoring gate 2%/5%. Raw data main work/w17, all edits/commits in current worktree.

## Checkpoints

1. Merges completed: integration 1c2249b, form fit 27427d3, view measure merged after it. Schema conflict kept human acceptance and added table-fit authored validation. Merge quick passed838.
2. Internal build_first_hull operation inspects/assigns panels, derives W19a anchors, fits/builds before first model request. Render exposes F1 overlay and W19b/D1 scoreboard. Preserve fitted spec across later revisions. Run four R-body cases (DTMB L0, 00045 L2, 00679 L0, 00683 L2), digest --factory. First-hull quick/build running.
3. Edit transaction: compare same drawing-derived combined score with frozen waterlines/half beam. Keep improving/gap-only edits, otherwise restore incumbent and explain scores. Identical authored curve merges without new revision. Preserve best build at finish/stop.
4. Normalize provider decisions (truncate notes, clamp existing numeric args, warnings), default80 request budget, N non-improving edits/builds soft finish. Run same R-body round with --factory again.
5. C2 invalid-shell section fallback: W19a first_hull already retries by dropping suspect anchor into fitted row; verify00683-L0 and add draft fallback regression if needed.
6. Full tests, honest per-case first-vs-final score and usage, docs/results, commits no push/main merge.

## Current limitations to verify

First hull uses inspection candidate scores (not truth) and actual traced corridor points. W19b stand-in adapted from canonical table, not persisted as second source. Avoid comparing automatically rescaled scores across edits. Read overlay/fairness after rendering. Do not mistake table score for frozen gate accuracy.
