"""From a GA reading to an estimated 3D arrangement: input checks, extents and the estimated hull.

This module does no reading. Its input is a GA reading (``marinaframe.ga_reading.v1``, written
by the GA reader) whose spaces carry an ``extent`` block, with the principal particulars and,
when read, the frame spacings. The schema is in docs/GA_ARRANGEMENT_INPUT.md.

It gives:

- ``load_input``: the checked input (items with extents in ship metres, the particulars used);
- ``hull_table``: an ESTIMATED hull as a station table in the prior-form family of
  ``form_fit`` (``section_shape``), sized from the read particulars and, when given, the read
  deck outline and profile outline. There is no lines plan, so every row is ``prior``;
- ``item_box``: the box of each item in ship metres, with a status for each of its extents
  (``read`` when the reading gave it, ``guessed`` when a rule here filled it in).

Axes: metres; x forward from the aft perpendicular (frame 0), y to port, z up from the baseline.
Nothing here is approved; ``engineering_approved`` stays false.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

from .form_fit import section_shape
from .vessel_model import FITTED_ROW_SAMPLES, StationRow, VesselTable, waterline_grid

READING_SCHEMA = "marinaframe.ga_reading.v1"
HULL_LABEL = "Estimated hull, no lines plan"
HULL_METHOD = "ga_prior_form_v1"

# Item kinds (the GA reader's vocabulary). Below-deck spaces are cut by the hull; the others
# stand on or above the deck.
SPACE_KINDS = ("cargo_hold", "cargo_tank", "slop_tank", "ballast_tank", "fuel_tank", "other_tank",
               "engine_room", "other_space")
DECK_KINDS = ("accommodation_deck", "cargo_hatch", "cargo_crane")
KINDS = SPACE_KINDS + DECK_KINDS
TANK_KINDS = ("cargo_tank", "slop_tank", "ballast_tank", "fuel_tank", "other_tank")
# "measured_from_scale": the reader measured the value on the drawing with its frame scale (not a
# printed value). The arrangement treats it as read: it came from drawn ink, not from a rule here.
MEASURED = "measured_from_scale"
STATUSES = ("read", MEASURED, "guessed")
SIDES = ("both", "port", "starboard", "centre")

# --- rules that fill a missing extent (each one is labelled "guessed" where it is used) -------
# A deckhouse tier without a breadth: the ship's breadth less this margin on each side.
HOUSE_SIDE_MARGIN_M = 1.0
# A tier without heights: this height per tier.
TIER_HEIGHT_M = 2.8
# A hatch without a coaming height, and a crane without a post height (share of the breadth).
COAMING_HEIGHT_M = 1.5
CRANE_POST_SHARE_OF_BREADTH = 0.6
CRANE_POST_RADIUS_M = 1.1
# A "centre" item without a breadth: this share of the breadth about the centreline.
CENTRE_SHARE_OF_BREADTH = 0.3

# --- estimated hull form (prior family of form_fit; no lines plan) ------------------------------
# Plan shape of the deck edge when no deck outline was read: full breadth over the parallel
# body (a share of the hull length), narrowing to TRANSOM_SHARE of the half-breadth at the aft
# end and to a point at the stem. Full-form cargo ships (bulk carriers, tankers) have a long
# parallel body; these shares are typical of them, not measured.
PARALLEL_FROM_SHARE = 0.22
PARALLEL_TO_SHARE = 0.70
TRANSOM_SHARE = 0.80
BOW_TAPER_EXPONENT = 0.55
# Section form: fullness p and bottom flat f0 of section_shape run from the ends (fine, V) to
# the parallel body (wall-sided with a bilge: p = MID_FULLNESS, flat MID_FLAT). WEIGHT_FROM is
# the deck half-breadth share below which a station counts as an end station.
MID_FULLNESS = 7.0
END_FULLNESS = 1.4
MID_FLAT = 0.82
WEIGHT_FROM = 0.55
WEIGHT_EXPONENT = 1.5
# The keel rises over the aft STERN_RISE_SHARE of the length to STERN_RISE_SHARE_OF_DEPTH of the
# depth (a cruiser stern above the propeller); without a profile outline this is a guess.
STERN_RISE_SHARE = 0.05
STERN_RISE_SHARE_OF_DEPTH = 0.45
# Hull ends when only LBP is known: LOA = LBP * (1 + OVERHANG_SHARE), split aft/forward.
OVERHANG_SHARE = 0.04
AFT_OVERHANG_PART = 0.4
# Smallest half-breadth of a loft station, as a share of the half-breadth (a station is never a line).
MIN_BREADTH_SHARE = 0.04
STATION_COUNT = 31


class InputError(ValueError):
    """The arrangement input cannot be used (missing breadth or depth, unknown kind ...)."""


@dataclass
class Box:
    """An item's extents in ship metres, with where each came from."""
    x: tuple[float, float]
    y: tuple[float, float]
    z: tuple[float, float]
    status: dict  # {"x": "read"|"guessed", "y": ..., "z": ...}
    basis: dict = field(default_factory=dict)  # why a guessed extent has its value

    @property
    def guessed(self) -> list[str]:
        """Axes whose extent is a guess (by the reader or by a rule here)."""
        return [axis for axis in ("x", "y", "z") if self.status[axis] == "guessed"]


