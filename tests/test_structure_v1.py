"""Structure v1: member reading from a synthetic midship section sheet.

The fixture is drawn here with PyMuPDF; no dataset file is used. The ship
is a half-breadth double-bottom section: breadth 8 m, depth 10 m, double
bottom 1.5 m, bilge radius 1 m, at 20 drawing-mm per ship metre.
"""
from __future__ import annotations

import math

import pytest

fitz = pytest.importorskip("fitz")

from vessel_reconstruction.structure import read_section_pdf
from vessel_reconstruction.structure.midship_eval import (TruthElement, match, score_design,
                                                         summarise, truth_host, truth_label)
from vessel_reconstruction.structure.model import Word
from vessel_reconstruction.structure.tables import (read_plate_table, read_scale,
                                                   read_stiffener_table)

PAGE_W, PAGE_H = 1190.64, 841.92  # A3 landscape, points
PT_PER_MM = 72 / 25.4
SCALE = 20.0  # drawing mm per ship metre
ORIGIN_MM = (40.0, 40.0)  # drawing position of centreline at baseline


def pt(y_m: float, z_m: float) -> fitz.Point:
    """Ship metres to a PDF point."""
    x_mm = ORIGIN_MM[0] + SCALE * y_m
    z_mm = ORIGIN_MM[1] + SCALE * z_m
    return fitz.Point(x_mm * PT_PER_MM, PAGE_H - z_mm * PT_PER_MM)


def line(page, a, b):
    shape = page.new_shape()
    shape.draw_line(pt(*a), pt(*b))
    shape.finish(color=(0, 0, 0), width=0.24, closePath=False)
    shape.commit()


def text(page, x_mm, z_mm, value, size=6):
    page.insert_text(fitz.Point(x_mm * PT_PER_MM, PAGE_H - z_mm * PT_PER_MM), value, fontsize=size)


def draw_section(page, *, with_scale=True, with_orphan=True):
    # Bottom shell with the bilge as one path: flat to y=7, quarter arc to (8, 1).
    shape = page.new_shape()
    shape.draw_line(pt(0, 0), pt(7, 0))
    k = 0.5523  # cubic Bezier constant for a quarter circle
    shape.draw_bezier(pt(7, 0), pt(7 + k, 0), pt(8, 1 - k), pt(8, 1))
    shape.finish(color=(0, 0, 0), width=0.24, closePath=False)
    shape.commit()
    line(page, (8, 1), (8, 10))        # side shell
    line(page, (8, 8.5), (8, 10))      # shell strake, drawn over the side shell
    line(page, (2, 10), (8, 10))       # main deck (hatch opening inboard of 2 m)
    line(page, (0, 1.5), (8, 1.5))     # inner bottom
    for y in (2, 4, 6):                # bottom girders, 1.5 m deep
        line(page, (y, 0), (y, 1.5))
    for y in (1, 3, 5):                # bottom and inner-bottom T stiffeners, 0.3 m, flange 0.1 m
        line(page, (y, 0), (y, 0.3))
        line(page, (y - 0.05, 0.3), (y + 0.05, 0.3))
        line(page, (y, 1.5), (y, 1.2))
        line(page, (y - 0.05, 1.2), (y + 0.05, 1.2))
    for z in (3, 5, 7):                # side L stiffeners, 0.3 m, flange 0.1 m
        line(page, (8, z), (7.7, z))
        line(page, (7.7, z), (7.7, z - 0.1))
    for y in (3, 5, 7):                # deck T stiffeners, 0.2 m, flange 0.1 m
        line(page, (y, 10), (y, 9.8))
        line(page, (y - 0.05, 9.8), (y + 0.05, 9.8))
    line(page, (6, 10), (6, 9.2))      # deck girder, 0.8 m, flange 0.3 m
    line(page, (5.85, 9.2), (6.15, 9.2))
    if with_orphan:
        line(page, (4, 6), (4.5, 6))   # touches nothing
    # Sheet frame with margin labels, plate and stiffener tables, title block.
    page.draw_rect(fitz.Rect(5, 5, PAGE_W - 5, PAGE_H - 5), color=(0, 0, 0), width=0.24)
    text(page, 7, 290, "1")
    text(page, 412, 290, "2")
    rows = [("Plate", "Thickness [mm]", "Material"), ("Side Shell", "21 mm", "ASTM A131 - AB/A"),
            ("Bottom Shell", "18 mm", "ASTM A131 - AB/A"), ("Inner Bot. Deck", "15 mm", "ASTM A131 - AB/A"),
            ("Main Deck", "20 mm", "ASTM A131 - AB/A"), ("Shell Strake", "22 mm", "ASTM A131 - AB/A")]
    for i, (a, b, c) in enumerate(rows):
        z = 220 - 8 * i
        text(page, 240, z, a)
        text(page, 290, z, b)
        text(page, 340, z, c)
    stiffeners = [("Stiffener", "Num.", "Spacing [m]", "Dims: Shape - H x W x t", "Material"),
                  ("Deck Girder", "1", "0.000 m", "T-0.800 m x 0.300 m x 14 mm", "ASTM A131 - AB/A"),
                  ("Deck Stiff.", "3", "0.000 m", "T-0.200 m x 0.100 m x 9 mm", "ASTM A131 - AB/A"),
                  ("Side Shell Stiff.", "3", "2.000 m", "L-0.300 m x 0.100 m x 10 mm", "ASTM A131 - AB/A"),
                  ("Bot. Girder", "3", "2.000 m", "I-1.500 m x 0 m x 15 mm", "ASTM A131 - AB/A"),
                  ("Bot. Stiff.", "3", "2.000 m", "T-0.300 m x 0.100 m x 11 mm", "ASTM A131 - AB/A"),
                  ("Inner Bot. Stiff.", "3", "2.000 m", "T-0.300 m x 0.100 m x 12 mm", "ASTM A131 - AB/A")]
    for i, cells in enumerate(stiffeners):
        z = 160 - 8 * i
        for x, value in zip((240, 268, 283, 313, 360), cells):
            text(page, x, z, value)
    text(page, 221, 26, "Scale:")
    if with_scale:
        text(page, 230, 18, "1 m = 20 mm", size=9)


