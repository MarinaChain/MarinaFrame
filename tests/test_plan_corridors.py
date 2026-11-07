"""Drawing-only selection evidence; no reference geometry or CAD is needed."""
from copy import deepcopy

import numpy as np
import pytest

from vessel_reconstruction.plan_corridors import derive_contour_selection


def example():
    image = np.full((140, 180, 3), 255, dtype=np.uint8)
    # Declared plan waterlines: each has one observed crossing at station x=40.
    image[30:33, 20:80] = 0
    image[60:63, 20:80] = 0
    section = {"id": "s1", "x_m": 2., "roi_px": [0, 0, 180, 140],
               "calibration": {"centerline_px": 10., "baseline_px": 110., "pixels_per_metre": 20.},
               "z_min_m": 0., "z_max_m": 4., "evidence": "Synthetic body plan"}
    setup = {"region_px": [0, 0, 100, 100], "x_origin_px": 20., "x_direction": 1,
             "centreline_px": 10., "pixels_per_metre": 10., "breadth_direction": 1,
             "evidence": "Synthetic plan grid"}
    waterlines = [{"z_m": 4., "region_px": [0, 25, 100, 40], "evidence": "Label WL4"},
                  {"z_m": 0., "region_px": [0, 55, 100, 70], "evidence": "Label WL0"}]
    return image, section, setup, waterlines


def test_unique_crossings_map_to_body_pixels_without_changing_input():
    image, section, setup, waterlines = example()
    before = deepcopy(section)
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert result["contour_selection"] == {"anchors_px": [[52., 30.], [112., 110.]], "half_width_px": 3.}
    assert [a["status"] for a in result["anchors"]] == ["accepted", "accepted"]
    assert result["engineering_approved"] is False
    assert result["identity_certified"] is False
    assert "same drawing" in result["interpretation"]
    assert section == before


@pytest.mark.parametrize("kind,reason", [("multiple", "ambiguous_crossing"), ("missing", "no_crossing"),
                                          ("edge", "crossing_touches_region_boundary")])
def test_refuse_ambiguous_missing_and_clipped_crossings(kind, reason):
    image, section, setup, waterlines = example()
    if kind == "multiple":
        image[36:38, 20:80] = 0
    elif kind == "missing":
        image[25:40] = 255
    else:
        image[25:33, 20:80] = 0
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert result["anchors"][0]["reason"] == reason
    assert result["contour_selection"] is None
    assert len(result["anchors"]) == 2


def test_no_extrapolation_when_waterlines_do_not_span_calibrated_range():
    image, section, setup, waterlines = example()
    waterlines[0]["z_m"] = 3.
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert result["contour_selection"] is None
    assert result["reason"] == "anchors_do_not_span_calibrated_range"
    assert all(a["status"] == "accepted" for a in result["anchors"])


def test_unidentified_ink_cannot_supply_height_identity():
    image, section, setup, waterlines = example()
    waterlines[0]["evidence"] = ""
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert result["anchors"][0]["reason"] == "missing_waterline_identity_evidence"
    assert result["contour_selection"] is None


@pytest.mark.parametrize("field,value", [("pixels_per_metre", 0), ("x_direction", 0),
                                         ("breadth_direction", 2), ("centreline_px", float("nan"))])
def test_invalid_setup_fails_closed(field, value):
    image, section, setup, waterlines = example()
    setup[field] = value
    with pytest.raises(ValueError):
        derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)


def test_station_outside_waterline_region_is_refused():
    image, section, setup, waterlines = example()
    section["x_m"] = 20.
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert all(a["reason"] == "station_outside_waterline_region" for a in result["anchors"])


