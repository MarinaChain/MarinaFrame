"""Synthetic tests for the MiDShip 3D block layout and its scorer (no dataset file)."""
import numpy as np
import pytest

from vessel_reconstruction.structure import block3d, block_eval
from vessel_reconstruction.structure.model import Member, SectionResult, Stroke


def member(role, host, bbox_mm, thickness=20.0, index=0):
    y0, z0, y1, z1 = bbox_mm
    stroke = Stroke(index, ((y0, z0), (y1, z1)), f"pdf_path:{index}")
    return Member(role=role, stroke=stroke, host=host, thickness_mm=thickness, ship_bbox_mm=bbox_mm,
                  ship_points_mm=((y0, z0), (y1, z1)))


def reading():
    members = [
        member("bottom_shell", "Bottom", (0, 0, 8000, 0), 28, 1),
        member("side_shell", "Side_Shell", (8000, 2000, 8000, 11000), 28, 2),
        member("deck", "Deck", (0, 11000, 8000, 11000), 29, 3),
        member("deck", "Inner_Bottom", (0, 2000, 8000, 2000), 35, 4),
        member("stiffener_web", "Side_Shell", (7700, 5000, 8000, 5000), 9, 5),
        member("stiffener_web", "Bottom", (1000, 0, 1000, 300), 8, 6),
    ]
    section = SectionResult(members, [], 20.0, (0.0, 0.0), [], [], "vector", 6, 0)
    rows = {
        "Webframe": block3d.PrintedRow("Webframe", 1, 1.4, "T", 1.9, 0.3, 21.0),
        "Floor": block3d.PrintedRow("Floor", 1, 1.4, "I", 2.0, 0.0, 29.0),
        "Deck_Transvere_Beam": block3d.PrintedRow("Deck_Transvere_Beam", 1, 1.4, "L", 0.9, 0.3, 25.0),
        "Vert. BLKHD Stiff.": block3d.PrintedRow("Vert. BLKHD Stiff.", 7, 1.0, "L", 0.24, 0.11, 10.0),
        "Trans. BLKHD Stiff.": block3d.PrintedRow("Trans. BLKHD Stiff.", 20, 0.5, "T", 0.22, 0.13, 10.0),
        "Side Shell Stiff.": block3d.PrintedRow("Side Shell Stiff.", 20, 0.5, "T", 0.3, 0.1, 9.0),
        "Bot. Stiff.": block3d.PrintedRow("Bot. Stiff.", 38, 0.2, "T", 0.3, 0.05, 8.0),
    }
    plates = {"Trans. BLKHD": 25.0, "Lower Bracket": 14.0, "Upper Bracket": 12.0}
    return block3d.BlockReading(section, plates, rows, 8.0, 11.0, 2.0, 2.0)


def test_stations_centre_three_holds_in_the_block():
    st = block3d.stations(1.4)
    hold = 9 * 1.4
    assert st.bulkheads[0] == pytest.approx((40 - 3 * hold) / 2)
    assert np.diff(st.bulkheads) == pytest.approx([hold] * 3)
    assert len(st.webs) == 3 * 8
    assert len(st.frames) == 3 * 9 * 4  # 5 frame spaces per web space: 4 frames between webs
    assert st.frame_spacing_m == pytest.approx(0.28)


def test_transverse_members_use_printed_scantlings_and_label_guesses():
    st = block3d.stations(1.4)
    members = block3d.transverse_members(reading(), st)
    by_label = {}
    for m in members:
        by_label.setdefault(m.label, []).append(m)
    assert len(by_label["transverse_bulkhead"]) == 4
    assert by_label["transverse_bulkhead"][0].thickness_mm == 25.0
    assert by_label["transverse_bulkhead"][0].box[4] == 8.0 and by_label["transverse_bulkhead"][0].box[5] == 11.0
    web = by_label["web_frame"][0]
    assert web.box[1] == pytest.approx(8.0 - 1.9) and web.thickness_mm == 21.0
    assert len(by_label["floor"]) == 24 and by_label["floor"][0].box[5] == 2.0
    # Ordinary frames carry guessed scantlings and a guessed spacing.
    frame = next(m for m in by_label["frame"] if m.member_id.endswith("Side_Shell"))
    assert frame.thickness_source == "guessed" and frame.sources["frame_spacing"] == "guessed"
    # In a double bottom the ordinary bottom frame spans bottom shell to inner bottom.
    bottom = next(m for m in by_label["frame"] if m.member_id.endswith("Bottom"))
    assert bottom.box[2] == 0.0 and bottom.box[5] == 2.0
    assert len(by_label["bulkhead_stiffener"]) == 4 * (7 + 20)
    assert len({m.member_id for m in members}) == len(members)


def test_iou_match_is_one_to_one_and_label_agnostic():
    true = np.array([[1.0, 0, 0, 1.0, 8, 11], [2.0, 0, 0, 2.0, 8, 11]])
    pred = np.array([[1.01, 0, 0, 1.01, 8, 11], [5.0, 0, 0, 5.0, 8, 11], [1.0, 0, 0, 1.0, 8, 11]])
    pairs = block_eval.match(pred, true)
    assert len(pairs) == 1
    assert pairs[0][1] == 0


def test_truth_labels_cover_transverse_classes():
    assert block_eval.label_3d("Transverse_Floor") == "floor"
    assert block_eval.label_3d("Deck_Transverse_Stiffener,") == "frame"
    assert block_eval.label_3d("Transverse_Bulkhead_Vertical_Stiffener") == "bulkhead_stiffener"
    assert block_eval.label_3d("Bracket_Floor_Web") == "bracket"
    assert block_eval.label_3d("Inner_Side_Shell_Vertical_Stiffener") == "frame"
    assert block_eval.label_3d("Side_Shell_Longitudinal_Stiffener") == "stiffener_web"


def test_scorer_refuses_w3_sealed_designs(tmp_path):
    with pytest.raises(SystemExit):
        block_eval.evaluate(tmp_path, [118])
