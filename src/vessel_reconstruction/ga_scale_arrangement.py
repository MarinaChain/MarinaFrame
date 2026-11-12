"""Commercial GA arrangement; rules and constants unchanged."""
from __future__ import annotations

from . import source_record
from .ga_labels import label_family
from .ga_scale_geometry import (
    _unknown,
    side_of_label,
)
from .ga_scale_overlaps import (
    _all_guessed,
)
from .ga_scale_settings import (
    AT_SHELL_SHARE,
    CARGO_CONFLICT_SHARE,
    CARGO_KINDS,
    CENTRE_TOLERANCE_M,
    COVERAGE_KINDS,
    DECK_EQUIPMENT,
    DECK_EQUIPMENT_GAP_M,
    GATE_GRID,
    GATE_KINDS,
    GATE_MAX_CARGO_LOSS,
    GUESSED_OVER_CARGO_SHARE,
    INPUT_SCHEMA,
    LOWER_TANK,
    OFF_CENTRE_SHARE,
    PRINTED,
    SAME_BOX_SHARE,
    SHELL_BOX_MAX_CARGO_SHARE,
    SIDE_WORDS,
    UPPER_BAND_SHARE,
)
import numpy as np
import re


# ------------------------------------------------------------------ the arrangement input

def _identity(space: dict) -> tuple:
    """What makes two labels the same physical space in two views (the side left out)."""
    from .ga_commercial import _base_number, COUNT_KINDS
    if space["kind"] in COUNT_KINDS.values() and space.get("number"):
        return space["kind"], _base_number(space["number"])
    if space.get("number"):
        # A numbered tank: its number and the words of its label ("NO. 4 W. B. TK (P)" in a plan
        # is "4 W. B. TK (P&S)" in the profile; round u6).
        return space["kind"], _base_number(space["number"]), label_family(space["label"])
    text = space["label"].upper()
    for pattern, _ in SIDE_WORDS:
        text = re.sub(pattern, "", text)
    return space["kind"], re.sub(r"[^A-Z0-9]", "", text)


def _sides(space: dict) -> set[str]:
    side = space["extent"].get("side")
    return {"port", "starboard"} if side == "both" else {side} if side else set()