@dataclass
class Item:
    id: str
    kind: str
    label: str
    side: str
    extent: dict
    source_record: dict
    status: str = "read"


@dataclass
class ArrangementInput:
    case_id: str
    ship_type: str | None
    particulars: dict  # name -> {"value", "status", "source_record"?}
    items: list[Item]
    skipped: list[dict]  # spaces without an extent (or with a kind not built), and why
    frames: list[dict]  # [{"from_frame", "to_frame", "spacing_mm"}]
    hull_outline: dict | None
    sheet: dict | None
    test_fixture: bool = False

    def value(self, name: str) -> float | None:
        entry = self.particulars.get(name) or {}
        value = entry.get("value")
        return float(value) if isinstance(value, (int, float)) and entry.get("status") in STATUSES else None


# ------------------------------------------------------------------ frames

def frame_to_m(frame: float, spacings: list[dict]) -> float:
    """Distance from frame 0 to ``frame`` (metres) with the spacing table [{from_frame, to_frame,
    spacing_mm}]. A frame outside every span uses the spacing of the nearest span; negative frames
    lie aft of frame 0."""
    if not spacings:
        raise InputError("frame positions need a frame-spacing table")
    spans = sorted(((float(s["from_frame"]), float(s["to_frame"]), float(s["spacing_mm"]) / 1000.0)
                    for s in spacings), key=lambda span: span[0])
    for low, high, _ in spans:
        if high <= low:
            raise InputError(f"frame span {low}..{high} is empty")

    def spacing_at(f: float) -> float:
        for low, high, spacing in spans:
            if low <= f < high:
                return spacing
        return spans[0][2] if f < spans[0][0] else spans[-1][2]

    # Integrate the spacing over unit frames (spans start and end on whole frames).
    sign = 1.0 if frame >= 0 else -1.0
    whole = math.floor(abs(frame))
    total = 0.0
    for step in range(whole):
        f = step if sign > 0 else -step - 1
        total += spacing_at(f)
    rest = abs(frame) - whole
    total += rest * spacing_at(whole if sign > 0 else -whole - 1)
    return sign * total


