"""Synthetic tests for parts above the hull (superstructure.py); no drawing data."""
import numpy as np
import pytest

from vessel_reconstruction.superstructure import (
    MAX_EXTRAPOLATION_M,
    HullSide,
    PlanShape,
    build_shaped,
    outline_extent,
    planform,
)


def flared_section(x, top_z=5.0, half_breadth_at_deck=4.0, flare=0.2):
    """A wall-sided section to z 3 m, then flaring out by ``flare`` m per metre up to ``top_z``."""
    rows = [[z, 0.0, half_breadth_at_deck + max(z - 3.0, 0.0) * flare] for z in np.arange(0.0, top_z + 1e-9, 0.25)]
    return {'x_m': x, 'regions': [{'kind': 'main', 'rows_m': rows}]}


def bow_hull():
    """Parallel body from x 0 to 10 m, then a bow that narrows to 1 m at x 14 m."""
    sections = [flared_section(x) for x in (0.0, 5.0, 10.0)]
    sections += [flared_section(12.0, half_breadth_at_deck=2.5), flared_section(14.0, half_breadth_at_deck=1.0)]
    return HullSide.from_sections(sections)


def test_hull_side_interpolates_and_continues_the_flare_above_the_top():
    hull = bow_hull()
    assert hull.half_breadth(5.0, 4.0) == pytest.approx(4.2)
    assert hull.half_breadth(11.0, 2.0) == pytest.approx(3.25)
    # Above the drawn top (5 m) the flare continues for at most MAX_EXTRAPOLATION_M.
    assert hull.half_breadth(5.0, 5.5) == pytest.approx(4.5)
    assert hull.half_breadth(5.0, 20.0) == pytest.approx(4.4 + 0.2 * MAX_EXTRAPOLATION_M)
    assert hull.half_breadth(-1.0, 4.0) == 0.0 and hull.half_breadth(15.0, 4.0) == 0.0


def test_hull_side_round_trips_through_json_values():
    hull = bow_hull()
    again = HullSide.from_dict(hull.to_dict())
    assert again.half_breadth(12.5, 3.3) == pytest.approx(hull.half_breadth(12.5, 3.3), abs=1e-4)


def test_outside_distance_is_lateral_or_longitudinal_whichever_is_smaller():
    hull = bow_hull()
    distance = hull.outside_distance([5.0, 5.0, 14.5, 13.0], [3.0, 4.5, 0.0, 3.9], [3.0, 3.0, 3.0, 3.0])
    assert distance[0] == 0.0
    assert distance[1] == pytest.approx(0.5)
    assert distance[2] == pytest.approx(0.5, abs=0.03)  # beyond the bow end: longitudinal
    # x 13 m: half-breadth 1.75 m, so 2.15 m lateral; the side is 3.9 m wide only aft of x 10.13 m.
    assert distance[3] == pytest.approx(2.15, abs=0.01)


cq = pytest.importorskip('cadquery')

# A GA deck outline that is 0.3 m wider than the hull and runs 2 m past the bow end.
WIDE_OUTLINE = [[0.0, -4.3], [16.0, -4.3], [16.0, 4.3], [0.0, 4.3]]


def surface_overhang(hull, solid, count=4000):
    vertices, _ = solid.tessellate(0.001, 0.2)
    points = np.array([[v.x, v.y, v.z] for v in vertices])
    return float(hull.outside_distance(points[:, 0], points[:, 1], points[:, 2]).max())


def test_outline_extent_reads_port_and_starboard_edges():
    low, high = outline_extent([[0, -1], [4, -1], [4, 2], [2, 3], [0, 2]], [1.0, 3.0, 5.0])
    assert low[:2].tolist() == [-1.0, -1.0] and high[0] == pytest.approx(2.5) and high[1] == pytest.approx(2.5)
    assert np.isnan(low[2])


@pytest.mark.cad
def test_deck_edge_follows_the_hull_and_the_disagreement_is_a_check_item():
    hull = bow_hull()
    solid, report = build_shaped('deck', 'deck', {'outline': WIDE_OUTLINE, 'height': [2.99, 3.0]}, hull)
    assert solid.isValid() and surface_overhang(hull, solid) <= 0.02
    kinds = {item['kind']: item for item in report['check_items']}
    # The outline is 4.3 m wide to x 16 m; the hull narrows to 1.0 m at its end (x 14 m).
    assert kinds['ga_outline_outside_hull']['distance_m'] == pytest.approx(3.3, abs=0.02)
    assert kinds['part_end_beyond_hull']['distance_m'] == pytest.approx(2.0, abs=0.05)


