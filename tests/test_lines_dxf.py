"""DXF body-plan reading on synthetic drawings with known stations."""
from __future__ import annotations

import numpy as np
import pytest

ezdxf = pytest.importorskip("ezdxf")

from vessel_reconstruction import lines_dxf  # noqa: E402
from vessel_reconstruction.lines_dxf import (BodyPlanView, LinesDxfError, SideLine, StationRequest,  # noqa: E402
                                             chain_fragments, read_stations, resample_by_arc_length,
                                             single_valued_section)

# Drawing units are millimetres at full scale; the centreline is at X = 1000,
# the baseline at Y = 200, the half-breadth is 2 m.
CL, BASE, HALF = 1000.0, 200.0, 2000.0


def view(**overrides) -> BodyPlanView:
    fields = dict(centreline_x=CL, baseline_y=BASE, units_per_metre=1000.0,
                  bounds=(-1500.0, 0.0, 3500.0, 4000.0), layers=("FRAMES",),
                  flatten_tolerance=0.5, join_tolerance=1.0)
    fields.update(overrides)
    return BodyPlanView(**fields)


def station_curve(side: int, scale: float, top_z: float = 3.0, samples: int = 60) -> np.ndarray:
    """Round-bilge half-section from the keel to the top, in drawing units."""
    z = np.linspace(0.0, top_z, samples)
    y = scale * HALF / 1000.0 * np.sqrt(z / top_z)
    return np.column_stack([CL + side * y * 1000.0, BASE + z * 1000.0])


def write_dxf(path, curves: list[np.ndarray], layer: str = "FRAMES") -> None:
    doc = ezdxf.new("R2010")
    for curve in curves:
        doc.modelspace().add_lwpolyline(curve.tolist(), dxfattribs={"layer": layer})
    doc.saveas(path)


def test_chain_fragments_joins_one_to_one_and_stops_at_junctions():
    a = np.array([[0.0, 0.0], [1.0, 1.0]])
    b = np.array([[1.0, 1.0], [2.0, 3.0]])
    assert len(chain_fragments([a, b], 0.01)) == 1
    c = np.array([[1.0, 1.0], [3.0, 0.0]])
    # Three fragments meet at one point: a junction, so nothing is joined.
    assert len(chain_fragments([a, b, c], 0.01)) == 3


def test_single_valued_section_reduces_flat_bottom_and_refuses_reversal():
    flat_bottom = np.array([[0.0, 0.0], [0.5, 0.0], [1.0, 0.5], [1.2, 1.0]])
    section = single_valued_section(flat_bottom)
    assert section[0].tolist() == [0.5, 0.0]
    assert np.all(np.diff(section[:, 1]) > 0)
    skeg = np.array([[0.0, 0.5], [0.5, 0.0], [0.8, 0.4], [1.0, 1.0]])
    with pytest.raises(LinesDxfError) as caught:
        single_valued_section(skeg)
    assert caught.value.kind == "multi_valued_section"
    with pytest.raises(LinesDxfError) as caught:
        single_valued_section(np.array([[-0.1, 0.0], [1.0, 1.0]]))
    assert caught.value.kind == "crosses_centreline"


def test_resample_keeps_limit_and_increasing_height():
    z = np.linspace(0, 1, 3000)
    section = np.column_stack([np.sin(z), z])
    resampled = resample_by_arc_length(section)
    assert len(resampled) == lines_dxf.MAX_SECTION_POINTS
    assert np.all(np.diff(resampled[:, 1]) > 0)
    assert resampled[0].tolist() == section[0].tolist() and resampled[-1].tolist() == section[-1].tolist()


