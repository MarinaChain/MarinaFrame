"""Commercial GA overlaps; rules and constants unchanged."""
from __future__ import annotations

from .ga_labels import label_family
from .ga_scale_geometry import (
    side_of_label,
)
from .ga_scale_settings import (
    EDGE_TOLERANCE_M,
    HATCH_SIZE,
    HATCH_SIZE_RANGE_M,
    INSIDE_LENGTH_SHARE,
    NOT_A_SPACE_ABOVE,
    OUTLINE_BOX_TOLERANCE_PX,
    SMALL_LABEL_BOX_FACTOR,
    SMALL_LABEL_LETTERS,
    STRIP_COVER,
    TANKS_ENDING_BELOW,
    UPPER_PART_SHARE,
)
import re


def _inside_polygon(point, polygon) -> bool:
    """Whether ``point`` lies inside ``polygon`` (even-odd rule)."""
    x, y = point
    inside = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _outline_problem(points, box, space: dict, spaces: list[dict], view: str) -> str | None:
    """Why an outline is not kept, or None: it must lie inside its box, hold the space's own
    label and hold no other label of the view (a label of the same family or a note of the same
    kind is the same space, as for the boxes)."""
    left, top, right, bottom = box
    tolerance = OUTLINE_BOX_TOLERANCE_PX
    if not all(left - tolerance <= x <= right + tolerance and top - tolerance <= y <= bottom + tolerance
               for x, y in points):
        return "the outline leaves its box"
    own = _label_centre(space)
    if own is None or not _inside_polygon(own, points):
        return "the outline does not hold the space's own label"
    for other in spaces:
        if other is space or other["status"] != "read" or other.get("view_id") != view:
            continue
        if label_family(other["label"]) == label_family(space["label"]):
            continue
        if other["kind"] == space["kind"] and other["kind"] not in ("other_space", "other_tank"):
            continue
        centre = _label_centre(other)
        if centre is not None and _inside_polygon(centre, points):
            return f"the outline holds the label of '{other['label'][:40]}'"
    return None


def _span(extent: dict) -> tuple[str, list[float], list[float]] | None:
    """The other axis name and the x and other-axis ranges of an extent, or None."""
    other = "z_m" if "z_m" in extent else "y_m" if "y_m" in extent else None
    if other is None:
        return None
    return other, list(extent.get("x_measured_m") or extent["x_m"]), list(extent[other])


def _holds(extent: dict, point) -> bool:
    span = _span(extent)
    if span is None or point is None:
        return False
    _, xs, vs = span
    return xs[0] < point[0] < xs[1] and vs[0] < point[1] < vs[1]


def _cover(outer: list[float], inner: list[float]) -> float:
    """The share of ``outer`` that ``inner`` covers."""
    length = outer[1] - outer[0]
    return max(0.0, min(outer[1], inner[1]) - max(outer[0], inner[0])) / length if length > 0 else 0.0


def _label_centre(space: dict) -> tuple[float, float] | None:
    """The centre of a space's printed label in sheet pixels, or None."""
    box = (space["source_record"].get("regions") or [{}])[0].get("box_px")
    return None if not box else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def covered_labels(result: dict) -> dict[str, list[dict]]:
    """For each measured box, the spaces without a box of their own whose label it holds.

    The overlap rules between two boxes cannot see a neighbour that was not boxed (a store above
    a peak tank, a residue tank beside a slop tank; review round 4). A box that holds such a
    label takes in that space. Not counted: a label of the same family (the same space read
    twice), and in a profile a tank printed for the sides (a wing or topside tank seen in
    projection).
    """
    kinds = {view["view_id"]: view["kind"] for view in result.get("views", [])}
    found: dict[str, list[dict]] = {}
    for big in result["spaces"]:
        extent = big.get("extent")
        if (not extent or extent.get("projection_of") or "outline_box_px" not in extent
                or "guessed" in extent["status"].values()):
            continue
        left, top, right, bottom = extent["outline_box_px"]
        for small in result["spaces"]:
            if (small is big or "extent" in small or small["status"] != "read"
                    or small.get("view_id") != extent["view_id"]):
                continue
            centre = _label_centre(small)
            if centre is None or not (left < centre[0] < right and top < centre[1] < bottom):
                continue
            if label_family(small["label"]) == label_family(big["label"]):
                continue
            if small["kind"] == big["kind"] and small["kind"] not in ("other_space", "other_tank"):
                continue  # a note on the same hatch or hold ("STEEL HATCH COVER"; lane W, round u6r7)
            if kinds.get(extent["view_id"]) == "profile" and side_of_label(small["label"]) in ("both", "port", "starboard"):
                continue
            found.setdefault(big["id"], []).append(small)
    return found


