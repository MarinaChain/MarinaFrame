"""Hull ends beyond the drawn stations (hull_ends.py), without CAD or a model."""
import numpy as np

from test_form_fit import DEPTH, STATIONS, declared, synthetic_anchors

from vessel_reconstruction import form_fit as F
from vessel_reconstruction import hull_ends as H
from vessel_reconstruction.section_authoring import check_authored
from vessel_reconstruction.vessel_model import build_spec

ENDS = {"aft_m": 0.0, "fore_m": 100.0}


def test_end_places_lie_between_the_end_stations_and_the_ends():
    places = H.end_stations(ENDS, STATIONS)
    aft = [p for p in places if p["end"] == "aft"]
    fore = [p for p in places if p["end"] == "fore"]
    assert len(aft) == len(fore) == len(H.END_FRACTIONS)
    assert all(0.0 < p["x_m"] < STATIONS[0] for p in aft)
    assert all(STATIONS[-1] < p["x_m"] < 100.0 for p in fore)
    assert [p["x_m"] for p in places] == sorted(p["x_m"] for p in places)


def test_no_end_place_where_the_end_station_already_is_the_end():
    places = H.end_stations({"aft_m": 9.0, "fore_m": 100.0}, STATIONS)
    assert all(p["end"] == "fore" for p in places)


def test_end_row_takes_the_outline_heights_and_the_taper():
    table = F.fit_vessel(declared(), synthetic_anchors())
    terminal = table.stations[-1]
    place = {"id": "fore-end-1", "x_m": 95.0, "end": "fore", "share": 0.5}
    row = H.end_row(place, {"keel": 2.0, "deck": DEPTH}, terminal, 0.4)
    assert row.source == "inferred" and row.keel_z_m == 2.0 and row.top_z_m == DEPTH
    assert np.isclose(max(p[0] for p in row.points_yz_m), 0.4 * max(p[0] for p in terminal.points_yz_m))


def test_end_row_is_left_out_at_the_very_tip():
    table = F.fit_vessel(declared(), synthetic_anchors())
    place = {"id": "fore-end-5", "x_m": 99.9, "end": "fore", "share": 0.97}
    assert H.end_row(place, {"keel": 9.9, "deck": 10.0}, table.stations[-1], 0.05) is None


def test_extended_table_builds_ends_as_ai_inferred_curves_without_guesses():
    sections = declared()
    table = F.fit_vessel(sections, synthetic_anchors())
    places = H.end_stations(ENDS, STATIONS)
    heights = {p["id"]: {"keel": 1.0, "deck": DEPTH} for p in places}
    tapers = {p["id"]: 1.0 - p["share"] for p in places}
    added = H.extend_to_ends(table, sections, places, heights, tapers)
    assert {s["id"] for s in added} == {p["id"] for p in places if tapers[p["id"]] > 0}
    assert any(w["kind"] == "inferred_end" for w in table.warnings)
    assert table.stations[0].x_m < STATIONS[0] and table.stations[-1].x_m > STATIONS[-1]
    base = {"source": {"file": "drawing.png"}, "sections": [a.selection_section for a in synthetic_anchors()]}
    spec = build_spec(table, base, sections + added)
    ends = [s for s in spec["sections"] if s["id"].endswith(tuple("12345")) and "-end-" in s["id"]]
    assert ends and all(s["authored"]["source_label"] == "ai_inferred" for s in ends)
    assert all(check_authored(s["authored"]) for s in ends)
    assert not (spec.get("draft") or {}).get("guesses")


def test_first_hull_without_its_ends_when_the_build_with_them_fails():
    sections = declared()
    places = H.end_stations(ENDS, STATIONS)
    heights = {p["id"]: {"keel": 1.0, "deck": DEPTH} for p in places}
    tapers = {p["id"]: 0.5 for p in places}
    builds = []

    def build(spec):
        builds.append(spec)
        return not any("-end-" in s["id"] for s in spec["sections"])

    base = {"source": {"file": "drawing.png"}, "sections": [a.selection_section for a in synthetic_anchors()]}
    table, result, left_out = F.first_hull(
        sections, synthetic_anchors(), base, build,
        extend=lambda t: H.extend_to_ends(t, sections, places, heights, tapers))
    assert result and left_out == [] and len(builds) == 2
    assert all(row.source != "inferred" for row in table.stations)


def test_the_drawing_fit_leaves_out_the_end_rows():
    from vessel_reconstruction.fit_feedback import drawn_stations
    sections = declared()
    table = F.fit_vessel(sections, synthetic_anchors())
    places = H.end_stations(ENDS, STATIONS)
    H.extend_to_ends(table, sections, places, {p["id"]: {"keel": 1.0, "deck": DEPTH} for p in places},
                     {p["id"]: 0.5 for p in places})
    drawn = drawn_stations(table)
    assert [row.id for row in drawn.stations] == [s["id"] for s in sections]


def test_profile_from_the_intake_when_the_model_set_up_none():
    from vessel_reconstruction.vessel_description import profile_setup
    setups = [{"view": "body", "region_px": [2172, 138, 2475, 333], "pixels_per_metre": 19.0},
              {"view": "body", "region_px": [153, 135, 2073, 312], "pixels_per_metre": 19.0}]
    hints = [{"label": "profile", "region_px": [150, 140, 2080, 310]}]
    profile = profile_setup(setups, hints)
    assert profile["view"] == "profile" and profile["region_px"] == [150, 140, 2080, 310]
    assert profile["pixels_per_metre"] == 19.0 and profile["baseline_px"] is None
    assert profile_setup(setups, []) is None


def plan_image(fore_px: int = 900) -> np.ndarray:
    """A half-breadth plan: centreline at row 200, one waterline full amidships, closing to the ends."""
    image = np.full((260, 1000, 3), 255, dtype=np.uint8)
    for column in range(100, fore_px + 1):
        u = (column - 100) / (fore_px - 100)
        breadth = 150 * min(1.0, 4 * u, 4 * (1 - u))
        image[int(round(200 - breadth)), column] = 0
    image[200, 100:fore_px + 1] = 0  # the centreline
    return image


def test_plan_breadths_follow_the_outline_mapped_onto_the_profile_ends():
    ends = {**ENDS, "scale": 8.0}
    breadths = H.plan_breadths(plan_image(), [50, 20, 950, 240], ends, [12.5, 50.0, 87.5])
    assert np.isclose(breadths[50.0], 150, atol=2)
    assert np.isclose(breadths[12.5] / breadths[50.0], 0.5, atol=0.03)
    assert np.isclose(breadths[87.5] / breadths[50.0], 0.5, atol=0.03)


def test_plan_of_another_length_is_not_read():
    ends = {**ENDS, "scale": 8.0}
    assert H.plan_breadths(plan_image(fore_px=600), [50, 20, 950, 240], ends, [50.0]) == {}
