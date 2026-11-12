"""Truth-blind product detection on the fixed nine development sheets.

This is input preflight, not a reader comparison or scoring run. Never load
truth files, call a model, invent view regions, or number detected station
columns by order. Per-sheet derived evidence stays in ignored work/.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from vessel_reconstruction import draft_fit, intake, vessel_description, view_measure, view_reader_v2


CASES = (
    ('pardon-me', 'sources/haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif',
     'benchmarks.pardon_me.holdout_value'),
    ('bue-girl', 'sources/haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif',
     'benchmarks.bue_girl.holdout_value'),
    ('thayer', 'sources/haer/ca_thayer/loc_ca1506_sheet_04.tif', 'benchmarks.thayer.holdout_value'),
    ('balclutha', 'sources/balclutha_ca54_s7.tif', 'benchmarks.balclutha.crossing_value'),
    ('bumble-bee', 'sources/haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif',
     'benchmarks.bumble_bee.holdout_value'),
    ('ec-collier', 'dev-truth/ec-collier/md1203-sheet-00002a-lines.tif', 'benchmarks.ec_collier.holdout_value'),
    ('white-gull', 'dev-truth/white-gull/md1939-sheet-00001a-lines.tif', 'benchmarks.white_gull.holdout_value'),
    ('colleen', 'dev-truth/colleen/md1887-sheet-00001a-lines.tif', 'benchmarks.colleen.holdout_value'),
    ('caleb-jones', 'dev-truth/caleb-jones/md1860-sheet-00001a-lines.tif', 'benchmarks.caleb_jones.holdout_value'),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inspect_case(name: str, path: Path, calibration_module: str) -> dict:
    started = time.monotonic()
    record = {'sheet': name, 'path': str(path), 'engineering_approved': False,
              'numbered_station_positions': {},
              'station_number_status': 'unavailable: product code detects lines, not printed station numbers',
              'missing': []}
    if not path.is_file():
        return {**record, 'missing': ['sheet', 'profile region', 'plan region', 'scale', 'station positions']}
    record['sheet_sha256'] = sha256(path)
    calibration = importlib.import_module(calibration_module)
    # Existing drawing calibration is truth-independent, but is supplied, not
    # detected by reference_views. Report this distinction explicitly.
    ppm = calibration.sheet_layout().pixels_per_metre
    record['scale'] = {'pixels_per_metre': ppm, 'source': calibration_module + '.sheet_layout',
                       'detected_by_product_view_path': False}
    grey = view_measure.load_grey(path)
    hints = intake.survey_page(grey)
    record['detected_regions'] = hints
    views = draft_fit.reference_views(grey, hints, ppm)
    record['reference_views'] = views
    for key, description in [('profile', 'profile region'), ('half_breadth_plan', 'plan region')]:
        if key not in views:
            record['missing'].append(description)
    record['missing'].append('station positions with printed identities')
    if 'profile' in views:
        profile = views['profile']
        setup = {'region_px': profile['roi_px'], **profile['calibration']}
        record['unlabelled_station_x_m'] = vessel_description.profile_station_lines(grey, setup, ppm)
    else:
        record['unlabelled_station_x_m'] = []
    reading = view_reader_v2.read_views(grey, views)
    record['view_reader_status'] = reading['status']
    profile = reading.get('profile')
    plan = reading.get('plan')
    record['profile_waterlines'] = profile.waterlines if profile is not None else None
    record['plan_available'] = plan is not None
    # Freeze the extracted vectors even though no numeric station identities
    # are available to sample them. Do not manufacture identities from columns.
    if plan is not None:
        record['plan_vectors'] = {'x_m': plan.x_m.tolist(), 'curves': {
            str(key): {'z_m': curve['z_m'],
                       'y_m': [float(value) if np.isfinite(value) else None for value in curve['y_m']],
                       'status': curve['status']}
            for key, curve in plan.curves.items() if key != 'deck'}}
    record['complete'] = not record['missing']
    record['seconds'] = round(time.monotonic() - started, 2)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    source_paths = [Path(module.__file__) for module in
                    (draft_fit, intake, vessel_description, view_measure, view_reader_v2)]
    sources = {str(path): sha256(path) for path in source_paths}
    cases = []
    for name, relative, module in CASES:
        print(f'{name}: starting code-only input detection', flush=True)
        try:
            record = inspect_case(name, args.work_root / relative, module)
        except Exception as error:
            # Preflight failures are evidence, not permission to guess a region.
            record = {'sheet': name, 'complete': False, 'error': f'{type(error).__name__}: {error}',
                      'missing': ['input extraction failed; see error'], 'engineering_approved': False}
        path = args.out / f'{name}.json'
        path.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
        cases.append({'sheet': name, 'artifact': str(path), 'sha256': sha256(path),
                      'complete': record.get('complete', False), 'missing': record['missing']})
        print(f'{name}: {record["missing"]}', flush=True)
    report = {'commit': commit, 'source_sha256': sources, 'cases': cases,
              'all_inputs_complete': all(case['complete'] for case in cases),
              'scoring_run_started': False, 'truth_loaded': False, 'model_calls': 0,
              'partial_scoring_permitted': False, 'engineering_approved': False}
    (args.out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