def test_read_stations_measures_known_curves_and_abstains(tmp_path):
    forward = station_curve(+1, 1.0)
    aft = station_curve(-1, 0.8)
    split = station_curve(+1, 0.5)
    # A station drawn in two entities that meet end to end must be joined.
    pieces = [split[:30], split[29:]]
    short = station_curve(+1, 0.3, top_z=1.0)  # stops before the side and the top
    path = tmp_path / "bodyplan.dxf"
    write_dxf(path, [forward, aft, *pieces, short])
    requests = [
        StationRequest("fwd", 10.0, +1, pick_xy=tuple(forward[45])),
        StationRequest("aft", 2.0, -1, pick_xy=tuple(aft[45])),
        StationRequest("joined", 8.0, +1, pick_xy=tuple(split[10]), extra_picks=(tuple(split[50]),)),
        StationRequest("two-pieces", 6.0, +1, pick_xy=tuple(forward[45]), extra_picks=(tuple(aft[45]),)),
        StationRequest("nothing-here", 4.0, +1, pick_xy=(3000.0, 3500.0)),
        StationRequest("short", 3.0, +1, pick_xy=tuple(short[30])),
    ]
    result = read_stations(path, view(), requests, side_line=SideLine(y_m=2.0, top_z_m=3.0))
    by_id = {s["id"]: s for s in result["sections"]}
    assert set(by_id) == {"fwd", "aft", "joined"}
    kinds = {a["id"]: a["kind"] for a in result["abstentions"]}
    assert kinds == {"two-pieces": "multiple_pieces", "nothing-here": "missing_curve", "short": "incomplete_curve"}
    for station_id, scale in (("fwd", 1.0), ("aft", 0.8), ("joined", 0.5)):
        points = np.array(by_id[station_id]["points_yz_m"])
        expected = scale * 2.0 * np.sqrt(points[:, 1] / 3.0)
        assert np.max(np.abs(points[:, 0] - expected)) < 1e-9
        assert points[0, 1] == pytest.approx(0.0) and points[-1, 1] == pytest.approx(3.0)


def test_side_line_is_followed_to_the_declared_top(tmp_path):
    curve = station_curve(+1, 1.0, top_z=2.0)  # ends on the side line (y = 2 m) at z = 2 m
    path = tmp_path / "bodyplan.dxf"
    write_dxf(path, [curve])
    result = read_stations(path, view(), [StationRequest("s", 1.0, +1, pick_xy=tuple(curve[30]))],
                           side_line=SideLine(y_m=2.0, top_z_m=3.5))
    points = np.array(result["sections"][0]["points_yz_m"])
    assert points[-1].tolist() == pytest.approx([2.0, 3.5])
    assert result["sections"][0]["evidence"]["side_line_followed"] is True


def test_ambiguous_pick_abstains(tmp_path):
    first = station_curve(+1, 1.0)
    second = first + [0.5, 0.0]  # half a drawing unit away
    path = tmp_path / "bodyplan.dxf"
    write_dxf(path, [first, second])
    result = read_stations(path, view(join_tolerance=0.1), [StationRequest("s", 1.0, +1, pick_xy=tuple(first[30]))],
                           pick_tolerance=5.0)
    assert result["abstentions"][0]["kind"] == "ambiguous_curve"


def test_invalid_view_is_refused():
    with pytest.raises(LinesDxfError):
        view(centreline_x=9000.0)
    with pytest.raises(LinesDxfError):
        view(units_per_metre=0.0)


def test_read_sections_build_a_valid_hull(tmp_path):
    curves = [station_curve(+1, scale) for scale in (0.6, 1.0, 0.7)]
    path = tmp_path / "bodyplan.dxf"
    write_dxf(path, curves)
    requests = [StationRequest(f"s{i}", float(i * 5), +1, pick_xy=tuple(c[45])) for i, c in enumerate(curves)]
    result = read_stations(path, view(), requests)
    assert not result["abstentions"]
    from vessel_reconstruction.geometry import build_hull

    shape, normalized = build_hull(result["sections"])
    assert shape.isValid() and len(normalized) == 3