@pytest.fixture()
def section_pdf(tmp_path):
    def make(**options):
        document = fitz.open()
        page = document.new_page(width=PAGE_W, height=PAGE_H)
        draw_section(page, **options)
        path = tmp_path / f"section_{len(list(tmp_path.iterdir()))}.pdf"
        document.save(path)
        return path
    return make


def roles_by(result):
    counts = {}
    for member in result.members:
        counts[member.role] = counts.get(member.role, 0) + 1
    return counts


def test_tables_and_scale_read_exact_printed_values():
    words = [Word(230, 17, 232, 19, "1"), Word(233, 17, 235, 19, "m"), Word(236, 17, 237, 19, "="),
             Word(238, 17, 246, 19, "12.91"), Word(247, 17, 251, 19, "mm")]
    assert read_scale(words) == 12.91
    header = [("Plate", 240), ("Thickness", 290), ("[mm]", 303), ("Material", 340)]
    row = [("Main", 240), ("Deck", 247), ("25", 290), ("mm", 294), ("ASTM", 340)]
    words = [Word(x, 220, x + 5, 222, t) for t, x in header] + [Word(x, 212, x + 5, 214, t) for t, x in row]
    assert [(r.name, r.thickness_mm) for r in read_plate_table(words)] == [("Main Deck", 25.0)]
    header = [("Stiffener", 240), ("Num.", 268), ("Spacing", 283), ("Dims:", 313), ("Material", 360)]
    row = [("Bot.", 240), ("Girder", 245), ("6", 268), ("2.022", 283), ("m", 291),
           ("I-1.466", 313), ("m", 323), ("x", 326), ("0", 328), ("m", 330), ("x", 333), ("15", 335),
           ("mm", 339), ("ASTM", 360)]
    words = [Word(x, 160, x + 4, 162, t) for t, x in header] + [Word(x, 152, x + 4, 154, t) for t, x in row]
    (girder,) = read_stiffener_table(words)
    assert (girder.name, girder.count, girder.shape, girder.height_mm, girder.width_mm,
            girder.thickness_mm) == ("Bot. Girder", 6, "I", 1466.0, 0.0, 15.0)


