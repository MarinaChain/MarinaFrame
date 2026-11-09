"""Read the Gunnerus construction drawings for the 3D structure (docs/STRUCTURE_V2.md section 8).

Deterministic reading of three polarkonsult DXF sheets (no model call):

- Midship Section: section #I (a plain frame of the 5,000 mm new part) gives the members in the
  section plane from the moulded lines (layer S0CO5) and the dashed stiffener lines (S0DA2); the
  labels give thicknesses and profiles. Section #G (a bulkhead of the new part) gives the bulkhead
  plate and its vertical stiffeners.
- Shell Expansion: strake thickness of the new part between the printed seams; side-frame key.
- Profile and Plan: frame axes, tank-top levels and plate labels, the deck plate label, the
  new-part note and the girder elevations.

The windows are host calibration (a person read them from the sheets, as in step 1 and step 2);
all geometry and values inside them are read by code. DXF units are millimetres at full size.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
import re
import statistics
from pathlib import Path

from benchmarks.gunnerus.whole_vessel_internals import FRAME_SPACING_MM, frame_index

MIDSHIP = "polarkonsult/Midship Section Rev0.dxf"
SHELL_EXPANSION = "polarkonsult/Shell Expansion Rev0.dxf"
PROFILE_AND_PLAN = "polarkonsult/Profile and Plan Rev0.dxf"

# Host calibration windows [x0, y0, x1, y1] in DXF millimetres.
SECTION_I_WINDOW = (26500, 7300, 37300, 13100)
SECTION_G_WINDOW = (15500, 7300, 26200, 13500)
SHELL_NEW_PART_WINDOW = (18800, 14000, 20800, 21500)  # starboard sheet, the "5000 Lengthening" strip
SHELL_FRAME_KEY_WINDOW = (0, 25000, 16000, 29500)
PLAN_TANK_TOP_WINDOW = (12500, 2000, 24000, 15300)  # "TANKTOPS AND SINGLE BOTTOM", new part
PLAN_DECK_WINDOW = (12000, 15300, 24000, 28500)  # 1-deck plan, new part
PLAN_SHEET_1 = (-1000, -1000, 42500, 60000)
PLAN_SHEET_2 = (42500, -1000, 90000, 60000)

MOULDED_LAYER = "S0CO5"
HIDDEN_LAYER = "S0DA2"
BASELINE_LAYER = "S0PH1"
NEW_PART_FRAMES = tuple("ABCDEFGHIJ")
# Labels of a kind are read within this distance of the member they describe (mm on the sheet).
LABEL_REACH_MM = 1500.0
LINE_TOLERANCE_MM = 5.0


# --- sheet primitives ----------------------------------------------------------------------

@dataclass(frozen=True)
class Label:
    x: float
    y: float
    text: str
    kind: str  # "PL" (plate thickness block), "FB" (flat-bar block) or "TEXT"
    layer: str


@dataclass(frozen=True)
class Segment:
    layer: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def vertical(self) -> bool:
        return abs(self.x0 - self.x1) < 1.0 and abs(self.y0 - self.y1) >= 1.0

    @property
    def horizontal(self) -> bool:
        return abs(self.y0 - self.y1) < 1.0 and abs(self.x0 - self.x1) >= 1.0

    @property
    def length(self) -> float:
        return ((self.x1 - self.x0) ** 2 + (self.y1 - self.y0) ** 2) ** 0.5


@dataclass
class Sheet:
    labels: list[Label]
    segments: list[Segment]
    polylines: list[tuple[str, list[tuple[float, float]]]]

    def labels_in(self, window, kind: str | None = None) -> list[Label]:
        x0, y0, x1, y1 = window
        return [l for l in self.labels if x0 <= l.x <= x1 and y0 <= l.y <= y1 and (kind is None or l.kind == kind)]

    def segments_in(self, window, layer: str) -> list[Segment]:
        x0, y0, x1, y1 = window
        return [s for s in self.segments if s.layer == layer
                and x0 <= min(s.x0, s.x1) and max(s.x0, s.x1) <= x1 and y0 <= min(s.y0, s.y1) and max(s.y0, s.y1) <= y1]

    def polylines_in(self, window, layer: str) -> list[list[tuple[float, float]]]:
        x0, y0, x1, y1 = window
        return [points for name, points in self.polylines if name == layer
                and all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in points)]


def _label_kind(entity) -> str:
    if entity.dxftype() != "ATTRIB":
        return "TEXT"
    tag = entity.dxf.tag.upper()
    return "PL" if tag == "XX.X" else "FB" if tag.startswith("FL.ST") else "TEXT"


@lru_cache(maxsize=4)
def read_sheet(path: Path) -> Sheet:
    """All texts, attribute labels, line pieces and polylines of a DXF, blocks exploded."""
    import ezdxf
    from ezdxf.disassemble import recursive_decompose

    labels, segments, polylines = [], [], []
    for entity in recursive_decompose(ezdxf.readfile(path).modelspace()):
        kind = entity.dxftype()
        layer = entity.dxf.layer
        if kind in ("TEXT", "MTEXT", "ATTRIB"):
            text = entity.plain_text() if kind == "MTEXT" else entity.dxf.text
            if text.strip():
                point = entity.dxf.insert
                labels.append(Label(float(point.x), float(point.y), " ".join(text.split()), _label_kind(entity), layer))
        elif kind == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            segments.append(Segment(layer, float(a.x), float(a.y), float(b.x), float(b.y)))
        elif kind == "LWPOLYLINE":
            points = [(float(x), float(y)) for x, y in entity.get_points("xy")]
            if entity.closed and points:
                points.append(points[0])
            polylines.append((layer, points))
            segments += [Segment(layer, *a, *b) for a, b in zip(points, points[1:])]
    return Sheet(labels, segments, polylines)


# --- value parsing -------------------------------------------------------------------------

PLATE_PATTERN = re.compile(r"^(\d+(?:[.,]\d+)?)(?:\s*x\s*(\d+))?")
FCL_PATTERN = re.compile(r"^(\d{3,4})\s*FCL", re.I)
LEVEL_PATTERN = re.compile(r"(\d{3,4})\s*(?:O/BL|OBL|AB\.?\s*(?:OLD\s*)?BL)", re.I)


def plate_value(label: Label) -> tuple[float, float | None]:
    """Thickness (mm) and optional width (mm) of a PL label such as '8,0' or '8.0x150'."""
    match = PLATE_PATTERN.match(label.text)
    return float(match.group(1).replace(",", ".")), float(match.group(2)) if match.group(2) else None


def _nearest(labels: list[Label], x: float, y: float) -> Label | None:
    return min(labels, key=lambda l: (l.x - x) ** 2 + (l.y - y) ** 2, default=None)


def _most_common(values):
    return Counter(values).most_common(1)[0][0] if values else None


# --- midship section -----------------------------------------------------------------------

@dataclass
class Datums:
    centre_x: float
    new_baseline_y: float
    old_baseline_y: float
    deck_y: float
    tank_top_y: float

    def y_m(self, x_dxf: float) -> float:
        """Ship y of a section x on the sheet (the view is taken as seen from aft: right is starboard)."""
        return (x_dxf - self.centre_x) / 1000

    def z_m(self, y_dxf: float) -> float:
        return (y_dxf - self.new_baseline_y) / 1000

    def old_bl_to_z_m(self, level_mm: float) -> float:
        return (self.old_baseline_y + level_mm - self.new_baseline_y) / 1000


@dataclass
class SectionMembers:
    """Members of a transverse section read from its linework and labels."""
    datums: Datums
    breadth_m: float
    db_girders_m: list[float]  # y of double-bottom girders (centre girder included)
    deck_girders: list[dict]  # {'y_m', 'web_mm', 'label'}
    floor_stiffeners_m: list[float]
    bulkhead_stiffeners_m: list[float]
    shell_yz: list[tuple[float, float]]
    floor_plate: dict | None  # {'mm', 'labels'}
    bulkhead_plate: dict | None
    floor_stiffener_profile: str | None
    bulkhead_stiffener_profile: str | None
    fcl_labels_mm: list[tuple[float, float]]  # (printed FCL value, x of its label line in ship metres)
    levels: dict[str, float] = field(default_factory=dict)  # printed level texts (mm)


def _datums(sheet: Sheet, window) -> Datums:
    moulded = sheet.segments_in(window, MOULDED_LAYER)
    horizontals = sorted((s for s in moulded if s.horizontal and s.length > 5000), key=lambda s: -s.y0)
    deck, tank_top = horizontals[0], horizontals[1]
    centre_x = (min(deck.x0, deck.x1) + max(deck.x0, deck.x1)) / 2
    # Baselines run past the section outline: keep any that overlap the window.
    x0, y0, x1, y1 = window
    base_lines = [s for s in sheet.segments if s.layer == BASELINE_LAYER and s.horizontal and y0 <= s.y0 <= y1
                  and min(s.x0, s.x1) < x1 and max(s.x0, s.x1) > x0]
    labels = sheet.labels_in(window)

    def line_at(text: str) -> float:
        anchor = next(l for l in labels if l.text.lower().startswith(text))
        return min(base_lines, key=lambda s: abs(s.y0 - anchor.y)).y0

    return Datums(centre_x, line_at("new baseline"), line_at("old baseline"), deck.y0, tank_top.y0)


def read_section(sheet: Sheet, window) -> SectionMembers:
    datums = _datums(sheet, window)
    moulded = sheet.segments_in(window, MOULDED_LAYER)
    tolerance = LINE_TOLERANCE_MM
    verticals = [s for s in moulded if s.vertical]
    db_girders = sorted({round(datums.y_m(s.x0), 4) for s in verticals
                         if abs(max(s.y0, s.y1) - datums.tank_top_y) < tolerance and min(s.y0, s.y1) < datums.tank_top_y - 300})
    labels = sheet.labels_in(window)
    plate_labels = [l for l in labels if l.kind == "PL"]
    deck_girders = []
    hanging = [s for s in verticals if abs(max(s.y0, s.y1) - datums.deck_y) < tolerance
               and abs(s.y0 - s.y1) < 400]
    for s in hanging:
        top, bottom = max(s.y0, s.y1), min(s.y0, s.y1)
        # A moulded line stands alone; two lines a plate thickness apart are a drawn part (a bracket).
        if any(other is not s and abs(other.x0 - s.x0) < 20 for other in hanging):
            continue
        label = _nearest([l for l in plate_labels if l.y > datums.tank_top_y], s.x0, top)
        deck_girders.append({"y_m": round(datums.y_m(s.x0), 4), "web_mm": round(top - bottom, 1),
                             "label": label.text if label else None})
    hidden = [s for s in sheet.segments_in(window, HIDDEN_LAYER) if s.vertical]
    floor_stiffeners = sorted({round(datums.y_m(s.x0), 4) for s in hidden if max(s.y0, s.y1) < datums.tank_top_y})
    bulkhead_stiffeners = sorted({round(datums.y_m(s.x0), 4) for s in hidden
                                  if min(s.y0, s.y1) > datums.tank_top_y and max(s.y0, s.y1) > datums.deck_y - 300})
    shells = sheet.polylines_in(window, MOULDED_LAYER)
    shell = [(datums.y_m(x), datums.z_m(y)) for points in shells if len(points) > 8 for x, y in points]

    def plate_between(low_y, high_y):
        found = [l for l in plate_labels if low_y < l.y < high_y and plate_value(l)[1] is None]
        values = [plate_value(l)[0] for l in found]
        return {"mm": _most_common(values), "labels": [l.text for l in found]} if found else None

    profile_texts = [l.text for l in labels if l.kind == "TEXT" and re.match(r"^HP\s*\d", l.text)]
    flat_bars = [l.text for l in labels if l.kind == "FB" and l.y < datums.tank_top_y]
    fcl = []
    for label in labels:
        match = FCL_PATTERN.match(label.text)
        if match:
            fcl.append((float(match.group(1)), datums.y_m(label.x)))
    levels = {}
    for label in labels:
        match = LEVEL_PATTERN.search(label.text)
        if match:
            levels[label.text] = float(match.group(1))
    return SectionMembers(
        datums, (max(s.x1 for s in moulded if s.horizontal) - min(s.x0 for s in moulded if s.horizontal)) / 1000,
        db_girders, sorted(deck_girders, key=lambda g: g["y_m"]), floor_stiffeners, bulkhead_stiffeners, shell,
        plate_between(datums.new_baseline_y - 500, datums.tank_top_y),
        plate_between(datums.tank_top_y, datums.deck_y),
        flat_bars[0] if flat_bars else None, profile_texts[0] if profile_texts else None, fcl, levels)


# --- shell expansion -----------------------------------------------------------------------

@dataclass
class ShellStrakes:
    seams: list[tuple[str, float, str]]  # ('y' | 'z', printed value mm, text), keel upwards
    thickness_mm: list[float | None]  # one per strake (len(seams) + 1)
    labels: list[str]


SEAM_Y = re.compile(r"^(\d{3,4})\s*FCL", re.I)
SEAM_Z = re.compile(r"T\.?T\.?\s*(\d{3,4})\s*O\.?BL", re.I)


def read_shell_strakes(sheet: Sheet, window=SHELL_NEW_PART_WINDOW) -> ShellStrakes:
    """Seams and strake thickness of the new part (strips sorted from the keel up the sheet)."""
    seams = []
    for label in sheet.labels_in(window, "TEXT"):
        y_match, z_match = SEAM_Y.match(label.text), SEAM_Z.search(label.text)
        if y_match:
            seams.append((label.y, "y", float(y_match.group(1)), label.text))
        elif z_match:
            seams.append((label.y, "z", float(z_match.group(1)), label.text))
    seams.sort()
    plates = sorted(sheet.labels_in(window, "PL"), key=lambda l: l.y)
    bounds = [s[0] for s in seams]
    thickness: list[float | None] = [None] * (len(seams) + 1)
    for label in plates:
        strake = sum(1 for b in bounds if label.y > b)
        thickness[strake] = plate_value(label)[0]
    return ShellStrakes([(axis, value, text) for _, axis, value, text in seams], thickness,
                        [f"{l.text} at sheet y {l.y:.0f}" for l in plates])


def read_frame_key(sheet: Sheet, window=SHELL_FRAME_KEY_WINDOW) -> dict[str, dict]:
    """Side-frame key: frame label -> {'profiles': [...], 'plate': mm or None, 'text': key title}."""
    labels = sheet.labels_in(window)
    keys = {}
    for title in (l for l in labels if l.text.upper().startswith("SECTION FRAME")):
        cell = [l for l in labels if title.x - 300 <= l.x <= title.x + 4800 and title.y < l.y <= title.y + 3000]
        profiles = [l.text for l in cell if l.kind == "TEXT" and re.search(r"\d+\s*x\s*\d+", l.text)]
        plates = [plate_value(l)[0] for l in cell if l.kind == "PL"]
        for frame in re.split(r"[,\s]+", title.text.split(":", 1)[1].strip()):
            if frame:
                keys[frame] = {"profiles": profiles, "plate_mm": plates[0] if plates else None, "key": title.text}
    return keys


# --- profile and plan ----------------------------------------------------------------------

@dataclass
class FrameAxis:
    frame0_x: float  # sheet x of frame 0 (from the two-digit labels, which share one text offset)
    row_y: float
    spacings_mm: list[float]  # spacing between neighbouring labels of equal length, per frame


def read_frame_axes(sheet: Sheet, window) -> list[FrameAxis]:
    """Frame-axis rows in a window: rows of frame labels (numbers and the letters A to J)."""
    rows: dict[int, list[Label]] = {}
    for label in sheet.labels_in(window, "TEXT"):
        if re.fullmatch(r"\d{1,2}|[A-J]", label.text) and frame_index(label.text) is not None:
            rows.setdefault(round(label.y / 50), []).append(label)
    axes = []
    for row in rows.values():
        if len(row) < 8:
            continue
        row.sort(key=lambda l: l.x)
        two_digit = [l for l in row if len(l.text) == 2]
        frame0 = statistics.median(l.x - frame_index(l.text) * FRAME_SPACING_MM for l in two_digit)
        spacings = [(b.x - a.x) / (frame_index(b.text) - frame_index(a.text)) for a, b in zip(row, row[1:])
                    if len(a.text) == len(b.text) and frame_index(b.text) > frame_index(a.text)]
        axes.append(FrameAxis(frame0, statistics.median(l.y for l in row), spacings))
    return sorted(axes, key=lambda a: a.row_y)


@dataclass
class PlanReading:
    tank_top_levels: list[tuple[float, float, str]]  # (ship x of the label, level mm above old BL, text)
    tank_top_step_x_m: float | None
    tank_top_plates: list[tuple[float, float, float]]  # (ship x, |y| from the centre line, mm)
    deck_plates: list[tuple[float, float, float]]
    deck_beam_profile: str | None
    long_girder_note: str | None
    girder_thickness: dict[float, dict]  # FCL offset mm -> {'mm', 'basis'}
    axes: dict[str, FrameAxis]


def _ship_x(axis: FrameAxis, x_dxf: float) -> float:
    return (x_dxf - axis.frame0_x) / 1000


def _plan_plates(sheet: Sheet, window, axis: FrameAxis) -> list[tuple[float, float, float]]:
    seam_labels = [l for l in sheet.labels_in(window, "TEXT") if l.text.upper().startswith("3525 FCL")]
    centre_y = statistics.mean(l.y for l in seam_labels) if len(seam_labels) >= 2 else axis.row_y
    return [(_ship_x(axis, l.x), abs(l.y - centre_y) / 1000, plate_value(l)[0])
            for l in sheet.labels_in(window, "PL") if plate_value(l)[1] is None]


def girder_view_thickness(sheet: Sheet, offset_mm: float, tank_top_mm: float) -> dict | None:
    """Plate label of a double-bottom girder from its longitudinal elevation on the plan sheets.

    The view is found by its title ('SECTION AT CENTERLINE' or '... <offset> FCL ...'); inside the
    band up to the next title above, the girder label is the plate label nearest below the
    tank-top text of the section's level ('T.T. 1250 ...').
    """
    titles = [l for l in sheet.labels if l.kind == "TEXT" and (l.text.upper().startswith("SECTION")
                                                                 or l.text.upper().startswith("LONG."))]
    pattern = re.compile("CENTERLINE" if offset_mm == 0 else rf"\b{int(offset_mm)}\s*FCL", re.I)
    for title in sorted((t for t in titles if pattern.search(t.text)), key=lambda t: t.y):
        above = [t.y for t in titles if t.y > title.y + 100 and abs(t.x - title.x) < 30000]
        top = min(above, default=title.y + 10000)
        band = [l for l in sheet.labels if title.y < l.y < top and abs(l.x - title.x) < 30000]
        tank_tops = [l for l in band if l.kind == "TEXT" and re.search(rf"(T\.T\.|TANKTOP)\s*{int(tank_top_mm)}\b", l.text)]
        if not tank_tops:
            continue
        level = tank_tops[0]
        below = [l for l in band if l.kind == "PL" and l.y < level.y and plate_value(l)[1] is None]
        label = _nearest(below, level.x, level.y)
        if label:
            return {"mm": plate_value(label)[0],
                    "basis": f"'{label.text}' nearest below '{level.text}' in view '{title.text}'"}
    return None


def read_plan(sheet: Sheet, tank_top_mm: float, girder_offsets_mm: list[float]) -> PlanReading:
    axes = {"tank_top": read_frame_axes(sheet, PLAN_TANK_TOP_WINDOW)[0],
            "deck": read_frame_axes(sheet, PLAN_DECK_WINDOW)[0]}
    tank_axis = axes["tank_top"]
    texts = sheet.labels_in(PLAN_TANK_TOP_WINDOW, "TEXT")
    levels = []
    for label in texts:
        match = re.search(r"TANKTOP\s*(\d{3,4})", label.text, re.I)
        if match:
            levels.append((_ship_x(tank_axis, label.x), float(match.group(1)), label.text))
    step = next((_ship_x(tank_axis, l.x) for l in texts if l.text.upper() == "STEP"), None)
    notes = [l.text for l in sheet.labels_in(PLAN_DECK_WINDOW, "TEXT")]
    beam = next((m.group(1) for t in notes for m in [re.search(r"DECK BEAMS:?\s*(HP\s*\d+\s*x\s*\d+)", t, re.I)] if m), None)
    girder = next((m.group(0) for t in notes for m in [re.search(r"LONG\. GIRDERS:[^.]*", t, re.I)] if m), None)
    thickness = {}
    for offset in girder_offsets_mm:
        found = girder_view_thickness(sheet, offset, tank_top_mm)
        if found:
            thickness[offset] = found
    return PlanReading(sorted(levels), step, _plan_plates(sheet, PLAN_TANK_TOP_WINDOW, tank_axis),
                       _plan_plates(sheet, PLAN_DECK_WINDOW, axes["deck"]), beam, girder, thickness, axes)


# --- everything -----------------------------------------------------------------------------

@dataclass
class GunnerusReading:
    section_i: SectionMembers
    section_g: SectionMembers
    strakes: ShellStrakes
    frame_key: dict[str, dict]
    plan: PlanReading
    shell_axes: list[FrameAxis]


def read_all(sources: Path) -> GunnerusReading:
    midship = read_sheet(sources / MIDSHIP)
    section_i = read_section(midship, SECTION_I_WINDOW)
    section_g = read_section(midship, SECTION_G_WINDOW)
    shell = read_sheet(sources / SHELL_EXPANSION)
    tank_top_mm = round((section_i.datums.tank_top_y - section_i.datums.old_baseline_y) / 25) * 25
    offsets = sorted({abs(round(y * 1000)) for y in section_i.db_girders_m})
    plan = read_plan(read_sheet(sources / PROFILE_AND_PLAN), tank_top_mm, offsets)
    return GunnerusReading(section_i, section_g, read_shell_strakes(shell), read_frame_key(shell), plan,
                           read_frame_axes(shell, (0, 13000, 42000, 14500)))
