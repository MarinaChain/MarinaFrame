"""OCX 3.0.1 export and plate reader for structure blocks (docs/STRUCTURE_V2.md section 6.1).

Export: one ``ocx:Plate`` per plate member, directly under ``ocx:Vessel`` (the schema allows plates
outside a panel; a block zone holds members in several planes, so it is not one OCX panel). Each
plate has a closed ``PolyLine3D`` outer contour (the member's ``contour`` when it has one, else the
mid-plane rectangle of its box), its thickness and material (``PlateMaterial``), net area and dry
weight. A member with a ``trace`` and a ``profile`` is written as an ``ocx:Stiffener`` (trace line,
material, section from the ``XSectionCatalogue``, web direction); the MiDShip block members have
no trace, so their stiffener webs and flanges stay plates. The member ID is the ``name``; the source
labels go in ``Description``.

Tanks (``tanks`` input, docs/TANKS_V1.md section 7): one ``ocx:Compartment`` per built tank in an
``ocx:Arrangement`` before the plates. A file may hold tanks only (``block`` is None).

Reader: streams ``Plate``, ``Stiffener`` and ``Compartment`` elements (name, thickness, area;
section and length; purpose, volume, centre), so a large model such as the 22 MB D-VLCC sample
reads in flat memory.

Schema check: ``validate`` runs ``xmllint`` against the local OCX 3.0.1 XSD. The XSD imports UnitsML
and the W3C ``xml.xsd`` by URL; the check copies the schema to a temporary folder and points both
imports at local files, so it needs no network.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ElementTree
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from .. import tanks as tank_model
from .steel import STEEL_DENSITY_T_M3
from .tank_faces import patch_corners, planar_faces

OCX_NAMESPACE = "https://3docx.org/fileadmin//ocx_schema//V301//OCX_Schema.xsd"
UNITSML_NAMESPACE = "urn:oasis:names:tc:unitsml:schema:xsd:UnitsMLSchema_lite-0.9.18"
SCHEMA_VERSION = "3.0.1"
# Coordinates are written in metres with 6 decimals (1 micrometre).
COORDINATE_DIGITS = 6
# Minimum yield and tensile strength (N/mm2) of hull steel grades (IACS UR W11), keyed by the OCX
# grade names (the schema enumeration). A printed higher-strength name "AH36" or "DH32" maps to the
# OCX name "A36" or "D32". A printed grade outside this table is written as grade A.
NORMAL_STRENGTH = (235, 400)
STRENGTH_BY_LEVEL = {"32": (315, 440), "36": (355, 490), "40": (390, 510)}
GRADE_STRENGTH = {**{grade: NORMAL_STRENGTH for grade in ("A", "B", "C", "D")},
                  **{f"{letter}{level}": strength for letter in "ADEF" for level, strength in STRENGTH_BY_LEVEL.items()}}
YOUNGS_MODULUS_N_MM2 = 206000
POISSON_RATIO = 0.3
# Units the export uses: xml:id -> (symbol, root unit, power, prefix). The OCX unit attributes are
# IDREFs to these UnitsML entries.
UNITS = {"Um": ("m", "meter", 1, None), "Um2": ("m2", "meter", 2, None), "Um3": ("m3", "meter", 3, None),
         "Umm": ("mm", "meter", 1, "m"),
         "UKg": ("kg", "gram", 1, "k"), "URad": ("rad", "radian", 1, None),
         "UKgOverm3": ("kg/m3", None, None, None), "UNOvermm2": ("N/mm2", None, None, None),
         "UDimless": ("", None, None, None)}
# The schema requires a class society; the block's scantlings follow the ABS rule subset of the
# MiDShip generator (docs/RULES_V1.md). It is not a class assignment.
CLASS_SOCIETY = "ABS"
GUID_NAMESPACE = uuid.UUID("6f1c1d0e-6a53-4c8e-9a64-6d1a0c2f3b10")  # fixed: stable GUIDs per ID
# Tank content class (tanks.CONTENT_CLASSES) -> OCX compartmentPurpose (schema enumeration).
COMPARTMENT_PURPOSE = {"fuel_oil": "Fuel", "diesel_oil": "Fuel", "lube_oil": "Lube", "water_ballast": "Ballast",
                       "fresh_water": "Freshwater", "feed_water": "Freshwater", "cargo": "Cargo", "void": "Void",
                       "oily_residue": "Other", "sewage": "Other", "other": "Other"}
# Tank content class -> OCX liquidCargoType (schema enumeration); other classes are "unspecified".
LIQUID_CARGO_TYPE = {"fuel_oil": "fuel oil", "diesel_oil": "fuel oil", "lube_oil": "lubricating oil",
                     "water_ballast": "water ballast", "fresh_water": "fresh water", "feed_water": "fresh water",
                     "oily_residue": "sludge", "sewage": "sullage"}
KG_PER_TONNE = 1000


def _guid(key: str) -> str:
    return str(uuid.uuid5(GUID_NAMESPACE, key))


def _xml_id(prefix: str, number: int) -> str:
    return f"{prefix}{number}"


def grade_of(material: str | None) -> str:
    """Steel grade from a printed material ('ASTM A131 - AB/A' -> 'A'); 'A' when none is printed."""
    if not material:
        return "A"
    tail = re.split(r"[/\s-]+", material.strip())[-1].upper()
    higher_strength = re.fullmatch(r"([ADEF])H(\d\d)", tail)  # a class-society name: "AH36" -> "A36"
    if higher_strength:
        tail = higher_strength.group(1) + higher_strength.group(2)
    elif re.fullmatch(r"[ADEF]\d\d", tail):
        return "A"  # "ASTM A36" is a 250 MPa structural steel, not the 355 MPa class grade AH36
    return tail if tail in GRADE_STRENGTH else "A"


def plate_corners(box) -> list[tuple[float, float, float]]:
    """The mid-plane rectangle of an axis-aligned member box, as 4 corners in order.

    The thin axis of the box is the plate normal. A box thin in two axes (a line) gives a
    degenerate rectangle; the caller writes it as is (zero area, as in the block model).
    """
    x0, y0, z0, x1, y1, z1 = box
    spans = [x1 - x0, y1 - y0, z1 - z0]
    normal = min(range(3), key=lambda i: spans[i])
    lo, hi = [x0, y0, z0], [x1, y1, z1]
    u, v = [i for i in range(3) if i != normal]
    corners = []
    for a, b in ((lo[u], lo[v]), (hi[u], lo[v]), (hi[u], hi[v]), (lo[u], hi[v])):
        point = list(lo)
        point[normal] = (lo[normal] + hi[normal]) / 2
        point[u], point[v] = a, b
        corners.append(tuple(point))
    return corners


def polygon_area(points) -> float:
    """Area of a planar polygon in 3D (Newell's method)."""
    nx = ny = nz = 0.0
    for (x0, y0, z0), (x1, y1, z1) in zip(points, points[1:] + points[:1]):
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return math.sqrt(nx * nx + ny * ny + nz * nz) / 2


def _coords(point) -> str:
    return " ".join(f"{v:.{COORDINATE_DIGITS}f}" for v in point)


def _units_xml() -> str:
    lines = [f'  <unitsml:UnitsML xmlns:unitsml="{UNITSML_NAMESPACE}">', "    <unitsml:UnitSet>"]
    for unit_id, (symbol, root, power, prefix) in UNITS.items():
        lines.append(f'      <unitsml:Unit xml:id="{unit_id}">')
        lines.append(f'        <unitsml:UnitName xml:lang="en-us">{escape(symbol or "dimensionless")}</unitsml:UnitName>')
        lines.append(f'        <unitsml:UnitSymbol type={quoteattr(symbol)}/>')
        if root:
            prefix_attr = f' prefix="{prefix}"' if prefix else ""
            lines.append("        <unitsml:RootUnits>")
            lines.append(f'          <unitsml:EnumeratedRootUnit unit="{root}" powerNumerator="{power}"{prefix_attr}/>')
            lines.append("        </unitsml:RootUnits>")
        lines.append("      </unitsml:Unit>")
    lines += ["    </unitsml:UnitSet>", "  </unitsml:UnitsML>"]
    return "\n".join(lines)


def _material_xml(material_ids: dict[str, str], sections: str = "") -> str:
    lines = ['  <ocx:ClassCatalogue id="catalogue">', '    <ocx:MaterialCatalogue id="materials">']
    for grade, xml_id in material_ids.items():
        yield_stress, tensile = GRADE_STRENGTH[grade]
        lines += [
            f'      <ocx:Material id="{xml_id}" name="{grade}" ocx:grade="{grade}" ocx:GUIDRef="{_guid("material/" + grade)}">',
            "        <ocx:Description>Grade from the printed material; density and strengths are "
            "standard values for the grade (guessed).</ocx:Description>",
            f'        <ocx:Density numericvalue="{STEEL_DENSITY_T_M3 * 1000:.0f}" unit="UKgOverm3"/>',
            f'        <ocx:YoungsModulus numericvalue="{YOUNGS_MODULUS_N_MM2}" unit="UNOvermm2"/>',
            f'        <ocx:PoissonRatio numericvalue="{POISSON_RATIO}" unit="UDimless"/>',
            f'        <ocx:YieldStress numericvalue="{yield_stress}" unit="UNOvermm2"/>',
            f'        <ocx:UltimateStress numericvalue="{tensile}" unit="UNOvermm2"/>',
            "      </ocx:Material>"]
    lines.append("    </ocx:MaterialCatalogue>")
    if sections:
        lines += ['    <ocx:XSectionCatalogue id="sections" name="sections">', sections, "    </ocx:XSectionCatalogue>"]
    lines.append("  </ocx:ClassCatalogue>")
    return "\n".join(lines)


def _description(member: dict) -> str:
    sources = " ".join(f"{k}={v}" for k, v in sorted((member.get("sources") or {}).items()))
    return (f"label={member['label']}; group={member['group']}; thickness={member['thickness_source']}; "
            f"material={member.get('material_source', 'guessed')}; placement: {sources}; "
            "engineering_approved=false")


def _volume_m3(member: dict) -> float:
    if member.get("volume_m3") is not None:
        return member["volume_m3"]
    return member["area_m2"] * (member["thickness_mm"] or 0.0) / 1000


def _centre(member: dict, points) -> list[float]:
    """Centre of gravity estimate: mean of the outline or trace points, else the box centre."""
    if points:
        return [sum(p[i] for p in points) / len(points) for i in range(3)]
    return [(member["box"][i] + member["box"][i + 3]) / 2 for i in range(3)]


def _plate_xml(number: int, member: dict, material_id: str, grade: str) -> str:
    corners = [tuple(p) for p in member["contour"]] if member.get("contour") else plate_corners(member["box"])
    closed = corners + [corners[0]]
    perimeter = sum(math.dist(a, b) for a, b in zip(closed, closed[1:]))
    thickness_m = (member["thickness_mm"] or 0.0) / 1000
    area = member["area_m2"]
    weight_kg = _volume_m3(member) * STEEL_DENSITY_T_M3 * 1000
    centre = _centre(member, member.get("contour"))
    key = member["member_id"]
    points = "\n".join(f'              <ocx:Point3D coordinates="{_coords(p)}" unit="Um"/>' for p in closed)
    return f"""    <ocx:Plate id="{_xml_id('plate', number)}" name={quoteattr(key)} ocx:GUIDRef="{_guid('plate/' + key)}">
      <ocx:Description>{escape(_description(member))}</ocx:Description>
      <ocx:PhysicalProperties>
        <ocx:DryWeight numericvalue="{weight_kg:.3f}" unit="UKg"/>
        <ocx:CenterOfGravity coordinates="{_coords(centre)}" unit="Um"/>
      </ocx:PhysicalProperties>
      <ocx:NetArea numericvalue="{area:.{COORDINATE_DIGITS}f}" unit="Um2"/>
      <ocx:OuterContour>
        <ocx:CompositeCurve3D id="{_xml_id('contour', number)}" ocx:GUIDRef="{_guid('contour/' + key)}">
          <ocx:CurveLength numericvalue="{perimeter:.{COORDINATE_DIGITS}f}" unit="Um"/>
          <ocx:PolyLine3D id="{_xml_id('polyline', number)}" ocx:GUIDRef="{_guid('polyline/' + key)}">
            <ocx:CurveLength numericvalue="{perimeter:.{COORDINATE_DIGITS}f}" unit="Um"/>
{points}
          </ocx:PolyLine3D>
        </ocx:CompositeCurve3D>
      </ocx:OuterContour>
      <ocx:PlateMaterial localRef="{material_id}" ocx:GUIDRef="{_guid('material/' + grade)}" ocx:refType="ocx:Material">
        <ocx:Thickness numericvalue="{thickness_m:.{COORDINATE_DIGITS}f}" unit="Um"/>
      </ocx:PlateMaterial>
    </ocx:Plate>"""


def section_name(profile: dict) -> str:
    return profile["name"]


def _section_xml(profile: dict, xml_id: str) -> str:
    """One ``BarSection`` of the section catalogue (dimensions in metres)."""
    def quantity(tag, mm):
        return f'          <ocx:{tag} numericvalue="{mm / 1000:.6f}" unit="Um"/>'
    kind = profile["kind"]
    if kind == "FlatBar":
        body = [quantity("Height", profile["height_mm"]), quantity("Width", profile["web_mm"])]
    elif kind == "BulbFlat":
        body = [quantity("Height", profile["height_mm"]), quantity("WebThickness", profile["web_mm"])]
    else:  # TBar
        body = [quantity("Height", profile["height_mm"]), quantity("Width", profile["flange_width_mm"]),
                quantity("WebThickness", profile["web_mm"]), quantity("FlangeThickness", profile["flange_thickness_mm"])]
    name = section_name(profile)
    return "\n".join([f'      <ocx:BarSection id="{xml_id}" name={quoteattr(name)} ocx:GUIDRef="{_guid("section/" + name)}">',
                      f"        <ocx:{kind}>", *body, f"        </ocx:{kind}>", "      </ocx:BarSection>"])


def _stiffener_xml(number: int, member: dict, material_id: str, grade: str, section_id: str) -> str:
    trace = [tuple(p) for p in member["trace"]]
    length = sum(math.dist(a, b) for a, b in zip(trace, trace[1:]))
    weight_kg = _volume_m3(member) * STEEL_DENSITY_T_M3 * 1000
    centre = _centre(member, trace)
    key = member["member_id"]
    name = section_name(member["profile"])
    points = "\n".join(f'              <ocx:Point3D coordinates="{_coords(p)}" unit="Um"/>' for p in trace)
    web = " ".join(f"{v:.6f}" for v in member["web_direction"])
    middle = trace[len(trace) // 2]
    return f"""    <ocx:Stiffener id="{_xml_id('stiffener', number)}" name={quoteattr(key)} ocx:GUIDRef="{_guid('stiffener/' + key)}">
      <ocx:Description>{escape(_description(member))}</ocx:Description>
      <ocx:PhysicalProperties>
        <ocx:DryWeight numericvalue="{weight_kg:.3f}" unit="UKg"/>
        <ocx:CenterOfGravity coordinates="{_coords(centre)}" unit="Um"/>
      </ocx:PhysicalProperties>
      <ocx:TraceLine>
        <ocx:CompositeCurve3D id="{_xml_id('trace', number)}" ocx:GUIDRef="{_guid('trace/' + key)}">
          <ocx:CurveLength numericvalue="{length:.{COORDINATE_DIGITS}f}" unit="Um"/>
          <ocx:PolyLine3D id="{_xml_id('tracepolyline', number)}" ocx:GUIDRef="{_guid('tracepolyline/' + key)}">
            <ocx:CurveLength numericvalue="{length:.{COORDINATE_DIGITS}f}" unit="Um"/>
{points}
          </ocx:PolyLine3D>
        </ocx:CompositeCurve3D>
      </ocx:TraceLine>
      <ocx:MaterialRef localRef="{material_id}" ocx:GUIDRef="{_guid('material/' + grade)}" ocx:refType="ocx:Material"/>
      <ocx:SectionRef localRef="{section_id}" ocx:GUIDRef="{_guid('section/' + name)}" ocx:refType="ocx:BarSection">
        <ocx:OffsetU numericvalue="0" unit="Um"/>
        <ocx:OffsetV numericvalue="0" unit="Um"/>
      </ocx:SectionRef>
      <ocx:Inclination>
        <ocx:WebDirection direction="{web}"/>
        <ocx:Position coordinates="{_coords(middle)}" unit="Um"/>
      </ocx:Inclination>
    </ocx:Stiffener>"""


def writable_tanks(tanks) -> list:
    """The tanks an OCX file can hold: those with a mesh (a compartment needs faces, volume and centre)."""
    return [t for t in tanks or [] if t.triangles is not None and len(t.triangles) > 0]


def _compartment_description(tank, row: dict, content_class: str) -> str:
    labels = " ".join(f"{k}={v}" for k, v in sorted(row["source_labels"].items()) if v)
    frames = f"; frames={row['frames']}" if row["frames"] else ""
    return (f"name={tank.name}; content={tank.content}; content_class={content_class}{frames}; "
            f"volume at 100 % fill (moulded); source labels: {labels}; engineering_approved=false")


def _polyline_loop_xml(key: str, suffix: str, loop, indent: str) -> str:
    """A closed ``CompositeCurve3D`` with one ``PolyLine3D`` through the loop points.

    ``key`` makes the GUIDs (any text); ``suffix`` makes the xml IDs (letters, digits, underscore).
    """
    closed = list(loop) + [loop[0]]
    length = sum(math.dist(a, b) for a, b in zip(closed, closed[1:]))
    points = "\n".join(f'{indent}    <ocx:Point3D coordinates="{_coords(p)}" unit="Um"/>' for p in closed)
    return f"""{indent}<ocx:CompositeCurve3D id="loop{suffix}" ocx:GUIDRef="{_guid('loop/' + key)}">
{indent}  <ocx:CurveLength numericvalue="{length:.{COORDINATE_DIGITS}f}" unit="Um"/>
{indent}  <ocx:PolyLine3D id="loopline{suffix}" ocx:GUIDRef="{_guid('polyline/' + key)}">
{indent}    <ocx:CurveLength numericvalue="{length:.{COORDINATE_DIGITS}f}" unit="Um"/>
{points}
{indent}  </ocx:PolyLine3D>
{indent}</ocx:CompositeCurve3D>"""


def _face_xml(tank_id: str, tank_number: int, number: int, face) -> str:
    """One planar ``CompartmentFace``: a bilinear NURBS patch (as in the sample models) trimmed by the loops."""
    key = f"{tank_id}/{number}"
    name = f"{tank_id}_{number}"
    suffix = f"{tank_number}_{number}"  # xml IDs come from numbers: a tank ID may hold any character
    patch = "\n".join(f'                <ocx:ControlPoint coordinates="{_coords(p)}" unit="Um" weight="1"/>'
                      for p in patch_corners(face))
    loops = "\n".join(_polyline_loop_xml(f"{key}/{k}", f"{suffix}_{k}", loop, "            ")
                      for k, loop in enumerate(face.loops))
    return f"""        <ocx:CompartmentFace id="face{suffix}" name={quoteattr(name)} ocx:GUIDRef="{_guid('face/' + key)}">
          <ocx:UnboundedGeometry>
            <ocx:NURBSSurface id="surface{suffix}" ocx:GUIDRef="{_guid('surface/' + key)}">
              <ocx:U_NURBSproperties degree="1" numCtrlPts="2" numKnots="4" isRational="false"/>
              <ocx:UknotVector value="0 0 1 1"/>
              <ocx:V_NURBSproperties degree="1" numCtrlPts="2" numKnots="4" isRational="false"/>
              <ocx:VknotVector value="0 0 1 1"/>
              <ocx:ControlPtList>
{patch}
              </ocx:ControlPtList>
            </ocx:NURBSSurface>
          </ocx:UnboundedGeometry>
          <ocx:FaceBoundaryCurve>
{loops}
          </ocx:FaceBoundaryCurve>
        </ocx:CompartmentFace>"""


def _cargo_xml(tank, content_class: str, density_t_m3: float | None) -> str:
    """``LiquidCargo`` when the tank has a density and holds something; else ``UnitCargo`` (the schema
    requires one cargo element, and a void or an unknown content has no liquid)."""
    if density_t_m3 is None or content_class == "void":
        return "        <ocx:UnitCargo/>"
    cargo_type = LIQUID_CARGO_TYPE.get(content_class, "unspecified")
    return (f'        <ocx:LiquidCargo ocx:liquidCargoType="{cargo_type}">\n'
            f'          <ocx:Density numericvalue="{density_t_m3 * KG_PER_TONNE:.3f}" unit="UKgOverm3"/>\n'
            "        </ocx:LiquidCargo>")


def _compartment_xml(number: int, tank) -> str:
    row = tank_model.capacity_row(tank)
    content_class = tank_model.content_class(tank.content, tank.name)
    faces = planar_faces(tank_model.outward(tank.triangles))
    centre = (row["lcg_m"], row["tcg_m"], row["vcg_m"])
    face_text = "\n".join(_face_xml(tank.id, number, n, face) for n, face in enumerate(faces))
    return f"""      <ocx:Compartment id="{_xml_id('compartment', number)}" name={quoteattr(tank.id)} ocx:GUIDRef="{_guid('compartment/' + tank.id)}" ocx:compartmentPurpose="{COMPARTMENT_PURPOSE[content_class]}">
        <ocx:Description>{escape(_compartment_description(tank, row, content_class))}</ocx:Description>
        <ocx:CompartmentProperties>
          <ocx:CenterOfGravity coordinates="{_coords(centre)}" unit="Um"/>
          <ocx:Volume numericvalue="{row['volume_100_m3']:.{COORDINATE_DIGITS}f}" unit="Um3"/>
        </ocx:CompartmentProperties>
{face_text}
{_cargo_xml(tank, content_class, row['density_t_m3'])}
      </ocx:Compartment>"""


def _arrangement_xml(tanks: list) -> str:
    if not tanks:
        return ""
    return ('    <ocx:Arrangement id="arrangement" name="tanks">\n'
            + "\n".join(_compartment_xml(n, t) for n, t in enumerate(tanks)) + "\n    </ocx:Arrangement>")


def _tank_extent(tanks: list) -> tuple[float, float, float]:
    """Length, breadth and height (top z) of the tanks' bounding box (principal particulars of a tanks-only file)."""
    corners = np.concatenate([t.triangles.reshape(-1, 3) for t in tanks])
    low, high = corners.min(axis=0), corners.max(axis=0)
    return float(high[0] - low[0]), float(high[1] - low[1]), float(high[2])


def _frame_planes_xml(block: dict, name: str) -> str:
    """X reference planes: the block's bulkhead, web-frame and ordinary-frame stations (x = 0 if none)."""
    stations = block.get("stations") or {}
    xs = sorted({round(x, COORDINATE_DIGITS) for key in ("bulkheads", "webs", "frames") for x in stations.get(key, [])})
    lines = []
    for number, x in enumerate(xs or [0.0]):
        lines += [f'        <ocx:RefPlane id="{_xml_id("xplane", number)}" name="X{number}" '
                  f'ocx:GUIDRef="{_guid(f"xplane/{name}/{number}")}">',
                  f'          <ocx:ReferenceLocation numericvalue="{x:.{COORDINATE_DIGITS}f}" unit="Um"/>',
                  "        </ocx:RefPlane>"]
    return "\n".join(lines)


def is_stiffener(member: dict) -> bool:
    return bool(member.get("trace")) and bool(member.get("profile"))


def export_ocx(block: dict | None, path: Path, name: str = "MarinaFrame structure block",
               tanks: list | None = None) -> int:
    """Write the block and the tanks as an OCX 3.0.1 file.

    ``block`` is a structure block (plates and stiffeners), or None for a tanks-only file; ``tanks`` is a
    ``tanks.Tank`` list (tanks without a mesh are left out). Returns the number of parts: members plus
    compartments.
    """
    block = block or {"members": []}
    compartment_tanks = writable_tanks(tanks)
    members = block["members"]
    # The schema needs one material in the catalogue: a tanks-only file carries grade A, used by nothing.
    grades = sorted({grade_of(m.get("material")) for m in members}) or [grade_of(None)]
    material_ids = {grade: _xml_id("material", k) for k, grade in enumerate(grades)}
    breadth, depth = block.get("breadth_m") or 0.0, block.get("depth_m") or 0.0
    length = (block.get("guesses") or {}).get("block_length_m") or block.get("length_m") or 0.0
    if not members and compartment_tanks:  # tanks only: the tanks' bounding box stands in for the block
        length, full_breadth, depth = _tank_extent(compartment_tanks)
        breadth = full_breadth / 2  # the particulars below write 2 x breadth
    plate_members = [m for m in members if not is_stiffener(m)]
    stiffener_members = [m for m in members if is_stiffener(m)]
    profiles = {section_name(m["profile"]): m["profile"] for m in stiffener_members}
    section_ids = {key: _xml_id("section", k) for k, key in enumerate(sorted(profiles))}
    parts = [_plate_xml(n, m, material_ids[grade_of(m.get("material"))], grade_of(m.get("material")))
             for n, m in enumerate(plate_members)]
    parts += [_stiffener_xml(n, m, material_ids[grade_of(m.get("material"))], grade_of(m.get("material")),
                             section_ids[section_name(m["profile"])])
              for n, m in enumerate(stiffener_members)]
    arrangement = [_arrangement_xml(compartment_tanks)] if compartment_tanks else []  # schema order: before plates
    vessel_parts = "\n".join(arrangement + parts)
    sections = "\n".join(_section_xml(profiles[key], section_ids[key]) for key in sorted(profiles))
    text = f"""<?xml version="1.0" encoding="utf-8"?>
<ocx:ocxXML xmlns:ocx="{OCX_NAMESPACE}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" schemaVersion="{SCHEMA_VERSION}">
  <ocx:Header name={quoteattr(name)} author="MarinaFrame" organization="MarinaFrame" originating_system="MarinaFrame structure block" application_version="structure block v2" time_stamp="2026-01-01T00:00:00" documentation="DRAFT: engineering_approved=false. Read from drawings; values labelled printed or guessed per plate."/>
  <ocx:Vessel id="vessel" name={quoteattr(name)} ocx:GUIDRef="{_guid('vessel/' + name)}">
    <ocx:DistanceTolerance numericvalue="1" unit="Umm"/>
    <ocx:AngleTolerance numericvalue="0.001" unit="URad"/>
    <ocx:CoordinateSystem id="coordinates" ocx:GUIDRef="{_guid('coordinates/' + name)}" isGlobal="true">
      <ocx:XRefPlanes>
{_frame_planes_xml(block, name)}
      </ocx:XRefPlanes>
      <ocx:LocalCartesian>
        <ocx:Origin coordinates="0 0 0" unit="Um"/>
        <ocx:PrimaryAxis direction="1 0 0"/>
        <ocx:SecondaryAxis direction="0 1 0"/>
      </ocx:LocalCartesian>
    </ocx:CoordinateSystem>
    <ocx:ClassificationData ocx:newbuildingSociety="{CLASS_SOCIETY}" identification="draft">
      <ocx:PrincipalParticulars>
        <ocx:Lpp numericvalue="{length:.3f}" unit="Um"/>
        <ocx:RuleLength numericvalue="{length:.3f}" unit="Um"/>
        <ocx:BlockCoefficient numericvalue="0" unit="UDimless"/>
        <ocx:FP_Pos numericvalue="{length:.3f}" unit="Um"/>
        <ocx:MouldedBreadth numericvalue="{2 * breadth:.3f}" unit="Um"/>
        <ocx:MouldedDepth numericvalue="{depth:.3f}" unit="Um"/>
        <ocx:ScantlingDraught numericvalue="0" unit="Um"/>
        <ocx:DesignSpeed numericvalue="0" unit="UDimless"/>
        <ocx:FreeboardLength numericvalue="{length:.3f}" unit="Um"/>
        <ocx:AP_Pos numericvalue="0" unit="Um"/>
      </ocx:PrincipalParticulars>
    </ocx:ClassificationData>
{vessel_parts}
  </ocx:Vessel>
{_material_xml(material_ids, sections)}
{_units_xml()}
</ocx:ocxXML>
"""
    Path(path).write_text(text, encoding="utf-8")
    return len(members) + len(compartment_tanks)


# Units a compartment refers to; a file written before compartments existed may lack ``Um3``.
COMPARTMENT_UNIT_IDS = ("Um", "Um3", "UKgOverm3")
# Vessel children that follow ``Arrangement`` in the schema sequence: the compartments go before the first.
AFTER_ARRANGEMENT = re.compile(r"^ *<ocx:(ReferenceSurfaces|Panel|Plate|Stiffener|Bracket|Member)\b", re.MULTILINE)


def add_compartments(source: Path, target: Path, tanks: list) -> bool:
    """Write ``target``: the OCX file ``source`` (made by ``export_ocx``) with the tanks added as compartments.

    Returns False, and writes nothing, when there is nothing to add or the file cannot take them: it has
    an ``Arrangement`` already, is not in the ``ocx:`` prefix form of ``export_ocx``, or lacks a unit
    the compartments need. The caller then keeps ``source`` as it is.
    """
    written = writable_tanks(tanks)
    text = Path(source).read_text(encoding="utf-8")
    has_units = all(f'xml:id="{unit}"' in text for unit in COMPARTMENT_UNIT_IDS)
    if not written or "<ocx:Vessel " not in text or "<ocx:Arrangement" in text or not has_units:
        return False
    arrangement = _arrangement_xml(written) + "\n"
    first_part = AFTER_ARRANGEMENT.search(text)
    position = first_part.start() if first_part else text.index("  </ocx:Vessel>")
    Path(target).write_text(text[:position] + arrangement + text[position:], encoding="utf-8")
    return True


# --- reader ------------------------------------------------------------------------------

@dataclass(frozen=True)
class OcxPlate:
    name: str | None
    thickness_m: float | None
    area_m2: float | None  # from the outer contour when it is a polyline, else the printed NetArea
    net_area_m2: float | None


UNIT_TO_METRES = {"Umm": 1e-3, "Umm2": 1e-6, "Umm3": 1e-9, "Ucm": 1e-2, "Ucm2": 1e-4, "Ucm3": 1e-6}


def _tag(element) -> str:
    return element.tag.split("}")[-1]


def _child(element, name):
    return next((c for c in element if _tag(c) == name), None)


def _metres(quantity) -> float | None:
    """A length, area or volume quantity in metres, square or cubic metres (OCX files use Um, Umm, Ucm and
    their square and cube units)."""
    if quantity is None:
        return None
    return float(quantity.get("numericvalue")) * UNIT_TO_METRES.get(quantity.get("unit", "Um"), 1.0)


def _contour_area(contour) -> float | None:
    polylines = [e for e in contour.iter() if _tag(e) == "PolyLine3D"]
    if len(polylines) != 1:
        return None
    points = [tuple(float(v) for v in p.get("coordinates").split()) for p in polylines[0] if _tag(p) == "Point3D"]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return polygon_area(points) if len(points) >= 3 else None


@dataclass(frozen=True)
class OcxStiffener:
    name: str | None
    section: str | None  # the referenced BarSection's name (from the catalogue)
    length_m: float | None


def read_stiffeners(path: Path) -> list[OcxStiffener]:
    """All ``Stiffener`` elements with their section name and trace length (streamed)."""
    stiffeners, section_names = [], {}
    for _, element in ElementTree.iterparse(path, events=("end",)):
        tag = _tag(element)
        if tag == "BarSection":
            section_names[element.get("id")] = element.get("name")
        elif tag == "Stiffener":
            trace = _child(element, "TraceLine")
            curve = _child(trace, "CompositeCurve3D") if trace is not None else None
            length = _metres(_child(curve, "CurveLength")) if curve is not None else None
            reference = _child(element, "SectionRef")
            stiffeners.append(OcxStiffener(element.get("name"),
                                           reference.get("localRef") if reference is not None else None, length))
            element.clear()
        elif tag == "Plate":
            element.clear()
    return [OcxStiffener(s.name, section_names.get(s.section, s.section), s.length_m) for s in stiffeners]


def read_plates(path: Path) -> list[OcxPlate]:
    """All ``Plate`` elements of an OCX file (streamed; other elements are dropped as read)."""
    plates = []
    depth = 0
    for event, element in ElementTree.iterparse(path, events=("start", "end")):
        tag = _tag(element)
        if event == "start":
            if tag == "Plate":
                depth += 1
            continue
        if tag == "Plate":
            depth -= 1
            material = _child(element, "PlateMaterial")
            thickness = _metres(_child(material, "Thickness")) if material is not None else None
            net = _metres(_child(element, "NetArea"))
            contour = _child(element, "OuterContour")
            area = _contour_area(contour) if contour is not None else None
            plates.append(OcxPlate(element.get("name"), thickness, area if area is not None else net, net))
            element.clear()
        elif depth == 0 and tag not in ("ocxXML", "Vessel"):
            element.clear()
    return plates


@dataclass(frozen=True)
class OcxCompartment:
    name: str | None
    purpose: str | None  # compartmentPurpose
    volume_m3: float | None
    centre_m: tuple[float, float, float] | None  # CenterOfGravity
    density_kg_m3: float | None  # LiquidCargo density; None for a unit or bulk cargo
    cargo_type: str | None  # liquidCargoType
    face_count: int


def _compartment_from(element) -> OcxCompartment:
    properties = _child(element, "CompartmentProperties")
    centre = _child(properties, "CenterOfGravity") if properties is not None else None
    point = None
    if centre is not None:
        scale = UNIT_TO_METRES.get(centre.get("unit", "Um"), 1.0)
        point = tuple(float(v) * scale for v in centre.get("coordinates").split())
    liquid = _child(element, "LiquidCargo")
    density = _child(liquid, "Density") if liquid is not None else None
    return OcxCompartment(
        element.get("name"), _attribute(element, "compartmentPurpose"),
        _metres(_child(properties, "Volume")) if properties is not None else None, point,
        float(density.get("numericvalue")) if density is not None else None,
        _attribute(liquid, "liquidCargoType") if liquid is not None else None,
        sum(1 for child in element if _tag(child) == "CompartmentFace"))


def _attribute(element, name: str) -> str | None:
    """An attribute by local name (OCX writes ``ocx:compartmentPurpose`` as a namespaced attribute)."""
    return next((value for key, value in element.attrib.items() if key.split("}")[-1] == name), None)


def read_compartments(path: Path) -> list[OcxCompartment]:
    """All ``Compartment`` elements of an OCX file (streamed; other elements are dropped as read)."""
    compartments = []
    depth = 0
    for event, element in ElementTree.iterparse(path, events=("start", "end")):
        tag = _tag(element)
        if event == "start":
            if tag == "Compartment":
                depth += 1
            continue
        if tag == "Compartment":
            depth -= 1
            compartments.append(_compartment_from(element))
            element.clear()
        elif depth == 0 and tag not in ("ocxXML", "Vessel", "Arrangement"):
            element.clear()
    return compartments


# --- schema check ------------------------------------------------------------------------

MINIMAL_XML_XSD = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="http://www.w3.org/XML/1998/namespace">
  <xs:attribute name="lang" type="xs:language"/>
  <xs:attribute name="space"><xs:simpleType><xs:restriction base="xs:NCName">
    <xs:enumeration value="default"/><xs:enumeration value="preserve"/></xs:restriction></xs:simpleType></xs:attribute>
  <xs:attribute name="base" type="xs:anyURI"/>
  <xs:attribute name="id" type="xs:ID"/>
</xs:schema>
"""
UNITSML_FILE = "unitsmlSchema_lite-0.9.18.xsd"


@dataclass(frozen=True)
class SchemaCheck:
    valid: bool
    errors: list[str]


def validate(path: Path, schema_dir: Path, max_errors: int = 20) -> SchemaCheck:
    """Validate an OCX file with ``xmllint`` against ``schema_dir/OCX_Schema.xsd`` (offline)."""
    xmllint = shutil.which("xmllint")
    if xmllint is None:
        raise FileNotFoundError("xmllint is not installed")
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder)
        schema = (schema_dir / "OCX_Schema.xsd").read_text(encoding="utf-8")
        schema = re.sub(r'schemaLocation="[^"]*' + re.escape(UNITSML_FILE) + '"',
                        f'schemaLocation="{UNITSML_FILE}"', schema)
        (local / "OCX_Schema.xsd").write_text(schema, encoding="utf-8")
        unitsml = (schema_dir / UNITSML_FILE).read_text(encoding="utf-8")
        unitsml = unitsml.replace('schemaLocation="http://www.w3.org/2001/xml.xsd"', 'schemaLocation="xml.xsd"')
        (local / UNITSML_FILE).write_text(unitsml, encoding="utf-8")
        (local / "xml.xsd").write_text(MINIMAL_XML_XSD, encoding="utf-8")
        result = subprocess.run([xmllint, "--noout", "--nonet", "--schema", str(local / "OCX_Schema.xsd"),
                                 str(path)], capture_output=True, text=True, check=False)
    errors = [line for line in result.stderr.splitlines() if "validates" not in line][:max_errors]
    return SchemaCheck(result.returncode == 0, errors)


def round_trip(block: dict | None, path: Path, tanks: list | None = None) -> dict:
    """Compare a written export with the block: plate count, thickness and area per plate; and
    stiffener count, section name and trace length per stiffener. With ``tanks``, also compartment
    count, name, purpose, volume and centre of gravity per tank."""
    result = {"all_equal": True}
    if block is not None:
        plates = {p.name: p for p in read_plates(path)}
        members = [m for m in block["members"] if not is_stiffener(m)]
        result = _plate_round_trip(members, plates)
        stiffener_members = [m for m in block["members"] if is_stiffener(m)]
        if stiffener_members:
            result["stiffeners"] = _stiffener_round_trip(stiffener_members, path)
            result["all_equal"] = result["all_equal"] and result["stiffeners"]["all_equal"]
    if tanks is not None:
        result["compartments"] = _compartment_round_trip(writable_tanks(tanks), path)
        result["all_equal"] = result["all_equal"] and result["compartments"]["all_equal"]
    return result


def _compartment_round_trip(tanks: list, path: Path) -> dict:
    read = {c.name: c for c in read_compartments(path)}
    purpose_equal = volume_equal = centre_equal = 0
    for tank in tanks:
        found = read.get(tank.id)
        if found is None:
            continue
        row = tank_model.capacity_row(tank)
        purpose_equal += found.purpose == COMPARTMENT_PURPOSE[tank_model.content_class(tank.content, tank.name)]
        volume_equal += found.volume_m3 is not None and abs(found.volume_m3 - row["volume_100_m3"]) <= 1e-6
        expected = (row["lcg_m"], row["tcg_m"], row["vcg_m"])
        centre_equal += found.centre_m is not None and all(abs(a - b) <= 1e-6 for a, b in zip(found.centre_m, expected))
    return {"tanks": len(tanks), "compartments_read": len(read), "count_equal": len(read) == len(tanks),
            "purpose_equal": purpose_equal, "volume_equal": volume_equal, "centre_equal": centre_equal,
            "all_equal": len(read) == len(tanks) == purpose_equal == volume_equal == centre_equal}


def _stiffener_round_trip(members: list[dict], path: Path) -> dict:
    read = {s.name: s for s in read_stiffeners(path)}
    section_equal = length_equal = 0
    for member in members:
        found = read.get(member["member_id"])
        if found is None:
            continue
        section_equal += found.section == section_name(member["profile"])
        length = member["length_m"]
        length_equal += found.length_m is not None and abs(found.length_m - length) <= 1e-6 * max(1.0, length)
    return {"members": len(members), "stiffeners_read": len(read), "count_equal": len(read) == len(members),
            "section_equal": section_equal, "length_equal": length_equal,
            "all_equal": len(read) == len(members) == section_equal == length_equal}


def _plate_round_trip(members: list[dict], plates: dict) -> dict:
    thickness_equal = area_equal = 0
    for member in members:
        plate = plates.get(member["member_id"])
        if plate is None:
            continue
        thickness = (member["thickness_mm"] or 0.0) / 1000
        if plate.thickness_m is not None and abs(plate.thickness_m - thickness) <= 1e-9:
            thickness_equal += 1
        expected = member["area_m2"]
        if plate.net_area_m2 is not None and abs(plate.net_area_m2 - expected) <= 1e-6 * max(1.0, expected):
            area_equal += 1
    return {"members": len(members), "plates_read": len(plates), "count_equal": len(plates) == len(members),
            "thickness_equal": thickness_equal, "area_equal": area_equal,
            "all_equal": len(plates) == len(members) == thickness_equal == area_equal}
