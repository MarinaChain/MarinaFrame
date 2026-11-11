"""Initialize investigation geometry from the anchored W19a vessel fit."""
from __future__ import annotations

import copy
from pathlib import Path
from uuid import uuid4

from . import investigation as inv
from .draft import make_guesses
from .form_fit import Anchor, BuildFailure, PriorDimensions, first_hull, panel_dimensions
from .isolation import run_isolated
from .provenance import write_json

# Worker states that depend on machine load, not on the specification: a build
# that ends in one of them is run once more before its anchors are judged.
RETRY_STATES = ("timed_out",)


def run_build(tools, spec_path, prefix: str, *, export_cad: bool):
    """Run one isolated build; run it once more when the worker timed out.

    Returns ``(outcome, out_dir, retried)``. A time-out says nothing about the
    geometry, so it must not decide which anchors the first hull keeps.
    """
    retried = False
    while True:
        out = tools.root / "builds" / f"{prefix}-{uuid4().hex[:12]}"
        outcome = run_isolated(spec_path, out, export_cad=export_cad, cancel_event=tools.cancel_event)
        if outcome.get("result") is not None or outcome.get("state") not in RETRY_STATES or retried:
            return outcome, out, retried
        retried = True


def build_failure(outcome: dict) -> BuildFailure:
    """Why a build made no solid: timeout, invalid geometry or another worker state."""
    record = outcome.get("result") or {}
    state = outcome.get("state")
    if state == "timed_out":
        return BuildFailure("timeout", "the build worker timed out twice")
    if record:
        kinds = [g.get("kind") for g in record.get("gaps", []) if g.get("severity") != "warning"][:3]
        return BuildFailure("invalid_geometry", ", ".join(k for k in kinds if k) or record.get("status", ""))
    return BuildFailure(str(state or "failed"), str(outcome.get("error_code", ""))[:120])


def prior_dimensions(spec: dict, sections: list[dict]) -> PriorDimensions | None:
    """Vessel size for a hull with no usable ink.

    The description's beam and depth (already applied to ``spec`` constraints
    by first_hull_spec, only when not doubtful) come first; else the drawing's
    calibrated panel extents.
    """
    constraints = spec.get("constraints") or {}
    beam = constraints.get("beam_m")
    if isinstance(beam, (int, float)) and beam > 0:
        depth = constraints.get("depth_m")
        top = float(depth) if isinstance(depth, (int, float)) and depth > 0 else None
        return PriorDimensions(half_beam_m=float(beam) / 2, top_z_m=top, source="vessel description")
    return panel_dimensions(sections)


# A body-plan top more than this many body-plan pixels above the profile's deck
# line ran on into other ink (a label, a neighbouring curve); it is cut at the deck.
DECK_TOP_TOLERANCE_PX = 3.0
# The profile deck line is trusted when its median distance to the traced
# body-plan tops is at most this (most tops are read correctly).
DECK_AGREEMENT_M = 0.5
# A traced curve that ends below this share of its deck height is broken
# (noise, a gap), not a section that ends there.
SHORT_TOP_SHARE = 0.25


def cap_tops_at_deck(sections: list[dict], anchors: list[Anchor], decks: dict) -> list[dict]:
    """Cut traced tops that run above the profile deck line; fitted stations end at the deck.

    ``decks`` maps station ids to the deck-at-side height read on the profile
    (vessel_description.station_outline_heights). Changes ``anchors`` in place and
    returns the sections with ``z_max_m`` lowered to the deck where it is lower.
    """
    from .form_fit import _clip_top
    import numpy as np
    tops = {a.id: max(p[1] for p in a.points_yz_m) for a in anchors if a.points_yz_m}
    differences = [abs(tops[sid] - deck) for sid, deck in decks.items() if sid in tops]
    if not differences or float(np.median(differences)) > DECK_AGREEMENT_M:
        # The deck line is used only when it agrees with most body-plan tops
        # (a wrong profile scale or origin puts it elsewhere).
        return sections
    for anchor in anchors:
        deck = decks.get(anchor.id)
        points = np.asarray(anchor.points_yz_m, dtype=float)
        if deck is None or not anchor.pixels_per_metre or len(points) < 2:
            continue
        points = points[np.argsort(points[:, 1], kind="stable")]
        tolerance = DECK_TOP_TOLERANCE_PX / anchor.pixels_per_metre
        if points[-1, 1] > deck + tolerance and points[0, 1] < deck:
            anchor.points_yz_m = _clip_top(points, deck).tolist()
            # The deck height is the line's centre already: no pen-cap correction.
            anchor.stroke_width_px = None
            anchor.notes.append(f"top cut at z {deck:.3f} m: the profile deck line at this station")
    capped = copy.deepcopy(sections)
    for section in capped:
        deck = decks.get(section["id"])
        if deck is not None and section.get("z_min_m", 0.0) < deck < section["z_max_m"]:
            section["z_max_m"] = round(float(deck), 6)
    return capped


