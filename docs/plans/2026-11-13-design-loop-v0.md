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

## Results

- Gate frozen in `c3ff27b` before checks. Stable baseline quick tier exited zero: Python **2715 passed, 4 skipped, 100 deselected**, 5 dependency warnings, 601.89 s; Rust format/clippy/workspace tests, UI and bounded secret scan passed. Log: `work/checks/baseline.log`.
- Test-first evidence: four adapter/graph tests failed on absent module. Pipeline tests then failed on absent API. Real integration exposed canonical numeric values returning integer tank counts as floats; restore only checked integral counts/year, never truncate. Mixed-unit engine/operation table test failed before per-column units were added.
- G1 plumbing PASS: `scripts/check_design_loop.py` runs the real concept, variation, CAD arrangement, weights, Holtrop, propulsion, engine and indices modules. Public requirement: Ardmore Gibraltar owner Q88, 2 September 2025, summer DWT **49,999 t** (p3), laden economical service speed **11.75 kn** (p20). Source: https://www.ardmoreshipping.com/s/Ardmore-Gibraltar_q88_02Sep2025.pdf . Existing locally archived public source was read; no new account or external upload.
- Parent: existing public KVLCC2 IGES at the explicitly permitted public path, sampled through the existing supported-domain sampler. Retained length **263.999981 m**; missing 0.5 m bottom and omitted end domains remain stated. Freeboard heights are independently scaled within the supported domain, not extrapolated. The resulting geometry is a capped retained-shell demonstrator, not a full KVLCC2 or product tanker reconstruction.
- All four fleet rows, weight coefficients/CGs, engine tuning table, reference-power speed and annual operation are **synthetic plumbing assumptions**. The requirement is public; the regression is not a calibrated public fleet fit. The engine uses a supplied fixed rating and selects an admissible service margin; SFOC must match that rating. Weights use explicit initial engine mass/MCR and do not iterate back from selected propulsion. Predicted DWT is used for indices; required DWT is not forced to equal it. No feasibility, accuracy, statutory rating or compliance claim.
- G2 PASS on the first final replay: Python -> Rust -> Python canonical JSON identical, **1,124,117 bytes**. Explicit schema **1.1.0** adds only `nm` and `g CO2/(t nm)`. Frozen 1.0.0 schema/default remain unchanged. Named pure Python/Rust migrations validate both endpoints and change only version. Final committed-source replay also exited zero and preserved **1,124,789 bytes** after vector metadata refinement; log `work/design-loop/roundtrip.log`.
- G3 PASS: first run executes seven steps; identical rerun zero; 11.75 -> 12 kn executes **concept, power, engine, efficiency** only. Hull, arrangement and weights are cache hits. Independent tests cover DWT edits, annual-operation-only edits, version-key invalidation, corrupt cache refusal, output ownership and ordering. Content projection, not upstream execution, drives reuse. CLI supports config seeding or a changed canonical record.
- Focused final checks: **36 passed** in 16.42 s, including real CAD integration, CLI subprocess replay, schema migration, record and wheel/catalog tests. Earlier integrated schema task: Rust contract **5 passed**, clippy passed; both old/new record bridge examples preserved canonical bytes. Whitespace check passed.
- Elegance refinement: kept the existing quantity/evidence extension points; cache stores only owned patches, not stale full records. Missing quantities keep their metadata; vector quantities keep source method and uncertainty. Explicit mixed-unit table columns avoid labelling rpm, power, SFOC or fuel as dimensionless.
- Structural refresh scanner completed, but bootstrap failed with `ModuleNotFoundError: render_bootstrap`. Generated index moved to ignored `work/checks/codesight-index/`. Shared tooling unchanged.

## Use and replay

All commands run from this worktree, with `PYTHONPATH=src` and `/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`.

```sh
# Requires the parent JSON produced with the existing supported KVLCC2 sampler.
PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python scripts/check_design_loop.py --parent work/design-loop/parent.json --out work/design-loop/replay
PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python scripts/design_loop.py --config work/design-loop/replay/config.json --cache work/design-loop/replay/cache --out work/design-loop/replay/cli-record.json --receipt work/design-loop/replay/cli-receipt.json
PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python scripts/check_design_record_roundtrip.py --rust-binary target/debug/examples/design_record_roundtrip --record work/design-loop/replay/record.json
```

Library API: `create_record(config) -> DesignRecord`; `run_pipeline(record, cache_dir) -> (DesignRecord, Receipt)`. A step takes only the record and returns only the record. Receipt lists executed/cached steps and hashes, outside engineering quantities. Cache patches have a checksum and schema validation; this is integrity checking, not an untrusted-cache authentication boundary. Caller input must be public or synthetic; the v0 seeder labels scope public and is not a private-project authorization route.

## Resume point

Implementation checkpoints: `5599ab9` graph/adapters, `ff15efb` / `ae51ed6` / `bcd0fa1` / `86dc63f` versioned schemas/migrations/packaging, `07e1d3c` pipeline, `eec0150` gate replay/tests. Final quick tier is running on stable source (`work/checks/final-quick.log`). Record its exit and final canonical byte count, commit results, push only `lane/design-loop-v0`, do not merge. Inspect and delete this worktree's `target/` last. PM follow-up: replace labelled synthetic inputs with source-supported fleet/coefficients/tuning/reference-speed data, resolve full parent geometry and iteration before any engineering or accuracy gate. Prior frozen module gates remain unchanged.