def _all_guessed(extent: dict) -> bool:
    return bool(extent.get("status")) and set(extent["status"].values()) == {"guessed"}


def withhold_oversized_guesses(result: dict) -> int:
    """Remove the guessed box of a short untyped label that is far larger than its label box."""
    from .ga_commercial import _named_words
    withheld = 0
    for space in result["spaces"]:
        extent = space.get("extent")
        region = (space["source_record"].get("regions") or [{}])[0].get("box_px")
        if (not extent or not region or "outline_box_px" not in extent or not _all_guessed(extent)
                or space["kind"] not in ("other_space", "other_tank")
                or len("".join(_named_words(space["label"]))) > SMALL_LABEL_LETTERS):
            continue
        left, top, right, bottom = extent["outline_box_px"]
        if (right - left > SMALL_LABEL_BOX_FACTOR * (region[2] - region[0])
                or bottom - top > SMALL_LABEL_BOX_FACTOR * (region[3] - region[1])):
            space.pop("extent")
            space["extent_withheld"] = "a guessed box far larger than the short label of a small space"
            result["checks"].append({"code": "extent_withheld", "status": "dropped", "label": space["label"][:64],
                                     "reason": "guessed box larger than its short label allows"})
            withheld += 1
    return withheld


def _end_below_spaces_above(result: dict) -> int:
    """End each tank box below the lowest space boxed inside its length in its upper part;
    its height becomes guessed. Returns how many tanks were ended."""
    kinds = {view["view_id"]: view["kind"] for view in result.get("views", [])}
    boxes = [s for s in result["spaces"] if "z_m" in (s.get("extent") or {})
             and kinds.get(s["extent"]["view_id"]) == "profile" and not s["extent"].get("projection_of")]
    ended = 0
    for tank in boxes:
        extent = tank["extent"]
        if tank["kind"] not in TANKS_ENDING_BELOW:
            continue
        x0, x1 = extent["x_m"]
        bottom, top = extent["z_m"]
        bottoms = []
        for other in boxes:
            box = other["extent"]
            if (other is tank or box["view_id"] != extent["view_id"] or other["kind"] in NOT_A_SPACE_ABOVE
                    or label_family(other["label"]) == label_family(tank["label"])):
                continue
            length = box["x_m"][1] - box["x_m"][0]
            inside = max(0.0, min(x1, box["x_m"][1]) - max(x0, box["x_m"][0]))
            starts = box["z_m"][0]
            if (length > 0 and inside / length >= INSIDE_LENGTH_SHARE
                    and bottom + UPPER_PART_SHARE * (top - bottom) < starts < top - EDGE_TOLERANCE_M):
                bottoms.append((starts, other["id"]))
        if bottoms:
            lowest, _ = min(bottoms)
            extent["z_m"] = [bottom, round(lowest, 2)]
            extent["status"]["z"] = "guessed"
            extent.setdefault("trimmed_by", []).extend(space_id for _, space_id in bottoms)
            result["checks"].append({"code": "extent_ends_below_spaces_above", "status": "changed",
                                     "label": tank["label"][:64]})
            ended += 1
    return ended


def parse_hatch_size(text: str) -> tuple[float, float] | None:
    """The two sides (metres) of a printed hatch size, or None. Numbers above 100 are millimetres
    ("15480 x 20600"); a comma is a decimal mark or, in millimetres, a thousands mark, which give
    the same metres ("15,480" is 15.48 m either way)."""
    match = HATCH_SIZE.search(text.strip())
    if not match:
        return None
    sides = []
    for number in match.group(1, 2):
        value = float(number.replace(",", "."))
        if match.group(3) == "mm" or value > 100:
            # Millimetres: a comma or dot in them is a thousands mark ("15,480 mm", "15480").
            value = float(re.sub(r"[.,]", "", number)) / 1000
        sides.append(value)
    low, high = HATCH_SIZE_RANGE_M
    return tuple(sides) if all(low <= side <= high for side in sides) else None


