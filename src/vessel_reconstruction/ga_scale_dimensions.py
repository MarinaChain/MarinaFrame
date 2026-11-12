"""Commercial GA dimensions; rules and constants unchanged."""
from __future__ import annotations

from . import source_record
from .ga_scale_frames import (
    Axis,
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
)
from .ga_scale_settings import (
    AP_MARK_FRAMES,
    BREADTH_OVER_DEPTH,
    LBP_OVER_LOA,
    LENGTH_OVER_BREADTH,
    MEASURED,
    MEASURED_FIELDS,
    MEASURE_CHECKS,
    MIDSHIP_SHARE,
    PLAN_KINDS,
    POINT_SIGMA_IMAGE_PX,
    PURPOSE,
    SAME_MARK_PX,
    SAME_SCALE_TOLERANCE,
)
from pathlib import Path
import math
import numpy as np


def read_scale(result: dict, reading: dict, request_dir: Path, earlier: dict | None = None) -> dict:
    """The frame table, the axis of every view and the measured principal dimensions.

    Sets ``result["frames"]`` and ``result["measured"]`` and returns the working data
    (axes and named points per view) for ``read_extents``. ``earlier`` is the working data of
    an earlier scale request of the same ship: its marks are read together with this reply's.
    """
    sheet = result["sources"]["ga"]["file"]
    page_px = result["sources"]["ga"]["size_px"]
    kinds = {v["view_id"]: v["kind"] for v in result.get("views", [])}
    reply = (reading.get("reply") or {}).get(PURPOSE)
    work = {"axes": {}, "points": {}, "table": None, "sheet": sheet, "page_px": page_px, "kinds": kinds}
    before = (earlier or {}).get("raw")
    if reply is None and before:
        work["raw"] = before
        return _measure(result, work)
    if reply is None:
        reason = reading.get("stop_reason") or "the model gave no valid reply for the frame scale"
        result["frames"] = {"status": "unknown", "spacings": [], "reason": reason,
                            "source_record": source_record.unknown(reason)}
        result["measured"] = {field: _unknown(reason) for field in MEASURED_FIELDS}
        return work
    tiles = _tiles(request_dir)
    ticks: dict[str, list] = {}
    marks: dict[str, dict] = {}
    spacing_labels: dict[str, list] = {}
    cuts: dict[str, list] = {}
    points: dict[str, dict] = {}
    sigma_px = 0.0
    for tile in tiles.values():
        sigma_px = max(sigma_px, POINT_SIGMA_IMAGE_PX * (tile["crop_box_px"][2] - tile["crop_box_px"][0]) / tile["width"])
    for tick in reply["ticks"]:
        view = _view_id(tiles[tick["image_id"]])
        x, y = _to_sheet(tiles[tick["image_id"]], tick["x"], tick["y"])
        parsed = parse_tick(tick["label"])
        if parsed is None:
            result["checks"].append({"code": "scale_mark_not_understood", "status": "dropped", "label": tick["label"][:16]})
        elif parsed[0] == "frame":
            ticks.setdefault(view, []).append((parsed[1], x, y))
        else:
            marks.setdefault(view, {}).setdefault(parsed[0], []).append((x, y))
    for label in reply["spacing_labels"]:
        view = _view_id(tiles[label["image_id"]])
        x, _ = _to_sheet(tiles[label["image_id"]], label["x"], label["y"])
        mm = parse_spacing_mm(label["printed"])
        if mm is None:
            result["checks"].append({"code": "frame_spacing_not_understood", "status": "dropped",
                                     "label": label["printed"][:32]})
        else:
            spacing_labels.setdefault(view, []).append((mm, x))
    for cut in reply["spacing_boundaries"]:
        view = _view_id(tiles[cut["image_id"]])
        cuts.setdefault(view, []).append(_to_sheet(tiles[cut["image_id"]], cut["x"], cut["y"])[0])
    for point in reply["points"]:
        view = _view_id(tiles[point["image_id"]])
        points.setdefault(view, {}).setdefault(point["name"], []).append(
            _to_sheet(tiles[point["image_id"]], point["x"], point["y"]))
    if before:
        for view, found in before["ticks"].items():
            ticks.setdefault(view, []).extend(found)
        for view, named in before["marks"].items():
            for name, places in named.items():
                marks.setdefault(view, {}).setdefault(name, []).extend(places)
        for view, found in before["spacing_labels"].items():
            spacing_labels.setdefault(view, []).extend(found)
        for view, found in before["cuts"].items():
            cuts.setdefault(view, []).extend(found)
        # A named place keeps its first pointing (two pointings of a hull end differ by more
        # than two pointings of a printed mark).
        for view, named in before["points"].items():
            points.setdefault(view, {}).update(named)
        sigma_px = max(sigma_px, before["sigma_px"])
    work["raw"] = {"ticks": ticks, "marks": marks, "spacing_labels": spacing_labels, "cuts": cuts,
                   "points": points, "sigma_px": sigma_px}
    return _measure(result, work)


