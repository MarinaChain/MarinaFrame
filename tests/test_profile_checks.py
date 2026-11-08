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
