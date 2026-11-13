"""Build a public KVLCC2 transport example, not a full-hull accuracy claim.

Input is the public IGES, extracted into its own empty work directory. All solver
outputs are captured, including limitations. No measured resistance is read.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from vessel_reconstruction.design_record import DesignRecord, capture_result, quantity, restore_result
from vessel_reconstruction.holtrop import HoltropHull, holtrop_resistance
from vessel_reconstruction.hull_variation import build_candidate, section_properties, vary_sections
from vessel_reconstruction.hull_waterlines import sample_supported_iges
from vessel_reconstruction.performance import fuel_per_day, propulsion_power

SOURCE = "https://simman2020.kr/contents/Ship_data_summary.php"


def build(iges: Path) -> DesignRecord:
    hull, sampling = sample_supported_iges(
        iges, face_indices=[2, 4, 5, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18],
        source_extent_m=(-328.1, 5.6), source_z_levels_m=[0.5, 1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20, 20.8, 22, 24, 26, 27.9],
        draft_source_z_m=20.8, interior_x_m=-160, parallel_source_x_m=(-220, -120),
        reverse_x=True, source_z_direction=-1)
    cb, lcb = section_properties(hull)
    varied = vary_sections(hull, length_m=hull.length_m, breadth_m=hull.breadth_m,
                           draft_m=hull.draft_m, cb=cb * 1.01, lcb_fraction=lcb / hull.length_m)
    variation = build_candidate(varied).report
    # Published full-vessel particulars: separate basis from the trimmed shell.
    inputs = HoltropHull(lwl_m=325.5, beam_m=58, draft_m=20.8, volume_m3=312622,
                         cm=0.998, cwp=0.9077, lcb_percent_lwl_forward=3.48,
                         wetted_surface_m2=27194)
    speed_kn = 14.5
    speed_ms = speed_kn * 1852 / 3600
    resistance = holtrop_resistance(inputs, speed_ms=speed_ms,
                                    water_density_kg_m3=1025, kinematic_viscosity_m2_s=1.19e-6)
    power = propulsion_power(effective_power_kw=resistance.effective_power_kw,
                             thrust_deduction=0.2, wake_fraction=0.3,
                             open_water_efficiency=0.65, relative_rotative_efficiency=1.0,
                             shaft_efficiency=0.98)
    fuel = fuel_per_day(brake_power_kw=power.brake_power_kw, sfoc_g_per_kwh=170)
    original = dict(hull_variation={"sampling": sampling, "candidate": variation},
                    hydrostatics=variation["hydrostatics"],
                    resistance={"inputs": asdict(inputs), "speed_ms": speed_ms,
                                "water_density_kg_m3": 1025.0, "kinematic_viscosity_m2_s": 1.19e-6,
                                "output": asdict(resistance)},
                    power=asdict(power), fuel=asdict(fuel), capacities={}, stability={})
    # Explicit units for every numeric source field; unknown numeric fields fail.
    units = {name: "1" for name in ["selected_faces", "excluded_faces", "reverse_x", "source_z_direction", "station_count", "waterline_count", "edge_samples", "design_cb", "mesh_volume_relative_error", "cm", "cwp", "appendage_form_factor", "stern_parameter", "tunnel_coefficient", "form_factor", "friction_coefficient", "correlation_coefficient", "reynolds", "froude", "hull_efficiency", "thrust_deduction", "wake_fraction", "open_water_efficiency", "relative_rotative_efficiency", "shaft_efficiency"]}
    def assign(value):
        if isinstance(value, dict):
            for name, child in value.items():
                for suffix, unit in [("_m3", "m3"), ("_m2", "m2"), ("_m", "m"), ("_kw", "kW"), ("_n", "N"), ("_ms", "m/s")]:
                    if name.endswith(suffix):
                        units[name] = unit
                assign(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                assign(child)
    assign(original)
    units.update(value="t/day", lcb_percent_lwl_forward="%", sfoc_g_per_kwh="g/kWh",
                 density_t_per_m3="t/m3", displacement_t="t", cb="1", cp="1",
                 triangles="1", mesh_vs_build_volume_relative="1",
                 disconnected_intervals_m="m", water_density_kg_m3="kg/m3",
                 kinematic_viscosity_m2_s="m2/s")
    metadata = dict(method="public KVLCC2 transport example; separate trimmed and full-vessel bases", method_version="1.0.0", sources=[SOURCE, "docs/plans/2026-11-12-hull-variation.md"])
    methods = dict(hull_variation="smooth longitudinal station shifts and retained-shell sampling",
                   hydrostatics=variation["hydrostatics"]["method"], resistance=resistance.method,
                   power="propulsion efficiency accounting", fuel="constant-load daily fuel accounting",
                   capacities="not supplied", stability="not supplied")
    results = {name: capture_result(value, units=units, **{**metadata, "method": methods[name]})["value"]
               for name, value in original.items()}
    assert {name: restore_result({"kind": "object", "value": value}) for name, value in results.items()} == json.loads(json.dumps(original))
    def q(value, unit):
        return quantity(value, unit, **metadata)
    record = dict(schema_version="1.0.0", design_id="public-kvlcc2-example", name="KVLCC2 public transport example", status="draft", engineering_approved=False,
                  data_scope=dict(kind="public", customer_id=None, permitted_uses=["development"]),
                  requirements=dict(quantities={}, service_speed=dict(kn=q(speed_kn, "kn"), m_s=q(speed_ms, "m/s")), cargo_types=["crude oil"], class_notation=None, flag=None, constraints=[]),
                  main_dimensions=dict(length=q(320.0, "m"), beam=q(58.0, "m"), draft=q(20.8, "m")),
                  hull=dict(parameters=dict(retained_length=q(hull.length_m, "m")), surfaces=[dict(path="public/kvlcc2.igs", sha256=hashlib.sha256(iges.read_bytes()).hexdigest(), media_type="model/iges", source_id=SOURCE)], coordinate_system="m; aft cap x=0, x forward, y starboard, z up above retained bottom", notes=["Variation uses a trimmed shell, not the full ship. Holtrop uses separately stated published particulars and illustrative assumptions."]),
                  results=results, lineage=dict(parent_design_id="public-kvlcc2-retained", variation_parameters=dict(cb=q(cb * 1.01, "1"))), designer_decisions=[])
    for name in ["compartments", "tanks", "weights", "loading_conditions", "midship_section_inputs", "appendages"]:
        record[name] = []
    return DesignRecord.from_dict(record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iges", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    build(args.iges).save(args.out)


if __name__ == "__main__":
    main()
