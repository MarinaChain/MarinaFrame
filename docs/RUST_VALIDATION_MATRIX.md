# Rust validation and finalization matrix

Rust owns finalization (`validation::ready`, `controller::execute_decision`). The Python legacy
Harness is being removed, so each row below must be guarded by a Rust test.
The matrix comes from section 4 of the project brief (private, not in this repository).

Test files:

- `FG` = `rust-control/tests/finalization_guards.rs` (injected audit result, real worker protocol).
- `VM` = `rust-control/tests/validation_matrix.rs` (this work; real geometry, no injected audit).
- `VU` = unit tests in `rust-control/src/validation.rs`; `RR` = `independent_receipt_review.rs`;
  `RL` = `independent_reliability.rs`; `ST` = unit tests in `rust-control/src/store.rs` / `util.rs`.
- `PY` = Python tests of the Python side only (`tests/test_validation_*.py`).

## Coverage table

"Before" is the state at commit 19afbeb. "After" adds `VM`.

| # | Matrix row | Rust before | Rust after (new in `VM`) | Python only |
|---|---|---|---|---|
| 1 | First failed audit, repeated cached failure, finish; repeat after restart | `FG::failed_audit_stays_failed_when_cached_and_finished`, `FG::restart_finalization_does_not_promote_failed_cache` (injected audit) | `VM::real_failing_geometry_stays_failed_cached_and_after_restart` (real audit, restart, `resume` refused) | `test_complete_failed_audit_stays_failed_when_cached`, `test_restart_retains_cached_pass_or_failure_without_a_new_audit` |
| 2 | Fresh and cached valid equivalence; failure equivalence; no redundant audit only while the evidence is valid | failure case only: audit count 1 in the two `FG` tests above | `VM::real_passing_candidate_reaches_review_on_valid_cached_evidence_without_a_new_audit` (cached evidence equals fresh, 0 new audits), the failing test above (failure equivalence, 0 new audits), `VM::interrupted_audit_then_a_real_audit_can_still_pass` | `test_fresh_and_cached_pass_have_identical_authoritative_semantics`; "no re-audit when evidence changed": `test_cached_conclusions_cannot_outlive_bound_artifacts` (audit_calls == 1) |
| 3a | Stale generation or revision | `VU` none (contract shape only) | `VM::stale_generation_revision_and_binding_mismatches_are_rejected` (29 cases) | `test_prior_current_candidate_cannot_satisfy_a_different_binding` |
| 3b | A, B, A selection | none | `VM::selection_a_b_a_makes_the_old_validation_stale` (real selections; old evidence stale; finish blocked) | `test_reselecting_an_old_generation_requires_a_new_revision_build` |
| 3c | Calibration, input, source, STEP changes | none | `VM::artifact_changes_on_disk_after_validation_are_rejected` (24 mutations: STEP, run result, manifest, extra or linked file, input spec calibration, captured source, revision spec and selection, checkpoint fields) | `test_persistent_domain_changes_invalidate_old_audit`, `test_cached_conclusions_cannot_outlive_bound_artifacts` |
| 3d | Missing, changed or stale raw audit and render artifacts | none (stale render: see gaps) | same test: raw audit, worker receipt and comparison image changed or missing; `VM::section_comparison_images_must_follow_the_sampling_order` | `test_cached_conclusions_cannot_outlive_bound_artifacts`, `test_render_marks_same_generation_older_revision_stale` |
| 4a | Exact Boolean and numeric types | `VU::incomplete_unknown_boolean_and_contradictory_contracts_fail` (contract only) | `VM::envelope_types_and_contract_identities_are_exact` (39), `VM::consistently_forged_audit_content_is_rejected_by_type_and_semantics` (43), `VM::audit_receipt_and_resource_contract_is_exact` (9) | `test_native_check_requires_exact_boolean`, `test_authoritative_artifact_cannot_use_numeric_boolean_equivalents` |
| 4b | Null and missing fields | `VU` (missing contract keys) | the three tests above (null, missing and unknown fields at every level) | `test_missing_contract_fields_are_not_inherited_from_cache`, `test_native_contradictory_or_incomplete_audit_is_rejected` |
| 4c | Nonfinite data | `ST::duplicate_nonfinite_and_nested_duplicates_rejected`, `ST::finite_float_event_bytes_survive_disk_parse_roundtrip` | no new test: JSON cannot hold NaN or Infinity, and `util::parse` already rejects the tokens; null, string and negative values are in the tables above | `test_strict_contract_rejects_invalid_serialization_or_semantics` |
| 4d | Unknown schemas; mismatched contract, implementation and tolerance identities | `VU` (schema version, units, tolerance) | `VM::envelope_types_and_contract_identities_are_exact` (schema, audit contract version, both tolerances, units, review flags); audit implementation identity: see gaps | `test_validation_contract_schema.py` (3 tests) |
| 4e | Envelope inconsistent with nested evidence | `FG::permissive_envelope_cannot_override_failed_contract` | `VM::failed_geometry_cannot_be_promoted_by_envelope_contract_or_cache_forgery` (envelope, contract, cached evidence and a consistently rewritten audit, all on a real failing run) | `test_cached_metadata_cannot_contradict_authoritative_json_even_if_envelope_passes` |
| 5a | Interrupted audit | none | `VM::interrupted_audit_is_not_cached_and_cannot_finish`, `VM::interrupted_audit_then_a_real_audit_can_still_pass` | `test_interrupted_or_failed_audit_cannot_be_a_cached_pass` |
| 5b | Interrupted provider call | `RL::reliability_unknown_provider_outcome_acknowledgement_survives_restart_without_repeat`, `RR::missing_receipt_stays_unknown_and_requires_explicit_acknowledgement` | not changed | none |
| 5c | Mutation during finalization | `FG::selection_is_excluded_after_the_passing_predicate`, `FG::selection_is_excluded_until_the_review_ready_commit` | not changed | none (Harness tests removed) |
| 5d | Cancellation under lock and before commit | `FG::cancellation_after_passing_predicate_prevents_review_ready_commit` | `VM::cancellation_before_finish_prevents_review_ready` | none |
| 5e | Stale review requests | none | `VM::stale_or_foreign_review_requests_are_refused` (head, generation, revision, task; current request accepted); `VM::real_passing_candidate_...` also shows that a review-ready task fails `Store::verify` after its run changes | none |
| 5f | Incomplete checkpoints | `RR::checkpoint_cache_requires_explicit_committed_prefix_recovery`, `RL::reliability_unreceipted_domain_is_not_adopted_and_late_receipt_reconciles_once`, `RL::reliability_stale_source_blocks_worker_and_checkpoint_recovery_before_mutation`, `ST::explicit_recovery_accepts_only_missing_or_exact_prefix_cache` | checkpoint field changes in `VM::artifact_changes_on_disk_after_validation_are_rejected` | `test_malformed_checkpoint_revision_rejected_on_reload_and_reopen`, `test_validation_finalize_independent.py` |
| 6 | Real geometry-backed failing fixture and real passing fixture | none (every Rust fixture injected the audit) | `VM::control_real_passing_evidence_is_accepted_and_failing_is_not_ready` and every `VM` test: real STEP, real native audit | none |

