"""Independent pixel adversaries for cross-contrast contour identity.

No reference ordinates are passed to inference. Optional corridors below are
explicit source-pixel selections, deliberately offset from the actual stroke.
"""
from copy import deepcopy

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import pytest

from vessel_reconstruction.ingest import extract_sections


def competing_lines(tmp_path, *, faint=180, dark_outer=False, width=3,
                    noise=0, blur=0, branch_fraction=1.0, slope=0.0):
    image = Image.new("RGB", (420, 420), "white")
    draw = ImageDraw.Draw(image)
    row0, row1 = 60, 360
    inner = [(180 + slope * (r - row0), r) for r in range(row0, row1 + 1)]
    outer = [(270 + slope * (r - row0), r) for r in range(row0, row1 + 1)]
    colors = (faint, 15) if dark_outer else (15, faint)
    draw.line(inner, fill=(colors[0],) * 3, width=width)
    first = int((1 - branch_fraction) * (len(outer) - 1) / 2)
    last = len(outer) - first
    draw.line(outer[first:last], fill=(colors[1],) * 3, width=width)
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        pixels = np.asarray(image).astype(float)
        pixels += np.random.default_rng(80471).normal(0, noise, pixels.shape)
        image = Image.fromarray(np.clip(pixels, 0, 255).astype("uint8"))
    image.save(tmp_path / "competing.png")
    return {"units": "m", "source": {"file": "competing.png"}, "sections": [{
        "id": "mixed", "x_m": 0, "roi_px": [65, 40, 350, 375],
        "calibration": {"centerline_px": 90, "baseline_px": 360, "pixels_per_metre": 60},
        "z_min_m": 0, "z_max_m": 5,
    }]}


@pytest.mark.parametrize("faint", [15, 80, 120, 150, 180, 210])
def test_original_mixed_contrast_reproducer_abstains_and_keeps_evidence(tmp_path, faint):
    result = extract_sections(competing_lines(tmp_path, faint=faint), tmp_path)
    assert result["sections"] == []
    assert result["gaps"][0]["kind"] == "ambiguous_curve"
    d = result["diagnostics"]["sections"]["mixed"]
    assert d["status"] == "abstained" and d["identity_status"] == "unresolved"
    assert d["quality_score_type"] == "heuristic_not_probability"
    assert d["unresolved_candidate_count"] >= 1
    assert d["proposed_trace_px"] and d["candidate_evidence"]
    assert max(c["vertical_span_fraction"] for c in d["candidate_evidence"]) > .95
    # Candidate coordinates stay tied to actual source pixels, including the
    # lighter line that the former two-tier threshold silently removed.
    coordinates = [p[0] for c in d["candidate_evidence"] for p in c["source_points_px"]]
    assert any(abs(x - (180 if faint == 15 else 270)) <= 2 for x in coordinates)


@pytest.mark.parametrize("faint,dark_outer,width,noise,blur,slope", [
    (93, True, 1, 0, 0, .07), (137, False, 2, 3, 0, -.06),
    (197, True, 3, 5, .35, .08), (219, False, 3, 2, .25, -.05),
    (47, False, 1, 4, 0, .04), (169, True, 4, 7, .4, -.08),
])
def test_changed_contrast_order_noise_and_slope_do_not_assign_identity(
        tmp_path, faint, dark_outer, width, noise, blur, slope):
    spec = competing_lines(tmp_path, faint=faint, dark_outer=dark_outer, width=width,
                           noise=noise, blur=blur, slope=slope)
    result = extract_sections(spec, tmp_path)
    assert result["sections"] == []
    assert result["gaps"][0]["kind"] == "ambiguous_curve", result
    assert result["diagnostics"]["sections"]["mixed"]["candidate_evidence"]


@pytest.mark.parametrize("branch_fraction", [.20, .32, .62])
def test_partial_faint_branch_is_not_hidden_by_global_coverage(tmp_path, branch_fraction):
    result = extract_sections(competing_lines(tmp_path, faint=207, branch_fraction=branch_fraction), tmp_path)
    assert result["sections"] == []
    assert result["gaps"][0]["kind"] == "ambiguous_curve"


