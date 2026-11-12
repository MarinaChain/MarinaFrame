"""Public KVLCC2 draft comparison and candidates; generated files stay in work/."""
import argparse
import json
from pathlib import Path

import numpy as np

from vessel_reconstruction.hull_variation import HullSections, build_candidate, section_properties, vary_sections

# SIMMAN 2020 full-scale KVLCC2 table, bare hull wetted area (without rudder).
PUBLIC_SOURCE = 'https://simman2020.kr/contents/Ship_data_summary.php'
PUBLISHED = dict(length_m=320.0, breadth_m=58.0, draft_m=20.8,
                 volume_m3=312622.0, cb=0.8098, wetted_surface_m2=27194.0)


def compare_particulars(sampled: dict) -> dict:
    values = dict(sampled)
    # Keep the published Lpp/B/T basis when reporting lost reference volume.
    values['cb'] = values['volume_m3'] / (320 * 58 * 20.8)
    return {key: dict(published=value, sampled=values[key], difference=values[key] - value,
                      difference_percent=100 * (values[key] / value - 1))
            for key, value in PUBLISHED.items()}


def load_sections(path: Path) -> HullSections:
    with np.load(path) as data:
        return HullSections(data['x'], data['z'], data['y'], float(data['L']), float(data['B']),
                            float(data['T']), tuple(data['parallel']))


def image(hull: HullSections, path: Path, title: str):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(12, 5), facecolor='#fcfcfb')
    ax = fig.add_subplot(projection='3d')
    x, z = np.meshgrid(hull.x_m, hull.z_m, indexing='ij')
    for sign in (1, -1):
        ax.plot_surface(x, sign * hull.half_breadths_m, z, color='#2a78d6',
                        linewidth=0, antialiased=True, alpha=0.9)
    ax.set(xlabel='x from retained aft end (m)', ylabel='y (m)', zlabel='height (m)', title=title + ' — draft')
    ax.set_box_aspect((hull.length_m, hull.breadth_m, hull.z_m[-1]))
    ax.view_init(elev=22, azim=-65)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run(sections: Path, out: Path, candidates: bool = False) -> dict:
    import cadquery as cq
    hull = load_sections(sections)
    out.mkdir(parents=True, exist_ok=True)
    if candidates:
        baseline_path = out / 'baseline.json'
        if not baseline_path.exists():
            raise ValueError('Run and inspect the baseline comparison before candidates.')
        baseline = json.loads(baseline_path.read_text())
        if baseline['input_sha256'] != __import__('hashlib').sha256(sections.read_bytes()).hexdigest():
            raise ValueError('Baseline sections changed; run the baseline again.')
    else:
        built = build_candidate(hull)
        hydro = built.report['hydrostatics']
        report = dict(status='draft', engineering_approved=False, source=PUBLIC_SOURCE,
                      input_sha256=__import__('hashlib').sha256(sections.read_bytes()).hexdigest(),
                      comparison=compare_particulars(dict(length_m=hull.length_m, breadth_m=hull.breadth_m,
                          draft_m=hull.draft_m, volume_m3=hydro['volume_m3'],
                          wetted_surface_m2=hydro['wetted_surface_m2'])), candidate=built.report)
        (out / 'baseline.json').write_text(json.dumps(report, indent=2))
        cq.exporters.export(built.solid, str(out / 'baseline.step'))
        image(hull, out / 'baseline.png', 'KVLCC2 supported reference')
        return report
    cb, lcb = section_properties(hull)
    reports = []
    for name, factor, beam in [('fuller', 1.01, hull.breadth_m), ('finer', .99, hull.breadth_m),
                               ('beam-plus-2m', 1.0, hull.breadth_m + 2)]:
        varied = vary_sections(hull, length_m=hull.length_m, breadth_m=beam,
                               draft_m=hull.draft_m, cb=cb * factor, lcb_fraction=lcb / hull.length_m)
        built = build_candidate(varied)
        hydro = built.report['hydrostatics']
        errors = dict(cb=abs(built.report['design_cb'] - cb * factor),
                      lcb_fraction=abs(hydro['lcb_m'] / hull.length_m - lcb / hull.length_m))
        if errors['cb'] > .001 or errors['lcb_fraction'] > .001:
            raise ValueError(f'{name} fails fixed target gates: {errors}')
        row = dict(name=name, length_m=varied.length_m, breadth_m=varied.breadth_m,
                   draft_m=varied.draft_m, target_cb=cb * factor,
                   target_lcb_fraction=lcb / hull.length_m, errors=errors, **built.report)
        (out / (name + '.json')).write_text(json.dumps(row, indent=2))
        cq.exporters.export(built.solid, str(out / (name + '.step')))
        image(varied, out / (name + '.png'), 'KVLCC2 ' + name)
        reports.append(row)
    report = dict(status='draft', engineering_approved=False, candidates=reports)
    (out / 'candidates.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sections', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--candidates', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.sections, args.out, args.candidates), indent=2))