def cut_bottoms_at_keel(anchors: list[Anchor], keels: dict) -> None:
    """Cut traced bottoms that run below the profile keel line (a trace down the centreline).

    ``keels`` maps station ids to the keel height read on the profile. Used
    only when it agrees with most traced bottoms; changes ``anchors`` in place.
    """
    import numpy as np
    bottoms = {a.id: min(p[1] for p in a.points_yz_m) for a in anchors if a.points_yz_m}
    differences = [abs(bottoms[sid] - keel) for sid, keel in keels.items() if sid in bottoms]
    if not differences or float(np.median(differences)) > DECK_AGREEMENT_M:
        return
    for anchor in anchors:
        keel = keels.get(anchor.id)
        points = np.asarray(anchor.points_yz_m, dtype=float)
        if keel is None or not anchor.pixels_per_metre or len(points) < 2:
            continue
        points = points[np.argsort(points[:, 1], kind="stable")]
        # Reader cells are measured evidence; the model path keeps its original cut.
        if anchor.source == "read":
            continue
        if points[0, 1] < keel - DECK_TOP_TOLERANCE_PX / anchor.pixels_per_metre and points[-1, 1] > keel:
            start = [float(np.interp(keel, points[:, 1], points[:, 0])), keel]
            anchor.points_yz_m = np.vstack([start, points[points[:, 1] > keel]]).tolist()
            anchor.notes.append(f"bottom cut at z {keel:.3f} m: the profile keel line at this station")


# A traced bottom that stops more than this many body-plan pixels above the
# profile keel, away from the centreline, lost its lowest ink.
BOTTOM_GAP_PX = 6.0
# ... and "away from the centreline" means a lowest half-breadth above this
# share of the widest traced half-breadth.
BOTTOM_GAP_BREADTH_SHARE = 0.1
# Points of a continued bottom between the lowest traced point and the keel.
BOTTOM_EXTENSION_POINTS = 6


def extend_bottoms_to_keel(anchors: list[Anchor], keels: dict) -> None:
    """Complete bottoms, preserving the model path's original chord handling.

    Only scanned body-plan reader anchors (source ``read``) continue their
    lowest measured segment. Their profile supplies the lower height, not a
    chord to the centreline. Terminal curves keep their drawn ends.
    """
    import numpy as np
    bottoms = {a.id: min(p[1] for p in a.points_yz_m) for a in anchors if a.points_yz_m}
    differences = [abs(bottoms[sid] - keel) for sid, keel in keels.items() if sid in bottoms]
    if not differences or float(np.median(differences)) > DECK_AGREEMENT_M:
        return
    # The hull ends are shaped from the end stations (hull_ends.end_row). With
    # a continued end station the build with ends stopped without a result in
    # both shipd-1-00679-3v-L0 replays, and the hull was built without ends.
    ordered = sorted(anchors, key=lambda a: a.x_m)
    ends = {ordered[0].id, ordered[-1].id} if ordered else set()
    for anchor in anchors:
        keel = keels.get(anchor.id)
        points = np.asarray(anchor.points_yz_m, dtype=float)
        if keel is None or anchor.id in ends or not anchor.pixels_per_metre or len(points) < 2:
            continue
        points = points[np.argsort(points[:, 1], kind="stable")]
        low_y, low_z = float(points[0, 0]), float(points[0, 1])
        if (low_z - keel <= BOTTOM_GAP_PX / anchor.pixels_per_metre
                or low_y <= BOTTOM_GAP_BREADTH_SHARE * float(points[:, 0].max())):
            continue
        if anchor.source != "read":
            share = np.linspace(0.0, 1.0, BOTTOM_EXTENSION_POINTS, endpoint=False)[:, None]
            continued = np.array([0.0, keel]) + share * np.array([low_y, low_z - keel])
            anchor.points_yz_m = np.vstack([continued, points]).tolist()
            anchor.extended = True
            anchor.notes.append(f"bottom continued from y {low_y:.2f} m, z {low_z:.3f} m straight to the "
                                f"profile keel at z {keel:.3f} m on the centreline")
            continue
        higher = points[points[:, 1] > low_z + 1e-6]
        if not len(higher):
            continue
        slope = max(0.0, float((higher[0, 0] - low_y) / (higher[0, 1] - low_z)))
        heights = np.linspace(float(keel), low_z, BOTTOM_EXTENSION_POINTS, endpoint=False)
        # Retain the centreline intersection as a knot: clamping samples alone
        # would change the tangent in the last segment below the measured curve.
        if slope > 0:
            crossing = low_z - low_y / slope
            if keel < crossing < low_z:
                heights = np.unique(np.append(heights, crossing))
        breadths = np.maximum(0.0, low_y + slope * (heights - low_z))
        continued = np.column_stack([breadths, heights])
        anchor.points_yz_m = np.vstack([continued, points]).tolist()
        anchor.bottom_filled_below_m = low_z
        anchor.extended = True
        anchor.notes.append(f"bottom interpolated below y {low_y:.2f} m, z {low_z:.3f} m along the "
                            f"lowest measured segment to the profile keel at z {keel:.3f} m")


def short_of_deck(anchors: list[Anchor], decks: dict) -> list[str]:
    """Ids of traced anchors that end far below the profile deck line (a trace broken by noise).

    Used only when the deck agrees with most traced tops. The form fit then
    fills those stations from the trend and their neighbours.
    """
    import numpy as np
    tops = {a.id: max(p[1] for p in a.points_yz_m) for a in anchors if a.points_yz_m}
    differences = [abs(tops[sid] - deck) for sid, deck in decks.items() if sid in tops]
    if not differences or float(np.median(differences)) > DECK_AGREEMENT_M:
        return []
    return [sid for sid, top in tops.items() if sid in decks and top < (1 - SHORT_TOP_SHARE) * decks[sid]]


