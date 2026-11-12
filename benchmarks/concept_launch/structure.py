"""Steel structure of the concept survey launch, as structure members (metres).

Members use the block-member form of ``vessel_reconstruction.structure`` (``display.py``,
``steel.py``): a plate has a ``contour`` (3D points in order) and a thickness; a stiffener has a
``trace``, a flat-bar ``profile`` and a ``web_direction``. ``structure.display.write_structure_glb``
groups them by label words (bulkheads, decks and inner bottom, floors/girders/web frames, frames
and beams), which gives the app's "Steel" control its groups.

Bulkheads, web frames, the centre girder and the inner bottom keep the id of their part in
``model.py``, so the part's source record and the member are the same item. Scantlings are made
up (a concept preview); ``thickness_source`` says so.
"""
from __future__ import annotations

import numpy as np

from . import model as M

THICKNESS_SOURCE = "concept_preview"
SIDE_FRAME = {"kind": "FlatBar", "height_mm": 120.0, "web_mm": 8.0, "name": "FB 120x8"}
DECK_BEAM = {"kind": "FlatBar", "height_mm": 100.0, "web_mm": 8.0, "name": "FB 100x8"}
LONGITUDINAL = {"kind": "FlatBar", "height_mm": 100.0, "web_mm": 8.0, "name": "FB 100x8"}
BULKHEAD_MM = 8.0
WEB_FRAME_MM = 10.0
FLOOR_MM = 8.0
INNER_BOTTOM_MM = 10.0
GIRDER_MM = 10.0
FIRST_FRAME, LAST_FRAME = 2, 46  # ordinary frames and deck beams run between these frames
DECK_LONGITUDINAL_Y_M = (2.4, 1.2, -1.2, -2.4)
BOTTOM_LONGITUDINAL_Y_M = (1.6, 0.8, -0.8, -1.6)
BOTTOM_LONGITUDINAL_X_M = (3.6, 18.0)
SIDE_FRAME_LOW_Z_M = 0.6  # side frames run from here (or the inner bottom) to under the deck
BEAM_CLEARANCE_M = 0.05  # deck beams stop this far inside the shell


def half_breadth_at(x: float, z: float) -> float:
    points = M.section_points(x)
    return float(np.interp(z, points[:, 1], points[:, 0]))


def bottom_height_at(x: float, y: float) -> float:
    """Height of the shell under ``y`` (the bilge curve, where y rises with z)."""
    points = M.section_points(x)
    return float(np.interp(abs(y), points[:, 0], points[:, 1]))


def _shoelace(points_2d) -> float:
    a = np.asarray(points_2d, dtype=float)
    return 0.5 * abs(float(np.dot(a[:, 0], np.roll(a[:, 1], -1)) - np.dot(a[:, 1], np.roll(a[:, 0], -1))))


def _plate(member_id: str, label: str, contour, thickness_mm: float, plane_axes: tuple[int, int]) -> dict:
    contour = [[float(v) for v in point] for point in contour]
    area = _shoelace([[p[plane_axes[0]], p[plane_axes[1]]] for p in contour])
    return {"member_id": member_id, "label": label, "contour": contour, "thickness_mm": thickness_mm,
            "thickness_source": THICKNESS_SOURCE, "material": "steel", "material_source": "guessed",
            "area_m2": area, "volume_m3": None, "sources": {"geometry": THICKNESS_SOURCE}}


def _stiffener(member_id: str, label: str, trace, profile: dict, web_direction) -> dict:
    trace = [[float(v) for v in point] for point in trace]
    length = float(np.sum(np.linalg.norm(np.diff(np.asarray(trace), axis=0), axis=1)))
    height, web = profile["height_mm"] / 1000, profile["web_mm"] / 1000
    return {"member_id": member_id, "label": label, "trace": trace, "profile": dict(profile),
            "web_direction": list(web_direction), "thickness_mm": profile["web_mm"],
            "thickness_source": THICKNESS_SOURCE, "material": "steel", "material_source": "guessed",
            "area_m2": length * height, "volume_m3": length * height * web, "length_m": length,
            "sources": {"geometry": THICKNESS_SOURCE}}


def _closed_section_3d(x: float, points: np.ndarray) -> list[list[float]]:
    port = [[x, y, z] for y, z in points[::-1]]
    starboard = [[x, -y, z] for y, z in points[1:]]
    return port + starboard


def _section_below(x: float, z_top: float) -> np.ndarray:
    """The starboard half of the station below ``z_top``, ending on that level."""
    points = M.section_points(x)
    kept = points[points[:, 1] < z_top]
    return np.vstack([kept, [[half_breadth_at(x, z_top), z_top]]])


def special_frames() -> set[int]:
    """Frames that carry a bulkhead or a web frame (no ordinary frame, beam or floor there)."""
    return {frame for _, _, frame in M.BULKHEADS} | set(M.WEB_FRAMES)


