"""Cross-station fairness check (D1): the section that breaks the hull is named."""
from __future__ import annotations

import copy
import json

import numpy as np
from draft_fixture import draft_drawing
from vessel_reconstruction.draft import DRAFT_STATUS, make_guesses
from vessel_reconstruction.fairness import check_fairness, fairness_warnings

STATIONS = np.arange(10., 91., 10.)
LENGTH, HALF_BEAM, DEPTH = 100., 8., 10.


def _hull_section(x, scale=1., top=DEPTH):
    """A smooth hull: full midbody, fine ends, a round bilge; 41 points keel to top."""
    fullness = 1. - (2. * x / LENGTH - 1.) ** 4
    z = np.linspace(0., top, 41)
    y = scale * HALF_BEAM * fullness * np.sqrt(np.clip(z / DEPTH, 0., 1.)) ** .5
    return np.column_stack([y, z]).tolist()


def _hull(**changes):
    sections = [{"id": f"s{i:02d}", "x_m": float(x), "points_yz_m": _hull_section(x)}
                for i, x in enumerate(STATIONS, 1)]
    for section_id, points in changes.items():
        next(s for s in sections if s["id"] == section_id)["points_yz_m"] = points
    return sections


def test_a_fair_hull_flags_nothing():
    report = check_fairness(_hull())
    assert report["status"] == "checked" and report["outliers"] == []
    assert all(not entry["flagged"] and entry["score"] <= 1. for entry in report["sections"])
    assert fairness_warnings(report) == []


def test_a_straight_grid_line_is_named_first_with_a_fix():
    grid_line = [[5., z] for z in np.linspace(0., DEPTH, 20)]
    report = check_fairness(_hull(s05=grid_line))
    top = report["sections"][0]
    assert report["outliers"] == ["s05"]
    assert top["feature"] == "straight_line" and top["rank"] == 1
    assert "vertical straight line" in top["reason"] and "propose_section" in top["suggestion"]


def test_a_too_wide_section_is_named_with_the_expected_range():
    report = check_fairness(_hull(s04=_hull_section(40., scale=1.5)))
    top = report["sections"][0]
    assert report["outliers"] == ["s04"]
    assert top["feature"] == "half_breadth"
    assert "wider than its neighbours (s03, s05)" in top["reason"]
    low, high = top["expected_range_m"]
    assert low < HALF_BEAM < high < top["observed_m"]


def test_a_too_wide_end_section_is_named():
    # 617-L3 s01: an end section several times wider than its neighbour.
    report = check_fairness(_hull(s01=_hull_section(10., scale=4.)))
    assert report["outliers"] == ["s01"]
    assert "(s02, s03)" in report["sections"][0]["reason"]


def test_a_partial_stroke_is_named_as_partial():
    report = check_fairness(_hull(s06=_hull_section(60., top=.5 * DEPTH)))
    top = report["sections"][0]
    assert report["outliers"] == ["s06"] and top["feature"] == "top_height"
    assert "partial stroke" in top["suggestion"]


def test_a_bad_neighbour_does_not_flag_good_sections():
    # Two bad sections: each is named, the good sections next to them are not.
    report = check_fairness(_hull(s03=_hull_section(30., scale=1.6), s07=_hull_section(70., scale=.4)))
    assert sorted(report["outliers"]) == ["s03", "s07"]


def test_warnings_never_block():
    report = check_fairness(_hull(s04=_hull_section(40., scale=1.5)))
    warnings = fairness_warnings(report)
    assert [(w["kind"], w["section_id"], w["severity"]) for w in warnings] == [("draft_fairness_outlier", "s04", "warning")]
    assert "s04 half-breadth" in warnings[0]["message"]


def test_too_few_sections_are_not_checked():
    report = check_fairness(_hull()[:3])
    assert report["status"] == "too_few_sections" and report["outliers"] == [] and report["sections"] == []


def test_draft_build_carries_fairness_diagnostics_and_warnings(tmp_path, monkeypatch):
    """The draft build path adds the report and its warnings; CAD is stubbed out."""
    from vessel_reconstruction import ingest, pipeline
    from vessel_reconstruction.errors import GeometryError

    path, spec = draft_drawing(tmp_path / "input", count=5)
    curved = [[.5 + .25 * z, z] for z in np.linspace(0., 3., 13)]
    sections = [{"id": s["id"], "x_m": s["x_m"], "points_yz_m": curved, "coverage": 1., "confidence": .5,
                 "evidence": {}} for s in spec["sections"]]
    sections[2]["points_yz_m"] = [[2., z] for z in np.linspace(0., 3., 13)]  # a grid line
    monkeypatch.setattr(ingest, "extract_sections", lambda *args: {"sections": copy.deepcopy(sections), "gaps": []})
    seen = {}

    def stop_before_cad(built_sections, **kwargs):
        seen["sections"] = built_sections
        raise GeometryError("CAD stubbed out in this test.")

    monkeypatch.setattr(pipeline, "build_hull", stop_before_cad)
    spec["draft"] = {"status": DRAFT_STATUS, "guesses": make_guesses(spec["sections"], {}, {})}
    path.write_text(json.dumps(spec))
    result = pipeline.reconstruct(path, tmp_path / "draft")
    fairness = result["diagnostics"]["fairness"]
    assert fairness["status"] == "checked" and fairness["outliers"] == ["s2"]
    warning = next(g for g in result["gaps"] if g["kind"] == "draft_fairness_outlier")
    assert warning["section_id"] == "s2" and warning["severity"] == "warning"
    # The check only reports: the sections passed to the CAD build are unchanged.
    assert seen["sections"][2]["points_yz_m"] == sections[2]["points_yz_m"]


def test_a_strict_build_has_no_fairness_report(tmp_path, monkeypatch):
    from vessel_reconstruction import ingest, pipeline
    from vessel_reconstruction.errors import GeometryError

    path, spec = draft_drawing(tmp_path / "input", count=5)
    curved = [[.5 + .25 * z, z] for z in np.linspace(0., 3., 13)]
    sections = [{"id": s["id"], "x_m": s["x_m"], "points_yz_m": curved, "coverage": 1., "confidence": .5,
                 "evidence": {}} for s in spec["sections"]]
    monkeypatch.setattr(ingest, "extract_sections", lambda *args: {"sections": copy.deepcopy(sections), "gaps": []})

    def stop_before_cad(*args, **kwargs):
        raise GeometryError("CAD stubbed out in this test.")

    monkeypatch.setattr(pipeline, "build_hull", stop_before_cad)
    result = pipeline.reconstruct(path, tmp_path / "strict")
    assert "fairness" not in result.get("diagnostics", {})
    assert not any(g["kind"] == "draft_fairness_outlier" for g in result["gaps"])
