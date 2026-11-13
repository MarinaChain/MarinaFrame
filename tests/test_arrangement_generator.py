"""Analytic controls for draft hull-clipped tanker arrangements."""
from dataclasses import replace
import json

import pytest

from vessel_reconstruction.arrangement_generator import (
    ArrangementInput, generate_arrangement, protection_dimensions,
)


def inputs(**changes):
    return replace(ArrangementInput(
        length_m=100, breadth_m=20, depth_m=12, deadweight_t=10000,
        rule_length_m=100, solas_length_m=100,
        cargo_rows=6, cargo_columns=2, engine_room_length_m=15,
        forepeak_length_m=6, slop_length_m=4, slop_columns=2,
        fuel_reserve_length_m=2, sources=('synthetic-control',),
    ), **changes)


@pytest.mark.parametrize('dwt,beam,expected', [
    (5000, 15, (1, 1)), (10000, 20, (1, 20/15)),
    (100000, 60, (2, 2)),
])
def test_protection_formula(dwt, beam, expected):
    assert protection_dimensions(dwt, beam) == pytest.approx(expected)


@pytest.mark.parametrize('changes', [
    {'length_m': float('nan')}, {'breadth_m': -1}, {'deadweight_t': 4999},
    {'cargo_rows': 0}, {'cargo_rows': True}, {'cargo_columns': 1.5},
    {'slop_columns': 0}, {'slop_length_m': 90}, {'forepeak_length_m': 0},
    {'fuel_reserve_length_m': 15}, {'sources': ()}, {'sources': 'citation'},
    {'rule_length_m': float('inf')},
])
def test_invalid_inputs(changes):
    with pytest.raises(ValueError):
        inputs(**changes)


@pytest.mark.cad
@pytest.mark.parametrize('wedge', [False, True])
def test_real_hull_partition_volume_centres_and_record(wedge):
    import cadquery as cq
    # Width varies linearly 10..20 m: not a bounding-box capacity calculation.
    if wedge:
        hull = (cq.Workplane('XY').polyline([(0, -5), (100, -10),
                (100, 10), (0, 5)]).close().extrude(12).val())
        volume, centre_x = 18000, 500/9
    else:
        hull = cq.Solid.makeBox(100, 20, 12, cq.Vector(0, -10, 0))
        volume, centre_x = 24000, 50
    result = generate_arrangement(hull, inputs(), hull_units='m')
    assert result.hull_volume_m3 == pytest.approx(volume, rel=1e-6)
    assert result.partition_relative_error <= 0.01
    assert sum(c.volume_m3 for c in result.compartments) == pytest.approx(volume, rel=1e-6)
    assert sum(c.volume_m3 * c.centre_m[0] for c in result.compartments) / volume == pytest.approx(centre_x, abs=1e-6)
    assert sum(c.volume_m3 * c.centre_m[1] for c in result.compartments) / volume == pytest.approx(0, abs=1e-6)
    assert sum(c.volume_m3 * c.centre_m[2] for c in result.compartments) / volume == pytest.approx(6, abs=1e-6)
    for compartment in result.compartments:
        assert compartment.volume_m3 > 0
        assert compartment.capacity_98_m3 == pytest.approx(0.98 * compartment.volume_m3)
    assert result.cargo_capacity_98_m3 == pytest.approx(sum(c.capacity_98_m3 for c in result.compartments if c.kind == 'cargo'))
    assert result.segregated_ballast_m3 == pytest.approx(sum(c.volume_m3 for c in result.compartments if c.kind == 'ballast'))
    fragment = result.to_record_fragment()
    json.dumps(fragment, allow_nan=False)
    assert fragment['engineering_approved'] is False
    assert set(fragment['rule_screens']) == {'18', '19', '23', '26', '29', 'SOLAS-II-1-12'}
    assert all(r['status'] == 'review_required' for r in fragment['rule_screens'].values())
    assert fragment['rule_screens']['23']['mean_outflow']['value'] is None
    assert fragment['rule_screens']['23']['largest_single_tank_release']['value'] > 0
    required = {'value', 'unit', 'uncertainty', 'method', 'method_version', 'sources', 'status'}
    assert required <= fragment['cargo_capacity_98'].keys()
    assert fragment['cargo_capacity_98']['uncertainty'] is None
    assert fragment['cargo_capacity_98']['uncertainty_reason']
    assert fragment['compartments'][0]['boundaries']['value']['operation'] == 'hull_intersection'
    # Boundaries are disjoint in their interiors, before hull clipping.
    for i, a in enumerate(result.compartments):
        for b in result.compartments[i+1:]:
            overlap = [min(a.bounds_m[k+1], b.bounds_m[k+1]) - max(a.bounds_m[k], b.bounds_m[k]) for k in (0, 2, 4)]
            assert min(overlap) <= 1e-9


