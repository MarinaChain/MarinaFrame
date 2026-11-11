"""Accuracy summary: bands joined with a run's own facts, in short honest lines."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vessel_reconstruction.accuracy_bands import band
from vessel_reconstruction.accuracy_summary import (
    facts_from_build, hull_path_of, steel_facts, summarise, tank_facts)
from vessel_reconstruction.exports.source import load_build

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "accuracy_summary_cases.json").read_text(encoding="utf-8"))
EXPORT_TASK = FIXTURES / "exports" / "shipd-1-00679-L0" / "task"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_shared_cases_give_the_expected_lines(case):
    """The same cases run in app/ui-tests/accuracy.test.mjs against the JavaScript port."""
    for output, summary in summarise(case["facts"]).items():
        expected = case["expected"][output]
        assert summary.line == expected["line"]
        assert summary.chip == expected["chip"]
        assert summary.present == expected["present"] and summary.caution == expected["caution"]
        assert list(summary.detail_ids) == expected["detail_ids"]


def line_of(facts, output="hull"):
    return summarise(facts)[output].line


def test_all_traced_clean_sheet_still_says_what_was_measured():
    facts = {"hull": {"path": "model_reading", "labels": {"traced": 9}, "to_check": 0, "fit": 0.91}}
    line = line_of(facts)
    assert "9 of 9 sections traced" in line and "no open check items" in line and "fit score 0.91" in line
    assert band("hull.model_reading_clean").short in line


def test_many_guessed_values_are_counted_and_flagged():
    labels = {"traced": 2, "interpolated": 3, "ai_inferred": 5}
    summary = summarise({"hull": {"labels": labels, "to_check": 8}})["hull"]
    assert "2 of 10 sections traced, 3 interpolated, 5 by AI" in summary.line and "8 to check" in summary.line
    assert summary.caution


def test_scanned_reader_path_quotes_holdouts_by_hull_type():
    base = {"path": "scanned_body_plan", "labels": {"traced": 4}}
    round_bilge = line_of({"hull": {**base, "hull_type": "round_bilge"}})
    assert "1.4 mm RMS on BUE GIRL" in round_bilge and "PARDON ME" not in round_bilge
    chine = line_of({"hull": {**base, "hull_type": "hard_chine"}})
    assert "missed on PARDON ME" in chine and "BUE GIRL" not in chine
    unknown = line_of({"hull": base})
    assert "BUE GIRL" in unknown and "PARDON ME" in unknown and "hull type not known" in unknown


def test_no_tanks_and_no_steel_say_none_and_carry_no_chip():
    summary = summarise({"hull": {}, "tanks": None, "steel": None})
    assert summary["tanks"].line == "Tanks: none in this run." and not summary["tanks"].present
    assert summary["steel"].line == "Steel: none in this run." and summary["steel"].chip == ""


def test_steel_weight_is_never_given_a_number():
    summary = summarise({"hull": {}, "steel": {"thickness_labels": {"printed": 1}}})["steel"]
    assert "weight not measured against a printed weight" in summary.line
    assert band("steel.weight").measured is False


def test_every_quoted_and_listed_band_exists_and_no_text_claims_approval():
    for case in CASES:
        for summary in summarise(case["facts"]).values():
            for band_id in (*summary.head_ids, *summary.detail_ids):
                band(band_id)
            assert "approved" not in summary.line.lower() and "verified" not in summary.line.lower()


@pytest.mark.parametrize("hull_type", [None, "round_bilge", "hard_chine"])
def test_invalid_bands_never_appear_in_a_run_summary(hull_type):
    invalid = band("hull.scanned_bumble_bee")
    assert invalid.outcome == "invalid"
    for summary in summarise({"hull": {"path": "scanned_body_plan", "hull_type": hull_type}}).values():
        assert invalid.id not in (*summary.head_ids, *summary.detail_ids)
        assert invalid.short not in summary.line
        assert invalid.chip not in summary.chip


def test_facts_of_a_real_export_fixture():
    build = load_build(EXPORT_TASK, "r3")
    facts = facts_from_build(build)
    hull = facts["hull"]
    assert hull["path"] == "model_reading" and hull["hull_type"] is None
    assert sum(hull["labels"].values()) == len(build.sections) and hull["to_check"] == 9
    assert hull["fit"] == pytest.approx(0.8572)
    assert facts["tanks"] is None and facts["steel"] is None


def test_body_plan_check_with_used_true_marks_the_scanned_path(tmp_path):
    (tmp_path / "body-plan-check.json").write_text(json.dumps({"used": True}), encoding="utf-8")
    assert hull_path_of(tmp_path) == "scanned_body_plan"
    (tmp_path / "body-plan-check.json").write_text(json.dumps({"used": False}), encoding="utf-8")
    assert hull_path_of(tmp_path) == "model_reading"
    (tmp_path / "body-plan-check.json").write_text("not json", encoding="utf-8")
    assert hull_path_of(tmp_path) == "model_reading"


def test_tank_and_steel_facts_from_tables(tmp_path):
    rows = [{"built": True, "source_labels": {"volume": "traced"}}, {"built": True, "sources": {"volume": "guessed"}},
            {"built": False}]
    assert tank_facts(rows) == {"built": 2, "total": 3, "path": None, "volume_labels": {"traced": 1, "guessed": 1}}
    assert tank_facts(None) is None
    (tmp_path / "x_steel_members.csv").write_text(
        "# DRAFT\nmember_id,thickness_source\nm1,printed\nm2,guessed\nm3,printed\n", encoding="utf-8")
    assert steel_facts(tmp_path) == {"thickness_labels": {"printed": 2, "guessed": 1}}
    assert steel_facts(tmp_path / "missing") is None and steel_facts(None) is None