def merged_spaces(result: dict) -> list[dict]:
    """One entry per physical space: x and z from the profile, y from a plan.

    A reading lists a numbered hold or tank once in each view. Views of the same space are
    joined by kind and number (or label); a plan entry of one side takes the profile entry
    that is printed for both sides.
    """
    kinds = {v["view_id"]: v["kind"] for v in result.get("views", [])}
    groups: dict[tuple, list[dict]] = {}
    plain = []
    for space in result["spaces"]:
        if "extent" in space:
            groups.setdefault(_identity(space), []).append(space)
        else:
            plain.append({key: space[key] for key in ("id", "kind", "label", "number", "status", "source_record",
                                                      "extent_withheld") if key in space})
    merged = []
    for members in groups.values():
        members = _without_repeats(members)
        profiles = [s for s in members if kinds.get(s["extent"]["view_id"]) == "profile"]
        plans = [s for s in members if s not in profiles]
        used_profiles = set()
        seen = []
        for plan in plans:
            if plan["kind"] == "cargo_hold" and seen:
                # A hold spans the breadth and is not split by side: a second plan entry of the same
                # numbered hold is a second reading, whatever its note says ("(PORT USE W. B.)"
                # read as a port side; round u10).
                continue
            side = plan["extent"].get("side")
            # The same space in a second plan view: its sides are already given over the same
            # frames ("(P&S)" on the tank top repeats "(P)" and "(S)" of the deck plan).
            covered = set().union(*[_sides({"extent": other}) for other in seen
                                    if _overlap(plan["extent"], other) > 0.5])
            if _sides(plan) and _sides(plan) <= covered:
                continue
            seen.append(plan["extent"])
            partner = next((p for p in profiles if _overlap(plan["extent"], p["extent"]) > 0.5
                            and (not _sides(p) or not side or side in _sides(p) or side == "centre")), None)
            merged.append(_joined(plan, partner))
            if partner:
                used_profiles.add(partner["id"])
        group = [entry for entry in merged if any(m["id"] == entry["id"] for m in members)]
        for profile in profiles:
            if profile["id"] in used_profiles:
                continue
            if any(_overlap(profile["extent"], entry["extent"]) > 0.5 for entry in group):
                continue  # a second reading of a space already given over the same frames (round u6)
            merged.append(_joined(None, profile))
            group.append(merged[-1])  # a later profile reading of the same space is checked against it
    kinds_of_view = {v["view_id"]: v["kind"] for v in result.get("views", [])}
    cargo_footprints = [e["extent"] for e in merged
                        if e["kind"] in ("cargo_hold", "cargo_tank") and "y_m" in e["extent"]]
    out = []
    for entry in merged:
        extent = entry["extent"]
        if (entry["kind"] == "other_space" and "z_m" not in extent and "y_m" in extent
                and all(kinds_of_view.get(view) == "deck_plan" for view in entry.get("views", []))
                and any(_footprint_share(extent, cargo) >= 0.5 for cargo in cargo_footprints)):
            # A room seen only on a deck plan over a hold or cargo tank stands on the deck (a store,
            # a deck house) or is a cut label; as a box from the base line it would take the cargo
            # space's volume (round u6).
            entry = {key: value for key, value in entry.items() if key != "extent"}
            entry["extent_withheld"] = "seen only on the deck plan, over a cargo space; its height is not known"
            out.append(entry)
            continue
        if entry["extent"].get("projection_of") and "y_m" not in entry["extent"]:
            # A tank drawn over a cargo space in the profile, with no plan to give its breadth:
            # as a full-breadth box it would take the cargo space's volume.
            entry = {key: value for key, value in entry.items() if key != "extent"}
            entry["extent_withheld"] = "drawn over a cargo space in the profile; no plan gives its breadth"
            out.append(entry)
            continue
        out.extend(_split_pair(entry))
    return out + plain


def _split_pair(entry: dict) -> list[dict]:
    """A pair printed for both sides ("(P&S)") whose plan box lies on one side: two spaces.

    The model boxes the tank on the side where its label is; the other tank of the pair is its
    mirror about the centreline (status ``guessed``). As one entry with ``side: both`` the
    pair would read as one space across the whole y range (development round 3: wing tanks of
    a pair given as one, so the cargo tank between them looked full breadth).
    """
    extent = entry["extent"]
    if extent.get("side") != "both" or side_of_label(entry["label"]) != "both":
        return [entry]
    if "y_m" not in extent:
        # No plan breadth: one tank on each side (the arrangement step then gives each half the
        # breadth). As one "both" entry it reads as one space (lane W, round u6).
        return [{**entry, "id": f"{entry['id']}-{side[0]}", "extent": {**extent, "side": side}}
                for side in ("port", "starboard")]
    low, high = extent["y_m"]
    if low < -CENTRE_TOLERANCE_M and high > CENTRE_TOLERANCE_M:
        # Boxed across the centreline: the label says two tanks, split at the centreline.
        halves = _without_outline(extent, "xy")
        return [{**entry, "id": f"{entry['id']}-p", "extent": {**halves, "side": "port", "y_m": [0.0, high]}},
                {**entry, "id": f"{entry['id']}-s", "extent": {**halves, "side": "starboard", "y_m": [low, 0.0]}}]
    boxed = "port" if low >= -CENTRE_TOLERANCE_M else "starboard"
    other = "starboard" if boxed == "port" else "port"
    first = {**entry, "id": f"{entry['id']}-{boxed[0]}", "extent": {**extent, "side": boxed}}
    mirror_extent = {**extent, "side": other, "y_m": [round(-high, 2), round(-low, 2)],
                     "status": {**extent["status"], "y": "guessed"},
                     "y_note": "mirror of the other tank of the pair about the centreline"}
    if extent.get("outline_m"):
        mirror_extent["outline_m"] = [
            {**outline, "points": [[x, round(-v, 2)] for x, v in outline["points"]], "status": "guessed"}
            if outline["plane"] == "xy" else outline for outline in extent["outline_m"]]
    second = {**entry, "id": f"{entry['id']}-{other[0]}", "extent": mirror_extent}
    return [first, second]


