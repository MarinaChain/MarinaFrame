"""Source identity, adversarial tool boundary, and real bounded CAD observations."""
from copy import deepcopy
import json
from pathlib import Path
import threading

import numpy as np
from PIL import Image, ImageDraw
import pytest

from vessel_reconstruction.agent_tools import DomainTools, _grid_evidence
from vessel_reconstruction.ingest import extract_sections


def drawing(tmp_path, *, grid=True, faint_competitor=False, grid_only=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (600, 230), "white")
    draw = ImageDraw.Draw(image)
    sections = []
    for i in range(3):
        left, centre, bottom = i * 200, i * 200 + 20, 210
        if grid:
            for x in range(centre, centre + 151, 30):
                draw.line((x, 30, x, bottom), fill=(210,) * 3, width=1)
            for y in range(30, bottom + 1, 30):
                draw.line((centre, y, centre + 170, y), fill=(210,) * 3, width=1)
        if not grid_only:
            draw.line([(centre + 30 + .25 * (bottom - row), row) for row in range(30, bottom + 1)],
                      fill=(15,) * 3, width=3)
        if faint_competitor:
            draw.line((centre + 137, 30, centre + 137, bottom), fill=(207,) * 3, width=3)
        sections.append({"id": f"s{i}", "x_m": i * 2., "roi_px": [left + 10, 20, left + 195, 220],
                         "calibration": {"centerline_px": centre, "baseline_px": bottom, "pixels_per_metre": 60},
                         "z_min_m": 0., "z_max_m": 3., "evidence": "Independently specified pixel fixture."})
    image.save(tmp_path / "drawing.png")
    spec = {"schema_version": "1.0", "vessel_id": "agent-tools-fixture", "units": "m",
            "symmetry": "port_starboard", "symmetry_evidence": "Explicit symmetric test fixture assumption.",
            "end_closure": "flat_at_terminal_stations", "source": {"file": "drawing.png"}, "sections": sections}
    path = tmp_path / "spec.json"; path.write_text(json.dumps(spec))
    return path, spec


def test_grid_grammar_needs_both_axes_and_does_not_assign_semantic_identity():
    mask = np.zeros((181, 181), dtype=bool)
    mask[:, [30, 60, 90, 120, 150]] = True
    assert not _grid_evidence(mask, (0, 0))["lattice_detected"]
    mask[[0, 30, 60, 90, 120, 150, 180], :] = True
    result = _grid_evidence(mask, (10, 20))
    assert result["lattice_detected"]
    assert result["vertical_lines_px"] == [40, 70, 100, 130, 160]
    assert result["unique_non_grid_candidate_id"] is None
    mask[91, :] = True  # Stroke thickness, not another semantic object.
    assert _grid_evidence(mask, (0, 0))["lattice_detected"]


def test_inspection_is_source_bound_and_grid_proposal_keeps_alternatives(tmp_path):
    path, spec = drawing(tmp_path / "input")
    original = path.read_bytes()
    unassisted = extract_sections(spec, path.parent)
    assert unassisted["gaps"][0]["kind"] == "ambiguous_curve"
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {})
    assert observed["ok"], observed
    assert tools.describe()["catalog_ready"]
    assert observed["human_semantic_review_required"] and not observed["engineering_approved"]
    for section in observed["sections"]:
        assert section["retained_competing_count"] >= 3
        assert section["grid_evidence"]["lattice_detected"]
        assert section["grid_evidence"]["unique_non_grid_candidate_id"]
        assert all(not c["identity_certified"] for c in section["candidates"])
        assert all("contour_selection" not in c and "source_points_px" not in c for c in section["candidates"])
    assert all(not Path(a["path"]).is_absolute() and len(a["sha256"]) == 64 for a in observed["artifacts"])
    derivatives = [a for a in observed["artifacts"] if a.get("model_eligible")]
    assert derivatives and any(a.get("evidence_kind") == "source_page" for a in derivatives)
    original_hashes = {a["sha256"] for a in observed["artifacts"] if not a.get("model_eligible")}
    for artifact in derivatives:
        assert artifact["bytes"] <= 128 * 1024
        assert artifact["derivative_of_sha256"] in original_hashes
        with Image.open(tmp_path / "task" / artifact["path"]) as image:
            assert image.width <= 1024 and image.height <= 768
            assert image.width * image.height <= 1_048_576
    assert len(json.dumps(observed).encode()) <= 48 * 1024
    description = tools.describe()
    assert len(description["source_manifest_sha256"]) == 64
    assert description["inspected_sections"]
    assert path.read_bytes() == original
    assert extract_sections(spec, path.parent)["gaps"] == unassisted["gaps"]


