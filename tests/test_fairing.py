"""Hull fairing on synthetic hulls: fair input kept, one bad cell or station not followed."""
import numpy as np
import pytest

from vessel_reconstruction import fairing

LENGTH, HALF_BEAM, DEPTH = 100.0, 5.0, 8.0


def hull_section(x: float, label: str = "traced", points: int = 61) -> dict:
    """A fair, full-bodied section: breadth falls towards both ends but stays open (transom, stem)."""
    s = x / LENGTH
    z = np.linspace(0.0, DEPTH, points)
    fullness = 1 - 0.7 * (2 * s - 1) ** 2
    y = HALF_BEAM * fullness * (1 - (1 - z / DEPTH) ** 4) ** 0.5
    return {"id": f"S{x:g}", "x_m": x, "points_yz_m": np.column_stack([y, z]).tolist(), "source_label": label}


def fair_hull(labels: dict | None = None) -> list[dict]:
    labels = labels or {}
    return [hull_section(x, labels.get(x, "traced")) for x in np.linspace(0, LENGTH, 11)]


def with_cell(sections: list[dict], station: str, amount: float, half_span: float = 0.05) -> list[dict]:
    result = []
    for section in sections:
        if section["id"] == station:
            points = np.asarray(section["points_yz_m"])
            t = points[:, 1] / DEPTH
            points[:, 0] += amount * np.clip(1 - np.abs(t - 0.5) / half_span, 0, 1)
            section = {**section, "points_yz_m": points.tolist()}
        result.append(section)
    return result


def breadth_at(sections: list[dict], station: str, z: float) -> float:
    points = np.asarray(next(s for s in sections if s["id"] == station)["points_yz_m"])
    return float(np.interp(z, points[:, 1], points[:, 0]))


def test_fair_hull_stays_within_tolerance_without_check_items():
    faired, report = fairing.fair_sections(fair_hull())
    assert report["applied"] and report["engineering_approved"] is False
    assert report["check_items"] == []
    assert report["moves_by_label"]["traced"]["max_m"] < 0.01 * HALF_BEAM
    assert [s["id"] for s in faired] == [s["id"] for s in fair_hull()]
    assert all(s["source_label"] == "traced" and "input_points_yz_m" in s["fairing"] for s in faired)


def test_one_bad_cell_moves_the_faired_hull_much_less():
    base, _ = fairing.fair_sections(fair_hull())
    bad = with_cell(fair_hull(), "S50", 0.5)
    faired, report = fairing.fair_sections(bad)
    moved = breadth_at(faired, "S50", DEPTH / 2) - breadth_at(base, "S50", DEPTH / 2)
    assert breadth_at(bad, "S50", DEPTH / 2) - breadth_at(fair_hull(), "S50", DEPTH / 2) == pytest.approx(0.5)
    # Huber weights bound the pull, but at a fairing length of 0.2 station most of it stays
    # (docs/HULL_FAIRING.md 6); the point is named in a check item.
    assert moved < 0.85 * 0.5
    items = report["check_items"]
    assert [item["section_id"] for item in items] == ["S50"]
    assert items[0]["kind"] == "fairing_moved_point" and items[0]["severity"] == "warning"
    assert "mm" in items[0]["message"]


def test_misread_station_outside_its_neighbours_is_pulled_back_a_little():
    base, _ = fairing.fair_sections(fair_hull())
    shifted = [{**s, "points_yz_m": (np.asarray(s["points_yz_m"]) * [1.05, 1]).tolist()} if s["id"] == "S50" else s
               for s in fair_hull()]
    faired, _ = fairing.fair_sections(shifted)
    injected = 0.05 * breadth_at(fair_hull(), "S50", DEPTH / 2)
    moved = breadth_at(faired, "S50", DEPTH / 2) - breadth_at(base, "S50", DEPTH / 2)
    assert abs(moved) < 0.9 * injected


def test_misread_station_inside_its_neighbours_range_is_not_an_outlier():
    """A known limit: a station wrong by less than its neighbours differ is only smoothed."""
    shifted = [{**s, "points_yz_m": (np.asarray(s["points_yz_m"]) * [1.05, 1]).tolist()} if s["id"] == "S30" else s
               for s in fair_hull()]
    faired, _ = fairing.fair_sections(shifted)
    injected = 0.05 * breadth_at(fair_hull(), "S30", DEPTH / 2)
    assert breadth_at(faired, "S30", DEPTH / 2) - breadth_at(fair_hull(), "S30", DEPTH / 2) > 0.5 * injected


def test_terminal_stations_are_held():
    bad = with_cell(fair_hull(), "S0", 0.5)
    faired, _ = fairing.fair_sections(bad)
    assert breadth_at(faired, "S0", DEPTH / 2) == pytest.approx(breadth_at(bad, "S0", DEPTH / 2), abs=1e-3)


def test_lower_labels_move_more_than_traced():
    sections = with_cell(fair_hull({60.0: "ai_inferred"}), "S60", 0.075)
    traced = with_cell(fair_hull(), "S60", 0.075)
    guessed_move = breadth_at(fairing.fair_sections(sections)[0], "S60", DEPTH / 2)
    traced_move = breadth_at(fairing.fair_sections(traced)[0], "S60", DEPTH / 2)
    assert guessed_move < traced_move


def test_centreline_points_stay_on_the_centreline():
    sections = fair_hull()
    for section in sections:
        points = np.asarray(section["points_yz_m"])
        points[0, 0] = 0.0
        section["points_yz_m"] = points.tolist()
    faired, _ = fairing.fair_sections(sections)
    assert all(s["points_yz_m"][0][0] == 0.0 for s in faired)


def test_end_stations_outside_the_measured_ones_are_kept():
    labels = {0.0: "ai_inferred", 10.0: "ai_inferred", 100.0: "ai_inferred"}
    sections = with_cell(fair_hull(labels), "S10", 0.5)
    faired, report = fairing.fair_sections(sections)
    assert report["parameters"]["faired_stations"][0] == "S20"
    kept = next(s for s in faired if s["id"] == "S10")
    assert kept["points_yz_m"] == next(s for s in sections if s["id"] == "S10")["points_yz_m"]
    assert kept["fairing"]["faired"] is False


def test_multi_region_sections_are_not_faired():
    sections = fair_hull()
    sections[3] = {"id": "R", "x_m": sections[3]["x_m"], "regions": []}
    result, report = fairing.fair_sections(sections)
    assert result is sections and report["applied"] is False
    assert report["check_items"][0]["kind"] == "fairing_not_applied"


def test_fairness_metrics_count_the_kink_of_a_bad_cell():
    fair = fairing.fairness_metrics(fair_hull(), HALF_BEAM)
    bumped = fairing.fairness_metrics(with_cell(fair_hull(), "S50", 1.0), HALF_BEAM)
    assert fair["waterline_inflections"] == 0
    assert bumped["waterline_inflections"] > 0
    assert bumped["max_curvature_jump"] > fair["max_curvature_jump"]


def test_setting_is_off_by_default(monkeypatch):
    monkeypatch.delenv(fairing.SETTING, raising=False)
    assert not fairing.enabled()
    monkeypatch.setenv(fairing.SETTING, "1")
    assert fairing.enabled()
