"""Profile cross-checks: the printed sheet scale, view lengths and the deck line as station tops.

Synthetic pixel sheets; no reference geometry is used.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import vessel_description as vd
from vessel_reconstruction.first_hull_tools import cap_tops_at_deck
from vessel_reconstruction.form_fit import Anchor

PPM, X0, BASE = 4.0, 20.0, 150.0  # Profile: 4 px/m, x = 0 at column 20, baseline at row 150.


def _deck_z(x):
    return 8.0 + 0.03 * x  # A rising sheer, metres.


def profile_sheet():
    """A 100 m hull outline: keel, transom, stem and a sheer line, with a station number above it."""
    image = Image.new("RGB", (460, 200), "white")
    draw = ImageDraw.Draw(image)
    xs = np.linspace(0, 100, 400)
    draw.line([(X0 + x * PPM, BASE - _deck_z(x) * PPM) for x in xs], fill=(15,) * 3, width=2)
    draw.line([(X0, BASE), (X0 + 100 * PPM, BASE)], fill=(15,) * 3, width=2)
    draw.line([(X0, BASE), (X0, BASE - _deck_z(0) * PPM)], fill=(15,) * 3, width=2)
    draw.line([(X0 + 100 * PPM, BASE), (X0 + 100 * PPM, BASE - _deck_z(100) * PPM)], fill=(15,) * 3, width=2)
    draw.text((X0 + 50 * PPM - 3, 30), "5", fill=(40,) * 3)
    setup = {"view": "profile", "view_id": "profile", "region_px": [10, 10, 450, 160],
             "pixels_per_metre": PPM, "grid_spacing_m": 10.0, "baseline_px": BASE, "x_origin_px": X0}
    return np.array(image), setup


def test_a_view_scale_that_disagrees_with_the_printed_scale_gets_the_printed_value():
    image, setup = profile_sheet()
    wrong = {**setup, "pixels_per_metre": 2.0}
    scales, warnings = vd.checked_scales(image, [wrong], {"dimension_text": "LOA 100.00 m; SCALE 1 m = 4.000 px"})
    assert scales["profile"] == 4.0
    assert warnings and warnings[0]["field"] == "views.profile.pixels_per_metre"
    assert warnings[0]["measured_value"] == 4.0 and "propose_sheet_setup" in warnings[0]["suggested_fix"]
    # Without a printed scale, the profile length over the printed LOA gives the likely scale.
    scales, warnings = vd.checked_scales(image, [wrong], {"dimension_text": "LOA 100.00 m"})
    assert abs(scales["profile"] - PPM) < 0.1 and warnings
    # An agreeing view has no warning.
    assert vd.checked_scales(image, [setup], {"dimension_text": "SCALE 1 m = 4 px"}) == ({"profile": 4.0}, [])


def test_profile_and_plan_lengths_are_compared():
    image, setup = profile_sheet()
    # The same outline read as a plan at half the scale: twice the length.
    plan = {**setup, "view": "plan", "view_id": "plan", "pixels_per_metre": PPM / 2, "centreline_px": 150.0}
    measured = vd.measure_description(image, {"units": "m", "sections": []}, {}, [setup, plan])
    readings = {r["view_id"]: r["value"] for r in measured["principal"]["loa"]["measurements"]}
    assert abs(readings["profile"] - 100) < 2 and abs(readings["plan"] - 200) < 4
    assert any(w["field"] == "principal.loa" and "plan" in w["suggested_fix"] for w in measured["warnings"])


def test_sheet_only_sections_use_the_printed_scale_over_a_disagreeing_setup():
    from vessel_reconstruction.materialize import read_scale
    image, _ = profile_sheet()
    setups = [{"pixels_per_metre": 18.0, "grid_spacing_m": 1.0}]
    warnings = []
    scale, basis = read_scale(image, setups, [], [], {"dimension_text": "SCALE 1 m = 19.000 px"}, [10, 10, 450, 160],
                              warnings)
    assert scale == 19.0 and "printed" in basis and warnings
    # An agreeing setup (within 2 %) keeps the model's reading.
    scale, _ = read_scale(image, [{"pixels_per_metre": 18.9}], [], [], {"dimension_text": "SCALE 1 m = 19 px"},
                          [10, 10, 450, 160], [])
    assert scale == 18.9


def test_model_station_positions_are_checked_against_the_profile_station_lines():
    image, setup = profile_sheet()
    picture = Image.fromarray(image)
    draw = ImageDraw.Draw(picture)
    for x in range(10, 100, 10):  # light full-height station lines, as on the factory sheets
        draw.line([(X0 + x * PPM, 10), (X0 + x * PPM, 159)], fill=(205,) * 3, width=1)
    image = np.array(picture)
    assert vd.profile_station_lines(image, setup, PPM) == [float(x) for x in range(10, 100, 10)]
    good = [{"id": str(i), "x_m": 10.0 * i + 0.2, "side": "aft"} for i in range(1, 10)]
    warnings = []
    assert vd.check_station_positions(image, [setup], {"stations": good}, warnings) == good and not warnings
    # One misread station: every station takes its measured line and keeps its id.
    shifted = [{**s, "x_m": 5.0} if s["id"] == "1" else s for s in good]
    fixed = vd.check_station_positions(image, [setup], {"stations": shifted}, warnings)
    assert [s["x_m"] for s in fixed] == [10.0 * i for i in range(1, 10)] and fixed[0]["side"] == "aft"
    # Ten stations spread over the LOA (series60 live run): the nine lines become the stations.
    spread = [{"id": str(i + 1), "x_m": 11.08 * i} for i in range(10)]
    fixed = vd.check_station_positions(image, [setup], {"stations": spread}, warnings)
    assert [s["id"] for s in fixed] == [str(i) for i in range(1, 10)] and len(warnings) == 2


def test_deck_heights_follow_the_sheer_and_skip_the_label():
    image, setup = profile_sheet()
    stations = [{"id": str(i), "x_m": 10.0 * i} for i in range(1, 10)]
    heights = vd.profile_deck_heights(image, setup, PPM, stations)
    assert set(heights) == {s["id"] for s in stations}
    for station in stations:
        assert abs(heights[station["id"]] - _deck_z(station["x_m"])) <= 1.0 / PPM


def test_light_station_lines_are_found_on_a_blurred_grey_scan():
    from PIL import ImageFilter
    image, setup = profile_sheet()
    picture = Image.fromarray(image)
    draw = ImageDraw.Draw(picture)
    for x in range(10, 100, 10):
        draw.line([(X0 + x * PPM, 10), (X0 + x * PPM, 159)], fill=(185,) * 3, width=1)
    # Grey paper (226) and blur: a light line ends only about 20 levels darker than the paper
    # (shipd-1-08158-3v-L1, where the sheet-wide ink level missed three of nine lines).
    grey = (np.asarray(picture.filter(ImageFilter.GaussianBlur(1.2))) * (226 / 255)).astype(np.uint8)
    measured = vd.profile_station_lines(grey, setup, PPM)
    assert len(measured) == 9 and max(abs(m - x) for m, x in zip(measured, range(10, 100, 10))) <= 0.5


def test_the_intake_profile_region_inside_the_model_region_is_measured():
    setup = {"view": "profile", "region_px": [60, 40, 2070, 320], "x_origin_px": 60.0}
    hints = [{"label": "profile", "region_px": [153, 132, 2064, 318]}]
    assert vd.profile_setup([setup], hints)["region_px"] == [153, 132, 2064, 318]
    # A model region that does not hold the intake's is kept (the intake may have cut the view short).
    other = {**setup, "region_px": [160, 120, 2070, 320]}
    assert vd.profile_setup([other], hints)["region_px"] == [160, 120, 2070, 320]


def test_a_baseline_on_another_grid_line_is_snapped_to_the_keel_line():
    image, setup = profile_sheet()
    wrong = {**setup, "baseline_px": BASE - 2 * PPM}  # the model took a waterline 2 m up (dtmb5415 live)
    stations = [{"id": "5", "x_m": 50.0}]
    heights = vd.profile_outline_heights(image, wrong, PPM, stations)["5"]
    assert abs(heights["deck"] - _deck_z(50.0)) <= 1.0 / PPM
    assert abs(heights["keel"]) <= 1.0 / PPM


def test_an_x_origin_on_the_region_edge_or_outside_it_is_the_hull_aft_end():
    image, setup = profile_sheet()
    assert vd.checked_x_origin(image, setup) == X0  # a read datum inside the view is kept
    for unread in (10.0, -100.0):  # the region's left edge (shipd-1-00679 live), a crop coordinate (dtmb5415)
        assert abs(vd.checked_x_origin(image, {**setup, "x_origin_px": unread}) - X0) <= 1.5


def test_sides_that_contradict_x_follow_x():
    from vessel_reconstruction.materialize import assign
    panel = {"region_px": [0, 0, 200, 100], "centreline_px": 100.0, "kind": "body"}
    # Numbered from the bow but placed from the stern (shipd-1-00679 live).
    stations = [{"id": str(i), "x_m": 10.0 * i, "side": "fore" if i <= 5 else "aft"} for i in range(1, 10)]
    warnings = []
    halves = {station["id"]: basis for station, _, _, basis in assign(stations, [panel], warnings)}
    assert halves["1"].startswith("aft") and halves["9"].startswith("fore") and warnings


def _gridded_sheet(angle_deg=0.0, with_plan=False):
    """profile_sheet with light waterlines (and a plan outline below it), rotated as a scan may be."""
    image, setup = profile_sheet()
    height = 300 if with_plan else image.shape[0]
    grid = Image.new("RGB", (image.shape[1], height), "white")
    draw = ImageDraw.Draw(grid)
    for z in range(0, 12):
        draw.line([(10, BASE - z * PPM), (450, BASE - z * PPM)], fill=(205,) * 3, width=1)
    if with_plan:  # a waterline curve of a half-breadth plan, 40 px below the profile
        draw.line([(X0, 230), (X0 + 50 * PPM, 200), (X0 + 100 * PPM, 230)], fill=(15,) * 3, width=2)
    sheet = np.array(grid)
    sheet[:image.shape[0]] = np.minimum(sheet[:image.shape[0]], image)  # the hull ink lies over the grid
    picture = Image.fromarray(sheet).rotate(angle_deg, resample=Image.BICUBIC, fillcolor="white")
    return np.array(picture), setup


def test_a_rotated_sheet_is_levelled_before_deck_and_keel_heights_are_read():
    image, setup = _gridded_sheet(angle_deg=0.3)
    # PIL turns the picture counter-clockwise: lines climb to the left, rows fall to the right.
    assert abs(vd.view_skew(image, setup["region_px"]) - np.tan(np.radians(-0.3))) < 0.0015
    stations = [{"id": str(i), "x_m": 10.0 * i} for i in range(1, 10)]
    heights = vd.profile_outline_heights(image, setup, PPM, stations)
    for station in stations:
        # Within 2 px: resampling the turned picture blurs line ends by about a pixel.
        assert abs(heights[station["id"]]["deck"] - _deck_z(station["x_m"])) <= 2.0 / PPM
        assert abs(heights[station["id"]]["keel"]) <= 2.0 / PPM
    assert vd.view_skew(_gridded_sheet()[0], setup["region_px"]) == 0.0


def test_a_region_over_two_views_reads_the_top_outline():
    image, setup = _gridded_sheet(with_plan=True)
    wide = {**setup, "region_px": [10, 10, 450, 290]}  # profile and plan (series60-3v-L2 live)
    heights = vd.profile_outline_heights(image, wide, PPM, [{"id": "5", "x_m": 50.0}])["5"]
    assert abs(heights["deck"] - _deck_z(50.0)) <= 1.0 / PPM and abs(heights["keel"]) <= 1.0 / PPM


def test_a_trace_that_stops_far_below_the_deck_is_left_to_the_fit():
    from vessel_reconstruction.first_hull_tools import short_of_deck
    anchors = [_anchor("1", 9.0), _anchor("2", 9.0), _anchor("3", 4.0)]
    assert short_of_deck(anchors, {"1": 9.0, "2": 9.0, "3": 9.0}) == ["3"]


def test_a_trace_that_runs_down_the_centreline_below_the_keel_is_cut_there():
    from vessel_reconstruction.first_hull_tools import cut_bottoms_at_keel
    anchors = [_anchor("1", 9.0), _anchor("2", 9.0), _anchor("3", 9.0)]
    for anchor in anchors:
        anchor.points_yz_m = [[y, z + 2.0] for y, z in anchor.points_yz_m]  # keel at z 2 m
    anchors[1].points_yz_m = [[0.0, 0.0]] + anchors[1].points_yz_m  # station 2 runs on down to z 0
    cut_bottoms_at_keel(anchors, {"1": 2.0, "2": 2.0, "3": 2.0})
    assert [round(min(p[1] for p in a.points_yz_m), 6) for a in anchors] == [2.0, 2.0, 2.0]
    assert anchors[1].notes and not anchors[0].notes


def _anchor(sid, top):
    z = np.linspace(0.0, top, 30)
    return Anchor(sid, float(sid), [[3.0 * np.sqrt(v / top), v] for v in z], {}, z_max_m=12.0,
                  pixels_per_metre=19.0, stroke_width_px=3.0)


def test_a_top_that_runs_above_the_deck_line_is_cut_there():
    anchors = [_anchor("1", 9.0), _anchor("2", 9.6), _anchor("3", 9.05)]
    decks = {"1": 9.0, "2": 9.1, "3": 9.0, "4": 9.2}
    sections = [{"id": sid, "z_min_m": 0.0, "z_max_m": 12.0} for sid in ("1", "2", "3", "4")]
    capped = cap_tops_at_deck(sections, anchors, decks)
    tops = {a.id: round(max(p[1] for p in a.points_yz_m), 6) for a in anchors}
    assert tops == {"1": 9.0, "2": 9.1, "3": 9.05}  # Only the overshooting top is cut.
    assert anchors[1].notes and anchors[1].stroke_width_px is None
    assert [s["z_max_m"] for s in capped] == [9.0, 9.1, 9.0, 9.2]


def test_a_deck_line_that_disagrees_with_most_tops_is_not_used():
    anchors = [_anchor("1", 9.0), _anchor("2", 9.6)]
    sections = [{"id": "1", "z_min_m": 0.0, "z_max_m": 12.0}, {"id": "2", "z_min_m": 0.0, "z_max_m": 12.0}]
    assert cap_tops_at_deck(sections, anchors, {"1": 4.0, "2": 4.2}) == sections
    assert max(p[1] for p in anchors[1].points_yz_m) == 9.6
