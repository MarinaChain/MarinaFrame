"""A simple 3D slice of the section members (CadQuery), for inspection only.

Each drawn segment of a member with a printed thickness becomes a box: the
segment length in the section plane, the printed thickness across it,
centred on the drawn line, and ``slice_length_mm`` along the ship. The
drawing gives no longitudinal extent and does not say on which side of the
line the thickness lies, so the slice length is the caller's choice and the
thickness is centred. Members without a printed thickness are left out and
listed. Ship axes: x along the ship, y to starboard, z up (millimetres).
"""
from __future__ import annotations

import math
from pathlib import Path

from .model import SectionResult
from ..cad_exports import export_iges
from ..rhino_exports import CadPart, export_3dm


def _slice_parts(result: SectionResult, slice_length_mm: float) -> tuple[list[CadPart], list[str]]:
    """Build named segment solids and list the omitted members."""
    import cadquery as cq

    parts = []
    omitted = []
    for number, member in enumerate(result.members):
        if member.thickness_mm is None or len(member.ship_points_mm) < 2:
            omitted.append(f"member {number} ({member.role}, stroke {member.stroke.index}): "
                           "no printed thickness or no ship placement")
            continue
        segments = zip(member.ship_points_mm, member.ship_points_mm[1:])
        for segment, ((y0, z0), (y1, z1)) in enumerate(segments):
            length = math.hypot(y1 - y0, z1 - z0)
            if length <= 0:
                continue
            box = cq.Solid.makeBox(slice_length_mm, length, member.thickness_mm,
                                   cq.Vector(0, -length / 2, -member.thickness_mm / 2))
            angle = math.degrees(math.atan2(z1 - z0, y1 - y0))
            box = box.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), angle)
            box = box.translate(cq.Vector(0, (y0 + y1) / 2, (z0 + z1) / 2))
            part_id = f"stroke-{member.stroke.index}-segment-{segment}"
            parts.append(CadPart(part_id, box, "Structure"))
    return parts, omitted


def build_slice(result: SectionResult, slice_length_mm: float):
    """Return (CadQuery compound or None, list of omitted member descriptions)."""
    import cadquery as cq

    parts, omitted = _slice_parts(result, slice_length_mm)
    if not parts:
        return None, omitted
    return cq.Compound.makeCompound([part.shape for part in parts]), omitted


def export_slice_step(result: SectionResult, path: Path, slice_length_mm: float) -> list[str]:
    """Write STEP and draft IGES/3dm files beside it; return omitted members."""
    import cadquery as cq

    parts, omitted = _slice_parts(result, slice_length_mm)
    if not parts:
        raise ValueError("no member has both a placement and a printed thickness")
    compound = cq.Compound.makeCompound([part.shape for part in parts])
    cq.exporters.export(cq.Workplane().add(compound), str(path), exportType="STEP")
    export_iges(compound, path.with_suffix(".iges"))
    export_3dm(parts, path.with_suffix(".3dm"))
    return omitted
