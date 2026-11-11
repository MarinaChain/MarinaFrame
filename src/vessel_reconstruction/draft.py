"""Best-effort draft records: the guesses a draft build makes, and their checks.

A draft is built when a section is ambiguous or unreadable. It takes the
best-scoring candidate, or leaves an unreadable station out so the loft spans
the gap. Each such choice is a guess. A draft is never verified geometry: the
Rust controller refuses review readiness while any guess is open, and only a
person resolves a guess (operator ``select_contours``). This module has no CAD
or image code, so the schema, the run record and the domain can share it.
"""
from __future__ import annotations

import json
import math

from .provenance import digest_object
from .artifacts import DRAFT_NAMES

DRAFT_STATUS = "draft_not_verified"
GUESS_KINDS = ("best_candidate", "bridged_gap", "dropped_end", "model_choice", "model_authored")
GUESS_FIELDS = {"guess_id", "section_id", "kind", "x_m", "x_range_m", "chosen_candidate_id",
                "alternatives", "score", "reason", "status"}
# A model choice also carries the deterministic verifier's evidence.
MODEL_CHOICE_FIELDS = GUESS_FIELDS | {"verifier_evidence"}
# A model-authored section (propose_section) carries the sanity checks the
# same way; its candidate holds the curve (see section_authoring.py).
MODEL_AUTHORED_KINDS = ("model_choice", "model_authored")
MAX_EVIDENCE_BYTES = 4096
MAX_GUESSES = 300
MAX_REASON_CHARS = 512
# Exported CAD file names of a draft build. The tag is in the file name, so a
# downloaded draft file cannot be mistaken for a verified export.
DRAFT_EXPORT_NAMES = DRAFT_NAMES


def candidate_score(candidate: dict) -> float:
    """Source support of one candidate, 0 to 1: row coverage x long-component
    support x trace contrast. A full, continuous, dark stroke scores near 1."""
    support = candidate.get("source_support", {})
    product = 1.0
    for key in ("observed_row_fraction", "long_component_support_fraction", "mean_trace_contrast"):
        value = support.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            return 0.0
        product *= min(1.0, max(0.0, float(value)))
    return round(product, 4)


def _guess_id(section_id, kind, candidate_id):
    return "guess-" + digest_object({"section_id": section_id, "kind": kind,
                                     "candidate_id": candidate_id})[:20]


def _metres(value):
    return f"{value:g}"


def model_choice_guess(section: dict, candidates: list[dict], choice: dict) -> dict:
    """The open guess of a verified model choice: the model's reason and the verifier's evidence."""
    chosen = next(c for c in candidates if c["candidate_id"] == choice["candidate_id"])
    return {"guess_id": _guess_id(section["id"], "model_choice", chosen["candidate_id"]),
            "section_id": section["id"], "kind": "model_choice", "x_m": section["x_m"], "x_range_m": None,
            "chosen_candidate_id": chosen["candidate_id"],
            "alternatives": [c["candidate_id"] for c in candidates if c["candidate_id"] != chosen["candidate_id"]],
            "score": candidate_score(chosen), "reason": choice["reason"][:MAX_REASON_CHARS],
            "status": "open", "verifier_evidence": choice["verifier_evidence"]}


def model_authored_guess(section: dict, candidates: list[dict], authored: dict) -> dict:
    """The open guess of a model-authored section: its label, basis and checks."""
    chosen = next(c for c in candidates if c["candidate_id"] == authored["candidate_id"])
    label = chosen["authored"]["source_label"]
    return {"guess_id": _guess_id(section["id"], "model_authored", chosen["candidate_id"]),
            "section_id": section["id"], "kind": "model_authored", "x_m": section["x_m"], "x_range_m": None,
            "chosen_candidate_id": chosen["candidate_id"],
            "alternatives": [c["candidate_id"] for c in candidates
                             if c["candidate_id"] != chosen["candidate_id"] and "authored" not in c],
            "score": None, "reason": (label + ": " + chosen["authored"]["basis"])[:MAX_REASON_CHARS],
            "status": "open", "verifier_evidence": authored["verifier_evidence"]}


