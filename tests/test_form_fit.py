"""Vessel table and anchored form fit (W19a), without CAD, images from disk or a model."""
import copy

import numpy as np
import pytest

from vessel_reconstruction import form_fit as F
from vessel_reconstruction.draft import check_draft
from vessel_reconstruction.section_authoring import check_authored
from vessel_reconstruction.vessel_model import StationRow, VesselTable, build_spec

STATIONS = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0]
DEPTH = 10.0
PPM = 40.0


def hull_breadth(x: float) -> float:
    """Half-breadth scale of a smooth synthetic hull: full midbody, fine ends."""
    return 6.0 * (1.0 - ((x - 50.0) / 55.0) ** 4)


def hull_keel(x: float) -> float:
    return 0.2 + 0.4 * ((x - 60.0) / 50.0) ** 2


def hull_section(x: float, samples: int = 120) -> list:
    """A form-family section of the synthetic hull, from keel to deck."""
    keel = hull_keel(x)
    z = np.linspace(keel, DEPTH, samples)
    eta = (z - keel) / (DEPTH - keel)
    y = hull_breadth(x) * F.section_shape(eta, 3.0, 0.05)
    return np.column_stack([y, z]).tolist()


def declared(ids=None) -> list[dict]:
    sections = []
    for index, x in enumerate(STATIONS):
        sid = f"s{index + 1:02d}"
        if ids is None or sid in ids:
            sections.append({"id": sid, "x_m": x, "z_min_m": 0.0, "z_max_m": DEPTH,
                             "roi_px": [0, 0, 400, 450],
                             "calibration": {"centerline_px": 10.0, "baseline_px": 440.0, "pixels_per_metre": PPM}})
    return sections


def anchor(sid: str, x: float, points, **extra) -> F.Anchor:
    section = {"id": sid, "x_m": x, "z_min_m": 0.0, "z_max_m": DEPTH,
               "contour_selection": {"anchors_px": [[50.0, 10.0], [60.0, 400.0]], "half_width_px": 2.75},
               "roi_px": [0, 0, 400, 450],
               "calibration": {"centerline_px": 10.0, "baseline_px": 440.0, "pixels_per_metre": PPM}}
    return F.Anchor(id=sid, x_m=x, points_yz_m=points, selection_section=section, z_max_m=DEPTH,
                    pixels_per_metre=PPM, **extra)


def synthetic_anchors(skip=()) -> list[F.Anchor]:
    return [anchor(f"s{i + 1:02d}", x, hull_section(x)) for i, x in enumerate(STATIONS)
            if f"s{i + 1:02d}" not in skip]


def breadth_error(points, x: float) -> float:
    """RMS half-breadth difference to the synthetic hull over its height (as the factory scorer)."""
    truth = np.asarray(hull_section(x))
    points = np.asarray(points)
    z = np.linspace(truth[0, 1] + 0.1, DEPTH - 0.1, 50)
    error = np.interp(z, points[:, 1], points[:, 0]) - np.interp(z, truth[:, 1], truth[:, 0])
    return float(np.sqrt(np.mean(error ** 2)))


def test_anchors_stay_exact_and_gaps_are_filled_close_to_the_hull():
    anchors = synthetic_anchors(skip=("s03", "s06"))
    originals = {a.id: copy.deepcopy(a.points_yz_m) for a in anchors}
    table = F.fit_vessel(declared(), anchors)
    assert [row.id for row in table.stations] == [s["id"] for s in declared()]
    for row in table.stations:
        if row.id in originals:
            assert row.source == "traced" and row.locked
            assert row.points_yz_m == sorted(originals[row.id], key=lambda p: p[1])
        else:
            assert row.source == "fitted" and not row.locked
            assert breadth_error(row.points_yz_m, row.x_m) < 0.02 * 6.0
    assert len(table.trend["coefficients"]["breadth"]) == F.TREND_COEFFICIENTS
    assert sum(len(v) for v in table.trend["coefficients"].values()) == 30