def _measure(result: dict, work: dict) -> dict:
    """The frame table, the axes and the principal dimensions from the marks collected in ``work``."""
    from .ga_commercial import PLAUSIBLE, RECORD_VIEWS
    fields = MEASURED_FIELDS
    sheet, page_px, kinds = work["sheet"], work["page_px"], work["kinds"]
    raw = work["raw"]
    ticks, marks, spacing_labels, cuts, points = (raw[key] for key in ("ticks", "marks", "spacing_labels",
                                                                       "cuts", "points"))
    sigma_px = raw["sigma_px"]
    result["checks"] = [c for c in result["checks"] if c.get("code") not in MEASURE_CHECKS]
    work.update(axes={}, points={}, table=None)

    def abstain(reason: str) -> dict:
        result["frames"] = {"status": "unknown", "spacings": [], "reason": reason,
                            "source_record": source_record.unknown(reason)}
        result["measured"] = {field: _unknown(reason) for field in fields}
        return work

    def one(places: list | None):
        """One place from marks of the same thing on overlapping images; None when they differ."""
        if not places:
            return None
        xs, ys = [p[0] for p in places], [p[1] for p in places]
        if max(xs) - min(xs) > SAME_MARK_PX or max(ys) - min(ys) > SAME_MARK_PX:
            return None
        return float(np.mean(xs)), float(np.mean(ys))

    work["points"] = {view: {name: place for name, places in named.items() if (place := one(places))}
                      for view, named in points.items()}
    # The frame table: from the profile when it prints the spacings, else from a plan.
    order = sorted(spacing_labels, key=lambda view: kinds.get(view) != "profile")
    table, reason, table_view = None, "no frame spacing is printed", None
    for view in order:
        table, reason = spacing_table([(f, x) for f, x, _ in ticks.get(view, [])], spacing_labels[view],
                                      cuts.get(view, []))
        if table:
            table_view = view
            break
    if table is None:
        return abstain(reason)
    for view, found in ticks.items():
        axis, why = fit_axis([(f, x) for f, x, _ in found], table)
        if axis:
            work["axes"][view] = axis
        else:
            result["checks"].append({"code": "frame_scale_not_fitted", "status": "check", "view": view, "reason": why})
    primary = next((view for view in [table_view, *work["axes"]] if view in work["axes"]), None)
    if primary is None:
        return abstain("the frame numbers do not fit the printed spacings")
    axis = work["axes"][primary]
    work["table"] = table
    scale_region, span_px = _record_frame_scale(result, work, table, axis, primary, ticks, sheet, page_px, kinds, RECORD_VIEWS)
    def measured(pixels: float, view_axis: Axis, how: str, regions: list[dict]) -> dict:
        value = view_axis.length_m(pixels)
        # Two pointed places and the fit of the scale itself.
        sigma = math.hypot(sigma_px, view_axis.rms_px)
        uncertainty = 2 * sigma / abs(view_axis.px_per_m) + value * axis.rms_px / max(span_px, 1.0)
        return {"value": round(value, 2), "status": MEASURED, "uncertainty_m": round(uncertainty, 2),
                "method": how, "scale_basis": view_axis.basis,
                "note": "measured on the drawing with its printed frame scale; not a printed particular",
                "source_record": source_record.validate(source_record.read([*regions, scale_region]))}

    out = _measure_profile_and_breadth(result, work, table, ticks, marks, points, raw, sheet, page_px, kinds, one, measured)
    _check_measured_dimensions(result, out, fields, PLAUSIBLE)
    result["measured"] = out
    return work