def test_faint_real_alternative_is_retained_and_can_be_selected(tmp_path):
    path, _ = drawing(tmp_path / "input", faint_competitor=True)
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {"section_ids": ["s0"]})
    assert observed["ok"], observed
    section = observed["sections"][0]
    # The extra complete vertical may conservatively invalidate the lattice
    # spacing itself; either way it must suppress an automatic grid proposal.
    assert section["grid_evidence"]["unique_non_grid_candidate_id"] is None
    candidates = tools.state["catalog"]["s0"]["candidates"]
    faint = [c for c in candidates if all(abs(p[0] - 157) < 2 for p in c["contour_selection"]["anchors_px"])]
    assert faint, candidates
    selected = tools.execute("select_contours", {"selections": [{"section_id": "s0", "candidate_id": faint[0]["candidate_id"]}]})
    assert selected["ok"] and selected["alternatives_retained"]
    assert selected["human_semantic_review_required"] and not selected["engineering_approved"]
    assert selected["remaining_count"] == 2


def test_grid_only_is_not_a_supported_hull_hypothesis(tmp_path):
    path, _ = drawing(tmp_path / "input", grid_only=True)
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {"section_ids": ["s0"]})
    assert observed["ok"], observed
    assert observed["sections"][0]["grid_evidence"]["unique_non_grid_candidate_id"] is None


def test_fractional_calibration_corridor_spans_actual_trace_rows(tmp_path):
    path, spec = drawing(tmp_path / "input")
    for section in spec["sections"]:
        # Both calibrated endpoints are fractional and just inside the rounded
        # source row interval, the development failure that prompted this test.
        section.update(z_min_m=.004, z_max_m=2.9963)
    path.write_text(json.dumps(spec))
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {})
    choices = [{"section_id": s["section_id"], "candidate_id": s["grid_evidence"]["unique_non_grid_candidate_id"]}
               for s in observed["sections"]]
    selected = tools.execute("select_contours", {"selections": choices})
    assert selected["ok"], selected
    revision = tools.root / "revisions" / selected["revision_id"] / "spec.json"
    reconstructed = extract_sections(json.loads(revision.read_text()), revision.parent)
    assert not reconstructed["gaps"], reconstructed
    assert len(reconstructed["sections"]) == 3


def test_source_overlay_five_candidate_legends_do_not_overlap_footer(tmp_path):
    from vessel_reconstruction.agent_tools import _source_overlay
    image = np.full((90, 90, 3), 255, dtype=np.uint8)
    section = {"id": "legend-fixture", "x_m": 0, "roi_px": [0, 0, 90, 90],
               "calibration": {"centerline_px": 2, "baseline_px": 80, "pixels_per_metre": 20}}
    entry = {"section_id": section["id"], "retained_diagnostics": {}, "candidates": [
        {"candidate_id": f"candidate-{i}", "hypothesis": "visible source hypothesis",
         "source_points_px": [[10 + i * 10, 5], [10 + i * 10, 80]]} for i in range(5)]}
    target = tmp_path / "overlay.png"
    _source_overlay(image, section, entry, target)
    pixels = np.asarray(Image.open(target).convert("RGB"))
    rows = np.indices(pixels.shape[:2])[0]
    below_crop = rows > 350
    fifth_legend = below_crop & (pixels[:, :, 0] == 71) & (pixels[:, :, 1] == 139) & (pixels[:, :, 2] == 139)
    footer = below_crop & (pixels[:, :, 0] == 70) & (pixels[:, :, 1] == 91) & (pixels[:, :, 2] == 107)
    assert fifth_legend.any() and footer.any()
    assert int(rows[footer].min()) - int(rows[fifth_legend].max()) >= 8


@pytest.mark.parametrize("name,args", [
    ("run_shell", {"command": "touch forbidden"}),
    ("inspect_source", {"path": "/etc/passwd"}),
    ("inspect_source", {"section_ids": ["../../outside"]}),
    ("select_contours", {"selections": [{"section_id": "s0", "candidate_id": "unknown", "points": [[1, 2]]}]}),
    ("select_contours", {"selections": [{"section_id": "s0", "candidate_id": "unknown"}]}),
    ("render_candidate", {"view": "body; shell"}),
    ("build_provisional", {"offset": float("nan")}),
])
def test_model_arguments_cannot_escape_typed_domain(tmp_path, name, args):
    path, _ = drawing(tmp_path / "input")
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute(name, args)
    assert not observed["ok"]
    assert not list((tmp_path / "task/domain").glob("builds/*"))
    assert tools.describe()["selected_count"] == 0


