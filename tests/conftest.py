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


def pytest_collection_modifyitems(items):
    if os.name != 'nt':
        return
    for item in items:
        name = item.name.split('[', 1)[0]
        if name in SECURE_READ_TESTS.get(item.path.name, set()):
            item.add_marker(pytest.mark.skip(reason=SECURE_READS_UNSUPPORTED))
        if name in POSIX_LIFECYCLE_TESTS.get(item.path.name, set()):
            item.add_marker(pytest.mark.skip(
                reason='Secure worker process lifecycle is not supported on this platform.'))
