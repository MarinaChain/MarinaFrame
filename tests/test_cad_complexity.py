"""Draft builds simplify over-complex traced curves to fit the CAD knot limit.

Traced drawing curves carry pixel jitter. With the 1 mm bound almost every
traced point is a knot, and stations with different point grids share few
normalized heights, so the knot union exceeds the 513-knot CAD limit. A strict
build still refuses; a draft raises the bound step by step and records it.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from vessel_reconstruction.geometry import (MAX_COMMON_KNOTS, GeometryError, approximation_summary,
                                            normalize_sections)
from vessel_reconstruction.run_record import _check_complexity_fit

# Pixel jitter of a traced curve; larger than the 1 mm default bound.
JITTER_M = .004


def jittered_sections(xs, point_counts, *, depth_m=3.):
    """Smooth half-sections plus deterministic jitter, each on its own height grid."""
    rng = np.random.default_rng(7)
    sections = []
    for index, (x, count) in enumerate(zip(xs, point_counts)):
        z = np.linspace(0., depth_m, count)
        breadth = 1. + .5 * np.sqrt(z / depth_m) + rng.uniform(-JITTER_M, JITTER_M, count)
        sections.append({"id": f"s{index}", "x_m": float(x), "points_yz_m": np.column_stack((breadth, z)).tolist(),
                         "coverage": 1., "confidence": .5, "evidence": {}})
    return sections


def _source_deviation(section):
    """Largest half-breadth difference between the CAD polyline and the traced curve."""
    source, cad = np.asarray(section["points_yz_m"]), np.asarray(section["cad_points_yz_m"])
    heights = np.unique(np.concatenate((source[:, 1], cad[:, 1])))
    return float(np.max(np.abs(np.interp(heights, cad[:, 1], cad[:, 0])
                               - np.interp(heights, source[:, 1], source[:, 0]))))


OVER_COMPLEX = dict(xs=(0., 2., 4., 6.), point_counts=(397, 401, 409, 419))


def test_strict_build_still_refuses_an_over_complex_curve():
    with pytest.raises(GeometryError, match="CAD complexity limit"):
        normalize_sections(jittered_sections(**OVER_COMPLEX))


def test_draft_fit_simplifies_within_the_recorded_tolerance():
    sections = jittered_sections(**OVER_COMPLEX)
    normalized = normalize_sections(copy.deepcopy(sections), fit_complexity=True)
    knots = len(normalized[0]["cad_points_yz_m"])
    assert knots <= MAX_COMMON_KNOTS
    for section in normalized:
        record = section["cad_approximation"]
        allowed = record["maximum_allowed_half_breadth_deviation_m"]
        assert record["complexity_fit"]["requested_maximum_deviation_m"] == .001
        assert .001 < allowed < 4 * JITTER_M
        assert record["common_knot_count"] == knots
        # Independent check of the declared bound against the traced points.
        assert _source_deviation(section) == pytest.approx(record["maximum_half_breadth_deviation_m"], abs=1e-12)
        assert record["maximum_half_breadth_deviation_m"] <= allowed + 1e-10
    summary = approximation_summary(normalized)
    assert summary["complexity_fit"] == normalized[0]["cad_approximation"]["complexity_fit"]
    # The observations are kept unchanged; only the CAD polyline is simplified.
    assert [s["points_yz_m"] for s in normalized] == [s["points_yz_m"] for s in sections]


def test_draft_fit_keeps_the_requested_bound_when_the_curves_already_fit():
    sections = jittered_sections((0., 2., 4.), (40, 40, 40))
    assert normalize_sections(copy.deepcopy(sections), fit_complexity=True) == normalize_sections(sections)


def test_draft_fit_also_meets_the_face_budget():
    sections = jittered_sections(np.arange(150.), [60] * 150)
    normalized = normalize_sections(sections, fit_complexity=True)
    assert normalized[0]["cad_approximation"]["estimated_face_count"] <= 20_000


def test_only_a_draft_record_may_raise_the_bound():
    fit = {"requested_maximum_deviation_m": .001, "reason": "fit"}
    _check_complexity_fit({"complexity_fit": fit}, .02, draft=True)
    for record, allowed, draft in (({"complexity_fit": fit}, .02, False),
                                   ({}, .02, True),
                                   ({"complexity_fit": fit}, .001, True),
                                   ({"complexity_fit": {**fit, "requested_maximum_deviation_m": .02}}, .03, True),
                                   ({"complexity_fit": {**fit, "extra": 1}}, .02, True)):
        with pytest.raises(ValueError):
            _check_complexity_fit(record, allowed, draft)


@pytest.mark.cad
def test_over_complex_draft_builds_a_verified_solid_but_strict_blocks(tmp_path, monkeypatch):
    from draft_fixture import draft_drawing
    from vessel_reconstruction import ingest
    from vessel_reconstruction.draft import DRAFT_STATUS, make_guesses
    from vessel_reconstruction.pipeline import reconstruct
    from vessel_reconstruction.run_record import verify_run
    path, spec = draft_drawing(tmp_path / "input", count=4)
    sections = jittered_sections([s["x_m"] for s in spec["sections"]], OVER_COMPLEX["point_counts"])
    monkeypatch.setattr(ingest, "extract_sections",
                        lambda *args: {"sections": copy.deepcopy(sections), "gaps": []})
    strict = reconstruct(path, tmp_path / "strict")
    assert strict["status"] == "blocked"
    assert any("CAD complexity limit" in g["message"] for g in strict["gaps"])
    spec["draft"] = {"status": DRAFT_STATUS, "guesses": make_guesses(spec["sections"], {}, {})}
    path.write_text(json.dumps(spec))
    draft = reconstruct(path, tmp_path / "draft")
    assert draft["status"] == "review_required", draft["gaps"]
    simplified = [g for g in draft["gaps"] if g["kind"] == "draft_simplified_curve"]
    assert {g["section_id"] for g in simplified} == {s["id"] for s in sections}
    assert all(g["severity"] == "warning" and " mm " in g["message"] for g in simplified)
    assert draft["metrics"]["geometry_approximation"]["common_knot_count"] <= MAX_COMMON_KNOTS
    assert verify_run(tmp_path / "draft")["valid"]
