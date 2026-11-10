"""Checklist and set analysis (drawing_set.py)."""
import numpy as np

from vessel_reconstruction.drawing_set import (CHECKLIST_RULES, analyse_page, analyse_set, checklist, views_in)


def sheet(page, kind, views=()):
    return {"page_id": page, "type": kind, "views": list(views)}


def status(items):
    return {i["id"]: i["status"] for i in items}


def test_every_rule_has_a_known_level_and_output():
    assert {r["level"] for r in CHECKLIST_RULES} == {"required", "recommended"}
    assert {r["output"] for r in CHECKLIST_RULES} == {"hull", "tanks", "steel", "booklet"}


def test_set_with_one_missing_required_drawing():
    items = checklist([sheet("p1", "lines_plan"), sheet("p2", "profile"), sheet("p3", "tank_plan"),
                       sheet("p4", "midship_section"), sheet("p5", "hydrostatics")])
    got = status(items)
    assert got["steel_shell"] == "missing"
    assert [i["id"] for i in items if i["level"] == "required" and i["status"] == "missing"] == ["steel_shell"]
    assert got["hull_lines"] == got["hull_profile"] == got["tanks_plan"] == got["steel_midship"] == "met"
    assert got["hull_ga"] == "missing"  # recommended, not required


def test_met_by_lists_the_pages():
    items = checklist([sheet("p1", "general_arrangement"), sheet("p2", "general_arrangement")])
    ga = next(i for i in items if i["id"] == "hull_ga")
    assert ga["met_by"] == ["p1", "p2"]


def test_a_lines_plan_with_a_sheer_plan_meets_the_profile_need_and_says_so():
    items = checklist([sheet("p1", "lines_plan", ["sheer", "body_plan"])])
    profile = next(i for i in items if i["id"] == "hull_profile")
    assert profile["status"] == "met" and profile["met_by"] == ["p1"] and "sheer" in profile["met_note"]
    no_sheer = checklist([sheet("p1", "lines_plan", ["body_plan"])])
    assert status(no_sheer)["hull_profile"] == "missing"


def test_empty_set_misses_everything_required():
    assert all(i["status"] == "missing" for i in checklist([]))


def test_views_named_in_text():
    assert views_in("HALF-BREADTH PLAN  Body Plan  SHEER") == ["sheer", "half_breadth", "body_plan"]


def test_analyse_set_leaves_out_skipped_pages_and_never_approves():
    pages = [{"page_id": "p1", "skip": False, "sheet": {"type": "tank_plan", "views": [], "length_m": 30.0,
                                                         "scale": {"status": "read"}}},
             {"page_id": "p2", "skip": True, "sheet": {"type": "shell_expansion", "views": [], "length_m": None,
                                                        "scale": {"status": "missing"}}}]
    result = analyse_set(pages)
    assert result["counts"] == {"tank_plan": 1}
    assert "steel_shell" in result["missing_required"] and "tanks_plan" not in result["missing_required"]
    assert result["engineering_approved"] is False
    assert result["scale_agreement"]["status"] == "too_few"


def test_analyse_page_reads_type_and_scale_from_text_given_by_ocr():
    gray = np.full((400, 900), 255, np.uint8)
    gray[100:140, 100:500] = 0  # one long dark view, under half the page wide (wider rows count as frame lines)
    sheet_result = analyse_page(path=None, page_index=0, gray=gray, info={"dpi": 200.0, "full_px": [900, 400]},
                                file_name="x.png", ocr=lambda g: "TANK PLAN capacity  SCALE 1:50  LOA 31.2 m")
    assert sheet_result["type"] == "tank_plan" and sheet_result["scale"]["main_ratio"] == 50.0
    assert sheet_result["printed_length_m"] == 31.2
    assert sheet_result["length_m"] is not None and sheet_result["text_source"] == "ocr"
