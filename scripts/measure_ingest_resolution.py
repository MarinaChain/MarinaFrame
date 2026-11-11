"""Run section extraction (ingest) on development drawings at native and reduced resolution.

Code-review item 8. Development family `development_wigley` (seeds 17, 23, 41; clean and drafting
styles), generated with `benchmarks/generate.py` into the output folder, with the benchmark's
pixel-corridor proposal (`benchmarks/propose_pixel_corridors.py`) made once at native size; without
a corridor every panel is refused for its grid lines. A reduced drawing is the native drawing
area-averaged to `scale` times the pixel density; its specification maps the panel, centreline,
baseline, scale and corridor to the reduced grid. Ground truth is read only after extraction, to
score. Output: per case the extraction JSON (byte comparison between code versions) and a summary.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from benchmarks.generate import generate_section_sheet, procedural_sections
from benchmarks.propose_pixel_corridors import propose
from vessel_reconstruction.ingest import extract_sections

SEEDS = (17, 23, 41)
# The corridor proposal refuses the degraded style (speckle gives several dark strokes per row).
STYLES = ('clean', 'drafting')


def reduce_case(native: Path, reduced: Path, scale: float) -> None:
    """Write the reduced drawing and its specification (pixel centres: x' = (x + 0.5) * scale - 0.5)."""
    reduced.mkdir(parents=True, exist_ok=True)
    spec = json.loads((native / 'spec.json').read_text())
    with Image.open(native / spec['source']['file']) as image:
        size = (round(image.width * scale), round(image.height * scale))
        image.convert('L').resize(size, Image.Resampling.BOX).save(reduced / 'drawing.png')
    reduced_spec = copy.deepcopy(spec)
    for section in reduced_spec['sections']:
        left, top, right, bottom = section['roi_px']
        section['roi_px'] = [int(np.floor(left * scale)), int(np.floor(top * scale)),
                             int(np.ceil(right * scale)), int(np.ceil(bottom * scale))]
        calibration = section['calibration']
        calibration['centerline_px'] = (calibration['centerline_px'] + 0.5) * scale - 0.5
        calibration['baseline_px'] = (calibration['baseline_px'] + 0.5) * scale - 0.5
        calibration['pixels_per_metre'] *= scale
        selection = section['contour_selection']
        anchors = [[(x + 0.5) * scale - 0.5, (y + 0.5) * scale - 0.5] for x, y in selection['anchors_px']]
        # The corridor must span the whole traced range; pixel rounding may leave the ends one row short.
        anchors[0][1] = float(section['roi_px'][1])
        anchors[-1][1] = float(section['roi_px'][3] - 1)
        selection['anchors_px'] = anchors
        selection['half_width_px'] = max(2.0, selection['half_width_px'] * scale)
    (reduced / 'spec.json').write_text(json.dumps(reduced_spec, indent=2) + '\n')


def section_errors(result: dict, truth: dict) -> dict:
    """RMS half-breadth error over beam, per extracted section, against the generated truth."""
    truth_by_id = {section['id']: np.asarray(section['points_yz_m']) for section in truth['sections']}
    beam = truth['beam_m']
    errors = []
    for section in result['sections']:
        points = np.asarray(section['points_yz_m'])
        reference = truth_by_id[section['id']]
        expected = np.interp(points[:, 1], reference[:, 1], reference[:, 0])
        errors.append(float(np.sqrt(np.mean((points[:, 0] - expected) ** 2)) / beam))
    return {'sections': len(result['sections']), 'abstained': len(result['gaps']),
            'worst_rms_over_beam': max(errors) if errors else None,
            'mean_rms_over_beam': float(np.mean(errors)) if errors else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--cases', required=True, type=Path, help='Folder for generated drawings (reused)')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--scales', default='1.0,0.5,0.35')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {'label': args.label, 'engineering_approved': False, 'cases': []}
    for seed in SEEDS:
        for style in STYLES:
            name = f'development_wigley-{seed}-{style}'
            generated, native = args.cases / name / 'generated', args.cases / name / '1'
            if not (native / 'spec.json').exists():
                sections, volume, provenance = procedural_sections(seed, 'development_wigley')
                generate_section_sheet(sections, generated, vessel_id=f'development_wigley-{seed}', seed=seed,
                                       style=style, reference_volume_m3=volume, provenance=provenance,
                                       label_dir=args.cases / name / 'labels')
                propose(generated / 'spec.json', native)
            truth = json.loads((args.cases / name / 'labels' / 'ground_truth.json').read_text())
            for scale in (float(value) for value in args.scales.split(',')):
                folder = native if scale == 1.0 else args.cases / name / f'{scale:g}'
                if not (folder / 'spec.json').exists():
                    reduce_case(native, folder, scale)
                result = extract_sections(json.loads((folder / 'spec.json').read_text()), folder)
                text = json.dumps(result, indent=2, sort_keys=True)
                (args.out / f'{name}_{scale:g}_{args.label}.json').write_text(text)
                score = section_errors(result, truth)
                summary['cases'].append({'case': name, 'scale': scale, 'sha256': hashlib.sha256(text.encode()).hexdigest(),
                                         'gap_kinds': sorted({gap['kind'] for gap in result['gaps']}), **score})
                print(f"{args.label} {name} x{scale:g}: {score['sections']} sections, {score['abstained']} abstained, "
                      f"worst RMS/beam {score['worst_rms_over_beam']}, sha {summary['cases'][-1]['sha256'][:12]}",
                      flush=True)
    (args.out / f'ingest_summary_{args.label}.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
