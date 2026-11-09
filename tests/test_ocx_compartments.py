"""Tanks as OCX compartments (docs/TANKS_V1.md section 7), on synthetic box tanks only."""
from pathlib import Path
import shutil

import numpy as np
import pytest
import trimesh

from test_structure_export import schema_dir, synthetic_block
from vessel_reconstruction import tanks
from vessel_reconstruction.structure import ocx
from vessel_reconstruction.structure.tank_faces import patch_corners, planar_faces

needs_schema = pytest.mark.skipif(shutil.which("xmllint") is None or schema_dir() is None,
                                  reason="xmllint or the local OCX 3.0.1 XSD (git-ignored work/sources) is missing")
SAMPLE_PARTS = {"vlcc": ("work", "sources", "ocx_models_platform", "models", "D-VLCC_1-HOLD-OCX-simple_v3.3docx"),
                "napa": ("work", "sources", "ocx_models_ocxtools", "tests", "data", "NAPA-OCX_M9.3docx")}


def sample(key: str) -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent.joinpath(*SAMPLE_PARTS[key])
        if candidate.is_file():
            return candidate
    return None


def box(low, high) -> np.ndarray:
    mesh = trimesh.creation.box(extents=np.subtract(high, low))
    mesh.apply_translation(np.add(low, high) / 2)
    return mesh.triangles


