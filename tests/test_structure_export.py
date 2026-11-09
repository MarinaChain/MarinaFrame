"""Steel table and OCX export of a structure block (docs/STRUCTURE_V2.md section 6), synthetic blocks only."""
import csv
from pathlib import Path
import shutil

import pytest

from vessel_reconstruction.structure import block3d, ocx, steel

SCHEMA_PARTS = ("work", "sources", "ocx_schema", "ocx", "ocx_301")


def schema_dir() -> Path | None:
    """The local OCX 3.0.1 XSD folder (git-ignored data), searched upwards from this file."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent.joinpath(*SCHEMA_PARTS)
        if (candidate / "OCX_Schema.xsd").is_file():
            return candidate
    return None


def member(member_id, label, group, box, area, thickness, source="printed", material="ASTM A131 - AB/A"):
    return {"member_id": member_id, "label": label, "group": group, "box": list(box), "area_m2": area,
            "thickness_mm": thickness, "thickness_source": source, "material": material,
            "material_source": "printed" if source == "printed" else "guessed",
            "sources": {"section": "traced", "length": "guessed"}, "table_row": None}


def synthetic_block():
    return {"breadth_m": 8.0, "depth_m": 11.0, "guesses": {"block_length_m": 10.0},
            "stations": {"bulkheads": [1.0, 9.0], "webs": [5.0], "frames": []},
            "members": [
                member("L/Bottom/bottom_shell/000", "bottom_shell", "longitudinal", (0, 0, 0, 10, 8, 0), 80.0, 20.0),
                member("L/Side_Shell/side_shell/001", "side_shell", "longitudinal", (0, 8, 2, 10, 8, 11), 90.0, 18.0,
                       material="AH36"),
                member("BH1/plate", "transverse_bulkhead", "transverse", (1, 0, 0, 1, 8, 11), 88.0, 12.0),
                member("FR010/frame/Bottom", "frame", "transverse", (5, 0, 0, 5, 8, 2), 16.0, 10.0, "guessed"),
            ]}


def test_steel_weight_is_area_times_thickness_times_density():
    rows = steel.member_weights(synthetic_block()["members"])
    assert rows[0]["volume_m3"] == pytest.approx(80.0 * 0.020)
    assert rows[0]["weight_t"] == pytest.approx(80.0 * 0.020 * 7.85)
    totals = {(t["group_by"], t["key"]): t for t in steel.weight_totals(rows)}
    expected = (80 * 0.020 + 90 * 0.018 + 88 * 0.012 + 16 * 0.010) * 7.85
    assert totals[("all", "all")]["weight_t"] == pytest.approx(expected)
    assert totals[("group", "longitudinal")]["members"] == 2
    assert totals[("thickness_source", "guessed")]["weight_t"] == pytest.approx(16 * 0.010 * 7.85)
    assert sum(t["weight_share"] for t in totals.values() if t["group_by"] == "label") == pytest.approx(1.0)


def test_steel_tables_carry_the_draft_stamp(tmp_path):
    paths = steel.write_steel_tables(synthetic_block(), tmp_path, "demo_DRAFT")
    text = paths["members"].read_text()
    assert text.startswith("# DRAFT") and "engineering_approved=false" in text
    rows = [r for r in csv.reader(line for line in text.splitlines() if not line.startswith("#"))]
    assert rows[0][0] == "member_id" and len(rows) == 5


def test_missing_thickness_is_guessed_and_material_is_labelled():
    members = [
        block3d.BlockMember("a", "deck", "longitudinal", (0, 0, 0, 1, 1, 0), 1.0, 20.0, "printed", table_row="Main Deck"),
        block3d.BlockMember("b", "deck", "longitudinal", (0, 0, 0, 1, 1, 0), 1.0, 30.0, "printed", table_row="Other"),
        block3d.BlockMember("c", "deck", "longitudinal", (0, 0, 0, 1, 1, 0), 1.0, None, "none"),
        block3d.BlockMember("d", "frame", "transverse", (0, 0, 0, 0, 1, 1), 1.0, 9.0, "guessed", table_row="Main Deck"),
    ]
    block3d.label_thickness_and_material(members, {"Main Deck": "AH36", "Side Shell": "A", "Bottom Shell": "A"})
    a, b, c, d = members
    assert (a.material, a.material_source) == ("AH36", "printed")
    assert (b.material, b.material_source) == ("A", "guessed")  # no printed material: most common one
    assert c.thickness_mm == 25.0 and c.thickness_source == "guessed"
    assert d.material_source == "guessed"  # a guessed scantling never has a printed material


def test_plate_corners_and_area():
    corners = ocx.plate_corners((1, 0, 0, 1, 8, 11))
    assert {c[0] for c in corners} == {1}
    assert ocx.polygon_area(corners) == pytest.approx(88.0)
    assert ocx.grade_of("ASTM A131 - AB/A") == "A"
    assert ocx.grade_of("AH36") == "A36"
    assert ocx.grade_of("ASTM A36") == "A"  # 250 MPa mild steel, not the 355 MPa AH36 class grade
    assert ocx.grade_of("E") == "A"  # not an OCX grade name: written as grade A
    assert ocx.grade_of(None) == "A"


def test_ocx_export_reads_back_equal(tmp_path):
    block = synthetic_block()
    path = tmp_path / "block.3docx"
    assert ocx.export_ocx(block, path) == 4
    plates = {p.name: p for p in ocx.read_plates(path)}
    assert plates["BH1/plate"].thickness_m == pytest.approx(0.012)
    assert plates["BH1/plate"].area_m2 == pytest.approx(88.0)  # from the contour
    trip = ocx.round_trip(block, path)
    assert trip["all_equal"] and trip["plates_read"] == 4


@pytest.mark.skipif(shutil.which("xmllint") is None or schema_dir() is None,
                    reason="xmllint or the local OCX 3.0.1 XSD (git-ignored work/sources) is missing")
def test_ocx_export_is_schema_valid_and_a_broken_file_is_not(tmp_path):
    path = tmp_path / "block.3docx"
    ocx.export_ocx(synthetic_block(), path)
    check = ocx.validate(path, schema_dir())
    assert check.valid, check.errors
    broken = tmp_path / "broken.3docx"
    broken.write_text(path.read_text().replace("<ocx:NetArea", "<ocx:NetAreaX").replace("</ocx:NetArea", "</ocx:NetAreaX"))
    assert not ocx.validate(broken, schema_dir()).valid