def _pair(value, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(isinstance(v, (int, float)) for v in value):
        raise InputError(f"{name} must be [low, high] numbers")
    low, high = float(value[0]), float(value[1])
    if high < low:
        low, high = high, low
    if high - low <= 0:
        raise InputError(f"{name} is empty")
    return low, high


def x_range_m(extent: dict, spacings: list[dict]) -> tuple[float, float]:
    """The item's x extent in metres from ``x_m`` or ``frames``."""
    if extent.get("x_m") is not None:
        return _pair(extent["x_m"], "x_m")
    if extent.get("frames") is not None:
        low, high = _pair(extent["frames"], "frames")
        return frame_to_m(low, spacings), frame_to_m(high, spacings)
    raise InputError("an extent needs x_m or frames")


# ------------------------------------------------------------------ input

def _particular(entry) -> dict:
    if isinstance(entry, dict):
        return entry
    return {"value": entry, "status": "read" if entry is not None else "unknown"}


def load_input(reading: dict) -> ArrangementInput:
    """Check a GA reading with extents and return the items that can be built.

    A space without an ``extent`` is skipped and listed (a GA reading without extents builds the
    hull only). Breadth and depth are required: the hull is sized from them."""
    if reading.get("schema") != READING_SCHEMA:
        raise InputError(f"schema must be {READING_SCHEMA}")
    if reading.get("engineering_approved") not in (False, None):
        raise InputError("engineering_approved must be false")
    particulars = {name: _particular(entry) for name, entry in (reading.get("particulars") or {}).items()}
    frames = list((reading.get("frames") or {}).get("spacings") or [])
    items, skipped = [], []
    for space in reading.get("spaces") or []:
        kind, extent = space.get("kind"), space.get("extent")
        reason = None
        if kind not in KINDS:
            reason = f"kind {kind!r} is not built"
        elif not isinstance(extent, dict):
            reason = "no extent"
        if reason:
            skipped.append({"id": space.get("id"), "label": space.get("label"), "reason": reason})
            continue
        side = extent.get("side", "both")
        if side not in SIDES:
            raise InputError(f"{space.get('id')}: side must be one of {SIDES}")
        for axis, status in (extent.get("status") or {}).items():
            if status not in STATUSES:
                raise InputError(f"{space.get('id')}: status of {axis} must be one of {STATUSES}")
        items.append(Item(id=str(space["id"]), kind=kind, label=str(space.get("label") or kind), side=side,
                          extent=extent, source_record=space.get("source_record") or {},
                          status=space.get("status", "read")))
    ship_type = reading.get("ship_type")
    if isinstance(ship_type, dict):
        ship_type = ship_type.get("value")
    data = ArrangementInput(case_id=str(reading.get("case_id") or "unnamed"), ship_type=ship_type,
                            particulars=particulars, items=items, skipped=skipped, frames=frames,
                            hull_outline=reading.get("hull_outline"),
                            sheet=(reading.get("sources") or {}).get("ga"),
                            test_fixture=reading.get("test_fixture") is True)
    if data.value("breadth_m") is None or data.value("depth_m") is None:
        raise InputError("breadth_m and depth_m must be read or guessed values: the hull is sized from them")
    if data.value("lbp_m") is None and data.value("loa_m") is None:
        raise InputError("lbp_m or loa_m is needed")
    return data


# ------------------------------------------------------------------ the estimated hull

@dataclass
class HullSize:
    x_aft_m: float
    x_fwd_m: float
    half_beam_m: float
    depth_m: float
    basis: dict


def hull_size(data: ArrangementInput) -> HullSize:
    """Hull ends, half-breadth and depth from the particulars (and the outline when read)."""
    breadth, depth = data.value("breadth_m"), data.value("depth_m")
    lbp, loa = data.value("lbp_m"), data.value("loa_m")
    basis = {"breadth": data.particulars["breadth_m"].get("status"), "depth": data.particulars["depth_m"].get("status")}
    outline = (data.hull_outline or {}).get("profile_xz_m")
    if outline:
        xs = [float(p[0]) for p in outline]
        return HullSize(min(xs), max(xs), breadth / 2, depth, {**basis, "ends": "profile outline"})
    if lbp is not None and loa is not None and loa >= lbp:
        overhang = loa - lbp
        basis["ends"] = "LOA and LBP"
    else:
        length = lbp if lbp is not None else loa / (1 + OVERHANG_SHARE)
        lbp = length
        overhang = OVERHANG_SHARE * length
        basis["ends"] = f"guessed: overhang {OVERHANG_SHARE:.0%} of LBP"
    return HullSize(-AFT_OVERHANG_PART * overhang, lbp + (1 - AFT_OVERHANG_PART) * overhang, breadth / 2, depth, basis)


def deck_half_breadth(x: float, size: HullSize, outline: list | None = None) -> float:
    """Half-breadth at the deck edge: from the read deck outline [[x, hb], ...] when given,
    else the prior plan shape (parallel body, transom, tapered bow)."""
    if outline:
        points = np.asarray(sorted(outline), dtype=float)
        value = float(np.interp(x, points[:, 0], points[:, 1], left=points[0, 1], right=0.0))
        return max(value, MIN_BREADTH_SHARE * size.half_beam_m)
    length = size.x_fwd_m - size.x_aft_m
    u = (x - size.x_aft_m) / length
    if u < PARALLEL_FROM_SHARE:
        share = 1.0 - u / PARALLEL_FROM_SHARE
        value = size.half_beam_m * (1.0 - (1.0 - TRANSOM_SHARE) * share ** 2)
    elif u > PARALLEL_TO_SHARE:
        share = min(1.0, (u - PARALLEL_TO_SHARE) / (1.0 - PARALLEL_TO_SHARE))
        value = size.half_beam_m * max(0.0, 1.0 - share ** 2) ** BOW_TAPER_EXPONENT
    else:
        value = size.half_beam_m
    return max(value, MIN_BREADTH_SHARE * size.half_beam_m)


def keel_height(x: float, size: HullSize) -> float:
    """Keel above the baseline: 0, rising at the stern (a guess without a profile outline)."""
    length = size.x_fwd_m - size.x_aft_m
    rise_to = size.x_aft_m + STERN_RISE_SHARE * length
    if x >= rise_to:
        return 0.0
    share = (rise_to - x) / (STERN_RISE_SHARE * length)
    return STERN_RISE_SHARE_OF_DEPTH * size.depth_m * share ** 2


def section_form(half_breadth: float, size: HullSize) -> tuple[float, float]:
    """Fullness and bottom flat of ``section_shape`` for a station of this deck half-breadth."""
    share = half_breadth / size.half_beam_m
    weight = min(1.0, max(0.0, (share - WEIGHT_FROM) / (0.98 - WEIGHT_FROM))) ** WEIGHT_EXPONENT
    return END_FULLNESS + (MID_FULLNESS - END_FULLNESS) * weight, MID_FLAT * weight


def hull_table(data: ArrangementInput, count: int = STATION_COUNT) -> tuple[VesselTable, HullSize]:
    """The estimated hull as a station table (rows ``prior``), from the hull ends to the stem.

    Each station: keel from the profile (or the stern-rise guess), top at the depth, and the
    ``form_fit`` section family scaled to the deck half-breadth. With a read profile outline the
    builder also cuts the lofted hull by that outline (``model.py``)."""
    size = hull_size(data)
    deck_outline = (data.hull_outline or {}).get("deck_half_breadth_m")
    xs = np.linspace(size.x_aft_m, size.x_fwd_m, count)
    eta = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, FITTED_ROW_SAMPLES)))
    rows = []
    for index, x in enumerate(xs):
        breadth = deck_half_breadth(float(x), size, deck_outline)
        fullness, flat = section_form(breadth, size)
        keel = keel_height(float(x), size) if not (data.hull_outline or {}).get("profile_xz_m") else 0.0
        top = size.depth_m
        points = np.column_stack([breadth * section_shape(eta, fullness, flat), keel + eta * (top - keel)])
        rows.append(StationRow(id=f"est{index:02d}", x_m=round(float(x), 4), points_yz_m=points.tolist(),
                               source="prior", notes=[f"{HULL_LABEL}: prior form p={fullness:.2f}, flat={flat:.2f}"]))
    trend = {"method": HULL_METHOD, "label": HULL_LABEL, "x_range_m": [size.x_aft_m, size.x_fwd_m],
             "dimensions": {"half_beam_m": size.half_beam_m, "depth_m": size.depth_m}, "basis": size.basis}
    warnings = [{"kind": "no_lines_plan", "section_id": None,
                 "message": f"{HULL_LABEL}: every station is the prior form sized from the GA particulars."}]
    return VesselTable(rows, waterline_grid(rows), trend, warnings), size


