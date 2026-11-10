"""Benchmark-only frame alignment, independent of development truth."""
import copy

import numpy as np
import pytest

from benchmarks.hull_fairing import station_frame


def profile(x):
    return .002 * x ** 2 + .2 * np.sin(x / 7), 5 + .003 * (x - 30) ** 2


def sample():
    sections = []
    for i, x in enumerate(np.linspace(5, 55, 9)):
        low, high = profile(x)
        sections.append({"id": f"s{i}", "x_m": float(x), "source_label": "traced",
                         "points_yz_m": [[0., low], [2., (low + high) / 2], [3., high]]})
    points = []
    for x in np.linspace(0, 60, 601):
        for target, z in zip(("keel", "top"), profile(x)):
            points.append({"view": "profile", "target": target, "curve_id": target,
                           "x_m": float(x), "z_m": float(z), "y_m": None,
                           "source_label": "traced", "confidence": 1.})
    return sections, {"points": points, "half_beam_m": 3., "coverage": {}}


def test_bounded_endpoints_move_towards_profile_and_remap_interior():
    sections, evidence = sample()
    for section in sections:
        for point in section["points_yz_m"]:
            point[1] -= .2
    original = copy.deepcopy((sections, evidence))
    result, report = station_frame.align_sections(sections, evidence, "bounded_endpoints", .025)
    for source, adjusted in zip(sections, result):
        assert adjusted["x_m"] == source["x_m"]
        delta = np.asarray(adjusted["points_yz_m"]) - source["points_yz_m"]
        np.testing.assert_allclose(delta[:, 0], 0)
        np.testing.assert_allclose(delta[:, 1], .075, atol=1e-10)
    assert report["max_endpoint_move_m"] == pytest.approx(.075)
    assert (sections, evidence) == original


def test_global_registration_recovers_uniform_scale_and_both_datums():
    truth, evidence = sample()
    scale, dx, dz = 1.03, .6, .15
    sections = copy.deepcopy(truth)
    for section in sections:
        section["x_m"] = (section["x_m"] - dx) / scale
        section["points_yz_m"] = [[y / scale, (z - dz) / scale] for y, z in section["points_yz_m"]]
    original = copy.deepcopy(sections)
    result, report = station_frame.align_sections(sections, evidence, "registered_frame")
    for expected, actual in zip(truth, result):
        assert actual["x_m"] == pytest.approx(expected["x_m"], abs=.002)
        np.testing.assert_allclose(actual["points_yz_m"], expected["points_yz_m"], atol=.002)
    assert report["scale"] == pytest.approx(scale, abs=1e-4)
    assert report["x_offset_m"] == pytest.approx(dx, abs=.002)
    assert report["z_offset_m"] == pytest.approx(dz, abs=.002)
    assert report["residual_rms_after_m"] < report["residual_rms_before_m"] / 100
    assert sections == original


def test_missing_profile_does_not_invent_an_alignment():
    sections, evidence = sample()
    evidence["points"] = []
    result, report = station_frame.align_sections(sections, evidence, "bounded_endpoints", .01)
    assert result == sections
    assert not report["applied"]
    assert "profile" in report["reason"]


def test_bounded_endpoints_do_not_extrapolate_and_keep_positive_heights():
    sections, evidence = sample()
    sections[0]["x_m"] = -1.
    result, report = station_frame.align_sections(sections, evidence, "bounded_endpoints", .05)
    assert result[0] == sections[0]
    assert report["uncovered_endpoints"] == 2
    assert all(np.all(np.diff(np.asarray(s["points_yz_m"])[:, 1]) > 0) for s in result)


def test_candidate_selection_keeps_failed_cases_and_prefers_gate_passes():
    failed = {"name": "failed", "scores": [{"passes": True, "rms_pct": 0., "volume_pct": 0.}, None]}
    sound = {"name": "sound", "scores": [{"passes": True, "rms_pct": 1., "volume_pct": 1.}] * 2}
    assert station_frame.select_candidate([failed, sound])["name"] == "sound"


def test_fit_population_rejects_check_and_missing_cases():
    protocol = {"fit_cases": ["a-L0", "b-L0"]}
    good = [{"case": case, "split": "fit", "delivered": True} for case in protocol["fit_cases"]]
    station_frame.require_fit_population(good, protocol)
    with pytest.raises(ValueError):
        station_frame.require_fit_population(good + [{"case": "a-L1", "split": "check", "delivered": True}], protocol)
    with pytest.raises(ValueError):
        station_frame.require_fit_population(good[:1], protocol)


def test_joint_report_counts_frame_displacement_from_original_evidence():
    sections, evidence = sample()
    # Flat spans keep the synthetic joint fit simple while testing datum movement.
    for section in sections:
        section["points_yz_m"] = [[0., -.2], [2., 2.3], [3., 4.8]]
    for point in evidence["points"]:
        point["z_m"] = 0. if point["target"] == "keel" else 5.
    snapshot = copy.deepcopy((sections, evidence))
    result, report = station_frame.fit_sections(sections, evidence, "bounded_endpoints", .05)
    by_id = {s["id"]: s for s in result}
    assert report["hard_boundary_max_move_m"] == pytest.approx(.15)
    assert report["moves_by_view"]["body_plan"]["traced"]["median_m"] >= .15 - 1e-9
    assert any(p["view"] == "body_plan" for p in report["point_excesses"])
    assert by_id["s0"]["points_yz_m"][0][1] == pytest.approx(-.05)
    assert (sections, evidence) == snapshot
