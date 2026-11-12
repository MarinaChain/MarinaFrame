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
from .ga_scale_arrangement import (
    _centred_when_off_centre,
    _deck_equipment_on_the_deck,
    _footprint_share,
    _gate_box,
    _guessed_over_cargo,
    _identity,
    _joined,
    _overlap,
    _side_boxes_without_height,
    _sides,
    _split_pair,
    _without_cargo_number_conflicts,
    _without_guessed_over_cargo,
    _without_outboard_extents,
    _without_outline,
    _without_repeats,
    _without_same_boxes,
    arrangement_gate,
    arrangement_input,
    merged_spaces,
)
from .ga_scale_depth import (
    check_depth,
    tops_of_uncertain_cargo,
)
from .ga_scale_dimensions import (
    _measure,
    read_scale,
)
from .ga_scale_extents import (
    read_extents,
)
from .ga_scale_frames import (
    Axis,
    FrameTable,
    _bracket,
    _line_rms,
    _local_frame,
    _local_intervals,
    _range_slope,
    _spacing_from_fit,
    _theil_sen,
    _with_local_interval,
    consistent_ticks,
    fit_axis,
    parse_spacing_mm,
    parse_tick,
    spacing_table,
)
from .ga_scale_geometry import (
    _point_region,
    _tiles,
    _to_sheet,
    _unknown,
    _view_id,
    side_of_label,
)
from .ga_scale_overlaps import (
    _all_guessed,
    _cover,
    _end_below_spaces_above,
    _holds,
    _inside_polygon,
    _label_centre,
    _outline_problem,
    _span,
    apply_printed_hatch_sizes,
    covered_labels,
    parse_hatch_size,
    resolve_overlaps,
    withhold_oversized_guesses,
)
from .ga_scale_requests import (
    _pad,
    _write_request,
    chosen_views,
    missing_places,
    prepare_extents,
    prepare_scale,
)
from .ga_scale_settings import (
    AP_MARK_FRAMES,
    AT_SHELL_SHARE,
    BELOW_DECK_KINDS,
    BREADTH_OVER_DEPTH,
    CARGO_CONFLICT_SHARE,
    CARGO_KINDS,
    CENTRE_TOLERANCE_M,
    CHOSEN_BY_FIT,
    COVERAGE_KINDS,
    DECK_EQUIPMENT,
    DECK_EQUIPMENT_GAP_M,
    DERIVED,
    EDGE_TOLERANCE_M,
    EXTENT_PRIORITY,
    EXTENT_SPACES_PER_REQUEST,
    FIT_CHOICE_ERROR,
    FIT_CHOICE_MARGIN,
    GATE_GRID,
    GATE_KINDS,
    GATE_MAX_CARGO_LOSS,
    GUESSED_OVER_CARGO_SHARE,
    HATCH_SIZE,
    HATCH_SIZE_RANGE_M,
    INPUT_SCHEMA,
    INSIDE_LENGTH_SHARE,
    LBP_OVER_LOA,
    LENGTH_OVER_BREADTH,
    LOCAL_FIT_GAIN,
    LOWER_TANK,
    MAX_EXTENT_REQUESTS,
    MAX_IMAGES,
    MAX_OUTLIER_RUN,
    MAX_OUTLIER_SHARE,
    MAX_RMS_FRAMES,
    MAX_SPACES,
    MEASURED,
    MEASURED_FIELDS,
    MEASURE_CHECKS,
    MIDSHIP_SHARE,
    MIN_DECK_TOPS,
    MIN_OUTLIER_PX,
    MIN_RANGE_TICKS,
    MIN_TICKS,
    NOT_A_SPACE_ABOVE,
    OFF_CENTRE_SHARE,
    OUTLIER_FRAMES,
    OUTLINE_BOX_TOLERANCE_PX,
    OUTLINE_STATUS,
    PLAN_KINDS,
    PLAN_PLACES,
    POINT_SIGMA_IMAGE_PX,
    PRINTED,
    PROFILE_PLACES,
    PURPOSE,
    RAIL_OR_CAMBER_M,
    RANGE_SLOPE_TOLERANCE,
    REDRAW_MIN_AREA_SHARE,
    REQUEST_SCHEMA,
    SAME_BOX_SHARE,
    SAME_LABEL_PX,
    SAME_MARK_PX,
    SAME_SCALE_TOLERANCE,
    SCALE_ATTEMPTS,
    SCALE_PASS_CHECKS,
    SHELL_BOX_MAX_CARGO_SHARE,
    SHORT_RANGE_TOLERANCE,
    SIDE_WORDS,
    SMALL_LABEL_BOX_FACTOR,
    SMALL_LABEL_LETTERS,
    SPACING_RANGE_MM,
    STANDARD_SPACINGS_MM,
    STRAIGHT_RUN_TOLERANCE,
    STRIP_COVER,
    TANKS_ENDING_BELOW,
    UNCONFIRMED,
    UNITLESS_METRES_BELOW,
    UPPER_BAND_SHARE,
    UPPER_PART_SHARE,
    VIEW_PAD_X,
    VIEW_PAD_Y,
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
    stats["requests"] = len(readings)
    return stats
