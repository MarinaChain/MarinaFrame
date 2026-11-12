"""The 3D model of the concept survey launch (made up for a demo; see ``__init__``).

Axes and units: metres; x forward from the transom (frame 0), y to port, z up from the baseline.
The layout follows the app's mock "Survey launch" (app/ui/mock/backend.js) so the names look
familiar: hull 24 m x 7.2 m x 3.4 m, deckhouse tier 1 and wheelhouse amidships, tanks in the double
bottom, an aft bulwark and a rudder.

The hull is an analytic offset function: each station is a superellipse bilge under a vertical
side, the keel rises at the transom and in a cut-away forefoot. CadQuery lofts a smooth solid
through the stations. The drawings use the same stations (body plan) and cuts of the model
(waterlines, buttocks), so model and drawings agree by construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

# --- principal particulars (made up) ---------------------------------------------------------
LENGTH_M = 24.0
HALF_BEAM_M = 3.6
DEPTH_M = 3.4
DESIGN_DRAFT_M = 1.6
FRAME_SPACING_M = 0.5
SEA_WATER_T_M3 = 1.025

# The stem: a loft cannot end in a point, so the last section at x = 24 m keeps a very small
# half-breadth.
BOW_END_X_M = LENGTH_M
STEM_HALF_BREADTH_M = 0.04

# --- hull form parameters ---------------------------------------------------------------------
TRANSOM_KEEL_RISE_M = 0.6  # keel height at the transom (an immersed transom)
TRANSOM_RISE_LENGTH_M = 4.0  # the keel reaches the baseline this far forward of the transom
FOREFOOT_START_X_M = 15.0  # the keel starts to rise into the stem here
FOREFOOT_RISE_M = 3.0  # keel height at the stem
FOREFOOT_EXPONENT = 2.2
TRANSOM_HALF_BREADTH_M = 3.2
PARALLEL_FROM_X_M = 6.0  # full beam from here ...
PARALLEL_TO_X_M = 13.0  # ... to here
BOW_TAPER_EXPONENT = 0.75
BILGE_HEIGHT_M = 1.3  # height of the round bilge above the keel amidships
MIDSHIP_FULLNESS = 4.0  # superellipse exponent: 4 is a full round bilge, 1 a straight V
BOW_FULLNESS = 1.3
POINTS_PER_BILGE = 28
POINTS_PER_SIDE = 5

# Loft stations every 1.2 m (half the body-plan station spacing) plus three near the stem.
STATION_SPACING_M = 2.4
LOFT_X_M = tuple([round(1.2 * i, 3) for i in range(20)] + [23.4, 23.8, BOW_END_X_M])
# Body-plan stations: 0 (transom) to 9, and 9 1/2 near the bow.
BODY_PLAN_STATIONS = tuple((f"st{i:02d}" if i == int(i) else f"st{int(i):02d}h", round(i * STATION_SPACING_M, 3))
                           for i in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9.5))

# --- arrangement --------------------------------------------------------------------------------
INNER_BOTTOM_Z_M = 1.0
INNER_BOTTOM_X_M = (9.0, 20.0)  # forward of the engine room to the collision bulkhead
PLATE_M = 0.010  # plate thickness of decks, bulkheads and frames
FRAME_WEB_M = 0.20  # web depth of a ring frame
FRAME_FLOOR_M = 0.25  # floor depth of a ring frame
BULWARK_HEIGHT_M = 1.0
BULWARK_PLATE_M = 0.06
BULKHEADS = (  # (id, label, frame number)
    ("bhd_fr07", "Aft peak bulkhead (fr 7)", 7),
    ("bhd_fr18", "Engine room fwd bulkhead (fr 18)", 18),
    ("bhd_fr33", "Survey lab bulkhead (fr 33)", 33),
    ("bhd_fr40", "Collision bulkhead (fr 40)", 40),
)
WEB_FRAMES = (4, 12, 22, 26, 30, 36, 44)  # frame numbers of the ring frames


@dataclass(frozen=True)
class TankSpec:
    id: str
    name: str
    content: str
    x_m: tuple[float, float]
    y_m: tuple[float, float]  # port is positive
    top_z_m: float
    density_t_m3: float
    bottom_z_m: float = -1.0  # below the keel: the tank reaches the shell
    free_standing: bool = False  # a box tank, not clipped by the hull


TANKS = (
    TankSpec("tank_apt", "Aft peak ballast", "water ballast", (0.3, 3.45), (-4.0, 4.0), 2.6, 1.025),
    TankSpec("tank_fop", "Fuel oil side tank port", "fuel oil", (4.0, 7.8), (2.2, 4.0), 2.8, 0.850, 0.5),
    TankSpec("tank_fos", "Fuel oil side tank starboard", "fuel oil", (4.0, 7.8), (-4.0, -2.2), 2.8, 0.850, 0.5),
    TankSpec("tank_do1", "Diesel oil day tank", "diesel oil", (7.9, 8.9), (-1.9, -0.7), 2.9, 0.840, 1.7, True),
    TankSpec("tank_fw1", "No 1 fresh water", "fresh water", (9.5, 12.5), (-1.5, 1.5), 0.99, 1.000),
    TankSpec("tank_wb1", "No 1 ballast port", "water ballast", (13.0, 16.0), (0.15, 4.0), 0.99, 1.025),
    TankSpec("tank_wb2", "No 1 ballast starboard", "water ballast", (13.0, 16.0), (-4.0, -0.15), 0.99, 1.025),
    TankSpec("tank_fo1", "No 1 fuel oil (double bottom)", "fuel oil", (16.6, 19.9), (-4.0, 4.0), 0.99, 0.850),
    TankSpec("tank_fpt", "Fore peak ballast", "water ballast", (20.05, 23.6), (-4.0, 4.0), 2.6, 1.025),
)
# Machinery (made up): a main engine on its seating, a gearbox, the shaft line and the propeller.
ENGINE_X_M = (4.7, 7.6)
GEARBOX_X_M = (4.15, 4.7)
SHAFT_AFT = (1.75, 0.45)  # (x, z) of the shaft at the propeller
SHAFT_FWD = (4.15, 0.62)  # (x, z) at the gearbox flange
PROPELLER_X_M = 1.55
PROPELLER_RADIUS_M = 0.42


# --- the hull form ----------------------------------------------------------------------------

def keel_height(x: float) -> float:
    """Height of the keel (the lowest point of the section) above the baseline."""
    if x < TRANSOM_RISE_LENGTH_M:
        return TRANSOM_KEEL_RISE_M * (1.0 - x / TRANSOM_RISE_LENGTH_M) ** 2
    if x > FOREFOOT_START_X_M:
        share = (x - FOREFOOT_START_X_M) / (LENGTH_M - FOREFOOT_START_X_M)
        return FOREFOOT_RISE_M * share ** FOREFOOT_EXPONENT
    return 0.0


def deck_half_breadth(x: float) -> float:
    """Half-breadth at the deck edge."""
    if x < PARALLEL_FROM_X_M:
        share = 1.0 - x / PARALLEL_FROM_X_M
        return HALF_BEAM_M - (HALF_BEAM_M - TRANSOM_HALF_BREADTH_M) * share ** 2
    if x > PARALLEL_TO_X_M:
        share = (x - PARALLEL_TO_X_M) / (LENGTH_M - PARALLEL_TO_X_M)
        return max(STEM_HALF_BREADTH_M, HALF_BEAM_M * max(0.0, 1.0 - share ** 2) ** BOW_TAPER_EXPONENT)
    return HALF_BEAM_M


def _forward_share(x: float) -> float:
    """0 aft of amidships, rising to 1 at the stem."""
    return min(1.0, max(0.0, (x - LENGTH_M / 2) / (LENGTH_M / 2)))


def bilge_fullness(x: float) -> float:
    return MIDSHIP_FULLNESS - (MIDSHIP_FULLNESS - BOW_FULLNESS) * _forward_share(x) ** 1.2


def bilge_top(x: float) -> float:
    """Height where the round bilge meets the vertical side. Forward it rises to the deck, so the
    bow sections flare all the way up."""
    keel = keel_height(x)
    amidships = keel + BILGE_HEIGHT_M
    return min(DEPTH_M, amidships + (DEPTH_M - amidships) * _forward_share(x) ** 1.5)


def section_points(x: float, *, inset_m: float = 0.0, floor_m: float = 0.0, top_m: float = DEPTH_M) -> np.ndarray:
    """Starboard half of the station at ``x`` as [[y, z], ...], keel first, y >= 0.

    With ``inset_m`` and ``floor_m`` the curve is the inside of a ring frame: the side moved in
    by ``inset_m``, the keel raised by ``floor_m``, and the top at ``top_m``.
    """
    keel = keel_height(x) + floor_m
    half = deck_half_breadth(x) - inset_m
    top = max(bilge_top(x), keel + 1e-3)
    exponent = bilge_fullness(x)
    angles = np.linspace(0.0, math.pi / 2, POINTS_PER_BILGE)
    # Superellipse (y / half)^n + ((top - z) / (top - keel))^n = 1, sampled by angle.
    y = half * np.sin(angles) ** (2.0 / exponent)
    z = top - (top - keel) * np.cos(angles) ** (2.0 / exponent)
    points = np.column_stack([y, z])
    if top_m - top > 1e-6:
        side_z = np.linspace(top, top_m, POINTS_PER_SIDE + 1)[1:]
        points = np.vstack([points, np.column_stack([np.full_like(side_z, half), side_z])])
    else:
        points = points[points[:, 1] <= top_m + 1e-9]
    return points


def section_area(x: float, z_max: float = DEPTH_M) -> float:
    """Area of the whole station below ``z_max`` (both halves), from the offsets."""
    points = section_points(x)
    z_grid = np.linspace(points[0, 1], min(z_max, points[-1, 1]), 400)
    if z_grid[-1] <= z_grid[0]:
        return 0.0
    y = np.interp(z_grid, points[:, 1], points[:, 0])
    return 2.0 * float(np.trapezoid(y, z_grid))


# --- CadQuery solids ------------------------------------------------------------------------------

def _section_wire(x: float, points: np.ndarray):
    """A closed wire: one spline from the port deck edge through the keel to the starboard deck
    edge, and a straight deck line back."""
    import cadquery as cq

    starboard = [cq.Vector(x, -y, z) for y, z in points[1:]]
    port = [cq.Vector(x, y, z) for y, z in points[1:]][::-1]
    keel = cq.Vector(x, 0.0, points[0, 1])
    spline = cq.Edge.makeSpline(port + [keel] + starboard)
    deck = cq.Edge.makeLine(starboard[-1], port[0])
    return cq.Wire.assembleEdges([spline, deck])


def hull_solid():
    """The moulded hull: a loft through the stations, closed by the transom, the deck and a
    narrow stem face."""
    import cadquery as cq

    wires = [_section_wire(x, section_points(x)) for x in LOFT_X_M]
    return cq.Solid.makeLoft(wires, ruled=False)


def _box(x0, x1, y0, y1, z0, z1):
    import cadquery as cq

    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def _plan_prism(points_xy, z0: float, z1: float):
    """A prism of a plan polygon [[x, y], ...] from z0 to z1."""
    import cadquery as cq

    wire = cq.Wire.makePolygon([cq.Vector(x, y, z0) for x, y in points_xy], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), cq.Vector(0, 0, z1 - z0))


def _profile_prism(points_xz, y0: float, y1: float):
    """A prism of a profile polygon [[x, z], ...] from y0 to y1."""
    import cadquery as cq

    wire = cq.Wire.makePolygon([cq.Vector(x, y0, z) for x, z in points_xz], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), cq.Vector(0, y1 - y0, 0))


def _closed_section(points: np.ndarray) -> list[tuple[float, float]]:
    """Both halves of a station as one polygon [(y, z), ...] (port side first, keel once)."""
    port = [(float(y), float(z)) for y, z in points[::-1]]
    starboard = [(-float(y), float(z)) for y, z in points[1:]]
    return port + starboard


def _section_plate(x: float, outer: np.ndarray, inner: np.ndarray | None, thickness: float):
    """A transverse plate at ``x``: the station polygon (with a hole for a ring frame)."""
    import cadquery as cq

    def wire(points):
        return cq.Wire.makePolygon([cq.Vector(x, y, z) for y, z in _closed_section(points)], close=True)

    face = cq.Face.makeFromWires(wire(outer), [wire(inner)] if inner is not None else [])
    return cq.Solid.extrudeLinear(face, cq.Vector(thickness, 0, 0))


def frame_x(frame: float) -> float:
    return frame * FRAME_SPACING_M


def frame_label(x: float) -> str:
    """'fr 14' for x = 7.0 m; half frames as 'fr 14.5'."""
    frame = x / FRAME_SPACING_M
    return f"fr {frame:g}" if abs(frame * 2 - round(frame * 2)) < 1e-6 else f"fr {frame:.1f}"


# --- parts ---------------------------------------------------------------------------------------

@dataclass
class Argument:
    value: object  # number, [low, high] or a short text
    source: str  # "traced" (drawn on a concept sheet) or "guessed"
    basis: str


@dataclass
class Part:
    id: str
    op: str  # ship-cad op: hull, deck, deckhouse, bulwark, appendage, tank, bulkhead, frame, other
    label: str
    solid: object  # cadquery Shape, metres
    arguments: dict[str, Argument]
    # Where the part is drawn: [(sheet key, view)], resolved to pixel boxes by sheets.py.
    drawn_in: list[tuple[str, str]]
    guess: str | None = None  # the guess method, when an argument is guessed
    guess_parts: list[str] = field(default_factory=list)  # other parts the guess used
    tank: TankSpec | None = None


def _bulwark(x_from: float, x_to: float, closed_end_x: float, height: float):
    """A U-shaped bulwark plate along the deck edge between x_from and x_to, closed across the
    vessel at ``closed_end_x`` (the transom or the bow)."""
    step = 0.25
    inset = BULWARK_PLATE_M
    open_end_x = x_to if closed_end_x == x_from else x_from
    toward_closed = 1.0 if closed_end_x > open_end_x else -1.0
    # Stations from the open end to the closed end. The inside stops one plate short of the
    # closed end, or where the deck becomes too narrow for an inside face (at the bow).
    count = max(2, int(abs(closed_end_x - open_end_x) / step) + 1)
    outer_xs = np.linspace(open_end_x, closed_end_x, count)
    inner_end_x = closed_end_x - toward_closed * inset
    inner_xs = [x for x in np.linspace(open_end_x, inner_end_x, count)
                if deck_half_breadth(x) - inset > 0.03]
    outer_port = [(float(x), deck_half_breadth(x)) for x in outer_xs]
    outer_starboard = [(x, -y) for x, y in outer_port[::-1]]
    inner_starboard = [(float(x), -(deck_half_breadth(x) - inset)) for x in inner_xs]
    inner_port = [(x, -y) for x, y in inner_starboard[::-1]]
    # Port outside to the closed end, across, starboard outside back to the open end, then the
    # inside the other way round.
    polygon = outer_port + outer_starboard + inner_starboard + inner_port
    return _plan_prism(polygon, DEPTH_M, DEPTH_M + height)


def build_parts() -> list[Part]:
    """Every part of the concept vessel, built in CadQuery (metres)."""
    import cadquery as cq

    hull = hull_solid()
    ga, lines, tank_plan = "ga", "lines", "tanks"
    drawn = "Drawn on the concept {sheet} ({view})"

    def traced(value, sheet, view):
        return Argument(value, "traced", drawn.format(sheet=SHEET_NAMES_SHORT[sheet], view=view))

    parts = [Part("hull", "hull", "Hull", hull, {
        "length": traced(LENGTH_M, lines, "profile"),
        "beam": traced(2 * HALF_BEAM_M, lines, "body plan"),
        "depth": traced(DEPTH_M, lines, "body plan"),
    }, [(lines, "body plan"), (lines, "profile"), (lines, "plan")])]

    deck = hull.intersect(_box(-1, LENGTH_M + 1, -5, 5, DEPTH_M - PLATE_M, DEPTH_M))
    parts.append(Part("main_deck", "deck", "Main deck", deck, {
        "top": traced(DEPTH_M, ga, "profile"), "outline": traced("deck edge", ga, "plan"),
    }, [(ga, "profile"), (ga, "plan")]))

    x0, x1 = INNER_BOTTOM_X_M
    inner_bottom = hull.intersect(_box(x0, x1, -5, 5, INNER_BOTTOM_Z_M - PLATE_M, INNER_BOTTOM_Z_M))
    parts.append(Part("inner_bottom", "deck", "Inner bottom (tank top)", inner_bottom, {
        "level": traced(INNER_BOTTOM_Z_M, tank_plan, "profile"), "extent": traced([x0, x1], tank_plan, "profile"),
    }, [(tank_plan, "profile")]))

    house = cq.Workplane().add(_box(9.0, 17.0, -2.6, 2.6, DEPTH_M, 5.8)).edges("|Z").fillet(0.25).val()
    parts.append(Part("house_t1", "deckhouse", "Deckhouse tier 1 (survey lab)", house, {
        "outline": traced([[9.0, -2.6], [17.0, -2.6], [17.0, 2.6], [9.0, 2.6]], ga, "plan"),
        "height": traced([DEPTH_M, 5.8], ga, "profile"),
    }, [(ga, "profile"), (ga, "plan")]))

    wheelhouse = _profile_prism([(11.0, 5.8), (15.5, 5.8), (15.0, 8.2), (11.0, 8.2)], -2.0, 2.0)
    parts.append(Part("wheelhouse", "deckhouse", "Wheelhouse", wheelhouse, {
        "height": traced([5.8, 8.2], ga, "profile"),
        "outline": Argument("tier 1 breadth less 0.6 m a side", "guessed",
                            "The wheelhouse plan is not drawn; the breadth is taken from the tier below"),
    }, [(ga, "profile")], guess="outline: the wheelhouse plan is not drawn; its breadth is taken from deckhouse tier 1",
        guess_parts=["house_t1"]))

    parts.append(Part("aft_bulwark", "bulwark", "Aft bulwark", _bulwark(0.0, 9.0, 0.0, BULWARK_HEIGHT_M), {
        "height": traced([DEPTH_M, DEPTH_M + BULWARK_HEIGHT_M], ga, "profile"),
        "outline": traced("deck edge aft of the house", ga, "plan"),
    }, [(ga, "profile"), (ga, "plan")]))
    parts.append(Part("fwd_bulwark", "bulwark", "Forecastle bulwark",
                      _bulwark(17.0, BOW_END_X_M, BOW_END_X_M, BULWARK_HEIGHT_M + 0.2), {
        "height": traced([DEPTH_M, DEPTH_M + BULWARK_HEIGHT_M + 0.2], ga, "profile"),
        "outline": traced("deck edge forward of the house", ga, "plan"),
    }, [(ga, "profile"), (ga, "plan")]))

    for part_id, label, frame in BULKHEADS:
        x = frame_x(frame)
        plate = _section_plate(x, section_points(x), None, PLATE_M)
        parts.append(Part(part_id, "bulkhead", label, plate, {"position": traced(x, tank_plan, "profile")},
                          [(tank_plan, "profile"), (ga, "profile")]))

    for frame in WEB_FRAMES:
        x = frame_x(frame)
        outer = section_points(x)
        inner = section_points(x, inset_m=FRAME_WEB_M, floor_m=FRAME_FLOOR_M, top_m=DEPTH_M - FRAME_WEB_M)
        ring = _section_plate(x, outer, inner, PLATE_M)
        parts.append(Part(f"web_fr{frame:02d}", "frame", f"Web frame fr {frame}", ring,
                          {"position": traced(x, ga, "profile")}, [(ga, "profile")]))

    girder = hull.intersect(_box(x0, x1, -PLATE_M / 2, PLATE_M / 2, -1.0, INNER_BOTTOM_Z_M))
    parts.append(Part("centre_girder", "other", "Centre girder", girder,
                      {"extent": traced([x0, x1], tank_plan, "profile")}, [(tank_plan, "profile")]))

    rudder = _profile_prism([(0.25, -0.35), (1.15, -0.35), (1.15, 0.75), (0.25, 0.75)], -0.07, 0.07)
    parts.append(Part("rudder", "appendage", "Rudder", rudder, {
        "outline": traced("4 points", ga, "profile")}, [(ga, "profile")]))
    skeg = _profile_prism([(2.2, -0.35), (2.2, 0.3), (9.5, 0.05), (9.5, 0.0)], -0.10, 0.10)
    parts.append(Part("skeg", "appendage", "Skeg", skeg, {"outline": traced("4 points", ga, "profile")},
                      [(ga, "profile")]))
    gondola = cq.Workplane().add(_box(14.0, 16.5, -0.25, 0.25, -0.45, 0.10)).edges("|Y").fillet(0.2).val()
    parts.append(Part("sonar_gondola", "appendage", "Survey sonar gondola", gondola, {
        "outline": traced("4 points", ga, "profile")}, [(ga, "profile")]))

    legs = [_box(0.45, 0.70, y - 0.12, y + 0.12, DEPTH_M, 7.3) for y in (-2.45, 2.45)]
    a_frame = cq.Compound.makeCompound(legs + [_box(0.40, 0.75, -2.6, 2.6, 7.05, 7.35)])
    parts.append(Part("a_frame", "other", "Stern A-frame", a_frame, {
        "height": traced([DEPTH_M, 7.35], ga, "profile")}, [(ga, "profile"), (ga, "plan")]))
    mast_post = cq.Solid.makeCylinder(0.09, 3.4, cq.Vector(13.2, 0, 8.2))
    yard = _box(13.12, 13.28, -1.2, 1.2, 10.75, 10.85)
    parts.append(Part("mast", "other", "Survey mast", cq.Compound.makeCompound([mast_post, yard]), {
        "height": traced([8.2, 11.6], ga, "profile")}, [(ga, "profile")]))

    parts += machinery_parts(ga, traced)

    for spec in TANKS:
        x0_t, x1_t = spec.x_m
        y0_t, y1_t = spec.y_m
        box = _box(x0_t, x1_t, y0_t, y1_t, spec.bottom_z_m, spec.top_z_m)
        solid = box if spec.free_standing else hull.intersect(box)
        arguments = {"outline": traced([[x0_t, y0_t], [x1_t, y1_t]], tank_plan, "plan"),
                     "height": traced([max(0.0, spec.bottom_z_m), spec.top_z_m], tank_plan, "profile")}
        guess = None
        if spec.id == "tank_fw1":
            arguments["height"] = Argument([0.0, spec.top_z_m], "guessed",
                                           "The tank top is not drawn for this tank; the inner bottom height is used")
            guess = "height: the tank top is not drawn; taken as the inner-bottom height"
        parts.append(Part(spec.id, "tank", spec.name, solid, arguments,
                          [(tank_plan, "plan"), (tank_plan, "profile"), (tank_plan, "table")],
                          guess=guess, guess_parts=["inner_bottom"] if guess else [], tank=spec))
    return parts


def machinery_parts(ga: str, traced) -> list[Part]:
    """Main engine, gearbox, shaft line and propeller of the engine room (frames 7 to 18)."""
    import cadquery as cq

    x0, x1 = ENGINE_X_M
    engine_box = cq.Workplane().add(_box(x0, x1, -0.55, 0.55, 0.55, 1.75)).edges("|X").fillet(0.12).val()
    rocker_cover = _box(x0 + 0.2, x1 - 0.2, -0.35, 0.35, 1.75, 2.05)
    seatings = [_box(x0 - 0.1, x1 + 0.1, y - 0.06, y + 0.06, 0.25, 0.55) for y in (-0.45, 0.45)]
    engine = cq.Compound.makeCompound([engine_box, rocker_cover, *seatings])
    g0, g1 = GEARBOX_X_M
    gearbox = _box(g0, g1, -0.4, 0.4, 0.35, 1.15)
    (xa, za), (xf, zf) = SHAFT_AFT, SHAFT_FWD
    length = math.hypot(xf - xa, zf - za)
    shaft = cq.Solid.makeCylinder(0.07, length, cq.Vector(xa, 0, za), cq.Vector(xf - xa, 0, zf - za))
    hub = cq.Solid.makeCylinder(0.13, 0.35, cq.Vector(PROPELLER_X_M - 0.1, 0, za), cq.Vector(1, 0, 0))
    disc = cq.Solid.makeCylinder(PROPELLER_RADIUS_M, 0.08, cq.Vector(PROPELLER_X_M, 0, za), cq.Vector(1, 0, 0))
    propeller = cq.Compound.makeCompound([hub, disc])
    return [
        Part("main_engine", "other", "Main engine", engine, {
            "outline": traced([[x0, 0.55], [x1, 2.05]], ga, "profile")}, [(ga, "profile")]),
        Part("gearbox", "other", "Gearbox", gearbox, {"outline": traced([[g0, 0.35], [g1, 1.15]], ga, "profile")},
             [(ga, "profile")]),
        Part("shaft_line", "other", "Shaft line", shaft, {"line": traced([[xa, za], [xf, zf]], ga, "profile")},
             [(ga, "profile")]),
        Part("propeller", "appendage", "Propeller", propeller, {
            "diameter": traced(2 * PROPELLER_RADIUS_M, ga, "profile")}, [(ga, "profile")]),
    ]


SHEET_NAMES_SHORT = {"ga": "general arrangement", "lines": "lines plan", "tanks": "tank arrangement"}


# --- meshes and volumes ---------------------------------------------------------------------------

def mesh_of(solid, tolerance_m: float = 0.002, angular_rad: float = 0.2) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (metres) and triangle indices of a solid."""
    vertices, triangles = solid.tessellate(tolerance_m, angular_rad)
    return (np.array([[v.x, v.y, v.z] for v in vertices], dtype=float),
            np.array(triangles, dtype=np.int64).reshape(-1, 3))


