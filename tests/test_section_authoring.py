"""Model-authored sections (propose_section): forms, bounds, fairing, labels."""
from __future__ import annotations

import json

import numpy as np
import pytest

from draft_fixture import draft_drawing
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.draft import (DRAFT_STATUS, check_draft, check_guess, make_guesses,
                                         prepare_draft_sections, section_sources)
from vessel_reconstruction.run_record import verify_run
from vessel_reconstruction.schema import validate_spec
from vessel_reconstruction.section_authoring import (CURVE_SAMPLES, ProposalError, author_section,
                                                     check_authored, check_proposal_arguments)

LIMITS = {"x_m": 2.0, "z_limits": (0.0, 3.0)}
OFFSETS = [[0.0, 0.0], [0.5, 0.6], [1.0, 0.9], [2.0, 1.1], [3.0, 1.2]]


def half_breadths(offsets=OFFSETS, **extra):
    return {"form": "half_breadths", "basis": "Neighbours and the plan view.", "offsets_m": offsets, **extra}


def heights_and_breadths(result):
    points = np.asarray(result["points_yz_m"])
    return points[:, 1], points[:, 0]


def test_half_breadths_become_a_fair_increasing_curve_closed_at_the_keel():
    result = author_section(half_breadths(), **LIMITS)
    z, y = heights_and_breadths(result)
    assert len(z) == CURVE_SAMPLES and np.all(np.diff(z) > 0)
    assert z[0] == 0 and z[-1] == 3
    assert y[0] == 0 and result["checks"]["closure"] == "keel_on_centreline"
    # The faired curve stays near the model's offsets and never overshoots them.
    assert abs(np.interp(2.0, z, y) - 1.1) < 0.03 and y.max() <= 1.2 + 1e-9
    # Out-of-order input gives the same curve.
    assert author_section(half_breadths(list(reversed(OFFSETS))), **LIMITS)["points_yz_m"] == result["points_yz_m"]


def test_half_breadths_are_clamped_with_warnings_instead_of_refused():
    offsets = [[-1.0, 0.2], [0.5, -0.1], [1.0, 0.9], [2.0, 3.0], [4.0, 1.2]]
    result = author_section(half_breadths(offsets), **LIMITS, half_beam_limit=1.5)
    z, y = heights_and_breadths(result)
    assert z[0] == 0 and z[-1] == 3 and y.min() >= 0 and y.max() <= 1.5
    text = " ".join(result["warnings"])
    for words in ("declared section range", "Negative half-breadths", "declared half beam"):
        assert words in text
    # A flat bottom is closed to the centreline by the build, and said so.
    flat = author_section(half_breadths([[0, .8], [1, 1.], [1.5, 1.1], [2, 1.15], [3, 1.2]]), **LIMITS)
    assert flat["checks"]["closure"] == "flat_bottom_to_centreline"
    # The declared depth lowers the top of the curve.
    shallow = author_section(half_breadths(), **LIMITS, depth_limit=2.5)
    assert heights_and_breadths(shallow)[0][-1] == 2.5


@pytest.mark.parametrize("arguments", [
    half_breadths(OFFSETS[:4]),
    half_breadths(OFFSETS * 5),
    half_breadths([[0, 0]] + [[1, float("nan")]] * 4),
    half_breadths(basis=""),
    {**half_breadths(), "basis": "x" * 301},
    half_breadths(fullness=1.0),
    {"form": "blend", "basis": "b", "fullness": 2.0},
    {"form": "standard_form", "basis": "b", "shape": "W", "beam_m": 4, "draft_m": 2},
    {"form": "standard_form", "basis": "b", "shape": "U", "draft_m": 2},
    {"form": "standard_form", "basis": "b", "shape": "V", "beam_m": 4, "draft_m": 2, "deadrise_deg": 80},
    {"form": "spline", "basis": "b"},
])
def test_proposal_bounds_are_strict(arguments):
    with pytest.raises(ProposalError):
        check_proposal_arguments(arguments)


def test_a_proposal_without_any_height_in_range_is_refused():
    with pytest.raises(ProposalError):
        author_section(half_breadths([[5, 1], [6, 1], [7, 1], [8, 1], [9, 1]]), **LIMITS)


