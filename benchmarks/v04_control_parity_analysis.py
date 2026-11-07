"""Read-only parity eligibility and measured totals; no engine or native imports."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def close_metrics(left, right):
    """Far below the millimetre geometry tolerance; raw differences are retained."""
    expected = {'length_m', 'beam_m', 'depth_m', 'volume_m3'}
    if not isinstance(left, dict) or not isinstance(right, dict) or left.keys() != expected or right.keys() != expected:
        return False, {}
    if any(type(value) not in (float, int) or not math.isfinite(value) or value <= 0
           for metrics in (left, right) for value in metrics.values()):
        return False, {}
    differences = {key: right[key] - left[key] for key in left}
    return all(math.isclose(left[k], right[k], rel_tol=1e-12, abs_tol=1e-9)
               for k in left), differences


def equal_digest(left, right):
    return (type(left) is str and type(right) is str
            and re.fullmatch('[0-9a-f]{64}', left) is not None
            and re.fullmatch('[0-9a-f]{64}', right) is not None and left == right)


def measured(row, evidence_root=None):
    result = row['result']
    stages = result.get('stages', [])
    native = result.get('native_observation_profiles', [])
    builds = [s['resources'] for s in stages
              if s['operation'] == 'build_provisional' and s.get('resources')]
    receipts = native + builds
    bridge = result.get('bridge_profiles', [])
    queue = sum((s.get('supervision') or {}).get('queue_wait_seconds', 0) for s in stages)
    python_metrics = ((Path(evidence_root) / 'runs' / row['case'] / str(row['repetition']) / row['arm'] / 'python-metrics.json')
                      if evidence_root is not None else Path(row['task']).parent / 'python-metrics.json')
    if row['arm'] == 'python' and python_metrics.exists():
        queue = read(python_metrics)['queue_wait_seconds']
    return {
        'case': row['case'], 'repetition': row['repetition'], 'arm': row['arm'],
        'status': result.get('status'), 'exit_code': row['timing']['exit_code'],
        'wall_seconds': row['timing']['wall_seconds'],
        'whole_command_cpu_seconds_wait4': row['timing']['whole_command_cpu_seconds_wait4'],
        'controller_sampled_self_peak_rss_kib': row['timing']['controller_sampled_self_peak_rss_kib'],
        'largest_reported_native_process_peak_rss_kib': max((p.get('peak_rss_kib', 0) for p in receipts), default=0),
        'largest_reported_bridge_process_peak_rss_kib': max((p.get('worker_peak_rss_kib', 0) for p in bridge), default=0),
        'native_receipt_wall_sum_seconds': sum(p.get('wall_seconds', 0) for p in receipts),
        'native_receipt_cpu_sum_seconds': sum(p.get('cpu_seconds', 0) for p in receipts),
        'queue_wait_seconds': queue,
        'operation_counts': dict(Counter(s['operation'] for s in stages)),
        'decision_count': result.get('decision_count'),
        'native_build_count': result.get('native_build_count'),
        'native_inspection_count': sum(p['stage'] == 'inspections' for p in native),
        'native_render_count': sum(p['stage'] == 'renders' for p in native),
        'native_audit_count': sum(p['stage'] == 'validation' for p in native),
        'cache_validation_hits': sum(s['operation'] == 'validate_candidate' and s.get('cached') is True for s in stages),
        'verification_valid': result.get('verification', {}).get('valid') is True,
    }


def compare(python, rust):
    p, r = python['result'], rust['result']
    pg, rg = p.get('geometry') or {}, r.get('geometry') or {}
    pa, ra = pg.get('actual_step_audit') or {}, rg.get('actual_step_audit') or {}
    metrics_equal, differences = close_metrics(pa.get('metrics'), ra.get('metrics'))
    checks = {
        'both_commands_exited_zero': all(type(row['timing']['exit_code']) is int and row['timing']['exit_code'] == 0 for row in (python, rust)),
        'both_integrity_verifiers_passed': p.get('verification', {}).get('valid') is True and r.get('verification', {}).get('valid') is True,
        'both_ready_only_for_review': p.get('status') == r.get('status') == 'awaiting_human_review',
        'nonempty_logical_decisions_and_arguments_equal': type(p.get('decisions')) is list and bool(p['decisions']) and p['decisions'] == r.get('decisions'),
        'nonempty_selected_candidate_ids_equal': type(p.get('selection')) is dict and bool(p['selection']) and p['selection'] == r.get('selection'),
        'both_built_one_candidate': all(type(result.get('native_build_count')) is int and result['native_build_count'] == 1 for result in (p, r)),
        'cad_section_bytes_equal': equal_digest(pg.get('cad_sections_sha256'), rg.get('cad_sections_sha256')),
        'mesh_bytes_equal': equal_digest(pg.get('mesh_sha256'), rg.get('mesh_sha256')),
        'both_geometry_audits_passed': pg.get('geometry_checks_passed') is True and rg.get('geometry_checks_passed') is True,
        'both_step_reimports_closed_single_solids': all(a.get('source') == 'independently_reimported_exported_STEP' and a.get('valid_shape') is True and a.get('closed_shell') is True and type(a.get('solid_count')) is int and a['solid_count'] == 1 for a in (pa, ra)),
        'independently_reimported_step_metrics_equal_within_tolerance': metrics_equal,
        'same_sampled_sections': bool(pg.get('sampled_sections')) and [x['section_id'] for x in pg.get('sampled_sections') or []] == [x['section_id'] for x in rg.get('sampled_sections') or []],
    }
    eligible = all(checks.values())
    return {
        'case': python['case'], 'repetition': python['repetition'],
        'eligible_for_successful_workload_timing_ratio': eligible,
        'eligibility_checks': checks, 'exclusion_reasons': [k for k, v in checks.items() if not v],
        'step_audit_metric_rust_minus_python': differences,
        'exported_step_bytes_equal': equal_digest(pg.get('step_sha256'), rg.get('step_sha256')),
        'python_step_sample_max_m': max((x['max_m'] for x in pg.get('sampled_sections') or []), default=None),
        'rust_step_sample_max_m': max((x['max_m'] for x in rg.get('sampled_sections') or []), default=None),
        'wall_rust_over_python': rust['timing']['wall_seconds'] / python['timing']['wall_seconds'] if eligible else None,
        'cpu_rust_over_python': rust['timing']['whole_command_cpu_seconds_wait4'] / python['timing']['whole_command_cpu_seconds_wait4'] if eligible else None,
        'python_status': p.get('status'), 'rust_status': r.get('status'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    rows = read(args.directory / 'results.json')
    grouped = {}
    for row in rows:
        key = row['case'], row['repetition']
        if row['arm'] in grouped.setdefault(key, {}):
            raise ValueError('Duplicate case/repetition/arm')
        grouped[key][row['arm']] = row
    pairs = [compare(pair['python'], pair['rust']) for pair in grouped.values() if set(pair) == {'python', 'rust'}]
    missing = [{'case': key[0], 'repetition': key[1], 'present_arms': sorted(pair)}
               for key, pair in grouped.items() if set(pair) != {'python', 'rust'}]
    metrics = [measured(row, args.directory) for row in rows]
    summary = {
        'schema_version': 'marinaframe.control-parity-analysis.v1',
        'analysis_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'main_results_sha256': hashlib.sha256((args.directory / 'results.json').read_bytes()).hexdigest(),
        'actual_trial_count': len(rows), 'paired_trial_count': len(pairs), 'missing_pairs': missing,
        'eligible_successful_pairs': sum(p['eligible_for_successful_workload_timing_ratio'] for p in pairs),
        'pairs': pairs, 'measurements': metrics,
        'native_build_count': sum(x.get('native_build_count') or 0 for x in metrics),
        'native_audit_count': sum(x['native_audit_count'] for x in metrics),
        'native_render_count': sum(x['native_render_count'] for x in metrics),
        'provider_calls': 0,
        'limits': [
            'Two fresh processes/tasks per arm per case; OS/file caches were not flushed.',
            'Sampled controller VmHWM is an observed lower bound. Per-process peaks are not a simultaneous tree peak and are never summed.',
            'wait4 CPU includes accounted waited descendants; do not add overlapping bridge/native CPU receipts.',
            'Rust has additional bridge startup, supervision, strict event/receipt verification and supplemental section-image work.',
            'No ratio is published for incomplete, refused, failed, unverified or unequal-work pairs.',
            'No expert vessel truth or hidden reference was accessed. STEP audit agreement concerns supplied geometry only.',
        ],
    }
    destination = args.directory / 'analysis.json'
    destination.write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'analysis': str(destination), 'trials': len(rows), 'eligible_pairs': summary['eligible_successful_pairs'], 'missing_pairs': len(missing)}))


if __name__ == '__main__':
    main()
