"""One coupled surface: cross-view pull, robust fit and exact boundaries."""
import copy

import numpy as np
import pytest

from vessel_reconstruction import fairing


def hull():
    sections = []
    for x in np.linspace(0, 100, 11):
        z = np.linspace(0, 8, 61)
        y = (2 + 3 * np.sin(np.pi * x / 100)) * np.sqrt(z / 8)
        sections.append({"id": f"s{x:g}", "x_m": float(x), "source_label": "traced",
                         "points_yz_m": np.column_stack([y, z]).tolist()})
    return sections


def evidence(sections):
    points = []
    for x in np.linspace(0, 100, 81):
        for z in (1., 2., 3., 4., 5., 6., 7.):
            points.append({"view": "half_breadth_plan", "target": "waterline", "curve_id": f"wl{z}",
                           "x_m": float(x), "y_m": float((2 + 3 * np.sin(np.pi * x / 100)) * np.sqrt(z / 8)),
                           "z_m": z, "source_label": "traced", "confidence": 1.})
        for target, z in (("keel", 0.), ("top", 8.)):
            points.append({"view": "profile", "target": target, "curve_id": target, "x_m": float(x),
                           "y_m": None, "z_m": z, "source_label": "traced", "confidence": 1.})
    return {"points": points, "half_beam_m": 5., "coverage": {}}


def new_fit(sections, observations, **options):
    return fairing.fair_sections(sections, evidence=observations, **options)


def breadth(rows, sid, z=4.):
    p = np.asarray(next(s for s in rows if s["id"] == sid)["points_yz_m"])
    return np.interp(z, p[:, 1], p[:, 0])


def test_joint_fit_rejects_a_bad_cell_with_fixed_other_views_and_preserves_inputs():
    sections = hull()
    observed = evidence(sections)
    snapshot = copy.deepcopy((sections, observed))
    base, report = new_fit(sections, observed)
    assert report["moves_by_view"]["body_plan"]["traced"]["within_tolerance"] >= .95
    bad = copy.deepcopy(sections)
    p = np.asarray(bad[5]["points_yz_m"])
    p[:, 0] += .2 * np.maximum(1 - abs(p[:, 1] - 4) / .4, 0)
    bad[5]["points_yz_m"] = p.tolist()
    result, changed_report = new_fit(bad, observed)
    assert (sections, observed) == snapshot
    assert abs(breadth(result, "s50") - breadth(base, "s50")) < .25 * .2
    assert report["method"].startswith("three_view")
    assert changed_report["engineering_approved"] is False
    assert any(g["section_id"] == "s50" for g in changed_report["check_items"])
    assert set(report["moves_by_view"]) == {"body_plan", "half_breadth_plan", "profile"}


def test_all_boundaries_are_exact_and_half_stations_use_profile():
    sections = hull()
    result, report = new_fit(sections, evidence(sections))
    by_id = {s["id"]: s for s in result}
    for s in sections:
        assert by_id[s["id"]]["points_yz_m"][0] == s["points_yz_m"][0]
        assert by_id[s["id"]]["points_yz_m"][-1] == s["points_yz_m"][-1]
    assert by_id["s0"]["points_yz_m"] == sections[0]["points_yz_m"]
    assert by_id["s100"]["points_yz_m"] == sections[-1]["points_yz_m"]
    added = [s for s in result if s["id"] not in {s["id"] for s in sections}]
    assert [s["x_m"] for s in added] == [5., 95.]
    assert all(s["source_label"] == "interpolated" for s in added)
    assert report["hard_boundary_max_move_m"] == 0.


def test_plan_weight_and_source_label_change_the_fit_between_stations():
    sections = hull()
    observed = evidence(sections)
    for point in observed["points"]:
        if point["view"] == "half_breadth_plan":
            point["y_m"] += .15 * np.sin(np.pi * point["x_m"] / 100)
    light, _ = new_fit(sections, observed, plan_weight=.5)
    heavy, _ = new_fit(sections, observed, plan_weight=8.)
    assert breadth(heavy, "s50") > breadth(light, "s50") + .01
    for point in observed["points"]:
        point["source_label"] = "ai_inferred"
    weak, _ = new_fit(sections, observed, plan_weight=8.)
    assert breadth(weak, "s50") < breadth(heavy, "s50")


def test_profile_evidence_changes_domain_between_fixed_station_edges():
    sections = hull()
    observed = evidence(sections)
    for point in observed["points"]:
        if point["view"] == "profile" and point["target"] == "top" and 0 < point["x_m"] < 10:
            point["z_m"] += .2
    result, report = new_fit(sections, observed)
    half = next(s for s in result if s["x_m"] == 5.)
    assert half["points_yz_m"][-1][1] > 8.05
    assert report["moves_by_view"]["profile"]["traced"]["points"] == 162


def test_absent_cross_views_keep_station_only_fallback_explicit():
    sections = hull()
    result, report = new_fit(sections, {"points": [], "half_beam_m": 5., "coverage": {}})
    old, _ = fairing.fair_sections(sections)
    assert result == old
    assert report["three_view_applied"] is False
    assert "cross-view evidence" in report["three_view_reason"]
    widened = copy.deepcopy(sections)
    widened[5]["points_yz_m"][-1][0] += .25
    _, frozen = new_fit(widened, {"points": [], "half_beam_m": 5., "coverage": {}})
    assert frozen["parameters"]["half_beam_m"] == 5.
    assert frozen["parameters"]["huber_scale_m"] == .05


def test_runtime_defaults_match_the_frozen_fit_only_choice():
    import inspect
    import json
    from pathlib import Path
    from vessel_reconstruction import three_view_fairing
    choice = json.loads(Path("benchmarks/hull_fairing/three_view_choice.json").read_text())
    defaults = inspect.signature(fairing.fair_sections).parameters
    assert defaults["plan_weight"].default == three_view_fairing.DEFAULT_PLAN_WEIGHT == choice["plan_weight"]
    assert defaults["fairness"].default == three_view_fairing.FAIRNESS == choice["fairness"]
