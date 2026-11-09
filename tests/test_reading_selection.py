"""Best of READINGS sheet-only readings, kept by the drawing fit (first_hull_tools)."""
import json
from pathlib import Path

from vessel_reconstruction import first_hull_tools as T
from vessel_reconstruction.agent_tools import MATERIALIZED_SPEC


class FakeTools:
    """The parts of DomainTools that the reading selection uses."""

    def __init__(self, root: Path, state: dict):
        self.root = root
        (root / "input").mkdir(parents=True, exist_ok=True)
        self.state = state
        self.spec = {"sections": [{"id": "new"}]}
        self.captured_spec = {"sections": []}
        self.saved = 0

    def _save(self):
        self.saved += 1


def first_hull_state(fit: float, draft_fit: float | None = None) -> dict:
    """State after a first hull: body-plan fit ``fit``; three-view draft fit ``draft_fit`` (None: not scored)."""
    return {"sheet_only": True, "fit_score": {"combined_fit": fit}, "draft_fit": {"draft_fit": draft_fit},
            "description_phase": "complete",
            "vessel_description": {"stations": [{"id": "1"}, {"id": "2"}]},
            "described_views": [{"view_id": "body"}], "sheet_setups": {"setup-1": {}},
            "vessel_table": {"stations": []}, "last_valid_candidate": {"id": "first"}, "builds": [{"id": "first"}]}


def test_first_hull_starts_a_second_reading_and_keeps_the_hull(tmp_path):
    tools = FakeTools(tmp_path, first_hull_state(0.8))
    started = T.start_next_reading(tools)
    assert started["reading"] == 2 and started["of"] == T.READINGS
    assert tools.state["description_phase"] == "views" and tools.state["sheet_setups"] == {}
    assert tools.state["vessel_table"] == {"stations": []}  # the first hull stays the draft
    assert tools.state["readings"] == [{"draft_fit": None, "combined_fit": 0.8, "station_count": 2, "kept": True}]
    assert T.start_next_reading(tools) is None  # only once


def test_no_second_reading_for_a_declared_spec_or_a_phase1_only_run(tmp_path):
    assert T.start_next_reading(FakeTools(tmp_path, {**first_hull_state(0.8), "sheet_only": False})) is None
    assert T.start_next_reading(FakeTools(tmp_path, {**first_hull_state(0.8), "phase1_only": True})) is None


def test_the_earlier_reading_is_kept_when_the_new_hull_fits_worse(tmp_path):
    earlier = {**first_hull_state(0.8), "readings": [{"combined_fit": 0.8, "kept": True}]}
    tools = FakeTools(tmp_path, {**first_hull_state(0.6), "readings": [{"combined_fit": 0.8, "kept": True}],
                                 "builds": [{"id": "first"}, {"id": "second"}],
                                 "last_valid_candidate": {"id": "second"}})
    (tmp_path / "input" / MATERIALIZED_SPEC).write_text("{}")
    materialized = json.dumps({"sections": [{"id": "old"}]}).encode()
    selection = T.keep_better_reading(tools, earlier, materialized, {"ok": True})
    assert selection == {"kept": "earlier", "fit_earlier": None, "fit_new": None,
                         "body_fit_earlier": 0.8, "body_fit_new": 0.6}
    assert tools.state["last_valid_candidate"] == {"id": "first"}
    # The set-aside reading's builds are history only: a later build must never reuse one.
    assert [b["id"] for b in tools.state["builds"]] == ["first"]
    assert [b["id"] for b in tools.state["set_aside_builds"]] == ["first", "second"]
    assert tools.spec == {"sections": [{"id": "old"}]}
    assert [r["kept"] for r in tools.state["readings"]] == [True, False]


def test_the_new_reading_is_kept_when_it_fits_better_or_the_old_failed(tmp_path):
    earlier = {**first_hull_state(0.6), "readings": [{"combined_fit": 0.6, "kept": True}]}
    tools = FakeTools(tmp_path, {**first_hull_state(0.9), "readings": [{"combined_fit": 0.6, "kept": True}],
                                 "last_valid_candidate": {"id": "second"}})
    selection = T.keep_better_reading(tools, earlier, b"{}", {"ok": True})
    assert selection["kept"] == "new" and tools.state["last_valid_candidate"] == {"id": "second"}
    assert [r["kept"] for r in tools.state["readings"]] == [False, True]