def test_source_snapshot_resume_and_tamper_fail_closed(tmp_path):
    path, _ = drawing(tmp_path / "input")
    task = tmp_path / "task"
    DomainTools(task, path)
    path.unlink(); (path.parent / "drawing.png").unlink()
    tools = DomainTools(task, path)
    assert tools.execute("inspect_source", {"section_ids": ["s0"]})["ok"]
    (task / "domain/input/source.png").write_bytes(b"tampered")
    observed = tools.execute("build_provisional", {})
    assert not observed["ok"] and observed["error_code"] == "domain_integrity_or_input_error"
    with pytest.raises(ValueError, match="changed"):
        DomainTools(task, path)


def test_precancelled_action_does_not_start_worker(tmp_path):
    path, _ = drawing(tmp_path / "input")
    cancellation = threading.Event(); cancellation.set()
    tools = DomainTools(tmp_path / "task", path, cancel_event=cancellation)
    assert tools.execute("inspect_source", {})["status"] == "cancelled"
    assert not (tools.root / "inspections").exists()


@pytest.mark.cad
def test_actual_provisional_build_step_views_and_source_cut_validation(tmp_path):
    path, spec = drawing(tmp_path / "input")
    spec["constraints"] = {"beam_m": 2.5, "relative_tolerance": .03}
    path.write_text(json.dumps(spec))
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {})
    choices = [{"section_id": s["section_id"], "candidate_id": s["grid_evidence"]["unique_non_grid_candidate_id"]}
               for s in observed["sections"]]
    selection = tools.execute("select_contours", {"selections": choices})
    assert selection["ok"], selection
    built = tools.execute("build_provisional", {})
    assert built["ok"] and built["status"] == "review_required", built
    assert tools.execute("build_provisional", {})["reused"]
    for view in ("body", "plan", "profile", "oblique"):
        rendered = tools.execute("render_candidate", {"view": view})
        assert rendered["ok"], rendered
        assert rendered["geometry_audit"]["source"] == "independently_reimported_exported_STEP"
        assert rendered["geometry_audit"]["closed_shell"]
        assert not rendered["stale_candidate"]
        assert rendered["artifacts"][0]["bytes"] > 1000
        derivative = [a for a in rendered["artifacts"] if a.get("model_eligible")][0]
        assert derivative["bytes"] <= 128 * 1024
        assert derivative["derivative_of_sha256"] == rendered["artifacts"][0]["sha256"]
    validated = tools.execute("validate_candidate", {})
    assert validated["ok"], validated
    assert validated["validation"]["sampled_section_count"] == 3
    assert all(s["max_m"] < .0011 for s in validated["validation"]["sampled_sections"])
    assert not validated["validation"]["numeric_reference_truth_used"]
    assert validated["human_semantic_review_required"] and not validated["engineering_approved"]
    # Choosing an actual grid stroke is permitted as a hypothesis, but remains
    # subject to the independently supplied dimensional constraint. A failed
    # revision must not replace the earlier valid candidate.
    outer = max(tools.state["catalog"]["s0"]["candidates"],
                key=lambda c: np.mean(np.asarray(c["contour_selection"]["anchors_px"])[:, 0]))
    assert outer["candidate_id"] != choices[0]["candidate_id"]
    tools.execute("select_contours", {"selections": [{"section_id": "s0", "candidate_id": outer["candidate_id"]}]})
    rejected = tools.execute("build_provisional", {})
    assert not rejected["ok"] and any(g["kind"] == "dimension_conflict" for g in rejected["validation_errors"])
    assert rejected["last_valid_preserved"]
    assert tools.describe()["last_valid_candidate"]["generation_id"] == built["generation_id"]
    assert not tools.execute("validate_candidate", {})["ok"]
    previous_view = tools.execute("render_candidate", {"view": "body"})
    assert previous_view["ok"] and previous_view["stale_candidate"]
    # The evidence boundary remains effective after a successful model/tool loop.
    run = tmp_path / "task" / built["candidate"]["path"]
    with (run / "model.step").open("ab") as handle:
        handle.write(b"\nchanged-after-build")
    assert not tools.execute("render_candidate", {"view": "body"})["ok"]
