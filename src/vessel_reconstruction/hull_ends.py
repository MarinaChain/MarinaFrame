"""Hull ends beyond the first and last drawn stations.

A body plan draws stations between the ends of the hull; the profile draws the
whole hull from the stern contour to the stem. A first hull lofted only through
the drawn stations stops at the end stations (series60: 10-90 m of a 99.76 m
LOA). This module extends it to the ends that the profile shows:

* **Where the ends are.** The profile's hull outline (vessel_description.
  _profile_outline) spans the hull from its aft extreme to its fore extreme;
  its ink columns, at the checked scale and x origin, give the end positions.
  When the title block's LOA is read and the outline length disagrees with it
  by more than END_LENGTH_TOLERANCE, the outline holds other ink (a ruler) or
  misses part of the hull, and no end is added.
* **End sections.** Between the end station and the end, END_FRACTIONS place
  end sections. Their keel and deck heights are the profile outline at their x
  (the forefoot rise, the stem rake, the stern overhang). Their shape is the end
  station's row, stretched to those heights, with its half-breadths scaled by
  the taper of the half-breadth plan: the plan outline's widest half-breadth
  at the section over the one at the end station (plan_breadths). Without a
  readable plan the taper is linear to END_MIN_SHARE at the end. The section
  shape is not read: every end row is labelled ``inferred`` (built as
  ``ai_inferred``) and the hull warns about it.

No truth and no model is used. When the profile cannot be read, no end is added
(the hull stops at the end stations, as before).
"""
from __future__ import annotations

import copy

import numpy as np

from .vessel_model import StationRow

# End sections lie at these shares of the way from the end station to the end.
# The last one is just inside the end, where the outline still has height.
END_FRACTIONS = (0.2, 0.4, 0.6, 0.8, 0.97)
# An end closer to its end station than this share of the station spacing is
# already reached; no end section is added there.
END_MIN_GAP_SHARE = 0.25
# Smallest taper of an end section's half-breadths (a stem bar or a stern
# contour edge is not a line: the builder needs a section with area). Without
# a plan, half-breadths taper linearly to it at the end.
END_MIN_SHARE = 0.03
# A plan taper above this is a reading of other ink (a label beside the plan).
END_MAX_TAPER = 1.2
# The half-breadth plan's centreline is where the waterlines meet at the bow:
# the median ink row of the outline's fore PLAN_TIP_SHARE of columns.
PLAN_TIP_SHARE = 0.005
# Columns either side of a section read for its widest plan half-breadth.
PLAN_COLUMN_PX = 2
# The outline length may differ from a read LOA by this share before the
# outline is taken as holding other ink.
END_LENGTH_TOLERANCE = 0.03
# An end section with less height than this share of the end station's height
# is at the very tip of the outline; it is left out.
END_MIN_HEIGHT_SHARE = 0.05
END_NOTE = ("hull end beyond the drawn stations: heights from the profile outline, taper from the plan "
            "outline, section shape inferred")
END_WARNING = ("Hull ends beyond the first and last drawn stations are ai_inferred: their keel and deck "
               "heights follow the profile outline, their breadth the half-breadth plan's outline; their "
               "section shape is the end station's.")


def profile_ends(image, setups, description, hints=None) -> dict | None:
    """The hull's aft and fore extremes (x, m) on the profile outline, or None.

    Returns ``{"aft_m", "fore_m", "profile", "scale"}``. None when there is no
    profile setup or outline, or when a read LOA disagrees with the outline length.
    """
    from .vessel_description import (_profile_outline, _value, checked_x_origin, printed_dimensions,
                                      profile_setup, with_outline_baseline)
    profile = profile_setup(setups, hints, image)
    if profile is None:
        return None
    scales = (description or {}).get("checked_scales") or {}
    scale = float(scales.get(profile.get("view_id", "profile"), profile["pixels_per_metre"]))
    outline, left, _ = _profile_outline(image, profile)
    columns = np.flatnonzero(outline.any(axis=0))
    if len(columns) < 2 or scale <= 0:
        return None
    profile = with_outline_baseline(image, profile)
    if profile is None:
        return None
    origin = checked_x_origin(image, profile)
    direction = profile.get("x_direction") or 1
    xs = sorted(direction * (float(c) + left - origin) / scale for c in (columns[0], columns[-1]))
    principal = (description or {}).get("principal") or {}
    loa = _value(principal.get("loa")) or _value(printed_dimensions(description or {}).get("loa"))
    if isinstance(loa, (int, float)) and loa > 0 and abs((xs[1] - xs[0]) - loa) > END_LENGTH_TOLERANCE * loa:
        return None
    return {"aft_m": xs[0], "fore_m": xs[1], "profile": profile, "scale": scale}


