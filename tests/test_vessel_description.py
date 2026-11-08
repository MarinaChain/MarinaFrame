"""Phase 1 reads values from pixels and keeps doubtful claims as warnings."""
import copy

import numpy as np
from PIL import Image, ImageDraw
import pytest

from vessel_reconstruction import vessel_description as vd


def sheet():
    image = Image.new("RGB", (400, 260), "white")
    draw = ImageDraw.Draw(image)
    for y in range(40, 221, 20):
        draw.line((40, y, 200, y), fill=(190, 190, 190))
    for x in range(40, 201, 20):
        draw.line((x, 40, x, 220), fill=(190, 190, 190))
    draw.line([(100, 220), (115, 200), (135, 160), (150, 100), (160, 40)], fill="black", width=2)
    section = {"id": "s01", "x_m": 10., "roi_px": [40, 40, 201, 221],
               "calibration": {"pixels_per_metre": 20., "centerline_px": 100., "baseline_px": 220.},
               "z_min_m": 0., "z_max_m": 9.}
    spec = {"units": "m", "sections": [section, {**copy.deepcopy(section), "id": "s02", "x_m": 20.}]}
    setup = {"view": "body", "view_id": "body", "region_px": [40, 40, 201, 221],
             "pixels_per_metre": 20., "grid_spacing_m": 1., "centreline_px": 100., "baseline_px": 220.}
    return np.array(image), spec, setup


def test_survey_finds_grid_families_and_keeps_semantics_for_model():
    image, spec, _ = sheet()
    result = vd.survey_sheet(image, spec)
    assert result["sheet_size_px"] == [400, 260]
    assert result["candidate_regions"]
    region = result["candidate_regions"][0]
    assert region["kind"] == "unclassified"
    assert any(f["spacing_px"] == pytest.approx(20) for f in region["grid_families"])
    assert "text_boxes" in result
    assert "strokes" in region
    assert region["grid_evidence"]["method"] == "repeated_orthogonal_lattice_v1"


def test_grid_roles_and_waterline_spacing_are_checked_per_field():
    image, spec, setup = sheet()
    result = vd.measure_description(image, spec, {"waterlines": [
        {"id": "w0", "z_m": 0.}, {"id": "w1", "z_m": 1.4}]}, [setup])
    assert "waterlines[1].z_m" in {w["field"] for w in result["warnings"]}


def test_setup_snaps_datums_and_warns_instead_of_refusing():
    image, spec, setup = sheet()
    setup.update(centreline_px=103., baseline_px=217.)
    result = vd.measure_setup(image, spec, setup)
    assert result["centreline_px"] == 100.
    assert result["baseline_px"] == 220.
    assert result["datum_snaps"]["baseline_px"]["distance_px"] == 3.
    setup["pixels_per_metre"] = 31.
    result = vd.measure_setup(image, spec, setup)
    assert any(w["field"].endswith("pixels_per_metre") for w in result["warnings"])


def test_measured_beam_retains_model_value_and_ignores_grid_extent():
    image, spec, setup = sheet()
    claim = {"principal": {"beam": {"value": 8., "source": "measured", "view_id": "body"}},
             "stations": [{"id": "s01", "x_m": 10., "label": "1"}, {"id": "s02", "x_m": 20., "label": "2"}],
             "waterlines": [{"id": f"wl{i}", "z_m": float(i), "label": str(i)} for i in range(10)]}
    result = vd.measure_description(image, spec, claim, [setup])
    beam = result["principal"]["beam"]
    assert beam["model_value"] == 8.
    assert beam["value"] == pytest.approx(6., abs=.15)
    assert beam["measured_value"] == beam["value"]
    warning = next(w for w in result["warnings"] if w["field"] == "principal.beam")
    assert warning["claimed_value"] == 8.
    assert warning["suggested_fix"]
    assert claim["principal"]["beam"]["value"] == 8.


def test_each_wrong_field_has_a_named_warning_and_no_refusal():
    image, spec, setup = sheet()
    claim = {"principal": {"depth": {"value": 4., "source": "title_block"}},
             "stations": [{"id": "s01", "x_m": 20., "label": "S1.5W"}, {"id": "s02", "x_m": 10., "label": "2"}],
             "waterlines": [{"id": "w1", "z_m": 5.}, {"id": "w2", "z_m": 2.}],
             "ends": {"stem": {"x_top": 1000.}, "bulb": {"present": True}}}
    result = vd.measure_description(image, spec, claim, [setup])
    fields = {w["field"] for w in result["warnings"]}
    assert {"principal.depth", "stations[0].x_m", "stations[1].x_m", "stations[0].label",
            "waterlines", "waterlines[0].z_m", "ends.stem.x_top", "ends.bulb.present"} <= fields
    assert all({"claimed_value", "measured_value", "suggested_fix"} <= w.keys() for w in result["warnings"])
    assert result["engineering_approved"] is False