def triangles_of(solid, tolerance_m: float = 0.002, angular_rad: float = 0.2) -> np.ndarray:
    """A closed triangle soup (n, 3, 3) in metres, as ``vessel_reconstruction.tanks`` takes it."""
    vertices, triangles = mesh_of(solid, tolerance_m, angular_rad)
    return vertices[triangles]


def bbox_of(solid) -> dict:
    """Tight box of a solid from its mesh (OCC bounding boxes are padded by a tolerance)."""
    vertices, _ = mesh_of(solid)
    return {"min": vertices.min(axis=0).tolist(), "max": vertices.max(axis=0).tolist()}


def waterplane_properties(hull, draft_m: float) -> dict:
    """Area, centroid and second moments of the waterplane at ``draft_m`` (OCC surface props)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    underwater = hull.intersect(_box(-1, LENGTH_M + 1, -5, 5, -1, draft_m))
    faces = [face for face in underwater.Faces()
             if abs(face.Center().z - draft_m) < 1e-6 and face.geomType() == "PLANE"]
    area = 0.0
    moment_x = 0.0
    i_transverse = 0.0
    i_longitudinal_origin = 0.0
    for face in faces:
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face.wrapped, props)
        face_area = props.Mass()
        centre = props.CentreOfMass()
        inertia = props.MatrixOfInertia()
        area += face_area
        moment_x += face_area * centre.X()
        # Second moment about the centreline (y = 0) and about x = 0 (parallel axis theorem).
        i_transverse += inertia.Value(1, 1) + face_area * centre.Y() ** 2
        i_longitudinal_origin += inertia.Value(2, 2) + face_area * centre.X() ** 2
    lcf = moment_x / area
    box = underwater.BoundingBox()
    return {"area_m2": area, "lcf_m": lcf, "i_transverse_m4": i_transverse,
            "i_longitudinal_m4": i_longitudinal_origin - area * lcf ** 2,
            "waterline_length_m": box.xlen, "waterline_breadth_m": box.ylen, "underwater": underwater}


def hydrostatics_at(hull, draft_m: float) -> dict:
    """Hydrostatic particulars of the moulded hull at one level draft (sea water)."""
    plane = waterplane_properties(hull, draft_m)
    underwater = plane.pop("underwater")
    volume = underwater.Volume()
    centre = underwater.Center()
    bm = plane["i_transverse_m4"] / volume
    bm_long = plane["i_longitudinal_m4"] / volume
    length, breadth = plane["waterline_length_m"], plane["waterline_breadth_m"]
    displacement = SEA_WATER_T_M3 * volume
    return {
        "draft_m": draft_m,
        "volume_m3": volume,
        "displacement_t": displacement,
        "lcb_m": centre.x,
        "kb_m": centre.z,
        "bm_m": bm,
        "km_m": centre.z + bm,
        "waterplane_area_m2": plane["area_m2"],
        "lcf_m": plane["lcf_m"],
        "tpc_t_cm": plane["area_m2"] * SEA_WATER_T_M3 / 100.0,
        "mct_1cm_tm": displacement * bm_long / (100.0 * length),
        "waterline_length_m": length,
        "waterline_breadth_m": breadth,
        "block_coefficient": volume / (length * breadth * draft_m),
        "waterplane_coefficient": plane["area_m2"] / (length * breadth),
    }


HYDROSTATIC_DRAFTS_M = (0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2)


def hydrostatic_table(hull) -> list[dict]:
    return [hydrostatics_at(hull, draft) for draft in HYDROSTATIC_DRAFTS_M]
