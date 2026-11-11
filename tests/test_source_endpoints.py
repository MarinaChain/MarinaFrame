"""Source-only endpoint hypotheses and ruler/alternative counterexamples."""
from copy import deepcopy
import json

import numpy as np
from PIL import Image, ImageDraw
import pytest

from vessel_reconstruction.agent_tools import inspect_source_worker
from vessel_reconstruction.ingest import (
    _eligible_trace_mask, _foreground, _source_endpoint_hypothesis, _trace,
    extract_sections,
)


def source(tmp_path, *, grid=False, flat_bottom=False, faint_alternative=False):
    image = Image.new("RGB", (720, 290), "white")
    draw = ImageDraw.Draw(image)
    sections = []
    for i in range(3):
        cx, base, height = 20 + i * 240, 250, 210
        if grid:
            for z in range(0, height + 1, 35):
                draw.line((cx, base - z, cx + 200, base - z), fill=(205,) * 3)
            for x in range(0, 201, 40):
                draw.line((cx + x, base - height, cx + x, base), fill=(205,) * 3)
        else:
            draw.line((cx, 25, cx, base), fill=(205,) * 3)
        if flat_bottom:
            points = [(cx, base), (cx + 120, base), (cx + 120, base - height)]
        else:
            xx = np.linspace(0, 150, 1201)
            # Nearest-pixel rasterization produces an extended bottom row at
            # a tangent. The exact source pixels, not this function, are the
            # only inference input.
            points = [(round(cx + float(x)), round(base - height * float(x / 150) ** 2.8)) for x in xx]
        draw.line(points, fill=(20,) * 3, width=1)
        if faint_alternative:
            draw.line((cx + 175, base - height, cx + 175, base), fill=(210,) * 3, width=2)
        sections.append({"id": f"s{i}", "x_m": float(i * 3), "roi_px": [i * 240 + 5, 20, i * 240 + 225, 270],
            "calibration": {"centerline_px": cx, "baseline_px": base, "pixels_per_metre": 70.},
            "z_min_m": 0., "z_max_m": 3., "evidence": "Explicit synthetic calibration."})
    image.save(tmp_path / "drawing.png")
    spec = {"schema_version": "1.0", "vessel_id": "endpoint-source", "units": "m",
        "symmetry": "port_starboard", "symmetry_evidence": "Declared synthetic assumption.",
        "end_closure": "flat_at_terminal_stations", "source": {"file": "drawing.png"},
        "sections": sections}
    path = tmp_path / "spec.json";path.write_text(json.dumps(spec))
    return path, spec


@pytest.mark.parametrize("grid", [False, True])
def test_visible_endpoint_is_a_separate_source_supported_candidate(tmp_path, grid):
    path, spec = source(tmp_path, grid=grid)
    before = path.read_bytes()
    obs = inspect_source_worker(path, ["s0"], tmp_path / "inspection")
    entry = obs["sections"][0]
    endpoints = [c for c in entry["candidates"] if c.get("endpoint_evidence")]
    assert endpoints
    preferred = entry["grid_evidence"].get("unique_non_grid_candidate_id")
    endpoint = next((c for c in endpoints if c["endpoint_evidence"]["centroid_alternative_id"] == preferred), endpoints[0])
    assert endpoint["endpoint_interpretation_requires_review"]
    assert endpoint["endpoint_evidence"]["contact_px"] == [20., 250.]
    assert len(endpoint["endpoint_evidence"]["connected_trace_witnesses_local_px"]) >= 2
    legacy = [c for c in entry["candidates"] if not c.get("endpoint_evidence")]
    assert legacy and all(c["candidate_id"] != endpoint["candidate_id"] for c in legacy)
    assert any(c["contour_selection"]["anchors_px"][-1][0] > 25 for c in legacy)
    selected = deepcopy(spec)
    selected["sections"] = [selected["sections"][0]]
    selected["sections"][0]["contour_selection"] = endpoint["contour_selection"]
    result = extract_sections(selected, path.parent)
    assert not result["gaps"], result
    assert 0 <= result["sections"][0]["points_yz_m"][0][0] <= 1.01 / 70
    assert path.read_bytes() == before
    assert not endpoint["endpoint_evidence"]["engineering_approved"]


def test_uniform_broad_ruler_cannot_be_clipped_into_an_endpoint():
    mask = np.zeros((101, 150), dtype=bool)
    mask[:, 70] = True
    mask[-1, :] = True
    ink = np.where(mask, 230., 0.)
    selection = np.zeros_like(mask);selection[:, 65:76] = True
    eligible, diagnostic = _eligible_trace_mask(mask, selection, ink)
    assert not eligible[-1].any()
    assert diagnostic["retained_contrast_subruns"] == []
    rows, xs, quality = _trace(eligible, ink, 0)
    assert _source_endpoint_hypothesis(mask, ink, rows, xs, 0, quality["median_stroke_width_px"]) is None


def test_horizontal_bottom_with_vertical_side_is_not_endpoint_contact(tmp_path):
    path, _ = source(tmp_path, flat_bottom=True)
    obs = inspect_source_worker(path, ["s0"], tmp_path / "inspection")
    assert not any(c.get("endpoint_evidence") for c in obs["sections"][0]["candidates"])


def test_faint_competitor_survives_new_endpoint_hypotheses(tmp_path):
    path, _ = source(tmp_path, grid=True, faint_alternative=True)
    obs = inspect_source_worker(path, ["s0"], tmp_path / "inspection")
    entry = obs["sections"][0]
    assert entry["retained_competing_count"] > 0
    assert any(np.mean(np.asarray(c["source_points_px"])[:, 0]) > 190
               for c in entry["candidates"])
    assert entry["grid_evidence"]["unique_non_grid_candidate_id"] is None


def test_disconnected_centreline_mark_cannot_become_endpoint():
    image = Image.new("RGB", (180, 110), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(100 + .2 * r, r) for r in range(101)], fill="black", width=1)
    draw.line((0, 100, 18, 100), fill="black", width=1)
    mask, ink, _ = _foreground(np.asarray(image)[:101])
    eligible, _ = _eligible_trace_mask(mask, None, ink)
    rows, xs, quality = _trace(eligible, ink, 0)
    assert _source_endpoint_hypothesis(mask, ink, rows, xs, 0, quality["median_stroke_width_px"]) is None
