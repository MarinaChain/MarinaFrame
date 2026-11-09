"""OCX 3.0.1 export and plate reader for structure blocks (docs/STRUCTURE_V2.md section 6.1).

Export: one ``ocx:Plate`` per block member, directly under ``ocx:Vessel`` (the schema allows plates
outside a panel; a block zone holds members in several planes, so it is not one OCX panel). Each
plate has its mid-plane rectangle as a closed ``PolyLine3D`` outer contour, its thickness and
material (``PlateMaterial``), net area and dry weight. Stiffener webs and flanges are flat parts in
the block model and are written as plates too. The member ID is the plate ``name``; the source
labels go in ``Description``.

Reader: streams ``Plate`` elements (name, thickness, area), so a large model such as the 22 MB
D-VLCC sample reads in flat memory.

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

from .steel import STEEL_DENSITY_T_M3

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
UNITS = {"Um": ("m", "meter", 1, None), "Um2": ("m2", "meter", 2, None), "Umm": ("mm", "meter", 1, "m"),
         "UKg": ("kg", "gram", 1, "k"), "URad": ("rad", "radian", 1, None),
         "UKgOverm3": ("kg/m3", None, None, None), "UNOvermm2": ("N/mm2", None, None, None),
         "UDimless": ("", None, None, None)}
# The schema requires a class society; the block's scantlings follow the ABS rule subset of the
# MiDShip generator (docs/RULES_V1.md). It is not a class assignment.
CLASS_SOCIETY = "ABS"
GUID_NAMESPACE = uuid.UUID("6f1c1d0e-6a53-4c8e-9a64-6d1a0c2f3b10")  # fixed: stable GUIDs per ID


def _guid(key: str) -> str:
    return str(uuid.uuid5(GUID_NAMESPACE, key))


def _xml_id(prefix: str, number: int) -> str:
    return f"{prefix}{number}"


def grade_of(material: str | None) -> str:
    """Steel grade from a printed material ('ASTM A131 - AB/A' -> 'A'); 'A' when none is printed."""
    if not material:
        return "A"
    tail = re.split(r"[/\s-]+", material.strip())[-1].upper()
    tail = re.sub(r"^([ADEF])H(\d\d)$", r"\1\2", tail)  # "AH36" -> "A36"
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


def _material_xml(material_ids: dict[str, str]) -> str:
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
    lines += ["    </ocx:MaterialCatalogue>", "  </ocx:ClassCatalogue>"]
    return "\n".join(lines)


def _description(member: dict) -> str:
    sources = " ".join(f"{k}={v}" for k, v in sorted((member.get("sources") or {}).items()))
    return (f"label={member['label']}; group={member['group']}; thickness={member['thickness_source']}; "
            f"material={member.get('material_source', 'guessed')}; placement: {sources}; "
            "engineering_approved=false")


def _plate_xml(number: int, member: dict, material_id: str, grade: str) -> str:
    corners = plate_corners(member["box"])
    closed = corners + [corners[0]]
    perimeter = sum(math.dist(a, b) for a, b in zip(closed, closed[1:]))
    thickness_m = (member["thickness_mm"] or 0.0) / 1000
    area = member["area_m2"]
    weight_kg = area * thickness_m * STEEL_DENSITY_T_M3 * 1000
    centre = [(member["box"][i] + member["box"][i + 3]) / 2 for i in range(3)]
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


def export_ocx(block: dict, path: Path, name: str = "MarinaFrame structure block") -> int:
    """Write the block as an OCX 3.0.1 file; return the number of plates written."""
    members = block["members"]
    grades = sorted({grade_of(m.get("material")) for m in members})
    material_ids = {grade: _xml_id("material", k) for k, grade in enumerate(grades)}
    breadth, depth = block.get("breadth_m") or 0.0, block.get("depth_m") or 0.0
    length = (block.get("guesses") or {}).get("block_length_m") or 0.0
    plates = "\n".join(_plate_xml(n, m, material_ids[grade_of(m.get("material"))], grade_of(m.get("material")))
                       for n, m in enumerate(members))
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
{plates}
  </ocx:Vessel>
{_material_xml(material_ids)}
{_units_xml()}
</ocx:ocxXML>
"""
    Path(path).write_text(text, encoding="utf-8")
    return len(members)


# --- reader ------------------------------------------------------------------------------

@dataclass(frozen=True)
class OcxPlate:
    name: str | None
    thickness_m: float | None
    area_m2: float | None  # from the outer contour when it is a polyline, else the printed NetArea
    net_area_m2: float | None


def _tag(element) -> str:
    return element.tag.split("}")[-1]


def _child(element, name):
    return next((c for c in element if _tag(c) == name), None)


def _metres(quantity) -> float | None:
    """A length or area quantity in metres (OCX files use Um or Umm, Um2 or Umm2)."""
    if quantity is None:
        return None
    value = float(quantity.get("numericvalue"))
    unit = quantity.get("unit", "Um")
    scale = {"Umm": 1e-3, "Umm2": 1e-6, "Ucm": 1e-2, "Ucm2": 1e-4}.get(unit, 1.0)
    return value * scale


def _contour_area(contour) -> float | None:
    polylines = [e for e in contour.iter() if _tag(e) == "PolyLine3D"]
    if len(polylines) != 1:
        return None
    points = [tuple(float(v) for v in p.get("coordinates").split()) for p in polylines[0] if _tag(p) == "Point3D"]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return polygon_area(points) if len(points) >= 3 else None


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


def round_trip(block: dict, path: Path) -> dict:
    """Compare a written export with the block: plate count, thickness and area per plate."""
    plates = {p.name: p for p in read_plates(path)}
    members = block["members"]
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