def _without_outline(extent: dict, plane: str) -> dict:
    """The extent without its outline in ``plane`` (an axis of that plane was changed)."""
    kept = [outline for outline in extent.get("outline_m", []) if outline["plane"] != plane]
    extent = {key: value for key, value in extent.items() if key != "outline_m"}
    if kept:
        extent["outline_m"] = kept
    return extent


def _footprint_share(a: dict, b: dict) -> float:
    """The share of extent ``a``'s plan footprint (x by y) that lies over extent ``b``'s."""
    xa, ya, xb, yb = a["x_m"], a["y_m"], b["x_m"], b["y_m"]
    area = (xa[1] - xa[0]) * (ya[1] - ya[0])
    shared = (max(0.0, min(xa[1], xb[1]) - max(xa[0], xb[0])) * max(0.0, min(ya[1], yb[1]) - max(ya[0], yb[0])))
    return shared / area if area > 0 else 0.0


def _overlap(a: dict, b: dict) -> float:
    """The shared length of two extents as a share of the shorter one."""
    shared = min(a["x_m"][1], b["x_m"][1]) - max(a["x_m"][0], b["x_m"][0])
    shorter = min(a["x_m"][1] - a["x_m"][0], b["x_m"][1] - b["x_m"][0])
    return shared / shorter if shorter > 0 else 0.0


def _without_repeats(members: list[dict]) -> list[dict]:
    """One entry where a view lists the same space twice (both passes read its label)."""
    kept: list[dict] = []
    # A boundary that was seen goes before one placed from the label.
    for space in sorted(members, key=lambda s: s["extent"]["basis"] != "outline"):
        extent = space["extent"]
        if not any(extent["view_id"] == other["extent"]["view_id"] and extent.get("side") == other["extent"].get("side")
                   and _overlap(extent, other["extent"]) > 0.5 for other in kept):
            kept.append(space)
    return kept


def _joined(plan: dict | None, profile: dict | None) -> dict:
    first = plan or profile
    extent = {"status": {}}
    x_source = profile or plan
    extent["frames"] = x_source["extent"]["frames"]
    extent["x_m"] = x_source["extent"]["x_m"]
    extent["status"]["x"] = x_source["extent"]["status"]["x"]
    if profile and "z_m" in profile["extent"]:
        extent["z_m"] = profile["extent"]["z_m"]
        extent["status"]["z"] = profile["extent"]["status"]["z"]
    if plan and "y_m" in plan["extent"]:
        extent["y_m"] = plan["extent"]["y_m"]
        extent["status"]["y"] = plan["extent"]["status"]["y"]
    side = (plan or profile)["extent"].get("side")
    if side:
        extent["side"] = side
    if profile and profile["extent"].get("projection_of"):
        extent["projection_of"] = profile["extent"]["projection_of"]
    # Optional traces of a boundary that is not a rectangle: x and z from the profile, x and y
    # from the plan (lane W's builder may ignore them; an entry without them is as before).
    outlines = [{"plane": source["extent"]["outline"]["plane"], "points": source["extent"]["outline"]["points_m"],
                 "status": source["extent"]["outline"]["status"]}
                for source, plane in ((profile, "xz"), (plan, "xy"))
                if source and source["extent"].get("outline", {}).get("plane") == plane]
    if outlines:
        extent["outline_m"] = outlines
    sized = next((s["extent"]["printed_size_m"] for s in (plan, profile) if s and s["extent"].get("printed_size_m")),
                 None)
    if sized:
        # A printed hatch size is the hatch's length and breadth; the measured box gives its place.
        extent["measured_box_m"] = {key: extent[key] for key in ("x_m", "y_m") if key in extent}
        middle = (extent["x_m"][0] + extent["x_m"][1]) / 2
        extent["x_m"] = [round(middle - sized["length"] / 2, 2), round(middle + sized["length"] / 2, 2)]
        extent["status"]["x"] = PRINTED
        if "y_m" in extent:
            middle = (extent["y_m"][0] + extent["y_m"][1]) / 2
            extent["y_m"] = [round(middle - sized["breadth"] / 2, 2), round(middle + sized["breadth"] / 2, 2)]
            extent["status"]["y"] = PRINTED
        extent["printed_size"] = sized["text"]
        extent.pop("outline_m", None)  # a trace of the measured box, not of the printed size
    regions = [region for space in (plan, profile) if space
               for region in space["source_record"].get("regions", [])][:source_record.MAX_REGIONS]
    return {"id": first["id"], "kind": first["kind"], "label": first["label"], "number": first.get("number"),
            "status": first["status"], "source_record": source_record.validate(source_record.read(regions)),
            "views": [s["extent"]["view_id"] for s in (plan, profile) if s], "extent": extent}


