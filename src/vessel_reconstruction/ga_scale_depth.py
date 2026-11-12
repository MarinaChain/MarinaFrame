"""Commercial GA depth; rules and constants unchanged."""
from __future__ import annotations

from dataclasses import dataclass

from . import source_record
from .ga_scale_geometry import (
    _unknown,
)
from .ga_scale_settings import (
    BELOW_DECK_KINDS,
    DERIVED,
    MIDSHIP_SHARE,
    MIN_DECK_TOPS,
    POINT_SIGMA_IMAGE_PX,
    RAIL_OR_CAMBER_M,
    UNCONFIRMED,
)
import numpy as np


def tops_of_uncertain_cargo(result: dict, kinds: dict) -> list[float]:
    """The tops of cargo holds and tanks boxed in the profile with an "uncertain" boundary."""
    return [space["extent"]["z_m"][1] for space in result["spaces"]
            if space["kind"] in ("cargo_hold", "cargo_tank") and "z_m" in space.get("extent", {})
            and space["extent"].get("basis") == "uncertain"
            and kinds.get(space["extent"]["view_id"]) == "profile"]




@dataclass
class _DepthEvidence:
    """Read-only inputs shared by the depth decision steps."""
    kinds: dict
    midship: list
    cargo: list
    others: list
    tiers: list
    depth: dict
    seen: dict
    axis: object
    allowed: float
    highest: float | None
    pointed: float | None
    reference: float | None
    tops_agree: bool


def check_depth(result: dict, work: dict) -> None:
    """Check the measured depth against the tops of the spaces below the deck (profile).

    The upper deck is not lower than the top of any hold or tank below it. A measured depth is
    kept only when this check can be made and passes. The top of a hold can be lower than the
    deck (topside tanks above it), so a pointed deck line above the tops is kept and marked "not
    confirmed". A deck line below a top is a contradiction: the depth is then the median top of
    the cargo spaces when they agree (status ``derived_from_space_tops``), else null. A deck line
    with no boxed space to check it against is null. Without a deck line pointed amidships, the
    depth is the median top of the cargo spaces when at least three agree and another kind of
    space, or the lowest deckhouse tier, ends there too.
    """
    evidence = _depth_evidence(result, work)
    if _check_spaces_above_depth(result, evidence):
        return
    if evidence.pointed is not None:
        _check_pointed_depth(result, evidence)
        return
    _derive_unpointed_depth(result, evidence)


def _depth_evidence(result, work):
    kinds = work["kinds"]

    table = work["table"]
    ends = [table.x_m(span_end) for span_end in (table.spans[0]["from_frame"], table.spans[-1]["to_frame"])]
    midship = [ends[0] + share * (ends[1] - ends[0]) for share in MIDSHIP_SHARE]

    def tops_of(wanted, amidships_only=False) -> list[float]:
        tops = []
        for space in result["spaces"]:
            extent = space.get("extent", {})
            if (space["kind"] not in wanted or "z_m" not in extent or extent["basis"] != "outline"
                    or kinds.get(extent["view_id"]) != "profile"):
                continue
            centre = (extent["x_m"][0] + extent["x_m"][1]) / 2
            if amidships_only and not midship[0] <= centre <= midship[1]:
                continue  # a space under the poop or the forecastle ends above the upper deck
            tops.append(extent["z_m"][1])
        return tops

    cargo = tops_of(("cargo_hold", "cargo_tank"))
    others = tops_of([kind for kind in BELOW_DECK_KINDS if kind not in ("cargo_hold", "cargo_tank")], True)
    tiers = [s["extent"]["z_m"][0] for s in result["spaces"]
             if s["kind"] == "accommodation_deck" and "z_m" in s.get("extent", {})]
    depth = result["measured"]["depth_m"]
    own = ("depth_below_a_space_top", "depth_not_confirmed_by_space_tops", "depth_taken_from_cargo_space_tops")
    result["checks"] = [c for c in result["checks"] if c.get("code") not in own]
    seen = {"cargo_space_tops_m": sorted(cargo), "other_space_tops_m": sorted(others),
            "lowest_deckhouse_tier_m": min(tiers, default=None)}
    axis = work["axes"][next(view for view in work["axes"] if kinds.get(view) == "profile")]
    # Two measurements, each two pointed places on the fitted scale.
    one = (2 * POINT_SIGMA_IMAGE_PX + 2 * axis.rms_px) / abs(axis.px_per_m)
    allowed = 2 * max(depth.get("uncertainty_m") or 0.0, one)
    highest = max(cargo + others, default=None)
    pointed = depth["value"]
    reference = float(np.median(cargo)) if cargo else None
    # The cargo spaces agree on one top, nothing below the deck is higher, and there are enough of them.
    tops_agree = (len(cargo) >= MIN_DECK_TOPS and all(abs(top - reference) <= allowed for top in cargo)
                  and highest <= reference + allowed)

    return _DepthEvidence(kinds, midship, cargo, others, tiers, depth, seen, axis, allowed, highest, pointed, reference, tops_agree)


