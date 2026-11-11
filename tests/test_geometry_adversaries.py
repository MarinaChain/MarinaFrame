"""Feature preservation and actual STEP geometry, independent of round-trip volume."""
import numpy as np
import pytest

from benchmarks.audit_geometry_hardening import analytic_fixture, measured_sections, audit_step, FIXTURE_NAMES
from vessel_reconstruction.geometry import (build_hull, normalize_sections, export_geometry,
                                             approximation_summary, GeometryError)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_actual_step_local_error_at_stations_midstations_and_end_closures(tmp_path, name):
    fixture = analytic_fixture(name)
    shape, normalized = build_hull(measured_sections(fixture))
    export_geometry(shape, tmp_path)
    report = audit_step(tmp_path / "model.step", fixture)
    assert report["complete"], report
    assert report["passed"], report
    assert report["maximum_between_station_error_m"] <= fixture["maximum_error_gate_m"]
    assert report["maximum_station_error_m"] <= fixture["maximum_error_gate_m"]
    assert all(cut["requested_ordinates"] == cut["compared_ordinates"] for cut in report["cuts"])
    assert any(cut["closure_endpoints_compared"] for cut in report["cuts"])
    summary = approximation_summary(normalized)
    assert summary["maximum_half_breadth_deviation_m"] <= .001 + 1e-10
    assert summary["maximum_height_weighted_rms_deviation_m"] <= .001 + 1e-10
    if name == "off_grid_narrow_peak":
        assert report["reference_metrics"]["volume_m3"] == pytest.approx(81.25)
        assert report["actual_reimported_step_metrics"]["beam_m"] == pytest.approx(6.)


def test_legacy_samples_argument_is_a_minimum_not_a_feature_erasing_cap():
    sections = measured_sections(analytic_fixture("off_grid_narrow_peak"))
    normalized = normalize_sections(sections, samples=33)
    for section in normalized:
        points = np.asarray(section["cad_points_yz_m"])
        assert points[:, 0].max() == pytest.approx(3.)
        assert any(abs(z - .0625) < 1e-12 for z in points[:, 1])
        assert len(points) > 33


def test_complexity_limit_blocks_instead_of_coarsening_a_sawtooth():
    z = np.linspace(0, 4, 1025)
    y = np.where(np.arange(len(z)) % 2, 2., 1.)
    sections = [{"id": str(i), "x_m": x, "points_yz_m": np.column_stack((y, z)).tolist()}
                for i, x in enumerate([0., 4., 8.])]
    with pytest.raises(GeometryError, match="complexity limit"):
        normalize_sections(sections)


def test_total_face_budget_is_checked_before_native_cad():
    z = np.linspace(0, 4, 65)
    y = np.where(np.arange(len(z)) % 2, 2., 1.)
    sections = [{"id": str(i), "x_m": float(i), "points_yz_m": np.column_stack((y, z)).tolist()}
                for i in range(160)]
    with pytest.raises(GeometryError, match="estimated faces"):
        normalize_sections(sections)


def test_conflicting_duplicate_elevation_cannot_be_silently_dropped():
    sections = measured_sections(analytic_fixture("off_grid_narrow_peak"))
    sections[1]["points_yz_m"].append([9., .0625])
    with pytest.raises(GeometryError, match="duplicate"):
        normalize_sections(sections)


def test_tiny_zero_width_pinch_cannot_be_simplified_away():
    sections = [{"id": str(i), "x_m": float(i),
                 "points_yz_m": [[.0002, 0.], [.0001, .3], [0., .31], [.0001, .32], [.0002, 1.]]}
                for i in range(3)]
    with pytest.raises(GeometryError, match="pinch"):
        normalize_sections(sections)