def panel_recommendation(entry: dict, candidates: list[dict]) -> dict | None:
    """The shared-panel assignment of a section (panel_assignment.py), when it names one of ``candidates``."""
    recommendation = entry.get("recommended_station_assignment")
    if not isinstance(recommendation, dict):
        return None
    if not any(c["candidate_id"] == recommendation.get("candidate_id") for c in candidates):
        return None
    return recommendation


def recommended_guess(section: dict, candidates: list[dict], recommendation: dict) -> dict:
    """Best-candidate guess that follows the shared-panel assignment (one stroke per station)."""
    chosen = next(c for c in candidates if c["candidate_id"] == recommendation["candidate_id"])
    others = [c["candidate_id"] for c in candidates if c["candidate_id"] != chosen["candidate_id"]]
    preferred = [cid for cid in recommendation.get("alternatives", []) if cid in others]
    alternatives = preferred + [cid for cid in others if cid not in preferred]
    reason = (f"Shared panel: stroke {recommendation.get('nesting_rank')} of "
              f"{recommendation.get('strokes_in_panel')} from outside by nesting order, for the station "
              f"{recommendation.get('expected_width_rank')} nearest midship "
              f"(confidence {recommendation.get('confidence', 0):.2f}).")
    warnings = recommendation.get("warnings") or []
    if warnings:
        reason += " Warning: " + "; ".join(warnings)
    return {"guess_id": _guess_id(section["id"], "best_candidate", chosen["candidate_id"]),
            "section_id": section["id"], "kind": "best_candidate", "x_m": section["x_m"],
            "x_range_m": None, "chosen_candidate_id": chosen["candidate_id"], "alternatives": alternatives,
            "score": candidate_score(chosen), "reason": reason[:MAX_REASON_CHARS], "status": "open"}


