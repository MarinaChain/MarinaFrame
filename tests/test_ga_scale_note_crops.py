"""Spacing-note coverage uses synthetic sheets and local text locations only."""
import json

import pytest
from PIL import Image, ImageDraw

from vessel_reconstruction import ga_scale_requests, ga_scale_settings, sheet_types


def _sheet(tmp_path):
    path = tmp_path / "synthetic.png"
    image = Image.new("L", (2400, 1600), 255)
    ImageDraw.Draw(image).text((100, 50), "FRAME SPACING 800 mm", fill=0)
    image.save(path)
    result = {"views": [
        {"view_id": "v1", "kind": "profile", "box_px": [200, 400, 2200, 650]},
        {"view_id": "v2", "kind": "deck_plan", "box_px": [200, 800, 2200, 1050]},
        {"view_id": "v3", "kind": "tank_top_plan", "box_px": [200, 1200, 2200, 1450]},
    ]}
    return path, result


def _words(text, box=(100, 50, 500, 80), line="1"):
    return [{"text": text, "bbox": list(box), "line": ["1", "1", "1", line]}]


def _covers(crop, box):
    return crop[0] <= box[0] and crop[1] <= box[1] and crop[2] >= box[2] and crop[3] >= box[3]


@pytest.mark.parametrize("text", ["FRAME SPACING 800 mm", "FR. SP. = 800 MM", "FRAME SPACE 600mm", "F.S. 0.70"])
@pytest.mark.parametrize("retry", [False, True])
def test_header_spacing_note_enters_existing_scale_request(tmp_path, monkeypatch, text, retry):
    path, result = _sheet(tmp_path)
    words = _words(text)
    monkeypatch.setattr(sheet_types, "ocr_read", lambda gray, **kw: kw["words_out"].extend(words))
    out = tmp_path / "request"
    assert ga_scale_requests.prepare_scale(result, path, out, "no spacing" if retry else None)
    request = json.loads((out / "request.json").read_text())
    images = request["images"]
    assert len(images) <= ga_scale_settings.MAX_IMAGES
    assert all(any(image["view"].startswith(view["kind"] + ":" + view["view_id"]) for image in images)
               for view in result["views"])
    assert any(_covers(image["crop_box_px"], words[0]["bbox"]) for image in images)
    assert not request["engineering_approved"]
    assert ("previous_attempt" in request["context"]) == retry


@pytest.mark.parametrize("words", [[], _words("LBP 150 m"), _words("FRAME SPACING 800 mm", (300, 450, 700, 480))])
def test_no_extra_crop_when_no_uncovered_spacing_note(tmp_path, monkeypatch, words):
    path, result = _sheet(tmp_path)
    monkeypatch.setattr(sheet_types, "ocr_read", lambda gray, **kw: kw["words_out"].extend(words))
    out = tmp_path / "request"
    ga_scale_requests.prepare_scale(result, path, out)
    images = json.loads((out / "request.json").read_text())["images"]
    assert not any("note" in image["image_id"] for image in images)


@pytest.mark.skipif(not sheet_types.ocr_available(), reason="local tesseract is not installed")
def test_generated_sheet_header_is_found_by_local_ocr(tmp_path):
    from benchmarks.ga_synthetic.generate import write_suite

    write_suite(tmp_path / "suite", seed=17, count=1)
    path = next((tmp_path / "suite" / "images").iterdir())
    result = {"views": [{"view_id": "v1", "kind": "profile", "box_px": [200, 450, 3750, 1020]}]}
    ga_scale_requests.prepare_scale(result, path, tmp_path / "request")
    images = json.loads((tmp_path / "request" / "request.json").read_text())["images"]
    note = next(image for image in images if "note" in image["image_id"])
    assert _covers(note["crop_box_px"], [281, 202, 563, 219])
    assert len(images) <= ga_scale_settings.MAX_IMAGES


def test_spacing_note_uses_first_plan_when_profile_is_absent(tmp_path, monkeypatch):
    path, result = _sheet(tmp_path)
    result["views"] = result["views"][1:]
    monkeypatch.setattr(sheet_types, "ocr_read", lambda gray, **kw: kw["words_out"].extend(_words("FRAME SPACING 800 mm")))
    ga_scale_requests.prepare_scale(result, path, tmp_path / "request")
    images = json.loads((tmp_path / "request" / "request.json").read_text())["images"]
    note = next(image for image in images if "note" in image["image_id"])
    assert note["view"] == "deck_plan:v2:spacing_note"


def test_split_ocr_words_and_multiple_notes_are_all_covered(tmp_path, monkeypatch):
    path, result = _sheet(tmp_path)
    words = [*_words("FRAME", (100, 50, 180, 80)), *_words("SPACING", (190, 50, 300, 80)),
             *_words("800 mm", (310, 50, 400, 80)), *_words("FR. SP. 700 mm", (1200, 90, 1500, 120), "2")]
    monkeypatch.setattr(sheet_types, "ocr_read", lambda gray, **kw: kw["words_out"].extend(words))
    ga_scale_requests.prepare_scale(result, path, tmp_path / "request")
    images = json.loads((tmp_path / "request" / "request.json").read_text())["images"]
    assert len(images) <= ga_scale_settings.MAX_IMAGES
    assert all(any(_covers(image["crop_box_px"], word["bbox"]) for image in images) for word in words)