def test_fill_follows_the_trend_better_than_a_straight_blend():
    """At a station between two anchors the fit adds the hull's curvature along x."""
    anchors = synthetic_anchors(skip=("s02",))
    table = F.fit_vessel(declared(), anchors)
    fitted = table.row("s02")
    blend = 0.5 * (np.asarray(hull_section(10.0)) + np.asarray(hull_section(30.0)))
    assert breadth_error(fitted.points_yz_m, 20.0) <= breadth_error(blend.tolist(), 20.0) + 1e-6


def test_wrong_stroke_and_straight_line_are_dropped_and_filled():
    anchors = synthetic_anchors()
    anchors[4].points_yz_m = (np.asarray(hull_section(50.0)) * [2.2, 1.0]).tolist()  # far too wide
    anchors[6].points_yz_m = [[4.0, z] for z in np.linspace(0.0, DEPTH, 50)]  # a grid line
    table = F.fit_vessel(declared(), anchors)
    dropped = {d["section_id"] for d in table.trend["dropped"]}
    assert dropped == {"s05", "s07"}
    assert table.row("s05").source == "fitted" and table.row("s07").source == "fitted"
    assert breadth_error(table.row("s05").points_yz_m, 50.0) < 0.02 * 6.0
    assert any(w["kind"] == "anchor_dropped" for w in table.warnings)


def test_free_top_end_moves_down_half_a_stroke_width():
    anchors = synthetic_anchors()
    low_top = [[y, z] for y, z in hull_section(50.0) if z <= 8.0]
    anchors[4] = anchor("s05", 50.0, low_top, stroke_width_px=4.0)
    top = max(z for _, z in low_top)
    F.check_tops(anchors)
    assert max(z for _, z in anchors[4].points_yz_m) == pytest.approx(top - 2.0 / PPM, abs=1e-9)


def test_vertical_run_to_the_panel_top_is_cut_when_the_neighbour_ends_lower():
    anchors = synthetic_anchors()
    for item in anchors[6:8]:  # s07, s08 end at 8 m: a sheer below the panel top
        item.points_yz_m = [[y, z] for y, z in item.points_yz_m if z <= 8.0]
    bow = [[y, z] for y, z in hull_section(90.0) if z <= 8.5]
    grid = bow[-1][0] + 0.1  # the hull ends 4 px inside a buttock grid line
    bow += [[grid, z] for z in np.linspace(8.6, DEPTH, 15)]
    anchors[8].points_yz_m = bow
    F.check_tops(anchors)
    assert max(z for _, z in anchors[8].points_yz_m) == pytest.approx(8.6, abs=1e-6)


def test_wall_sided_tops_at_the_panel_top_are_kept():
    anchors = synthetic_anchors()
    tops_before = [max(z for _, z in a.points_yz_m) for a in anchors]
    F.check_tops(anchors)
    assert [max(z for _, z in a.points_yz_m) for a in anchors] == tops_before


def test_flat_inward_ink_at_the_top_is_cut_and_the_side_continued():
    anchors = synthetic_anchors()
    side = [[y, z] for y, z in hull_section(50.0) if z <= 9.8]
    label = [[side[-1][0] - 1.0, 9.85], [side[-1][0] - 2.5, 9.9], [side[-1][0] - 2.5, DEPTH]]
    anchors[4].points_yz_m = side + label
    F.check_tops(anchors)
    points = np.asarray(anchors[4].points_yz_m)
    assert anchors[4].extended
    assert points[-1, 1] == pytest.approx(DEPTH) and points[-1, 0] == pytest.approx(side[-1][0])
    table = F.fit_vessel(declared(), anchors)
    assert table.row("s05").source == "fitted"  # built as a curve, not from the contour selection


