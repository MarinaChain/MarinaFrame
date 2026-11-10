"""Sheet typing (sheet_types.py): keyword rules, file-name switch, vision fallback, no-text pages."""
import json

import numpy as np
import pytest

from vessel_reconstruction.sheet_types import (SHEET_TYPES, VISION_BELOW, decide, ocr_read, ocr_text, type_sheet,
                                               vision_type)

CASES = [
    ("HALF-BREADTH PLAN  BODY PLAN  TABLE OF OFFSETS  STATIONS", "lines_plan"),
    ("GENERAL ARRANGEMENT  A-deck plan  wheelhouse", "general_arrangement"),
    ("OUTBOARD PROFILE  INBOARD PROFILE", "profile"),
    ("MIDSHIP SECTION  typical section frame 17", "midship_section"),
    ("SHELL EXPANSION  strake A  plate thickness 8", "shell_expansion"),
    ("STRUCTURAL PROFILE scantlings girder welding", "construction_profile"),
    ("TANK PLAN  tank schedule  capacity m3  sounding", "tank_plan"),
    ("HYDROSTATIC TABLES  LCB LCF TPC  displacement  KMT", "hydrostatics"),
    ("TITLE SHEET", "other"),
    ("RIGGING PROFILE", "other"),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_title_text_names_the_type(text, expected):
    result = decide(text, "pdf_text")
    assert result["type"] == expected
    assert result["confidence"] >= VISION_BELOW
    assert result["source"] == "text:pdf_text"
    assert result["evidence"]


def test_capacity_plan_profile_is_a_tank_plan_not_a_profile():
    assert decide("CAPACITY PLAN PROFILE", "ocr")["type"] == "tank_plan"


def test_file_name_is_a_source_and_can_be_switched_off():
    named = decide("", "none", "Midship_Section_Rev0.pdf")
    assert (named["type"], named["source"]) == ("midship_section", "file_name")
    silent = type_sheet(file_name="Midship_Section_Rev0.pdf", text="", use_file_name=False)
    assert silent["type"] == "other" and silent["confidence"] < VISION_BELOW


def test_text_and_name_together_are_listed_as_both_sources():
    result = decide("TANK PLAN", "pdf_text", "tank_plan.pdf")
    assert result["source"] == "file_name+text:pdf_text"


def test_nothing_matches_gives_other_with_low_confidence():
    result = decide("lorem ipsum", "ocr")
    assert result["type"] == "other" and result["confidence"] < VISION_BELOW


def test_layout_alone_is_a_weak_vote_for_lines_plan():
    regions = [{"label": "body_plan"}, {"label": "profile"}]
    result = decide("", "none", None, regions)
    assert result["confidence"] < VISION_BELOW  # one weak vote never settles a sheet


def test_confidence_is_in_range_and_types_are_known():
    for text, _ in CASES:
        result = decide(text, "ocr")
        assert result["type"] in SHEET_TYPES and 0 <= result["confidence"] <= 1


GRAY = np.full((50, 80), 255, np.uint8)


def test_model_is_asked_only_when_code_is_unsure():
    asked = []

    def ask(prompt, pngs):
        asked.append(len(pngs))
        return '{"type": "tank_plan", "confidence": 0.8, "evidence": "tank outlines"}'

    sure = type_sheet(text="TANK PLAN capacity", gray=GRAY, ask=ask)
    assert sure["type"] == "tank_plan" and asked == [] and sure["source"].startswith("text")
    unsure = type_sheet(text="", gray=GRAY, ask=ask, use_file_name=False)
    assert asked == [1]
    assert unsure["type"] == "tank_plan" and unsure["source"] == "model:claude-sonnet-5-5"
    assert unsure["code"]["type"] == "other"  # what code alone said stays visible


def test_a_failed_or_off_list_model_answer_keeps_the_code_result():
    assert vision_type(GRAY, lambda p, i: "no json") is None
    assert vision_type(GRAY, lambda p, i: json.dumps({"type": "approved"})) is None

    def broken(prompt, pngs):
        raise RuntimeError("the claude CLI gave no answer")

    result = type_sheet(text="", gray=GRAY, ask=broken)
    assert result["type"] == "other" and result["source"] == "code:no_rule"


def test_ocr_without_tesseract_is_empty(monkeypatch):
    monkeypatch.setattr("vessel_reconstruction.sheet_types.shutil.which", lambda name: None)
    assert ocr_text(GRAY) == ""
    assert ocr_read(GRAY) == ("", "")


def test_headings_outweigh_notes():
    # A profile sheet whose notes name tanks and decks stays a profile when the heading says so.
    notes = "tank capacity deck"
    assert decide(notes, "ocr", None, None, "OUTBOARD PROFILE")["type"] == "profile"
    assert decide(notes, "ocr")["type"] != "profile"


def test_a_short_pdf_layer_is_read_with_ocr(monkeypatch):
    monkeypatch.setattr("vessel_reconstruction.sheet_types.pdf_text", lambda path, index: "A0 sheet 1:50")
    from pathlib import Path
    from vessel_reconstruction.sheet_types import sheet_text
    text, title, where = sheet_text(Path("x.pdf"), 0, GRAY, lambda g: ("TANK PLAN", "TANK PLAN"))
    assert where == "pdf_text+ocr" and "1:50" in text and "TANK PLAN" in text and title == "TANK PLAN"