def test_odd_description_fields_are_preserved_coerced_and_warned():
    image, spec, setup = sheet()
    claim = {"principal": {"beam": {"value": "wide", "source": "visual_guess"},
                           "depth": "9.0", "scale": {"value": "1:100", "source": "title_block"}},
             "stations": {"s01": "10", "s02": "20"}, "waterlines": ["1", "2"],
             "ends": {"stem": "raked", "stern": "transom"}, "deck": "rising sheer",
             "custom_notes": ["keep this"]}
    assert vd.valid_description(claim)
    result = vd.measure_description(image, spec, claim, [setup])
    assert result["model_description"] == claim
    assert result["principal"]["depth"]["value"] == 9.
    assert result["principal"]["scale"]["value"] == "1:100"
    assert result["custom_notes"] == ["keep this"]
    assert result["stations"][0]["x_m"] == 10.
    assert result["ends"]["stem"]["note"] == "raked"
    assert {"principal.beam", "principal.scale", "deck"} <= {w["field"] for w in result["warnings"]}


def test_arbitrary_description_shape_is_recorded_not_rejected():
    image, spec, setup = sheet()
    for claim in (None, "Hull with raked bow", ["body plan"], {"stations": "not a station list",
                  "waterlines": [{"z_m": "unreadable"}], "ends": False}):
        result = vd.measure_description(image, spec, claim, [setup])
        assert result["engineering_approved"] is False
        assert result["warnings"]


def test_missing_grid_still_warns_for_nonempty_incomplete_waterlines():
    image, spec, setup = sheet()
    result = vd.measure_description(np.full_like(image, 255), spec,
                                    {"waterlines": [{"id": "w0", "z_m": 0.}]}, [setup])
    assert "waterlines" in {w["field"] for w in result["warnings"]}


def test_waterline_grid_uses_declared_panels_and_excludes_baseline():
    image, spec, setup = sheet()
    setup["region_px"] = [0, 0, 400, 260]
    result = vd.measure_description(image, spec, {}, [setup])
    assert [w["z_m"] for w in result["waterlines"]] == pytest.approx(list(range(1, 10)), abs=.02)


def test_description_feeds_station_positions_dimensions_and_table_grid():
    from vessel_reconstruction.vessel_model import StationRow, VesselTable
    _, spec, _ = sheet()
    description = {"stations": [{"id": "s01", "x_m": 11.}, {"id": "s02", "x_m": 21.}],
                   "principal": {"beam": {"value": 6.}, "depth": {"value": 9.}},
                   "waterlines": [{"id": "w0", "z_m": 0.}, {"id": "w1", "z_m": 3.}]}
    fitted_spec = vd.first_hull_spec(spec, description)
    assert fitted_spec["sections"][0]["x_m"] == 11.
    assert spec["sections"][0]["x_m"] == 10.
    assert fitted_spec["constraints"]["beam_m"] == 6.
    table = VesselTable([StationRow("s01", 10., [[0., 0.], [3., 9.]], "fitted")], [0., 9.])
    vd.describe_table(table, description)
    assert table.waterlines_z_m == [0., 3.]
    assert table.trend["description"]["principal"]["beam"]["value"] == 6.


def test_unknown_principal_values_are_accepted_and_warned():
    image, spec, setup = sheet()
    claim = {"principal": {"beam": {"value": None, "source": "ai_inferred"},
                           "loa": {"value": None, "source": "ai_inferred"}}}
    assert vd.valid_description(claim)
    result = vd.measure_description(image, spec, claim, [setup])
    assert result["principal"]["beam"]["value"] is not None
    assert result["principal"]["loa"]["value"] is None
    assert "principal.loa" in {w["field"] for w in result["warnings"]}


def test_doubtful_dimension_never_becomes_a_hard_build_constraint():
    _, spec, _ = sheet()
    result = vd.first_hull_spec(spec, {"principal": {"beam": {"value": 99., "source": "ai_inferred"}},
                                     "warnings": [{"field": "principal.beam"}]})
    assert "beam_m" not in result.get("constraints", {})


def test_incomplete_description_warns_on_each_missing_design_field():
    image, spec, setup = sheet()
    result = vd.measure_description(image, spec, {}, [setup])
    fields = {w["field"] for w in result["warnings"]}
    assert {"ends.keel", "ends.stem", "ends.stern", "deck.sheer_z", "form.type"} <= fields


def test_dark_partial_grid_does_not_set_hull_breadth():
    image, spec, setup = sheet()
    pil = Image.fromarray(image)
    draw = ImageDraw.Draw(pil)
    for y in range(40, 221, 20):
        draw.line((40, y, 180, y), fill="black")
    result = vd.measure_description(np.array(pil), spec, {"principal": {
        "beam": {"value": 6., "source": "measured"}}}, [setup])
    assert result["principal"]["beam"]["value"] == pytest.approx(6., abs=.2)


def test_body_only_does_not_invent_profile_measurements():
    image, spec, setup = sheet()
    result = vd.measure_description(image, spec, {"ends": {"stern": {"type": "transom"}}}, [setup])
    assert result["ends"]["stern"]["source"] == "ai_inferred"
    assert result["stations"][0]["x_m"] == 10.
    assert result["waterlines"]