# ------------------------------------------------------------------ item boxes

def _extent_status(item: Item, axis: str) -> str:
    return (item.extent.get("status") or {}).get(axis, "read")


def item_box(item: Item, data: ArrangementInput, size: HullSize) -> Box:
    """The item's box in ship metres. A missing y or z extent is filled by a labelled rule."""
    status = {"x": _extent_status(item, "x")}
    basis = {}
    x = x_range_m(item.extent, data.frames)
    deck = size.depth_m
    half = size.half_beam_m

    if item.extent.get("y_m") is not None:
        y = _pair(item.extent["y_m"], "y_m")
        status["y"] = _extent_status(item, "y")
    else:
        status["y"] = "guessed"
        if item.kind == "accommodation_deck":
            y = (-(half - HOUSE_SIDE_MARGIN_M), half - HOUSE_SIDE_MARGIN_M)
            basis["y"] = f"breadth of the ship less {HOUSE_SIDE_MARGIN_M:g} m a side"
        elif item.kind == "cargo_crane":
            y = (-CRANE_POST_RADIUS_M, CRANE_POST_RADIUS_M)
            basis["y"] = "post on the centreline"
        elif item.side == "port":
            y = (0.0, half)
            basis["y"] = "port half of the hull"
        elif item.side == "starboard":
            y = (-half, 0.0)
            basis["y"] = "starboard half of the hull"
        elif item.side == "centre":
            y = (-CENTRE_SHARE_OF_BREADTH * half, CENTRE_SHARE_OF_BREADTH * half)
            basis["y"] = f"{CENTRE_SHARE_OF_BREADTH:.0%} of the breadth about the centreline"
        else:
            y = (-half, half)
            basis["y"] = "full breadth inside the hull"

    if item.extent.get("z_m") is not None:
        z = _pair(item.extent["z_m"], "z_m")
        status["z"] = _extent_status(item, "z")
    else:
        status["z"] = "guessed"
        if item.kind == "accommodation_deck":
            tier = int(item.extent.get("tier") or 1)
            z = (deck + (tier - 1) * TIER_HEIGHT_M, deck + tier * TIER_HEIGHT_M)
            basis["z"] = f"tier {tier} at {TIER_HEIGHT_M:g} m per tier above the deck"
        elif item.kind == "cargo_hatch":
            z = (deck, deck + COAMING_HEIGHT_M)
            basis["z"] = f"coaming {COAMING_HEIGHT_M:g} m above the deck"
        elif item.kind == "cargo_crane":
            z = (deck, deck + CRANE_POST_SHARE_OF_BREADTH * 2 * half)
            basis["z"] = f"post height {CRANE_POST_SHARE_OF_BREADTH:.0%} of the breadth"
        else:
            z = (0.0, deck)
            basis["z"] = "baseline to deck"
    return Box(x, y, z, status, basis)


