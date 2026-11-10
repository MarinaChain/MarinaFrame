"""Additional draft CAD formats for the millimetre OpenCascade model."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .errors import GeometryError

if TYPE_CHECKING:
    import cadquery as cq

# Mode 1 writes boundary representations, including solid topology; mode 0 writes surfaces.
IGES_BREP_MODE = 1
IGES_DRAFT_STAMP = "MarinaFrame DRAFT: not for construction."


def export_iges(shape: cq.Shape, path: Path) -> None:
    """Write an IGES BRep in millimetres, matching STEP, with a draft stamp."""
    from OCP.IGESControl import IGESControl_Writer

    writer = IGESControl_Writer("MM", IGES_BREP_MODE)
    model = writer.Model()
    model.AddStartLine(IGES_DRAFT_STAMP)
    model.AddStartLine("engineering_approved=false")
    model.AddStartLine("Units mm; x along the length as drawn; z up from the baseline.")
    if not writer.AddShape(shape.wrapped):
        raise GeometryError("The shape could not be translated to IGES.")
    if not writer.Write(str(path)):
        raise GeometryError("The IGES file could not be written.")
