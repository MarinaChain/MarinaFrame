"""Offline Phase 1 checks keep missing cases and warnings in the denominator."""
import importlib.util
import json
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "scripts/check_vessel_description.py"
spec = importlib.util.spec_from_file_location("description_check", MODULE)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def reference():
    return {"length_m": 100., "max_half_breadth_m": 5., "depth_m": 10., "draft_m": 6.}


def test_missing_description_is_not_a_pass(tmp_path):
    result = checker.check_case(tmp_path, reference(), {"sections": [{"id": "s01", "x_m": 10.}]},
                                {"waterline_grid_z_m": [2., 4., 6., 8.]})
    assert not result["description_present"]
    assert not result["all_dimensions_within_2_percent"]
    assert not result["stations_right"]
    assert not result["waterlines_right"]
    assert result["wrong_fields_without_warning"]


def test_warning_coverage_does_not_change_numeric_pass(tmp_path):
    domain = tmp_path / "domain"
    domain.mkdir()
    description = {"principal": {"loa": {"value": 100.}, "beam": {"value": 10.},
                                  "depth": {"value": 10.}, "draft": {"value": None}},
                   "stations": [{"id": "s01", "x_m": 10.}],
                   "waterlines": [{"id": "w2", "z_m": 2.}, {"id": "w4", "z_m": 4.}],
                   "warnings": [{"field": "principal.draft"}]}
    (domain / "vessel.json").write_text(json.dumps({"description": description}))
    result = checker.check_case(tmp_path, reference(), {"sections": [{"id": "s01", "x_m": 10.}]},
                                {"waterline_grid_z_m": [2., 4.]})
    assert not result["all_dimensions_within_2_percent"]
    assert result["stations_right"] and result["waterlines_right"]
    assert result["wrong_fields"] == ["principal.draft"]
    assert result["wrong_fields_without_warning"] == []