def _depth_from_tops(result, evidence, why: str, how: str) -> dict:
    regions = [s["source_record"]["regions"][0] for s in result["spaces"]
               if s["kind"] in ("cargo_hold", "cargo_tank") and "z_m" in s.get("extent", {})]
    return {"value": round(evidence.reference, 2), "status": DERIVED, "uncertainty_m": round(evidence.allowed, 2),
            "method": f"median top of {len(evidence.cargo)} cargo spaces boxed in the profile, on the frame scale; " + how,
            "scale_basis": evidence.axis.basis, "pointed_depth_m": evidence.pointed, "reason": why,
            "note": "an estimate from the read spaces, not a measured deck line and not a printed particular",
            "cross_check": {**evidence.seen, "pointed_depth_m": evidence.pointed, "result": "taken from the tops of the cargo spaces"},
            "source_record": source_record.validate(source_record.read(
                [*regions[:source_record.MAX_REGIONS - 1], result["frames"]["source_record"]["regions"][0]]))}



def _check_spaces_above_depth(result, evidence):
    # The cargo spaces are the reference for the deck at side: when enough of them agree on one
    # top and the pointed deck line lies there, a space of another kind boxed above that line is
    # the wrong box (development round u3: wing ballast tanks boxed 3.6 m above the deck), not a
    # wrong deck line. Its height is then a guess and the depth stands.
    cargo_agree = len(evidence.cargo) >= MIN_DECK_TOPS and all(abs(top - evidence.reference) <= evidence.allowed for top in evidence.cargo)
    if evidence.pointed is not None and cargo_agree and abs(evidence.pointed - evidence.reference) <= evidence.allowed and evidence.highest > evidence.pointed + evidence.allowed:
        above = 0
        for space in result["spaces"]:
            extent = space.get("extent", {})
            if (space["kind"] in BELOW_DECK_KINDS and space["kind"] not in ("cargo_hold", "cargo_tank")
                    and "z_m" in extent and extent["basis"] == "outline" and evidence.kinds.get(extent["view_id"]) == "profile"
                    and evidence.midship[0] <= (extent["x_m"][0] + extent["x_m"][1]) / 2 <= evidence.midship[1]
                    and extent["z_m"][1] > evidence.pointed + evidence.allowed):
                extent["status"]["z"] = "guessed"
                extent["z_note"] = "boxed above the deck at side that the cargo spaces confirm; height not measured"
                above += 1
        result["checks"].append({"code": "extent_above_the_deck", "status": "changed", "count": above})
        evidence.depth["cross_check"] = {**evidence.seen, "result": "agrees with the tops of the cargo spaces; spaces of other kinds "
                                                  "boxed above the deck are taken as guesses"}
        return True
    return False


