"""Hull fairing in the pipeline's hull build: setting, check items, fallback."""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from draft_fixture import draft_drawing
from vessel_reconstruction import fairing
from vessel_reconstruction.draft import DRAFT_STATUS, make_guesses
from vessel_reconstruction.run_record import verify_run

pytestmark = pytest.mark.cad


def _sections(spec: dict, bad_station: str | None = None) -> list[dict]:
    """Fair synthetic sections on the fixture's stations; an optional bad cell at mid-height."""
    z = np.linspace(0., 3., 31)
    result = []
    for s in spec["sections"]:
        y = (1.2 - 0.02 * (s["x_m"] - 4.) ** 2) * (1 - (1 - z / 3.) ** 4) ** .5 + .05
        if s["id"] == bad_station:
            y = y + .3 * np.clip(1 - np.abs(z - 1.5) / .15, 0, 1)
        result.append({"id": s["id"], "x_m": s["x_m"], "points_yz_m": np.column_stack([y, z]).tolist(),
                       "coverage": 1., "confidence": 1., "source_label": "traced", "evidence": {}})
    return result


def _run(tmp_path, monkeypatch, sections, name="run"):
    from vessel_reconstruction import ingest
    from vessel_reconstruction.pipeline import reconstruct
    path, spec = draft_drawing(tmp_path / "input", count=5)
    monkeypatch.setattr(ingest, "extract_sections", lambda *args: {"sections": copy.deepcopy(sections), "gaps": []})
    spec["draft"] = {"status": DRAFT_STATUS, "guesses": make_guesses(spec["sections"], {}, {})}
    path.write_text(json.dumps(spec))
    return reconstruct(path, tmp_path / name)


def test_setting_off_builds_through_the_sections_as_observed(tmp_path, monkeypatch):
    monkeypatch.delenv(fairing.SETTING, raising=False)
    _, spec = draft_drawing(tmp_path / "spec", count=5)
    record = _run(tmp_path, monkeypatch, _sections(spec, "s2"))
    assert record["status"] == "review_required"
    assert "hull_fairing" not in record["diagnostics"]
    assert all("fairing" not in s for s in record["sections"])


def test_faired_build_is_valid_and_names_the_bad_cell(tmp_path, monkeypatch):
    monkeypatch.setenv(fairing.SETTING, "1")
    _, spec = draft_drawing(tmp_path / "spec", count=5)
    observed = _sections(spec, "s2")
    record = _run(tmp_path, monkeypatch, observed)
    assert record["status"] == "review_required", record["gaps"]
    assert record["exports"]["step"] == "model-draft.step"
    assert verify_run(tmp_path / "run")["valid"]
    report = record["diagnostics"]["hull_fairing"]
    assert report["applied"] and report["engineering_approved"] is False
    moved = [g for g in record["gaps"] if g["kind"] == "fairing_moved_point"]
    assert [g["section_id"] for g in moved] == ["s2"] and moved[0]["severity"] == "warning"
    faired = {s["id"]: s for s in record["sections"]}
    assert faired["s2"]["source_label"] == "traced"
    assert faired["s2"]["fairing"]["input_points_yz_m"] == observed[2]["points_yz_m"]
    # The bad cell (+0.3 m) is followed less than in full (docs/HULL_FAIRING.md 6).
    fair = _sections(spec)[2]["points_yz_m"][15]
    middle = faired["s2"]["points_yz_m"][15]
    assert middle[1] == fair[1] == 1.5
    assert middle[0] - fair[0] < 0.9 * 0.3


def test_fit_failure_falls_back_with_a_check_item(tmp_path, monkeypatch):
    monkeypatch.setenv(fairing.SETTING, "1")

    def broken(sections, **options):
        raise FloatingPointError("synthetic")
    monkeypatch.setattr(fairing, "fair_sections", broken)
    _, spec = draft_drawing(tmp_path / "spec", count=5)
    record = _run(tmp_path, monkeypatch, _sections(spec))
    assert record["status"] == "review_required"
    assert "fairing_fallback" in {g["kind"] for g in record["gaps"]}
    assert all("fairing" not in s for s in record["sections"])


def test_unbuildable_faired_sections_fall_back_to_the_observed_hull(tmp_path, monkeypatch):
    monkeypatch.setenv(fairing.SETTING, "1")

    def pinched(sections, **options):
        # A centreline pinch inside a section: the builder refuses it.
        result = copy.deepcopy(sections)
        result[1]["points_yz_m"][10][0] = 0.
        return result, {"method": fairing.METHOD, "applied": True, "check_items": []}
    monkeypatch.setattr(fairing, "fair_sections", pinched)
    _, spec = draft_drawing(tmp_path / "spec", count=5)
    observed = _sections(spec)
    record = _run(tmp_path, monkeypatch, observed)
    assert record["status"] == "review_required", record["gaps"]
    assert "fairing_fallback" in {g["kind"] for g in record["gaps"]}
    assert record["diagnostics"]["hull_fairing"]["applied"] is False
    assert [s["points_yz_m"] for s in record["sections"]] == [s["points_yz_m"] for s in observed]
    assert verify_run(tmp_path / "run")["valid"]