def extend_tops_to_deck(anchors: list[Anchor], decks: dict) -> None:
    """Continue traced tops that stop a little below the profile deck line up to it.

    A body-plan curve runs up to the deck at side, which the profile's deck
    line gives at each station. On a blurred sheet a trace can stop short of
    it where a station label or a neighbouring curve's top merges with the
    curve (series60-3v-L1: three aft stations ended 0.4-1.7 m low). The top is
    continued along the direction of its last EXTEND_FIT_SHARE of height. Used
    only when the deck agrees with most traced tops; traces that end far below
    it (short_of_deck) are already left to the form fit. Changes ``anchors``.
    """
    import numpy as np
    tops = {a.id: max(p[1] for p in a.points_yz_m) for a in anchors if a.points_yz_m}
    differences = [abs(tops[sid] - deck) for sid, deck in decks.items() if sid in tops]
    if not differences or float(np.median(differences)) > DECK_AGREEMENT_M:
        return
    for anchor in anchors:
        deck = decks.get(anchor.id)
        points = np.asarray(anchor.points_yz_m, dtype=float)
        if deck is None or not anchor.pixels_per_metre or len(points) < 4:
            continue
        points = points[np.argsort(points[:, 1], kind="stable")]
        top = float(points[-1, 1])
        if top >= deck - DECK_TOP_TOLERANCE_PX / anchor.pixels_per_metre:
            continue
        upper = points[points[:, 1] >= top - EXTEND_FIT_SHARE * deck]
        if len(upper) < 2 or np.ptp(upper[:, 1]) <= 0:
            continue
        slope, intercept = np.polyfit(upper[:, 1], upper[:, 0], 1)
        breadth = max(0.0, float(slope * deck + intercept))
        anchor.points_yz_m = np.vstack([points, [breadth, deck]]).tolist()
        # The deck height is the line's centre already: no pen-cap correction.
        anchor.stroke_width_px = None
        anchor.notes.append(f"top continued from z {top:.3f} to the profile deck line at z {deck:.3f} m")


# A top continued to the deck follows the direction of its upper part: the
# points within this share of the deck height below the traced top.
EXTEND_FIT_SHARE = 0.1


# A traced anchor that covers less than this share of its section's height is
# a fragment when other stations carry the same ink: a shared station curve
# runs from keel to deck (stations near midship can share a full curve).
SHARED_FRAGMENT_HEIGHT_SHARE = 0.6


def shared_fragments(anchors: list[Anchor], ink_of: dict, sections: list[dict], same_ink) -> list[str]:
    """Ids of traced anchors that are short pieces of ink other stations also carry.

    On a blurred overlay body plan the stroke enumeration often finds fewer
    strokes than stations, and the panel assignment then gives one broken
    piece to several stations (shipd-1-08158-3v-L2 replay: one stroke from
    z 0.6 to 5.5 m of a 10 m section anchored stations 2-7). Built as drawn,
    each of those stations has no breadth above or below the piece. Left out,
    the form fit fills them from their neighbours and the described size.
    A short anchor on ink of its own (a cut-up end station) is kept.
    ``ink_of`` maps anchor ids to their catalog candidates; ``same_ink(a, b)``
    says whether two candidates follow the same ink.
    """
    heights = {s["id"]: float(s["z_max_m"]) - float(s["z_min_m"]) for s in sections}
    short = []
    for anchor in anchors:
        if anchor.source != "traced" or not anchor.points_yz_m or heights.get(anchor.id, 0.0) <= 0:
            continue
        zs = [float(point[1]) for point in anchor.points_yz_m]
        if max(zs) - min(zs) >= SHARED_FRAGMENT_HEIGHT_SHARE * heights[anchor.id]:
            continue
        mine = ink_of.get(anchor.id)
        shared = any(other.id != anchor.id and ink_of.get(other.id) is not None
                     and same_ink(mine, ink_of[other.id]) for other in anchors) if mine is not None else False
        if shared:
            short.append(anchor.id)
    return short


def cap_at_profile_outline(sections: list[dict], anchors: list[Anchor], heights: dict) -> tuple[list, list]:
    """Apply the profile outline (vessel_description.station_outline_heights).

    Keel bottoms and deck tops cut traces that run on, tops that stop a little
    below the deck are continued to it, and traces that stop far below the
    deck are left to the form fit. Returns (sections, anchors).
    """
    decks = {sid: h["deck"] for sid, h in heights.items()}
    # A body-plan reader curve is measured at every waterline it crosses; one that ends below the
    # deck (a transom, a curve ending at a label) keeps its cells and is continued, not dropped.
    short = set(short_of_deck(anchors, decks)) - {a.id for a in anchors if a.source == "read"}
    anchors = [a for a in anchors if a.id not in short]
    # A keel read at the deck (an outline broken at that station) is no keel:
    # a station section is never that shallow.
    keels = {sid: h["keel"] for sid, h in heights.items() if h["keel"] < (1 - SHORT_TOP_SHARE) * h["deck"]}
    cut_bottoms_at_keel(anchors, keels)
    extend_bottoms_to_keel(anchors, keels)
    sections = cap_tops_at_deck(sections, anchors, decks)
    extend_tops_to_deck(anchors, decks)
    return sections, anchors