def test_unparsed_dims_cell_gives_no_values():
    header = [("Stiffener", 240), ("Num.", 268), ("Spacing", 283), ("Dims:", 313), ("Material", 360)]
    row = [("Deck", 240), ("Stiff.", 246), ("x", 268), ("0.1", 283), ("T-0.1?", 313), ("ASTM", 360)]
    words = [Word(x, 160, x + 4, 162, t) for t, x in header] + [Word(x, 152, x + 4, 154, t) for t, x in row]
    (stiffener,) = read_stiffener_table(words)
    assert stiffener.count is None and stiffener.height_mm is None and stiffener.thickness_mm is None


def test_vector_sheet_gives_every_drawn_member_with_role_and_host(section_pdf):
    result = read_section_pdf(section_pdf(), mode="vector")
    assert result.source_kind == "vector"
    assert result.scale_mm_per_m == 20.0
    assert roles_by(result) == {"bottom_shell": 1, "side_shell": 1, "shell_strake": 1, "deck": 2,
                                "girder": 4, "stiffener_web": 12, "flange": 13}
    hosts = {}
    for member in result.members:
        if member.role in ("stiffener_web", "girder"):
            hosts[member.host] = hosts.get(member.host, 0) + 1
    assert hosts == {"Bottom": 6, "Inner_Bottom": 3, "Side_Shell": 3, "Deck": 4}
    # Table, title block and frame strokes are not members.
    assert all(m.ship_bbox_mm[2] <= 8000.5 for m in result.members)


def test_placement_and_scantlings_follow_the_drawing(section_pdf):
    result = read_section_pdf(section_pdf(), mode="vector")
    by_role = {}
    for member in result.members:
        by_role.setdefault(member.role, []).append(member)
    (inner_bottom,) = [m for m in by_role["deck"] if m.host == "Inner_Bottom"]
    assert inner_bottom.ship_bbox_mm == pytest.approx((0, 1500, 8000, 1500), abs=0.5)
    assert inner_bottom.thickness_mm == 15.0 and inner_bottom.plate_row == "Inner Bot. Deck"
    (main_deck,) = [m for m in by_role["deck"] if m.host == "Deck"]
    assert main_deck.thickness_mm == 20.0
    assert by_role["shell_strake"][0].thickness_mm == 22.0
    (deck_girder,) = [m for m in by_role["girder"] if m.host == "Deck"]
    assert deck_girder.measured_length_mm == pytest.approx(800, abs=0.5)
    assert (deck_girder.stiffener_row, deck_girder.thickness_mm) == ("Deck Girder", 14.0)
    bottom_girders = [m for m in by_role["girder"] if m.host == "Bottom"]
    assert {round(m.ship_bbox_mm[0]) for m in bottom_girders} == {2000, 4000, 6000}
    assert all(m.thickness_mm == 15.0 for m in bottom_girders)
    side_webs = [m for m in by_role["stiffener_web"] if m.host == "Side_Shell"]
    assert sorted(round(m.ship_bbox_mm[1]) for m in side_webs) == [3000, 5000, 7000]
    assert all(m.measured_length_mm == pytest.approx(300, abs=0.5) and m.thickness_mm == 10.0
               for m in side_webs)
    flanges = [m for m in by_role["flange"] if m.host == "Inner_Bottom"]
    assert all(m.measured_length_mm == pytest.approx(100, abs=0.5) and m.thickness_mm == 12.0
               for m in flanges)
    bottom_shell = by_role["bottom_shell"][0]
    assert bottom_shell.ship_bbox_mm == pytest.approx((0, 0, 8000, 1000), abs=1.0)
    assert result.origin_mm == pytest.approx(ORIGIN_MM, abs=1e-3)


def test_unexplained_stroke_is_an_abstention_not_a_member(section_pdf):
    result = read_section_pdf(section_pdf(), mode="vector")
    stroke_abstentions = [a for a in result.abstentions if a.subject.startswith("stroke:")]
    assert len(stroke_abstentions) == 1
    assert "not attached" in stroke_abstentions[0].reason
    assert stroke_abstentions[0].evidence.startswith("pdf_path:")
    clean = read_section_pdf(section_pdf(with_orphan=False), mode="vector")
    assert not [a for a in clean.abstentions if a.subject.startswith("stroke:")]


