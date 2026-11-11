"""CadQuery solids of the estimated arrangement: the estimated hull and one solid per item.

Axes and units: metres; x forward from the aft perpendicular (frame 0), y to port, z up from
the baseline. The hull comes from ``ga_arrangement.hull_table`` (prior form, no lines plan);
items are boxes from ``ga_arrangement.item_box``, cut by the hull when they are below the deck,
and carved smallest first so that spaces do not overlap.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vessel_reconstruction import ga_arrangement as G

# A loft cannot end in a line: end stations keep at least this half-breadth (metres).
MIN_LOFT_HALF_BREADTH_M = 0.05
# Height above the deck that the profile-outline prism allows (deckhouses are separate parts).
DECK_CLEARANCE_M = 0.0
# Boxes reach this far beyond the hull so that the hull, not the box, gives the shell side.
BOX_MARGIN_M = 0.5
# Display gap (metres) on each face of a space that is not the shell: neighbouring spaces (two
# holds at one bulkhead) then do not share a face in the 3D view. The recorded extents are
# unchanged.
DISPLAY_GAP_M = 0.05
# Mesh tolerances (metres, radians).
MESH = (0.02, 0.3)


@dataclass
class Solid:
    id: str
    kind: str
    label: str
    solid: object  # cadquery Shape, metres
    box: G.Box | None
    item: G.Item | None


def _section_wire(x: float, points: np.ndarray):
    """A closed wire: one spline from the port deck edge through the keel to the starboard deck
    edge, and a straight deck line back (as the concept model's hull)."""
    import cadquery as cq

    points = points[np.argsort(points[:, 1], kind="stable")]
    points[:, 0] = np.maximum(points[:, 0], MIN_LOFT_HALF_BREADTH_M)
    # Thin the 65 fitted samples: every second point keeps the shape and halves the loft cost.
    points = np.vstack([points[:-1:2], points[-1:]])
    starboard = [cq.Vector(x, -y, z) for y, z in points]
    port = [cq.Vector(x, y, z) for y, z in points][::-1]
    keel = cq.Vector(x, 0.0, float(points[0, 1]) - 1e-3)
    spline = cq.Edge.makeSpline(port + [keel] + starboard)
    deck = cq.Edge.makeLine(starboard[-1], port[0])
    return cq.Wire.assembleEdges([spline, deck])


def hull_solid(table, outline_xz: list | None = None):
    """Loft through the station rows; cut by the read profile outline when there is one."""
    import cadquery as cq

    wires = [_section_wire(row.x_m, np.asarray(row.points_yz_m, dtype=float)) for row in table.stations]
    hull = cq.Solid.makeLoft(wires, ruled=False)
    if outline_xz:
        half = max(max(p[0] for p in row.points_yz_m) for row in table.stations) + 1.0
        wire = cq.Wire.makePolygon([cq.Vector(float(x), -half, float(z)) for x, z in outline_xz], close=True)
        prism = cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), cq.Vector(0, 2 * half, 0))
        hull = hull.intersect(prism)
    return hull


def _box(x, y, z):
    import cadquery as cq

    return cq.Solid.makeBox(x[1] - x[0], y[1] - y[0], z[1] - z[0], cq.Vector(x[0], y[0], z[0]))


def _largest_solid(shape):
    """A boolean result as one solid (the largest), or None when it is empty."""
    solids = list(shape.Solids()) if shape is not None else []
    solids = [solid for solid in solids if solid.Volume() > 1e-6]
    if not solids:
        return None
    if len(solids) == 1:
        return solids[0]
    import cadquery as cq

    return cq.Compound.makeCompound(solids)


# Height of the deck-outline prism above the deck (higher than any deckhouse or crane).
DECK_PRISM_HEIGHT_M = 80.0


def deck_outline_prism(table, size: G.HullSize):
    """A vertical prism of the hull's deck outline (the stations' deck half-breadths), from just
    below the deck upward: what stands on the deck stays inside the ship side."""
    import cadquery as cq

    port = [(row.x_m, max(max(p[0] for p in row.points_yz_m), MIN_LOFT_HALF_BREADTH_M)) for row in table.stations]
    outline = port + [(x, -y) for x, y in reversed(port)]
    bottom = size.depth_m - 1.0
    wire = cq.Wire.makePolygon([cq.Vector(x, y, bottom) for x, y in outline], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), cq.Vector(0, 0, DECK_PRISM_HEIGHT_M))