def end_stations(ends: dict, station_xs: list[float]) -> list[dict]:
    """Places of the end sections: ``{"id", "x_m", "end", "share"}``, aft first.

    ``share`` is how far the place lies from the end station (0) to the end (1).
    """
    xs = sorted(float(x) for x in station_xs)
    if len(xs) < 2:
        return []
    spacing = float(np.median(np.diff(xs)))
    places = []
    for end, terminal, extreme in (("aft", xs[0], ends["aft_m"]), ("fore", xs[-1], ends["fore_m"])):
        gap = extreme - terminal
        if abs(gap) < END_MIN_GAP_SHARE * spacing or (end == "aft") != (gap < 0):
            continue
        for index, share in enumerate(END_FRACTIONS, 1):
            places.append({"id": f"{end}-end-{index}", "x_m": round(terminal + share * gap, 4),
                           "end": end, "share": share})
    return sorted(places, key=lambda p: p["x_m"])


def plan_region(setups, profile_region, hints=None) -> list | None:
    """The half-breadth plan's region, as vessel_description.profile_setup takes the profile's.

    Rows from the intake's region (measured on ink), else the model's.
    Columns are the union of the intake's, the model's and the profile's: a
    lines plan draws the half-breadth plan under the profile over the same
    length, and an intake region can hold only part of a long view
    (shipd-1-09867-3v-L0: the fore half, the aft end taken as a body plan).
    None when neither the intake nor the model has a plan region.
    """
    setup = next((s for s in setups if s.get("view") == "plan" and s.get("region_px")), None)
    model = list(setup["region_px"]) if setup else None
    intake = next((list(h["region_px"]) for h in hints or []
                   if h.get("label") == "half_breadth" and h.get("region_px")), None)
    rows = intake or model
    if rows is None:
        return None
    regions = [r for r in (intake, model, profile_region) if r]
    return [min(r[0] for r in regions), rows[1], max(r[2] for r in regions), rows[3]]


def plan_breadths(image, region, ends: dict, xs: list[float], direction: int = 1) -> dict:
    """Widest half-breadth (plan pixels) of the half-breadth plan's outline at each x, ``{x: px}``.

    The plan is drawn over the same length as the profile: its outline's
    column extent is mapped onto the profile's ends (``ends`` aft_m/fore_m),
    so no plan scale or origin is needed. The centreline row is where the
    waterlines meet at the bow. Returns {} when the plan has no outline or its
    length differs from the profile's by more than END_LENGTH_TOLERANCE (part
    of the plan is outside the region, or other ink is in it).
    """
    from .vessel_description import _profile_outline
    outline, _, _ = _profile_outline(image, {"region_px": region})
    columns = np.flatnonzero(outline.any(axis=0))
    profile_span = (ends["fore_m"] - ends["aft_m"]) * ends["scale"]
    if len(columns) < 2 or abs((columns[-1] - columns[0]) - profile_span) > END_LENGTH_TOLERANCE * profile_span:
        return {}
    aft_column, fore_column = (columns[0], columns[-1]) if direction >= 0 else (columns[-1], columns[0])
    tip = max(1, int(round(PLAN_TIP_SHARE * len(columns))))
    tip_columns = columns[-tip:] if direction >= 0 else columns[:tip]
    centre = float(np.median(np.nonzero(outline[:, tip_columns])[0]))
    breadths = {}
    for x in xs:
        share = (x - ends["aft_m"]) / (ends["fore_m"] - ends["aft_m"])
        column = int(round(aft_column + share * (fore_column - aft_column)))
        rows = np.nonzero(outline[:, max(0, column - PLAN_COLUMN_PX):column + PLAN_COLUMN_PX + 1])[0]
        if len(rows):
            breadths[x] = float(np.max(np.abs(rows - centre)))
    return breadths