def apply_printed_hatch_sizes(result: dict, reported: list[dict] = ()) -> int:
    """Tie each printed hatch size to the one hatch whose box holds the text, and record it as
    the hatch's length and breadth (status ``printed``); otherwise ignore it with a reason in
    checks. Returns how many sizes were tied (PM decision, 2026-11-12)."""
    hatches = [s for s in result["spaces"] if s["kind"] == "cargo_hatch" and "outline_box_px" in (s.get("extent") or {})]
    tied = 0
    settled = set()  # spaces whose reported size was used or ignored with a reason
    for hatch in hatches:
        raw = hatch["extent"].pop("printed_size_raw", None)
        if raw is None:
            continue
        settled.add(hatch["id"])
        x, y = raw["at_px"]
        holding = [other for other in hatches if other["extent"]["view_id"] == hatch["extent"]["view_id"]
                   and other["extent"]["outline_box_px"][0] < x < other["extent"]["outline_box_px"][2]
                   and other["extent"]["outline_box_px"][1] < y < other["extent"]["outline_box_px"][3]]
        sides = parse_hatch_size(raw["text"])
        reason = (None if holding == [hatch] and sides else
                  "the size is not inside this hatch's box alone" if holding != [hatch] else
                  "the printed size is not two plausible sides")
        if reason:
            result["checks"].append({"code": "printed_hatch_size_ignored", "status": "dropped",
                                     "label": hatch["label"][:64], "reason": reason})
            continue
        # Which side is the length: the order closer to the measured box.
        extent = hatch["extent"]
        along = extent["x_m"][1] - extent["x_m"][0]
        across_axis = "y_m" if "y_m" in extent else None
        across = extent[across_axis][1] - extent[across_axis][0] if across_axis else None

        def misfit(length, breadth):
            error = abs(length - along) / along if along > 0 else 0.0
            return error + (abs(breadth - across) / across if across else 0.0)

        length, breadth = min([sides, sides[::-1]], key=lambda pair: misfit(*pair))
        extent["printed_size_m"] = {"length": round(length, 3), "breadth": round(breadth, 3), "text": raw["text"]}
        tied += 1
    # A reported size that reached no hatch box: say why, never drop it silently.
    kinds = {space["id"]: space["kind"] for space in result["spaces"]}
    for item in reported:
        if item["space_id"] in settled:
            continue
        settled.add(item["space_id"])
        reason = ("it was given for a space that is not a cargo hatch"
                  if kinds.get(item["space_id"]) != "cargo_hatch" else "its hatch has no box to tie it to")
        result["checks"].append({"code": "printed_hatch_size_ignored", "status": "dropped",
                                 "label": item["text"], "reason": reason})
    return tied


def resolve_overlaps(result: dict) -> dict:
    """Keep each extent off the labelled spaces beside it, per view; return statistics.

    - A box that holds another space's label while that space's box does not hold its own label
      takes in a neighbour. When the neighbour is a strip at one edge of the box (a double-bottom
      tank under a hold, a wing tank beside a cargo tank, a peak at a hold end), the box ends at
      the neighbour's boundary. Otherwise its axes become ``guessed``.
    - Two boxes that hold each other's labels in a profile are a projection (a wing tank drawn
      over a cargo tank): the space that is not cargo is marked ``projection_of`` and gets no
      extent in the arrangement input unless a plan gives its breadth. In a plan, both boxes are
      wrong and their y becomes ``guessed``.
    """
    stats = {"trimmed": 0, "guessed": 0, "projections": 0}
    spaces = [s for s in result["spaces"] if _span(s.get("extent", {})) and s["extent"].get("label_at_m")]
    by_view: dict[str, list[dict]] = {}
    for space in spaces:
        by_view.setdefault(space["extent"]["view_id"], []).append(space)
    cargo = ("cargo_hold", "cargo_tank")
    for members in by_view.values():
        _resolve_view_overlaps(result, members, cargo, stats)
    stats["ended_below_spaces_above"] = _end_below_spaces_above(result)
    # A box that still holds the label of a space without a box takes in that space: it is not
    # a measured boundary (its axes become guessed).
    spaces = {space["id"]: space for space in result["spaces"]}
    for big_id, neighbours in covered_labels(result).items():
        extent = spaces[big_id]["extent"]
        for axis in extent["status"]:
            extent["status"][axis] = "guessed"
        extent.setdefault("covers", []).extend(small["id"] for small in neighbours)
        stats["guessed"] += 1
        result["checks"].append({"code": "extent_covers_a_labelled_neighbour", "status": "changed",
                                 "label": f"{spaces[big_id]['label'][:30]} / {neighbours[0]['label'][:30]}"})
    # An outline traced inside the first box no longer fits a box the rules changed.
    for space in result["spaces"]:
        extent = space.get("extent") or {}
        changed = (extent.get("trimmed_by") or extent.get("covers") or extent.get("projection_of")
                   or (extent.get("basis") == "outline" and "guessed" in extent.get("status", {}).values()))
        if "outline" in extent and changed:
            extent.pop("outline")
            result["checks"].append({"code": "outline_dropped", "status": "dropped", "label": space["label"][:64],
                                     "reason": "the overlap rules changed its box"})
    return stats


