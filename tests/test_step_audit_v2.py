"""Independent analytic fixtures for the versioned STEP boundary comparator."""
from pathlib import Path

import cadquery as cq
import numpy as np
import pytest

from benchmarks.audit_exported_step_v2 import ordinate_intersection, sample_step_sections


def test_float_endpoint_gap_is_resolved_and_explicitly_recorded():
    edges = [([2.0, 0.0], [2.0, 1.0 - 5e-16]),
             ([2.0, 1.0 + 2e-16], [2.0, 2.0])]
    result = ordinate_intersection(edges, 1.0)
    assert result["status"] == "complete"
    assert result["y_m"] == pytest.approx(2.0)
    assert result["endpoint_tolerance_applied"] is True
    assert 0 < result["maximum_endpoint_adjustment_m"] < 1e-14


def test_real_missing_interval_is_not_bridged_by_tolerance():
    edges = [([2.0, 0.0], [2.0, 0.999]), ([2.0, 1.001], [2.0, 2.0])]
    result = ordinate_intersection(edges, 1.0)
    assert result["status"] == "absent"
    assert result["y_m"] is None
    assert result["nearest_positive_endpoint_distance_m"] == pytest.approx(0.001)


def test_distinct_positive_boundaries_are_not_silently_deduplicated():
    edges = [([2.0, 0.0], [2.0, 2.0]), ([2.00001, 0.0], [2.00001, 2.0])]
    result = ordinate_intersection(edges, 1.0)
    assert result["status"] == "ambiguous"
    assert len(result["boundary_candidates_y_m"]) == 2


def test_horizontal_boundary_interval_is_reported_as_ambiguous():
    result = ordinate_intersection([([1.0, 1.0], [2.0, 1.0])], 1.0)
    assert result["status"] == "ambiguous"
    assert result["horizontal_intervals_y_m"] == [[1.0, 2.0]]


def reference_sections():
    return [{"id": f"station-{i}", "x_m": x,
             "points_yz_m": [[2.0, float(z)] for z in np.linspace(0, 3, 5)]}
            for i, x in enumerate([0.0, 2.5, 5.0, 7.5, 10.0])]


def test_actual_analytic_step_units_and_known_positive_error(tmp_path: Path):
    # This primitive is independent of the inference geometry implementation.
    # It extends +0.25m further on starboard than the numerical reference.
    shape = cq.Solid.makeBox(10000, 4500, 3000, cq.Vector(0, -2250, 0))
    target = tmp_path / "independent-box.step"
    shape.exportStep(str(target))
    records = sample_step_sections(target, reference_sections(), count=3, samples=9)
    assert len(records) == 3
    assert sum(r["compared_ordinates"] for r in records) == 27
    for row in records:
        assert row["status"] == "complete"
        assert row["mean_squared_error_m2"] == pytest.approx(0.25**2, abs=1e-12)
        assert row["maximum_absolute_error_m"] == pytest.approx(0.25, abs=1e-12)
        assert row["unresolved_ordinate_details"] == []


def test_actual_short_step_retains_every_missing_ordinate(tmp_path: Path):
    shape = cq.Solid.makeBox(10000, 4000, 2600, cq.Vector(0, -2000, 0))
    target = tmp_path / "truncated-box.step"
    shape.exportStep(str(target))
    records = sample_step_sections(target, reference_sections(), count=3, samples=9)
    for row in records:
        assert row["status"] == "incomplete"
        assert row["requested_ordinates"] == 9
        assert row["compared_ordinates"] == 8
        assert row["absent_ordinates"] == 1
        assert row["unresolved_ordinate_details"][0]["z_m"] == pytest.approx(2.7)

