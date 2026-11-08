"""Accuracy hints must not remove evidence or refuse a choice."""
import copy

from vessel_reconstruction.accuracy_feedback import candidate_feedback, candidate_catalog

SECTION = {"id": "s01", "calibration": {"pixels_per_metre": 10}, "z_min_m": 0, "z_max_m": 10}


def test_grid_fragment_and_nonstation_label_are_advisory():
    candidate = {"candidate_id": "trace-grid", "z_range_m": [2, 7],
                 "contour_selection": {"anchors_px": [[100, 20], [100, 70]]}}
    original = copy.deepcopy(candidate)
    result = candidate_feedback(SECTION, candidate, "S1.5W")
    assert result["coverage_percent"] == 50
    assert result["half_breadth_std_m"] == 0
    assert len(result["warnings"]) == 3
    assert "trace_from_point" in result["suggested_next_tools"]
    assert candidate == original


def test_unambiguous_contour_is_listed_first_without_deleting_other_choices():
    entry = {"grid_evidence": {"unique_non_grid_candidate_id": "contour-hull"}, "candidates": [
        {"candidate_id": "trace-grid"}, {"candidate_id": "contour-hull", "z_range_m": [0, 10],
         "contour_selection": {"anchors_px": [[0, 100], [50, 50], [80, 0]]}}]}
    result = candidate_catalog(SECTION, entry)
    assert [r["candidate_id"] for r in result] == ["contour-hull", "trace-grid"]
    assert result[0]["recommended"] is True
    assert result[0]["warnings"] == []