def synthetic_tanks() -> list:
    """Ballast (printed density), fuel (default density), a void, an L-shaped fresh water tank, a tank
    whose ID is not an XML name, and one that is not built."""
    return [
        tanks.Tank("wb1", "No 1 water ballast", "water ballast", box((1, -1, 0.5), (3, 2, 4.5)), ("2", "6"),
                   density_t_m3=1.025, source_labels={"geometry": "traced", "density": "read"}),
        tanks.Tank("fo1", "Fuel oil tank <port>", "fuel oil", box((4, -1, 0), (6, 1, 2)), ("6", "8")),
        tanks.Tank("v1", "Cofferdam", "dry", box((7, 0, 0), (8, 1, 1))),
        tanks.Tank("fw1", "Fresh water L", "fresh water", tanks.prism_triangles(9, 11, [(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (0, 2)])),
        tanks.Tank("=evil 1", "Odd id", "misc", box((12, 0, 0), (13, 2, 3))),
        tanks.Tank("gone", "Not built", "fuel oil", None),
    ]


def test_box_has_six_faces_and_an_l_prism_has_eight_sides_and_two_caps():
    box_faces = planar_faces(box((0, 0, 0), (2, 3, 4)))
    assert len(box_faces) == 6 and all(len(f.loops) == 1 and len(f.loops[0]) == 4 for f in box_faces)
    l_faces = planar_faces(tanks.prism_triangles(0, 2, [(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (0, 2)]))
    assert len(l_faces) == 8
    caps = [f for f in l_faces if abs(f.normal[0]) > 0.99]
    assert len(caps) == 2 and all(len(f.loops[0]) == 6 for f in caps)


def test_face_loops_enclose_the_face_and_the_patch_spans_it():
    for face in planar_faces(box((0, 0, 0), (2, 3, 4))):
        corners = np.array(patch_corners(face))
        outer = np.array(face.loops[0])
        assert corners.min(axis=0) == pytest.approx(outer.min(axis=0))
        assert corners.max(axis=0) == pytest.approx(outer.max(axis=0))


def test_export_writes_one_compartment_per_built_tank(tmp_path):
    path = tmp_path / "tanks.3docx"
    assert ocx.export_ocx(None, path, tanks=synthetic_tanks()) == 5
    read = {c.name: c for c in ocx.read_compartments(path)}
    assert set(read) == {"wb1", "fo1", "v1", "fw1", "=evil 1"}
    assert {name: c.purpose for name, c in read.items()} == {
        "wb1": "Ballast", "fo1": "Fuel", "v1": "Void", "fw1": "Freshwater", "=evil 1": "Other"}
    assert read["wb1"].volume_m3 == pytest.approx(24.0)
    assert read["wb1"].centre_m == pytest.approx((2.0, 0.5, 2.5))
    assert read["wb1"].density_kg_m3 == pytest.approx(1025.0) and read["wb1"].cargo_type == "water ballast"
    assert read["fo1"].density_kg_m3 == pytest.approx(850.0) and read["fo1"].cargo_type == "fuel oil"
    assert read["v1"].density_kg_m3 is None  # a void is a unit cargo: no liquid
    assert read["fw1"].volume_m3 == pytest.approx(2 * 4.0) and read["fw1"].face_count == 8
    assert read["wb1"].face_count == 6
    text = path.read_text()
    assert "engineering_approved=false" in text and "volume=traced" in text and "density=read" in text
    assert "Fuel oil tank &lt;port&gt;" in text  # the display name is escaped in the description


def test_round_trip_of_tanks_only_and_of_structure_with_tanks(tmp_path):
    model = synthetic_tanks()
    tanks_only = tmp_path / "tanks.3docx"
    ocx.export_ocx(None, tanks_only, tanks=model)
    trip = ocx.round_trip(None, tanks_only, model)["compartments"]
    assert trip == {"tanks": 5, "compartments_read": 5, "count_equal": True, "purpose_equal": 5,
                    "volume_equal": 5, "centre_equal": 5, "all_equal": True}
    both = tmp_path / "both.3docx"
    block = synthetic_block()
    assert ocx.export_ocx(block, both, tanks=model) == len(block["members"]) + 5
    result = ocx.round_trip(block, both, model)
    assert result["all_equal"] and result["plates_read"] == 4 and result["compartments"]["compartments_read"] == 5
    assert ocx.round_trip(block, both)["all_equal"] and "compartments" not in ocx.round_trip(block, both)


def test_file_without_tanks_is_unchanged_in_structure(tmp_path):
    path = tmp_path / "block.3docx"
    ocx.export_ocx(synthetic_block(), path)
    assert "<ocx:Arrangement" not in path.read_text() and ocx.read_compartments(path) == []


@needs_schema
def test_tanks_only_and_combined_files_are_schema_valid(tmp_path):
    for block, name in ((None, "tanks.3docx"), (synthetic_block(), "both.3docx")):
        path = tmp_path / name
        ocx.export_ocx(block, path, tanks=synthetic_tanks())
        check = ocx.validate(path, schema_dir())
        assert check.valid, check.errors
    broken = tmp_path / "broken.3docx"
    broken.write_text((tmp_path / "both.3docx").read_text().replace('ocx:compartmentPurpose="Ballast"',
                                                                  'ocx:compartmentPurpose="Tank"'))
    assert not ocx.validate(broken, schema_dir()).valid


@needs_schema
def test_compartments_added_to_an_existing_structure_file_are_schema_valid(tmp_path):
    source, target = tmp_path / "block.3docx", tmp_path / "merged.3docx"
    ocx.export_ocx(synthetic_block(), source)
    assert ocx.add_compartments(source, target, synthetic_tanks())
    assert ocx.validate(target, schema_dir()).valid
    assert len(ocx.read_compartments(target)) == 5 and len(ocx.read_plates(target)) == 4
    assert not ocx.add_compartments(target, tmp_path / "twice.3docx", synthetic_tanks())  # has an Arrangement
    assert not ocx.add_compartments(source, tmp_path / "none.3docx", [])


@pytest.mark.skipif(sample("napa") is None, reason="OCX sample models (git-ignored work/sources) are missing")
def test_reader_parses_the_napa_sample_compartments():
    read = {c.name: c for c in ocx.read_compartments(sample("napa"))}
    assert len(read) == 2
    ballast = read["BALLASTP"]
    assert ballast.purpose == "Ballast" and ballast.volume_m3 == pytest.approx(37.954)
    assert ballast.centre_m == pytest.approx((5.03188, 7.43997, 0.8276))
    assert ballast.density_kg_m3 == pytest.approx(1000.0) and ballast.cargo_type == "water ballast"
    assert ballast.face_count == 8  # a chined tank


@pytest.mark.skipif(sample("vlcc") is None, reason="OCX sample models (git-ignored work/sources) are missing")
def test_reader_parses_the_vlcc_sample_compartments():
    read = {c.name: c for c in ocx.read_compartments(sample("vlcc"))}
    assert len(read) == 5
    cargo = read["CO_C3"]
    assert cargo.purpose == "Cargo" and cargo.volume_m3 == pytest.approx(33586.556)
    assert cargo.density_kg_m3 == pytest.approx(970.0) and cargo.cargo_type == "crude oil"
    assert cargo.face_count == 6