def test_build_spec_keeps_ink_selection_and_builds_fitted_rows_as_curves():
    anchors = synthetic_anchors(skip=("s04",))
    table = F.fit_vessel(declared(), anchors)
    table.row("s02").top_z_m = 9.5
    base = {"source": {"file": "drawing.png"}, "sections": [a.selection_section for a in anchors],
            "draft": {"status": "draft_not_verified", "guesses": []}}
    spec = build_spec(table, base, declared())
    by_id = {s["id"]: s for s in spec["sections"]}
    assert set(by_id) == {s["id"] for s in declared()}
    assert "contour_selection" in by_id["s02"] and by_id["s02"]["z_max_m"] == 9.5
    fitted = by_id["s04"]
    assert "contour_selection" not in fitted and fitted["authored"]["source_label"] == "interpolated"
    assert check_authored(fitted["authored"], table_fit=True)
    assert check_draft(spec["draft"])
    guess = next(g for g in spec["draft"]["guesses"] if g["section_id"] == "s04")
    assert guess["kind"] == "bridged_gap" and guess["x_range_m"] == [30.0, 50.0]


def test_first_hull_leaves_out_a_suspect_anchor_after_a_failed_build():
    anchors = synthetic_anchors()
    anchors[4].points_yz_m = (np.asarray(hull_section(50.0)) * [1.3, 1.0]).tolist()  # suspect, not dropped
    base = {"source": {"file": "drawing.png"}, "sections": [a.selection_section for a in anchors]}
    builds = []

    def build(spec):
        builds.append(spec)
        return len(builds) > 1  # The first build fails.

    table, result, left_out = F.first_hull(declared(), anchors, base, build)
    assert result and len(builds) == 2
    assert left_out == [F.suspect_order(anchors)[0]]
    assert table.row(left_out[0]).source == "fitted"
    assert anchors[4].points_yz_m == (np.asarray(hull_section(50.0)) * [1.3, 1.0]).tolist()  # inputs unchanged


def test_first_hull_without_anchors_returns_no_table():
    table, result, left_out = F.first_hull(declared(), [], {"sections": []}, lambda spec: True)
    assert table is None and not result and left_out == []


def test_stroke_width_is_measured_across_the_curve():
    image = np.full((450, 400), 255, dtype=np.uint8)
    points = hull_section(50.0)
    for y, z in points:
        col, row = 10.0 + y * PPM, 440.0 - z * PPM
        image[int(round(row)), int(round(col)) - 1:int(round(col)) + 2] = 40  # 3 px wide
    width = F.measure_stroke_width_px(image, points, declared()[0]["calibration"])
    assert width == pytest.approx(3.0, abs=0.6)


def test_table_cells_and_json_round_trip():
    rows = [StationRow(id="a", x_m=0.0, points_yz_m=[[0.0, 0.0], [2.0, 2.0]], source="traced"),
            StationRow(id="b", x_m=1.0, points_yz_m=[[0.0, 1.0], [1.0, 2.0]], source="fitted")]
    table = VesselTable(rows, [0.0, 1.0, 2.0])
    cells = table.cells()
    assert cells[0].tolist() == [0.0, 1.0, 2.0]
    assert np.isnan(cells[1, 0]) and cells[1, 2] == 1.0
    again = VesselTable.from_json(table.to_json())
    assert again.sources() == {"a": "traced", "b": "fitted"}
    with pytest.raises(ValueError):
        StationRow(id="c", x_m=0.0, points_yz_m=[[0.0, 0.0], [1.0, 1.0]], source="guessed")


def test_interpolated_label_only_for_form_fit_sections():
    """A model-authored section cannot pass as interpolated: the label needs a form-fit guess."""
    from vessel_reconstruction.schema import _table_fit_section_ids
    from vessel_reconstruction.section_authoring import check_authored

    authored = {"source_label": "interpolated", "basis": "form fit",
                "points_yz_m": [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [2.5, 3.0], [2.6, 4.0]]}
    assert not check_authored(authored)
    assert check_authored(authored, table_fit=True)
    spec = {"draft": {"guesses": [{"section_id": "s02", "kind": "bridged_gap"},
                                  {"section_id": "s03", "kind": "model_authored"}]}}
    assert _table_fit_section_ids(spec) == {"s02"}