@pytest.mark.parametrize("selected_x,expected_y", [(180, 1.5), (270, 3.0)])
def test_explicit_pixel_selection_can_select_either_dark_or_faint_stroke(tmp_path, selected_x, expected_y):
    spec = competing_lines(tmp_path, faint=210)
    spec["sections"][0]["contour_selection"] = {
        "anchors_px": [[selected_x + 1, 60], [selected_x + 1, 360]], "half_width_px": 5,
    }
    result = extract_sections(spec, tmp_path)
    assert not result["gaps"], result
    section = result["sections"][0]
    assert np.asarray(section["points_yz_m"])[:, 0] == pytest.approx(expected_y)
    assert section["evidence"]["contour_selection"]["anchors_px"] == spec["sections"][0]["contour_selection"]["anchors_px"]
    diagnostic = result["diagnostics"]["sections"]["mixed"]
    assert diagnostic["identity_status"] == "explicit_supplied_pixel_selection"
    assert diagnostic["candidate_evidence"][0]["status"] == "excluded_by_explicit_pixel_selection"
    assert diagnostic["candidate_evidence"][0]["source_points_px"]


def test_oversized_corridor_does_not_resolve_two_candidates(tmp_path):
    spec = competing_lines(tmp_path, faint=210)
    spec["sections"][0]["contour_selection"] = {
        "anchors_px": [[225, 60], [225, 360]], "half_width_px": 60,
    }
    result = extract_sections(spec, tmp_path)
    assert result["gaps"][0]["kind"] == "ambiguous_curve"


def test_selection_is_not_used_as_geometry_when_selected_pixels_are_blank(tmp_path):
    spec = competing_lines(tmp_path, faint=210)
    spec["sections"][0]["contour_selection"] = {
        "anchors_px": [[225, 60], [225, 360]], "half_width_px": 5,
    }
    result = extract_sections(spec, tmp_path)
    assert result["sections"] == []
    assert result["gaps"][0]["kind"] == "missing_curve"


@pytest.mark.parametrize("selection", [
    {"anchors_px": [[180, 65], [180, 355]], "half_width_px": 4},
    {"anchors_px": [[180, 60], [180, 60]], "half_width_px": 4},
    {"anchors_px": [[180, 60], [180, 360]], "half_width_px": 0},
    {"anchors_px": [[True, 60], [180, 360]], "half_width_px": 4},
    {"anchors_px": [[180, 60], [180, 360]], "half_width_px": 129},
])
def test_invalid_source_selection_is_structured_abstention(tmp_path, selection):
    spec = competing_lines(tmp_path)
    spec["sections"][0]["contour_selection"] = deepcopy(selection)
    result = extract_sections(spec, tmp_path)
    assert result["sections"] == []
    assert result["gaps"][0]["kind"] == "invalid_contour_selection"


def test_corridor_clipping_cannot_turn_a_baseline_into_positive_keel_breadth(tmp_path):
    # Independent linear, one-pixel outline approaches the exact centreline.
    # A wide pale baseline is not a curve observation. After corridor clipping
    # it used to become a short 7-pixel run and invent a positive-width bottom
    # point followed by real zero-width observations (an artificial pinch).
    image = Image.new("RGB", (420, 420), "white")
    draw = ImageDraw.Draw(image)
    for row in [60, 120, 180, 240, 300, 360]:
        draw.line((90, row, 349, row), fill=(200, 200, 200), width=1)
    draw.line([(90 + .1 * (360 - row), row) for row in range(60, 361)], fill=(15, 15, 15), width=1)
    image.save(tmp_path / "keel-rulers.png")
    spec = {"units": "m", "source": {"file": "keel-rulers.png"}, "sections": [{
        "id": "keel", "x_m": 0, "roi_px": [65, 40, 350, 375],
        "calibration": {"centerline_px": 90, "baseline_px": 360, "pixels_per_metre": 60},
        "z_min_m": 0, "z_max_m": 5,
    }]}
    unselected = extract_sections(spec, tmp_path)
    assert not unselected["gaps"]
    spec["sections"][0]["contour_selection"] = {"anchors_px": [[120, 60], [90, 360]], "half_width_px": 6}
    selected = extract_sections(spec, tmp_path)
    assert not selected["gaps"]
    observed = np.asarray(selected["sections"][0]["points_yz_m"])
    expected = np.asarray(unselected["sections"][0]["points_yz_m"])
    assert observed == pytest.approx(expected, abs=1e-12)
    assert observed[0, 0] == 0
    diagnostic = selected["diagnostics"]["sections"]["keel"]
    assert diagnostic["horizontal_source_rows_with_exclusions"] == 6
    # The source contrast now retains the actual one-pixel curve where it
    # crosses each pale ruler. No part of a uniformly shaded ruler is turned
    # into a curve by corridor clipping.
    assert diagnostic["max_missing_run_px"] == 0
    assert len(diagnostic["retained_contrast_subruns"]) == 6
    assert all(item["span"][1] - item["span"][0] == 1
               for item in diagnostic["retained_contrast_subruns"])
