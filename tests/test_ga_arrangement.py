"""GA reading with extents -> estimated hull and arrangement (src/vessel_reconstruction/ga_arrangement.py).

The fixture is a made-up ship (TEST DATA, tests/fixtures/ga_arrangement_synthetic.json), not a
reading of any drawing.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from vessel_reconstruction import ga_arrangement as G

FIXTURE = Path(__file__).parent / "fixtures" / "ga_arrangement_synthetic.json"


@pytest.fixture
def reading() -> dict:
    return json.loads(FIXTURE.read_text())


def test_frame_to_m_integrates_the_spacing_table():
    spacings = [{"from_frame": 0, "to_frame": 10, "spacing_mm": 600},
                {"from_frame": 10, "to_frame": 40, "spacing_mm": 800}]
    assert G.frame_to_m(0, spacings) == 0.0
    assert G.frame_to_m(10, spacings) == pytest.approx(6.0)
    assert G.frame_to_m(20, spacings) == pytest.approx(14.0)
    assert G.frame_to_m(10.5, spacings) == pytest.approx(6.4)
    # Outside the table: the nearest span's spacing; aft of frame 0 is negative.
    assert G.frame_to_m(45, spacings) == pytest.approx(6.0 + 35 * 0.8)
    assert G.frame_to_m(-2, spacings) == pytest.approx(-1.2)


def test_frame_to_m_needs_a_table():
    with pytest.raises(G.InputError):
        G.frame_to_m(5, [])


def test_load_input_keeps_items_with_extents_and_lists_the_rest(reading):
    data = G.load_input(reading)
    assert data.test_fixture is True
    assert {item.id for item in data.items} >= {"cargo_hold-001", "cargo_crane-001"}
    assert data.skipped == [{"id": "other_space-001", "label": "BOSUN STORE", "reason": "no extent"}]


@pytest.mark.parametrize("change, message", [
    (lambda r: r.update(schema="other"), "schema"),
    (lambda r: r.update(engineering_approved=True), "engineering_approved"),
    (lambda r: r["particulars"].pop("breadth_m"), "breadth_m"),
    (lambda r: r["spaces"][0]["extent"].update(side="middle"), "side"),
    (lambda r: r["spaces"][0]["extent"].update(status={"x": "approved"}), "status"),
])
def test_load_input_refuses_unusable_input(reading, change, message):
    change(reading)
    with pytest.raises(G.InputError, match=message):
        G.load_input(reading)


def test_unknown_kind_is_skipped_not_built(reading):
    reading["spaces"][0]["kind"] = "lifeboat"
    data = G.load_input(reading)
    assert "engine_room-001" not in {item.id for item in data.items}
    assert data.skipped[0]["reason"] == "kind 'lifeboat' is not built"


def test_measured_from_scale_counts_as_a_value(reading):
    reading["particulars"]["breadth_m"]["status"] = G.MEASURED
    reading["spaces"][3]["extent"]["status"] = {"x": G.MEASURED, "y": G.MEASURED}
    data = G.load_input(reading)
    assert data.value("breadth_m") == 18.0
    tank = next(item for item in data.items if item.id == "ballast_tank-001")
    assert G.item_box(tank, data, G.hull_size(data)).guessed == []


def test_hull_size_from_loa_and_lbp(reading):
    size = G.hull_size(G.load_input(reading))
    assert size.x_fwd_m - size.x_aft_m == pytest.approx(104.0)
    assert size.x_aft_m == pytest.approx(-1.6)
    assert size.half_beam_m == 9.0 and size.depth_m == 9.0


def test_hull_size_guesses_overhang_from_lbp_alone(reading):
    del reading["particulars"]["loa_m"]
    size = G.hull_size(G.load_input(reading))
    assert size.x_fwd_m - size.x_aft_m == pytest.approx(104.0)
    assert size.basis["ends"].startswith("guessed")


def test_hull_table_is_prior_form_inside_breadth_and_depth(reading):
    table, size = G.hull_table(G.load_input(reading))
    assert all(row.source == "prior" for row in table.stations)
    assert table.trend["label"] == G.HULL_LABEL
    widths = [max(p[0] for p in row.points_yz_m) for row in table.stations]
    assert max(widths) == pytest.approx(9.0)
    assert min(widths) >= G.MIN_BREADTH_SHARE * 9.0 - 1e-9
    assert all(row.top_z_m == pytest.approx(9.0) for row in table.stations)
    # Full sections in the parallel body, fine ones at the stem.
    middle = table.stations[len(table.stations) // 2]
    bottom_half_breadth = middle.points_yz_m[0][0]
    assert bottom_half_breadth > 0.7 * 9.0
    assert table.stations[-1].points_yz_m[0][0] < 0.1 * 9.0


def test_hull_table_follows_a_read_deck_outline(reading):
    reading["hull_outline"] = {"deck_half_breadth_m": [[-1.6, 7.0], [20.0, 9.0], [80.0, 9.0], [102.4, 0.0]]}
    table, size = G.hull_table(G.load_input(reading))
    first = table.stations[0]
    assert max(p[0] for p in first.points_yz_m) == pytest.approx(7.0)


def test_item_box_reads_frames_and_marks_rules_as_guessed(reading):
    data = G.load_input(reading)
    size = G.hull_size(data)
    items = {item.id: item for item in data.items}
    engine = G.item_box(items["engine_room-001"], data, size)
    assert engine.x == pytest.approx((8 * 0.6, 20 * 0.6 + 6 * 0.7))
    assert engine.status == {"x": "read", "y": "guessed", "z": "read"}
    assert engine.basis["y"] == "full breadth inside the hull"
    house = G.item_box(items["accommodation_deck-001"], data, size)
    assert house.z == pytest.approx((9.0, 9.0 + G.TIER_HEIGHT_M))
    assert house.y == pytest.approx((-8.0, 8.0))
    assert house.guessed == ["y", "z"]
    tank = G.item_box(items["ballast_tank-001"], data, size)
    assert tank.guessed == []


def test_check_boxes_finds_overlaps_and_items_off_the_hull(reading):
    reading["spaces"][2]["extent"]["x_m"] = [45.0, 88.0]
    reading["spaces"][0]["extent"] = {"x_m": [-20.0, -10.0]}
    data = G.load_input(reading)
    size = G.hull_size(data)
    items = {item.id: item for item in data.items}
    boxes = {item_id: G.item_box(item, data, size) for item_id, item in items.items()}
    findings = G.check_boxes(boxes, items, size)
    assert any("overlap by 5.0 m" in text for text in findings)
    assert any("engine_room-001" in text and "outside the hull length" in text for text in findings)


def test_check_proportions_flags_a_misread_dimension(reading):
    assert G.check_proportions(G.hull_size(G.load_input(reading))) == []
    reading["particulars"]["depth_m"]["value"] = 3.0
    findings = G.check_proportions(G.hull_size(G.load_input(reading)))
    assert findings == ["B/D = 6.00 is outside 1.2..2.6: check the dimensions"]


def _boxes(data):
    size = G.hull_size(data)
    return {item.id: G.item_box(item, data, size) for item in data.items}


def test_check_depth_against_the_cargo_space_tops(reading):
    data = G.load_input(reading)
    assert G.check_depth(data, _boxes(data)) == []
    # A depth measured to another deck (here 0.7 m higher) disagrees with the holds' top.
    reading["particulars"]["depth_m"].update(value=9.7, uncertainty_m=0.29)
    data = G.load_input(reading)
    assert G.check_depth(data, _boxes(data)) == [
        "depth 9.70 m disagrees with the cargo spaces' top 9.00 m by more than 0.30 m"]
    # Within the stated uncertainty it passes.
    reading["particulars"]["depth_m"]["uncertainty_m"] = 0.8
    data = G.load_input(reading)
    assert G.check_depth(data, _boxes(data)) == []


def test_a_derived_depth_is_used_as_an_estimate_and_never_checked_against_itself(reading):
    reading["particulars"]["depth_m"].update(value=9.7, status="derived_from_space_tops")
    data = G.load_input(reading)
    assert data.value("depth_m") == 9.7
    assert data.estimated() == ["depth_m (derived_from_space_tops)"]
    assert G.check_depth(data, _boxes(data)) == []
    from benchmarks.ga_arrangement.run_folder import hull_record

    assert "not taken from the drawing: depth_m (derived_from_space_tops)" in hull_record(data)["method"]


def test_an_unknown_depth_is_refused(reading):
    reading["particulars"]["depth_m"] = {"value": None, "status": "unknown", "reason": "not found"}
    with pytest.raises(G.InputError, match="depth_m"):
        G.load_input(reading)


def test_hull_aft_end_follows_the_aftmost_item(reading):
    reading["spaces"][4]["extent"]["frames"] = [-6, 24]  # deckhouse reaching 3.6 m aft of the AP
    size = G.hull_size(G.load_input(reading))
    assert size.x_aft_m == pytest.approx(-3.6)
    assert size.x_fwd_m - size.x_aft_m == pytest.approx(104.0)
    assert "aftmost item" in size.basis["ends"]
    # Never further aft than the whole overhang (LOA - LBP = 4 m): the bow stays at or past the FP.
    reading["spaces"][4]["extent"]["frames"] = [-12, 24]
    assert G.hull_size(G.load_input(reading)).x_aft_m == pytest.approx(-4.0)


def test_a_space_above_the_deck_is_not_cut_by_the_hull(reading):
    data = G.load_input(reading)
    size = G.hull_size(data)
    store = G.Box((90.0, 98.0), (-3.0, 3.0), (8.8, 11.5), {"x": "read", "y": "read", "z": "read"})
    hold = G.Box((50.0, 88.0), (-9.0, 9.0), (1.2, 9.0), {"x": "read", "y": "guessed", "z": "read"})
    assert G.above_deck(store, size) and not G.above_deck(hold, size)


def test_carve_order_puts_small_tanks_before_holds(reading):
    data = G.load_input(reading)
    size = G.hull_size(data)
    items = {item.id: item for item in data.items}
    boxes = {item_id: G.item_box(item, data, size) for item_id, item in items.items()}
    order = G.carve_order(boxes, items)
    assert order.index("ballast_tank-001") < order.index("cargo_hold-002")
    assert "cargo_crane-001" not in order


def test_build_and_run_folder(reading, tmp_path):
    cadquery = pytest.importorskip("cadquery")  # noqa: F841 - the CAD worker's dependency
    from benchmarks.ga_arrangement import ESTIMATE_LABEL, POLICY
    from benchmarks.ga_arrangement.run_folder import generate

    image = tmp_path / "synthetic-ga.png"
    from PIL import Image

    Image.new("RGB", (1000, 600), "white").save(image)
    result = generate(copy.deepcopy(reading), image, tmp_path / "out", "synthetic-test", "SYNTHETIC-1 (TEST DATA)")
    task = Path(result["task"])
    state = json.loads((task / "state.json").read_text())["state"]
    assert state["config"]["policy"] == POLICY and state["engineering_approved"] is False
    presentation = json.loads((task / "presentation.json").read_text())
    assert presentation["credit"] == ESTIMATE_LABEL and len(ESTIMATE_LABEL) <= 300
    execution = json.loads((task / "whole_vessel" / "execution.json").read_text())["result"]
    components = {entry["id"]: entry for entry in execution["components"]}
    assert components["hull"]["label"] == G.HULL_LABEL
    assert components["hull"]["source_record"]["kind"] == "guessed"
    # Every part points at the GA; a part with a guessed extent has a guessed record.
    for entry in components.values():
        record = entry["source_record"]
        regions = record.get("regions") or record.get("inputs")
        assert regions and all(region["sheet"] == "synthetic-ga.png" for region in regions)
        assert entry["engineering_approved"] is False
    assert components["ballast_tank-001"]["source_record"]["kind"] == "read"
    assert components["cargo_hold-002"]["source_record"]["kind"] == "guessed"
    assert "full breadth" in components["cargo_hold-002"]["source_record"]["method"]
    # Carving: the hold above the double-bottom tank does not overlap it.
    hold, tank = components["cargo_hold-002"]["bbox_m"], components["ballast_tank-001"]["bbox_m"]
    assert hold["min"][2] >= tank["max"][2] - 1e-3
    # The hull is the estimate and every space lies inside it.
    hull = components["hull"]["bbox_m"]
    for entry in components.values():
        if entry["ga_kind"] in G.SPACE_KINDS:
            assert np.all(np.array(entry["bbox_m"]["min"]) >= np.array(hull["min"]) - 1e-2)
            assert np.all(np.array(entry["bbox_m"]["max"]) <= np.array(hull["max"]) + 1e-2)
    assert (task / "whole_vessel" / "whole-vessel-draft.glb").stat().st_size > 0
    assert (task / "intake" / "sources" / "synthetic-ga.png").exists()
    entry = result["selection_entry"]
    assert entry["credit"] == ESTIMATE_LABEL and entry["file_stem"] == "SYNTHETIC-1"
    summary = json.loads((task / "ga_estimate.json").read_text())
    assert summary["test_fixture"] is True and summary["skipped"][0]["id"] == "other_space-001"