def members() -> list[dict]:
    """Every steel member of the concept vessel."""
    found = []
    for part_id, label, frame in M.BULKHEADS:
        x = M.frame_x(frame)
        found.append(_plate(part_id, f"Watertight bulkhead fr {frame}", _closed_section_3d(x, M.section_points(x)),
                            BULKHEAD_MM, (1, 2)))
    for frame in M.WEB_FRAMES:
        x = M.frame_x(frame)
        outer = M.section_points(x)
        inner = M.section_points(x, inset_m=M.FRAME_WEB_M, floor_m=M.FRAME_FLOOR_M, top_m=M.DEPTH_M - M.FRAME_WEB_M)
        ring = _closed_section_3d(x, outer) + _closed_section_3d(x, inner)[::-1]
        area = abs(_shoelace([[p[1], p[2]] for p in _closed_section_3d(x, outer)])
                   - _shoelace([[p[1], p[2]] for p in _closed_section_3d(x, inner)]))
        member = _plate(f"web_fr{frame:02d}", f"Web frame fr {frame}", ring, WEB_FRAME_MM, (1, 2))
        member["area_m2"] = area
        found.append(member)

    x0, x1 = M.INNER_BOTTOM_X_M
    xs = np.linspace(x0, x1, 45)
    port_edge = [[float(x), half_breadth_at(float(x), M.INNER_BOTTOM_Z_M), M.INNER_BOTTOM_Z_M] for x in xs]
    starboard_edge = [[x, -y, z] for x, y, z in port_edge[::-1]]
    found.append(_plate("inner_bottom", "Inner bottom deck (tank top)", port_edge + starboard_edge, INNER_BOTTOM_MM, (0, 1)))
    keel = [[float(x), 0.0, M.keel_height(float(x))] for x in xs]
    girder = keel + [[x1, 0.0, M.INNER_BOTTOM_Z_M], [x0, 0.0, M.INNER_BOTTOM_Z_M]]
    found.append(_plate("centre_girder", "Centre girder", girder, GIRDER_MM, (0, 2)))

    special = special_frames()
    first_floor, last_floor = round(x0 / M.FRAME_SPACING_M) + 1, round(x1 / M.FRAME_SPACING_M) - 1
    for frame in range(first_floor, last_floor + 1):
        if frame in special:
            continue
        x = M.frame_x(frame)
        found.append(_plate(f"floor_fr{frame:02d}", f"Floor fr {frame}",
                            _closed_section_3d(x, _section_below(x, M.INNER_BOTTOM_Z_M)), FLOOR_MM, (1, 2)))

    for frame in range(FIRST_FRAME, LAST_FRAME + 1):
        if frame in special:
            continue
        x = M.frame_x(frame)
        low = M.INNER_BOTTOM_Z_M if x0 <= x <= x1 else max(SIDE_FRAME_LOW_Z_M, M.keel_height(x) + 0.3)
        high = M.DEPTH_M - DECK_BEAM["height_mm"] / 1000
        points = M.section_points(x)
        side = points[(points[:, 1] >= low) & (points[:, 1] <= high)]
        if len(side) >= 2:
            for sign, suffix in ((1.0, "P"), (-1.0, "S")):
                trace = [[x, sign * y, z] for y, z in side]
                found.append(_stiffener(f"frame_fr{frame:02d}{suffix.lower()}", f"Side frame fr {frame} {suffix}",
                                        trace, SIDE_FRAME, (0.0, -sign, 0.0)))
        half = M.deck_half_breadth(x) - BEAM_CLEARANCE_M
        if half > 0.2:
            found.append(_stiffener(f"beam_fr{frame:02d}", f"Deck beam fr {frame}",
                                    [[x, half, M.DEPTH_M], [x, -half, M.DEPTH_M]], DECK_BEAM, (0.0, 0.0, -1.0)))

    beam_xs = np.arange(M.frame_x(FIRST_FRAME), M.frame_x(LAST_FRAME) + 1e-9, M.FRAME_SPACING_M)
    for y in DECK_LONGITUDINAL_Y_M:
        xs_on_deck = [float(x) for x in beam_xs if M.deck_half_breadth(float(x)) > abs(y) + 0.15]
        name = f"deck_long_{'p' if y > 0 else 's'}{abs(y):.1f}".replace(".", "")
        found.append(_stiffener(name, f"Deck longitudinal {'P' if y > 0 else 'S'} {abs(y):.1f} m",
                                [[xs_on_deck[0], y, M.DEPTH_M], [xs_on_deck[-1], y, M.DEPTH_M]], LONGITUDINAL,
                                (0.0, 0.0, -1.0)))
    bx0, bx1 = BOTTOM_LONGITUDINAL_X_M
    for y in BOTTOM_LONGITUDINAL_Y_M:
        trace = [[float(x), y, bottom_height_at(float(x), y)] for x in np.arange(bx0, bx1 + 1e-9, 0.5)]
        name = f"bottom_long_{'p' if y > 0 else 's'}{abs(y):.1f}".replace(".", "")
        found.append(_stiffener(name, f"Bottom longitudinal {'P' if y > 0 else 'S'} {abs(y):.1f} m", trace,
                                LONGITUDINAL, (0.0, 0.0, 1.0)))
    return found


def kind_of(member: dict) -> str:
    """Drawing kind of a member: bulkhead, web, floor, inner_bottom, girder, frame, beam, longitudinal."""
    member_id = member["member_id"]
    for prefix, kind in (("bhd_", "bulkhead"), ("web_", "web"), ("floor_", "floor"), ("inner_bottom", "inner_bottom"),
                         ("centre_girder", "girder"), ("frame_", "frame"), ("beam_", "beam"),
                         ("deck_long", "longitudinal"), ("bottom_long", "longitudinal")):
        if member_id.startswith(prefix):
            return kind
    raise ValueError(member_id)


def bounds(member: dict) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(member.get("contour") or member["trace"], dtype=float)
    return points.min(axis=0), points.max(axis=0)
