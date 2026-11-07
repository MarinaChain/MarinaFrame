"""Pixel checks do not turn missing sheet evidence into a setup."""
from copy import deepcopy

import pytest
from PIL import Image, ImageDraw


def fixture():
    image = Image.new("RGB", (400, 400), "white")
    draw = ImageDraw.Draw(image)
    for x in [50, 100, 150]:
        draw.line((x, 50, x, 300), fill="black", width=2)
    for y in [100, 200, 300]:
        draw.line((50, y, 250, y), fill="black", width=2)
    seen = lambda value, evidence="printed mark": {"value": value, "evidence": evidence}
    overview = {"layout": seen("separate_panels"), "panels": [{"panel_id": "P1", "box_px": [40, 40, 260, 310], "evidence": "frame"}],
                "stations": [{"label": "1", "panel_id": "P1", "x_px": 100, "y_px": 30,
                              "position": seen(0), "evidence": "Station 1 x=0 m"},
                             {"label": "2", "panel_id": "P1", "x_px": 200, "y_px": 30,
                              "position": seen(5), "evidence": "Station 2 x=5 m"}],
                "units": seen("m"), "symmetry": seen("port_starboard"), "vertical_datum": seen("baseline")}
    panel = {"panel_id": "P1", "centreline_x_px": seen(50), "baseline_y_px": seen(300),
             "scale_marks": [{"kind": "waterline_label", "text": "1", "value": 1, "x_px": 50, "y_px": 200, "evidence": "WL 1"},
                             {"kind": "buttock_label", "text": "1", "value": 1, "x_px": 150, "y_px": 300, "evidence": "B 1"}]}
    return image, overview, {"P1": panel}


def check(image, overview, panels):
    from vessel_reconstruction.llm_setup import check_setup
    return check_setup(image, overview, panels)


def test_consistent_setup_records_checked_scale():
    report = check(*fixture())
    assert not report["failures"]
    assert report["panels"]["P1"]["pixels_per_metre"]["value"] == pytest.approx(100)
    assert report["panels"]["P1"]["pixels_per_metre"]["checked"] is True


@pytest.mark.parametrize("mutation,reason", [
    ("blank", "panel_no_ink"), ("centre", "centreline_not_on_ink"),
    ("base", "baseline_not_on_ink"), ("single", "scale_independent_marks_missing"),
    ("duplicate", "scale_independent_marks_missing"), ("scale", "scale_marks_disagree"),
    ("order", "station_order"), ("label", "station_label_evidence"),
    ("missing", "station_position_missing"), ("units", "units_missing"),
])
def test_setup_guard(mutation, reason):
    image, overview, panels = fixture()
    panel = panels["P1"]
    if mutation == "blank": image = Image.new("RGB", image.size, "white")
    if mutation == "centre": panel["centreline_x_px"]["value"] = 80
    if mutation == "base": panel["baseline_y_px"]["value"] = 280
    if mutation == "single": panel["scale_marks"] = panel["scale_marks"][:1]
    if mutation == "duplicate": panel["scale_marks"] = [panel["scale_marks"][0]] * 2
    if mutation == "scale":
        panel["scale_marks"][1]["value"] = 2
        panel["scale_marks"][1]["text"] = "2"
    if mutation == "order": overview["stations"][1]["position"]["value"] = -1
    if mutation == "label": overview["stations"][1]["label"] = "7"
    if mutation == "missing": overview["stations"][0]["position"] = {"missing": "not printed"}
    if mutation == "units": overview["units"] = {"missing": "not printed"}
    assert reason in {f["kind"] for f in check(image, overview, panels)["failures"]}


def test_prepare_hashes_crop_and_preserves_source_coordinates(tmp_path):
    from vessel_reconstruction.llm_setup import prepare_request
    image, _, _ = fixture()
    source = tmp_path / "sheet.png"
    image.save(source)
    manifest = prepare_request(source, tmp_path / "request", "panel:P1", [40, 40, 260, 310])
    assert manifest["images"][0]["crop_box_px"] == [40, 40, 260, 310]
    assert manifest["source_sha256"]
    assert manifest["images"][0]["bytes"] > 0


def test_scale_mark_must_lie_on_drawn_line():
    image, overview, panels = fixture()
    panels["P1"]["scale_marks"][0]["y_px"] = 180
    assert "scale_mark_not_on_ink" in {f["kind"] for f in check(image, overview, panels)["failures"]}


def test_scale_number_must_match_printed_token():
    image, overview, panels = fixture()
    panels["P1"]["scale_marks"][0]["text"] = "WL7"
    assert "scale_mark_text_mismatch" in {f["kind"] for f in check(image, overview, panels)["failures"]}


def test_station_must_reference_proposed_panel():
    image, overview, panels = fixture()
    overview["stations"][0]["panel_id"] = "P7"
    assert "station_panel_missing" in {f["kind"] for f in check(image, overview, panels)["failures"]}


def test_checked_setup_can_fill_explicit_spec_template(tmp_path):
    from vessel_reconstruction.llm_setup import make_spec
    image, overview, panels = fixture()
    overview["stations"].append({"label": "3", "panel_id": "P1", "x_px": 250, "y_px": 30,
                                 "position": {"value": 10, "evidence": "x=10 m"}, "evidence": "Station 3"})
    report = check(image, overview, panels)
    template = {"schema_version": "1.0", "vessel_id": "fixture", "units": "m",
                "source": {"file": "drawing.png", "license": "CC0", "description": "fixture"},
                "symmetry": "port_starboard", "symmetry_evidence": "explicit", "end_closure": "flat_at_terminal_stations",
                "sections": [{"id": str(i), "z_min_m": 0, "z_max_m": 2, "evidence": "visible extent"}
                             for i in [1, 2, 3]], "components": []}
    image.save(tmp_path / "drawing.png")
    spec, provenance = make_spec(template, overview, report, tmp_path)
    assert spec["sections"][0]["calibration"]["pixels_per_metre"] == 100
    assert spec["sections"][0]["x_m"] == 0
    assert provenance["engineering_approved"] is False
    bad = deepcopy(report)
    bad["failures"] = [{"kind": "missing"}]
    with pytest.raises(ValueError, match="unchecked"):
        make_spec(template, overview, bad, tmp_path)


def test_no_progress_stops_repeated_failures():
    from vessel_reconstruction.llm_setup import Progress
    progress = Progress()
    assert not progress.stop([{"kind": "missing", "field": "units"}])
    assert progress.stop([{"kind": "missing", "field": "units"}])