def _gate_box(space: dict, breadth: float, depth: float) -> np.ndarray | None:
    """A space's box with the arrangement step's rules for a missing y or z."""
    extent = space.get("extent")
    if not extent or "x_m" not in extent:
        return None
    side = extent.get("side", "both")
    y = extent.get("y_m") or {"port": [0.0, breadth / 2], "starboard": [-breadth / 2, 0.0],
                              "centre": [-0.15 * breadth, 0.15 * breadth]}.get(side, [-breadth / 2, breadth / 2])
    z = extent.get("z_m") or [0.0, depth]
    return np.array([sorted(extent["x_m"]), sorted(y), sorted(z)], dtype=float)


def arrangement_gate(data: dict) -> dict:
    """The arrangement step's gate on an arrangement input, for regression checks.

    Spaces are cut from the smallest to the largest (each loses the parts that smaller spaces
    cover); the hull is not modelled. Returns the spaces left without volume, the fragment
    labels, each cargo space's loss, the spaces guessed on every axis that cover a cargo space
    (lane W, round u6r3), and ``passed``.
    """
    from .ga_commercial import _words, fragment_reason
    particulars = data.get("particulars", {})
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    spaces = [s for s in data["spaces"] if s["kind"] in GATE_KINDS]
    vocabulary_of = lambda space: {w for o in data["spaces"] if o is not space for w in _words(o["label"])}
    fragments = [s["label"] for s in data["spaces"]
                 if fragment_reason(s, [o for o in data["spaces"] if o is not s], vocabulary_of(s),
                                    {"".join(_words(o["label"])) for o in data["spaces"] if o is not s})]
    report = {"fragments": fragments, "no_volume": [], "cargo_loss": {}, "max_cargo_loss": None,
              "depth_status": (particulars.get("depth_m") or {}).get("status"),
              "guessed_over_cargo": []}
    if breadth and depth:
        report["guessed_over_cargo"] = [s["label"] for s in _guessed_over_cargo(spaces, breadth, depth)]
        boxes = [(s, _gate_box(s, breadth, depth)) for s in spaces]
        boxes = [(s, b) for s, b in boxes if b is not None and np.all(b[:, 1] > b[:, 0])]
        volume = lambda b: float(np.prod(b[:, 1] - b[:, 0]))
        for space, own in boxes:
            grid = np.meshgrid(*[np.linspace(own[i, 0], own[i, 1], GATE_GRID + 2)[1:-1] for i in range(3)],
                               indexing="ij")
            taken = np.zeros(grid[0].shape, dtype=bool)
            for other, box in boxes:
                if other is not space and volume(box) < volume(own):
                    taken |= np.all([(grid[i] > box[i, 0]) & (grid[i] < box[i, 1]) for i in range(3)], axis=0)
            loss = float(taken.mean())
            if loss >= 0.999:
                report["no_volume"].append(space["id"])
            if space["kind"] in ("cargo_hold", "cargo_tank"):
                report["cargo_loss"][space["id"]] = round(loss, 3)
        report["max_cargo_loss"] = max(report["cargo_loss"].values(), default=None)
    # Coverage warnings (not failures): a kind of tank with no extent on a ship whose other
    # spaces have extents; the fine pass reads different labels from run to run (PM, round u9n2).
    boxed = {s["kind"] for s in data["spaces"] if s.get("extent")}
    report["warnings"] = [f"no {kind.replace('_', ' ')} has an extent" for kind in COVERAGE_KINDS
                          if boxed and kind not in boxed]
    report["passed"] = (not report["fragments"] and not report["no_volume"] and not report["guessed_over_cargo"]
                        and (report["max_cargo_loss"] or 0.0) <= GATE_MAX_CARGO_LOSS)
    return report


