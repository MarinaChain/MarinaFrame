"""Analytic synthetic checks; no reference-ship geometry or capacity fixtures."""
import math

import pytest

from vessel_reconstruction.arrangement_generator.shaped import (
    EnvelopeStation, TankEnvelope, build_envelope, measure_tanks, offset_side,
)

pytestmark = pytest.mark.cad


def box(length=12, width=20, depth=12):
    import cadquery as cq
    return cq.Solid.makeBox(length, width, depth, cq.Vector(0, -width/2, 0))


def prism(points, length=12):
    return build_envelope((EnvelopeStation(0, points), EnvelopeStation(length, points)))


def test_hopper_prism_volume_and_centroid():
    # Rectangle 16*9 less two 2*2/2 hopper triangles.
    points = ((-6, 1), (6, 1), (8, 3), (8, 10), (-8, 10), (-8, 3))
    shape = prism(points)
    tank = measure_tanks(box(), (TankEnvelope('oil', 'cargo', shape, ('synthetic',)),), units='m')[0]
    area = 144 - 4
    z_centroid = (144*5.5 - 4*(1+2/3)) / area
    assert tank.volume_m3 == pytest.approx(area*12, rel=1e-6)
    assert tank.centre_m == pytest.approx((6, 0, z_centroid), abs=1e-6)
    assert tank.capacity_m3 == pytest.approx(area*12*.98, rel=1e-6)


def test_cambered_deck_is_not_flattened():
    points = ((-8, 1), (8, 1), (8, 9), (0, 11), (-8, 9))
    measured = measure_tanks(box(), (TankEnvelope('oil', 'cargo', prism(points), ('synthetic',)),), units='m')[0]
    assert measured.volume_m3 == pytest.approx((16*8 + 16*2/2)*12, rel=1e-6)
    assert measured.centre_m[2] == pytest.approx((128*5 + 16*(9+2/3))/144, abs=1e-6)


def test_varying_side_follows_declared_ruled_surface():
    a = ((-4, 2), (4, 2), (4, 8), (-4, 8))
    b = ((-8, 2), (8, 2), (8, 8), (-8, 8))
    shape = build_envelope((EnvelopeStation(0, a), EnvelopeStation(12, b)))
    measured = measure_tanks(box(), (TankEnvelope('oil', 'cargo', shape, ('synthetic',)),), units='m')[0]
    assert measured.volume_m3 == pytest.approx(12*12*6, rel=1e-6)
    assert measured.centre_m == pytest.approx((20/3, 0, 5), abs=1e-6)


def test_shell_normal_offset_of_sloped_side():
    # y=4+z/2. A horizontal subtraction of 2 is not a normal offset of 2.
    points = offset_side(((4, 0), (9, 10)), 2)
    for y, z in points:
        assert (4+z/2-y)/math.sqrt(1.25) == pytest.approx(2, abs=1e-12)


def test_hull_clipping_and_explicit_deduction_are_separate():
    shape = prism(((-12, 1), (12, 1), (12, 10), (-12, 10)))
    measured = measure_tanks(box(), (TankEnvelope('oil', 'cargo', shape, ('synthetic',), usable_fraction=.95, fill_fraction=.9),), units='m')[0]
    assert measured.volume_m3 == pytest.approx(12*20*9, rel=1e-6)
    assert measured.capacity_m3 == pytest.approx(12*20*9*.95*.9, rel=1e-6)
    fragment = measured.to_record_fragment()
    assert fragment['engineering_approved'] is False
    assert fragment['capacity']['sources'] == ['synthetic']
    assert fragment['capacity']['method'] == 'explicit_shaped_envelope_hull_intersection'