def hull_end_extension(image, setups, description, sections, hints):
    """A first_hull ``extend`` callback that adds the hull ends the profile shows, or None.

    The end places and their outline heights are read once; each fitted table
    then gets end rows shaped from its own end stations (hull_ends.py).
    """
    from . import hull_ends
    ends = hull_ends.profile_ends(image, setups, description, hints)
    if ends is None:
        return None
    places = hull_ends.end_stations(ends, [s["x_m"] for s in sections])
    heights = hull_ends.end_heights(image, ends, places) if places else {}
    if not heights:
        return None
    xs = sorted(float(s["x_m"]) for s in sections)
    tapers = hull_ends.end_tapers(image, setups, ends, places, {"aft": xs[0], "fore": xs[-1]}, hints)

    def extend(table):
        return hull_ends.extend_to_ends(table, sections, places, heights, tapers)
    return extend


def built_table(table, build_dir):
    """A copy of ``table`` whose rows hold the sections the build delivered (extracted_sections.json).

    A traced row is rebuilt from its ink between the section's heights, so the
    built curve can differ from the form-fit row (a top a pixel or two lower).
    The reading choice must score what the build delivered: on dtmb5415-3v-L0
    live the table fits kept a reading whose built tops were 0.08 m lower at
    every station (8.92 % RMS over 5.07 %); the built fits rank the two correctly.
    Rows the build did not report keep their table points.
    """
    import json
    path = Path(build_dir) / "extracted_sections.json"
    if not path.exists():
        return table
    built = {str(s["id"]): s.get("points_yz_m") for s in json.loads(path.read_text()).get("sections", [])}
    copied = copy.deepcopy(table)
    for row in copied.stations:
        points = built.get(str(row.id))
        if points and len(points) >= 2:
            ordered = sorted(([float(y), float(z)] for y, z in points), key=lambda p: p[1])
            row.points_yz_m = ordered
            row.keel_z_m, row.top_z_m = ordered[0][1], ordered[-1][1]
    return copied


