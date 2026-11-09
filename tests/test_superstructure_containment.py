"""Containment: no deck, bulwark or deckhouse stands out past the hull side.

Tolerance: ``superstructure.CHECK_TOLERANCE_M`` (0.02 m, two deck plate thicknesses; plan
section 3.8). The distance of a surface point is its plan distance outside the hull side at its
own height (``HullSide.outside_distance``), checked at every tessellation vertex and triangle
centre of each built part.

The synthetic case has a flared bow, a stem that rakes forward, and GA outlines that are wider
and longer than the hull. Set ``MARINAFRAME_GUNNERUS_SOURCES`` to a Gunnerus source folder
(licensed drawings, never in the repository) to run the same check on the real drawings.
"""
import os
from pathlib import Path

import numpy as np
import pytest

from vessel_reconstruction.superstructure import CHECK_TOLERANCE_M, HullSide

cq = pytest.importorskip('cadquery')
pytestmark = pytest.mark.cad


def ship_section(x, deck_half_breadth, flare, stem_rise=0.0):
    """Wall-sided to z 3 m, flaring above; a bow section starts ``stem_rise`` above the base."""
    rows = [[z, 0.0, deck_half_breadth + max(z - 3.0, 0.0) * flare]
            for z in np.arange(stem_rise, 6.0 + 1e-9, 0.1)]
    return {'x_m': x, 'regions': [{'kind': 'main', 'rows_m': rows}]}


def ship_hull():
    sections = [ship_section(x, 4.0, 0.0) for x in (0.0, 4.0, 8.0, 12.0)]
    # The bow narrows, flares more and its stem rakes forward (sections start higher up).
    for x, half_breadth, flare, rise in ((14.0, 3.2, 0.3, 0.5), (16.0, 2.0, 0.5, 1.5), (17.0, 1.0, 0.7, 2.5),
                                         (17.5, 0.4, 0.8, 3.2)):
        sections.append(ship_section(x, half_breadth, flare, rise))
    return HullSide.from_sections(sections)


def labelled(value):
    return {'value': value, 'source': 'guessed', 'basis': 'synthetic'}


def component(cid, op, outline, height, thickness=None):
    args = {'outline': labelled(outline), 'height': labelled(height)}
    if thickness is not None:
        args['thickness'] = labelled(thickness)
    return {'id': cid, 'op': op, 'source': {'view': 'plan', 'region': cid, 'method': 'enclosed_region'},
            'args': args}


def surface_points(path: Path) -> np.ndarray:
    shape = cq.importers.importStep(str(path)).val()
    vertices, triangles = shape.tessellate(1.0, 0.2)  # STEP files are in millimetres
    points = np.array([[v.x, v.y, v.z] for v in vertices]) / 1000.0
    centres = points[np.asarray(triangles)].mean(axis=1)
    return np.concatenate([points, centres])


def assert_contained(hull, result, folder):
    for part in result['components']:
        if part['op'] not in ('deck', 'bulwark', 'deckhouse'):
            continue
        assert part['built'] and part['shape'] == 'follows_hull_side', part['id']
        points = surface_points(folder / f'{part["id"]}.step')
        distance = hull.outside_distance(points[:, 0], points[:, 1], points[:, 2])
        assert distance.max() <= CHECK_TOLERANCE_M, (part['id'], float(distance.max()),
                                                    points[int(np.argmax(distance))].round(3).tolist())


def test_no_part_stands_out_past_a_flared_bow(tmp_path):
    from vessel_reconstruction.ship_cad import execute

    hull = ship_hull()
    # GA outlines drawn at the rail: 0.3 m wider than the hull at the deck and past the stem.
    rail = [[-0.5, -4.3], [15.0, -4.3], [18.5, 0.0], [15.0, 4.3], [-0.5, 4.3]]
    program = {'schema': 'ship-cad/v1', 'components': [
        component('deck', 'deck', rail, [2.99, 3.0]),
        component('forecastle', 'deckhouse', [[10.0, -4.3], [18.5, -4.3], [18.5, 4.3], [10.0, 4.3]], [3.0, 5.0]),
        component('rail', 'bulwark', rail, [5.0, 6.0], 0.05),
        component('house', 'deckhouse', [[4.0, -3.0], [9.0, -3.0], [9.0, 3.0], [4.0, 3.0]], [5.0, 7.5])]}
    detail = {'hull_side': {'value': hull.to_dict(), 'source': 'traced', 'basis': 'synthetic lines'},
              'parts': {'deck': {'camber_m': labelled(0.16)},
                        'house': {'end_fwd': {'value': [[5.0, 10.0], [7.5, 9.0]], 'source': 'traced',
                                              'basis': 'raked front'}}}}
    result = execute(program, {}, tmp_path / 'out', detail=detail)
    assert_contained(hull, result, tmp_path / 'out')
    checks = {part['id']: part['check_items'] for part in result['components']}
    assert checks['deck'] and checks['forecastle'] and checks['rail']  # each disagreement is reported
    assert checks['house'] == []


@pytest.mark.skipif(not os.environ.get('MARINAFRAME_GUNNERUS_SOURCES'),
                    reason='needs the licensed Gunnerus drawings (MARINAFRAME_GUNNERUS_SOURCES)')
def test_gunnerus_parts_stay_inside_the_hull_side(tmp_path):
    from benchmarks.gunnerus.whole_vessel import build_inputs
    from benchmarks.gunnerus.whole_vessel_detail import add_detail
    from vessel_reconstruction.ship_cad import execute

    sources = Path(os.environ['MARINAFRAME_GUNNERUS_SOURCES'])
    inputs = build_inputs(sources)
    add_detail(inputs, sources)
    result = execute(inputs['program'], inputs['measurements'], tmp_path / 'out', guesses=inputs['guesses'],
                     detail=inputs['detail'])
    assert_contained(HullSide.from_dict(inputs['detail']['hull_side']['value']), result, tmp_path / 'out')