Rows before: of 18 sub-rows, 7 had a full Rust test (1, 4c, 4e, 5b, 5c, 5d, 5f) and 4 a partial one
(2, 4a, 4b, 4d). After: 16 are fully covered; 3d (stale render) and 4d (audit implementation identity)
keep a gap, listed below.

## Fixtures

- Passing: the pixel fixture of `tests/test_agent_tools.py`; real build, real audit, 0.9 mm against a 1.1 mm limit.
- Failing: a curved hull built while the engine's CAD approximation bound is raised from 1 mm to 10 mm
  (`tests/rust_matrix_sitecustomize/`, used only by the build subprocess when `matrix-mode.json` asks for it).
  The exported STEP really deviates by 8.5 mm. The audit, the run record and the controller are not changed.
  The engine's own 1 mm bound makes an honest failing build impossible, so a loosened engine is the only
  real-geometry failure available.
- `tests/rust_matrix_worker.py` is the worker shim. It injects nothing by default. Optional modes:
  `audit_outcome` (an interrupted audit), `alternative_candidate` (a second contour for A, B, A),
  `loose_cad_bound`.
- Most tests call `validation::ready` directly on a private copy of a validated task, change one
  thing, and require a specific error code. Forging helpers rewrite the raw audit, the worker receipt,
  the cached observation and all hashes consistently, so only the semantic content differs.
- Tests in `VM` run one at a time. The controller locks `domain/lock` twice in a row; a process spawned
  by another test thread in between holds the old lock for a moment and fails the second lock. A single
  controller process cannot do that.

## Remaining gaps

- Stale render observations: `controller::apply_worker` checks `render_candidate_mismatch` and
  `render_step_identity`. No Rust test renders. Only `test_render_marks_same_generation_older_revision_stale`
  covers it (Python).
- `audit_implementation_sha256` is checked for format and for equality with the context that the worker
  returns. Rust has no independent source for the audit implementation hash, so a worker that reports a
  different, well-formed value consistently is accepted. Closing this needs a pinned value from the
  controller, which is a design change and is not made here.
- The controller check `cancelled_before_finalization` is shadowed by earlier cancellation checks in
  `worker::run` and `apply_worker`. Removing it alone does not fail any test.
- `resume --expected-*` (stale request check in `main.rs`) has no Rust test; `controller::intervene` has one.