def build_first_hull(tools):
    from .vessel_description import first_hull_spec, describe_table
    description = tools.state.get("vessel_description")
    materialization = None
    if tools.state.get("sheet_only") and not tools.state.get("materialized_spec_sha256"):
        # A sheet-only intake: declare the sections from the phase-1 reading first.
        materialization = tools._materialize_sections()
    sections = first_hull_spec(tools.spec, description)["sections"]
    while not all(s["id"] in tools.state["catalog"] for s in sections):
        observed = tools._inspect_source()
        if not observed.get("ok") and not observed.get("recovery_tools"):
            break
    tools._assign_shared_panels()
    guesses = make_guesses(sections, tools.state["selected"], tools.state["catalog"], tools.state.get("model_choices"))
    tools.state["guesses"] = guesses
    tools._save()
    base = tools._write_revision()
    from .schema import load_bounded_json
    base_spec = first_hull_spec(load_bounded_json(base), description)
    baseline, _, _ = run_build(tools, base, "anchors", export_cad=False)
    measured = {s["id"]: s for s in (baseline.get("result") or {}).get("sections", [])}
    image, _, _ = tools._source()
    chosen = {g["section_id"]: g["chosen_candidate_id"] for g in guesses}
    chosen.update(tools.state["selected"])
    anchors = []
    ink_of = {}
    for section in sections:
        candidate = next((c for c in tools.state["catalog"].get(section["id"], {}).get("candidates", [])
                          if c["candidate_id"] == chosen.get(section["id"])), None)
        if not candidate or "contour_selection" not in candidate:
            continue
        trace = inv.dense_trace(candidate)
        if trace is None:
            continue
        rows, xs = trace
        cal = section["calibration"]
        # Half-breadth from the centreline on either half (an afterbody curve is drawn left of it).
        points = [[abs(float(x) - cal["centerline_px"]) / cal["pixels_per_metre"],
                   (cal["baseline_px"] - float(y)) / cal["pixels_per_metre"]] for y, x in zip(rows, xs)]
        points.sort(key=lambda p: p[1])
        if section["id"] in measured:
            points = measured[section["id"]]["points_yz_m"]
        from .form_fit import measure_stroke_width_px
        width = measure_stroke_width_px(image, points, cal)
        selected = copy.deepcopy(section)
        selected["contour_selection"] = copy.deepcopy(candidate["contour_selection"])
        anchors.append(Anchor(section["id"], section["x_m"], points, selected,
            z_max_m=section["z_max_m"], pixels_per_metre=cal["pixels_per_metre"], stroke_width_px=width))
        ink_of[section["id"]] = candidate
    fragments = set(shared_fragments(anchors, ink_of, sections, inv.same_ink))
    anchors = [a for a in anchors if a.id not in fragments]
    # Stations the body-plan reader measured replace the model path's anchors (body_plan_intake).
    from .body_plan_intake import reader_anchors, write_check
    body_plan = tools.body_plan_reading()
    anchors, body_plan_report = reader_anchors(sections, anchors, body_plan)
    write_check(tools.root, image, body_plan, body_plan_report)
    if body_plan_report["used"]:
        # A station the reader measured has no open candidate choice: its guess is dropped.
        read = set(body_plan_report["stations"])
        guesses = [g for g in guesses if g["section_id"] not in read]
    from .vessel_description import station_outline_heights
    outline = station_outline_heights(image, list(tools.state.get("sheet_setups", {}).values()), description,
                                      sections, tools.intake_hints())
    sections, anchors = cap_at_profile_outline(sections, anchors, outline)
    extend = hull_end_extension(image, list(tools.state.get("sheet_setups", {}).values()), description,
                                sections, tools.intake_hints())
    built = {}
    retried_builds = []

    def build(spec):
        # Keep the table spec at the captured revision so source paths resolve.
        write_json(base, spec)
        outcome, out, retried = run_build(tools, base, "first", export_cad=True)
        if retried:
            retried_builds.append(out.name)
        record = outcome.get("result") or {}
        if record.get("exports", {}).get("step"):
            built.update(out=out, record=record, spec=spec)
            return True
        return build_failure(outcome)

    table, success, left_out = first_hull(sections, anchors, base_spec, build,
                                          prior=prior_dimensions(base_spec, sections), extend=extend)
    if not success:
        reason = getattr(success, "reason", "build_failed")
        return tools._observation(False, "blocked", error_code=f"first_hull_{reason}",
                                  message="First hull could not form a solid; use propose_section to complete it.")
    describe_table(table, description)
    warnings = hull_warnings(table, retried_builds)
    if tools.state.get("materialization"):
        # Sections of a sheet-only intake came from the model's reading: say so.
        warnings = [w[:300] for w in tools.state["materialization"]["warnings"]] + warnings
        warnings.insert(0, "Stations and calibration were set from the model's reading of the sheet (ai_inferred).")
    if body_plan is not None:
        tools.state["body_plan_reader"] = body_plan_report
        if body_plan_report["used"]:
            warnings.insert(0, f"Stations {', '.join(body_plan_report['stations'])} were measured by the body-plan "
                               "reader with an automatic calibration; confirm the calibration overlay.")
        else:
            warnings.insert(0, f"Body-plan reader not used: {body_plan_report['reason']}"[:300])
        warnings[1:1] = [w[:300] for w in body_plan_report.get("warnings", [])]
    tools.state["vessel_table"] = table.to_json()
    write_json(tools.root / "vessel.json", {"description": description, "table": table.to_json()})
    from .fit_feedback import score
    tools.state["fit_score"] = score(tools, table)
    from .draft_fit import task_score
    tools.state["draft_fit"] = task_score(tools, table)
    # The reading choice scores the hull the build delivered (built_table); the edit keep
    # rule keeps comparing table fits with table fits (draft_fit).
    tools.state["built_draft_fit"] = task_score(tools, built_table(table, built["out"])).get("draft_fit")
    tools.state["first_hull_spec"] = built["spec"]
    tools.state["guesses"] = built["spec"].get("draft", {}).get("guesses", guesses)
    candidate = {"id":tools.generation_id,"generation_id":tools.generation_id,"revision_id":tools.revision_id,
        "path":built["out"].relative_to(tools.task_dir).as_posix(),"status":"review_required","valid":True,
        # The export is tagged a draft only when the build has open guesses (run_record._cad_names);
        # a first hull read entirely by the body-plan reader has none.
        "draft":"draft" in built["record"],
        "run_id":built["record"]["run_id"],"gaps":built["record"]["gaps"],"metrics":built["record"]["metrics"],
        "engineering_approved":False,"human_semantic_review_required":True,"identity_certified":False,
        "warnings":warnings}
    tools.state["builds"].append(candidate)
    candidate["combined_fit"] = tools.state["fit_score"].get("combined_fit")
    candidate["draft_fit"] = tools.state["draft_fit"].get("draft_fit")
    tools.state["last_valid_candidate"] = candidate
    tools.state["best_valid_candidate"] = copy.deepcopy(candidate)
    tools._save()
    no_ink = all(row.source in ("prior", "inferred") for row in table.stations)
    message = ("No usable ink: the first hull is the prior form scaled to the vessel size. Author or correct "
               "sections from the drawing." if no_ink else
               "Anchored first hull ready. Render it, preserve good ink and improve only the weak sections.")
    extra = {"materialized_sections": materialization} if materialization else {}
    return tools._observation(True,"first_hull_built",candidate=candidate,left_out_anchor_ids=left_out,
                              warnings=warnings, message=message, **extra)


# A later reading changes the first hull's setup when a station moves by more
# than SETUP_X_SHARE of the hull length, a scale or height by more than
# SETUP_SCALE_SHARE, or a datum by more than SETUP_DATUM_PX. Smaller
# differences are reading noise and keep the built hull.
SETUP_X_SHARE = 0.01
SETUP_SCALE_SHARE = 0.01
SETUP_DATUM_PX = 2.0
# State of the sections built on the old setup; a rebuild starts them again.
SECTION_STATE = {"catalog": {}, "selected": {}, "model_choices": {}, "authored_sections": {}, "guesses": [],
                 "resolved_guesses": [], "validation": None, "non_improving_edits": 0}