def _check_pointed_depth(result, evidence):
    # A depth stays measured only when the check passes: some space below the deck was boxed
    # in the profile and none of them is higher than the deck line.
    if evidence.highest is None:
        reason = "the deck line could not be checked: no space below the deck was boxed in the profile"
        unsure = tops_of_uncertain_cargo(result, evidence.kinds)
        middle = float(np.median(unsure)) if unsure else None
        if (len(unsure) >= MIN_DECK_TOPS and all(abs(top - middle) <= evidence.allowed for top in unsure)
                and abs(evidence.pointed - middle) <= evidence.allowed):
            # Boxes the model marked "uncertain" agree with the pointed line: a depth with its
            # own status, never measured or derived, and never used to confirm a box (PM, round
            # u10; the circular-check lesson).
            result["measured"]["depth_m"] = {
                "value": evidence.pointed, "status": UNCONFIRMED, "uncertainty_m": round(evidence.allowed, 2),
                "method": "the pointed deck line at side, agreeing with the tops of cargo spaces boxed "
                          "in the profile with an uncertain boundary",
                "scale_basis": evidence.axis.basis, "pointed_depth_m": evidence.pointed, "reason": reason,
                "note": "not confirmed: no space below the deck has a clear boundary in the profile",
                "cross_check": {**evidence.seen, "uncertain_cargo_tops_m": sorted(unsure),
                                "result": "agrees with the tops of uncertain cargo boxes"},
                "source_record": evidence.depth["source_record"]}
            result["checks"].append({"code": "depth_unconfirmed_from_uncertain_boxes", "status": "check"})
            return
        result["measured"]["depth_m"] = {**_unknown(reason), "pointed_depth_m": evidence.pointed,
                                         "cross_check": {**evidence.seen, "result": "not checked"}}
        result["checks"].append({"code": "depth_not_checked", "status": "check"})
    elif evidence.pointed < evidence.highest - evidence.allowed:
        # The deck line or the boxes are wrong. When the cargo spaces agree on one top, that
        # top is the depth (a derived estimate); otherwise there is no depth.
        result["checks"].append({"code": "depth_below_a_space_top", "status": "check"})
        reason = (f"the pointed deck line ({evidence.pointed} m) lies below the top of a space boxed under the deck "
                  f"({round(evidence.highest, 2)} m)")
        # Another space below the deck ends at the pointed line: the boxes disagree among
        # themselves (development round u4: cargo tanks boxed to the rail above the deck while a
        # ballast tank ends at the deck line), so the cargo tops cannot replace the line.
        confirmed_by_other = any(abs(top - evidence.pointed) <= evidence.allowed for top in evidence.others)
        if confirmed_by_other:
            reason += "; another space below the deck ends at the pointed line, so the boxes disagree"
        # Cargo boxes a rail or bulwark height above the pointed line: the boxes may end on the
        # rail (development round u5) as well as the line may be below the deck; code cannot
        # tell which, so the cargo tops do not replace the line.
        rail_apart = evidence.highest - evidence.pointed <= RAIL_OR_CAMBER_M
        if rail_apart and not confirmed_by_other:
            reason += "; the boxes end a rail height above it, so which line is the deck at side is not clear"
        if evidence.tops_agree and not confirmed_by_other and not rail_apart:
            result["measured"]["depth_m"] = _depth_from_tops(result, evidence, reason, "the pointed line lay below them")
            result["checks"].append({"code": "depth_taken_from_cargo_space_tops", "status": "check"})
        else:
            result["measured"]["depth_m"] = {**_unknown(reason), "pointed_depth_m": evidence.pointed,
                                             "cross_check": {**evidence.seen, "result": "contradicted"}}
    elif evidence.pointed <= evidence.highest + evidence.allowed:
        evidence.depth["cross_check"] = {**evidence.seen, "result": "agrees with the top of the spaces below the deck"}
    elif evidence.tops_agree and evidence.pointed - evidence.reference <= RAIL_OR_CAMBER_M:
        # The moulded depth is to the deck AT SIDE, where the cargo spaces end.
        result["measured"]["depth_m"] = _depth_from_tops(result, evidence,
            f"the pointed deck line ({evidence.pointed} m) lies a rail or camber height above the cargo spaces: "
            "the deck at the centreline or a rail, not the deck at side",
            "the pointed line lay a rail or camber height above them")
        result["checks"].append({"code": "depth_taken_from_cargo_space_tops", "status": "check"})
    else:
        evidence.depth["cross_check"] = {**evidence.seen, "result": "not confirmed: the deck line lies above the tops of the "
                                                  "boxed spaces (topside tanks, or another deck)"}
        result["checks"].append({"code": "depth_not_confirmed_by_space_tops", "status": "check"})
    return


def _derive_unpointed_depth(result, evidence):
    support = [top for top in [*evidence.others, *evidence.tiers] if evidence.reference is not None and abs(top - evidence.reference) <= evidence.allowed]
    if evidence.tops_agree and support:
        result["measured"]["depth_m"] = _depth_from_tops(result, evidence,
            "no deck line was measured at side amidships (" + evidence.depth.get("reason", "") + ")",
            "another space or the lowest deckhouse tier ends at the same height")