def item_solid(item: G.Item, box: G.Box, hull, size: G.HullSize, deck_prism=None):
    """The item's solid before carving: below-deck spaces are box and hull; deckhouse tiers and
    spaces above the deck are boxes kept inside the deck outline; hatches are boxes and a crane
    is a cylinder post."""
    import cadquery as cq

    if deck_prism is not None and (item.kind == "accommodation_deck"
                                   or (item.kind in G.SPACE_KINDS and G.above_deck(box, size))):
        return _largest_solid(deck_prism.intersect(_box(box.x, box.y, (box.z[0] + DISPLAY_GAP_M, box.z[1]))))
    if item.kind in G.SPACE_KINDS and not G.above_deck(box, size):
        # ``hull`` here is the inner hull (G.DISPLAY_INSET_M inside the shell). A space whose side
        # reaches the shell: let that surface give the side. Other faces move in by DISPLAY_GAP_M,
        # so neighbouring spaces do not share a face either (display only).
        gap = DISPLAY_GAP_M
        y0 = box.y[0] - BOX_MARGIN_M if box.y[0] <= -size.half_beam_m + 1e-6 else box.y[0] + gap
        y1 = box.y[1] + BOX_MARGIN_M if box.y[1] >= size.half_beam_m - 1e-6 else box.y[1] - gap
        z0 = box.z[0] - BOX_MARGIN_M if box.z[0] <= 1e-6 else box.z[0] + gap
        x = (box.x[0] + gap, box.x[1] - gap)
        return _largest_solid(hull.intersect(_box(x, (y0, y1), (z0, box.z[1] - gap))))
    if item.kind == "cargo_crane":
        centre_x = 0.5 * (box.x[0] + box.x[1])
        centre_y = 0.5 * (box.y[0] + box.y[1])
        radius = max(0.3, 0.5 * min(box.x[1] - box.x[0], box.y[1] - box.y[0]))
        bottom = box.z[0] + DISPLAY_GAP_M
        return cq.Solid.makeCylinder(radius, box.z[1] - bottom, cq.Vector(centre_x, centre_y, bottom))
    # A hatch coaming stands on the deck: its bottom face moves up by the display gap.
    return _box(box.x, box.y, (box.z[0] + DISPLAY_GAP_M, box.z[1]))


def build(data: G.ArrangementInput):
    """Hull and item solids. Returns (table, size, solids, findings)."""
    table, size = G.hull_table(data)
    outline = (data.hull_outline or {}).get("profile_xz_m")
    hull = hull_solid(table, outline)
    # Spaces are cut by an inner hull (DISPLAY_INSET_M inside the shell), so no space shares a
    # face with the hull in the 3D view.
    inner_hull = hull_solid(G.inset_table(table), outline)
    items = {item.id: item for item in data.items}
    boxes = {item.id: G.item_box(item, data, size) for item in data.items}
    findings = G.check_proportions(size) + G.check_depth(data, boxes) + G.check_boxes(boxes, items, size)
    solids = [Solid("hull", "hull", G.HULL_LABEL, hull, None, None)]
    deck_prism = deck_outline_prism(table, size)
    placed = []
    for item_id in G.carve_order(boxes, items):
        item = items[item_id]
        solid = item_solid(item, boxes[item_id], inner_hull, size, deck_prism)
        for other in placed:
            if solid is None:
                break
            solid = _largest_solid(solid.cut(other))
        if solid is None:
            findings.append(f"{item_id}: nothing left inside the hull after the smaller spaces")
            continue
        placed.append(solid)
        solids.append(Solid(item_id, item.kind, item.label, solid, boxes[item_id], item))
    for item in data.items:
        if item.kind not in G.DECK_KINDS:
            continue
        solid = item_solid(item, boxes[item.id], hull, size, deck_prism)
        if solid is None:
            findings.append(f"{item.id}: lies outside the deck outline")
            continue
        solids.append(Solid(item.id, item.kind, item.label, solid, boxes[item.id], item))
    return table, size, solids, findings


def mesh_of(solid, tolerance_m: float = MESH[0], angular_rad: float = MESH[1]) -> tuple[np.ndarray, np.ndarray]:
    vertices, triangles = solid.tessellate(tolerance_m, angular_rad)
    return (np.array([[v.x, v.y, v.z] for v in vertices], dtype=float),
            np.array(triangles, dtype=np.int64).reshape(-1, 3))


def bbox_of(solid) -> dict:
    vertices, _ = mesh_of(solid)
    return {"min": vertices.min(axis=0).tolist(), "max": vertices.max(axis=0).tolist()}
