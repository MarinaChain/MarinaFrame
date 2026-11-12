"""Commercial GA extents; rules and constants unchanged."""
from __future__ import annotations

from .ga_scale_dimensions import (
    _measure,
)
from .ga_scale_frames import (
    parse_tick,
)
from .ga_scale_geometry import (
    _tiles,
    _to_sheet,
    _view_id,
    side_of_label,
)
from .ga_scale_overlaps import (
    _outline_problem,
)
from .ga_scale_settings import (
    CENTRE_TOLERANCE_M,
    MEASURED,
    OUTLINE_STATUS,
    PLAN_KINDS,
    POINT_SIGMA_IMAGE_PX,
    PURPOSE,
)
from pathlib import Path
import json


def read_extents(result: dict, work: dict, reading: dict, request_dir: Path) -> dict:
    """Give each boxed space its ``extent`` (frames, metres and status per axis); return statistics."""
    stats = {"asked": 0, "boxed": 0, "with_extent": 0}
    reply = (reading.get("reply") or {}).get(PURPOSE)
    marks = [] if reply is None else [t for t in reply["ticks"] if (parse_tick(t["label"]) or ("frame",))[0] != "frame"]
    if reply is not None and work.get("table") is not None and (reply["points"] or marks):
        # Named places that the scale request left out (a plan it did not look at) come from
        # the whole-view images; a place already pointed at high resolution is kept.
        tiles = _tiles(request_dir)
        raw, added = work["raw"], 0
        for point in reply["points"]:
            tile = tiles[point["image_id"]]
            named = raw["points"].setdefault(_view_id(tile), {})
            if point["name"] not in named:
                named[point["name"]] = [_to_sheet(tile, point["x"], point["y"])]
                raw["sigma_px"] = max(raw["sigma_px"], POINT_SIGMA_IMAGE_PX
                                      * (tile["crop_box_px"][2] - tile["crop_box_px"][0]) / tile["width"])
                added += 1
        # A.P. and F.P. marks that the scale request left out (needed for the LBP).
        for tick in marks:
            name = parse_tick(tick["label"])[0]
            tile = tiles[tick["image_id"]]
            view_marks = raw["marks"].setdefault(_view_id(tile), {})
            if name in view_marks:
                continue  # a mark already pointed in this view is kept
            view_marks[name] = [_to_sheet(tile, tick["x"], tick["y"])]
            added += 1
        if added:
            stats["points_added"] = added
            _measure(result, work)
    table = work.get("table")
    if reply is None or table is None:
        stats["reason"] = ("the frame scale was not established" if table is None
                           else reading.get("stop_reason") or "the model gave no valid reply for the extents")
        return stats
    tiles = _tiles(request_dir)
    request = json.loads((Path(request_dir) / "request.json").read_text())
    stats["asked"] = len(request["context"]["spaces"])
    asked = {s["space_id"]: s for s in request["context"]["spaces"]}
    spaces = {s["id"]: s for s in result["spaces"]}
    kinds = work["kinds"]
    for entry in reply["extents"]:
        space = spaces.get(entry["space_id"])
        tile = tiles[entry["image_id"]]
        view = _view_id(tile)
        if space is None or entry["space_id"] not in asked or asked[entry["space_id"]]["image_id"] != view:
            result["checks"].append({"code": "extent_of_unknown_space", "status": "dropped",
                                     "label": entry["space_id"][:64]})
            continue
        stats["boxed"] += 1
        if entry.get("printed_size"):
            # Every printed size the model reports ends up used or in checks with a reason.
            work.setdefault("printed_sizes", []).append({"space_id": entry["space_id"], "text": entry["printed_size"][:32]})
        axis = work["axes"].get(view)
        if axis is None or "extent" in space:
            continue
        left, top = _to_sheet(tile, entry["box"][0], entry["box"][1])
        right, bottom = _to_sheet(tile, entry["box"][2], entry["box"][3])
        status = MEASURED if entry["basis"] == "outline" else "guessed"
        ends = sorted((axis.x_m(left), axis.x_m(right)))
        frames = [int(round(table.frame_at(x))) for x in ends]
        if frames[0] == frames[1]:
            continue
        extent = {"frames": frames, "x_m": [round(table.x_m(f), 3) for f in frames],
                  "x_measured_m": [round(x, 2) for x in ends], "status": {"x": status},
                  "view_id": view, "outline_box_px": [round(v, 1) for v in (left, top, right, bottom)],
                  "basis": entry["basis"],
                  "method": "ends of the drawn boundary measured on the frame scale, given to the nearest frame"}
        named = work["points"].get(view, {})
        if kinds.get(view) == "profile" and "base_line" in named:
            base = named["base_line"][1]
            low, high = (base - bottom) / abs(axis.px_per_m), (base - top) / abs(axis.px_per_m)
            extent["z_m"] = [round(max(low, 0.0), 2), round(high, 2)]
            extent["status"]["z"] = status
        elif kinds.get(view) in PLAN_KINDS and "centre_line" in named:
            centre = named["centre_line"][1]
            # Seen from above with the bow to the right, port is up the sheet; bow left, down.
            sign = 1.0 if axis.px_per_m > 0 else -1.0
            sides = sorted((sign * (centre - top) / abs(axis.px_per_m), sign * (centre - bottom) / abs(axis.px_per_m)))
            extent["y_m"] = [round(sides[0], 2), round(sides[1], 2)]
            extent["status"]["y"] = status
        region = (space["source_record"].get("regions") or [{}])[0].get("box_px")
        if region and sum((s["source_record"].get("regions") or [{}])[0].get("box_px") == region
                          for s in result["spaces"]) > 1:
            region = None  # read from a crop shared with other labels: its own place is not known
        if region:
            # Where the label of this space is printed, in the metres of the extent (overlap rules).
            cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
            if "z_m" in extent:
                extent["label_at_m"] = [round(axis.x_m(cx), 2), round((base - cy) / abs(axis.px_per_m), 2)]
            elif "y_m" in extent:
                extent["label_at_m"] = [round(axis.x_m(cx), 2), round(sign * (centre - cy) / abs(axis.px_per_m), 2)]
        side = side_of_label(space["label"])
        if side is None and "y_m" in extent:
            low, high = extent["y_m"]
            side = ("port" if low >= -CENTRE_TOLERANCE_M else "starboard" if high <= CENTRE_TOLERANCE_M else "centre")
        if side:
            extent["side"] = side
        if space["kind"] == "cargo_hatch" and entry.get("printed_size") and entry.get("printed_size_at"):
            extent["printed_size_raw"] = {"text": entry["printed_size"][:32],
                                          "at_px": [round(v, 1) for v in _to_sheet(tile, *entry["printed_size_at"])]}
        if entry.get("outline"):
            def to_metres(px, py, axis=axis, named=named, view=view):
                if "z_m" in extent:
                    return [round(axis.x_m(px), 2), round((named["base_line"][1] - py) / abs(axis.px_per_m), 2)]
                return [round(axis.x_m(px), 2), round(sign * (named["centre_line"][1] - py) / abs(axis.px_per_m), 2)]

            points_px = [_to_sheet(tile, x, y) for x, y in entry["outline"]]
            reason = _outline_problem(points_px, extent["outline_box_px"], space, result["spaces"], view)
            if reason is None and ("z_m" in extent or "y_m" in extent):
                extent["outline"] = {"plane": "xz" if "z_m" in extent else "xy",
                                     "points_m": [to_metres(x, y) for x, y in points_px],
                                     "points_px": [[round(x, 1), round(y, 1)] for x, y in points_px],
                                     "status": OUTLINE_STATUS}
                stats["outlines"] = stats.get("outlines", 0) + 1
            else:
                result["checks"].append({"code": "outline_dropped", "status": "dropped", "label": space["label"][:64],
                                         "reason": reason or "the view has no base line or centre line"})
        space["extent"] = extent
        stats["with_extent"] += 1
    return stats
