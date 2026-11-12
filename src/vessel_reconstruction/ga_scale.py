"""Measure a commercial GA with its own printed frame scale.

Plan: docs/plans/2026-11-12-ga-commercial.md ("Measured from the frame scale").

A GA prints a frame scale: frame numbers along the base line of the profile (and often along
the centreline of the plans) and the frame spacings ("FR. SP. = 800 MM") with the places where
the spacing changes. With them, drawn ink can be measured in metres.

Division of work:

- The model (purpose ``ga_scale``; up to seven requests a ship: the scale request, sent again
  while the scale is not established, then up to four extents requests) only points: at frame numbers,
  at the marks A.P. and F.P., at the spacing texts and the places where the spacing changes, at a few
  named places of the hull, and at the drawn boundary of each space that was read.
- Code builds the frame-spacing table, fits pixels to metres on every view with a frame scale
  (robust to a misread number), and measures LBP, LOA, depth, breadth and the extent of each
  space. When the scale cannot be established (no spacing printed, too few frame numbers, the
  numbers do not fit the spacings) every measured value is null with the reason.

A measured value has status ``measured_from_scale``. It is never a printed particular: the
``particulars`` of a reading hold printed values only (the GA exam scores those), and measured
values live in ``measured``. ``arrangement_input`` writes the file the arrangement step reads
(docs/GA_ARRANGEMENT_INPUT.md), where a particular is the printed value when there is one and
else the measured one, with its status.

Axes: metres; x forward from the aft perpendicular (frame 0), y to port, z up from the base line."""
from __future__ import annotations

from . import source_record
from .ga_scale_depth import (
    check_depth,
)
from .ga_scale_dimensions import (
    read_scale,
)
from .ga_scale_extents import (
    read_extents,
)
from .ga_scale_geometry import (
    _unknown,
)
from .ga_scale_overlaps import (
    _label_centre,
    apply_printed_hatch_sizes,
    covered_labels,
    resolve_overlaps,
    withhold_oversized_guesses,
)
from .ga_scale_requests import (
    missing_places,
    prepare_extents,
    prepare_scale,
)
from .ga_scale_settings import (
    DECK_EQUIPMENT,
    DERIVED,
    MEASURED,
    REDRAW_MIN_AREA_SHARE,
    SCALE_ATTEMPTS,
)
from pathlib import Path
import json


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def redraw_covering_boxes(result: dict, work: dict, sheet_path: Path, out: Path, call, readings: list) -> dict:
    """One more request for the boxes that hold the label of a space without a box (review round 4).

    The request names, per box, the labels it must leave out. A redrawn box is kept only when it
    holds none of them; otherwise the first box stays (and the overlap rules mark it guessed).
    """
    covered = covered_labels(result)
    if not covered:
        return {}
    spaces = {space["id"]: space for space in result["spaces"]}
    directories = prepare_extents(result, sheet_path, out / "extents-redraw", only_ids=set(covered), exclude=covered)
    if not directories:
        return {}
    directory = directories[0]
    asked = {entry["space_id"] for entry in json.loads((directory / "request.json").read_text())["context"]["spaces"]}
    first = {space_id: spaces[space_id].pop("extent") for space_id in asked}
    readings.append(call(directory, directory.with_name(f"{directory.name}-provider")))
    read_extents(result, work, readings[-1], directory)
    def holds(box, space):
        centre = _label_centre(space)
        return centre is not None and box[0] < centre[0] < box[2] and box[1] < centre[1] < box[3]

    kept = 0
    for space_id, old in first.items():
        new = spaces[space_id].get("extent")
        if new is not None:
            inside = [other for other in covered[space_id] if holds(new["outline_box_px"], other)]
            # A box shrunk off its own label is not the space (round u6r5: cargo tanks redrawn
            # as a strip at the bottom to leave out a label).
            lost_own = holds(old["outline_box_px"], spaces[space_id]) and not holds(new["outline_box_px"],
                                                                                  spaces[space_id])
            shrunk = _area(new["outline_box_px"]) < REDRAW_MIN_AREA_SHARE * _area(old["outline_box_px"])
            if not inside and not lost_own and not shrunk:
                new["redrawn"] = "drawn again without the labels of the spaces beside it"
                if "printed_size_raw" in old and "printed_size_raw" not in new:
                    # The text's place does not depend on the box (round hS2: a redrawn hatch lost its size).
                    new["printed_size_raw"] = old["printed_size_raw"]
                kept += 1
                continue
        spaces[space_id]["extent"] = old
    return {"redraw_requests": 1, "redraw_asked": len(asked), "redraw_kept": kept}


