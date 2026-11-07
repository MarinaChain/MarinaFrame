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

DRAFT_STATUS = "draft_not_verified"
GUESS_KINDS = ("best_candidate", "bridged_gap", "dropped_end", "model_choice")
GUESS_FIELDS = {"guess_id", "section_id", "kind", "x_m", "x_range_m", "chosen_candidate_id",
                "alternatives", "score", "reason", "status"}
# A model choice also carries the deterministic verifier's evidence.
MODEL_CHOICE_FIELDS = GUESS_FIELDS | {"verifier_evidence"}
MAX_EVIDENCE_BYTES = 4096
MAX_GUESSES = 300
MAX_REASON_CHARS = 512
# Exported CAD file names of a draft build. The tag is in the file name, so a
# downloaded draft file cannot be mistaken for a verified export.
DRAFT_EXPORT_NAMES = {"step": "model-draft.step", "stl": "model-draft.stl"}


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


def make_guesses(sections: list[dict], selected: dict, catalog: dict,
                 model_choices: dict | None = None) -> list[dict]:
    """One open guess for every section that has no person- or policy-selected line.

    ``sections`` are the declared spec sections. A section with a verified
    model choice keeps that choice. Other sections with a selectable
    candidate get the best-scoring one. Unreadable sections are left out of the
    draft; the loft spans them (bridged_gap) or the draft ends before them
    (dropped_end).
    """
    guesses, read_x = [], [s["x_m"] for s in sections if s["id"] in selected]
    unread = []
    model_choices = model_choices or {}
    for section in sections:
        sid = section["id"]
        if sid in selected:
            continue
        candidates = [c for c in catalog.get(sid, {}).get("candidates", []) if c.get("selectable") is True]
        if not candidates:
            unread.append(section)
            continue
        choice = model_choices.get(sid)
        if choice is not None and any(c["candidate_id"] == choice["candidate_id"] for c in candidates):
            guesses.append(model_choice_guess(section, candidates, choice))
            read_x.append(section["x_m"])
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
    if guess.get("kind") == "model_choice":
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