def _record_frame_scale(result, work, table, axis, primary, ticks, sheet, page_px, kinds, RECORD_VIEWS):
    # A plan without its own frame numbers: the scale of the primary view, when both views draw
    # the hull equally long (one sheet, one scale); its origin comes from the hull's aft end.
    primary_ends = work["points"].get(primary, {})
    for view, named in work["points"].items():
        if view in work["axes"] or not {"hull_aft_end", "hull_fore_end"} <= named.keys():
            continue
        if not {"hull_aft_end", "hull_fore_end"} <= primary_ends.keys():
            continue
        own = named["hull_fore_end"][0] - named["hull_aft_end"][0]
        reference = primary_ends["hull_fore_end"][0] - primary_ends["hull_aft_end"][0]
        if reference and abs(own / reference - 1) <= SAME_SCALE_TOLERANCE:
            aft_m = axis.x_m(primary_ends["hull_aft_end"][0])
            work["axes"][view] = Axis(named["hull_aft_end"][0] - axis.px_per_m * aft_m, axis.px_per_m, axis.rms_px,
                                      0, 0, "scale of the frame-scale view; hull ends matched")
    # The table reaches from the aft end to the fore end of the hull (and holds frame 0).
    ends = [table.frame_at(axis.x_m(primary_ends[name][0])) for name in ("hull_aft_end", "hull_fore_end")
            if name in primary_ends]
    # (A hull end a little past a frame does not add a frame.)
    table.spans[0]["from_frame"] = min([table.spans[0]["from_frame"], 0, *(math.floor(f + 0.25) for f in ends)])
    table.spans[-1]["to_frame"] = max([table.spans[-1]["to_frame"], *(math.ceil(f - 0.25) for f in ends)])
    tick_xy = [(x, y) for _, x, y in ticks[primary]]
    scale_region = _point_region(sheet, page_px, RECORD_VIEWS.get(kinds.get(primary)), *tick_xy)
    span_px = max(x for x, _ in tick_xy) - min(x for x, _ in tick_xy)
    result["frames"] = {
        "status": "read", "spacings": table.spans, "frame_zero": "aft perpendicular",
        "boundaries_status": MEASURED,
        "scale": {"view_id": primary, "px_per_m": round(abs(axis.px_per_m), 4),
                  "direction": "bow_right" if axis.px_per_m > 0 else "bow_left",
                  "ticks_used": axis.ticks_used, "ticks_read": axis.ticks_read, "rms_px": round(axis.rms_px, 2)},
        "source_record": source_record.validate(source_record.read([scale_region]))}

    return scale_region, span_px