def make_guesses(sections: list[dict], selected: dict, catalog: dict,
                 model_choices: dict | None = None, authored: dict | None = None) -> list[dict]:
    """One open guess for every section that has no person- or policy-selected line.

    ``sections`` are the declared spec sections. A section with a verified
    model choice keeps that choice. A section of a shared panel with a
    ``recommended_station_assignment`` (panel_assignment.py) takes that
    stroke, so the stations of one panel do not all take one stroke. Other
    sections with a selectable candidate get the best-scoring one.
    Unreadable sections are left out of the draft; the loft spans them
    (bridged_gap) or the draft ends before them (dropped_end).
    """
    guesses, read_x = [], [s["x_m"] for s in sections if s["id"] in selected]
    unread = []
    model_choices, authored = model_choices or {}, authored or {}
    for section in sections:
        sid = section["id"]
        if sid in selected:
            continue
        candidates = [c for c in catalog.get(sid, {}).get("candidates", []) if c.get("selectable") is True]
        proposal = authored.get(sid)
        if proposal is not None and any(c["candidate_id"] == proposal["candidate_id"] for c in candidates):
            guesses.append(model_authored_guess(section, candidates, proposal))
            read_x.append(section["x_m"])
            continue
        choice = model_choices.get(sid)
        if choice is not None and any(c["candidate_id"] == choice["candidate_id"] for c in candidates):
            guesses.append(model_choice_guess(section, candidates, choice))
            read_x.append(section["x_m"])
            continue
        # A traced line enters a draft only through a station claim: the
        # best-score guess never takes one (a panel's traced strokes are
        # candidates of every section that shares the panel).
        candidates = [c for c in candidates if not c.get("model_traced")]
        recommended = panel_recommendation(catalog.get(sid, {}), candidates)
        if recommended is not None:
            guesses.append(recommended_guess(section, candidates, recommended))
            read_x.append(section["x_m"])
            continue
        # Panel strokes enter a draft through the panel assignment; a section
        # whose only lines are panel strokes still takes one (it is readable).
        inspected = [c for c in candidates if not c.get("panel_stroke")]
        candidates = inspected or candidates
        if not candidates:
            unread.append(section)
            continue
        ranked = sorted(candidates, key=lambda c: (-candidate_score(c),
                                                   not c.get("grid_supported_hypothesis", False),
                                                   c["candidate_id"]))
        chosen, score = ranked[0], candidate_score(ranked[0])
        if len(candidates) > 1:
            reason = f"{len(candidates)} lines found; took the best-supported one (score {score:.2f})."
        else:
            competing = chosen.get("non_grid_competing_components") or 0
            reason = (f"One line found, but {competing} other strokes compete with it; "
                      f"took it (score {score:.2f}).")
        guesses.append({"guess_id": _guess_id(sid, "best_candidate", chosen["candidate_id"]),
                        "section_id": sid, "kind": "best_candidate", "x_m": section["x_m"],
                        "x_range_m": None, "chosen_candidate_id": chosen["candidate_id"],
                        "alternatives": [c["candidate_id"] for c in ranked[1:]], "score": score,
                        "reason": reason, "status": "open"})
        read_x.append(section["x_m"])
    for section in unread:
        sid, x = section["id"], section["x_m"]
        lower = max((v for v in read_x if v < x), default=None)
        upper = min((v for v in read_x if v > x), default=None)
        if lower is not None and upper is not None:
            kind, x_range = "bridged_gap", [lower, upper]
            reason = (f"No readable line at x={_metres(x)} m; smoothed across "
                      f"x={_metres(lower)} to {_metres(upper)} m.")
        else:
            edge = lower if lower is not None else upper
            kind = "dropped_end"
            x_range = None if edge is None else [min(x, edge), max(x, edge)]
            reason = (f"No readable line at x={_metres(x)} m at the end of the hull; "
                      + ("no line was read anywhere." if edge is None
                         else f"the draft stops at x={_metres(edge)} m."))
        guesses.append({"guess_id": _guess_id(sid, kind, None), "section_id": sid, "kind": kind,
                        "x_m": x, "x_range_m": x_range, "chosen_candidate_id": None,
                        "alternatives": [], "score": None, "reason": reason, "status": "open"})
    order = {s["id"]: index for index, s in enumerate(sections)}
    return sorted(guesses, key=lambda g: order[g["section_id"]])


def guessed_choices(guesses: list[dict]) -> dict:
    """The identity part of open guesses: section id -> chosen candidate id or None.

    It holds no floating-point values, so the Rust controller recomputes the
    same generation identity from it.
    """
    return {g["section_id"]: g["chosen_candidate_id"] for g in guesses}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def check_guess(guess) -> bool:
    """Shape and type of one open guess record (no catalog cross-check)."""
    if type(guess) is not dict or guess.get("status") != "open":
        return False
    if guess.get("kind") in MODEL_AUTHORED_KINDS:
        evidence = guess.get("verifier_evidence")
        if (set(guess) != MODEL_CHOICE_FIELDS or type(evidence) is not dict or evidence.get("passed") is not True
                or len(json.dumps(evidence)) > MAX_EVIDENCE_BYTES):
            return False
    elif set(guess) != GUESS_FIELDS:
        return False
    if guess["kind"] not in GUESS_KINDS or type(guess["section_id"]) is not str or not guess["section_id"]:
        return False
    if type(guess["guess_id"]) is not str or not guess["guess_id"].startswith("guess-"):
        return False
    if not _finite(guess["x_m"]) or type(guess["reason"]) is not str:
        return False
    if not 0 < len(guess["reason"]) <= MAX_REASON_CHARS:
        return False
    alternatives = guess["alternatives"]
    if type(alternatives) is not list or any(type(a) is not str for a in alternatives):
        return False
    x_range = guess["x_range_m"]
    if x_range is not None and (type(x_range) is not list or len(x_range) != 2
                                or not all(_finite(v) for v in x_range) or x_range[0] > x_range[1]):
        return False
    if guess["kind"] == "model_authored":
        return (type(guess["chosen_candidate_id"]) is str and guess["score"] is None and x_range is None
                and guess["chosen_candidate_id"] not in alternatives)
    if guess["kind"] in ("best_candidate", "model_choice"):
        return (type(guess["chosen_candidate_id"]) is str and _finite(guess["score"])
                and 0 <= guess["score"] <= 1 and x_range is None
                and guess["chosen_candidate_id"] not in alternatives)
    if guess["chosen_candidate_id"] is not None or guess["score"] is not None or alternatives:
        return False
    if guess["kind"] == "bridged_gap":
        return x_range is not None and x_range[0] < guess["x_m"] < x_range[1]
    return True