def twin_skeg_curve(side: int = +1) -> np.ndarray:
    """A station from the centreline over a skeg to the side line, in drawing units.

    Half-plane (metres): tunnel roof at z = 1.0 from the centreline to y = 0.5,
    skeg from y = 0.5 to 1.0 down to z = 0, hull bottom at z = 1.0 to the side
    (y = 2.0), side line up to z = 2.0.
    """
    yz = np.array([[0.0, 1.0], [0.5, 1.0], [0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [2.0, 1.0], [2.0, 2.0]])
    return np.column_stack([CL + side * yz[:, 0] * 1000.0, BASE + yz[:, 1] * 1000.0])


def test_region_mode_reads_twin_skeg_and_split_bulb(tmp_path):
    from vessel_reconstruction import section_regions as sr

    skeg = twin_skeg_curve()
    bulb = np.array([[CL, BASE + 0.0], [CL + 600.0, BASE + 400.0], [CL, BASE + 800.0]])
    bow = np.array([[CL, BASE + 1200.0], [CL + 1500.0, BASE + 3000.0]])
    path = tmp_path / "bodyplan.dxf"
    write_dxf(path, [skeg, bulb, bow])
    requests = [StationRequest("skeg", 2.0, +1, pick_xy=tuple(skeg[3])),
                StationRequest("bulb", 9.0, +1, pick_xy=tuple(bulb[1]), extra_picks=(tuple(bow.mean(axis=0)),))]
    side = SideLine(y_m=2.0, top_z_m=3.0)
    single = read_stations(path, view(), requests, side_line=side)
    assert {a["kind"] for a in single["abstentions"]} == {"multi_valued_section", "multiple_pieces"}
    result = read_stations(path, view(), requests, side_line=side, regions=True)
    assert not result["abstentions"]
    by_id = {s["id"]: s for s in result["sections"]}

    def area(regions):
        return sr.total_area([{"rows_m": np.array(r["rows_m"])} for r in regions])

    skeg_regions = by_id["skeg"]["regions"]
    assert sorted(r["kind"] for r in skeg_regions) == ["centreline", "offset"]
    # Skeg 0.5 m x 1.0 m; hull 2.0 m wide from z = 1 m to the side-line top z = 3 m.
    assert area(skeg_regions) == pytest.approx(0.5 + 4.0)
    assert by_id["skeg"]["evidence"]["side_line_followed"] is True
    bulb_regions = by_id["bulb"]["regions"]
    assert [r["rows_m"][0][0] for r in bulb_regions] == pytest.approx([0.0, 1.2])
    # Bulb triangle 0.6 x 0.8 / 2; bow trapezoid from z = 1.2 to 3.0, closed at the top.
    assert area(bulb_regions) == pytest.approx(0.24 + 1.35)


def test_region_mode_uses_the_station_top_and_refuses_open_pieces(tmp_path):
    skeg = twin_skeg_curve()
    stub = np.array([[CL, BASE + 500.0], [CL + 700.0, BASE + 600.0]])  # ends nowhere
    path = tmp_path / "bodyplan.dxf"
    write_dxf(path, [skeg, stub])
    requests = [StationRequest("low-top", 1.0, +1, pick_xy=tuple(skeg[3]), top_z_m=2.5, top_evidence="profile"),
                StationRequest("stub", 2.0, +1, pick_xy=tuple(stub.mean(axis=0)))]
    result = read_stations(path, view(), requests, side_line=SideLine(y_m=2.0, top_z_m=3.0), regions=True)
    assert [a["kind"] for a in result["abstentions"]] == ["incomplete_curve"]
    section = result["sections"][0]
    assert max(r["rows_m"][-1][0] for r in section["regions"]) == pytest.approx(2.5)
    assert section["evidence"]["top_evidence"] == "profile"


def test_cross_view_identity_assigns_and_refuses_ambiguity():
    z = np.linspace(0, 2, 50)

    def curve(width):
        return np.column_stack([width * np.sqrt(z / 2), z])

    heights = (0.5, 1.0, 1.5)
    references = {name: {h: float(w * np.sqrt(h / 2)) for h in heights}
                  for name, w in (("A", 1.0), ("B", 1.5), ("C", 2.0))}
    assigned, ledger = lines_dxf.cross_view_identity({"k1": curve(1.01), "k2": curve(2.0), "k3": curve(1.75)},
                                                     references)
    assert assigned == {"k1": "A", "k2": "C"}
    decisions = {entry["curve"]: entry["decision"] for entry in ledger}
    assert decisions["k3"].startswith("refused")
    # Two curves that both fit one frame best are both refused.
    assigned, _ = lines_dxf.cross_view_identity({"k1": curve(1.0), "k2": curve(1.005)}, references)
    assert assigned == {}