def _measure_profile_and_breadth(result, work, table, ticks, marks, points, raw, sheet, page_px, kinds, one, measured):
    out = {}
    profile = next((view for view in work["axes"] if kinds.get(view) == "profile"), None)
    named = work["points"].get(profile, {}) if profile else {}
    record_view = "profile"
    ap, fp = one(marks.get(profile, {}).get("ap")), one(marks.get(profile, {}).get("fp"))
    if profile is None:
        for field in ("lbp_m", "loa_m", "depth_m"):
            out[field] = _unknown("the profile has no fitted frame scale")
    else:
        profile_axis = work["axes"][profile]
        if fp is None:
            out["lbp_m"] = _unknown("the forward perpendicular (F.P.) is not marked on the frame scale")
        else:
            # Frame 0 is the AP by the table; a printed A.P. mark must agree with it.
            ap_px = profile_axis.offset
            frame_px = abs(profile_axis.px_per_m) * table.spacing_m(0)
            if ap is not None and abs(ap[0] - ap_px) > max(SAME_MARK_PX, AP_MARK_FRAMES * frame_px):
                result["checks"].append({"code": "ap_mark_not_at_frame_0", "status": "check"})
                out["lbp_m"] = _unknown("the A.P. mark does not lie at frame 0 of the frame scale")
            else:
                out["lbp_m"] = measured(fp[0] - ap_px, profile_axis, "frame 0 (A.P.) to the F.P. mark on the frame scale",
                                        [_point_region(sheet, page_px, record_view, fp, (ap_px, fp[1]))])
        if {"hull_aft_end", "hull_fore_end"} <= named.keys():
            aft, fore = named["hull_aft_end"], named["hull_fore_end"]
            out["loa_m"] = measured(fore[0] - aft[0], profile_axis, "aft end to fore end of the hull in the profile",
                                    [_point_region(sheet, page_px, record_view, aft),
                                     _point_region(sheet, page_px, record_view, fore)])
        else:
            out["loa_m"] = _unknown("the profile does not show both ends of the hull")
        hull = sorted(named[name][0] for name in ("hull_aft_end", "hull_fore_end") if name in named)
        if len(hull) < 2:  # without both hull ends, the ends of the frame scale
            hull = [min(x for _, x, _ in ticks[profile]), max(x for _, x, _ in ticks[profile])]
        if {"base_line", "upper_deck_at_side"} <= named.keys() and not (
                MIDSHIP_SHARE[0] <= (named["upper_deck_at_side"][0] - hull[0]) / (hull[1] - hull[0]) <= MIDSHIP_SHARE[1]):
            # A deck line pointed near an end of the ship can be the poop or forecastle deck. It
            # is dropped, so that the extents request can point the deck line again.
            raw["points"][profile].pop("upper_deck_at_side")
            out["depth_m"] = _unknown("the upper deck line was not pointed amidships")
            result["checks"].append({"code": "deck_point_not_amidships", "status": "check"})
        elif {"base_line", "upper_deck_at_side"} <= named.keys():
            base, deck = named["base_line"], named["upper_deck_at_side"]
            out["depth_m"] = measured(base[1] - deck[1], profile_axis,
                                      "base line to the upper deck at side amidships in the profile",
                                      [_point_region(sheet, page_px, record_view, base),
                                       _point_region(sheet, page_px, record_view, deck)])
        else:
            out["depth_m"] = _unknown("the base line or the upper deck at side was not found in the profile")
    out["breadth_m"] = _unknown("no plan view with a scale shows both sides of the shell")
    for view, view_axis in work["axes"].items():
        sides = work["points"].get(view, {})
        if kinds.get(view) in PLAN_KINDS and {"shell_side_a", "shell_side_b"} <= sides.keys():
            a, b = sides["shell_side_a"], sides["shell_side_b"]
            out["breadth_m"] = measured(a[1] - b[1], view_axis, "shell side to shell side amidships in the plan",
                                        [_point_region(sheet, page_px, "plan", a),
                                         _point_region(sheet, page_px, "plan", b)])
            break

    return out


def _check_measured_dimensions(result, out, fields, PLAUSIBLE):
    def refuse(names, reason, code):
        for name in names:
            out[name] = _unknown(reason)
        result["checks"].append({"code": code, "status": "check"})

    def value(name):
        return out[name]["value"]

    for name in fields:
        if value(name) is not None and not PLAUSIBLE[name][0] <= value(name) <= PLAUSIBLE[name][1]:
            refuse([name], f"the measured {name} is not plausible", "measured_value_implausible")
    if value("lbp_m") and value("loa_m") and not LBP_OVER_LOA[0] <= value("lbp_m") / value("loa_m") <= LBP_OVER_LOA[1]:
        refuse(["lbp_m", "loa_m"], "measured LBP and LOA do not fit each other", "measured_lengths_disagree")
    length = value("lbp_m") or value("loa_m")
    if length and value("breadth_m") and not (LENGTH_OVER_BREADTH[0] <= length / value("breadth_m")
                                              <= LENGTH_OVER_BREADTH[1]):
        refuse(["breadth_m"], "the measured breadth does not fit the measured length", "measured_breadth_disagrees")
    if value("breadth_m") and value("depth_m") and not (BREADTH_OVER_DEPTH[0] <= value("breadth_m") / value("depth_m")
                                                        <= BREADTH_OVER_DEPTH[1]):
        refuse(["depth_m"], "the measured depth does not fit the measured breadth", "measured_depth_disagrees")
