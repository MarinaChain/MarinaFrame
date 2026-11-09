"""Synthetic tests for the Gunnerus internals reader (no licensed drawing)."""
import numpy as np
import pytest

from benchmarks.gunnerus import whole_vessel_internals as internals


def box_mesh(x0, x1, y0, y1, z0, z1):
    """A closed box as triangles (metres)."""
    v = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = [(a, b, c) for a, b, c, d in quads] + [(a, c, d) for a, b, c, d in quads]
    return v[np.array(tris)]


def test_frame_index_counts_lettered_frames_after_27():
    assert internals.frame_x_m('0') == 0.0
    assert internals.frame_x_m('27') == 13.5
    assert internals.frame_x_m('A') == 14.0
    assert internals.frame_x_m('J') == 18.5
    assert internals.frame_x_m('28') == 19.0
    assert internals.frame_x_m('-2') == -1.0
    assert internals.frame_x_m('Hold') is None


def test_frame_calibration_snaps_the_label_estimate_to_the_line_grid():
    # Labels printed 74 mm left of their frame line; lines on a grid with phase 79.
    texts = [(5005.0 + 500 * k, 1000.0, str(k)) for k in range(0, 28)]
    lines = [5079.0 + 500 * k for k in (18, 22, 30)]
    assert internals.calibrate_frames(texts, lines) == pytest.approx(5079.0)


def test_hull_slicer_area_of_a_box_inside_ranges():
    slicer = internals.HullSlicer(box_mesh(0, 10, -2, 2, 0, 3))
    area, outline = internals.clipped_outline(slicer, 5.0, (-1.0, 5.0), (0.5, 2.5), internals.OUTLINE_DZ_M)
    assert area == pytest.approx(3.0 * 2.0, rel=1e-3)
    assert outline is not None
    plate = internals.plate_part(slicer, 5.0, (0.0, 3.0), 0.01)
    assert plate[0][0] == pytest.approx(4.995) and plate[0][1] == pytest.approx(5.005)


def test_cross_marks_give_boxes_and_tell_rectangles_from_curved_sides():
    def line(a, b):
        return {'layer': 'S0PH1', 'points': [list(a), list(b)], 'id': 'x'}
    entities = [line((0, 0), (1000, 500)), line((0, 500), (1000, 0)),  # rectangle
                line((2000, 0), (3000, 600)), line((2000, 500), (3000, 100)),  # one corner on a curve
                line((5000, 0), (5100, 900))]  # too narrow to be a cross diagonal
    boxes = internals.cross_boxes(entities, (-10, -10, 9000, 9000))
    assert boxes == [(0, 0, 1000, 500, True), (2000, 0, 3000, 600, False)]


def test_tank_top_gap_between_equal_levels_is_bridged_as_a_guess():
    tops = [{'z_m': 1.8, 'x_m': [21.0, 26.5], 'source': 'traced', 'evidence': 'a'},
            {'z_m': 1.8, 'x_m': [29.0, 30.5], 'source': 'traced', 'evidence': 'b'},
            {'z_m': 1.25, 'x_m': [8.0, 17.0], 'source': 'traced', 'evidence': 'c'},
            {'z_m': 1.45, 'x_m': [17.0, 21.0], 'source': 'traced', 'evidence': 'd'}]
    bridged = internals.bridge_tank_top_gaps(tops)
    gap = [t for t in bridged if t['source'] == 'guessed']
    assert len(gap) == 1 and gap[0]['x_m'] == [26.5, 29.0] and gap[0]['z_m'] == 1.8


def test_profile_floor_is_measured_from_the_deck_line():
    profile = internals.Profile(frame0_x=0.0, deck_runs=[(0.0, 20000.0, 10000.0)],
                                floors=[(8500.0, 4000.0, 5500.0, 'a'), (7000.0, 4000.0, 6000.0, 'b'),
                                        (9900.0, 4000.0, 6000.0, 'too close to the deck')])
    assert profile.floor_z(4.5, 4.2) == pytest.approx(2.7)
    assert profile.floor_z(5.8, 4.2) == pytest.approx(1.2)
    assert profile.floor_z(7.0, 4.2) is None


def test_bulkhead_lines_need_a_low_foot_and_the_deck():
    deck_y, frame0 = 10000.0, 0.0
    verticals = [(4000.0, 5900.0, 10000.0, 'a'), (4060.0, 5900.0, 10000.0, 'b'),  # one bulkhead, two lines
                 (5500.0, 8500.0, 10000.0, 'c'),  # platform wall: foot too high
                 (14000.0, 6000.0, 12000.0, 'd'),  # through the deck
                 (17000.0, 5900.0, 8000.0, 'e')]  # stops below the deck
    found = internals.bulkhead_lines(verticals, frame0, deck_y, 4200.0)
    assert [x for x, _ in found] == [4.0, 14.0]


def test_label_matches_numbers_names_and_spelling():
    row = internals.TankRow('No 11sb', 'FO Service tank', ('17', '20'), 2.21)
    assert internals.label_matches('No 11sb FO', row)
    assert not internals.label_matches('No 11p FO', row)
    grey = internals.TankRow(None, 'Gray water new', ('A', 'E'), None)
    assert internals.label_matches('Grey water New', grey)
    hold = internals.TankRow('Hold', 'Cargo hold aft', ('2', '8'), 42.45)
    assert internals.label_matches('Cargo hold', hold)


def test_tank_table_rows_by_column():
    texts = [(100, 1000, 'No'), (300, 1000, 'Name'), (600, 1010, 'Area of location, fr.'),
             (900, 1000, 'Net volume, m³'), (1200, 1000, 'Mass, t'),
             (100, 750, 'Water ballast ρ = 1.025 t/m³'),
             (100, 500, 'No 1'), (300, 500, 'Dbb water ballast'), (600, 500, '48...51'), (900, 500, '5.64'),
             (1200, 500, '5.78'),
             (300, 0, 'Total water ballast'), (900, 0, '62.30'), (1200, 0, '64.73'),
             (100, -250, 'MISC'),
             (300, -500, 'New fuel oil tank'), (600, -500, 'A...I'), (900, -500, '8.00'), (1200, -500, '7.20')]
    rows = internals.read_tank_table(texts)
    assert [(r.number, r.frames, r.volume_m3, r.group, r.density_t_m3) for r in rows] == [
        ('No 1', ('48', '51'), 5.64, 'water ballast', 1.025), (None, ('A', 'I'), 8.0, 'misc', 0.9)]
    totals = internals.read_table_totals(texts)
    assert totals == {'water ballast': {'volume_m3': 62.3, 'mass_t': 64.73}}


def test_full_label_match_wins_over_a_shortened_name():
    row = internals.TankRow(None, 'Black water new', ('A', 'E'), None)
    assert internals.label_match_quality('Black water New', row) == 2
    assert internals.label_match_quality('Black water', row) == 1