@pytest.mark.cad
def test_units_step_and_deck_clipping(tmp_path):
    import cadquery as cq
    hull = cq.Solid.makeBox(100000, 20000, 14000, cq.Vector(0, -10000, 0))
    path = tmp_path / 'hull.step'
    cq.exporters.export(hull, str(path))
    result = generate_arrangement(path, inputs(), hull_units='mm')
    assert result.hull_volume_m3 == pytest.approx(24000)
    assert result.to_record_fragment()['hull_basis']['sha256']
    assert result.compartments


@pytest.mark.cad
def test_bad_geometry_is_rejected():
    import cadquery as cq
    box = cq.Solid.makeBox(100, 20, 12, cq.Vector(0, -10, 0))
    with pytest.raises(ValueError, match='bounds'):
        generate_arrangement(box, inputs(breadth_m=22), hull_units='m')
    with pytest.raises(ValueError, match='solid'):
        generate_arrangement(box.Faces()[0], inputs(), hull_units='m')
    with pytest.raises(ValueError, match='units'):
        generate_arrangement(box, inputs(), hull_units='ft')


@pytest.mark.cad
def test_rule_screens_keep_failed_checks_visible():
    import cadquery as cq
    box = cq.Solid.makeBox(100, 20, 12, cq.Vector(0, -10, 0))
    result = generate_arrangement(box, inputs(cargo_rows=1, forepeak_length_m=20, slop_length_m=0.1), hull_units='m')
    rules = result.to_record_fragment()['rule_screens']
    assert rules['29']['screen_satisfied'] is False
    assert rules['26']['screen_satisfied'] is False
    assert rules['SOLAS-II-1-12']['screen_satisfied'] is False
    assert rules['18']['screen_satisfied'] is None
    assert rules['19']['screen_satisfied'] is None
    assert rules['23']['screen_satisfied'] is None


@pytest.mark.cad
def test_large_tanker_requires_two_slop_tanks():
    import cadquery as cq
    box = cq.Solid.makeBox(100, 20, 12, cq.Vector(0, -10, 0))
    result = generate_arrangement(box, inputs(deadweight_t=70000, slop_columns=1, slop_length_m=10), hull_units='m')
    assert result.to_record_fragment()['rule_screens']['29']['screen_satisfied'] is False


@pytest.mark.cad
def test_disconnected_tank_regions_are_rejected():
    import cadquery as cq
    bottom = cq.Solid.makeBox(100, 20, 1, cq.Vector(0, -10, 0))
    port = cq.Solid.makeBox(100, 5, 11, cq.Vector(0, -10, 1))
    starboard = cq.Solid.makeBox(100, 5, 11, cq.Vector(0, 5, 1))
    hull = bottom.fuse(port, starboard)
    with pytest.raises(ValueError, match='disconnected'):
        generate_arrangement(hull, inputs(cargo_columns=1, slop_columns=1), hull_units='m')


@pytest.mark.cad
def test_step_with_multiple_objects_is_rejected(tmp_path):
    import cadquery as cq
    first = cq.Solid.makeBox(100, 20, 12, cq.Vector(0, -10, 0))
    second = cq.Solid.makeBox(1, 1, 1, cq.Vector(200, 0, 0))
    path = tmp_path / 'multiple.step'
    cq.exporters.export(cq.Compound.makeCompound([first, second]), str(path))
    with pytest.raises(ValueError, match='solid'):
        generate_arrangement(path, inputs(), hull_units='m')