def _resolve_view_overlaps(result, members, cargo, stats):
    _mark_side_projections(members, cargo, stats)
    def area(space):
        _, xs, vs = _span(space["extent"])
        return (xs[1] - xs[0]) * (vs[1] - vs[0])
    members.sort(key=area, reverse=True)
    for big in members:
        for small in members:
            _resolve_extent_pair(result, big, small, cargo, stats, area)


def _resolve_extent_pair(result, big, small, cargo, stats, area):
    if small is big or area(small) > area(big):
        return
    a, b = big["extent"], small["extent"]
    if label_family(big["label"]) == label_family(small["label"]) and big["kind"] == small["kind"]:
        return  # the same space read twice
    a_holds_b, b_holds_a = _holds(a, b["label_at_m"]), _holds(b, a["label_at_m"])
    other, axs, avs = _span(a)
    if a_holds_b and b_holds_a:
        if other == "z_m":
            for this, that in ((big, small), (small, big)):
                if this["kind"] not in cargo and that["kind"] in cargo:
                    this["extent"]["projection_of"] = that["id"]
                    stats["projections"] += 1
        else:
            for this in (big, small):
                this["extent"]["status"]["y"] = "guessed"
            stats["guessed"] += 2
            result["checks"].append({"code": "plan_boxes_hold_each_others_labels", "status": "changed",
                                     "label": f"{big['label'][:30]} / {small['label'][:30]}"})
        return
    if not a_holds_b:
        return
    _, bxs, bvs = _span(b)
    trimmed = False
    if _span(b)[0] == other and _cover(axs, bxs) >= STRIP_COVER:
        if bvs[0] <= avs[0] + EDGE_TOLERANCE_M < bvs[1] < avs[1]:
            a[other][0] = round(bvs[1], 2)  # the neighbour is a strip along the bottom or one side
            trimmed = True
        elif avs[0] < bvs[0] < avs[1] - EDGE_TOLERANCE_M <= bvs[1]:
            a[other][1] = round(bvs[0], 2)  # along the top or the other side
            trimmed = True
    elif _span(b)[0] == other and _cover(avs, bvs) >= STRIP_COVER and "frames" in b:
        if bxs[0] <= axs[0] + EDGE_TOLERANCE_M < bxs[1] < axs[1]:
            a["frames"][0], a["x_m"][0] = b["frames"][1], b["x_m"][1]
            a["x_measured_m"] = [round(bxs[1], 2), a["x_measured_m"][1]] if "x_measured_m" in a else None
            trimmed = True
        elif axs[0] < bxs[0] < axs[1] - EDGE_TOLERANCE_M <= bxs[1]:
            a["frames"][1], a["x_m"][1] = b["frames"][0], b["x_m"][0]
            a["x_measured_m"] = [a["x_measured_m"][0], round(bxs[0], 2)] if "x_measured_m" in a else None
            trimmed = True
    if a.get("x_measured_m") is None:
        a.pop("x_measured_m", None)
    if trimmed:
        a.setdefault("trimmed_by", []).append(small["id"])
        stats["trimmed"] += 1
    elif (other == "z_m" and big["kind"] in cargo and small["kind"] not in cargo
            and side_of_label(small["label"]) in ("both", "port", "starboard")):
        # A tank printed for the sides ("(P/S)") inside a cargo space in the profile, and
        # not a strip at its edge, is a wing, topside or hopper tank seen in projection
        # (round u6: topside fuel tanks boxed over the holds).
        b["projection_of"] = big["id"]
        stats["projections"] += 1
        return
    if _holds(a, b["label_at_m"]):
        for axis in a["status"]:
            a["status"][axis] = "guessed"
        a.setdefault("covers", []).append(small["id"])
        stats["guessed"] += 1
        result["checks"].append({"code": "extent_covers_a_labelled_neighbour", "status": "changed",
                                 "label": f"{big['label'][:30]} / {small['label'][:30]}"})


def _mark_side_projections(members, cargo, stats):
    # A tank printed for the sides that overlaps a cargo space in the profile (topside, wing or
    # hopper tanks; round u6: topside tanks over two holds) is a projection, whichever hold
    # its label lies over.
    for tank in members:
        span = _span(tank["extent"])
        if (span[0] != "z_m" or tank["kind"] in cargo
                or side_of_label(tank["label"]) not in ("both", "port", "starboard")):
            continue
        for hold in members:
            if hold["kind"] not in cargo:
                continue
            _, hxs, hvs = _span(hold["extent"])
            if (_cover(hxs, span[1]) > 0.2 and _cover(hvs, span[2]) > 0.2
                    and not (span[2][1] <= hvs[0] + EDGE_TOLERANCE_M)):  # not a tank under the hold
                tank["extent"]["projection_of"] = hold["id"]
                stats["projections"] += 1
                break