def test_blend_interpolates_neighbours_by_station_and_scales_by_fullness():
    lower = (0.0, [[0.0, 0.0], [1.0, 1.5], [1.0, 3.0]])
    upper = (4.0, [[0.0, 0.0], [2.0, 1.5], [2.0, 3.0]])
    plain = author_section({"form": "blend", "basis": "Halfway between s1 and s3."}, **LIMITS, lower=lower, upper=upper)
    z, y = heights_and_breadths(plain)
    assert np.interp(3.0, z, y) == pytest.approx(1.5)
    fuller = author_section({"form": "blend", "basis": "Fuller.", "fullness": 1.2}, **LIMITS, lower=lower, upper=upper)
    assert np.interp(3.0, *heights_and_breadths(fuller)) == pytest.approx(1.8)
    single = author_section({"form": "blend", "basis": "Only s1."}, **LIMITS, lower=lower)
    assert "one neighbouring" in " ".join(single["warnings"])
    with pytest.raises(ProposalError):
        author_section({"form": "blend", "basis": "None."}, **LIMITS)
    # A much fuller or finer section than its neighbours is reported, not refused.
    odd = author_section(half_breadths([[0, 0], [.5, 3], [1, 3], [2, 3], [3, 3]]), **LIMITS, lower=lower, upper=upper)
    assert "unfair" in " ".join(odd["warnings"])


def test_standard_forms_have_the_declared_beam_bilge_and_deadrise():
    u = author_section({"form": "standard_form", "basis": "Typical midship U section.", "shape": "U",
                        "beam_m": 4.0, "draft_m": 2.0, "bilge_radius_m": 0.6}, **LIMITS)
    z, y = heights_and_breadths(u)
    assert y[-1] == pytest.approx(2.0) and z[-1] == 3.0
    assert u["checks"]["closure"] == "flat_bottom_to_centreline"  # flat floor, rounded bilge
    assert y[0] == pytest.approx(1.4, abs=0.02)  # half beam minus bilge radius
    v = author_section({"form": "standard_form", "basis": "Fine forward V section.", "shape": "V",
                        "beam_m": 4.0, "draft_m": 2.0, "deadrise_deg": 30}, **LIMITS)
    z, y = heights_and_breadths(v)
    assert v["checks"]["closure"] == "keel_on_centreline"
    # Hard chine at the half beam, 2 tan(30 deg) above the keel.
    chine = 2.0 * np.tan(np.radians(30))
    assert np.interp(chine / 2, z, y) == pytest.approx(1.0, abs=0.05)
    big = author_section({"form": "standard_form", "basis": "Too round.", "shape": "U", "beam_m": 4.0,
                          "draft_m": 1.0, "bilge_radius_m": 5.0}, **LIMITS)
    assert "Bilge radius reduced" in " ".join(big["warnings"])


def test_authored_record_is_checked_and_accepted_only_in_a_draft(tmp_path):
    record = {"source_label": "ai_inferred", "basis": "Neighbours.",
              "points_yz_m": author_section(half_breadths(), **LIMITS)["points_yz_m"]}
    assert check_authored(record)
    assert not check_authored({**record, "source_label": "traced"})
    assert not check_authored({**record, "points_yz_m": record["points_yz_m"][::-1]})
    assert not check_authored({**record, "extra": 1})
    path, spec = draft_drawing(tmp_path, count=3)
    spec["sections"][1]["authored"] = record
    errors = validate_spec(spec, tmp_path)
    assert [e["kind"] for e in errors] == ["authored_outside_draft"]
    spec["draft"] = {"status": DRAFT_STATUS, "guesses": make_guesses(spec["sections"], {}, {})}
    assert validate_spec(spec, tmp_path) == []


def test_section_sources_label_and_count_every_section():
    sections = [{"id": "s0", "x_m": 0., "points_yz_m": [[1., 0.], [1., 1.], [0., 2.], [1., 3.], [1., 4.]]},
                {"id": "s1", "x_m": 2., "points_yz_m": [[1., z] for z in range(5)], "source_label": "ai_inferred",
                 "evidence": {"authored_basis": "Neighbours."}},
                {"id": "s3", "x_m": 6., "points_yz_m": [[1., z] for z in range(5)]}]
    declared = [{"id": s, "x_m": x} for s, x in (("s0", 0.), ("s1", 2.), ("s2", 4.), ("s3", 6.))]
    prepared, _ = prepare_draft_sections(sections, declared)
    labels = {s["id"]: s["source_label"] for s in prepared}
    assert labels == {"s0": "repaired", "s1": "ai_inferred", "s2": "interpolated", "s3": "traced"}
    sources = section_sources(prepared, [{"section_id": "s4", "kind": "dropped_end"}])
    assert sources["counts"] == {"repaired": 1, "ai_inferred": 1, "interpolated": 1, "traced": 1, "omitted": 1}
    assert sources["sections"][1] == {"section_id": "s1", "label": "ai_inferred", "basis": "Neighbours."}


