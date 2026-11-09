"""Print every frozen-reader chine candidate and the current rejection gates.

No detector changes. Include all pairs searched by join_chine, plus any other
vertically ordered pair whose ends are within one waterline spacing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.pardon_me import diagnose as diagnosis
from benchmarks.pardon_me import holdout_value as hv
from vessel_reconstruction import body_plan_chine as chine


def inspect(reading, layout):
    spacing = hv.bpr.waterline_spacing(layout)
    widths = [c.width_px for cs in reading.stations.values() for c in cs]
    tolerance = min(chine.END_WIDTHS * float(np.median(widths)), spacing * chine.END_SPACING_SHARE)
    levels = {w: i for i, w in enumerate(layout.waterlines_low_to_high())}
    rows = []
    groups = {}
    for i, lower in enumerate(reading.chains):
        for j, upper in enumerate(reading.chains):
            if i == j:
                continue
            low_level = max(levels[w] for w in lower.nodes)
            upper_level = min(levels[w] for w in upper.nodes)
            below = chine._end(lower, True, spacing * chine.FIT_SPACING_SHARE)
            above = chine._end(upper, False, spacing * chine.FIT_SPACING_SHARE)
            if below is None or above is None:
                if upper_level == low_level + 1:
                    rows.append({'lower': i, 'upper': j, 'first_rejection': 'endpoint fit unavailable'})
                continue
            p, sl, bl = below
            q, su, bu = above
            gap = float(np.linalg.norm(p - q))
            searched = upper_level == low_level + 1
            if not searched and not (upper_level > low_level and gap <= spacing):
                continue
            angle = float(abs(np.degrees(np.arctan(sl) - np.arctan(su))))
            if abs(sl - su) > 1e-12:
                y = (bu - bl) / (sl - su)
                x = sl * y + bl
                reach = float(max(np.linalg.norm(np.array([y, x]) - end) for end in (p, q)))
            else:
                y = x = reach = None
            rejections = []
            if not searched:
                rejections.append('adjacent levels')
            if gap > tolerance:
                rejections.append('gap')
            if angle < chine.MIN_TURN_DEGREES:
                rejections.append('angle')
            if reach is None or reach > tolerance:
                rejections.append('intersection reach')
            meeting = chine._meeting(lower, upper, spacing, tolerance)
            if searched and meeting is not None:
                groups.setdefault(low_level, []).append(chine._Join(i, j, *meeting))
            rows.append({'lower': i, 'upper': j, 'searched': searched,
                         'lower_end_y_x': p.tolist(), 'upper_end_y_x': q.tolist(),
                         'dx': float(q[1] - p[1]), 'dy': float(q[0] - p[0]),
                         'gap': gap, 'angle': angle, 'slopes': [sl, su],
                         'intersection_y_x': [y, x], 'intersection_reach': reach,
                         'level_step': upper_level - low_level,
                         'local_rejections': rejections,
                         'first_rejection': rejections[0] if rejections else 'series'})
    series = []
    for level, candidates in groups.items():
        unique = [c for c in candidates if sum(o.lower == c.lower for o in candidates) == 1
                  and sum(o.upper == c.upper for o in candidates) == 1]
        accepted = chine._series(candidates, reading, spacing)
        series.append({'level': level, 'candidates': [[c.lower, c.upper] for c in candidates],
                       'unique': [[c.lower, c.upper] for c in unique],
                       'accepted': [[c.lower, c.upper] for c in accepted]})
    return {'tolerance': tolerance, 'spacing': spacing, 'fit_rows': spacing * chine.FIT_SPACING_SHARE,
            'pairs': rows, 'series': series,
            'chains': [{'index': i, 'nodes': c.nodes,
                        'crossings': {w: diagnosis.crossing_record(reading.stations[w][n], reading.layout, layout)
                                      for w, n in c.nodes.items()}}
                       for i, c in enumerate(reading.chains)]}


def markdown(report):
    lines = ['### Why no joins: measured rejection gates (`4232502`)', '',
             'This is diagnosis of the unchanged detector, not a threshold search. Chain indices are the frozen reader indices used by `benchmarks/pardon_me/diagnose.py`. The saved-arm diagnosis was reconstructed and checked against its saved scores. No new station identities are inferred from proximity.', '',
             'Enumeration includes **every ordered pair searched by `join_chine`** (upper lowest waterline exactly one level above lower highest), plus vertically ordered pairs with ends within one waterline spacing (300 px) even if the level gate excludes them. Thus distant search candidates are retained, not filtered away. Δx and Δy are upper-piece bottom end minus lower-piece top end, in image coordinates. Gap is Euclidean. Reach is the greatest distance from either endpoint to the fitted line intersection. Both gap and reach must meet the same tolerance; small gap alone is insufficient.', '']
    for side, data in report['sides'].items():
        tol = data['tolerance']
        lines += [f'#### {side}', '',
                  f'Waterline spacing = {data["spacing"]:.1f} px; endpoint fit window = {data["fit_rows"]:.1f} px (skip first 3 px, at least 5 samples and 15 px row span). Gap and intersection reach ≤ **{tol:.3f} px** = min(2 × median station width, 0.05 × spacing). Angle ≥ **20°**. Level step = **1**.', '',
                  '| Lower → upper chain | Level step (=1) | Δx / Δy px | Gap px (≤ ' + f'{tol:.3f}' + ') | Angle ° (≥20) | Reach px (≤ ' + f'{tol:.3f}' + ') | First rejection; other failed local gates |',
                  '|---|---:|---:|---:|---:|---:|---|']
        for p in data['pairs']:
            if 'gap' not in p:
                lines.append(f'| {p["lower"]} → {p["upper"]} | — | — | — | — | — | endpoint fit unavailable |')
                continue
            reach = 'parallel' if p['intersection_reach'] is None else f'{p["intersection_reach"]:.2f}'
            failures = '; '.join(p['local_rejections']) or 'local pass; series gate'
            lines.append(f'| {p["lower"]} → {p["upper"]} | {p["level_step"]} | {p["dx"]:.2f} / {p["dy"]:.2f} | {p["gap"]:.2f} | {p["angle"]:.2f} | {reach} | {failures} |')
        lines += ['', 'Series gates (after local gates): each lower and upper endpoint must have **exactly 1** candidate; **at least 3** unique pairs; strict nesting at shared waterlines; column span **>15 px**; maximum straight-series row residual **≤12 px**.', '',
                  'Actual local-pass groups: `' + json.dumps(data['series']) + '`.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    args = parser.parse_args()
    saved = diagnosis.diagnose(args.sheet, args.truth, args.runs)
    layout = hv.sheet_layout()
    ink = hv.bpc.load_ink(args.sheet)
    readings = hv.round8.measure(ink, layout)
    report = {'implementation_commit': '4232502', 'saved_diagnosis_scores': [t['score'] for t in saved['tables']],
              'sides': {name: inspect(r, layout) for name, r in readings.items()}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    text = markdown(report)
    args.markdown.write_text(text + '\n')
    print(text)


if __name__ == '__main__':
    main()