def setup_changes(old: dict, new: dict) -> list[str]:
    """What differs between two first-hull setups: materialized sections and description constraints.

    ``old`` and ``new`` are first_hull_spec results (sections, constraints).
    Returns one short line per change; empty when the setup is the same.
    """
    old_sections, new_sections = old.get("sections", []), new.get("sections", [])
    if [s["id"] for s in old_sections] != [s["id"] for s in new_sections]:
        return [f"stations {[s['id'] for s in old_sections]} -> {[s['id'] for s in new_sections]}"]
    changes = []
    length = max([abs(float(s["x_m"])) for s in old_sections + new_sections] + [1e-6])

    def relative(a, b):
        return abs(float(a) - float(b)) / max(abs(float(b)), 1e-9)

    for before, after in zip(old_sections, new_sections):
        sid = after["id"]
        if abs(float(before["x_m"]) - float(after["x_m"])) > SETUP_X_SHARE * length:
            changes.append(f"{sid}: x {before['x_m']:g} -> {after['x_m']:g} m")
        if relative(before["z_max_m"], after["z_max_m"]) > SETUP_SCALE_SHARE:
            changes.append(f"{sid}: top {before['z_max_m']:g} -> {after['z_max_m']:g} m")
        cal_before, cal_after = before["calibration"], after["calibration"]
        if relative(cal_before["pixels_per_metre"], cal_after["pixels_per_metre"]) > SETUP_SCALE_SHARE:
            changes.append(f"{sid}: scale {cal_before['pixels_per_metre']:g} -> "
                           f"{cal_after['pixels_per_metre']:g} px/m")
        for key in ("centerline_px", "baseline_px"):
            if abs(float(cal_before[key]) - float(cal_after[key])) > SETUP_DATUM_PX:
                changes.append(f"{sid}: {key} {cal_before[key]:g} -> {cal_after[key]:g}")
    old_limits, new_limits = old.get("constraints") or {}, new.get("constraints") or {}
    for key in ("beam_m", "depth_m", "length_m"):
        a, b = old_limits.get(key), new_limits.get(key)
        if (a is None) != (b is None) or (a is not None and relative(a, b) > SETUP_SCALE_SHARE):
            changes.append(f"{key} {a} -> {b}")
    return changes


# Views other than the body plan whose setup shapes the first hull: the
# profile gives the keel, deck and hull ends, the plan the waterline ends
# (vessel_description.station_outline_heights, hull_ends).
OUTLINE_VIEWS = ("profile", "plan")
# Fields of a view setup that place it on the sheet; SETUP_DATUM_PX and
# SETUP_SCALE_SHARE say how much they may differ.
VIEW_DATUM_KEYS = ("baseline_px", "centreline_px", "x_origin_px")


def view_setup_changes(old_setups: dict, new_setups: dict) -> list[str]:
    """What differs between two readings' profile and plan setups (scale, datums, direction).

    ``old_setups`` and ``new_setups`` are task ``sheet_setups`` maps. A view
    set up in one reading only is no change: the first hull then uses the
    code-measured view. Returns one short line per change.

    Sonnet 5.5 live (round 81d3047, dtmb5415-3v-L0): an independent second
    reading put the profile baseline at 360 px against 398 px, but its body
    setup matched, so no second hull was built and the best of two had one
    hull to choose from.
    """
    def by_view(setups):
        # The record the hull uses: the first with an x origin, else the first
        # (vessel_description.profile_setup).
        records = {}
        for record in (setups or {}).values():
            if isinstance(record, dict) and record.get("view") in OUTLINE_VIEWS:
                held = records.get(record["view"])
                if held is None or (held.get("x_origin_px") is None and record.get("x_origin_px") is not None):
                    records[record["view"]] = record
        return records

    old, new = by_view(old_setups), by_view(new_setups)
    changes = []
    for view in OUTLINE_VIEWS:
        before, after = old.get(view), new.get(view)
        if before is None or after is None:
            continue
        a, b = before.get("pixels_per_metre"), after.get("pixels_per_metre")
        if a and b and abs(float(a) - float(b)) / float(b) > SETUP_SCALE_SHARE:
            changes.append(f"{view}: scale {a:g} -> {b:g} px/m")
        for key in VIEW_DATUM_KEYS:
            a, b = before.get(key), after.get(key)
            if a is not None and b is not None and abs(float(a) - float(b)) > SETUP_DATUM_PX:
                changes.append(f"{view}: {key} {a:g} -> {b:g}")
        if (before.get("x_direction") or 1) != (after.get("x_direction") or 1):
            changes.append(f"{view}: x direction {before.get('x_direction')} -> {after.get('x_direction')}")
    return changes


# What a reading wrote to the task state beside its first hull; a repeat
# reading starts these again, and the kept reading's values come back when
# the earlier first hull is kept.
READING_RECORD_KEYS = ("sheet_setups", "described_views", "vessel_description")


# A sheet-only first hull is read READINGS times: after the first hull the
# model reads the sheet again (phase 1), and of the first hulls the one with
# the best drawing fit is kept (draft_fit.task_score: all three views in one
# frame measured by code; drawing only, never truth). Live runs differ by 1-5
# points from the model's reading alone (docs/HULL_SELECTION.md); each further
# reading costs a few model calls.
READINGS = 2
# Description state of one reading; a new reading starts it again.
READING_STATE = {"description_phase": "views", "description_next_view": None, "described_views": [],
                 "sheet_setups": {}}


