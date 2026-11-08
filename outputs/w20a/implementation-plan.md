# W20a Read the Vessel Implementation Plan

> **For Claude:** Use executing-plans to implement the approved design task by task.

**Goal:** Read a sheet into a measured, warning-labelled vessel description before first-hull construction.

**Architecture:** Add a Python description/survey module, connect it through existing domain tools and checkpoints, and add typed Rust model tools. Run survey without a model request; ask for view identities, setup per geometry view, and a vessel description. Use existing public first-hull/table functions; keep all checks advisory.

**Tech Stack:** Python/Pillow/NumPy/SciPy, Rust/serde, existing live investigator and round runner.

## Boundaries

- Branch `w20a-read-vessel`; no push or merge.
- Do not edit `vessel_model.py`, `form_fit.py`, `panel_assignment.py`, `fairness.py`, `investigation.py`, `view_measure.py`, or `whole_vessel_score.py`.
- Runtime snapshots, logs and development data only in `/Users/jonathanjie/Documents/workspace/MarinaFrame/work/w20a/`.
- Never open sealed v2/v3. Use only supplied development input drawings/specifications.
- Preserve `engineering_approved=false` and existing frozen geometry scoring gates.

## Design review

- Architecture: PASS. Use domain dispatch/checkpoint and typed operations, not a second controller.
- Quality: WARN. Keep measured and model values side by side; name the exact doubtful field and repair in each warning. Grid lines are not hull extents.
- Tests: PASS. Synthetic sheets test pixel results independently of model claims; tool and phase tests cover routing and persistence.
- Performance: WARN. Bound survey tiles/strokes and observations; no CAD or section tracing in Phase 1 evaluation.

## Execution checklist

1. Read current source and add failing tests for survey, description measurements, field warnings and persistence.
2. Implement `src/vessel_reconstruction/vessel_description.py`, reusing public grid/stroke operations where possible.
3. Add `survey_sheet`, `describe_views`, and `describe_vessel` domain dispatch, checkpoint summaries and persisted vessel description. Snap setup datums and report distances without refusing claims.
4. Add Rust types/catalog entries and phase ordering: survey -> describe_views -> per-view setup -> describe_vessel -> existing first hull. Add a Phase 1-only pause option for evaluation. Keep existing task compatibility.
5. Feed description stations, principal dimensions and waterline grid through `first_hull_tools.py` and existing public table functions, without changing other lanes.
6. Run focused Python/Rust tests, then freeze runtime and worker source under main `work/w20a/`.
7. Run two development smoke cases detached with `scripts/run_round.py`; inspect all traces. If useful, finish the four R-body cases and both available R-3view cases. Use `scripts/round_digest.py`; report requests and all receipt costs, including failed attempts.
8. Use `demand-elegance` for the final change review. Run `make test-quick`, then `make test-full` on stable source. Record failures and reruns.
9. Write `outputs/w20a/report.md` with the Phase 1 check table, costs, missing inputs, tests and commit IDs. Commit on the requested branch only.

## Acceptance

R-body: dimensions within 2% in 4/4; station and waterline sets correct in at least 3/4; at most 7 requests per case; each wrong field receives a named warning. R-3view: same checks for DTMB L0 and Ship-D 00679 L0 (00045 and 00683 are not present). Measure Phase 1 only, without truth geometry or CAD scoring. Do not turn unavailable inputs or unmeasurable fields into passes.

## Resume point

Plan saved after reading design, lessons, investigator history and continuation status. Next: implement and run focused regression tests. Update this section with frozen runtime paths and detached run commands before starting evaluation.