def scale_pass(result: dict, sheet_path: Path, out: Path, call) -> dict:
    """Run both ``ga_scale`` requests for one ship. ``call(request_dir, out_dir)`` sends one request."""
    stats = {"requests": 0}
    readings = []
    if "ga" not in result.get("sources", {}) or not prepare_scale(result, sheet_path, out / "scale"):
        reason = "no profile or plan view was found on the sheet"
        result["frames"] = {"status": "unknown", "spacings": [], "reason": reason,
                            "source_record": source_record.unknown(reason)}
        result["measured"] = {field: _unknown(reason) for field in ("lbp_m", "loa_m", "breadth_m", "depth_m")}
        return stats
    # Small print is read differently from one request to the next: while the scale is not
    # established, the scale request is sent again and the marks of all replies are read together.
    work = None
    for attempt in range(1, SCALE_ATTEMPTS + 1):
        name = "scale" if attempt == 1 else f"scale-{attempt}"
        if attempt > 1:
            prepare_scale(result, sheet_path, out / name, result["frames"].get("reason"))
        readings.append(call(out / name, out / f"{name}-provider"))
        combined = read_scale(result, readings[-1], out / name, work)
        if combined.get("table") is None and work is not None:
            # The marks of earlier replies can spoil a clean reply (round u8: changes of spacing
            # drawn on one side of a local spacing only in the first reply); this reply alone.
            alone = read_scale(result, readings[-1], out / name)
            if alone.get("table") is not None:
                combined = alone
            else:
                combined = read_scale(result, readings[-1], out / name, work)  # its reason is kept
        work = combined
        if work.get("table") is not None:
            break
    stats["scale_attempts"] = attempt
    stats["frames"] = result["frames"]["status"]
    stats["measured"] = sorted(k for k, v in result["measured"].items() if v["status"] == MEASURED)
    checked = False
    directories = (prepare_extents(result, sheet_path, out / "extents", missing_places(work))
                   if work.get("table") is not None else [])
    if directories:
        totals: dict = {}
        for directory in directories:
            readings.append(call(directory, directory.with_name(f"{directory.name}-provider")))
            part = read_extents(result, work, readings[-1], directory)
            for key, value in part.items():
                totals[key] = totals.get(key, 0) + value if isinstance(value, int) else value
        # Deck equipment (cranes, hatch covers) is few and comes late in the priority order; when
        # the spaces fill the requests it is left without an extent (lane W, round u6r: three cranes
        # skipped). One more request asks for the cranes and hatches still without one.
        deck = {space["id"] for space in result["spaces"]
                if space["kind"] in DECK_EQUIPMENT and space["status"] == "read" and "extent" not in space}
        if deck:
            for directory in prepare_extents(result, sheet_path, out / "extents-deck", only_ids=deck)[:1]:
                readings.append(call(directory, directory.with_name(f"{directory.name}-provider")))
                part = read_extents(result, work, readings[-1], directory)
                for key, value in part.items():
                    totals[key] = totals.get(key, 0) + value if isinstance(value, int) else value
                totals["deck_requests"] = 1
        totals.update(redraw_covering_boxes(result, work, sheet_path, out, call, readings))
        totals["requests"] = len(directories) + totals.get("deck_requests", 0) + totals.get("redraw_requests", 0)
        stats["extents"] = totals
        if any(work["kinds"].get(view) == "profile" for view in work["axes"]):
            check_depth(result, work)
            checked = True
    if any("extent" in space for space in result["spaces"]):
        # After the depth check: a trimmed hold ends at a topside tank, not at the deck.
        stats["overlaps"] = resolve_overlaps(result)
        stats["overlaps"]["small_label_boxes_withheld"] = withhold_oversized_guesses(result)
        stats["printed_hatch_sizes"] = apply_printed_hatch_sizes(result, work.get("printed_sizes", []))
    if not checked and result["measured"]["depth_m"]["status"] == MEASURED:
        # A depth that the space tops could not check is not given (see check_depth).
        pointed = result["measured"]["depth_m"]["value"]
        result["measured"]["depth_m"] = {
            **_unknown("the deck line could not be checked: no space below the deck was boxed in the profile"),
            "pointed_depth_m": pointed}
        result["checks"].append({"code": "depth_not_checked", "status": "check"})
    stats["measured"] = sorted(k for k, v in result["measured"].items() if v["status"] == MEASURED)
    stats["derived"] = sorted(k for k, v in result["measured"].items() if v["status"] == DERIVED)
    if work.get("table") is not None and (work.get("raw") or {}).get("chains"):
        # Last: the frame record is rebuilt whenever an extents reply adds named places.
        from .ga_scale_chain import read_printed_spans
        stats["printed_spans"] = read_printed_spans(result, work)
    stats["requests"] = len(readings)
    return stats