@pytest.mark.cad
def test_camber_raises_the_deck_centre_only():
    hull = bow_hull()
    detail = {'camber_m': {'value': 0.2, 'source': 'guessed', 'basis': 'B/50'}}
    solid, report = build_shaped('deck', 'deck', {'outline': WIDE_OUTLINE, 'height': [2.99, 3.0]}, hull, detail)
    box = solid.BoundingBox()
    assert box.zmax == pytest.approx(3.2, abs=0.005) and box.zmin == pytest.approx(2.99, abs=0.005)
    assert report['detail_used'] == ['camber_m']


@pytest.mark.cad
def test_bulwark_follows_the_flared_shell_above_the_deck():
    hull = bow_hull()
    values = {'outline': WIDE_OUTLINE, 'height': [3.0, 4.0], 'thickness': 0.05}
    solid, _ = build_shaped('wall', 'bulwark', values, hull)
    assert solid.isValid() and surface_overhang(hull, solid) <= 0.02
    # The flare makes the top 0.2 m wider than the base on each side (parallel body).
    section = solid.intersect(cq.Solid.makeBox(0.1, 20, 2, cq.Vector(5.0, -10, 2.5)))
    assert section.BoundingBox().ymax == pytest.approx(4.2, abs=0.01)


@pytest.mark.cad
def test_house_reaching_the_hull_side_is_cut_to_it_at_every_height():
    hull = bow_hull()
    values = {'outline': WIDE_OUTLINE, 'height': [3.0, 5.0]}
    solid, _ = build_shaped('house', 'deckhouse', values, hull)
    assert solid.isValid() and surface_overhang(hull, solid) <= 0.02
    plan = planform(PlanShape(WIDE_OUTLINE), hull, 3.0, 50)
    assert plan['x_range'][1] == pytest.approx(14.0)  # the hull end, not the outline end (16 m)


def deck_program():
    def labelled(value):
        return {'value': value, 'source': 'guessed', 'basis': 'test value'}
    return {'schema': 'ship-cad/v1', 'components': [
        {'id': 'deck', 'op': 'deck', 'source': {'view': 'plan', 'region': 'deck', 'method': 'enclosed_region'},
         'args': {'outline': labelled(WIDE_OUTLINE), 'height': labelled([2.99, 3.0])}}]}


@pytest.mark.cad
def test_execute_builds_hull_following_parts_and_labels_detail_values(tmp_path):
    from vessel_reconstruction.ship_cad import execute

    detail = {'hull_side': {'value': bow_hull().to_dict(), 'source': 'traced', 'basis': 'test lines'},
              'parts': {'deck': {'camber_m': {'value': 0.0, 'source': 'traced', 'basis': 'level deck line'}}}}
    report = execute(deck_program(), {}, tmp_path / 'out', detail=detail)
    component = report['components'][0]
    assert component['built'] and component['shape'] == 'follows_hull_side'
    assert component['source_labels']['hull_side'] == 'traced'
    assert component['source_labels']['camber_m'] == 'traced'
    assert component['bbox_m']['max'][1] <= 4.0 + 1e-6
    assert component['check_items'] and report['engineering_approved'] is False


def test_execute_without_a_usable_hull_side_keeps_the_straight_part(tmp_path):
    from vessel_reconstruction.ship_cad import execute

    report = execute(deck_program(), {}, tmp_path / 'out', detail={'hull_side': {'value': {'x_m': [0]}}})
    component = report['components'][0]
    assert component['built'] and 'shape' not in component
    assert component['bbox_m']['max'][1] == pytest.approx(4.3)


@pytest.mark.parametrize('rise_mm, expected_m', [(0.0, 0.0), (190.0, 0.19)])
def test_midship_section_camber_is_the_rise_of_the_labelled_deck_line(tmp_path, rise_mm, expected_m):
    ezdxf = pytest.importorskip('ezdxf')
    from vessel_reconstruction.ga_reader import section_deck_camber

    document = ezdxf.new()
    space = document.modelspace()
    space.add_text('1-DECK', dxfattribs={'height': 100, 'insert': (0, 4374)})
    # A half section: side at x 1000, centreline at x 5800; the deck line rises to the centre.
    space.add_lwpolyline([(1000, 4300), (3400, 4300 + rise_mm * 0.75), (5800, 4300 + rise_mm)],
                         dxfattribs={'layer': 'S0CO5'})
    space.add_line((1000, 0), (9000, 0), dxfattribs={'layer': 'S0CO5'})  # baseline: not beside the label
    document.saveas(tmp_path / 'section.dxf')
    result = section_deck_camber(tmp_path / 'section.dxf')
    assert result['camber_m'] == pytest.approx(expected_m) and result['sections'] == 1


