"""Known 3D box arrangements. Truth is never placed in the image input folder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random

from vessel_reconstruction.ga_arrangement import frame_to_m

SHIP_TYPES = ('bulk_carrier', 'tanker', 'general_cargo')


def arrangements(seed: int = 17) -> list[dict]:
    rng = random.Random(seed)
    return [_arrangement(rng, seed, index, kind) for index, kind in enumerate(SHIP_TYPES * 2)]


def _arrangement(rng: random.Random, seed: int, index: int, kind: str) -> dict:
    spacing = rng.choice([700, 750, 800])
    last = rng.choice([180, 200, 220])
    frames = [{'from_frame': 0, 'to_frame': last, 'spacing_mm': spacing}]
    length = frame_to_m(last, frames)
    beam = round(length / rng.uniform(6.0, 7.0), 2)
    depth = round(beam / 1.8, 2)
    inner_bottom = round(depth * 0.14, 2)
    wing_inner = round(beam * 0.36, 2)
    half_beam = round(beam / 2, 2)
    spaces = []

    def add(kind, label, aft, forward, y, z):
        spaces.append({'id': f's{len(spaces) + 1:03}', 'kind': kind, 'label': label,
                       'frames': [aft, forward],
                       'box_m': {'x': [frame_to_m(aft, frames), frame_to_m(forward, frames)],
                                 'y': list(y), 'z': list(z)}})

    add('ballast_tank', 'AFT PEAK W.B.', 0, 8, (-half_beam * .6, half_beam * .6), (0, depth))
    add('engine_room', 'E/R', 8, 38, (-half_beam, half_beam), (inner_bottom, depth))
    add('ballast_tank', 'FWD PEAK W.B.', last - 12, last, (-half_beam * .5, half_beam * .5), (0, depth))
    for tier in range(1, 4):
        add('accommodation_deck', f'DECK {tier}', 10 + tier, 34 - tier,
            (-wing_inner, wing_inner), (depth + (tier - 1) * 2.8, depth + tier * 2.8))
    count = rng.choice([3, 4, 5])
    ends = [round(42 + i * (last - 58) / count) for i in range(count + 1)]
    for bay, (aft, forward) in enumerate(zip(ends, ends[1:]), 1):
        add('ballast_tank', f'NO.{bay} DB W.B.', aft, forward,
            (-wing_inner, wing_inner), (0, inner_bottom))
        for side, y in [('S', (-half_beam, -wing_inner)), ('P', (wing_inner, half_beam))]:
            add('ballast_tank', f'NO.{bay} WING W.B. {side}', aft, forward, y, (0, depth))
        if kind == 'tanker':
            for side, y in [('S', (-wing_inner, 0)), ('P', (0, wing_inner))]:
                add('cargo_tank', f'NO.{bay} C.O.T. {side}', aft, forward, y, (inner_bottom, depth))
        else:
            add('cargo_hold', f'NO.{bay} HOLD', aft, forward,
                (-wing_inner, wing_inner), (inner_bottom, depth))
            add('cargo_hatch', f'NO.{bay} HATCH', aft + 2, forward - 2,
                (-beam * .25, beam * .25), (depth, depth + 1.5))
            if bay < count:
                add('cargo_crane', f'CR.{bay}', forward - 1, forward + 1,
                    (-1, 1), (depth + 1.5, depth + beam * .55))
    return {'schema': 'marinaframe.ga_synthetic_truth.v1', 'seed': seed,
            'case_id': f'SYN-GA-{index + 1:03}', 'ship_type': kind,
            'engineering_approved': False,
            'axes': 'metres: x forward from AP/frame 0; y port; z above baseline',
            'dimensions': {'lbp_m': length, 'loa_m': length, 'breadth_m': beam, 'depth_m': depth},
            'frames': {'spacings': frames},
            'frame_table': [{'frame': f, 'x_m': frame_to_m(f, frames)} for f in range(last + 1)],
            'spaces': spaces}


def write_suite(out: Path, seed: int = 17, count: int = 6) -> None:
    """Refuse to overwrite a run. Images alone are the future reader input."""
    from .render import draw_arrangement

    if not 1 <= count <= 6:
        raise ValueError('count must be in 1..6')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'images').mkdir()
    (out / 'truth').mkdir()
    for case in arrangements(seed)[:count]:
        name = case['case_id']
        draw_arrangement(case).save(out / 'images' / f'{name}.png')
        (out / 'truth' / f'{name}.json').write_text(json.dumps(case, indent=2, allow_nan=False) + '\n')
    entries = []
    for path in sorted(out.glob('*/*')):
        entries.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(out)}')
    (out / 'SHA256SUMS').write_text('\n'.join(entries) + '\n')
