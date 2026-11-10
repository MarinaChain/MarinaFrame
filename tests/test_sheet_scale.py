"""Printed scale, hull length estimate and cross-sheet agreement (sheet_scale.py)."""
import pytest

from vessel_reconstruction.sheet_scale import (long_view_width_fraction, length_estimate_m, parse_scales,
                                               printed_length_m, read_scale, scale_agreement)


@pytest.mark.parametrize("text,ratio", [
    ("SCALE 1:100", 100), ("Scale 1 : 50", 50), ("1:25", 25), ("SCALE 1/100", 100),
    ('Scale: 1/16" = 1\'-0"', 192), ('3/8" = 1\'-0"', 32), ('1" = 20\'', 240), ('1 1/2" = 1\'-0"', 8),
])
def test_printed_scale_forms(text, ratio):
    assert parse_scales(text)[0]["ratio"] == pytest.approx(ratio)


def test_time_dates_and_odd_ratios_are_not_scales():
    assert parse_scales("10:30 and 2026-11-10 and 1:37 and 21:100") == []


def test_main_scale_is_the_most_frequent_and_status_is_mixed():
    result = read_scale("1:50 1:25 1:50 1:10 SCALE 1:50")
    assert (result["status"], result["main_ratio"]) == ("mixed", 50.0)
    assert result["source"] == "text:ocr"
    assert read_scale("SCALE 1:100")["status"] == "read"
    assert read_scale("nothing here")["status"] == "missing"


def test_length_estimate_uses_paper_size_and_scale():
    # A0 landscape 1189 mm wide, view covers 0.5 of it at 1:100: 59.45 m.
    info = {"pdf_points": [1189 / 25.4 * 72, 841 / 25.4 * 72]}
    assert length_estimate_m(0.5, info, 100) == pytest.approx(59.45, abs=0.01)
    assert length_estimate_m(0.5, {"dpi": 400, "full_px": [14400, 9600]}, 192) == pytest.approx(
        0.5 * 914.4 * 192 / 1000, abs=0.01)
    assert length_estimate_m(None, info, 100) is None and length_estimate_m(0.5, {}, 100) is None


def test_long_view_is_the_widest_group_at_least_twice_as_wide_as_tall():
    boxes = [[0, 0, 500, 400], [0, 0, 800, 200], [0, 0, 900, 600]]
    assert long_view_width_fraction(boxes, 1000) == 0.8
    assert long_view_width_fraction([[0, 0, 100, 100]], 1000) is None


def test_printed_length():
    assert printed_length_m("LOA 28.9 m  BEAM 9.6 m") == 28.9
    assert printed_length_m("Length overall 31,25 m") == 31.25
    assert printed_length_m("L.O.A. 422'-6\"") == pytest.approx(128.8, abs=0.1)
    assert printed_length_m("no length") is None


def sheet(page, kind, length, status="read", printed=None):
    return {"page_id": page, "type": kind, "length_m": length, "scale_status": status, "printed_length_m": printed}


def test_sheets_that_agree():
    result = scale_agreement([sheet("p1", "lines_plan", 31.0), sheet("p2", "profile", 31.6),
                              sheet("p3", "general_arrangement", 30.8), sheet("p4", "other", None)])
    assert result["status"] == "agree" and result["items"] == []
    assert result["reference_m"] == pytest.approx(31.0)


def test_a_disagreeing_sheet_becomes_a_check_item_not_a_failure():
    result = scale_agreement([sheet("p1", "lines_plan", 31.0), sheet("p2", "profile", 31.2),
                              sheet("p3", "tank_plan", 62.0)])
    assert result["status"] == "check"
    [item] = result["items"]
    assert item["code"] == "scale_disagrees" and item["page_id"] == "p3"
    assert item["estimate_m"] == 62.0 and "31" in item["message"]


def test_missing_scale_and_few_estimates_and_printed_length():
    result = scale_agreement([sheet("p1", "tank_plan", None, "missing"), sheet("p2", "lines_plan", 31.0)])
    assert result["status"] == "too_few"
    assert [i["code"] for i in result["items"]] == ["scale_missing"]
    result = scale_agreement([sheet("p1", "lines_plan", 31.0), sheet("p2", "profile", 31.1, printed=40.0)])
    assert [i["code"] for i in result["items"]] == ["printed_length_differs"]


def test_printed_length_in_a_particulars_table():
    text = "LENGTH OVER ALL  36.25 [m] LENGTH BETV. PERP.   33.90 [m] BREADTH MOULDED 9.60 [m]"
    assert printed_length_m(text) == 36.25
    assert printed_length_m("LENGTH BETWEEN PERPENDICULARS 33.9 m") == 33.9