def check_draft(draft) -> bool:
    """Shape of the ``draft`` object carried by a draft spec and its run record."""
    if type(draft) is not dict or set(draft) != {"status", "guesses"} or draft["status"] != DRAFT_STATUS:
        return False
    guesses = draft["guesses"]
    if type(guesses) is not list or not 1 <= len(guesses) <= MAX_GUESSES:
        return False
    ids = [g.get("section_id") if type(g) is dict else None for g in guesses]
    return all(check_guess(g) for g in guesses) and len(set(ids)) == len(ids)


# Smallest height, in pixels, of a centreline run at the panel top that counts
# as a drawn closure line. A hull curve that only touches the centreline at the
# top (a pointed stern section) spans about one pixel row there.
TOP_CLOSURE_MINIMUM_RUN_PX = 3.


def trim_top_closure(points: list, minimum_breadth_m: float, z_max_m: float | None,
                     pixel_m: float | None) -> list | None:
    """Points without the deck/centreline closure above the hull curve, or None.

    A traced contour often continues above the hull: a deck camber line to the
    centreline and then up the centreline to the panel top (``z_max_m``).
    Neither is hull ink. The trimmed section ends at the top of the hull curve;
    the CAD top closure then goes straight to the centreline at that height.
    Removed, in this order:
      1. a top run on the centreline (breadth at most ``minimum_breadth_m``)
         that reaches the panel top and is at least three pixels high;
      2. then, top segments that go inward and are flatter than 45 degrees
         (a deck camber line; a hull side at the top is steeper or flares out).
    A constant-breadth line up to the panel top is kept: it cannot be told
    apart from wall-sided topsides. Returns None when nothing is removed, when
    the calibration is unknown, or when fewer than five points would remain.
    """
    import numpy as np

    if z_max_m is None or pixel_m is None:
        return None
    ordered = np.asarray(points, dtype=float)
    ordered = ordered[np.argsort(ordered[:, 1], kind="stable")]
    y, z = ordered[:, 0], ordered[:, 1]
    if z[-1] < z_max_m - pixel_m:
        return None
    end = len(ordered)
    while end > 0 and y[end - 1] <= minimum_breadth_m:
        end -= 1
    if end == len(ordered) or end == 0 or z[-1] - z[end] < TOP_CLOSURE_MINIMUM_RUN_PX * pixel_m:
        return None
    while end >= 2 and y[end - 2] - y[end - 1] > z[end - 1] - z[end - 2]:
        end -= 1
    if end < 5:
        return None
    return ordered[:end].tolist()


def _pixel_metres(declared_section: dict | None) -> float | None:
    calibration = (declared_section or {}).get("calibration") or {}
    scale = calibration.get("pixels_per_metre")
    return 1. / scale if isinstance(scale, (int, float)) and not isinstance(scale, bool) and scale > 0 else None


