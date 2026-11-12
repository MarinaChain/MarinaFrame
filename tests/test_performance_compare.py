"""Synthetic-only evaluator contract; no external ship measurements."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vessel_reconstruction import performance_compare


def synthetic_case():
    return {
        "schema_version": 1, "ship": "synthetic", "scale": "model",
        "method": "holtrop_mennen_1982", "particulars_source": "synthetic dimensions",
        "hull": {"lwl_m": 100, "beam_m": 15, "draft_m": 5, "volume_m3": 4500,
                 "cm": 0.98, "cwp": 0.75, "lcb_percent_lwl_forward": -1,
                 "wetted_surface_m2": 2000},
        "water": {"density_kg_m3": 1000, "kinematic_viscosity_m2_s": 1e-6},
        "measurements": [{"speed_ms": 3, "ct": 0.004,
                          "reference_surface_m2": 2000, "source": "synthetic row 1"}],
    }


def test_evaluator_contract_keeps_sources_and_draft_status():
    result = performance_compare.evaluate_case(synthetic_case())
    row = result["rows"][0]
    assert result["engineering_approved"] is False
    assert row["source"] == "synthetic row 1"
    assert row["scale"] == "model"
    assert row["method"] == "holtrop_mennen_1982"
    assert row["measured_effective_power_kw"] == pytest.approx(108)
    assert row["ct_error_percent"] == pytest.approx(row["effective_power_error_percent"])
    assert row["validity_warnings"]  # full-scale empirical regression at model scale
    assert "synthetic" in performance_compare.markdown_report([result])


def test_evaluator_preserves_different_reference_surface_basis():
    case = synthetic_case()
    case["measurements"][0]["reference_surface_m2"] = 2200
    row = performance_compare.evaluate_case(case)["rows"][0]
    assert row["measured_effective_power_kw"] == pytest.approx(118.8)
    assert row["ct_error_percent"] != pytest.approx(row["effective_power_error_percent"])


@pytest.mark.parametrize("change", [
    {"schema_version": 2}, {"scale": "automatic"}, {"measurements": []},
    {"method": "automatic"}, {"particulars_source": ""}, {"engineering_approved": True},
    {"sfoc_g_per_kwh": 180},
])
def test_evaluator_rejects_ambiguous_or_unsupported_inputs(change):
    case = synthetic_case()
    case.update(change)
    with pytest.raises(ValueError):
        performance_compare.evaluate_case(case)


def test_evaluator_includes_propulsion_and_explicit_fuel_assumptions():
    case = synthetic_case()
    case["propeller"] = dict(diameter_m=3,blade_count=4,pitch_diameter_ratio=1,
                              expanded_area_ratio=.7,shaft_efficiency=.98)
    case["sfoc_g_per_kwh"] = 180
    row = performance_compare.evaluate_case(case)["rows"][0]
    matching = row["propulsion"]["matching"]
    assert matching["operating_points"]
    point = matching["operating_points"][0]
    assert point["brake_power_kw"] > point["delivered_power_kw"]
    assert point["fuel_t_per_day"] == pytest.approx(point["brake_power_kw"]*180*24/1e6)
    assert matching["validity_warnings"]


def test_evaluator_requires_source_per_measurement():
    case = synthetic_case()
    case["measurements"][0]["source"] = ""
    with pytest.raises(ValueError):
        performance_compare.evaluate_case(case)


def test_cli_outputs_input_hash_and_never_overwrites_existing_outputs(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"cases": [synthetic_case()]}))
    out = tmp_path / "score.json"
    md = tmp_path / "score.md"
    command = [sys.executable, "-m", "vessel_reconstruction.performance_compare",
               "--input", str(path), "--output", str(out), "--markdown", str(md)]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    run = subprocess.run(command, capture_output=True, text=True, env=env)
    assert run.returncode == 0, run.stderr
    result = json.loads(out.read_text())
    assert len(result["input_sha256"]) == 64
    assert result["cases"][0]["rows"]
    old = out.read_bytes()
    run = subprocess.run(command, capture_output=True, text=True, env=env)
    assert run.returncode != 0
    assert out.read_bytes() == old
    assert md.read_text().startswith("# Performance comparison")
