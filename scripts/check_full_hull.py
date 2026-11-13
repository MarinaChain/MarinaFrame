"""Public full-hull gate. Source data and generated geometry stay in work/."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from vessel_reconstruction.full_hull_source import sample_full_iges
from vessel_reconstruction.hull_variation import build_candidate

# Fixed before comparison: SIMMAN 2020 full-scale bare hull table.
SOURCE = 'https://simman2020.kr/contents/Ship_data_summary.php'
REFERENCE = dict(waterline_length_m=325.5, volume_m3=312622., wetted_surface_m2=27194.)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iges', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    hull, report = sample_full_iges(args.iges, face_indices=[0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
        source_aft_x_m=5.5016, source_fore_x_m=-328.085,
        parallel_source_x_m=(-220., -120.), draft_m=20.8, depth_m=28.)
    parent = {k: v.tolist() if hasattr(v, 'tolist') else v for k, v in asdict(hull).items()}
    (args.out / 'parent.json').write_text(json.dumps(parent))
    (args.out / 'source-report.json').write_text(json.dumps(report, indent=2))
    try:
        candidate = build_candidate(hull)
    except ValueError as error:
        failure = dict(status='draft', engineering_approved=False, passed=False,
                       source=SOURCE, stage='source region CAD build', reason=str(error),
                       source_report=report, checks_not_run=['Lwl', 'volume', 'wetted surface', 'LCB'])
        (args.out / 'gate.json').write_text(json.dumps(failure, indent=2))
        raise
    hydro = candidate.report['hydrostatics']
    checks = {k: dict(reference=value, measured=hydro[k], relative_error=abs(hydro[k] / value - 1),
                      passed=abs(hydro[k] / value - 1) <= .005) for k, value in REFERENCE.items()}
    # SIMMAN gives 3.48% forward but does not state its datum on this page.
    # Do not silently assume midships or compare against a retained end cap.
    checks['lcb'] = dict(passed=False, reason='Published page does not state LCB reference datum; needs source confirmation.',
                         published_percent_forward=3.48, tolerance_m=.005 * 320,
                         measured_from_local_aft_m=hydro['lcb_m'])
    result = dict(source=SOURCE, source_report=report, checks=checks, candidate=candidate.report,
                  passed=all(c['passed'] for c in checks.values()))
    (args.out / 'gate.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(checks, indent=2), flush=True)
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
