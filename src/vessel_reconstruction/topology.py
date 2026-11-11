"""Sub-shape lists and face triangulations without the slow end of an OCP iteration.

CadQuery's ``Faces()``, ``Edges()``, ``Wires()``, ``innerWires()`` and ``tessellate()``
iterate an OCP ``TopTools_IndexedMapOfShape`` in Python. The end of that iteration is a
``StopIteration`` that pybind11 passes through every exception translator OCP registers:
about 6 ms per call on a warm process (up to 80 ms on the first), whatever the map size.
The display mesh calls these several times per face; the Gunnerus hull has 3,151 faces,
so that cost was about a minute of the whole-vessel build (docs/plans/2026-11-11-build-speed.md).

These helpers read the same map by index (``FindKey``), so they return the same shapes in the
same order as CadQuery, and the same triangulation values as ``Shape.tessellate``.
"""
from __future__ import annotations

import cadquery as cq
import numpy as np
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape


def _mapped(shape: cq.Shape, kind) -> list:
    """The sub-shapes of one kind in ``TopExp.MapShapes`` order (as CadQuery lists them)."""
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape.wrapped, kind, found)
    return [found.FindKey(index) for index in range(1, found.Extent() + 1)]


def faces(shape: cq.Shape) -> list[cq.Face]:
    """Same as ``shape.Faces()``."""
    return [cq.Face(item) for item in _mapped(shape, TopAbs_FACE)]


def edges(shape: cq.Shape) -> list[cq.Edge]:
    """Same as ``shape.Edges()``: degenerated edges are left out."""
    return [cq.Edge(item) for item in _mapped(shape, TopAbs_EDGE)
            if not BRep_Tool.Degenerated_s(TopoDS.Edge_s(item))]


def wires(shape: cq.Shape) -> list[cq.Wire]:
    """Same as ``shape.Wires()``."""
    return [cq.Wire(item) for item in _mapped(shape, TopAbs_WIRE)]


def inner_wires(face: cq.Face) -> list[cq.Wire]:
    """Same as ``face.innerWires()``: every wire that is not the outer wire."""
    outer = face.outerWire()
    return [wire for wire in wires(face) if not wire.isSame(outer)]


def face_triangulation(face: cq.Face, tolerance: float, angular_tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (n x 3) and triangles (m x 3) of one face, as ``face.tessellate`` gives them.

    The face is meshed with ``face.mesh`` (the kernel mesher, only when the face has no
    triangulation at this tolerance yet), and the node coordinates and the triangle order of a
    reversed face are the same as in ``Shape.tessellate``.
    """
    face.mesh(tolerance, angular_tolerance)
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(face.wrapped, location)
    if triangulation is None:
        return np.array([]).reshape(-1, 3), np.asarray([], dtype=int).reshape(-1, 3)
    transform = location.Transformation()
    vertices = []
    for index in range(1, triangulation.NbNodes() + 1):
        node = triangulation.Node(index).Transformed(transform)
        vertices.append([node.X(), node.Y(), node.Z()])
    reverse = face.wrapped.Orientation() == TopAbs_REVERSED
    corners = (1, 3, 2) if reverse else (1, 2, 3)
    triangles = []
    for index in range(1, triangulation.NbTriangles() + 1):
        triangle = triangulation.Triangle(index)
        triangles.append([triangle.Value(corner) - 1 for corner in corners])
    return np.array(vertices).reshape(-1, 3), np.asarray(triangles, dtype=int).reshape(-1, 3)
