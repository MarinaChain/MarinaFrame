# Design Record v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Store a complete draft ship design in one strict, versioned, portable record.

**Architecture:** JSON Schema is the contract. Python validates it before loading and saving. Rust uses matching serde types, rejects unknown record fields, and checks semantic constraints. Named quantity maps are explicit extension points, not untyped metadata. Customer scope is a label, not an authorization service.

**Tech Stack:** JSON Schema 2020-12, Python dataclasses/jsonschema, Rust serde/serde_json.

## Scope and boundaries

Work only on `lane/design-record` in `.claude/worktrees/design-record`, based on local `continue/v0.5`. Public KVLCC2 inputs and synthetic data only. Do not open holdout, sealed, pilot data or other lane worktrees. Do not edit PRD, ROADMAP or modules owned by other lanes. No engineering approval is granted. No original licensed-product identifiers are introduced.

## Review before implementation

- Architecture: PASS. Independent Python package and app/core module; no dependencies on other batch lanes.
- Quality: PASS with a risk: Rust/Python validation must stay aligned. Use the same invalid corpus in both languages.
- Coverage: PASS with a risk: record round trips alone do not prove result capture. Compare captured output to original results, including warnings and inputs.
- Performance: PASS. In-memory records; no solver calls or network services during serialization.

## Gates (fixed before checks)

### G0 — first schema draft and baseline quick tier

Commit this plan and the schema before checks. `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python CARGO_TARGET_DIR=target` must pass before pushing the first schema draft. Run in background. A baseline failure is reported, not hidden. No gate thresholds will change after results.

### G1 — strict contract

Schema self-check passes. Python and Rust accept the public fixture and reject the same invalid corpus: unknown top-level/nested fields, missing fields, unsupported versions, invalid statuses, nonfinite numbers, missing uncertainty reason, invalid units, invalid hashes, invalid customer scope and engineering approval. All stored computed numbers carry value, unit, uncertainty/reason, method/version, sources and draft/review_required status. Speed stores m/s alongside kn.

### G2 — public result preservation and cross-language round trip

Capture public KVLCC2 hull variation output, mesh hydrostatics, Holtrop baseline, propulsion power and fuel from current source. Preserve all original result fields, warnings and method inputs. Python save/load and Rust save/load must reproduce equivalent JSON values exactly (no tolerance). Python -> Rust -> Python must produce identical canonical JSON bytes. This is a data-preservation gate, not a new accuracy claim. Do not inspect measured resistance or holdout truth.

### G3 — final quick tier and hygiene

Targeted Python/Rust tests and full quick tier must pass. Format and lint pass. Commit and push only `lane/design-record`. Do not merge. Inspect and remove only this worktree's `target` as the last shell step after push.

## Tasks and files

1. Draft `schemas/design-record-v1.schema.json`: closed record objects; reusable quantity, component, file, scope, lineage and decision definitions. Commit plan and schema, run G0 and push.
2. Add failing contract tests in `tests/test_design_record.py`; add `src/vessel_reconstruction/design_record/` with `DesignRecord`, load/save and explicit version rejection. No implicit migration: v1 accepts only 1.0.0; future migration must be a named pure transform, followed by target validation; never discard unknown fields.
3. Add `app/core/src/design_record.rs`, export it from `app/core/src/lib.rs`, add an example JSON round-trip command and Rust tests. Use typed serde structs with deny_unknown_fields; keep named quantity maps intentional.
4. Add public result adapter and fixture builder under this package and `scripts/build_design_record_example.py`. Unit tests compare adapter reconstruction with original outputs, not just with fixture values.
5. Run G1/G2; record exact commands/results here. Run G3, review elegance and diff, commit/push, remove local build output.

## Results

Pending. No gates have run.

## Resume point

Plan and gate definitions are written. Next: draft schema, commit it with this plan, run G0, push first draft. Then implement tasks 2-5 directly under the user's existing authorization.
