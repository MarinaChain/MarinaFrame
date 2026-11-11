"""A calibrated range must not force a hull trace onto a buttock ruler."""
from copy import deepcopy
import json

from PIL import Image, ImageDraw
import pytest

from vessel_reconstruction.agent_tools import inspect_source_worker
from vessel_reconstruction.ingest import extract_sections


def shortened_hull(tmp_path, *, local_bottom=False, complete=False):
    image = Image.new("RGB", (250, 250), "white")
    draw = ImageDraw.Draw(image)
    for x in range(20, 221, 40):
        draw.line((x, 20, x, 220), fill=(205,) * 3)
    for row in range(20, 221, 40):
        draw.line((20, row, 220, row), fill=(205,) * 3)
    points = [(180, 20), (156, 60), (140, 100)]
    if complete:
        points += [(110, 140), (70, 180), (20, 220)]
    draw.line(points, fill=(20,) * 3, width=2)
    image.save(tmp_path / "drawing.png")
    section = {"id": "s0", "x_m": 0., "roi_px": [15, 15, 230, 230],
               "calibration": {"centerline_px": 20., "baseline_px": 220.,
                               "pixels_per_metre": 100.},
               "z_min_m": 1.2 if local_bottom else 0., "z_max_m": 2.}
    spec = {"schema_version": "1.0", "vessel_id": "shortened-hull", "units": "m",
            "symmetry": "port_starboard", "symmetry_evidence": "Synthetic symmetric drawing.",
            "end_closure": "flat_at_terminal_stations", "source": {"file": "drawing.png"},
            "sections": [section]}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    return path, spec


def selected_spec(spec, candidate):
    result = deepcopy(spec)
    result["sections"][0]["contour_selection"] = candidate["contour_selection"]
    return result


def test_dark_complete_stroke_on_a_pale_ruler_is_not_a_ruler_continuation(tmp_path):
    path, spec = shortened_hull(tmp_path)
    with Image.open(tmp_path / "drawing.png") as source:
        image = source.convert("RGB")
    ImageDraw.Draw(image).line((140, 100, 140, 220), fill=(20,) * 3, width=2)
    image.save(tmp_path / "drawing.png")
    entry = inspect_source_worker(path, ["s0"], tmp_path / "inspection")["sections"][0]
    cid = entry["grid_evidence"].get("unique_non_grid_candidate_id")
    assert cid is not None, entry
    candidate = next(c for c in entry["candidates"] if c["candidate_id"] == cid)
    result = extract_sections(selected_spec(spec, candidate), tmp_path)
    assert not result["gaps"], result


def test_catalog_refuses_coverage_from_a_buttock_below_the_hull(tmp_path):
    path, _ = shortened_hull(tmp_path)
    entry = inspect_source_worker(path, ["s0"], tmp_path / "inspection")["sections"][0]
    assert entry["grid_evidence"].get("unique_non_grid_candidate_id") is None
    # Complete rulers can remain for explicit operator review; the mixed hull
    # plus ruler path must not be selectable or preferred by the policy.
    assert all(not c["grid_supported_hypothesis"] for c in entry["candidates"])
    assert any(r["reason"] == "stroke_identity_unresolved"
               for r in entry["rejected_trace_hypotheses"])


def test_corridor_cannot_hide_a_ruler_continuation(tmp_path):
    _, spec = shortened_hull(tmp_path)
    spec["sections"][0]["contour_selection"] = {
        "anchors_px": [[180., 20.], [156., 60.], [140., 100.], [140., 220.]],
        "half_width_px": 2.75}
    result = extract_sections(spec, tmp_path)
    assert not result["sections"], result
    assert result["gaps"][0]["kind"] == "stroke_identity_unresolved", result
    diagnostic = result["diagnostics"]["sections"]["s0"]["stroke_identity"]
    assert diagnostic["ruler_continuations"]
    assert diagnostic["source_before_selection"] is True


@pytest.mark.parametrize("complete", [False, True])
def test_local_endpoint_or_complete_stroke_does_not_need_ruler_coverage(tmp_path, complete):
    path, spec = shortened_hull(tmp_path, local_bottom=not complete, complete=complete)
    entry = inspect_source_worker(path, ["s0"], tmp_path / "inspection")["sections"][0]
    cid = entry["grid_evidence"].get("unique_non_grid_candidate_id")
    assert cid is not None, entry
    candidate = next(c for c in entry["candidates"] if c["candidate_id"] == cid)
    result = extract_sections(selected_spec(spec, candidate), tmp_path)
    assert not result["gaps"], result
    points = result["sections"][0]["points_yz_m"]
    assert points[0][1] == pytest.approx(0. if complete else 1.2)
    assert points[-1][1] == pytest.approx(2.)
