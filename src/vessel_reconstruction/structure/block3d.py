"""A 3D cargo-hold block from the three MiDShip midship drawings (whole-vessel step 2).

The frozen W3 reader gives the longitudinal members of view 3 in the section plane (y, z).
This module sweeps them along the block, and places the transverse members (bulkheads, web
frames, floors, deck beams, brackets, ordinary frames and bulkhead stiffeners) at their
spacing. Section geometry and scantlings come from the drawings; the values the drawings do
not give are labelled guesses (docs/plans/2026-11-09-whole-vessel-scope.md, section 4.3.1).

Every member is an axis-aligned box in ship metres (x along the block, y from the centreline
to the side, z up from the baseline) that holds the member's mid-plane; its thickness is a
separate value. Every output has ``engineering_approved=false``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import math
import statistics
from pathlib import Path
import re

from . import read_section_pdf
from ..cad_exports import export_iges
from ..rhino_exports import CadPart, export_3dm
from .model import SectionResult
from .tables import PLATE_HEADER, STIFFENER_HEADER, _table_rows, text_lines
from .vector import read_pdf_words

VIEWS = {"bulkhead": "Transverse Bulkhead", "web_frame": "Midship Section IWO of Web Frame",
         "longitudinal": "Midship Section of Long. Structure"}

# Guesses for values the drawings do not print. They are the generator conventions found in a
# BOM survey of the 488 SGLD designs outside the W3 sealed split (plan section 4.3.1).
GUESS_BLOCK_LENGTH_M = 40.0  # 239 of 488 designs; the others 40.0 to 43.7 m
GUESS_HOLDS = 3  # 4 transverse bulkheads in all 488 designs
GUESS_WEB_SPACES_PER_HOLD = 9  # all 488 designs
GUESS_FRAME_SPACES_PER_WEB = 5  # 269 designs; 4 in 204, 3 in 15
# Bracket legs as a share of the printed web-frame depth (drawn in view 2, not printed;
# seen on development design 379: lower 1.18 m and upper 0.98 m for a 1.96 m web).
GUESS_LOWER_BRACKET_LEG = 0.6
GUESS_UPPER_BRACKET_LEG = 0.5

THICKNESS_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*mm$")
SPACING_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*m$")
DIMS_PATTERN = re.compile(
    r"^([TLI])-\s*(\d+(?:\.\d+)?)\s*m\s*x\s*(\d+(?:\.\d+)?)\s*m\s*x\s*(\d+(?:\.\d+)?)\s*mm$")

# Plate hosts of view 3 that carry ordinary transverse frames when they carry longitudinal
# stiffeners, with the stiffener-table row whose scantling the frame takes (a guess).
FRAME_HOSTS = {"Bottom": "Bot. Stiff.", "Inner_Bottom": "Inner Bot. Stiff.", "Deck": "Deck Stiff.",
               "Side_Shell": "Side Shell Stiff.", "Inner_Side_Shell": "Inner Side Shell Stiff.",
               "Longitudinal_Bulkhead": "Long. BLKHD Stiff."}

Box = tuple[float, float, float, float, float, float]  # x0, y0, z0, x1, y1, z1 (metres)


@dataclass(frozen=True)
class PrintedRow:
    """One stiffener-table row with its spacing column (the W3 table reader drops spacing)."""
    name: str
    count: int | None
    spacing_m: float | None
    shape: str | None
    height_m: float | None
    width_m: float | None
    thickness_mm: float | None
    material: str | None = None


@dataclass
class BlockMember:
    member_id: str  # stable ID: zone / frame / member
    label: str  # scoring label (plan section 4.3.1)
    group: str  # "longitudinal" or "transverse"
    box: Box
    area_m2: float
    thickness_mm: float | None
    thickness_source: str  # "printed" or "guessed"
    sources: dict[str, str] = field(default_factory=dict)  # argument -> traced | guessed
    basis: str = ""
    table_row: str | None = None  # printed table row that gives the scantling (or the guessed one)
    material: str | None = None
    material_source: str = "none"  # "printed" or "guessed" once labelled

    def as_dict(self) -> dict:
        record = asdict(self)
        record["box"] = [round(v, 4) for v in self.box]
        record["area_m2"] = round(self.area_m2, 4)
        return record


@dataclass
class BlockReading:
    """Everything read from the three sheets before the block is laid out."""
    section: SectionResult
    plate_mm: dict[str, float]
    rows: dict[str, PrintedRow]
    materials: dict[str, str]  # table row name -> printed material (plate and stiffener tables)
    breadth_m: float
    depth_m: float
    side_bottom_m: float
    inner_bottom_m: float | None


def read_rows(words) -> dict[str, PrintedRow]:
    rows = {}
    for name, count, spacing, dims, material, *_ in _table_rows(text_lines(words), STIFFENER_HEADER):
        spacing_match = SPACING_PATTERN.match(spacing.strip())
        dims_match = DIMS_PATTERN.match(dims.strip())
        shape = height = width = thickness = None
        if dims_match:
            shape = dims_match.group(1)
            height, width, thickness = (float(dims_match.group(i)) for i in (2, 3, 4))
        rows[name.strip()] = PrintedRow(
            name.strip(), int(count) if count.strip().isdigit() else None,
            float(spacing_match.group(1)) if spacing_match else None, shape, height, width, thickness,
            material.strip() or None)
    return rows


def read_plate_rows(words) -> dict[str, tuple[float | None, str | None]]:
    """Plate table rows: name -> (thickness in mm or None, material or None)."""
    rows = {}
    for name, thickness, material, *_ in _table_rows(text_lines(words), PLATE_HEADER):
        match = THICKNESS_PATTERN.match(thickness.strip())
        rows[name.strip()] = (float(match.group(1)) if match else None, material.strip() or None)
    return rows


def read_sheets(sheets: dict[str, Path]) -> BlockReading:
    """Read view 3 with the frozen W3 reader and the printed tables of all three views."""
    section = read_section_pdf(sheets["longitudinal"], mode="vector")
    plate_mm: dict[str, float] = {}
    rows: dict[str, PrintedRow] = {}
    materials: dict[str, str] = {}
    for key in ("longitudinal", "web_frame", "bulkhead"):
        words = read_pdf_words(sheets[key])
        for name, (thickness, material) in read_plate_rows(words).items():
            if thickness is not None:
                plate_mm.setdefault(name, thickness)
            if material:
                materials.setdefault(name, material)
        for name, row in read_rows(words).items():
            rows.setdefault(name, row)
            if row.material:
                materials.setdefault(name, row.material)
    plates = [m for m in section.members if m.role in ("bottom_shell", "side_shell", "shell_strake", "deck",
                                                       "longitudinal_bulkhead", "hopper_plate")]
    if not plates:
        raise ValueError("view 3 gives no plate: no block can be laid out")
    breadth = max(m.ship_bbox_mm[2] for m in plates) / 1000
    depth = max(m.ship_bbox_mm[3] for m in plates) / 1000
    side = [m for m in section.members if m.role == "side_shell"]
    side_bottom = min(m.ship_bbox_mm[1] for m in side) / 1000 if side else 0.0
    inner = [m for m in section.members if m.role == "deck" and m.host == "Inner_Bottom"]
    inner_bottom = inner[0].ship_bbox_mm[1] / 1000 if inner else None
    return BlockReading(section, plate_mm, rows, materials, breadth, depth, side_bottom, inner_bottom)


def _polyline_length_m(points_mm) -> float:
    return sum(math.dist(a, b) for a, b in zip(points_mm, points_mm[1:])) / 1000


def longitudinal_members(reading: BlockReading, length_m: float) -> list[BlockMember]:
    """View 3 members swept along the whole block (their x extent is the block length)."""
    members = []
    for number, member in enumerate(reading.section.members):
        if member.ship_bbox_mm is None:
            continue
        y0, z0, y1, z1 = (v / 1000 for v in member.ship_bbox_mm)
        label = member.role
        section_length = _polyline_length_m(member.ship_points_mm) or max(y1 - y0, z1 - z0)
        members.append(BlockMember(
            member_id=f"L/{member.host or 'section'}/{label}/{number:03d}", label=label, group="longitudinal",
            box=(0.0, y0, z0, length_m, y1, z1), area_m2=section_length * length_m,
            thickness_mm=member.thickness_mm,
            thickness_source="printed" if member.thickness_mm is not None else "none",
            sources={"section": "traced", "length": "guessed"},
            basis=f"view 3 stroke {member.stroke.index}, swept over the guessed block length",
            table_row=member.plate_row or member.stiffener_row))
    return members


@dataclass(frozen=True)
class Stations:
    bulkheads: list[float]
    webs: list[float]
    frames: list[float]
    web_spacing_m: float
    frame_spacing_m: float


def stations(web_spacing_m: float, length_m: float = GUESS_BLOCK_LENGTH_M,
             holds: int = GUESS_HOLDS, webs_per_hold: int = GUESS_WEB_SPACES_PER_HOLD,
             frames_per_web: int = GUESS_FRAME_SPACES_PER_WEB) -> Stations:
    """Bulkhead, web-frame and ordinary-frame x positions, holds centred in the block."""
    hold_length = webs_per_hold * web_spacing_m
    start = (length_m - holds * hold_length) / 2
    bulkheads = [start + k * hold_length for k in range(holds + 1)]
    webs, frames = [], []
    frame_spacing = web_spacing_m / frames_per_web
    for hold in range(holds):
        for web in range(webs_per_hold):
            base = bulkheads[hold] + web * web_spacing_m
            if web > 0:
                webs.append(base)
            frames.extend(base + k * frame_spacing for k in range(1, frames_per_web))
    return Stations(bulkheads, webs, frames, web_spacing_m, frame_spacing)


def _plane_x(x: float, y0: float, z0: float, y1: float, z1: float) -> Box:
    return (x, y0, z0, x, y1, z1)


def transverse_members(reading: BlockReading, st: Stations) -> list[BlockMember]:
    rows, plate_mm = reading.rows, reading.plate_mm
    breadth, depth, inner = reading.breadth_m, reading.depth_m, reading.inner_bottom_m
    members: list[BlockMember] = []
    x_sources = {"x": "traced", "block_length": "guessed"}

    def add(member_id, label, box, area, thickness, thickness_source, extra_sources, basis, row=None):
        members.append(BlockMember(member_id, label, "transverse", box, area, thickness, thickness_source,
                                   {**x_sources, **extra_sources}, basis, table_row=row))

    def frame_no(x: float) -> int:
        return round((x - st.bulkheads[0]) / st.frame_spacing_m)

    # Transverse bulkheads and their stiffeners (view 1 tables).
    vertical = rows.get("Vert. BLKHD Stiff.")
    horizontal = rows.get("Trans. BLKHD Stiff.")
    for number, x in enumerate(st.bulkheads):
        zone = f"BH{number + 1}"
        add(f"{zone}/plate", "transverse_bulkhead", _plane_x(x, 0.0, 0.0, breadth, depth), breadth * depth,
            plate_mm.get("Trans. BLKHD"), "printed" if "Trans. BLKHD" in plate_mm else "none",
            {"extent": "traced"}, "plate row 'Trans. BLKHD'; extent from the view 3 section", row="Trans. BLKHD")
        if vertical and vertical.count and vertical.spacing_m and vertical.height_m:
            for k in range(vertical.count):
                y = k * vertical.spacing_m
                add(f"{zone}/vstiff/{k:02d}", "bulkhead_stiffener", (x, y, 0.0, x + vertical.height_m, y, depth),
                    vertical.height_m * depth, vertical.thickness_mm, "printed", {"side": "guessed"},
                    "row 'Vert. BLKHD Stiff.' count and spacing; web on the +x side (guess)", row=vertical.name)
                if vertical.shape in ("T", "L") and vertical.width_m:
                    xf = x + vertical.height_m
                    y_lo, y_hi = (y - vertical.width_m / 2, y + vertical.width_m / 2) if vertical.shape == "T" \
                        else (y, y + vertical.width_m)
                    add(f"{zone}/vstiff/{k:02d}/flange", "flange", (xf, max(0.0, y_lo), 0.0, xf, y_hi, depth),
                        vertical.width_m * depth, vertical.thickness_mm, "printed", {"side": "guessed"},
                        "flange of the row 'Vert. BLKHD Stiff.'", row=vertical.name)
        if horizontal and horizontal.count and horizontal.spacing_m and horizontal.height_m:
            for k in range(1, horizontal.count + 1):
                z = k * horizontal.spacing_m
                if z >= depth:
                    break
                add(f"{zone}/hstiff/{k:02d}", "bulkhead_stiffener", (x, 0.0, z, x + horizontal.height_m, breadth, z),
                    horizontal.height_m * breadth, horizontal.thickness_mm, "printed", {"side": "guessed"},
                    "row 'Trans. BLKHD Stiff.' count and spacing; web on the +x side (guess)", row=horizontal.name)
                if horizontal.shape in ("T", "L") and horizontal.width_m:
                    xf = x + horizontal.height_m
                    z_lo, z_hi = (z - horizontal.width_m / 2, z + horizontal.width_m / 2) \
                        if horizontal.shape == "T" else (z - horizontal.width_m, z)
                    add(f"{zone}/hstiff/{k:02d}/flange", "flange", (xf, 0.0, z_lo, xf, breadth, z_hi),
                        horizontal.width_m * breadth, horizontal.thickness_mm, "printed", {"side": "guessed"},
                        "flange of the row 'Trans. BLKHD Stiff.'", row=horizontal.name)

    # Web-frame stations (view 2 tables).
    web = rows.get("Webframe")
    floor = rows.get("Floor")
    beam = rows.get("Deck_Transvere_Beam")
    for x in st.webs:
        zone = f"FR{frame_no(x):03d}"
        if floor and inner:
            add(f"{zone}/floor", "floor", _plane_x(x, 0.0, 0.0, breadth, inner), breadth * inner,
                floor.thickness_mm, "printed", {"extent": "traced"}, "row 'Floor'; inner bottom from view 3", row=floor.name)
        if web and web.height_m:
            z0 = reading.side_bottom_m
            add(f"{zone}/web", "web_frame", _plane_x(x, breadth - web.height_m, z0, breadth, depth),
                web.height_m * (depth - z0), web.thickness_mm, "printed", {"extent": "traced"},
                "row 'Webframe' depth on the side shell span of view 3", row=web.name)
            if web.shape in ("T", "L") and web.width_m:
                x_lo, x_hi = (x - web.width_m / 2, x + web.width_m / 2) if web.shape == "T" else (x, x + web.width_m)
                yf = breadth - web.height_m
                add(f"{zone}/web/flange", "flange", (x_lo, yf, z0, x_hi, yf, depth), web.width_m * (depth - z0),
                    web.thickness_mm, "printed", {}, "flange of the row 'Webframe'", row=web.name)
            leg_low = GUESS_LOWER_BRACKET_LEG * web.height_m
            leg_up = GUESS_UPPER_BRACKET_LEG * web.height_m
            y_in = breadth - web.height_m
            if "Lower Bracket" in plate_mm and inner:
                add(f"{zone}/bracket_low", "bracket", _plane_x(x, y_in - leg_low, inner, y_in, inner + leg_low),
                    leg_low ** 2 / 2, plate_mm["Lower Bracket"], "printed", {"size": "guessed"},
                    "plate row 'Lower Bracket'; legs guessed from the web depth", row="Lower Bracket")
            if "Upper Bracket" in plate_mm:
                top = depth - (beam.height_m if beam and beam.height_m else 0.0)
                add(f"{zone}/bracket_up", "bracket", _plane_x(x, y_in - leg_up, top - leg_up, y_in, top),
                    leg_up ** 2 / 2, plate_mm["Upper Bracket"], "printed", {"size": "guessed"},
                    "plate row 'Upper Bracket'; legs guessed from the web depth", row="Upper Bracket")
        if beam and beam.height_m:
            z_low = depth - beam.height_m
            add(f"{zone}/deck_beam", "deck_beam", _plane_x(x, 0.0, z_low, breadth, depth), beam.height_m * breadth,
                beam.thickness_mm, "printed", {"extent": "traced"}, "row 'Deck_Transvere_Beam'", row=beam.name)
            if beam.shape in ("T", "L") and beam.width_m:
                x_lo, x_hi = (x - beam.width_m / 2, x + beam.width_m / 2) if beam.shape == "T" else (x, x + beam.width_m)
                add(f"{zone}/deck_beam/flange", "flange", (x_lo, 0.0, z_low, x_hi, breadth, z_low),
                    beam.width_m * breadth, beam.thickness_mm, "printed", {}, "flange of the row 'Deck_Transvere_Beam'", row=beam.name)

    # Ordinary frames: one per stiffened plate host, scantling of that host's longitudinal row.
    hosts = _stiffened_plate_spans(reading)
    for x in st.frames:
        zone = f"FR{frame_no(x):03d}"
        for host, (span, orientation) in hosts.items():
            row = rows.get(FRAME_HOSTS[host])
            if not row or not row.height_m:
                continue
            h = row.height_m
            (a0, a1), level = span
            flange_box = None
            flanged = row.shape in ("T", "L") and bool(row.width_m)
            if host == "Bottom" and inner:
                # In a double bottom the ordinary bottom frame is an open floor: bottom frame,
                # struts and inner-bottom frame between two plate floors, from the bottom shell
                # to the inner bottom (guess; no flange).
                box = _plane_x(x, a0, 0.0, a1, inner)
            elif orientation == "horizontal":  # web hangs below a deck or stands on the bottom
                z_lo, z_hi = (level, level + h) if host == "Bottom" else (level - h, level)
                box = _plane_x(x, a0, z_lo, a1, z_hi)
                if flanged:
                    zf = z_hi if host == "Bottom" else z_lo
                    flange_box = (x - row.width_m / 2, a0, zf, x + row.width_m / 2, a1, zf)
            else:
                # Side shell: the web stands inboard. Inner side shell and longitudinal bulkhead:
                # the web stands outboard, in the double side space (guess).
                outboard = host != "Side_Shell"
                y_web, y_free = (level, level + h) if outboard else (level - h, level)
                box = _plane_x(x, min(y_web, y_free), a0, max(y_web, y_free), a1)
                if flanged:
                    yf = y_free if outboard else y_web
                    flange_box = (x - row.width_m / 2, yf, a0, x + row.width_m / 2, yf, a1)
            add(f"{zone}/frame/{host}", "frame", box, h * (a1 - a0), row.thickness_mm, "guessed",
                {"frame_spacing": "guessed", "scantling": "guessed"},
                f"ordinary frame on {host}; scantling of the row '{row.name}' (guess)", row=row.name)
            if flange_box:
                add(f"{zone}/frame/{host}/flange", "flange", flange_box, row.width_m * (a1 - a0),
                    row.thickness_mm, "guessed", {"frame_spacing": "guessed", "scantling": "guessed"},
                    f"flange of the ordinary frame on {host} (guess)", row=row.name)
    return members


def _stiffened_plate_spans(reading: BlockReading) -> dict[str, tuple[tuple[tuple[float, float], float], str]]:
    """For each host with stiffener webs in view 3: ((span start, span end), level) and orientation."""
    stiffened = {m.host for m in reading.section.members if m.role == "stiffener_web"}
    spans = {}
    for member in reading.section.members:
        if member.role not in ("bottom_shell", "deck", "side_shell", "longitudinal_bulkhead"):
            continue
        host = "Inner_Side_Shell" if member.host == "Inner_Side_Shell" else member.host
        if host not in stiffened or host not in FRAME_HOSTS or host in spans:
            continue
        y0, z0, y1, z1 = (v / 1000 for v in member.ship_bbox_mm)
        if member.role == "bottom_shell":
            spans[host] = (((0.0, reading.breadth_m), 0.0), "horizontal")
        elif member.role == "deck":
            spans[host] = (((y0, y1), z1), "horizontal")
        else:
            spans[host] = (((z0, z1), y1), "vertical")
    return spans


def label_thickness_and_material(members: list[BlockMember], materials: dict[str, str]) -> None:
    """Give every member a thickness and a material, each with a source label.

    A member without a printed thickness takes the median printed thickness of its label in this
    design (else of all printed members), labelled ``guessed``. The material is printed when the
    member's table row prints one and the member's scantling is printed; otherwise it is the most
    common printed material of the design, labelled ``guessed``.
    """
    printed = [m for m in members if m.thickness_mm is not None and m.thickness_source == "printed"]
    by_label: dict[str, list[float]] = {}
    for m in printed:
        by_label.setdefault(m.label, []).append(m.thickness_mm)
    overall = statistics.median(m.thickness_mm for m in printed) if printed else None
    common = Counter(materials.values()).most_common(1)
    common_material = common[0][0] if common else None
    for m in members:
        if m.thickness_mm is None:
            values = by_label.get(m.label)
            m.thickness_mm = statistics.median(values) if values else overall
            m.thickness_source = "guessed"
            m.basis += "; thickness guessed: median printed thickness of the label in this design"
        own = materials.get(m.table_row) if m.table_row else None
        if own and m.thickness_source == "printed":
            m.material, m.material_source = own, "printed"
        else:
            m.material, m.material_source = own or common_material, "guessed"


def build_block(sheets: dict[str, Path], length_m: float = GUESS_BLOCK_LENGTH_M,
                frames_per_web: int = GUESS_FRAME_SPACES_PER_WEB) -> dict:
    """Read the three sheets and lay out the block. Returns the member list and the reading.

    ``length_m`` and ``frames_per_web`` are the guesses of values the drawings do not print; a
    caller passes other values only for a diagnostic of what the guesses cost.
    """
    reading = read_sheets(sheets)
    web = reading.rows.get("Webframe") or reading.rows.get("Floor")
    if not web or not web.spacing_m:
        raise ValueError("no printed web-frame spacing (rows 'Webframe' and 'Floor')")
    st = stations(web.spacing_m, length_m=length_m, frames_per_web=frames_per_web)
    members = longitudinal_members(reading, length_m) + transverse_members(reading, st)
    label_thickness_and_material(members, reading.materials)
    return {
        "schema": "marinaframe.structure_block.v1",
        "engineering_approved": False,
        "status": "draft_only",
        "breadth_m": reading.breadth_m, "depth_m": reading.depth_m, "inner_bottom_m": reading.inner_bottom_m,
        "guesses": {"block_length_m": length_m, "holds": GUESS_HOLDS,
                    "web_spaces_per_hold": GUESS_WEB_SPACES_PER_HOLD,
                    "frame_spaces_per_web": frames_per_web,
                    "bracket_legs": [GUESS_LOWER_BRACKET_LEG, GUESS_UPPER_BRACKET_LEG]},
        "printed": {"web_spacing_m": web.spacing_m, "plates_mm": reading.plate_mm, "materials": reading.materials,
                    "rows": {name: asdict(row) for name, row in reading.rows.items()}},
        "stations": asdict(st),
        "members": [m.as_dict() for m in members],
    }


def export_step(block: dict, path: Path) -> int:
    """Write thin member boxes to STEP and draft IGES/3dm files, all in millimetres."""
    import cadquery as cq

    parts = []
    for index, member in enumerate(block["members"]):
        t = (member["thickness_mm"] or 10.0) / 1000
        x0, y0, z0, x1, y1, z1 = member["box"]
        dims = [x1 - x0, y1 - y0, z1 - z0]
        thin = min(range(3), key=lambda i: dims[i])
        lo, hi = [x0, y0, z0], [x1, y1, z1]
        lo[thin] -= t / 2
        hi[thin] += t / 2
        size = [max(hi[i] - lo[i], 1e-4) * 1000 for i in range(3)]
        shape = cq.Solid.makeBox(*size, cq.Vector(*(v * 1000 for v in lo)))
        parts.append(CadPart(member.get("member_id", f"member-{index}"), shape, "Structure"))
    compound = cq.Compound.makeCompound([part.shape for part in parts])
    cq.exporters.export(cq.Workplane().add(compound), str(path), exportType="STEP")
    export_iges(compound, path.with_suffix(".iges"))
    export_3dm(parts, path.with_suffix(".3dm"))
    return len(parts)