def test_touching_tanks_allowed_but_overlaps_rejected():
    left = prism(((-8, 1), (0, 1), (0, 10), (-8, 10)))
    right = prism(((0, 1), (8, 1), (8, 10), (0, 10)))
    specs = (TankEnvelope('left', 'cargo', left, ('synthetic',)), TankEnvelope('right', 'cargo', right, ('synthetic',)))
    assert len(measure_tanks(box(), specs, units='m')) == 2
    with pytest.raises(ValueError, match='overlap'):
        measure_tanks(box(), (specs[0], TankEnvelope('duplicate', 'cargo', left, ('synthetic',))), units='m')


def test_mm_units_are_applied_to_hull_and_envelope():
    shape = prism(((-8, 1), (8, 1), (8, 10), (-8, 10)))
    measured = measure_tanks(box().scale(1000), (TankEnvelope('oil', 'cargo', shape.scale(1000), ('synthetic',)),), units='mm')[0]
    assert measured.volume_m3 == pytest.approx(12*16*9, rel=1e-6)


@pytest.mark.parametrize('kwargs', [dict(fill_fraction=float('nan')), dict(fill_fraction=0), dict(fill_fraction=1.1), dict(usable_fraction=0), dict(usable_fraction=float('inf')), dict(sources=()), dict(sources='citation'), dict(name=''), dict(kind='unknown')])
def test_bad_tank_metadata_rejected(kwargs):
    args = dict(name='oil', kind='cargo', envelope=box(), sources=('synthetic',))
    args.update(kwargs)
    with pytest.raises(ValueError):
        TankEnvelope(**args)


@pytest.mark.parametrize('stations', [(), (EnvelopeStation(0, ((0, 0), (1, 0), (1, 1))),), (EnvelopeStation(0, ((0, 0), (1, 0), (1, 1))), EnvelopeStation(0, ((0, 0), (1, 0), (1, 1)))), (EnvelopeStation(0, ((0, 0), (1, 0), (1, 1))), EnvelopeStation(1, ((0, 0), (1, 0), (1, 1), (0, 1))))])
def test_invalid_station_sequences_rejected(stations):
    with pytest.raises(ValueError):
        build_envelope(stations)


def test_nonfinite_and_self_crossed_polygon_rejected():
    with pytest.raises(ValueError):
        EnvelopeStation(float('nan'), ((0, 0), (1, 0), (1, 1)))
    with pytest.raises(ValueError):
        prism(((0, 0), (2, 2), (0, 2), (2, 0)))


@pytest.mark.parametrize('points,distance', [(((1, 0), (1, 3)), 2), (((2, 3), (4, 0)), 1), (((2, 0), (3, 1)), float('nan')), (((2, 0), (3, 1)), 0)])
def test_invalid_side_offsets_rejected(points, distance):
    with pytest.raises(ValueError):
        offset_side(points, distance)


def test_offset_miter_meets_both_shifted_segment_lines():
    points = offset_side(((4, 0), (6, 4), (6, 8)), 1)
    y, z = points[1]
    assert y == pytest.approx(5, abs=1e-12)
    assert (4+z/2-y)/math.sqrt(1.25) == pytest.approx(1, abs=1e-12)


def test_extra_non_solid_geometry_is_not_silently_discarded():
    import cadquery as cq
    mixed = cq.Compound.makeCompound([box(), box().Faces()[0].translate((30, 0, 0))])
    with pytest.raises(ValueError, match='closed solid'):
        measure_tanks(mixed, (TankEnvelope('oil', 'cargo', box(), ('synthetic',)),), units='m')


def test_open_hull_and_disconnected_envelopes_rejected():
    import cadquery as cq
    shape = prism(((-8, 1), (8, 1), (8, 10), (-8, 10)))
    with pytest.raises(ValueError, match='closed solid'):
        measure_tanks(box().Faces()[0], (TankEnvelope('oil', 'cargo', shape, ('synthetic',)),), units='m')
    compound = cq.Compound.makeCompound([shape, shape.translate((20, 0, 0))])
    with pytest.raises(ValueError, match='closed solid'):
        measure_tanks(box(), (TankEnvelope('oil', 'cargo', compound, ('synthetic',)),), units='m')