def test_missing_scale_gives_no_ship_coordinates(section_pdf):
    result = read_section_pdf(section_pdf(with_scale=False), mode="vector")
    assert result.scale_mm_per_m is None
    assert any(a.subject == "scale" for a in result.abstentions)
    assert result.members and all(m.ship_bbox_mm is None for m in result.members)
    assert all(m.measured_length_mm is None for m in result.members)


def test_output_is_deterministic_and_not_approved(section_pdf):
    path = section_pdf()
    first = read_section_pdf(path, mode="vector").as_dict()
    second = read_section_pdf(path, mode="vector").as_dict()
    assert first == second
    assert first["engineering_approved"] is False


def test_raster_fallback_finds_the_main_plates(section_pdf):
    result = read_section_pdf(section_pdf(), mode="raster", dpi=300)
    assert result.source_kind == "raster"
    counts = roles_by(result)
    assert counts.get("bottom_shell") == 1 and counts.get("side_shell") == 1
    decks = sorted(round(m.ship_bbox_mm[1], -2) for m in result.members if m.role == "deck")
    assert decks == [1500, 10000]
    webs = [m for m in result.members if m.role in ("stiffener_web", "girder")]
    assert len(webs) >= 12


def test_scoring_matches_by_box_and_counts_label_errors(section_pdf):
    result = read_section_pdf(section_pdf(with_orphan=False), mode="vector")
    truth = []
    for member in result.members:
        x0, z0, x1, z1 = member.stroke.bbox
        label = member.role
        truth.append(TruthElement(f"id{member.stroke.index}", "x", label, member.host,
                                  (x0 - 1, z0 - 1, x1 + 1, z1 + 1), member.ship_bbox_mm,
                                  member.thickness_mm or 0.0, member.measured_length_mm or 0.0))
    truth[0] = TruthElement("wrong", "x", "hopper_plate", None, truth[0].drawing_box,
                            truth[0].ship_box_mm, truth[0].thickness_mm, truth[0].l2_mm)
    pairs = match(result, truth)
    assert len(pairs) == len(truth)
    record = score_design(result, truth, SCALE, ORIGIN_MM)
    record.update(predicted_labels={}, truth_labels={})
    for member in result.members:
        record["predicted_labels"][member.role] = record["predicted_labels"].get(member.role, 0) + 1
    for element in truth:
        record["truth_labels"][element.label] = record["truth_labels"].get(element.label, 0) + 1
    summary = summarise([record])
    assert summary["detection"]["f1"] == 1.0
    assert summary["typed_micro_f1"] == pytest.approx((len(truth) - 1) / len(truth))
    assert summary["centre_error_mm"]["max"] == pytest.approx(0.0, abs=1e-6)


def test_truth_labels_and_hosts_from_bom_classes():
    assert truth_label("Hopper Pannel") == "hopper_plate"
    assert truth_label("Bottom_Longitudinal_Girder") == "girder"
    assert truth_label("Inner_Bottom_Longitudinal_Stiffener") == "stiffener_web"
    assert truth_label("Something_Else") == "other"
    assert truth_host("Inner_Bottom_Longitudinal_Stiffener") == "Inner_Bottom"
    assert truth_host("Bottom_Longitudinal_Girder") == "Bottom"
    assert truth_host("Stiffener_Flange") is None


def test_step_slice_has_one_box_per_drawn_segment(section_pdf):
    pytest.importorskip("cadquery")
    from vessel_reconstruction.structure.solid import build_slice
    result = read_section_pdf(section_pdf(with_orphan=False), mode="vector")
    compound, omitted = build_slice(result, slice_length_mm=500.0)
    segments = sum(len(m.ship_points_mm) - 1 for m in result.members)
    assert omitted == []
    assert len(compound.Solids()) == segments
    box = compound.BoundingBox()
    assert (box.xmin, box.xmax) == pytest.approx((0.0, 500.0), abs=1e-6)
    # Thickness is centred on the drawn line: the 20 mm deck reaches 10 mm above it.
    assert box.zmax == pytest.approx(10000 + 20 / 2, abs=0.01)
    # The bottom shell (18 mm) starts at the centreline and lies 9 mm below the baseline.
    assert math.isclose(box.ymin, 0.0, abs_tol=0.01)
    assert math.isclose(box.zmin, -18 / 2, abs_tol=0.01)
