"""Explicit capability requirements for tests of unavailable OS security primitives."""
import os

import pytest

from vessel_reconstruction.platform_files import SECURE_READS_UNSUPPORTED

# Each entry names a test that exercises descriptor-relative no-follow opens.
# Ordinary tests and unsupported-platform refusal regressions must still run.
SECURE_READ_TESTS = {
    'test_reexport.py': {
        'test_refresh_preserves_every_original_file',
        'test_failure_leaves_original_bytes',
        'test_controller_lock_is_held_on_both_sides_of_exchange',
        'test_busy_and_symlink_runs_are_refused',
    },
    'test_reexport_failures.py': {
        'test_failed_rollback_preserves_original_snapshot',
        'test_cleanup_failure_does_not_leak_lock',
    },
    'test_reexport_formats.py': {'test_requested_conversion_uses_step_without_changing_build'},
    'test_reexport_manifest.py': {'test_manifest_hashes_match_after_repeated_refresh'},
    'test_reexport_options.py': {
        'test_cli_refresh_and_missing_revision',
        'test_post_publication_lock_failure_rolls_back',
        'test_existing_user_choices_and_identity_survive',
        'test_protected_geometry_tampering_is_refused',
        'test_unfinished_or_pending_is_refused',
    },
    'test_worker_progress.py': {
        'test_untrusted_progress_files_do_not_block_or_follow_links',
        'test_relay_rejects_invalid_display_fields',
        'test_child_counter_alone_cannot_advance_trusted_progress',
        'test_relay_advance_budget_is_per_step_and_cannot_be_reset_by_the_child',
    },
    'test_ship_cad.py': {
        'test_worker_result_reader_refuses_symlinks',
        'test_worker_result_reader_refuses_a_fifo_without_blocking',
    },
    'test_linux_sandbox.py': {'test_linux_setup_failure_is_not_a_successful_empty_result'},
}


# These tests execute the POSIX supervisor, not only ordinary CAD functions.
# Windows needs a job-object/resource-limit implementation before they can run.
POSIX_LIFECYCLE_TESTS = {
    'test_iges_exports.py': {'test_structure_block_writes_iges_beside_step'},
    'test_rhino_exports.py': {'test_structure_block_3dm_names_follow_member_ids'},
    'test_parallel_parts.py': {
        'test_parts_use_processes_in_input_order',
        'test_parts_respect_occupied_pool',
        'test_parts_serial_and_parallel_errors_match',
        'test_synthetic_vessel_exports_are_identical',
        'test_ship_components_and_failure_reports_match',
        'test_internal_and_steel_builds_match',
    },
    'test_runtime.py': {
        'test_sandbox_stall_kills_child_process_group',
        'test_cancel_kills_worker_and_descendant',
        'test_exited_parent_does_not_leave_descendant',
        'test_restart_cleanup_can_identify_orphan_group',
        'test_reused_pid_identity_is_never_signalled',
        'test_actual_cpu_address_space_and_file_limits',
        'test_quick_exit_still_checks_aggregate_output_budget',
        'test_deterministic_default_has_no_cpu_limit_and_reports_progress',
        'test_cpu_limit_stop_names_limit_and_progress',
    },
    'test_worker_progress.py': {
        'test_nested_worker_defers_time_limit_to_controller',
        'test_standalone_stall_policy_uses_trust_not_child_heartbeat',
        'test_security_cap_stops_a_live_child_without_process_inspection',
    },
}


