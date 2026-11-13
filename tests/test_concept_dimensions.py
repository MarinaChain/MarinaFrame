"""Synthetic checks only: these are not a public-fleet reconstruction score."""

import json
import math
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from dataclasses import replace

import pytest

from vessel_reconstruction.concept_dimensions import (
    FleetModel,
    FleetShip,
    Requirements,
    displacement_t,
    froude_number,
)


def fleet():
    # Exact power laws allow a check against known coefficients, without ship truth.
    rows = []
    for index, dwt in enumerate((20000, 30000, 40000, 50000, 70000, 90000, 120000, 150000, 200000, 300000)):
        scale = (dwt / 50000) ** (1 / 3)
        rows.append(FleetShip(
            ship_id=f"synthetic-{index}", design_id=f"design-{index}",
            dwt_t=dwt, lpp_m=180 * scale, beam_m=32 * scale,
            depth_m=18 * scale, draft_m=12 * scale, cb=0.8,
            cargo_volume_m3=dwt * 1.15, service_speed_kn=14,
            sources=("synthetic:power-law-test",), cargo_types=("oil",),
        ))
    return rows


def requirement(**kwargs):
    return Requirements(dwt_t=60000, cargo_volume_m3=69000, service_speed_kn=14, **kwargs)


def test_power_law_recovery_and_metadata():
    result = FleetModel.fit(fleet()).propose(requirement())
    dimensions = result.to_record_fragment()["main_dimensions"]
    for name, expected in {"lpp": 180 * 1.2 ** (1 / 3), "beam": 32 * 1.2 ** (1 / 3), "cb": 0.8}.items():
        value = dimensions[name]
        assert value["value"] == pytest.approx(expected)
        assert value["uncertainty"]["lower"] < expected < value["uncertainty"]["upper"]
        assert set(value) == {"value", "unit", "uncertainty", "method", "method_version", "sources", "status"}
        assert value["status"] == "review_required"
    assert result.to_record_fragment()["engineering_approved"] is False
    json.dumps(result.to_record_fragment(), allow_nan=False)


def test_reference_differences_and_missing_fields():
    model = FleetModel.fit(fleet())
    result = model.propose(Requirements(dwt_t=50000, cargo_volume_m3=57500, service_speed_kn=14))
    reference = result.to_record_fragment()["references"][0]
    assert reference["ship_id"] == "synthetic-3"
    assert reference["differences"]["dwt"]["value"] == 0
    assert reference["differences"]["cargo_volume"]["value"] == pytest.approx(0, abs=1e-9)
    assert reference["differences"]["fuel_per_day"]["value"] is None
    assert reference["differences"]["fuel_per_day"]["uncertainty"]["reason"]
    assert reference["dimensions"]["lpp"]["value"] == 180
    assert reference["differences"]["payload"]["value"] is None


def test_port_constraints_do_not_clip_statistical_ranges():
    model = FleetModel.fit(fleet())
    unconstrained = model.propose(requirement()).to_record_fragment()
    constrained = model.propose(requirement(max_beam_m=20, max_draft_m=8)).to_record_fragment()
    assert constrained["main_dimensions"] == unconstrained["main_dimensions"]
    assert {item["status"] for item in constrained["constraints"]} == {"infeasible"}
    assert constrained["feasible"] is False


def test_partial_constraint_overlap_requires_review():
    result = FleetModel.fit(fleet()).propose(requirement(max_beam_m=34)).to_record_fragment()
    assert result["constraints"][0]["status"] == "overlap"
    assert result["feasible"] is None


def test_extrapolation_warns_and_ranking_is_stable():
    left = FleetModel.fit(fleet()).propose(Requirements(dwt_t=400000)).to_record_fragment()
    right = FleetModel.fit(list(reversed(fleet()))).propose(Requirements(dwt_t=400000)).to_record_fragment()
    assert left == right
    assert any("extrapolation" in warning for warning in left["warnings"])


def test_excluded_designs_do_not_enter_fit_or_references():
    rows = fleet()
    rows.append(replace(rows[3], ship_id="sister-ship"))
    model = FleetModel.fit(rows, excluded_ship_ids={"synthetic-3"})
    assert "synthetic-3" not in model.training_ship_ids
    assert "sister-ship" not in model.training_ship_ids
    assert all(item["ship_id"] not in {"synthetic-3", "sister-ship"} for item in model.propose(requirement()).to_record_fragment()["references"])


def test_same_design_has_one_vote():
    rows = fleet()
    expected = FleetModel.fit(rows).propose(requirement()).to_record_fragment()["main_dimensions"]
    rows.append(replace(rows[3], ship_id="sister"))
    actual = FleetModel.fit(rows).propose(requirement()).to_record_fragment()["main_dimensions"]
    assert actual == expected


