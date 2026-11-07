"""Data types for structural members read from a midship section drawing.

Drawing coordinates are millimetres on the sheet with the z axis up
(``x_mm`` to the right, ``z_mm`` up from the bottom sheet edge). Ship
coordinates are millimetres with y from the centreline to starboard and z up
from the baseline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

Point = tuple[float, float]

PLATE_ROLES = ("bottom_shell", "side_shell", "shell_strake", "deck",
               "longitudinal_bulkhead", "hopper_plate")
WEB_ROLES = ("girder", "stiffener_web")
ROLES = PLATE_ROLES + WEB_ROLES + ("flange",)

HOSTS = ("Bottom", "Inner_Bottom", "Deck", "Side_Shell", "Inner_Side_Shell",
         "Longitudinal_Bulkhead", "Hopper_Pannel")


@dataclass(frozen=True)
class Stroke:
    """One drawn line or polyline in drawing millimetres.

    ``source`` names the evidence: the page path index for vector input, or
    the pixel component for raster input.
    """
    index: int
    points: tuple[Point, ...]
    source: str

    @property
    def start(self) -> Point:
        return self.points[0]

    @property
    def end(self) -> Point:
        return self.points[-1]

    @property
    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        zs = [p[1] for p in self.points]
        return min(xs), min(zs), max(xs), max(zs)

    @property
    def midpoint(self) -> Point:
        x0, z0, x1, z1 = self.bbox
        return (x0 + x1) / 2, (z0 + z1) / 2


@dataclass(frozen=True)
class Word:
    """One text word with its box in drawing millimetres (z up)."""
    x0: float
    z0: float
    x1: float
    z1: float
    text: str

    @property
    def centre(self) -> Point:
        return (self.x0 + self.x1) / 2, (self.z0 + self.z1) / 2


@dataclass(frozen=True)
class SheetInput:
    """Everything the section reader receives from one drawing sheet."""
    strokes: tuple[Stroke, ...]
    words: tuple[Word, ...]
    width_mm: float
    height_mm: float
    source_kind: str  # "vector" or "raster"
    tolerance_mm: float  # distance at which two strokes are taken to touch


@dataclass(frozen=True)
class PlateRow:
    name: str
    thickness_mm: float | None


@dataclass(frozen=True)
class StiffenerRow:
    name: str
    count: int | None
    shape: str | None  # "T", "L" or "I"
    height_mm: float | None
    width_mm: float | None
    thickness_mm: float | None


@dataclass
class Member:
    """One structural member established by the drawing."""
    role: str
    stroke: Stroke
    host: str | None = None
    host_plate: int | None = None  # stroke index of the plate a web stands on
    web: int | None = None  # stroke index of the web a flange belongs to
    plate_row: str | None = None  # plate table row that gives the thickness
    stiffener_row: str | None = None  # stiffener table row
    thickness_mm: float | None = None
    measured_length_mm: float | None = None  # drawn length at ship scale
    ship_bbox_mm: tuple[float, float, float, float] | None = None  # y0, z0, y1, z1
    ship_points_mm: tuple[Point, ...] = ()
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "role": self.role,
            "host": self.host,
            "stroke": self.stroke.index,
            "evidence": self.stroke.source,
            "host_plate_stroke": self.host_plate,
            "web_stroke": self.web,
            "plate_table_row": self.plate_row,
            "stiffener_table_row": self.stiffener_row,
            "thickness_mm": self.thickness_mm,
            "measured_length_mm": _round(self.measured_length_mm),
            "ship_bbox_mm": [_round(v) for v in self.ship_bbox_mm] if self.ship_bbox_mm else None,
            "ship_points_mm": [[_round(x), _round(z)] for x, z in self.ship_points_mm],
            "drawing_bbox_mm": [_round(v) for v in self.stroke.bbox],
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Abstention:
    """A drawn stroke, or a property, that the drawing does not establish."""
    subject: str  # "stroke:<index>" or a property name
    reason: str
    evidence: str = ""

    def as_dict(self) -> dict:
        return {"subject": self.subject, "reason": self.reason, "evidence": self.evidence}


@dataclass
class SectionResult:
    members: list[Member]
    abstentions: list[Abstention]
    scale_mm_per_m: float | None
    origin_mm: Point | None  # drawing position of (centreline, baseline)
    plate_rows: list[PlateRow]
    stiffener_rows: list[StiffenerRow]
    source_kind: str
    section_strokes: int
    furniture_strokes: int

    def as_dict(self) -> dict:
        return {
            "schema": "marinaframe.structure_section.v1",
            "engineering_approved": False,
            "source_kind": self.source_kind,
            "scale_mm_per_m": self.scale_mm_per_m,
            "origin_drawing_mm": list(self.origin_mm) if self.origin_mm else None,
            "section_strokes": self.section_strokes,
            "furniture_strokes": self.furniture_strokes,
            "plate_table": [row.__dict__ for row in self.plate_rows],
            "stiffener_table": [row.__dict__ for row in self.stiffener_rows],
            "members": [m.as_dict() for m in self.members],
            "abstentions": [a.as_dict() for a in self.abstentions],
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)