# Plausible proportions of a displacement cargo ship (gate G3 of the demo plan). Outside them a
# dimension is probably misread; the run lists a finding and is not shown.
LENGTH_BREADTH_RANGE = (4.0, 9.0)
BREADTH_DEPTH_RANGE = (1.2, 2.6)


def check_proportions(size: HullSize) -> list[str]:
    """Findings for a length/breadth or breadth/depth ratio outside the plausible ranges."""
    findings = []
    length, breadth = size.x_fwd_m - size.x_aft_m, 2 * size.half_beam_m
    for name, ratio, (low, high) in (("L/B", length / breadth, LENGTH_BREADTH_RANGE),
                                     ("B/D", breadth / size.depth_m, BREADTH_DEPTH_RANGE)):
        if not low <= ratio <= high:
            findings.append(f"{name} = {ratio:.2f} is outside {low:g}..{high:g}: check the dimensions")
    return findings


def check_boxes(boxes: dict[str, Box], items: dict[str, Item], size: HullSize) -> list[str]:
    """Findings (text) for boxes outside the hull length or cargo spaces that overlap in x."""
    findings = []
    for item_id, box in boxes.items():
        if box.x[0] < size.x_aft_m - 1.0 or box.x[1] > size.x_fwd_m + 1.0:
            findings.append(f"{item_id}: x {box.x[0]:.1f}..{box.x[1]:.1f} m is outside the hull length")
    cargo = sorted((box.x, item_id) for item_id, box in boxes.items()
                   if items[item_id].kind in ("cargo_hold",) and items[item_id].side == "both")
    for (first, first_id), (second, second_id) in zip(cargo, cargo[1:]):
        if second[0] < first[1] - 1.0:
            findings.append(f"{first_id} and {second_id} overlap by {first[1] - second[0]:.1f} m in x")
    return findings


def carve_order(boxes: dict[str, Box], items: dict[str, Item]) -> list[str]:
    """Below-deck spaces from the smallest box to the largest: each space is cut by the spaces
    placed before it, so a tank drawn inside a hold (a topside or double-bottom tank) keeps its
    volume and the hold gets the rest."""
    def volume(item_id: str) -> float:
        box = boxes[item_id]
        return (box.x[1] - box.x[0]) * (box.y[1] - box.y[0]) * (box.z[1] - box.z[0])

    spaces = [item_id for item_id in boxes if items[item_id].kind in SPACE_KINDS]
    return sorted(spaces, key=lambda item_id: (volume(item_id), item_id))