@pytest.mark.parametrize("field,value", [("dwt_t", 0), ("dwt_t", math.nan), ("dwt_t", math.inf), ("cargo_volume_m3", -1), ("service_speed_kn", 0), ("range_m", -1), ("max_draft_m", 0)])
def test_invalid_requirements(field, value):
    with pytest.raises(ValueError):
        Requirements(**{"dwt_t": 50000, field: value})


@pytest.mark.parametrize("field,value", [("lpp_m", 0), ("cb", 1.1), ("draft_m", 30), ("sources", ()), ("length_basis", "loa"), ("design_id", "")])
def test_invalid_fleet_rows(field, value):
    with pytest.raises(ValueError):
        replace(fleet()[0], **{field: value})


def test_duplicate_and_insufficient_training_rows_fail():
    with pytest.raises(ValueError, match="unique"):
        FleetModel.fit(fleet() + [fleet()[0]])
    with pytest.raises(ValueError, match="independent"):
        FleetModel.fit(fleet()[:3])
    with pytest.raises(ValueError, match="span"):
        FleetModel.fit([replace(row, dwt_t=50000) for row in fleet()])


def test_requirements_fragment_preserves_strings_and_speed_units():
    req = requirement(range_m=1000000, cargo_types=("oil",), class_notation="example class", flag="example flag")
    record = req.to_record_fragment()
    assert record["service_speed_m_s"]["value"] == pytest.approx(14 * 1852 / 3600)
    assert record["service_speed_kn"]["value"] == 14
    assert record["range"]["unit"] == "m"
    assert record["class_notation"] == "example class"
    assert record["flag"] == "example flag"


def test_physical_cross_checks_use_explicit_density_and_lpp():
    assert displacement_t(200, 32, 12, 0.8, water_density_t_m3=1.025) == pytest.approx(62976)
    assert froude_number(14, 200) == pytest.approx((14 * 1852 / 3600) / math.sqrt(9.80665 * 200))
    with pytest.raises(ValueError):
        displacement_t(200, 32, 12, 1.1)
    with pytest.raises(ValueError):
        froude_number(14, 0)


def test_unknown_cargo_cannot_prove_capacity_or_type():
    rows = [replace(row, cargo_volume_m3=None, cargo_types=()) for row in fleet()]
    record = FleetModel.fit(rows).propose(requirement(cargo_types=("chemical",))).to_record_fragment()
    assert any("cargo" in warning for warning in record["warnings"])
    assert record["references"][0]["differences"]["cargo_volume"]["value"] is None


@pytest.mark.parametrize("field", ["dwt_t", "lpp_m", "beam_m", "depth_m", "draft_m", "cb"])
def test_required_fleet_numbers_cannot_be_null(field):
    with pytest.raises(ValueError):
        replace(fleet()[0], **{field: None})


def test_unresolved_ship_exclusion_fails_closed():
    with pytest.raises(ValueError, match="unresolved"):
        FleetModel.fit(fleet(), excluded_ship_ids={"absent-reserved-ship"})


@pytest.mark.parametrize("value", [True, False, "50000"])
def test_non_numeric_requirement_values_fail(value):
    with pytest.raises(ValueError):
        Requirements(dwt_t=value)


def test_boolean_fleet_coefficient_fails():
    with pytest.raises(ValueError):
        replace(fleet()[0], cb=True)


def test_port_limits_do_not_prove_overall_feasibility():
    record = FleetModel.fit(fleet()).propose(requirement(max_beam_m=100)).to_record_fragment()
    assert record["port_limits_within_ranges"] is True
    assert record["feasible"] is None


def test_json_cli(tmp_path):
    root = Path(__file__).resolve().parents[1]
    fleet_path = tmp_path / "fleet.json"
    req_path = tmp_path / "requirements.json"
    fleet_path.write_text(json.dumps([asdict(row) for row in fleet()]))
    req_path.write_text(json.dumps({"dwt_t": 60000}))
    process = subprocess.run(
        [sys.executable, str(root / "scripts/concept_dimensions.py"),
         "--fleet", str(fleet_path), "--requirements", str(req_path),
         "--exclude-ship", "synthetic-0"], capture_output=True, text=True, cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
    )
    assert process.returncode == 0, process.stderr
    record = json.loads(process.stdout)
    assert "synthetic-0" not in record["training_ship_ids"]
    assert record["engineering_approved"] is False


def test_neighbour_ranges_are_reported_with_provenance():
    record = FleetModel.fit(fleet()).propose(requirement()).to_record_fragment()
    assert set(record["neighbour_ranges"]) == {"lpp", "beam", "depth", "draft", "cb"}
    for quantity in record["neighbour_ranges"].values():
        assert quantity["method"] == "nearest_neighbour_envelope"
        assert quantity["sources"]
        assert quantity["uncertainty"]["basis"]