def test_an_equal_fit_keeps_the_earlier_reading(tmp_path):
    tools = FakeTools(tmp_path, {**first_hull_state(0.8), "last_valid_candidate": {"id": "second"}})
    assert T.keep_better_reading(tools, first_hull_state(0.8), b"{}", {"ok": True})["kept"] == "earlier"


def test_a_failed_new_build_keeps_the_earlier_reading(tmp_path):
    earlier = first_hull_state(0.5)
    tools = FakeTools(tmp_path, {**first_hull_state(0.9), "last_valid_candidate": {"id": "second"}})
    selection = T.keep_better_reading(tools, earlier, b'{"sections": []}', {"ok": False})
    assert selection["kept"] == "earlier" and tools.state["last_valid_candidate"] == {"id": "first"}


def test_the_draft_fit_ranks_readings_before_the_body_plan_fit(tmp_path):
    # shipd-1-08158-3v-L1 Sonnet live: the first reading put x = 0 3 m forward of
    # the aft end; its body plan fit its own frame better (0.919 against 0.872)
    # but its hull was 11.9 % RMS against 5.3 %. The three-view fit in the
    # code-measured frame ranks them the other way.
    earlier = first_hull_state(0.919, draft_fit=0.70)
    tools = FakeTools(tmp_path, {**first_hull_state(0.872, draft_fit=0.78), "last_valid_candidate": {"id": "second"}})
    selection = T.keep_better_reading(tools, earlier, b"{}", {"ok": True})
    assert selection["kept"] == "new" and tools.state["last_valid_candidate"] == {"id": "second"}
    assert selection["fit_earlier"] == 0.70 and selection["body_fit_earlier"] == 0.919


def test_better_reading_compares_like_with_like():
    assert T.better_reading({"draft_fit": 0.7, "combined_fit": 0.9}, {"draft_fit": 0.8, "combined_fit": 0.5})
    # One reading without a draft fit: both are compared on the body-plan fit.
    assert not T.better_reading({"draft_fit": None, "combined_fit": 0.9}, {"draft_fit": 0.8, "combined_fit": 0.5})
    assert not T.better_reading({"draft_fit": 0.7, "combined_fit": 0.9}, {"draft_fit": None, "combined_fit": None})


def test_a_reading_with_the_same_setup_is_recorded_and_the_next_one_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "READINGS", 3)
    tools = FakeTools(tmp_path, first_hull_state(0.8, draft_fit=0.7))
    assert T.start_next_reading(tools)["reading"] == 2 and tools.state["reading_open"] == 1
    # Reading 2 gave the kept setup again: no first hull was built, so no record yet.
    tools.state.update(description_phase="complete", vessel_description={"stations": [{"id": "1"}]})
    following = T.finish_reading(tools)
    assert following["reading"] == 3 and following["of"] == 3
    assert tools.state["readings"][1] == {"draft_fit": None, "combined_fit": None, "station_count": 1,
                                          "same_setup": True, "kept": False}
    assert tools.state["description_phase"] == "views" and tools.state["reading_open"] == 2
    # Reading 3 built a first hull (keep_better_reading added its record): the readings end.
    tools.state["readings"].append({"draft_fit": 0.6, "kept": False})
    assert T.finish_reading(tools) is None and "reading_open" not in tools.state
    assert T.finish_reading(tools) is None  # nothing open


def test_two_readings_end_after_the_second(tmp_path):
    tools = FakeTools(tmp_path, first_hull_state(0.8))
    T.start_next_reading(tools)
    tools.state["readings"].append({"draft_fit": None, "kept": False})
    assert T.finish_reading(tools) is None and len(tools.state["readings"]) == T.READINGS == 2


