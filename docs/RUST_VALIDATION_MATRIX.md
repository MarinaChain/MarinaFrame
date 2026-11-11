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
| 4d | Unknown schemas; mismatched contract, implementation and tolerance identities | `VU` (schema version, units, tolerance) | `VM::envelope_types_and_contract_identities_are_exact` (schema, audit contract version, both tolerances, units, review flags); audit implementation identity is pinned by the controller: `AI::unchanged_identity_is_pinned_at_initialize_and_finalizes`, `AI::consistent_but_different_audit_identity_cannot_reach_review`, `AI::consistent_different_identity_fails_the_finalization_predicate_itself`, `AI::result_identity_alone_changing_is_refused`, `AI::dropping_the_identity_after_the_pin_is_refused`, `AI::changed_worker_implementation_mid_task_is_refused`, `AI::task_without_a_pin_fails_closed_at_finalization`, `AI::old_state_without_the_field_reads_and_serializes_unchanged` (`AI` = `rust-control/tests/audit_identity.rs`) | `test_validation_contract_schema.py` (3 tests) |
| 4e | Envelope inconsistent with nested evidence | `FG::permissive_envelope_cannot_override_failed_contract` | `VM::failed_geometry_cannot_be_promoted_by_envelope_contract_or_cache_forgery` (envelope, contract, cached evidence and a consistently rewritten audit, all on a real failing run) | `test_cached_metadata_cannot_contradict_authoritative_json_even_if_envelope_passes` |
| 5a | Interrupted audit | none | `VM::interrupted_audit_is_not_cached_and_cannot_finish`, `VM::interrupted_audit_then_a_real_audit_can_still_pass` | `test_interrupted_or_failed_audit_cannot_be_a_cached_pass` |
| 5b | Interrupted provider call | `RL::reliability_unknown_provider_outcome_acknowledgement_survives_restart_without_repeat`, `RR::missing_receipt_stays_unknown_and_requires_explicit_acknowledgement` | not changed | none |
| 5c | Mutation during finalization | `FG::selection_is_excluded_after_the_passing_predicate`, `FG::selection_is_excluded_until_the_review_ready_commit` | not changed | none (Harness tests removed) |
| 5d | Cancellation under lock and before commit | `FG::cancellation_after_passing_predicate_prevents_review_ready_commit` | `VM::cancellation_before_finish_prevents_review_ready` | none |
| 5e | Stale review requests | none | `VM::stale_or_foreign_review_requests_are_refused` (head, generation, revision, task; current request accepted); `VM::real_passing_candidate_...` also shows that a review-ready task fails `Store::verify` after its run changes | none |
| 5f | Incomplete checkpoints | `RR::checkpoint_cache_requires_explicit_committed_prefix_recovery`, `RL::reliability_unreceipted_domain_is_not_adopted_and_late_receipt_reconciles_once`, `RL::reliability_stale_source_blocks_worker_and_checkpoint_recovery_before_mutation`, `ST::explicit_recovery_accepts_only_missing_or_exact_prefix_cache` | checkpoint field changes in `VM::artifact_changes_on_disk_after_validation_are_rejected` | `test_malformed_checkpoint_revision_rejected_on_reload_and_reopen`, `test_validation_finalize_independent.py` |
| 6 | Real geometry-backed failing fixture and real passing fixture | none (every Rust fixture injected the audit) | `VM::control_real_passing_evidence_is_accepted_and_failing_is_not_ready` and every `VM` test: real STEP, real native audit | none |

Rows before: of 18 sub-rows, 7 had a full Rust test (1, 4c, 4e, 5b, 5c, 5d, 5f) and 4 a partial one
(2, 4a, 4b, 4d). After: 17 are fully covered; 3d (stale render) keeps a gap, listed below.
4d (audit implementation identity) is closed by the controller pin (see "Audit identity pin").

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
- The controller check `cancelled_before_finalization` is shadowed by earlier cancellation checks in
  `worker::run` and `apply_worker`. Removing it alone does not fail any test.
- `resume --expected-*` (stale request check in `main.rs`) has no Rust test; `controller::intervene` has one.

## Audit identity pin

