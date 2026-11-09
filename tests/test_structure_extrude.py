"""Extrusion of section members along a hull and OCX stiffeners (docs/STRUCTURE_V2.md section 8).

Synthetic hulls only: a box prism (exact areas) and a V-bottom prism (bottom heights by formula).
"""
import pytest

from vessel_reconstruction import tanks
from vessel_reconstruction.structure import extrude, ocx, steel
from tests.test_structure_export import schema_dir

BOX_SECTION = [(-4.0, 0.0), (4.0, 0.0), (4.0, 4.0), (-4.0, 4.0)]
# V bottom: keel at z 0 on the centre line, bilge corner at (4, 1), side up to the deck at z 4.
V_SECTION = [(0.0, 0.0), (4.0, 1.0), (4.0, 4.0), (-4.0, 4.0), (-4.0, 1.0)]


def sections_of(polygon, x0=0.0, x1=10.0):
    slicer = tanks.HullSlicer(tanks.prism_triangles(x0, x1, polygon))
    return extrude.HullSections(slicer, -0.5, 4.0, dz=0.005)


def test_parse_profile_reads_printed_names():
    assert extrude.parse_profile("HP 100x6") == extrude.Profile("HP 100x6", "BulbFlat", 100, 6)
    assert extrude.parse_profile("HP140x8").height_mm == 140
    assert extrude.parse_profile("100x8").kind == "FlatBar"
    tee = extrude.parse_profile("LONG. GIRDERS: W:200x8 / FL:150x10.")
    assert (tee.kind, tee.height_mm, tee.web_mm, tee.flange_width_mm, tee.flange_thickness_mm) == ("TBar", 210, 8, 150, 10)
    assert extrude.parse_profile("PL 8,0") is None


def test_horizontal_plate_is_cut_to_the_hull_breadth():
    sections = sections_of(BOX_SECTION)
    contour, area = extrude.horizontal_plate(sections, [1.0, 2.0, 3.0], 1.3, (-1.875, 10.0))
    assert area == pytest.approx(2.0 * (4.0 + 1.875), rel=1e-3)
    assert max(p[1] for p in contour) == pytest.approx(4.0, abs=1e-3)
    assert extrude.horizontal_plate(sections, [9.5, 10.5], 1.3, (-1.0, 1.0)) is None  # leaves the hull


def test_vertical_plate_runs_from_the_bottom_shell_to_the_top():
    sections = sections_of(V_SECTION)
    contour, area = extrude.vertical_plate(sections, [1.0, 3.0], 2.0, 1.3)
    # The V bottom at y = 2 is at z = 0.5.
    assert min(p[2] for p in contour) == pytest.approx(0.5, abs=0.01)
    assert area == pytest.approx(2.0 * 0.8, abs=0.02)


def test_shell_strakes_split_at_seams_and_sum_to_the_girth():
    sections = sections_of(V_SECTION)
    seams = [extrude.Seam("y", 2.0, "2000 FCL"), extrude.Seam("z", 2.0, "level 2000")]
    girths = []
    for index in range(3):
        _, area, strake_girths = extrude.shell_strake(sections, [1.0, 3.0], +1, seams, index, 4.0)
        girths.append(strake_girths[0])
        assert area == pytest.approx(2.0 * strake_girths[0], rel=1e-6)
    bottom = (4.0 ** 2 + 1.0 ** 2) ** 0.5
    assert girths[0] == pytest.approx(bottom / 2, abs=0.01)
    assert girths[1] == pytest.approx(bottom / 2 + 1.0, abs=0.01)
    assert girths[2] == pytest.approx(2.0, abs=0.01)


def test_transverse_plate_and_inside_check():
    sections = sections_of(BOX_SECTION)
    contour, area = extrude.transverse_plate(sections, 5.0, (0.0, 1.3))
    assert area == pytest.approx(8.0 * 1.3, rel=1e-3)
    assert all(p[0] == 5.0 for p in contour)
    assert sections.inside(5.0, 4.005, 2.0) and not sections.inside(5.0, 4.05, 2.0)


def test_runs_of_keeps_contiguous_stations():
    assert extrude.runs_of([1, 2, 3, 4, 5, 6], lambda s: s != 3) == [[1, 2], [4, 5, 6]]
    assert extrude.runs_of([1, 2, 3], lambda s: s != 2) == []
    assert extrude.runs_of([1, 2, 4, 5], lambda s: True) == [[1, 2, 4, 5]]


def stiffener_block():
    profile = extrude.parse_profile("HP 100x6")
    stiffener = extrude.stiffener_member("G/T/A/frame_s", "frame", "transverse",
                                         [(14.0, 4.0, 1.3), (14.0, 4.5, 3.0), (14.0, 4.8, 4.2)], profile,
                                         "printed", "key", (0, -1, 0), {"position": "traced"}, "side frame")
    flat = extrude.stiffener_member("G/T/A/floor_stiff_s0500", "floor_stiffener", "transverse",
                                    [(14.0, 0.5, 0.1), (14.0, 0.5, 1.3)], extrude.parse_profile("100x8"),
                                    "printed", "label", (1, 0, 0), {}, "floor stiffener")
    contour = [(13.5, -4.0, 1.3), (19.0, -4.0, 1.3), (19.0, 4.0, 1.3), (13.5, 4.0, 1.3)]
    plate = extrude.plate_member("G/L/tank_top/27-28", "inner_bottom", "longitudinal", contour, 44.0,
                                 {"mm": 8.0, "source": "printed", "basis": "PL 8,0"}, {}, "tank top")
    return {"breadth_m": 4.8, "depth_m": 4.287, "length_m": 5.5, "members": [plate, stiffener, flat]}


def test_stiffener_volume_enters_the_steel_table():
    block = stiffener_block()
    rows = steel.member_weights(block["members"])
    stiffener = block["members"][1]
    assert rows[1]["volume_m3"] == pytest.approx(stiffener["length_m"] * 0.100 * 0.006 * extrude.BULB_AREA_SHARE)
    assert rows[0]["volume_m3"] == pytest.approx(44.0 * 0.008)


def test_ocx_writes_stiffeners_and_round_trips(tmp_path):
    block = stiffener_block()
    path = tmp_path / "stiffeners.3docx"
    assert ocx.export_ocx(block, path, name="test") == 3
    read = {s.name: s for s in ocx.read_stiffeners(path)}
    assert read["G/T/A/frame_s"].section == "HP 100x6"
    check = ocx.round_trip(block, path)
    assert check["all_equal"] and check["stiffeners"]["all_equal"] and check["plates_read"] == 1
    plate = ocx.read_plates(path)[0]
    assert plate.area_m2 == pytest.approx(5.5 * 8.0)  # the real outline, not a box
    folder = schema_dir()
    if folder is None or ocx.shutil.which("xmllint") is None:
        pytest.skip("OCX XSD or xmllint not available")
    result = ocx.validate(path, folder)
    assert result.valid, result.errors
