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

### G4 — packaging fixture regression and final rerun

Before checking: the temporary wheel-test project must include every newly declared schema data file. Its wheel must retain the existing tool catalog and contain the exact canonical design-record schema. Run the focused wheel test, then the unchanged full quick tier. Both must exit zero before any push.

## Results

- First draft committed as `49e6c69` before G0. G0 (`work/g0-quick.log`) passed Rust but was interrupted during Python after a failure marker. It overlapped implementation; the failure cause was not captured before interruption, so it is not a clean baseline result. Stopped this redundant run to avoid competing with G3. No push yet because quick tier is mandatory before every push. The first-draft early-push goal is delayed by this mandatory gate.
- TDD red: `test_design_record_api_exists` failed because the package was absent. Early Rust test attempt failed because the generated public fixture was not yet available; rerun after fixture generation passed.
- G1/G2 first focused run: 11 Python tests passed; Rust shared corpus (21 invalid records) passed; Python -> Rust -> Python produced identical canonical JSON, 138445 bytes. Expanded checks add schema-vocabulary drift protection and save-time mutation validation (3 Rust tests passed). Final rerun pending after per-method provenance refinement.
- Public IGES fixture generation initially failed because water properties were not supplied to Holtrop. Corrected with explicit 1025 kg/m3 and 1.19e-6 m2/s; generation then passed. No thresholds changed.
- `cargo clippy --locked -p marinaframe-app-core --lib -- -D warnings` passed.
- Elegance review: retained explicit extension maps; added installed-schema data file, save-time revalidation, per-method evidence provenance, and a schema-vocabulary drift test. No cross-lane import.
- Architecture refresh attempted in this worktree. Scanner completed, but helper failed with `ModuleNotFoundError: render_bootstrap`. Removed incomplete generated `.codesight` output. No source files were changed by the helper. This is machine tooling follow-up, not a contract blocker.

## Resume point

Implementation and focused checks are complete. G0 is interrupted (see results); G3 (`work/final-quick.log`) is running. Latest focused run passed: 13 Python tests, 3 Rust tests, exact canonical bridge 134622 bytes. Wheel build passed and contains the Python package plus the canonical schema data file. Do not push until a full quick tier passes. Latest generated fixture includes per-method provenance and explicit water inputs; rerun focused output is in the background task log. Next: read completed quick logs, fix real failures without weakening gates, record exact totals, push schema commit first then implementation commit on `lane/design-record`, and remove only this worktree's `target` after all builds stop. No merge.

Public example values: candidate Cb 0.9144898202304488; retained volume 284881.8334721441 m3; separate full-vessel baseline resistance 1654064.986120052 N; brake power 16948.359713548485 kW; fuel 69.14930763127782 t/day. These are preserved draft calculations, not new accuracy evidence.

Final focused expectation: 13 Python tests and 3 Rust tests, 21 shared invalid mutations, and exact canonical bridge. Full quick totals remain pending. Full hull reconstruction, stability/strength calculations, scope authorization service and mapping other lanes' fragments are outside this lane.
