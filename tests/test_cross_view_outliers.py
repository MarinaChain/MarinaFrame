"""Report-only cell checks must not change source geometry or acceptance gates."""
import copy

import numpy as np
import pytest

from vessel_reconstruction import cross_view_outliers as outliers


def sections():
    return [{"id": "s1", "x_m": 5.0, "source_label": "read",
             "points_yz_m": [[1.0, float(z)] for z in np.linspace(0, 2, 41)]}]


def test_plan_disagreement_has_distances_and_does_not_mutate():
    source = sections()
    before = copy.deepcopy(source)
    evidence = {("s1", 20): {"plan": {"status": "measured", "residual_m": .1, "competing_runs": 0}}}
    report = outliers.detect_cells(source, evidence=evidence, half_beam_m=1)
    cell = report["cells"][20]
    assert cell["flagged"]
    assert cell["distances_m"]["plan"] == pytest.approx(.1)
    assert cell["tolerance_m"] == pytest.approx(.02)
    assert len(report["check_items"]) == 1
    assert source == before
    assert report["engineering_approved"] is False


def test_ambiguous_and_missing_views_are_not_agreement():
    evidence = {("s1", 20): {"plan": {"status": "measured", "residual_m": .2, "competing_runs": 1}}}
    report = outliers.detect_cells(sections(), evidence=evidence, half_beam_m=1)
    cell = report["cells"][20]
    assert not cell["flagged"]
    assert cell["availability"]["plan"] == "ambiguous"
    assert cell["availability"]["profile"] == "missing"
    assert cell["distances_m"]["plan"] is None
    assert report["coverage"]["independent_cells"] == 0


@pytest.mark.parametrize("limit,value", [("keel", 1.2), ("deck", .8), ("transom", 5.2), ("stem", 4.8)])
def test_profile_limits_are_one_sided(limit, value):
    evidence = {("s1", 20): {"profile": {limit: value}}}
    cell = outliers.detect_cells(sections(), evidence=evidence, half_beam_m=1)["cells"][20]
    assert cell["flagged"]
    assert cell["distances_m"][limit] == pytest.approx(.2)
    evidence[("s1", 20)]["profile"] = {"keel": 0, "deck": 2, "transom": 0, "stem": 10}
    cell = outliers.detect_cells(sections(), evidence=evidence, half_beam_m=1)["cells"][20]
    assert not cell["flagged"]


def test_section_neighbours_detect_peak_but_not_straight_curve_or_ends():
    source = sections()
    assert not outliers.detect_cells(source, half_beam_m=1)["check_items"]
    source[0]["points_yz_m"][20][0] += .2
    report = outliers.detect_cells(source, half_beam_m=1)
    assert report["cells"][20]["flagged"]
    assert report["cells"][20]["distances_m"]["section"] == pytest.approx(.2)
    assert report["cells"][0]["distances_m"]["section"] is None
    assert report["cells"][-1]["distances_m"]["section"] is None


def test_pixel_tolerance_and_unsupported_curves_are_explicit():
    evidence = {("s1", 20): {"pixels_per_metre": 10,
                "plan": {"status": "measured", "residual_m": .2, "competing_runs": 0}}}
    cell = outliers.detect_cells(sections(), evidence=evidence, half_beam_m=1)["cells"][20]
    assert cell["tolerance_m"] == pytest.approx(.3)
    assert not cell["flagged"]
    source = sections()
    source[0]["points_yz_m"][20][1] = source[0]["points_yz_m"][19][1]
    report = outliers.detect_cells(source, half_beam_m=1)
    assert report["cells"][20]["availability"]["section"] == "unsupported"
    with pytest.raises(ValueError, match="finite"):
        outliers.detect_cells(sections(), half_beam_m=float("nan"))


def test_raster_adapter_measures_plan_and_profile_without_truth():
    grey = np.full((200, 240), 255, dtype=np.uint8)
    # Plan: horizontal waterline y=1 m at row 40, centreline at 60.
    grey[39:42, 20:221] = 0
    # Profile: rectangular hull x=[0,10], z=[0,2], baseline row 150.
    grey[109:112, 20:221] = 0
    grey[149:152, 20:221] = 0
    grey[110:151, 19:22] = 0
    grey[110:151, 219:222] = 0
    views = {
        "half_breadth_plan": {"roi_px": [10, 10, 230, 65], "calibration": {
            "pixels_per_metre": 20, "x_origin_px": 20, "centerline_px": 60}},
        "profile": {"roi_px": [10, 100, 230, 160], "calibration": {
            "pixels_per_metre": 20, "x_origin_px": 20, "baseline_px": 150}},
    }
    evidence = outliers.measure_evidence(sections(), grey, views, half_beam_m=1)
    middle = evidence[("s1", 20)]
    assert abs(middle["plan"]["residual_m"]) < .05
    assert middle["profile"]["keel"] == pytest.approx(0, abs=.1)
    assert middle["profile"]["deck"] == pytest.approx(2, abs=.1)
    assert middle["profile"]["transom"] == pytest.approx(0, abs=.1)
    assert middle["profile"]["stem"] == pytest.approx(10, abs=.1)