def arrangement_input(result: dict, case_id: str) -> dict:
    """The reading in the form of docs/GA_ARRANGEMENT_INPUT.md.

    A particular is the printed value (status ``read``) when the drawing prints it, else the
    value measured with the frame scale (status ``measured_from_scale``), else null. This file
    is for the arrangement step only; the GA exam reads ``ga_reading.json``.
    """
    particulars = {}
    for field in ("loa_m", "lbp_m", "breadth_m", "depth_m"):
        printed = result.get("particulars", {}).get(field) or {}
        measured = (result.get("measured") or {}).get(field) or {}
        if printed.get("value") is not None:
            particulars[field] = {key: printed[key] for key in ("value", "status", "source_record")}
        elif measured.get("value") is not None:
            # The status says what the value is: measured_from_scale, or derived_from_space_tops.
            particulars[field] = {key: measured[key] for key in
                                  ("value", "status", "uncertainty_m", "method", "note", "reason", "pointed_depth_m",
                                   "cross_check", "source_record") if key in measured}
        else:
            reason = measured.get("reason") or printed.get("reason") or "not printed and not measured"
            particulars[field] = _unknown(reason)
    frames = result.get("frames") or {"status": "unknown", "spacings": []}
    spaces, dropped = _without_same_boxes(merged_spaces(result), particulars)
    spaces = _without_outboard_extents(spaces, particulars)
    spaces = _centred_when_off_centre(spaces, particulars)
    spaces = _deck_equipment_on_the_deck(spaces, particulars)
    spaces = _side_boxes_without_height(spaces, particulars)
    spaces = _without_guessed_over_cargo(spaces, particulars)
    spaces = _without_cargo_number_conflicts(spaces, particulars)
    from .ga_scale_chain import holds_with_printed_spans
    spaces = holds_with_printed_spans(spaces, result.get("frames") or {})
    return {"schema": INPUT_SCHEMA, "case_id": case_id, "engineering_approved": False,
            "sources": result["sources"], "ship_type": result.get("ship_type"),
            "particulars": particulars, "frames": frames, "spaces": spaces, "dropped": dropped}


def _guessed_over_cargo(spaces: list[dict], breadth: float, depth: float) -> list[dict]:
    """The spaces (not cargo) whose extent is guessed on every axis and covers a cargo space,
    with the missing y and z filled by the arrangement step's rules. A box against the shell (a
    side tank) counts only when it takes more than ``SHELL_BOX_MAX_CARGO_SHARE`` of the cargo
    space."""
    cargo = [box for space in spaces if space["kind"] in CARGO_KINDS
             and (box := _gate_box(space, breadth, depth)) is not None]
    found = []
    for space in spaces:
        extent = space.get("extent")
        if not extent or space["kind"] in CARGO_KINDS + DECK_EQUIPMENT or not _all_guessed(extent):
            continue  # a hatch or crane stands on the deck above the cargo space
        own = _gate_box(space, breadth, depth)
        if own is None or not np.all(own[:, 1] > own[:, 0]):
            continue
        at_shell = max(abs(own[1, 0]), abs(own[1, 1])) >= AT_SHELL_SHARE * breadth / 2
        volume = float(np.prod(own[:, 1] - own[:, 0]))
        for box in cargo:
            shared = float(np.prod(np.clip(np.minimum(own[:, 1], box[:, 1]) - np.maximum(own[:, 0], box[:, 0]),
                                           0.0, None)))
            if (shared > SHELL_BOX_MAX_CARGO_SHARE * float(np.prod(box[:, 1] - box[:, 0])) if at_shell
                    else shared > GUESSED_OVER_CARGO_SHARE * volume):
                found.append(space)
                break
    return found


