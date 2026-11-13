# Design loop v0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the six merged foundations through a draft design record and an input-hashed step graph.

**Architecture:** Each step accepts and returns a validated record. Explicit input projections form a directed acyclic graph; cached patches contain only a step's owned output fields. All caller inputs and parent sections are recorded as tagged evidence. Fragment adapters preserve missing values, source methods and uncertainty. A named migration adds efficiency units without changing the frozen 1.0.0 contract.

**Tech Stack:** Python, existing NumPy/CadQuery modules, JSON Schema, existing Rust serde bridge, pytest.

## Scope and architecture review

- Work only on `lane/design-loop-v0`, from local `continue/v0.5` at `5dc2585`. No CFD, PRD or ROADMAP edits. No sealed, holdout or pilot data. No original product identifiers.
- Architecture PASS: use existing tagged evidence extension points; no second calculation implementation. Unit vocabulary requires a versioned schema, not opaque unit substitution.
- Quality WARN: concept fits require complete fleet rows; weight coefficients and engine tables require explicit assumptions/sources. Do not invent public calibration. Existing parent is a trimmed KVLCC2 shell; state its missing domain.
- Coverage PASS: test fragment conversion, graph invalidation, malformed inputs, cache corruption, CLI, actual module integration and Rust canonical round trip.
- Performance WARN: CAD is sequential and cached. Cache only owned patches, never a whole stale record. No network or solver runs in the pipeline.

## Fixed exit gate (written before checks)

G1: A requirement copied from cited public product-tanker particulars produces one schema-valid record through requirements -> concept dimensions -> scaled/varied KVLCC2 parent -> arrangement -> preliminary weights/deadweight -> Holtrop/propulsion -> engine -> EEDI/CII. Record remains `draft`, engineering_approved false. Every stored numeric value is a quantity with unit, method/version, sources and uncertainty or an explicit unknown reason. Any synthetic fleet/calculation assumptions remain labelled synthetic, never public evidence.

G2: Python -> Rust -> Python preserves canonical JSON exactly. New units require schema version bump and named pure migration from validated v1, with target validation and no dropped data. Existing v1 fixtures remain supported.

G3: Identical rerun executes zero calculation steps. Change service speed only: concept reference ranking, resistance/power, engine and efficiency recompute; unchanged chosen dimensions do not force hull, arrangement or weight recomputation. Also test changed DWT, operational-only input, code-version keys and corrupted-cache refusal. Hash actual input projections plus step version; downstream reuse depends on content, not merely upstream execution.

G4: Targeted tests, real CAD integration, Rust bridge and `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python CARGO_TARGET_DIR=target` exit zero before push. Run long checks in background. No gate widening. No accuracy or compliance claim; prior module accuracy gates stay unchanged.

## Small commit steps

1. Commit this plan and gate before checks. Read module interfaces and source-linked public input. Run a stable-source quick baseline in background before implementation.
2. Add adapter tests first; map fragment quantity metadata and complete nested evidence into existing record extension maps. Add schema 1.1.0 and explicit migration with Rust/Python tests in a separate bounded task. Commit.
3. Add test-first DAG runner in `src/vessel_reconstruction/design_loop/__init__.py`: dependency order, stable input hashes, owned patches, persistent cache integrity and execution receipt. Commit.
4. Add record-only calculation steps using concept, hull variation, arrangement, weights, Holtrop, engine and indices. Add `scripts/design_loop.py` with JSON input/output/cache arguments. Caller supplies full source-linked fleet, parent sections, weight assumptions and engine layouts. Commit.
5. Add `tests/test_design_loop.py` integration and CLI cases. Run public requirement gate with permitted existing parent only, keep source data in ignored work. If a necessary source is absent, report blocked rather than substitute an accuracy claim. Record gate results and exact resume commands here. Commit.
6. Use demand-elegance, run final quick tier on stable source, inspect diff/identity boundaries, commit results and push only lane branch. Do not merge. Inspect and delete only this worktree's `target/` as the final step.

## Resume point

Plan and gate written; implementation not started. Next: commit plan, run quick baseline, then adapter/DAG tests. Public requirement and parent provenance must be frozen before the integration calculation. Schema work is delegated independently; do not duplicate those files. All final results remain pending.