def test_profile_and_plan_setups_count_as_setup_changes():
    old = {"a": {"view": "body", "baseline_px": 398.0},
           "b": {"view": "profile", "pixels_per_metre": 19.0, "baseline_px": 398.0, "x_origin_px": 170.0},
           "c": {"view": "plan", "pixels_per_metre": 19.0, "baseline_px": 595.0, "x_origin_px": 170.0}}
    same = {key: {**value} for key, value in old.items()}
    same["b"]["baseline_px"] = 399.0  # within SETUP_DATUM_PX
    assert T.view_setup_changes(old, same) == []
    moved = {key: {**value} for key, value in old.items()}
    moved["b"]["baseline_px"] = 359.5
    moved["c"]["x_direction"] = -1
    assert T.view_setup_changes(old, moved) == ["profile: baseline_px 398 -> 359.5", "plan: x direction None -> -1"]
    # A view read in one reading only is no change.
    assert T.view_setup_changes({"a": old["a"]}, moved) == []


def test_a_repeat_reading_keeps_the_kept_readings_setups_and_restores_them(tmp_path):
    tools = FakeTools(tmp_path, first_hull_state(0.8, draft_fit=0.7))
    T.start_next_reading(tools)
    assert tools.state["kept_reading"]["sheet_setups"] == {"setup-1": {}}
    # Reading 2 reads other setups and builds a worse hull: the earlier one stays, with its setups.
    tools.state.update(sheet_setups={"setup-2": {"view": "profile"}}, vessel_description={"stations": []},
                       draft_fit={"draft_fit": 0.6}, last_valid_candidate={"id": "second"})
    snapshot = json.loads(json.dumps(tools.state))
    snapshot["draft_fit"] = {"draft_fit": 0.7}
    (tmp_path / "input" / MATERIALIZED_SPEC).write_text("{}")
    selection = T.keep_better_reading(tools, snapshot, b'{"sections": []}', {"ok": True})
    assert selection["kept"] == "earlier"
    assert tools.state["sheet_setups"] == {"setup-1": {}}
    assert tools.state["vessel_description"] == {"stations": [{"id": "1"}, {"id": "2"}]}


def test_a_bottom_that_stops_above_the_keel_is_continued_to_it():
    from vessel_reconstruction.form_fit import Anchor
    # shipd-1-00679-3v-L0: the trace lost a shallow bottom and stopped at y 6.0 m, z 0.82 m.
    lost = Anchor("3", 30.0, [[6.0, 0.82], [7.0, 1.5], [8.5, 6.0]], {}, pixels_per_metre=19.0)
    kept = Anchor("7", 70.0, [[0.4, 0.06], [5.0, 0.5], [8.0, 6.0]], {}, pixels_per_metre=19.0)
    on_centreline = Anchor("9", 90.0, [[0.1, 1.4], [2.0, 3.0], [2.5, 6.0]], {}, pixels_per_metre=19.0)
    aft_end = Anchor("1", 10.0, [[0.8, 0.0], [5.0, 6.0]], {}, pixels_per_metre=19.0)
    fore_end = Anchor("10", 100.0, [[2.2, 1.45], [2.5, 6.0]], {}, pixels_per_metre=19.0)
    T.extend_bottoms_to_keel([aft_end, lost, kept, on_centreline, fore_end],
                             {"1": 0.0, "3": 0.06, "7": 0.06, "9": 1.0, "10": 1.0})
    assert lost.extended and lost.points_yz_m[0][1] == 0.06 and lost.points_yz_m[-3] == [6.0, 0.82]
    # Continue the lower segment, rather than drawing a chord to the centreline.
    slope = (7.0 - 6.0) / (1.5 - 0.82)
    assert abs(lost.points_yz_m[0][0] - (6.0 - slope * 0.76)) < 1e-9
    assert abs(lost.points_yz_m[1][1] - (0.06 + 0.76 / 6)) < 1e-9
    assert not kept.extended and len(kept.points_yz_m) == 3
    assert not on_centreline.extended  # the lowest point is on the centreline: nothing was lost
    assert not fore_end.extended  # the end stations shape the hull ends: left as traced


def test_readings_are_counted_by_reading_not_by_record(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "READINGS", 3)
    tools = FakeTools(tmp_path, first_hull_state(0.8, draft_fit=0.7))
    T.start_next_reading(tools)
    # Reading 2 rebuilt twice (body setup, then describe_vessel): two records, one reading.
    tools.state["readings"] += [{"draft_fit": 0.6, "kept": False}, {"draft_fit": 0.65, "kept": False}]
    following = T.finish_reading(tools)
    assert following is not None and following["reading"] == 3
    assert T.finish_reading(tools) is None
