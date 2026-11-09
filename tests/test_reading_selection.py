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


def first_hull_state(fit: float) -> dict:
    return {"sheet_only": True, "fit_score": {"combined_fit": fit}, "description_phase": "complete",
            "vessel_description": {"stations": [{"id": "1"}, {"id": "2"}]},
            "described_views": [{"view_id": "body"}], "sheet_setups": {"setup-1": {}},
            "vessel_table": {"stations": []}, "last_valid_candidate": {"id": "first"}, "builds": [{"id": "first"}]}


def test_first_hull_starts_a_second_reading_and_keeps_the_hull(tmp_path):
    tools = FakeTools(tmp_path, first_hull_state(0.8))
    started = T.start_next_reading(tools)
    assert started["reading"] == 2 and started["of"] == T.READINGS
    assert tools.state["description_phase"] == "views" and tools.state["sheet_setups"] == {}
    assert tools.state["vessel_table"] == {"stations": []}  # the first hull stays the draft
    assert tools.state["readings"] == [{"combined_fit": 0.8, "station_count": 2, "kept": True}]
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
    assert selection == {"kept": "earlier", "fit_earlier": 0.8, "fit_new": 0.6}
    assert tools.state["last_valid_candidate"] == {"id": "first"}
    assert [b["id"] for b in tools.state["builds"]] == ["first", "second"]
    assert tools.spec == {"sections": [{"id": "old"}]}
    assert [r["kept"] for r in tools.state["readings"]] == [True, False]


def test_the_new_reading_is_kept_when_it_fits_better_or_the_old_failed(tmp_path):
    earlier = {**first_hull_state(0.6), "readings": [{"combined_fit": 0.6, "kept": True}]}
    tools = FakeTools(tmp_path, {**first_hull_state(0.9), "readings": [{"combined_fit": 0.6, "kept": True}],
                                 "last_valid_candidate": {"id": "second"}})
    selection = T.keep_better_reading(tools, earlier, b"{}", {"ok": True})
    assert selection["kept"] == "new" and tools.state["last_valid_candidate"] == {"id": "second"}
    assert [r["kept"] for r in tools.state["readings"]] == [False, True]


def test_a_failed_new_build_keeps_the_earlier_reading(tmp_path):
    earlier = first_hull_state(0.5)
    tools = FakeTools(tmp_path, {**first_hull_state(0.9), "last_valid_candidate": {"id": "second"}})
    selection = T.keep_better_reading(tools, earlier, b'{"sections": []}', {"ok": False})
    assert selection["kept"] == "earlier" and tools.state["last_valid_candidate"] == {"id": "first"}
