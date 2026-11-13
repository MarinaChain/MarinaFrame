"""Recompute stored performance evidence from its full recorded inputs."""
from dataclasses import asdict
import json
from pathlib import Path

from vessel_reconstruction.design_record import restore_result
from vessel_reconstruction.holtrop import HoltropHull, holtrop_resistance
from vessel_reconstruction.performance import fuel_per_day, propulsion_power


def test_public_performance_outputs_reproduce_exactly():
    data = json.loads((Path(__file__).parent / "fixtures/design_record/kvlcc2.json").read_text())
    results = {name: restore_result({"kind": "object", "value": evidence}) for name, evidence in data["results"].items()}
    resistance = results["resistance"]
    calculated = holtrop_resistance(HoltropHull(**resistance["inputs"]), speed_ms=resistance["speed_ms"],
                                    water_density_kg_m3=resistance["water_density_kg_m3"],
                                    kinematic_viscosity_m2_s=resistance["kinematic_viscosity_m2_s"])
    assert json.loads(json.dumps(asdict(calculated))) == resistance["output"]
    assert json.loads(json.dumps(asdict(propulsion_power(**results["power"]["inputs"])))) == results["power"]
    assert json.loads(json.dumps(asdict(fuel_per_day(**results["fuel"]["inputs"])))) == results["fuel"]
    variation = results["hull_variation"]["candidate"]
    assert variation["hydrostatics"] == results["hydrostatics"]
    assert variation["engineering_approved"] is False