def next_reading_message(number: int) -> str:
    return (f"Reading {number} of {READINGS} (best of {READINGS} by drawing fit): read the sheet again from the "
            "views, as an independent check: describe_views, propose_sheet_setup and describe_vessel. The first "
            "hull of the reading that fits the drawing best is kept.")


def reading_fits(state: dict) -> dict:
    """Drawing fits of a task state's first hull: draft_fit (three views, code frame) and the body-plan fit."""
    return {"built_draft_fit": state.get("built_draft_fit"),
            "draft_fit": (state.get("draft_fit") or {}).get("draft_fit"),
            "combined_fit": (state.get("fit_score") or {}).get("combined_fit")}


def better_reading(old: dict, new: dict) -> bool:
    """True when the new reading's fits (reading_fits) beat the old ones; ties keep the old reading.

    Both readings are compared on the first fit both have, in this order:
    built_draft_fit (the delivered hull, built_table), draft_fit (the form-fit
    table), combined_fit. The body-plan fit alone measures each reading in its
    own frame: it kept a reading with x = 0 3 m off the hull's aft end
    (shipd-1-08158-3v-L1 Sonnet live: fit 0.919 and 11.9 % RMS against 0.872 and 5.3 %).
    """
    key = next((k for k in ("built_draft_fit", "draft_fit")
                if old.get(k) is not None and new.get(k) is not None), "combined_fit")
    if new.get(key) is None:
        return False
    return old.get(key) is None or new[key] > old[key]


def reading_record(tools, kept: bool | None = None) -> dict:
    """Summary of one reading's first hull: its drawing fits and stations."""
    stations = (tools.state.get("vessel_description") or {}).get("stations") or []
    record = {**reading_fits(tools.state), "station_count": len(stations)}
    if kept is not None:
        record["kept"] = kept
    return record


def begin_reading(tools) -> dict:
    """Start one more phase-1 reading; returns the observation part that says so.

    ``reading_open`` holds the number of reading records before this reading,
    so finish_reading can tell whether the reading built a first hull.
    ``reading_number`` counts the readings themselves: one reading can add
    several records (a rebuild at propose_sheet_setup for the body and
    another at describe_vessel).
    """
    readings = tools.state["readings"]
    number = tools.state.get("reading_number", len(readings)) + 1
    # The kept reading's setups and description: compared with the new
    # reading's (rebuild_if_setup_changed) and restored when its hull is kept.
    tools.state["kept_reading"] = {key: copy.deepcopy(tools.state.get(key)) for key in READING_RECORD_KEYS}
    tools.state.update(copy.deepcopy(READING_STATE))
    tools.state["reading_open"] = len(readings)
    tools.state["reading_number"] = number
    tools._save()
    return {"reading": number, "of": READINGS, "message": next_reading_message(number)}


def start_next_reading(tools) -> dict | None:
    """After the first sheet-only first hull, start another phase-1 reading (best of READINGS).

    The built hull stays the task's draft while the model reads again; the
    new reading's first hull is built by rebuild_if_setup_changed and kept
    only when it fits the drawing better. Returns the observation part, or
    None when no further reading is due.
    """
    if not tools.state.get("sheet_only") or tools.state.get("phase1_only"):
        return None
    readings = tools.state.setdefault("readings", [])
    if readings:
        return None  # Only the controller's first build starts the readings.
    readings.append(reading_record(tools, kept=True))
    tools.state["reading_number"] = 1
    if len(readings) >= READINGS:
        tools._save()
        return None
    return begin_reading(tools)


def finish_reading(tools) -> dict | None:
    """End a repeat reading after its describe_vessel; start the next one when due.

    A reading whose setup equals the kept one builds no first hull
    (rebuild_if_setup_changed): it is recorded as ``same_setup``. Returns the
    next reading's observation part, or None.
    """
    opened = tools.state.pop("reading_open", None)
    if opened is None:
        return None
    readings = tools.state.setdefault("readings", [])
    if len(readings) == opened:
        stations = (tools.state.get("vessel_description") or {}).get("stations") or []
        readings.append({"draft_fit": None, "combined_fit": None, "station_count": len(stations),
                         "same_setup": True, "kept": False})
    if tools.state.get("reading_number", len(readings)) >= READINGS:
        tools._save()
        return None
    return begin_reading(tools)


