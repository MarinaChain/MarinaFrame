"""Rules that turn the strokes of a midship section sheet into members.

The rules use only what the sheet shows: stroke contacts, stroke lengths, the
printed scale and the printed tables. The order is:

1. Separate the section drawing from the sheet frame, tables and title block.
2. Find plates: long strokes that carry two or more other strokes at interior
   points, long strokes that lie on a plate line (a shell strake), long
   strokes that span between plates without a printed girder height, and
   long free strokes that stand on a plate without a flange.
3. Name each plate by its position. A short vertical piece on a bulkhead
   line with a printed girder height is a girder.
4. Find webs (one end on a plate; a girder when the length matches a printed
   girder height) and flanges (touching a web's free end).
5. Read scantlings from the tables and the drawn lengths; place every member
   in ship coordinates from the printed scale.

"Long" means longer than the tallest printed ordinary stiffener web.

A stroke that no rule explains is an abstention with a reason. No member is
created without a drawn stroke.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math

from .geometry2d import (StrokeIndex, angle_between_deg, direction_deg, is_straight,
                         orientation, point_segment_distance, point_stroke_distance,
                         stroke_distance)
from .model import (Abstention, Member, PlateRow, SectionResult, SheetInput, StiffenerRow,
                    Stroke)
from .tables import read_plate_table, read_scale, read_stiffener_table

# A component that has a stroke this close to the sheet edge is the frame.
SHEET_EDGE_MARGIN_MM = 5.0
# A stroke between plates, or a web, is a girder when its length is within
# this fraction of a printed girder height.
GIRDER_HEIGHT_TOLERANCE = 0.05
# A stroke standing on a plate with a free end is a plate, not a web, when it
# is this many times longer than the tallest printed ordinary stiffener, does
# not match a printed girder height and carries no flange.
FREE_PLATE_LENGTH_FACTOR = 1.5
# A plate is at least this many times longer than the tallest printed
# ordinary stiffener web (girders excluded).
PLATE_MIN_LENGTH_FACTOR = 1.2
# Collinear strokes: direction difference in degrees.
COLLINEAR_ANGLE_DEG = 0.5
# The inner bottom is the lowest deck, if it lies in the lower part of the section.
INNER_BOTTOM_HEIGHT_FRACTION = 0.35

PLATE_TABLE_ROW = {
    "bottom_shell": "Bottom Shell",
    "side_shell": "Side Shell",
    "shell_strake": "Shell Strake",
}
HOST_STIFFENER_ROWS = {
    "Bottom": ("Bot. Stiff.", "Bot. Girder"),
    "Inner_Bottom": ("Inner Bot. Stiff.",),
    "Deck": ("Deck Stiff.", "Deck Girder"),
    "Side_Shell": ("Side Shell Stiff.",),
    "Inner_Side_Shell": ("Inner Side Shell Stiff.",),
    "Longitudinal_Bulkhead": ("Long. BLKHD Stiff.",),
    "Hopper_Pannel_Upper": ("Upper Hopper Stiff.",),
    "Hopper_Pannel_Lower": ("Lower Hopper Stiff.",),
}


@dataclass(frozen=True)
class Contact:
    """An end of stroke ``a`` lies on stroke ``b``."""
    a: int
    a_end: str  # "start" or "end"
    b: int
    at: str  # "start", "end" or "interior" of b


def separate_section(sheet: SheetInput) -> tuple[list[Stroke], list[Stroke]]:
    """Split strokes into the section drawing and the sheet furniture.

    Strokes are joined into connected components. A component is furniture
    when it reaches the sheet edge or when its box holds any text word
    (tables, title block, frame). Everything else is the section.
    """
    strokes = list(sheet.strokes)
    tolerance = sheet.tolerance_mm
    index = StrokeIndex(strokes, tolerance)
    parent = list(range(len(strokes)))
    position = {s.index: i for i, s in enumerate(strokes)}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for stroke in strokes:
        for other in index.near_stroke(stroke):
            if other.index > stroke.index and stroke_distance(stroke, other) <= tolerance:
                parent[find(position[stroke.index])] = find(position[other.index])
    components: dict[int, list[Stroke]] = defaultdict(list)
    for stroke in strokes:
        components[find(position[stroke.index])].append(stroke)

    section, furniture = [], []
    for members in components.values():
        x0 = min(s.bbox[0] for s in members)
        z0 = min(s.bbox[1] for s in members)
        x1 = max(s.bbox[2] for s in members)
        z1 = max(s.bbox[3] for s in members)
        at_edge = (x0 < SHEET_EDGE_MARGIN_MM or z0 < SHEET_EDGE_MARGIN_MM
                   or x1 > sheet.width_mm - SHEET_EDGE_MARGIN_MM
                   or z1 > sheet.height_mm - SHEET_EDGE_MARGIN_MM)
        holds_text = any(x0 <= w.centre[0] <= x1 and z0 <= w.centre[1] <= z1 for w in sheet.words)
        (furniture if at_edge or holds_text else section).extend(members)
    return sorted(section, key=lambda s: s.index), sorted(furniture, key=lambda s: s.index)


class Topology:
    """End-point contacts and collinear overlaps between section strokes."""

    def __init__(self, strokes: list[Stroke], tolerance: float):
        self.strokes = {s.index: s for s in strokes}
        self.tolerance = tolerance
        self.straight = {s.index: is_straight(s, tolerance) for s in strokes}
        index = StrokeIndex(strokes, tolerance)
        self.contacts: list[Contact] = []
        for stroke in strokes:
            for end_name, point in (("start", stroke.start), ("end", stroke.end)):
                for other in index.near_point(point):
                    if other.index == stroke.index:
                        continue
                    if point_stroke_distance(point, other) > tolerance:
                        continue
                    if math.dist(point, other.start) <= tolerance:
                        at = "start"
                    elif math.dist(point, other.end) <= tolerance:
                        at = "end"
                    else:
                        at = "interior"
                    self.contacts.append(Contact(stroke.index, end_name, other.index, at))
        self.collinear: dict[int, set[int]] = defaultdict(set)
        for stroke in strokes:
            if not self.straight[stroke.index]:
                continue
            for other in index.near_stroke(stroke):
                if self.straight[other.index] and self._collinear_overlap(stroke, other):
                    self.collinear[stroke.index].add(other.index)

    def _collinear_overlap(self, s: Stroke, t: Stroke) -> bool:
        if angle_between_deg(direction_deg(s), direction_deg(t)) > COLLINEAR_ANGLE_DEG:
            return False
        if max(point_segment_distance(p, t.start, t.end) for p in (s.start, s.end)) > self.tolerance \
                and max(point_segment_distance(p, s.start, s.end) for p in (t.start, t.end)) > self.tolerance:
            # Neither stroke lies on the other's line segment; test the infinite line.
            if _line_distance(s.start, t) > self.tolerance or _line_distance(s.end, t) > self.tolerance:
                return False
        ux, uz = _unit(t)
        def project(p):
            return (p[0] - t.start[0]) * ux + (p[1] - t.start[1]) * uz
        s0, s1 = sorted((project(s.start), project(s.end)))
        t0, t1 = sorted((project(t.start), project(t.end)))
        return min(s1, t1) - max(s0, t0) > self.tolerance

    def ends_on(self, stroke_index: int, targets: set[int]) -> dict[str, list[Contact]]:
        found: dict[str, list[Contact]] = {"start": [], "end": []}
        for contact in self.contacts:
            if contact.a == stroke_index and contact.b in targets:
                found[contact.a_end].append(contact)
        return found

    def interior_carriers(self) -> dict[int, set[int]]:
        """For each stroke, the strokes that end on its interior (not collinear ones)."""
        carried: dict[int, set[int]] = defaultdict(set)
        for contact in self.contacts:
            if contact.at == "interior" and contact.a not in self.collinear[contact.b]:
                carried[contact.b].add(contact.a)
        return carried


def _unit(stroke: Stroke) -> tuple[float, float]:
    (x0, z0), (x1, z1) = stroke.start, stroke.end
    length = math.hypot(x1 - x0, z1 - z0)
    return (x1 - x0) / length, (z1 - z0) / length


def _line_distance(p, stroke: Stroke) -> float:
    ux, uz = _unit(stroke)
    dx, dz = p[0] - stroke.start[0], p[1] - stroke.start[1]
    return abs(dx * uz - dz * ux)


def read_section(sheet: SheetInput, scale_mm_per_m: float | None = None) -> SectionResult:
    """Read the members of one `Midship Section of Long. Structure` sheet."""
    printed_scale = read_scale(sheet.words)
    scale = printed_scale if printed_scale is not None else scale_mm_per_m
    plate_rows = read_plate_table(sheet.words)
    stiffener_rows = read_stiffener_table(sheet.words)
    section, furniture = separate_section(sheet)
    abstentions: list[Abstention] = []
    if scale is None:
        abstentions.append(Abstention("scale", "no printed scale `1 m = X mm` was found; "
                                      "ship coordinates and drawn scantlings are not given"))
    if not section:
        abstentions.append(Abstention("section", "no stroke group free of text was found"))
        return SectionResult([], abstentions, scale, None, plate_rows, stiffener_rows,
                             sheet.source_kind, 0, len(furniture))

    reader = _SectionReader(section, sheet.tolerance_mm, scale, plate_rows, stiffener_rows)
    members = reader.run()
    abstentions.extend(reader.abstentions)
    return SectionResult(members, abstentions, scale, reader.origin, plate_rows, stiffener_rows,
                         sheet.source_kind, len(section), len(furniture))


class _SectionReader:
    def __init__(self, strokes, tolerance, scale, plate_rows: list[PlateRow],
                 stiffener_rows: list[StiffenerRow]):
        self.strokes = {s.index: s for s in strokes}
        self.tolerance = tolerance
        self.scale = scale
        self.plate_rows = {row.name: row for row in plate_rows}
        self.stiffener_rows = {row.name: row for row in stiffener_rows}
        self.topology = Topology(strokes, tolerance)
        self.abstentions: list[Abstention] = []
        # The centreline is the leftmost drawn point and the baseline the lowest.
        self.origin = (min(s.bbox[0] for s in strokes), min(s.bbox[1] for s in strokes))
        self.section_height = max(s.bbox[3] for s in strokes) - self.origin[1]

    # -- scale helpers -------------------------------------------------
    def ship_length_mm(self, drawing_mm: float) -> float | None:
        return None if self.scale is None else drawing_mm / self.scale * 1000.0

    def to_ship(self, point) -> tuple[float, float]:
        return ((point[0] - self.origin[0]) / self.scale * 1000.0,
                (point[1] - self.origin[1]) / self.scale * 1000.0)

    def tallest_printed_stiffener_mm(self) -> float | None:
        """Tallest printed web height of ordinary stiffeners (girders excluded)."""
        heights = [row.height_mm for row in self.stiffener_rows.values()
                   if row.height_mm and "Girder" not in row.name]
        return max(heights) if heights else None

    # -- main ----------------------------------------------------------
    def run(self) -> list[Member]:
        plates = self.find_plates()
        self.roles = self.name_plates(plates)
        self.plate_hosts: dict[int, str] = {}
        plate_members = {index: self.plate_member(index) for index in sorted(plates)}
        members: list[Member] = list(plate_members.values())
        webs, flanges, spanning_girders = self.find_webs_and_flanges(plates)
        web_members: dict[int, Member] = {}
        for index, host_plate in sorted(webs.items()):
            web_members[index] = self.web_member(index, host_plate, plate_members)
        for index, host_plates in sorted(spanning_girders.items()):
            web_members[index] = self.spanning_girder_member(index, host_plates, plate_members)
        members.extend(web_members[i] for i in sorted(web_members))
        for index, web in sorted(flanges.items()):
            members.append(self.flange_member(index, web_members.get(web) or plate_members[web]))
        explained = {m.stroke.index for m in members}
        for index in sorted(set(self.strokes) - explained):
            self.abstentions.append(Abstention(
                f"stroke:{index}", "stroke is not attached to an identified plate or web",
                self.strokes[index].source))
        if self.scale is not None:
            for member in members:
                self.place(member)
        return members

    # -- plates --------------------------------------------------------
    def find_plates(self) -> set[int]:
        carried = self.topology.interior_carriers()
        min_length = self.min_plate_length_mm()
        plates = {i for i, carriers in carried.items()
                  if len(carriers) >= 2 and self._long_enough(i, min_length)}
        tallest_stiffener = self.tallest_printed_stiffener_mm()
        changed = True
        while changed:
            changed = False
            for index, stroke in self.strokes.items():
                if index in plates:
                    continue
                if self.topology.collinear[index] & plates and self._long_enough(index, min_length):
                    plates.add(index)  # lies on a plate line, e.g. a shell strake
                    changed = True
                    continue
                ends = self.topology.ends_on(index, plates)
                on_start, on_end = bool(ends["start"]), bool(ends["end"])
                length_ship = self.ship_length_mm(stroke.length)
                if on_start and on_end:
                    if self._long_enough(index, min_length) and not self._matches_girder_height(length_ship):
                        plates.add(index)
                        changed = True
                elif (on_start or on_end) and tallest_stiffener is not None and length_ship is not None \
                        and length_ship > FREE_PLATE_LENGTH_FACTOR * tallest_stiffener \
                        and not self._matches_girder_height(length_ship) \
                        and not self._free_end_touches_other(index, plates):
                    plates.add(index)
                    changed = True
        return plates

    def min_plate_length_mm(self) -> float | None:
        """Plates are longer than any printed ordinary stiffener web.

        Crossing stiffeners in a crowded double bottom can end on a short web;
        this bound keeps such a web from being taken as a plate.
        """
        tallest = self.tallest_printed_stiffener_mm()
        return None if tallest is None else PLATE_MIN_LENGTH_FACTOR * tallest

    def _long_enough(self, index: int, min_length: float | None) -> bool:
        if min_length is None:
            return True
        length = self.ship_length_mm(self.strokes[index].length)
        return length is None or length >= min_length

    def _matches_girder_height(self, length_ship: float | None) -> bool:
        if length_ship is None:
            return False
        for row in self.stiffener_rows.values():
            if "Girder" in row.name and row.height_mm:
                if abs(length_ship - row.height_mm) <= GIRDER_HEIGHT_TOLERANCE * row.height_mm:
                    return True
        return False

    def _free_end_touches_other(self, index: int, plates: set[int]) -> bool:
        """True when the end that is not on a plate touches another stroke (a flange)."""
        on_plates = self.topology.ends_on(index, plates)
        on_others = self.topology.ends_on(index, set(self.strokes) - plates - {index})
        return any(on_others[name] for name in ("start", "end") if not on_plates[name])

    # -- webs and flanges ---------------------------------------------
    def find_webs_and_flanges(self, plates: set[int]):
        """Webs stand on a plate with one end; flanges touch a web's free end.

        When a stroke that stands on a plate also carries another such
        stroke's free end (a flange that reaches a plate, for example at the
        bilge), the stroke whose length better matches a printed web height is
        the web and the other is its flange.
        """
        webs: dict[int, int] = {}
        spanning: dict[int, list[int]] = {}
        free_end: dict[int, str] = {}
        for index in self.strokes:
            if index in plates:
                continue
            ends = self.topology.ends_on(index, plates - self.topology.collinear[index])
            if ends["start"] and ends["end"]:
                spanning[index] = [self._preferred_host(ends["start"]), self._preferred_host(ends["end"])]
            elif ends["start"] or ends["end"]:
                end_name = "start" if ends["start"] else "end"
                webs[index] = self._preferred_host(ends[end_name])
                free_end[index] = "end" if end_name == "start" else "start"
        for web in sorted(webs):
            if web not in webs:
                continue
            point = getattr(self.strokes[web], free_end[web])
            for other in sorted(webs):
                if other == web or other not in webs:
                    continue
                if point_stroke_distance(point, self.strokes[other]) > self.tolerance:
                    continue
                loser = other if self._web_height_misfit(web) <= self._web_height_misfit(other) else web
                del webs[loser]
                del free_end[loser]
                if loser == web:
                    break
        # Girder pieces on a bulkhead line have a free end where a flange may sit.
        for index, role in self.roles.items():
            if role == "girder":
                horizontal = {m for m in plates if self.roles.get(m) in ("bottom_shell", "deck")}
                ends = self.topology.ends_on(index, horizontal)
                if bool(ends["start"]) != bool(ends["end"]):
                    free_end[index] = "end" if ends["start"] else "start"
        flanges: dict[int, int] = {}
        taken = set(plates) | set(webs) | set(spanning)
        for web, end_name in sorted(free_end.items()):
            point = getattr(self.strokes[web], end_name)
            for index, stroke in self.strokes.items():
                if index in taken or index in flanges:
                    continue
                if point_stroke_distance(point, stroke) <= self.tolerance:
                    flanges[index] = web
        return webs, flanges, spanning

    def _preferred_host(self, contacts: list[Contact]) -> int:
        """At a plate crossing, a web belongs to the deck, shell or bulkhead, not the hopper."""
        priority = {"deck": 0, "bottom_shell": 1, "longitudinal_bulkhead": 2, "side_shell": 3,
                    "shell_strake": 4, "girder": 5, "hopper_plate": 6}
        return min((c.b for c in contacts), key=lambda b: (priority.get(self.roles.get(b), 9), b))

    def _web_height_misfit(self, index: int) -> float:
        """Smallest relative difference between the stroke length and a printed web height."""
        length = self.ship_length_mm(self.strokes[index].length)
        heights = [row.height_mm for row in self.stiffener_rows.values() if row.height_mm]
        if length is None or not heights:
            return 0.0
        return min(abs(length - h) / h for h in heights)

    # -- naming --------------------------------------------------------
    def name_plates(self, plates: set[int]) -> dict[int, str]:
        """Name plates by position.

        Bottom shell: the longest run along the baseline. Side shell: the
        longest vertical plate at the outermost breadth; other plates on that
        line are shell strakes. Horizontal plates at the highest level are the
        main deck, and at the lowest level in the lower part of the section the
        inner bottom. Other horizontal plates, and vertical plates that meet
        them at a corner, are container-step (hopper panel) plates. Other
        vertical plates are longitudinal bulkheads; inclined plates are hopper
        plates.
        """
        roles: dict[int, str] = {}
        remaining = set(plates)
        baseline = min(self.strokes[i].bbox[1] for i in remaining)
        bottom = max(sorted(remaining), key=lambda i: self._run_at_height(self.strokes[i], baseline))
        roles[bottom] = "bottom_shell"
        remaining.discard(bottom)
        kinds = {i: orientation(self.strokes[i]) if self.topology.straight[i] else "inclined"
                 for i in remaining}
        verticals = [i for i in remaining if kinds[i] == "vertical"]
        if verticals:
            outer_x = max(self.strokes[i].bbox[2] for i in verticals)
            outer = [i for i in verticals if abs(self.strokes[i].bbox[2] - outer_x) <= self.tolerance]
            side = max(outer, key=lambda i: self.strokes[i].length)
            roles[side] = "side_shell"
            for i in outer:
                if i != side:
                    roles[i] = "shell_strake"
        horizontals = [i for i in remaining if kinds[i] == "horizontal"]
        self.main_deck_z = max((self.strokes[i].bbox[1] for i in horizontals), default=None)
        low = [self.strokes[i].bbox[1] for i in horizontals
               if self.strokes[i].bbox[1] - self.origin[1] <= INNER_BOTTOM_HEIGHT_FRACTION * self.section_height]
        self.inner_bottom_z = min(low) if low else None
        steps = set()
        for i in horizontals:
            z = self.strokes[i].bbox[1]
            if any(level is not None and abs(z - level) <= self.tolerance
                   for level in (self.main_deck_z, self.inner_bottom_z)):
                roles[i] = "deck"
            else:
                roles[i] = "hopper_plate"
                steps.add(i)
        for i in remaining - set(roles):
            if kinds[i] == "vertical":
                corners = {c.b for c in self.topology.contacts
                           if c.a == i and c.at != "interior" and c.b in steps}
                corners |= {c.a for c in self.topology.contacts
                            if c.b == i and c.at != "interior" and c.a in steps}
                roles[i] = "hopper_plate" if corners else "longitudinal_bulkhead"
            else:
                roles[i] = "hopper_plate"
        self.roles = roles
        for i in sorted(roles):
            if roles[i] in ("longitudinal_bulkhead", "hopper_plate") and kinds.get(i) == "vertical" \
                    and self._is_girder_piece(i, plates):
                roles[i] = "girder"
        return roles

    def _is_girder_piece(self, index: int, plates: set[int]) -> bool:
        """A vertical plate piece on a bulkhead line with a printed girder height.

        On a bulkhead line the drawing shows the bottom girder in the double
        bottom and the deck girder under the deck as separate strokes, either
        as breaks of the line or drawn over it. Such a piece stands on a
        horizontal plate and its length is a printed girder height.
        """
        if not self._matches_girder_height(self.ship_length_mm(self.strokes[index].length)):
            return False
        horizontal_plates = {m for m in plates - self.topology.collinear[index] - {index}
                             if self.roles.get(m) in ("bottom_shell", "deck")}
        ends = self.topology.ends_on(index, horizontal_plates)
        return bool(ends["start"] or ends["end"])

    def _run_at_height(self, stroke: Stroke, z: float) -> float:
        """Length of the stroke's segments that lie on the horizontal line at z."""
        return sum(math.dist(a, b) for a, b in zip(stroke.points, stroke.points[1:])
                   if abs(a[1] - z) <= self.tolerance and abs(b[1] - z) <= self.tolerance)

    def deck_host(self, index: int) -> str:
        z = self.strokes[index].bbox[1]
        if self.inner_bottom_z is not None and abs(z - self.inner_bottom_z) <= self.tolerance:
            return "Inner_Bottom"
        return "Deck"

    def bulkhead_host(self, index: int) -> str:
        has_inner = "Inner Side Shell" in self.plate_rows
        has_long = "Long. BLKHD" in self.plate_rows
        if has_inner and not has_long:
            return "Inner_Side_Shell"
        if has_long and not has_inner:
            return "Longitudinal_Bulkhead"
        if has_inner and has_long:
            # The inner side shell is the bulkhead line nearest the side shell.
            bulkheads = [m for m, role in self.roles.items() if role == "longitudinal_bulkhead"]
            outer_x = max(self.strokes[m].bbox[0] for m in bulkheads)
            return "Inner_Side_Shell" if abs(self.strokes[index].bbox[0] - outer_x) <= self.tolerance \
                else "Longitudinal_Bulkhead"
        return "Longitudinal_Bulkhead"

    def girder_piece_hosts(self, index: int) -> tuple[str, str]:
        """(host of the girder itself, host of stiffeners standing on it)."""
        touched = {c.b for c in self.topology.contacts if c.a == index} | \
                  {c.a for c in self.topology.contacts if c.b == index}
        on_bottom = any(self.roles.get(m) == "bottom_shell" or
                        (self.roles.get(m) == "deck" and self.deck_host(m) == "Inner_Bottom")
                        for m in touched)
        own = "Bottom" if on_bottom else "Deck"
        x = self.strokes[index].bbox[0]
        line = [m for m, role in self.roles.items() if role == "longitudinal_bulkhead"
                and abs(self.strokes[m].bbox[0] - x) <= self.tolerance]
        return own, (self.bulkhead_host(line[0]) if line else own)

    def hopper_host(self, index: int) -> str:
        """Upper or lower hopper. A container-step deck is upper and its side lower."""
        stroke = self.strokes[index]
        kind = orientation(stroke) if self.topology.straight[index] else "inclined"
        if kind == "horizontal":
            return "Hopper_Pannel_Upper"
        if kind == "vertical":
            return "Hopper_Pannel_Lower"
        upper = stroke.midpoint[1] - self.origin[1] > self.section_height / 2
        return "Hopper_Pannel_Upper" if upper else "Hopper_Pannel_Lower"

    def plate_host(self, index: int, role: str) -> str:
        if role == "bottom_shell":
            return "Bottom"
        if role in ("side_shell", "shell_strake"):
            return "Side_Shell"
        if role == "deck":
            return self.deck_host(index)
        if role == "longitudinal_bulkhead":
            return self.bulkhead_host(index)
        if role == "girder":
            return self.girder_piece_hosts(index)[1]
        return self.hopper_host(index)

    # -- members -------------------------------------------------------
    def plate_member(self, index: int) -> Member:
        role = self.roles[index]
        host = self.plate_host(index, role)
        self.plate_hosts[index] = host
        if role == "girder":
            return self.girder_piece_member(index)
        member = Member(role=role, stroke=self.strokes[index], host=_public_host(host))
        row_name = PLATE_TABLE_ROW.get(member.role)
        if member.role == "deck":
            row_name = "Inner Bot. Deck" if host == "Inner_Bottom" else "Main Deck"
        elif member.role == "longitudinal_bulkhead":
            row_name = "Inner Side Shell" if host == "Inner_Side_Shell" else "Long. BLKHD"
        elif member.role == "hopper_plate":
            row_name = "Upper Hopper" if host == "Hopper_Pannel_Upper" else "Lower Hopper"
        row = self.plate_rows.get(row_name)
        if row is None or row.thickness_mm is None:
            self.abstentions.append(Abstention(
                f"thickness:stroke:{index}",
                f"plate table has no readable row `{row_name}`", member.stroke.source))
        else:
            member.plate_row = row_name
            member.thickness_mm = row.thickness_mm
        return member

    def web_member(self, index: int, host_plate: int, plates: dict[int, Member]) -> Member:
        host = self.plate_hosts[host_plate]
        stroke = self.strokes[index]
        notes = []
        if host == "Bottom":
            plate = self.strokes[host_plate]
            foot = min((stroke.start, stroke.end), key=lambda p: point_stroke_distance(p, plate))
            if foot[1] - self.origin[1] > self.tolerance and orientation(stroke) == "horizontal":
                # A horizontal longitudinal on the bilge arc continues the side shell stiffening.
                host = "Side_Shell"
                notes.append("horizontal web on the bilge arc; read as a side shell stiffener")
        length_ship = self.ship_length_mm(stroke.length)
        role, row = "stiffener_web", None
        candidates = [self.stiffener_rows[n] for n in HOST_STIFFENER_ROWS.get(host, ())
                      if n in self.stiffener_rows and self.stiffener_rows[n].height_mm]
        if candidates and length_ship is not None:
            row = min(candidates, key=lambda r: abs(length_ship - r.height_mm) / r.height_mm)
            if "Girder" in row.name:
                role = "girder"
        member = Member(role=role, stroke=stroke, host=_public_host(host), host_plate=host_plate,
                        measured_length_mm=length_ship, notes=notes)
        if row is None:
            self.abstentions.append(Abstention(
                f"stiffener_row:stroke:{index}",
                f"no stiffener table row with a height for host `{host}`; girder or stiffener "
                "is not established and the web is reported as a stiffener", stroke.source))
        else:
            member.stiffener_row = row.name
            member.thickness_mm = row.thickness_mm
        return member

    def spanning_girder_member(self, index: int, host_plates: list[int], plates) -> Member:
        stroke = self.strokes[index]
        hosts = {self.plate_hosts[i] for i in host_plates}
        host = "Bottom" if hosts & {"Bottom", "Inner_Bottom"} else sorted(hosts)[0]
        row = None
        for name in HOST_STIFFENER_ROWS.get(host, ()):
            candidate = self.stiffener_rows.get(name)
            if candidate and "Girder" in name:
                row = candidate
        member = Member(role="girder", stroke=stroke, host=_public_host(host),
                        host_plate=host_plates[0],
                        measured_length_mm=self.ship_length_mm(stroke.length))
        if row is not None:
            member.stiffener_row = row.name
            member.thickness_mm = row.thickness_mm
        return member

    def girder_piece_member(self, index: int) -> Member:
        own_host, _ = self.girder_piece_hosts(index)
        row_name = "Bot. Girder" if own_host == "Bottom" else "Deck Girder"
        row = self.stiffener_rows.get(row_name)
        return Member(role="girder", stroke=self.strokes[index], host=own_host,
                      stiffener_row=row_name if row else None,
                      thickness_mm=row.thickness_mm if row else None,
                      measured_length_mm=self.ship_length_mm(self.strokes[index].length),
                      notes=["girder in the plane of a bulkhead line; it also carries stiffeners"])

    def flange_member(self, index: int, web: Member) -> Member:
        stroke = self.strokes[index]
        return Member(role="flange", stroke=stroke, host=web.host, web=web.stroke.index,
                      stiffener_row=web.stiffener_row, thickness_mm=web.thickness_mm,
                      measured_length_mm=self.ship_length_mm(stroke.length))

    def place(self, member: Member) -> None:
        points = tuple(self.to_ship(p) for p in member.stroke.points)
        ys = [p[0] for p in points]
        zs = [p[1] for p in points]
        member.ship_points_mm = points
        member.ship_bbox_mm = (min(ys), min(zs), max(ys), max(zs))


def _public_host(host: str) -> str:
    return "Hopper_Pannel" if host.startswith("Hopper_Pannel") else host