def _deck_equipment_on_the_deck(spaces: list[dict], particulars: dict) -> list[dict]:
    """Cranes and hatches reach down to the deck; the extended bottom is guessed."""
    depth = (particulars.get("depth_m") or {}).get("value")
    if not depth:
        return spaces
    kept = []
    for space in spaces:
        extent = space.get("extent") or {}
        z = extent.get("z_m")
        if space["kind"] in DECK_EQUIPMENT and z and z[0] > depth + DECK_EQUIPMENT_GAP_M:
            extent = {**_without_outline(extent, "xz"), "z_m": [round(depth, 2), z[1]],
                      "status": {**extent["status"], "z": "guessed"},
                      "z_note": "the box began above the deck; extended down to the deck it stands on"}
            space = {**space, "extent": extent}
        kept.append(space)
    return kept


def _centred_when_off_centre(spaces: list[dict], particulars: dict) -> list[dict]:
    """A hold, or a space on the centreline, boxed clearly off the centreline: its y is centred
    with the same breadth and becomes guessed."""
    breadth = (particulars.get("breadth_m") or {}).get("value")
    if not breadth:
        return spaces
    kept = []
    for space in spaces:
        extent = space.get("extent") or {}
        y = extent.get("y_m")
        on_centre = space["kind"] == "cargo_hold" or extent.get("side") in ("centre", "both")
        if y and on_centre and abs(y[0] + y[1]) > OFF_CENTRE_SHARE * breadth:
            half = min((y[1] - y[0]) / 2, breadth / 2)
            extent = {**_without_outline(extent, "xy"), "y_m": [round(-half, 2), round(half, 2)],
                      "status": {**extent.get("status", {}), "y": "guessed"},
                      "y_note": "boxed off the centreline; centred with the same breadth"}
            space = {**space, "extent": extent}
        kept.append(space)
    return kept


def _side_boxes_without_height(spaces: list[dict], particulars: dict) -> list[dict]:
    """A tank against the shell guessed on every axis with no drawn height (no profile box) goes
    in an upper band under the deck; one named as a lower tank (double bottom, hopper) loses its
    extent instead."""
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    if not breadth or not depth:
        return spaces
    kept = []
    for space in spaces:
        extent = space.get("extent") or {}
        y = extent.get("y_m")
        if (extent and y and "z_m" not in extent and _all_guessed(extent)
                and space["kind"] not in CARGO_KINDS + DECK_EQUIPMENT
                and max(abs(y[0]), abs(y[1])) >= AT_SHELL_SHARE * breadth / 2):
            if LOWER_TANK.search(space["label"].upper()):
                space = {key: value for key, value in space.items() if key != "extent"}
                space["extent_withheld"] = "guessed against the shell with no height drawn"
            else:
                extent = {**extent, "z_m": [round(depth * (1 - UPPER_BAND_SHARE), 2), round(depth, 2)],
                          "status": {**extent["status"], "z": "guessed"},
                          "z_note": "no height drawn: placed in the upper part, under the deck"}
                space = {**space, "extent": extent}
        kept.append(space)
    return kept