def keep_better_reading(tools, snapshot: dict, materialized: bytes | None, observation: dict) -> dict:
    """Keep the earlier reading's first hull unless the new one fits the drawing better.

    ``snapshot`` is the task state before the rebuild and ``materialized``
    its materialized spec file. Returns the selection record.
    """
    from .agent_tools import MATERIALIZED_SPEC
    from .schema import load_bounded_json
    old_fits = reading_fits(snapshot)
    new_fits = reading_fits(tools.state) if observation.get("ok") else {"draft_fit": None, "combined_fit": None}
    # The new reading replaces the earlier one only when it fits the drawing strictly better.
    has_old = materialized is not None and any(value is not None for value in old_fits.values())
    keep_old = has_old and not better_reading(old_fits, new_fits)
    readings = copy.deepcopy(tools.state.get("readings") or [])
    for record in readings:
        if record.get("kept"):
            record["kept"] = keep_old
    readings.append({**reading_record(tools), **new_fits, "kept": not keep_old})
    selection = {"kept": "earlier" if keep_old else "new", "fit_earlier": old_fits["draft_fit"],
                 "fit_new": new_fits["draft_fit"], "body_fit_earlier": old_fits["combined_fit"],
                 "body_fit_new": new_fits["combined_fit"],
                 "built_fit_earlier": old_fits.get("built_draft_fit"), "built_fit_new": new_fits.get("built_draft_fit")}
    if keep_old:
        (tools.root / "input" / MATERIALIZED_SPEC).write_bytes(materialized)
        set_aside = snapshot.get("set_aside_builds", []) + tools.state.get("builds", [])
        tools.state = copy.deepcopy(snapshot)
        # The snapshot holds the new reading's setups and description; the
        # earlier hull was built from the kept reading's.
        tools.state.update(copy.deepcopy(snapshot.get("kept_reading") or {}))
        # The new reading's builds are kept as history only: a build is reused by
        # its generation and revision ids, which do not name the reading's setup.
        tools.state["set_aside_builds"] = set_aside
        tools.spec = load_bounded_json(tools.root / "input" / MATERIALIZED_SPEC)
        write_json(tools.root / "vessel.json", {"description": tools.state.get("vessel_description"),
                                                "table": tools.state.get("vessel_table")})
    tools.state["readings"] = readings
    tools.state["reading_selection"] = selection
    tools._save()
    return selection


def rebuild_if_setup_changed(tools, previous_description) -> dict | None:
    """Build the first hull again when a later reading changes its setup (sheet-only happy path).

    The first hull is built once, after phase 1. When the model later reads the
    title block or a scale again and the corrected reading gives other stations,
    scale, datums or principal dimensions, the old hull and the sections traced
    or authored on it rest on a wrong setup: they are set aside and the first
    hull is built from the corrected setup. Returns the rebuild observation, or
    None when nothing was built yet or nothing changed.
    """
    if not (tools.state.get("sheet_only") and tools.state.get("vessel_table")
            and tools.state.get("materialized_spec_sha256")):
        return None
    from .materialize import materialize_sections
    from .vessel_description import first_hull_spec
    image, _, _ = tools._source()
    made = materialize_sections(image, tools.captured_spec, tools.state, tools.intake_hints())
    old = first_hull_spec(tools.spec, previous_description)
    new = first_hull_spec({**tools.captured_spec, "sections": made["sections"]}, tools.state.get("vessel_description"))
    changes = setup_changes(old, new)
    if tools.state.get("reading_open") is not None:
        # A repeat reading also changes the hull through its profile and plan setups.
        kept = (tools.state.get("kept_reading") or {}).get("sheet_setups")
        changes += view_setup_changes(kept, tools.state.get("sheet_setups"))
    if not changes:
        return None
    snapshot = copy.deepcopy(tools.state)
    from .agent_tools import MATERIALIZED_SPEC
    materialized_path = tools.root / "input" / MATERIALIZED_SPEC
    materialized = materialized_path.read_bytes() if materialized_path.exists() else None
    tools.state.pop("materialized_spec_sha256", None)
    tools.state.update(copy.deepcopy(SECTION_STATE))
    # Builds of the old setup are history: the new setup must never reuse one
    # (build reuse matches generation and revision ids, which do not name the setup).
    tools.state["set_aside_builds"] = tools.state.get("set_aside_builds", []) + tools.state.get("builds", [])
    tools.state["builds"] = []
    tools.spec = tools.captured_spec
    tools._save()
    observation = build_first_hull(tools)
    selection = keep_better_reading(tools, snapshot, materialized, observation)
    if selection["kept"] == "earlier":
        return tools._observation(True, "earlier_reading_kept", setup_changes=changes[:12],
                                  reading_selection=selection,
                                  candidate=copy.deepcopy(tools.state.get("last_valid_candidate")),
                                  message=(f"The new reading changed the hull setup, but its first hull fits the "
                                           f"drawing no better (fit {selection['fit_new']} vs "
                                           f"{selection['fit_earlier']}) or was not built; the earlier reading "
                                           "and its first hull were kept."))
    observation["setup_changes"] = changes[:12]
    observation["reading_selection"] = selection
    observation["message"] = ("The corrected reading changed the hull setup; the first hull was built again from it "
                              "and earlier section edits were set aside. " + observation.get("message", ""))[:600]
    return observation


# Kinds of table warning that say what happened to the ink (fairness notes stay in the table).
REPORTED_WARNINGS = ("no_ink", "anchor_dropped", "anchor_left_out", "inferred_end")


def hull_warnings(table, retried_builds: list) -> list[str]:
    """Draft warnings of the first hull: no ink, each dropped or left-out anchor and why, retries."""
    lines = []
    for item in table.warnings:
        if item.get("kind") in REPORTED_WARNINGS:
            where = f"{item['section_id']}: " if item.get("section_id") else ""
            lines.append(f"{where}{item.get('message', '')}"[:300])
    if retried_builds:
        lines.append(f"{len(retried_builds)} build(s) timed out and were run once more.")
    return lines