def inspected_task(tmp_path, blank=("s2",)):
    path, _ = draft_drawing(tmp_path / "input", count=4, blank=blank)
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {})
    unique = [{"section_id": s["section_id"], "candidate_id": s["grid_evidence"]["unique_non_grid_candidate_id"]}
              for s in observed["sections"] if s["grid_evidence"].get("unique_non_grid_candidate_id")]
    assert tools.execute("select_contours", {"selections": unique})["ok"]
    return tools


def test_propose_section_makes_an_open_ai_inferred_guess_with_an_overlay(tmp_path):
    tools = inspected_task(tmp_path)
    before = tools.generation_id
    refused = tools.execute("propose_section", {"section_id": "s2", "form": "blend", "basis": "b", "fullness": 9})
    assert not refused["ok"] and refused["error_code"] == "invalid_tool_arguments"
    refused = tools.execute("propose_section", {"section_id": "s2", "form": "blend", "basis": "Between s1 and s3.",
                                                "replaces": "trace-unknown"})
    assert not refused["ok"] and refused["error_code"] == "unknown_replaced_candidate"
    proposed = tools.execute("propose_section", {"section_id": "s2", "form": "blend",
                                                 "basis": "No ink at s2; blended from s1 and s3."})
    assert proposed["ok"], proposed
    assert proposed["source_label"] == "ai_inferred" and proposed["guess"]["kind"] == "model_authored"
    assert proposed["artifacts"][0]["evidence_kind"] == "authored_section"
    assert (tools.task_dir / proposed["artifacts"][0]["path"]).is_file()
    assert tools.generation_id != before
    guess = next(g for g in tools.open_guesses if g["section_id"] == "s2")
    assert check_guess(guess) and guess["reason"].startswith("ai_inferred: ")
    # The draft revision carries the curve; the strict schema accepts it there.
    guesses = make_guesses(tools.spec["sections"], tools.state["selected"], tools.state["catalog"],
                           tools.state.get("model_choices"), tools.state["authored_sections"])
    assert [g["kind"] for g in guesses] == ["best_candidate", "model_authored"]
    tools.state["guesses"] = guesses
    spec = json.loads(tools._write_revision().read_text())
    s2 = next(s for s in spec["sections"] if s["id"] == "s2")
    assert s2["authored"]["source_label"] == "ai_inferred" and "contour_selection" not in s2
    assert check_draft(spec["draft"])


def test_propose_section_that_replaces_a_trace_is_ai_corrected(tmp_path):
    tools = inspected_task(tmp_path, blank=())
    trace = tools.state["selected"]["s1"]
    proposed = tools.execute("propose_section", {
        "section_id": "s1", "form": "standard_form", "basis": "The traced line is a grid line; typical U form.",
        "shape": "U", "beam_m": 5.0, "draft_m": 2.0, "replaces": trace})
    assert proposed["ok"], proposed
    assert proposed["source_label"] == "ai_corrected"
    assert "s1" not in tools.state["selected"]
    assert any(c["candidate_id"] == trace for c in tools.state["catalog"]["s1"]["candidates"])
    # Proposing again keeps only the newest proposal in the catalog.
    again = tools.execute("propose_section", {"section_id": "s1", "form": "half_breadths", "offsets_m": OFFSETS,
                                              "basis": "Read the offsets from the plan view."})
    assert again["ok"] and again["source_label"] == "ai_corrected"  # still replaces the trace
    authored = [c for c in tools.state["catalog"]["s1"]["candidates"] if "authored" in c]
    assert [c["candidate_id"] for c in authored] == [again["candidate_id"]]


@pytest.mark.cad
def test_draft_with_an_ai_inferred_section_builds_labelled_cad(tmp_path):
    tools = inspected_task(tmp_path)
    assert tools.execute("propose_section", {"section_id": "s2", "form": "blend",
                                             "basis": "No ink at s2; blended from s1 and s3."})["ok"]
    built = tools.execute("build_draft", {})
    assert built["ok"], built
    assert built["section_sources"]["counts"].get("ai_inferred") == 1
    labels = {row["section_id"]: row["label"] for row in built["section_sources"]["sections"]}
    assert labels["s2"] == "ai_inferred"
    assert labels["s1"] in ("traced", "repaired") and labels["s3"] in ("traced", "repaired")
    run = tmp_path / "task" / built["candidate"]["path"]
    assert verify_run(run)["valid"]
    record = json.loads((run / "result.json").read_text())
    assert [s["id"] for s in record["sections"]] == ["s0", "s1", "s2", "s3"]
    assert record["exports"]["step"] == "model-draft.step"
    rendered = tools.execute("render_candidate", {"view": "body"})
    assert rendered["ok"], rendered