# End-to-end inspection tests require the same isolated parser/native worker.
# Pure algorithms in these modules still run; only named integration tests need it.
ISOLATED_INSPECTION_TESTS = {
    'test_agent_tools.py': {
        'test_inspection_is_source_bound_and_grid_proposal_keeps_alternatives',
        'test_faint_real_alternative_is_retained_and_can_be_selected',
        'test_grid_only_is_not_a_supported_hull_hypothesis',
        'test_fractional_calibration_corridor_spans_actual_trace_rows',
        'test_source_snapshot_resume_and_tamper_fail_closed',
        'test_actual_provisional_build_step_views_and_source_cut_validation',
    },
    'test_draft.py': {
        'test_deterministic_guesses_on_an_ambiguous_drawing',
        'test_draft_build_records_guesses_and_tags_exports',
    },
    'test_investigation.py': {
        'test_view_is_bounded_and_records_its_mapping',
        'test_trace_is_snapped_to_ink_and_refused_without_ink',
        'test_a_clicked_point_is_followed_along_its_own_stroke',
        'test_enumerated_strokes_are_tagged_shared_by_the_panel_and_never_best_guesses',
        'test_enumeration_keeps_new_tags_assignable_after_many_calls',
        'test_tracing_has_no_aggregate_candidate_cap',
        'test_a_short_fragment_or_unknown_view_is_refused',
        'test_assignment_is_an_open_model_choice_and_ink_is_used_once',
        'test_a_draft_keeps_model_choices_and_is_well_formed',
        'test_sheet_setup_is_checked_against_grid_datum_and_declared_calibration',
    },
    'test_mirrored_half.py': {'test_aft_stations_take_their_own_left_curves_not_the_bulb'},
    'test_panel_assignment.py': {'test_nested_drawing_gets_one_stroke_per_station'},
    'test_parallel_inspection.py': {
        'test_the_controller_count_wins_over_the_environment',
        'test_parallel_inspection_matches_one_worker',
        'test_a_run_takes_only_the_free_workers_of_the_pool',
    },
    'test_region_pipeline.py': {
        'test_region_candidate_passes_the_independent_v2_audit',
        'test_draft_mode_spans_an_unreadable_multi_piece_station',
    },
    'test_replace_sheet.py': {'test_real_replacement_reads_builds_and_keeps_a_draft'},
    'test_section_authoring.py': {
        'test_propose_section_makes_an_open_ai_inferred_guess_with_an_overlay',
        'test_propose_section_that_replaces_a_trace_is_ai_corrected',
        'test_draft_with_an_ai_inferred_section_builds_labelled_cad',
        'test_person_can_confirm_ai_authored_section_and_keep_its_source_label',
    },
    'test_station_overlay.py': {'test_draft_render_has_station_overlay_and_scoreboard'},
    'test_stroke_discovery.py': {'test_enumeration_tags_carry_coverage_and_rank'},
    'test_whole_vessel_step1.py': {'test_arm_b_code_sees_no_credentials'},
    'test_worker_pool.py': {'test_an_inspection_runs_when_the_pool_folder_is_unsafe'},
}


ATOMIC_PACKAGE_EXCHANGE_TESTS = {
    'test_exports.py': {
        'test_package_replaces_existing_directory_after_complete_write',
        'test_report_without_a_viewer_capture_has_no_picture_on_page_one',
        'test_report_puts_the_viewer_capture_on_page_one',
        'test_a_capture_that_is_not_an_image_leaves_the_report_complete',
        'test_the_capture_is_not_listed_in_the_package',
    },
    'test_package_spatial.py': {'test_reexport_removes_a_previously_packaged_stale_task_model'},
}


def pytest_collection_modifyitems(items):
    if os.name != 'nt':
        return
    for item in items:
        name = item.name.split('[', 1)[0]
        if name in ATOMIC_PACKAGE_EXCHANGE_TESTS.get(item.path.name, set()):
            item.add_marker(pytest.mark.skip(
                reason='Atomic replacement of an existing package is not supported on this platform.'))
        if name in SECURE_READ_TESTS.get(item.path.name, set()):
            item.add_marker(pytest.mark.skip(reason=SECURE_READS_UNSUPPORTED))
        if (name in POSIX_LIFECYCLE_TESTS.get(item.path.name, set())
                or name in ISOLATED_INSPECTION_TESTS.get(item.path.name, set())):
            item.add_marker(pytest.mark.skip(
                reason='Secure worker process lifecycle is not supported on this platform.'))