def _without_cargo_number_conflicts(spaces: list[dict], particulars: dict) -> list[dict]:
    """Two cargo spaces with different numbers boxed at one place: the views read the number
    differently (round u10: "NO.2", "NO.3" and "NO.5" at the same frames in three views), and
    code cannot tell which reading is right, so both lose their extents."""
    from .ga_commercial import _base_number
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    if not breadth or not depth:
        return spaces
    cargo = [(space, box) for space in spaces if space["kind"] in CARGO_KINDS and space.get("number")
             and (box := _gate_box(space, breadth, depth)) is not None and np.all(box[:, 1] > box[:, 0])]
    conflicting = set()
    for index, (a, box_a) in enumerate(cargo):
        for b, box_b in cargo[index + 1:]:
            if a["kind"] != b["kind"] or _base_number(a["number"]) == _base_number(b["number"]):
                continue
            shared = float(np.prod(np.clip(np.minimum(box_a[:, 1], box_b[:, 1])
                                           - np.maximum(box_a[:, 0], box_b[:, 0]), 0.0, None)))
            smaller = min(float(np.prod(box_a[:, 1] - box_a[:, 0])), float(np.prod(box_b[:, 1] - box_b[:, 0])))
            if shared > CARGO_CONFLICT_SHARE * smaller:
                conflicting.update((id(a), id(b)))
    kept = []
    for space in spaces:
        if id(space) in conflicting:
            space = {key: value for key, value in space.items() if key != "extent"}
            space["extent_withheld"] = "another cargo space with a different number is boxed at the same place"
        kept.append(space)
    return kept


def _without_guessed_over_cargo(spaces: list[dict], particulars: dict) -> list[dict]:
    """A box guessed on every axis does not cover a labelled cargo space (lane W, round u6r3: a
    small tank guessed along a whole hold took its port side): it loses its extent."""
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    if not breadth or not depth:
        return spaces
    covering = {id(space) for space in _guessed_over_cargo(spaces, breadth, depth)}
    kept = []
    for space in spaces:
        if id(space) in covering:
            space = {key: value for key, value in space.items() if key != "extent"}
            space["extent_withheld"] = "guessed on every axis and over a cargo space"
        kept.append(space)
    return kept


def _without_outboard_extents(spaces: list[dict], particulars: dict) -> list[dict]:
    """No space extent outside the hull: a box whose breadth lies mostly outboard of the half
    breadth (a ladder or a boat beside the ship; lane W, round u6r) loses its extent."""
    breadth = (particulars.get("breadth_m") or {}).get("value")
    if not breadth:
        return spaces
    half = breadth / 2
    kept = []
    for space in spaces:
        y = (space.get("extent") or {}).get("y_m")
        if y and y[1] > y[0]:
            outside = max(0.0, y[1] - max(y[0], half)) + max(0.0, min(y[1], -half) - y[0])
            if outside / (y[1] - y[0]) > 0.5:
                space = {key: value for key, value in space.items() if key != "extent"}
                space["extent_withheld"] = "outboard of the hull: not a space inside the ship"
        kept.append(space)
    return kept


def _without_same_boxes(spaces: list[dict], particulars: dict) -> tuple[list[dict], list[dict]]:
    """One entry per box: two labels on one compartment (a misread repeat, a cut label) give
    two boxes, and the arrangement step would leave one of them without volume (round u6).

    The entry kept is the one with a counted or named kind, then a printed number, then the
    longer label; the other is listed in ``dropped`` with the reason.
    """
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    if not breadth or not depth:
        return spaces, []
    boxes = {id(s): _gate_box(s, breadth, depth) for s in spaces if s["kind"] in GATE_KINDS}

    def rank(space):
        return (not space["kind"].startswith("other_"), bool(space.get("number")), len(space["label"]))

    dropped_ids, dropped = set(), []
    order = sorted((s for s in spaces if boxes.get(id(s)) is not None), key=rank, reverse=True)
    for index, keep in enumerate(order):
        if id(keep) in dropped_ids:
            continue
        a = boxes[id(keep)]
        for other in order[index + 1:]:
            if id(other) in dropped_ids:
                continue
            b = boxes[id(other)]
            shared = float(np.prod(np.clip(np.minimum(a[:, 1], b[:, 1]) - np.maximum(a[:, 0], b[:, 0]), 0, None)))
            if min(shared / float(np.prod(a[:, 1] - a[:, 0])), shared / float(np.prod(b[:, 1] - b[:, 0]))) >= SAME_BOX_SHARE:
                dropped_ids.add(id(other))
                dropped.append({"id": other["id"], "label": other["label"],
                                "reason": f"the same box as {keep['id']} ({keep['label'][:40]})"})
    return [s for s in spaces if id(s) not in dropped_ids], dropped
