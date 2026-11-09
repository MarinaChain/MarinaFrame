# Bottom Handling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Preserve measured cells while completing missing bottoms in their local direction, without lowering transom endpoints.

**Architecture:** Correct the anchor bottom completion in `first_hull_tools.py`, before `form_fit.py` creates section rows. Keep original points intact; carry interpolation provenance into the vessel table and build. Do not change the frozen reader, gates, or sealed data.

**Tech Stack:** Python, NumPy, pytest, existing CAD worker and development replay scorers.

---

## Review

- Architecture: PASS — correct the source of the chord, not fairing.
- Code quality: WARN — preserve the existing removal of unsupported centreline tails, not real measured cells.
- Coverage: WARN — report matched-cell coverage; dropping BUE GIRL station 10's lowest truth cell is not a comparable improvement.
- Performance: PASS — bounded curve sampling; run CAD cases sequentially.

## Step 1 — failing regressions (commit before implementation)

Create `tests/test_first_hull_bottoms.py`: four measured waterlines, unchanged lowest cell, local lower tangent, profile conflicts, raised transom end. Run:

`set -o pipefail; PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_first_hull_bottoms.py -q`

Observed baseline: four failures (chord slope and removed cells), one pass (terminal end exemption). Commit tests and this plan.

## Step 2 — fix and checks (commit before replay)

Modify `src/vessel_reconstruction/first_hull_tools.py` bottom helpers; carry point provenance through `form_fit.py` and `vessel_model.py` if needed. Add tests for labels and end handling. Continue only below the original curve, with its lower direction. Keep raised terminal curve ends. Preserve the centreline-noise trimming test without deleting off-centre cells.

Run the new suite and existing hull-end, materialization, profile, intake, form-fit, reading-selection, section-authoring and build tests. Use `set -o pipefail` first in each test chain. Check `git diff --check`; commit the complete fix.

## Step 3 — stored development replay and report (commit)

Use stored BUE GIRL intake and reader output, with `/private/tmp/claude-501/bue-girl/truth_s2.json`. Replay all ten stored L0/L1 development readings through the first-hull path, fairing disabled, against the unchanged baseline and fix. Keep temporary outputs in `work/`; keep final machine-readable results in `outputs/`. Record RMS and coverage in a short subsection of `docs/AUTO_CALIBRATION.md`. No images, live reader calls or sealed data. Commit results and documentation.

## Resume point

Continue from the latest committed step on `fix/bottom-handling`. Never push, merge, switch branches, or pipe git commands. Step 1's red suite is intentional until step 2 lands.
