"""Fine pass of the GA reading: text blobs, level crops, contact sheets, kind checks.

Synthetic images only; no model is called and no partner drawing is used.
"""
from __future__ import annotations

import json

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
    crop_map = ga_labels.prepare(path, candidates * 10, tmp_path / "fine")
    assert len(crop_map) == 10
    first = crop_map[0]
    assert first["box_px"][0] < first["blob_px"][0] and first["box_px"][2] > first["blob_px"][2]
    # More room along the text line than across it.
    along = first["blob_px"][0] - first["box_px"][0]
    level = ga_labels.Candidate((400, 400, 500, 420), 0.0, 5, 10.0)
    box = ga_labels.crop_box(level, 1200, 800)
    assert 400 - box[0] > 2 * (400 - box[1]) and along > 0
    request = json.loads((tmp_path / "fine" / "labels-1" / "request.json").read_text())
    assert request["purpose"] == "ga_labels" and request["engineering_approved"] is False
    for image in request["images"]:
        assert max(image["width"], image["height"]) <= 1024 and image["bytes"] <= ga_labels.MAX_IMAGE_BYTES
    assert {c["crop_id"] for c in request["context"]["crops"]} == {c["crop_id"] for c in crop_map}


def test_the_fine_pass_never_needs_more_than_its_request_budget(tmp_path):
    path = _sheet(tmp_path, 30.0)
    candidate = ga_labels.text_candidates(np.asarray(Image.open(path).convert("L")))[0]
    big = ga_labels.Candidate(candidate.box, candidate.angle_deg, candidate.glyphs, 6.0)  # large cells
    crop_map = ga_labels.prepare(path, [big] * 200, tmp_path / "fine")
    requests = {c["request"] for c in crop_map}
    assert len(requests) <= ga_labels.MAX_FINE_REQUESTS
    assert 0 < len(crop_map) < 200
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
