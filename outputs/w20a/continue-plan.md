# W20a Happy-Path Continuation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the read phase without one setup request per body panel or refusals for recoverable model formatting.

**Architecture:** Keep existing worker/controller dispatch. Normalize descriptions at the Python tool boundary, preserving original claims and extra metadata with warnings; normalize malformed decision envelopes before Rust deserialization. Propagate the first body setup to same-scale panel members, with translated or supplied panel datums. Use supplied drawing calibrations and measured grid evidence, never checker truth.

**Tech Stack:** Python/NumPy/SciPy/Pillow, Rust/serde_json, pytest, Cargo.

## Plan review
- Architecture PASS: no new service or gate; reuse setup records and public measurement functions.
- Quality WARN: preserve unknown values as metadata but keep computational fields numeric/null; warn instead of rejecting.
- Coverage WARN: test separately for shifted panel datums, shared scale, unknown principal fields, string rows/ends and malformed outer notes/arguments.
- Performance PASS: existing bounded tools; only one six-case development round. New work data below 2 GB.

## Steps
1. Run `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`; commit existing checkpoint as-is. Previous full run was interrupted, not passed.
2. Add failing shared-body-family tests in `tests/test_description_tools.py`. In `investigation_tools.py`, default body views to one family, accept optional panel/family/setup metadata and propagate first setup across members. Use each panel's supplied calibration or translated datum, retaining family source/warnings. Keep separate plan/profile setups.
3. Add failing permissive-description tests in `tests/test_vessel_description.py`. In `vessel_description.py`, preserve raw claims, coerce finite numeric strings, retain extra/odd metadata with field warnings, normalize ends and row arrays without rejecting. Remove shape-based rejection at description dispatch only. Add incomplete waterline warnings, measure panel grids independently and separate baseline from labelled waterlines.
4. Add malformed-envelope Rust tests in `provider.rs`/`types.rs`. Repair misplaced reason/notes, stringified arguments and bounded extra metadata. Do not invent unknown operations. Update catalog/instructions to show shared body family and accepted description examples.
5. Run focused tests; freeze runtime and Python source under main `work/w20a/round4-*`. Run exactly one R-body round of four cases and one arm with the two available three-view cases via `run_round.py`, Phase 1-only, seven requests. Inspect every trace.
6. Update offline checker to distinguish strict numeric accuracy from acceptable warned unknowns for sheet-absent dimensions. Keep wrong numbers failed, missing descriptions failed, and station/waterline denominators unchanged. Save table and all receipt costs.
7. Run `make test-full` on stable source; record exact outcome. Update report and lesson via gateway checks. Commit, no push or merge.

## Storage
Existing work/w20a is about 85 MB, with one runtime/source per cited round and no duplicate build folders. Removed only inspected bytecode caches. Retain reports, JSON and runtimes; inspect targets before any further deletion. Reuse existing Cargo target cache, monitor free disk. Keep added data below 2 GB.

## Resume
Checkpoint b7ca986 committed after fresh quick pass (855 Python tests). Happy-path fixes pass 23 focused Python tests and 77 Rust library tests. Frozen runtime/source in main `work/w20a/round4-runtime` and `round4-source`. Exactly one four-case body arm and two-case three-view arm launched detached; logs `round4-body.log` and `round4-3view.log`. Full verification running in `continue-test-full.log` (task bnvjlms5g); do not edit worker package until it ends. All six traces inspected: every case completed describe_views -> describe_vessel in two requests, no rejected outputs. Saved continue-checks.json/traces/digest; 12 requests cost USD 0.02406242. Body dims 2/4 acceptable, stations 4/4, waterlines 3/4; dimension target unmet. Runner misclassified Phase 1 pause as failure after first body wave; launched only remaining unstarted two in round4-body-rest. Full verification passed exit 0: 862 non-CAD Python tests, 24 Python CAD tests, Rust workspace and real-CAD groups, app real task, release and deterministic smoke. Log continue-test-full.log. Next: commit without push/merge; report target unmet. Current work data about 104 MB (new about 20 MB).
