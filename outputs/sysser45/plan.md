# Fail-closed stroke identity implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop the silent wrong `sysser45-L1` build without changing a CAD or accuracy gate.

**Architecture:** Check whole-trace identity against the original source, before a corridor can hide a ruler continuation. Share the check between extraction and candidate generation. Keep explicit local height ranges; refuse unsupported continuations rather than infer endpoints from reference geometry.

**Tech Stack:** Python, NumPy, Pillow, pytest; existing Rust controller and OpenCascade benchmarks.

## Review

- Architecture: PASS. Use the existing lattice detector and one shared source check.
- Quality: PASS. No reference enters inference; no CAD or validation change.
- Coverage: WARN. Test a shortened hull, a grid crossing, corridor masking, explicit local endpoints, and a complete stroke control.
- Performance: PASS. Bounded raster and row arrays; no new search space.

## Task 1: Baseline

1. Regenerate `sysser45-L1` from the frozen manifest. Require matching hashes.
2. Open baseline PNGs and record visible wrong continuations.
3. Run the pinned controller and independent scorer. Freeze Python source for concurrent baseline probes.
4. Record the 528 development selection fingerprints and the 45 procedural drawings plus two examples.

## Task 2: One falsifiable hypothesis

H9: A sustained trace segment on a detected vertical ruler, followed by a departure onto another stroke, cannot establish whole-stroke identity. Refusing it in both extraction and catalog generation stops the wrong build.

1. Add `tests/test_source_stroke_identity.py` with small synthetic rasters. Run before the fix and preserve assertion failures.
2. Share the existing lattice detector in `ingest.py`; retain its `agent_tools.py` import contract.
3. Add a source-only identity diagnostic. Refuse ruler continuations with a blocking reason, including with an explicit corridor.
4. Reject the same hypotheses in `inspect_source_worker`, with diagnostic evidence.
5. Run the synthetic tests and frozen case. Keep or revert based on measured results. Record all attempts in `docs/GEOMETRY_ACCURACY_V05.md`.

## Task 3: Verification

1. Replay development selections. Build and score the four formerly correct factory cases and every new all-selected case.
2. Compare procedural fingerprints; report every changed outcome and zero newly wrong builds only if evidence supports it.
3. Open after PNGs. Record what is visible, not only file paths.
4. Run `make test-quick` with the supplied Python and worktree source. Check `pgrep -fl 'make test-full'`, then run full tier once if none runs. Do not edit source during pinned tests.
5. Review the diff for clarity. Commit on `fix-sysser45`, do not push. Run `cargo clean` when no evaluation uses the binary.

**Resume point:** Baseline source regeneration and sysser45 inspection are complete. Baseline native replay and independent development/procedural probes are in progress. No production source has changed.