def end_tapers(image, setups, ends: dict, places: list[dict], terminals: dict, hints=None) -> dict:
    """Half-breadth taper of each end place from the plan, ``{id: share}``; linear where the plan is unread.

    ``terminals`` maps "aft" and "fore" to the end stations' x.
    """
    linear = {p["id"]: 1.0 - p["share"] * (1.0 - END_MIN_SHARE) for p in places}
    region = plan_region(setups, ends["profile"]["region_px"], hints)
    if region is None:
        return linear
    direction = ends["profile"].get("x_direction") or 1
    xs = [p["x_m"] for p in places] + list(terminals.values())
    breadths = plan_breadths(image, region, ends, xs, direction)
    tapers = {}
    for place in places:
        reference = breadths.get(terminals[place["end"]])
        own = breadths.get(place["x_m"])
        if reference and own is not None:
            tapers[place["id"]] = float(np.clip(own / reference, END_MIN_SHARE, END_MAX_TAPER))
        else:
            tapers[place["id"]] = linear[place["id"]]
    return tapers


def end_heights(image, ends: dict, places: list[dict]) -> dict:
    """Profile-outline keel and deck heights at each end place: ``{id: {"deck", "keel"}}``."""
    from .vessel_description import profile_outline_heights
    return profile_outline_heights(image, ends["profile"], ends["scale"], places)


def end_row(place: dict, heights: dict, terminal: StationRow, taper: float) -> StationRow | None:
    """One end section: the end station's shape stretched to the outline heights and tapered.

    None when the outline there has too little height (the very tip).
    """
    points = np.asarray(terminal.points_yz_m, dtype=float)
    keel, top = terminal.keel_z_m, terminal.top_z_m
    low, high = float(heights["keel"]), float(heights["deck"])
    if high - low < END_MIN_HEIGHT_SHARE * (top - keel) or top - keel <= 0:
        return None
    eta = (points[:, 1] - keel) / (top - keel)
    shaped = np.column_stack([points[:, 0] * taper, low + eta * (high - low)])
    return StationRow(id=place["id"], x_m=float(place["x_m"]), points_yz_m=shaped.tolist(), source="inferred",
                      notes=[END_NOTE])


def end_declared(place: dict, row: StationRow, terminal_declared: dict) -> dict:
    """The declared section of an end row: the end station's view and calibration at the end's x and heights."""
    section = copy.deepcopy(terminal_declared)
    for key in ("contour_selection", "pieces", "authored"):
        section.pop(key, None)
    section.update(id=place["id"], x_m=float(place["x_m"]), z_min_m=float(row.keel_z_m),
                   z_max_m=float(row.top_z_m),
                   evidence=("Hull end beyond the drawn stations, inferred from the profile outline "
                             "and the end station's shape; not a drawn section."))
    return section


def extend_to_ends(table, declared: list[dict], places: list[dict], heights: dict, tapers: dict) -> list[dict]:
    """Add end rows to ``table`` (in place); return their declared sections.

    Each end row takes the shape of the table's end station on its side.
    """
    stations = [row for row in table.stations if row.source != "inferred"]
    if not stations or not places:
        return []
    by_id = {s["id"]: s for s in declared}
    terminals = {"aft": stations[0], "fore": stations[-1]}
    added = []
    for place in places:
        terminal = terminals[place["end"]]
        if place["id"] not in heights or terminal.id not in by_id:
            continue
        row = end_row(place, heights[place["id"]], terminal, tapers[place["id"]])
        if row is None:
            continue
        table.stations.append(row)
        added.append(end_declared(place, row, by_id[terminal.id]))
    if added:
        table.stations.sort(key=lambda r: r.x_m)
        table.warnings.append({"kind": "inferred_end", "section_id": None, "message": END_WARNING})
    return added