- The Python worker adds `audit_implementation_sha256` to every `result`. The controller records the value
  from the `initialize` receipt in `State.audit_implementation_sha256`. The worker does not choose the value
  later: every later receipt must repeat it (`audit_implementation_changed`, `audit_implementation_missing`),
  and `validation::ready` requires the validation contract to carry it (`audit_implementation_mismatch`).
- Old tasks: the field is optional and is not serialized when absent, so old ledger hashes stay valid. A task
  without a pin never receives one later (a later worker value would be the worker's own choice). It cannot
  finalize: `validation::ready` returns `audit_implementation_unpinned`. `Store::verify` of an old task that
  is already awaiting review still passes through `validation::ready_legacy_unpinned`, which applies every
  check except the pin.
- Trust root: the pin comes from the worker environment at `initialize`, not from a controller-computed
  hash. It stops a worker or audit implementation that changes, or reports a different identity, after
  initialization. It does not stop a worker that is wrong from the first receipt. Rust cannot compute the
  hash itself (it includes installed dependency versions). An operator-supplied expected hash is a possible
  extension. The offline `check-validation` command takes an optional `--audit-pin`; without it, it checks
  everything except the pin and reports `audit_implementation_pinned: false`.

## Draft guards (best-effort drafts, 2026-11-07)

With `on_ambiguity = draft` (app default, see the head-to-head section of `BENCHMARK_FACTORY.md`; CLI `--on-ambiguity draft`), an ambiguous or unreadable
section gives a draft instead of an abstention. Each choice is an open guess in `domain/state.json`
`guesses` (`src/vessel_reconstruction/draft.py`). Rust enforces, independently of Python:

| Check | Where | Error code |
|---|---|---|
| Finish with open guesses stops at `draft_not_verified`, no validation call | `controller::execute_decision` | `open_guesses_block_review` |
| Open guesses, a draft candidate or a draft run record are never review-ready (finish and `Store::verify`) | `validation::ready`, `ready_legacy_unpinned` (`refuse_draft`, first check) | `draft_guesses_open`, `draft_candidate_not_verifiable`, `draft_build_not_verifiable` |
| Every guess is typed and agrees with the inspected catalog; the description lists exactly the checkpoint guesses | `store::verify_domain_identity` (every receipt and `Store::verify`) | `draft_guess_contract`, `draft_guess_not_in_catalog`, `draft_guess_description_mismatch` |
| Open guesses are part of the generation id | `store::verify_domain_identity` | `domain_identity_or_review_boundary` |
| Only an operator resolves a guess | `controller::validate_selection` | `guess_requires_operator_confirmation` |
| A draft task is terminal for `resume` | `controller::resume` | `terminal_task_requires_explicit_source_backed_intervention` |

Tests: `DG` = `rust-control/tests/draft_guards.rs` (8 real-CAD tests: deterministic draft and abstain
control, finish repeated and after restart, permissive envelope, forged review status, edited and
removed guesses, worker-forged guess, policy confirmation, operator resolution then the normal path
to `awaiting_human_review`) and unit tests in `validation.rs`, `controller.rs`, `types.rs`.
Mutation check (2026-11-07): removing each row's check (9 mutations, including the generation
binding and the draft stop) fails at least one `DG` test.

## Region runs (multi-piece stations, 2026-11-07)

A region run (`metrics.region_loft`) must carry the `step_source_regions_v2` audit; Rust checks it
independently of Python (`validation::assess`, `region_cad_pass`, `check_piece_reports`):

| Check | Error code |
|---|---|
| Contract version and context `regions` agree with the run record (v2 only for a region run) | `audit_contract_version_not_current_run` |
| Context `regions` equals the run's solid count, sorted solid volumes and sampled piece counts | `context_regions_not_current_run` |
| Expected solid count equals the run's `metrics.solid_count` | `audit_expected_solids_not_current_run` |
| Per-solid audit complete, sorted, summary consistent; volume error recomputed | `solid_audit_incomplete`, `solid_audit_order_or_summary`, `solid_volume_error_contradiction` |
| Per-piece reports: index, sample count, maxima agree with the section | `piece_reports_incomplete`, `piece_report_identity`, `piece_maxima_contradiction` |

Tests: `rust-control/tests/region_pipeline.rs` (4 real-CAD tests: a deterministic run of
`tests/region_fixture.py` reaches `awaiting_human_review` through v2; a removed context `regions`, a
changed solid volume and a v1 claim are refused).