def test_no_deck_line_gives_no_camber_reading(tmp_path):
    ezdxf = pytest.importorskip('ezdxf')
    from vessel_reconstruction.ga_reader import section_deck_camber

    document = ezdxf.new()
    document.modelspace().add_text('1-DECK', dxfattribs={'height': 100, 'insert': (0, 4374)})
    document.saveas(tmp_path / 'empty.dxf')
    assert section_deck_camber(tmp_path / 'empty.dxf') is None


def profile_view():
    from vessel_reconstruction.ga_reader import View

    return View('profile', 'profile', [0, 0, 50000, 20000], [0, 0])


def test_end_contour_follows_a_raked_wheelhouse_front_down_to_the_base():
    from vessel_reconstruction.ga_reader import end_contour

    # Lower face leans aft (x 21.0 -> 20.3 m), upper face leans forward (to 21.3 m): drawn in mm.
    entities = [{'id': 'upper', 'points': [[20300, 10150], [21300, 11500]]},
                {'id': 'lower', 'points': [[21000, 9100], [20300, 10150]]},
                {'id': 'roof', 'points': [[13500, 11500], [21300, 11500]]}]
    contour = end_contour(entities, profile_view(), 21.3, 11.5, 9.1)
    assert contour['points'] == [[9.1, 21.0], [10.15, 20.3], [11.5, 21.3]]
    assert contour['reached_base'] and contour['entity_ids'] == ['upper', 'lower']
    assert end_contour(entities, profile_view(), 13.0, 11.5, 9.1) is None


def test_profile_windows_keep_the_outer_frame_only():
    from vessel_reconstruction.ga_reader import profile_windows

    def box(name, x0, z0, x1, z1):
        return {'id': name, 'closed': True, 'points': [[x0, z0], [x1, z0], [x1, z1], [x0, z1], [x0, z0]]}

    entities = [box('outer', 14100, 10300, 15300, 11200), box('inner', 14150, 10350, 15250, 11150),
                box('door', 16000, 9100, 16800, 11100), box('tiny', 17000, 10500, 17100, 10600)]
    windows = profile_windows(entities, profile_view(), [13.0, 22.0], [9.0, 11.5])
    assert [w['entity_id'] for w in windows] == ['outer']


@pytest.mark.cad
def test_raked_end_rounded_corners_and_window_recesses_shape_a_deckhouse():
    box_outline = [[14.0, -3.5], [21.0, -3.5], [21.0, 3.5], [14.0, 3.5]]
    values = {'outline': box_outline, 'height': [9.0, 11.5]}
    plain, _ = build_shaped('wh', 'deckhouse', values, None)
    detail = {'end_fwd': {'value': [[9.0, 21.0], [11.5, 20.0]], 'source': 'traced', 'basis': 'profile'},
              'corner_radius_m': {'value': {'fwd': 1.0}, 'source': 'guessed', 'basis': 'test'},
              'windows': {'value': [[15.0, 16.0, 10.2, 11.1]], 'source': 'traced', 'basis': 'profile'},
              'window_recess_m': {'value': 0.05, 'source': 'guessed', 'basis': 'test'}}
    shaped, report = build_shaped('wh', 'deckhouse', values, None, detail)
    assert shaped.isValid()
    top = shaped.intersect(cq.Solid.makeBox(10, 10, 0.05, cq.Vector(12, -5, 11.4))).BoundingBox()
    assert top.xmax == pytest.approx(20.0, abs=0.05)  # the front leans aft by 1 m at the roof
    window = shaped.intersect(cq.Solid.makeBox(0.2, 0.2, 0.2, cq.Vector(15.4, 3.4, 10.5)))
    # The probe spans y 3.4 to 3.6 m; the wall face is at 3.5 m, recessed 0.05 m to 3.45 m.
    assert window.Volume() == pytest.approx(0.2 * 0.05 * 0.2, rel=0.02)
    corner = shaped.intersect(cq.Solid.makeBox(0.1, 0.5, 0.5, cq.Vector(20.85, 3.0, 9.0)))
    assert corner.Volume() < 0.1 * 0.5 * 0.5 * 0.5  # the forward corner is rounded off
    assert set(report['detail_used']) == {'end_fwd', 'corner_radius_m', 'windows', 'window_recess_m'}
    assert shaped.Volume() < plain.Volume()