def test_overlaid_body_plan_is_selected_from_matching_plan_view(tmp_path):
    from PIL import Image, ImageDraw
    from vessel_reconstruction.ingest import extract_sections

    body = Image.new("RGB", (240, 240), "white")
    draw = ImageDraw.Draw(body)
    for offset in range(0, 100, 12):
        draw.line([(45 + offset, 20), (75 + offset, 120), (55 + offset, 220)], fill="black", width=2)
    body.save(tmp_path / "body.png")
    section = {"id": "station", "x_m": 2., "roi_px": [10, 10, 230, 230],
               "calibration": {"centerline_px": 20., "baseline_px": 220., "pixels_per_metre": 100.},
               "z_min_m": 0., "z_max_m": 2.}
    plan = np.full((150, 100, 3), 255, dtype=np.uint8)
    # The target is offset 36, so breadths are 61, 91, 71 source pixels.
    for row in (71, 101, 81):
        plan[row, 20:80] = 0
    setup = {"region_px": [0, 0, 100, 150], "x_origin_px": 20., "x_direction": 1,
             "centreline_px": 10., "pixels_per_metre": 100., "breadth_direction": 1,
             "evidence": "Synthetic matching plan scale"}
    # x_m=0.2 places the station at column 40 on this plan.
    section["x_m"] = .2
    waterlines = [{"z_m": z, "region_px": [0, row - 3, 100, row + 4], "evidence": f"WL {z}"}
                  for z, row in [(2., 71), (1., 101), (0., 81)]]
    result = derive_contour_selection(plan, section, setup, waterlines, half_width_px=3.)
    assert result["contour_selection"] is not None
    spec = {"schema_version": "1.0", "vessel_id": "synthetic", "units": "m",
            "source": {"file": "body.png"}, "sections": [section]}
    before = extract_sections(spec, tmp_path)
    assert not before["sections"]
    assert before["gaps"][0]["kind"] == "ambiguous_curve"
    section["contour_selection"] = result["contour_selection"]
    measured = extract_sections(spec, tmp_path)
    assert not measured["gaps"], measured
    points = np.asarray(measured["sections"][0]["points_yz_m"])
    expected = np.interp(points[:, 1], [0., 1., 2.], [.71, .91, .61])
    assert np.max(np.abs(points[:, 0] - expected)) < .02


def test_raster_prepare_records_same_drawing_evidence(tmp_path, monkeypatch):
    import json
    from benchmarks.gunnerus import raster_path

    image, section, setup, waterlines = example()
    pdf = tmp_path / "synthetic.pdf"
    pdf.write_bytes(b"synthetic source identity")
    monkeypatch.setattr(raster_path, "render_clip", lambda *args: image.copy())
    config = {"pdf": str(pdf), "page_index": 0, "clip_pt": [0, 0, 100, 100], "dpi": 72,
              "calibration": {"centreline_px": 10., "baseline_px": 110., "pixels_per_metre": 20.},
              "stations": [{"id": "s1", "x_m": 2., "side": 1}],
              "z_range_m": {"1": [0., 4.]}, "vessel_id": "synthetic", "license": "test",
              "description": "Synthetic sheet", "plan_corridors": {
                  "clip_pt": [0, 0, 100, 100], "setup": setup,
                  "waterlines_by_section": {"s1": waterlines}, "half_width_px": 3.}}
    out = tmp_path / "prepared"
    raster_path.cmd_prepare(config, tmp_path, out)
    spec = json.loads((out / "spec.json").read_text())
    assert spec["sections"][0]["contour_selection"]["anchors_px"] == [[52., 30.], [112., 110.]]
    report = json.loads((out / "plan_corridors.json").read_text())
    assert report["engineering_approved"] is False
    assert report["source_sha256"]
    assert "same drawing" in spec["sections"][0]["evidence"]


def test_mirrored_plan_direction_and_existing_selection_are_preserved():
    image, section, setup, waterlines = example()
    setup.update(x_origin_px=60., x_direction=-1, centreline_px=90., breadth_direction=-1)
    section["contour_selection"] = {"anchors_px": [[30., 30.], [40., 110.]], "half_width_px": 2.}
    before = deepcopy(section)
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert result["plan_column_px"] == 40.
    assert result["anchors"][0]["anchor_px"] == [128., 30.]
    assert result["contour_selection"] is None
    assert result["reason"] == "existing_contour_selection_preserved"
    assert section == before


@pytest.mark.parametrize("width", [0., 129., True, float("nan")])
def test_width_cannot_widen_the_existing_contract(width):
    image, section, setup, waterlines = example()
    with pytest.raises(ValueError):
        derive_contour_selection(image, section, setup, waterlines, half_width_px=width)


def test_anchor_on_exclusive_body_boundary_is_refused():
    image, section, setup, waterlines = example()
    section["roi_px"][2] = 112
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert result["anchors"][1]["reason"] == "anchor_outside_body_panel"
    assert result["contour_selection"] is None


def test_neighbouring_diagonal_crossings_cannot_merge_into_a_unique_anchor():
    image, section, setup, waterlines = example()
    image[25:40] = 255
    for column, rows in [(39, (30, 32)), (40, (31, 33)), (41, (32, 34))]:
        image[list(rows), column] = 0
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert result["anchors"][0]["status"] == "refused"
    assert result["anchors"][0]["reason"] == "ambiguous_crossing"


def test_duplicate_elevations_do_not_make_a_corridor():
    image, section, setup, waterlines = example()
    waterlines[1]["z_m"] = 4.
    result = derive_contour_selection(image, section, setup, waterlines, half_width_px=3.)
    assert result["contour_selection"] is None
    assert result["reason"] == "duplicate_anchor_elevation"