def prepare_draft_sections(sections: list[dict], declared: list[dict]) -> tuple[list[dict], list[dict]]:
    """Make draft-only profiles usable; generated geometry stays explicitly labelled."""
    import copy
    import numpy as np
    from .errors import GeometryError
    from .schema import gap

    # Draft construction constants, not evidence or scoring tolerances.
    minimum_breadth_m = .001
    interpolation_samples = 129
    prepared = copy.deepcopy(sections)
    declared_by_id = {item["id"]: item for item in declared}
    warnings = []
    for section in prepared:
        # The source label of each section (see section_authoring.SOURCE_LABELS).
        section.setdefault("source_label", "traced")
        if "points_yz_m" not in section:
            continue
        spec_section = declared_by_id.get(section["id"])
        trimmed = trim_top_closure(section["points_yz_m"], minimum_breadth_m,
                                   (spec_section or {}).get("z_max_m"), _pixel_metres(spec_section))
        if trimmed is not None:
            removed_to_m = max(z for _, z in section["points_yz_m"])
            section["points_yz_m"] = trimmed
            warnings.append(gap("draft_top_trimmed", f"Top closure trimmed to the top of the hull curve at z {trimmed[-1][1]:.2f} m; "
                                f"removed a deck and centreline line up to z {removed_to_m:.2f} m.",
                                section["id"], severity="warning"))
        points = np.asarray(section["points_yz_m"], dtype=float)
        positive = np.flatnonzero(points[:, 0] > 0)
        if len(positive):
            pinched = np.flatnonzero(points[:, 0] < minimum_breadth_m)
            if len(pinched):
                # One millimetre is a draft construction floor, not measured ink.
                points[pinched, 0] = minimum_breadth_m
                section["points_yz_m"] = points.tolist()
                if section["source_label"] == "traced":
                    section["source_label"] = "repaired"
                warnings.append(gap("draft_repaired", "Centreline breadth clamped to 1 mm for draft CAD; avoids pinches and zero-width closures.", section["id"], severity="warning"))
    anchors = sorted([s for s in prepared if "points_yz_m" in s], key=lambda s: s["x_m"])
    found = {s["id"] for s in prepared}
    for missing in declared:
        if missing["id"] in found:
            continue
        if not anchors:
            raise GeometryError(f"Section {missing['id']}: no usable neighbouring profile for draft interpolation.")
        x = missing["x_m"]
        left = max((s for s in anchors if s["x_m"] < x), key=lambda s: s["x_m"], default=anchors[0])
        right = min((s for s in anchors if s["x_m"] > x), key=lambda s: s["x_m"], default=anchors[-1])
        weight = 0. if left["x_m"] == right["x_m"] else (x - left["x_m"]) / (right["x_m"] - left["x_m"])
        t = np.linspace(0., 1., interpolation_samples)
        profiles = []
        for neighbour in (left, right):
            points = np.asarray(neighbour["points_yz_m"], dtype=float)
            z = points[0, 1] + t * (points[-1, 1] - points[0, 1])
            profiles.append(np.column_stack([np.interp(z, points[:, 1], points[:, 0]), z]))
        points = (1 - weight) * profiles[0] + weight * profiles[1]
        prepared.append({"id": missing["id"], "x_m": x, "points_yz_m": points.tolist(),
                         "coverage": 0., "confidence": 0., "evidence": {}, "source_label": "interpolated",
                         "warnings": ["Draft interpolation; not measured source geometry."]})
        warnings.append(gap("draft_interpolated", "Missing section interpolated from neighbouring profiles for draft CAD.", missing["id"], severity="warning"))
    return sorted(prepared, key=lambda s: s["x_m"]), warnings


def section_sources(sections: list[dict], guesses: list[dict]) -> dict:
    """Source label of every section of a draft build, and the count per label.

    ``sections`` are the built sections (each with ``source_label``). A station
    that the loft spans is ``interpolated``; one beyond the draft's end is
    ``omitted``. A model-authored section also gives the model's basis.
    """
    rows = []
    for section in sorted(sections, key=lambda s: s["x_m"]):
        row = {"section_id": section["id"], "label": section.get("source_label", "traced")}
        basis = section.get("evidence", {}).get("authored_basis")
        if basis:
            row["basis"] = basis
        rows.append(row)
    built = {row["section_id"] for row in rows}
    for guess in guesses:
        if guess["section_id"] not in built and guess["kind"] in ("bridged_gap", "dropped_end"):
            rows.append({"section_id": guess["section_id"],
                         "label": "interpolated" if guess["kind"] == "bridged_gap" else "omitted"})
    counts = {}
    for row in rows:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    return {"sections": rows, "counts": counts}
