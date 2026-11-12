"""Fine pass of the GA reading: text blobs, level crops, contact sheets, kind checks.

Synthetic images only; no model is called and no partner drawing is used.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from vessel_reconstruction import ga_labels


def _sheet(tmp_path, angle: float = 0.0):
    """A sheet with one label (turned by ``angle``) and one dashed line."""
    sheet = Image.new("L", (1200, 800), 255)
    label = Image.new("L", (420, 60), 255)
    ImageDraw.Draw(label).text((10, 10), "NO.3 W.B.T. (P)", fill=0, font=ImageFont.load_default(size=28))
    label = label.rotate(angle, expand=True, fillcolor=255)
    sheet.paste(label, (300, 300))
    draw = ImageDraw.Draw(sheet)
    for x in range(50, 1150, 24):  # a dashed line: long thin dashes are not glyphs
        draw.line([(x, 700), (x + 14, 700)], fill=0, width=2)
    path = tmp_path / "S_GA.png"
    sheet.save(path)
    return path


@pytest.mark.parametrize("angle", [0.0, 30.0])
def test_a_label_is_found_and_its_direction_measured(tmp_path, angle):
    path = _sheet(tmp_path, angle)
    candidates = ga_labels.text_candidates(np.asarray(Image.open(path).convert("L")))
    assert len(candidates) == 1  # the label; the dashed line is not text
    found = candidates[0]
    # The blob box includes the joining radius (about one glyph) around the ink.
    assert 270 <= found.box[0] and found.box[2] <= 300 + 520
    # PIL turns counter-clockwise; image y runs down, so the text rises to the right.
    assert found.angle_deg == pytest.approx(-angle, abs=4.0)


def test_crops_reach_beyond_the_blob_and_cells_fit_the_provider(tmp_path):
    path = _sheet(tmp_path, 30.0)
    candidates = ga_labels.text_candidates(np.asarray(Image.open(path).convert("L")))
    crop_map, _ = ga_labels.prepare(path, candidates * 10, tmp_path / "fine")
    assert len(crop_map) == 10
    first = crop_map[0]
    assert first["box_px"][0] < first["blob_px"][0] and first["box_px"][2] > first["blob_px"][2]
    # More room along the text line than across it.
    along = first["blob_px"][0] - first["box_px"][0]
    level = ga_labels.Candidate((400, 400, 500, 420), 0.0, 5, 10.0)
    box = ga_labels.crop_box(level, 1200, 800)
    assert 400 - box[0] > 1.5 * (400 - box[1]) and along > 0
    request = json.loads((tmp_path / "fine" / "labels-1" / "request.json").read_text())
    assert request["purpose"] == "ga_labels" and request["engineering_approved"] is False
    for image in request["images"]:
        assert max(image["width"], image["height"]) <= 1024 and image["bytes"] <= ga_labels.MAX_IMAGE_BYTES
    assert {c["crop_id"] for c in request["context"]["crops"]} == {c["crop_id"] for c in crop_map}


def test_the_fine_pass_never_needs_more_than_its_request_budget(tmp_path):
    path = _sheet(tmp_path, 30.0)
    candidate = ga_labels.text_candidates(np.asarray(Image.open(path).convert("L")))[0]
    big = ga_labels.Candidate(candidate.box, candidate.angle_deg, candidate.glyphs, 6.0)  # large cells
    crop_map, _ = ga_labels.prepare(path, [big] * 400, tmp_path / "fine")
    requests = {c["request"] for c in crop_map}
    assert len(requests) <= ga_labels.MAX_FINE_REQUESTS
    assert 0 < len(crop_map) < 400
    # The ceiling is a setting: with two fine requests fewer crops are read.
    fewer, _ = ga_labels.prepare(path, [big] * 400, tmp_path / "fewer", max_requests=2)
    assert len({c["request"] for c in fewer}) == 2 and len(fewer) < len(crop_map)
    assert [c["crop_id"] for c in crop_map] == [f"c{i + 1:02d}" for i in range(len(crop_map))]  # priority order


def test_accommodation_blobs_go_last():
    level = ga_labels.Candidate((10, 10, 60, 20), 0.0, 6, 10.0)
    cabin = ga_labels.Candidate((510, 10, 590, 20), 20.0, 9, 10.0)
    order = ga_labels.unexplained([cabin, level], [], later_boxes=[[500, 0, 600, 100]])
    assert order == [level, cabin]


@pytest.mark.parametrize("kind, text, expected", [
    ("cargo_tank", "NO.2 CARGO", "other_tank"),         # a cut label does not say it is a cargo tank
    ("cargo_tank", "NO.1 C.O.T (P&S)", "cargo_tank"),
    ("cargo_tank", "NO.3 C.T. (P)", "cargo_tank"),
    ("cargo_hold", "NO.3 HOLD", "cargo_hold"),
    ("cargo_hold", "NO.3 CARGO", "other_space"),
    ("cargo_crane", "25t DECK CRANE", "cargo_crane"),
    ("cargo_crane", "10T HOSE HANDLING CRANE", "other_space"),
    ("cargo_crane", "PROVISION CRANE", "other_space"),
    ("cargo_hold", "NO.9 H O L D", "cargo_hold"),
    ("slop_tank", "SLOP T.(P)", "slop_tank"),
    ("ballast_tank", "W.B.T.", "ballast_tank"),     # kinds that are not counted are kept
])
def test_counted_kinds_need_their_word_in_the_label(kind, text, expected):
    assert ga_labels.checked_kind(kind, text) == expected


def test_every_unexplained_blob_is_a_candidate():
    """No fixed cap of crops: the request ceiling alone bounds the fine pass."""
    blobs = [ga_labels.Candidate((x, 10, x + 50, 20), 0.0, 6, 10.0) for x in range(0, 9000, 60)]
    assert len(ga_labels.unexplained(blobs, [])) == len(blobs) == 150
    assert len(ga_labels.unexplained(blobs, [], limit=48)) == 48


def test_the_pieces_of_a_letter_spaced_label_are_one_blob():
    """'NO. 5    W. B.   TK (P&S)' drawn with wide gaps along a slope is one label, not three."""
    slope = math.tan(math.radians(-12.0))

    def piece(x, width, glyphs):  # text that rises to the right: its box runs from the right end's top
        return ga_labels.Candidate((x, int(500 + slope * (x + width)), x + width, int(500 + slope * x) + 12),
                                   -12.0, glyphs, 10.0)

    pieces = [piece(100, 50, 4), piece(190, 40, 3), piece(270, 80, 7)]
    other_line = ga_labels.Candidate((100, 700, 180, 712), 0.0, 6, 10.0)   # a label on another line
    far = piece(600, 80, 6)
    joined = ga_labels.join_collinear([*pieces, other_line, far])
    assert len(joined) == 3
    label = max(joined, key=lambda c: c.glyphs)
    assert label.glyphs == 14 and label.box[0] == 100 and label.box[2] == 350
    # Level text beside a diagonal piece is not on its line.
    level = ga_labels.Candidate((360, 390, 420, 402), 0.0, 5, 10.0)
    assert len(ga_labels.join_collinear([pieces[2], level])) == 2


@pytest.mark.parametrize("kind, text, expected", [
    ("other_tank", "NO.4 C.T.(P)", "cargo_tank"),
    ("other_tank", "NO.6 C.O.T.(P&S)", "cargo_tank"),
    ("other_space", "NO.9 H O L D", "cargo_hold"),
    ("other_space", "HOLD OR W. B.", "other_space"),          # no hold number: not a hold
    ("other_space", "A/H FOR NO.6 HOLD", "other_space"),      # an access hatch for a hold
    ("other_tank", "NO.3 W.B.T.(S)", "ballast_tank"),
    ("other_space", "NO.5 TOP-SIDE W.B.TK (P)", "ballast_tank"),
    ("other_tank", "A.P.T.", "ballast_tank"),
    ("other_tank", "NO.1 F.O.T.(S)", "fuel_tank"),
    ("other_tank", "H.F.O.TK(P)", "fuel_tank"),
    ("other_tank", "SLOP HOLDING TK.(C)", "slop_tank"),
    ("other_tank", "RESIDUE TK", "other_tank"),
    ("other_tank", "L.O.S.T.", "other_tank"),
    ("other_space", "ACCESS HATCH", "other_space"),
    ("ballast_tank", "NO.2 C.O.T.(P)", "ballast_tank"),       # a kind the model named is not overruled
])
def test_a_label_that_names_its_kind_gets_that_kind(kind, text, expected):
    assert ga_labels.promoted_kind(kind, text) == expected


def test_the_slop_definition_is_a_setting():
    from vessel_reconstruction.ga_commercial_settings import DEFINITIONS
    assert ga_labels.label_kind("slop_tank", "SLOP HOLDING TK.(C)", DEFINITIONS) == "slop_tank"
    strict = {**DEFINITIONS, "slop_holding_tank_is_slop": False}
    assert ga_labels.label_kind("slop_tank", "SLOP HOLDING TK.(C)", strict) == "other_tank"
    assert ga_labels.label_kind("slop_tank", "SLOP TK.(P)", strict) == "slop_tank"
    assert ga_labels.label_kind("slop_tank", "RESIDUE TK", DEFINITIONS) == "other_tank"


def test_a_crop_that_a_reply_leaves_out_is_asked_once_more(tmp_path):
    """Review of the adaptive fine pass: one reply answered 4 of 35 cells."""
    path = _sheet(tmp_path, 0.0)
    candidate = ga_labels.text_candidates(np.asarray(Image.open(path).convert("L")))[0]
    asked = []

    def call(request_dir, provider_dir):
        crops = [c["crop_id"] for c in json.loads((request_dir / "request.json").read_text())["context"]["crops"]]
        asked.append(crops)
        answered = crops[:2] if len(asked) == 1 else crops  # the first reply stops after two cells
        return {"reply": {"ga_labels": {"crops": [{"crop_id": c, "labels": [], "evidence": "x"} for c in answered]}}}

    crop_map, readings = ga_labels.prepare(path, [candidate] * 5, tmp_path / "fine", max_requests=3, call=call)
    assert asked == [["c01", "c02", "c03", "c04", "c05"], ["c03", "c04", "c05"]]
    assert len(readings) == 2 and {row["crop_id"]: row["request"] for row in crop_map}["c04"] == "labels-2"
    # With one request only, the crops left out stay unread; nothing is asked a third time.
    asked.clear()
    ga_labels.prepare(path, [candidate] * 5, tmp_path / "one", max_requests=1, call=call)
    assert len(asked) == 1


def test_a_diagonal_crop_is_cut_to_its_text_band(tmp_path):
    path = _sheet(tmp_path, 30.0)
    candidate = ga_labels.text_candidates(np.asarray(Image.open(path).convert("L")))[0]
    cell = ga_labels.crop_image(Image.open(path).convert("L"), candidate)
    assert cell.width > 3 * cell.height   # a band along the text, not the square box of the diagonal


def test_a_fine_label_of_a_hold_without_its_number_is_not_a_hold():
    from vessel_reconstruction import source_record
    result = {"sources": {"ga": {"file": "S_GA.png"}}, "checks": [], "counts": {}, "views": [], "spaces": [],
              "model_counts": {name: {"missing": "x"} for name in
                               ("cargo_holds", "cargo_hatches", "cargo_cranes", "cargo_tanks", "slop_tanks",
                                "container_bays")}}
    crop_map = [{"crop_id": "c01", "box_px": [10, 10, 90, 40]}]
    reading = {"reply": {"ga_labels": {"crops": [{"crop_id": "c01", "evidence": "x", "labels": [
        {"text": "HOLD", "kind": "cargo_hold", "number": None},
        {"text": "NO.3 HOLD", "kind": "cargo_hold", "number": "3"}]}]}}}
    ga_labels.merge(result, crop_map, [reading], "S_GA.png", [100, 100])
    assert [(s["label"], s["kind"]) for s in result["spaces"]] == [("HOLD", "other_space"), ("NO.3 HOLD", "cargo_hold")]


@pytest.mark.parametrize("first, second, same", [
    ("NO. 3 T. S. W. B. T. (P/S)", "NO.3 T.S.W.B.T.(P/S)", True),   # one tank read twice
    ("NO.3 T.S.W.B.T. (P/S)", "NO.3 W.B.T. (P/S)", False),         # two tank families, one number
    ("NO.2 F.O.T. (P)", "NO.2 F.O.T. (S)", True),                   # the side is in the number
])
def test_a_label_is_another_space_only_when_its_family_differs(first, second, same):
    assert (ga_labels.label_family(first) == ga_labels.label_family(second)) is same


def test_a_hoist_crane_is_not_a_cargo_crane():
    assert ga_labels.checked_kind("cargo_crane", "HOIST CRANE") == "other_space"



def test_a_label_dropped_as_cut_is_read_again_from_a_wider_crop(tmp_path):
    """The re-read of cut labels uses only the requests a ship has left, with new crop ids."""
    path = _sheet(tmp_path, 0.0)
    result = {"sources": {"ga": {"file": "S_GA.png"}}, "checks": [], "counts": {}, "views": [], "spaces": [],
              "model_counts": {name: {"missing": "x"} for name in
                               ("cargo_holds", "cargo_hatches", "cargo_cranes", "cargo_tanks", "slop_tanks",
                                "container_bays")}}
    fine_crops = [{"crop_id": "c07", "blob_px": [300, 300, 420, 360], "angle_deg": 0.0, "glyphs": 8,
                   "box_px": [290, 290, 430, 370]}]
    cut = {"id": "other_tank-c07-1", "label": "NO.3 W", "kind": "other_tank",
           "source_record": {"kind": "read", "regions": [{"box_px": [290, 290, 430, 370]}]}}
    fitting = {"id": "other_space-c07-2", "label": "PILOT LADDER", "kind": "other_space",
               "source_record": {"kind": "read", "regions": [{"box_px": [290, 290, 430, 370]}]}}
    asked = []

    def call(request_dir, provider_dir):
        crops = json.loads((request_dir / "request.json").read_text())["context"]["crops"]
        asked.append([c["crop_id"] for c in crops])
        return {"reply": {"ga_labels": {"crops": [{"crop_id": c["crop_id"], "evidence": "x", "labels": [
            {"text": "NO.3 W.B.T. (P)", "kind": "ballast_tank", "number": "3P"}]} for c in crops]}}}

    dropped = [(cut, "'W' is the start of a longer word printed on the sheet: the label is cut"),
               (fitting, "a fitting or an opening, not a space")]
    stats = ga_labels.reread_cut_labels(result, dropped, path, tmp_path / "reread", call, 1, fine_crops)
    assert asked == [["c08"]]  # one crop (the fitting is not read again), numbered after the fine pass
    assert stats["requests"] == 1 and [s["label"] for s in result["spaces"]] == ["NO.3 W.B.T. (P)"]
    asked.clear()
    assert ga_labels.reread_cut_labels(result, dropped, path, tmp_path / "none", call, 0, fine_crops)["requests"] == 0
    assert asked == []
