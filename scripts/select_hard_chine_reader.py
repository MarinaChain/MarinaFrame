"""Run the three hard-chine readers and the frozen baseline on the five development sheets (no model calls).

Protocol: docs/plans/2026-11-11-reader-selection.md (committed before this script ran). Arms:

- frozen: frozen v1 reader with nesting-rank identities (baseline);
- joining: `body_plan_chine.join_chine` on the frozen reading, rank identities;
- reader_v2: `body_plan_reader_v2` (drawn chine line) on the frozen reading;
- polyline: `body_plan_polyline` with the product rule of `benchmarks/deadrise_holdout/score.py`.

Same harness calibrations, truth files and scorers as scripts/measure_chine_reader_v2.py. Truth is read
after all arms have read the sheet, for scoring only. Metrics: the existing scorer (M1) and the per-section
ink distance (M2), both defined in the protocol.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_body_plan_chine as base  # noqa: E402
from measure_chine_reader_v2 import summarise  # noqa: E402
from benchmarks.balclutha import crossing_value as cv  # noqa: E402
from benchmarks.balclutha import model_value as balclutha  # noqa: E402
from benchmarks.bue_girl import holdout_value as bue  # noqa: E402
from benchmarks.bumble_bee import holdout_value as bumble  # noqa: E402
from benchmarks.deadrise_holdout import score as product  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_crossings as crossings  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_reader as reader  # noqa: E402
from benchmarks.pardon_me import holdout_value as pardon  # noqa: E402
from benchmarks.thayer import holdout_value as thayer  # noqa: E402
from vessel_reconstruction import body_plan_chine as chine  # noqa: E402
from vessel_reconstruction import body_plan_polyline as polyline  # noqa: E402
from vessel_reconstruction import body_plan_reader_v2 as v2  # noqa: E402

ARMS = ('frozen', 'joining', 'reader_v2', 'polyline')
# Protocol section 5: samples per chord between two cells, the margin round a section's bounding box for the
# distance transform, and the maximum distance above which a section counts as off ink.
CHORD_SAMPLES = 9
DISTANCE_MARGIN_PX = 200
OFF_INK_M = 0.05


def development_cases(sources: Path, truth_root: Path, legacy_truth_root: Path) -> list[tuple]:
    """(name, sheet path, truth path, layout, truth loader, scorer): protocol section 3."""
    return [
        ('PARDON ME', sources / 'haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif',
         truth_root / 'pardon-me/truth_s4.json', pardon.sheet_layout(), pardon.load_truth, pardon.score),
        ('BUE GIRL', sources / 'haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif',
         truth_root / 'bue-girl/truth_s2.json', bue.sheet_layout(), bue.load_truth, bue.score),
        ('C.A. Thayer', sources / 'haer/ca_thayer/loc_ca1506_sheet_04.tif',
         legacy_truth_root / 'thayer/truth_s4.json', thayer.sheet_layout(), thayer.load_truth, thayer.score),
        ('Balclutha', sources / 'balclutha_ca54_s7.tif',
         legacy_truth_root / 'balclutha/truth_s7.json', cv.sheet_layout(), balclutha.load_truth, cv.score),
        ('BUMBLE BEE (corrected sides)', sources / 'haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif',
         truth_root / 'bumble-bee/truth_s2.json', base.corrected_bumble_layout(), bumble.load_truth, bumble.score),
    ]


def read_all_arms(ink: np.ndarray, layout) -> dict[str, dict]:
    """Waterline table {(station, waterline): half-breadth m} of each arm, from one frozen reading."""
    frozen = cv.measure(ink, layout)
    identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in frozen.items()}
    tables = {'frozen': cv.table_and_flags(frozen, identities, layout)[0]}

    joined = {name: chine.join_chine(ink, layout, r) for name, r in frozen.items()}
    joined_identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                         for name, r in joined.items()}
    tables['joining'] = cv.table_and_flags(joined, joined_identities, layout)[0]

    tables['reader_v2'] = v2.sheet_table(v2.read_sheet(ink, layout, frozen), layout)[0]

    halves = polyline.read_sheet(ink, layout)
    product.engage(halves, frozen, identities, layout, ink)
    tables['polyline'] = product.polyline_table(halves, frozen, identities, layout)
    return tables


def section_ink_distances(table: dict, ink: np.ndarray, layout) -> list[dict]:
    """Per-section ink distance (protocol M2): chord samples between consecutive cells to the nearest ink."""
    side_of = {station: side for side in layout.sides for station in side.stations_outer_first}
    height = {w: row for w, row in layout.waterline_rows.items()}
    sections = []
    for station, side in side_of.items():
        cells = sorted(((height[w], value) for (s, w), value in table.items() if s == station), reverse=True)
        if len(cells) < 2:
            continue
        points = np.array([(row, layout.centre_column + side.sign * value * layout.pixels_per_metre)
                           for row, value in cells])
        fractions = np.arange(1, CHORD_SAMPLES + 1) / (CHORD_SAMPLES + 1)
        samples = np.concatenate([a + fractions[:, None] * (b - a) for a, b in zip(points, points[1:])])
        top, left = np.floor(samples.min(axis=0)).astype(int) - DISTANCE_MARGIN_PX
        bottom, right = np.ceil(samples.max(axis=0)).astype(int) + DISTANCE_MARGIN_PX
        top, left = max(top, 0), max(left, 0)
        bottom, right = min(bottom, ink.shape[0]), min(right, ink.shape[1])
        crop = ink[top:bottom, left:right]
        if not crop.any():
            continue
        distance = distance_transform_edt(~crop)
        rows = np.clip(np.rint(samples[:, 0]).astype(int) - top, 0, crop.shape[0] - 1)
        columns = np.clip(np.rint(samples[:, 1]).astype(int) - left, 0, crop.shape[1] - 1)
        metres = distance[rows, columns] / layout.pixels_per_metre
        sections.append({'half': side.name, 'station': station, 'cells': len(cells),
                         'rms_m': float(np.sqrt(np.mean(metres ** 2))), 'max_m': float(metres.max())})
    return sections


def ink_summary(sections: list[dict]) -> dict:
    if not sections:
        return {'sections': 0, 'median_rms_mm': None, 'off_ink_sections': 0, 'off_ink_stations': []}
    return {'sections': len(sections),
            'median_rms_mm': float(np.median([s['rms_m'] for s in sections]) * 1000),
            'off_ink_sections': sum(s['max_m'] > OFF_INK_M for s in sections),
            'off_ink_stations': [s['station'] for s in sections if s['max_m'] > OFF_INK_M]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--truth-root', required=True, type=Path)
    parser.add_argument('--legacy-truth-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    report = {'engineering_approved': False, 'protocol': 'docs/plans/2026-11-11-reader-selection.md',
              'commit': commit, 'cases': []}
    for name, sheet_path, truth_path, layout, load_truth, scorer in development_cases(
            args.sources, args.truth_root, args.legacy_truth_root):
        missing = [str(p) for p in (sheet_path, truth_path) if not p.is_file()]
        if missing:
            report['cases'].append({'sheet': name, 'unavailable_inputs': missing})
            print(f'{name}: missing inputs {missing}', flush=True)
            continue
        started = time.monotonic()
        ink = crossings.load_ink(sheet_path)
        tables = read_all_arms(ink, layout)
        truth = load_truth(truth_path)  # read only now, after every arm has read the sheet
        case = {'sheet': name, 'sheet_sha256': base.fingerprint(sheet_path),
                'truth_sha256': base.fingerprint(truth_path), 'truth_cells': len(truth), 'arms': {}}
        for arm in ARMS:
            sections = section_ink_distances(tables[arm], ink, layout)
            case['arms'][arm] = {'score': summarise(tables[arm], truth, scorer), 'ink': ink_summary(sections),
                                 'sections': sections,
                                 'identical_to_frozen': tables[arm] == tables['frozen']}
        case['seconds'] = round(time.monotonic() - started, 1)
        report['cases'].append(case)
        for arm in ARMS:
            s, i = case['arms'][arm]['score'], case['arms'][arm]['ink']
            print(f"{name:30s} {arm:10s} cells {s['cells_given']}/{len(truth)} RMS {s.get('rms_m', float('nan')):.6f} "
                  f"max {s.get('max_abs_m', float('nan')):.4f} wrong {s['wrong_cells']} "
                  f"identity {s['identity_errors']} extra {len(s['extra_cell_keys'])} "
                  f"ink median {i['median_rms_mm']} mm off-ink {i['off_ink_sections']} "
                  f"same-as-frozen {case['arms'][arm]['identical_to_frozen']}", flush=True)
        del ink
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')


if __name__ == '__main__':
    main()
