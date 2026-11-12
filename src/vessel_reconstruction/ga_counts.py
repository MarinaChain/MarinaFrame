"""Commercial GA counts."""
from __future__ import annotations

from . import source_record
from .ga_commercial_settings import (
    COUNT_KINDS,
    DEFINITIONS,
)
from .ga_vocabulary import DECK_NAME_WORDS, FITTING_WORDS, KIND_WORDS, NOTE_WORDS, ROOM_NOUNS, SYSTEM_WORDS
import re


def _number_key(number: str | None) -> str | None:
    """'No. 3', '3', 'NO3' -> '3'; '4 A' -> '4A'. None for an unnumbered item."""
    if not number:
        return None
    key = re.sub(r"^(?:NO\.?|N°)\s*", "", number.strip().upper())
    key = re.sub(r"[\s.]", "", key)
    return key or None


def _number_with_side(number: str | None, label: str) -> str | None:
    """The number token with the side that the label prints: ("3", "NO.3 C.O.TK(P)") -> "3P".

    The model sometimes gives the bare number of a label that prints its side; the views are
    compared by number and side, so the side comes from the label.
    """
    if not number or not re.fullmatch(r"(?:NO\.?\s*)?\d+", number.strip(), re.I):
        return number
    side = re.search(r"\(\s*([PSC])\s*\)", label.upper())
    return f"{number.strip()}{side[1]}" if side else number


def _base_number(number: str | None) -> str | None:
    """The space number without its side: '1P', '1 (S)', '1P&S' -> '1'; '4A' stays '4A'."""
    key = _number_key(number)
    if key is None:
        return None
    return re.sub(r"\(?(?:P&S|P/S|PS|P|S|C)\)?$", "", key) or key


def _count_key(number: str | None, kind: str, definitions: dict) -> str | None:
    """The number under which a space is counted: '4A' and '4F' are one hold when the
    definition says that halves of one number are one hold."""
    key = _number_key(number)
    if key and kind == "cargo_hold" and not definitions["split_holds_are_separate"]:
        return re.sub(r"(?<=\d)[A-Z]$", "", key)
    return key


def _highest_number(numbers: set) -> int | None:
    """The largest leading whole number of space numbers ('4A', '4F', '3' -> 4)."""
    leading = [int(match[0]) for number in numbers if number and (match := re.match(r"\d+", number))]
    return max(leading, default=None)


def _words(label: str) -> list[str]:
    """The words of a label in capitals, letter-spaced words joined ('T. S. W. B. T.' -> 'TSWBT')."""
    from .ga_labels import joined_letters
    text = joined_letters(label.upper())
    text = re.sub(r"(?<=\b[A-Z])\.\s?(?=[A-Z]\b)", "", text)  # 'W.B.T' -> 'WBT'
    return re.findall(r"[A-Z]+", text)


def _named_words(label: str) -> list[str]:
    """The words of a label without "NO" and without its side marks in parentheses ("(P&S)")."""
    without_sides = re.sub(r"\(\s*(?:P\s*[&/,]?\s*S|P|S|C)\s*\)?", " ", label.upper())
    return [word for word in _words(without_sides) if word != "NO"]


def fragment_reason(space: dict, others: list[dict], vocabulary: set[str],
                    whole_labels: set[str] = frozenset()) -> str | None:
    """Why a label is a piece of a label, not a space; None for a whole label.

    ``vocabulary`` is every word of the other labels on the sheet, ``whole_labels`` their word
    sequences joined; ``others`` are the other spaces (for a piece read at the place of a longer
    label).
    """
    label = space["label"].strip()
    words = _words(label)
    if not [word for word in words if word != "NO"]:
        return "no words: only a number"
    if label.count("(") != label.count(")"):
        return "an unclosed parenthesis: the label is cut"
    if ((re.search(r"\d\s*\.?\s*[A-Z]\.?$", label.upper()) and len(words[-1]) == 1 and len(words) <= 2)
            or re.fullmatch(r"NO\.?\s*(?:\d+|I)\s*\.?\s*[A-Z]\.?", label.upper().strip())):
        # Also "NO.I T.": a capital I read for the number 1 (round u10).
        return "a single letter after the number: the label is cut"
    # CR.1 is a complete crane label, not a cut prefix of CRANE in another view.
    # Keep the shared non-cargo exclusions; malformed parentheses were checked above.
    if space.get("kind") == "cargo_crane" and re.search(KIND_WORDS["cargo_crane"], label.upper()):
        return None
    is_room = bool(_named_words(label)) and _named_words(label)[-1] in ROOM_NOUNS
    if space.get("kind") in ("other_space", "other_tank") and not is_room and (
            FITTING_WORDS & set(words) or re.search(r"\bA\s*/\s*H\b", label.upper())):
        # "A/H" is an access hatch (review round 4).
        return "a fitting or an opening, not a space"
    # A last word cut inside a fitting word ("HATCH OPENI" for "HATCH OPENING"). Four letters at
    # least, so that a short word of a real room is not taken for the start of a fitting word.
    if space.get("kind") in ("other_space", "other_tank") and len(words[-1]) >= 4 and any(
            fitting.startswith(words[-1]) and fitting != words[-1] for fitting in FITTING_WORDS):
        return f"'{words[-1]}' is the start of a fitting word: a cut fitting or opening label"
    if len(words) == 1 and space.get("kind") in ("other_space", "other_tank") and words[0] in SYSTEM_WORDS:
        return f"'{words[0]}' names a system; the room noun of the label is missing"
    untyped = space.get("kind") in ("other_space", "other_tank")
    outside_parentheses = _named_words(re.sub(r"\([^)]*\)", " ", label))
    if untyped and outside_parentheses and outside_parentheses[-1] in DECK_NAME_WORDS:
        # "UPPER DECK", "2ND DECK" name a deck level of the drawing (review round 4); a room with
        # its deck in parentheses ("CHANGING ROOM (DECK)") is a room.
        return "a deck name, not a space"
    if untyped and NOTE_WORDS & set(words):
        return "a note on the drawing (a type or a size), not a space"
    return _fragment_from_other_labels(space, others, vocabulary, whole_labels, label, words, untyped)


def drop_fragments(result: dict, removed_out: list | None = None) -> int:
    """Remove spaces whose label is a piece of a label (lane W: "NO. 4", "NO. 2 CARG", "GEAR").

    Each removal is listed in ``checks`` (``fragment_label_dropped``) with its reason; counts are
    recomputed. Returns the number removed.
    """
    spaces = result["spaces"]
    removed = []
    for space in list(spaces):
        others = [other for other in spaces if other is not space and other not in removed]
        vocabulary = {word for other in others for word in _words(other["label"])}
        whole_labels = {"".join(_words(other["label"])) for other in others}
        reason = fragment_reason(space, others, vocabulary, whole_labels)
        if reason:
            removed.append(space)
            if removed_out is not None:
                removed_out.append((space, reason))
            result["checks"].append({"code": "fragment_label_dropped", "status": "dropped",
                                     "label": space["label"][:64], "reason": reason[:160]})
    for space in removed:
        spaces.remove(space)
    if removed and "model_counts" in result:
        finish_counts(result)
    return len(removed)


def finish_counts(result: dict) -> None:
    """Counts from the model's counts, checked against the numbered spaces and across views.

    A count is kept only when (1) no single view shows more differently numbered spaces of its
    kind than the model counted, and (2) every view that shows two or more numbered spaces of
    the kind ends at the same highest number (for example the holds of the profile and of the
    tank top plan). A view that misses some labels in between is not a contradiction.
    """
    ga_name = (result["sources"].get("ga") or result["sources"].get("particulars"))["file"]
    definitions = result.get("definitions") or DEFINITIONS
    result["checks"] = [c for c in result["checks"] if c.get("code") != "holds_and_hatches_differ"]
    for name, kind in COUNT_KINDS.items():
        reading_count = result["model_counts"][name]
        spaces = [s for s in result["spaces"] if s["kind"] == kind]
        numbered = [s for s in spaces if s["status"] == "read" and _number_key(s["number"])]
        # Numbers per view: views write the same tanks differently ("1 (P&S)" in the profile,
        # "1P" and "1S" on the tank top), so labels are counted within one view, never across.
        full_by_view: dict[str, set] = {}
        base_by_view: dict[str, set] = {}
        for space in numbered:
            view = space["view_id"] or "?"  # spaces outside every named view form one group
            full_by_view.setdefault(view, set()).add(_count_key(space["number"], kind, definitions))
            # Where a view's numbering ends comes from the coarse pass only: it lists every
            # numbered hold, hatch and tank per view. The fine pass reads only some crops, so a
            # view it saw two labels in is not a view that ends there (review round 2).
            if space.get("found_by", "coarse") == "coarse":
                base_by_view.setdefault(view, set()).add(_base_number(space["number"]))
        # A fine-pass label adds its number to a view that the coarse pass listed (the coarse
        # pass can miss the last label of a view; the label is printed there all the same).
        # It does not make a view of its own.
        for space in numbered:
            view = space["view_id"] or "?"
            if space.get("found_by") == "fine" and len(base_by_view.get(view, ())) >= 2:
                base_by_view[view].add(_base_number(space["number"]))
        # A bare number beside the same number with a side ("6" and "6P", "6S" in one view) is a
        # second label of those tanks (a cut label), not another tank.
        for found in full_by_view.values():
            found -= {key for key in found if any(f"{key}{side}" in found for side in "PSC")}
        labelled = max((len(found) for found in full_by_view.values()), default=0)
        # A view may miss a label (hidden by other ink, not listed); that is not a contradiction.
        # Views contradict when their highest space number differs (profile up to No.5, tank top up
        # to No.4): one of them shows a hold that the other does not have at the end.
        compared = {view: found for view, found in base_by_view.items()
                    if len(found) >= 2 and view != "?"}
        highest = {view: _highest_number(found) for view, found in compared.items()}
        agree = len({top for top in highest.values() if top is not None}) <= 1
        entry = {"labelled_items": labelled, "views_compared": len(compared)}
        if "missing" in reading_count:
            entry.update(value=None, status="unknown", reason=reading_count["missing"])
        else:
            value = int(reading_count["value"])
            entry.update(value=value, status="read", evidence=reading_count["evidence"])
            if labelled > value:
                entry.update(value=None, status="unknown",
                             reason=f"the model counted {value} but one view has {labelled} differently numbered items")
                result["checks"].append({"code": "count_below_labels", "count": name, "status": "check"})
            elif not agree:
                detail = "; ".join(f"{view}: up to No.{top}" for view, top in sorted(highest.items()))
                entry.update(value=None, status="unknown", reason=f"views disagree ({detail})"[:240])
                result["checks"].append({"code": "views_disagree", "count": name, "status": "check"})
        regions = [s["source_record"]["regions"][0] for s in spaces if s["source_record"]["kind"] == "read"]
        if entry["value"] is None:
            entry["source_record"] = source_record.unknown(entry["reason"])
        elif regions:
            entry["source_record"] = source_record.read(regions)
        else:
            entry["source_record"] = source_record.guessed(
                "count judged by the model from the drawing: " + reading_count["evidence"],
                [source_record.region(ga_name, view=None)])
        result["counts"][name] = entry
    # Holds and main hatches are usually equal on a bulk carrier. A difference is not refused
    # (a hold can have two hatches); it is listed for the reader.
    holds, hatches = result["counts"]["cargo_holds"]["value"], result["counts"]["cargo_hatches"]["value"]
    if ((result.get("ship_type") or {}).get("value") == "bulk_carrier" and holds is not None and hatches is not None
            and holds != hatches):
        result["checks"].append({"code": "holds_and_hatches_differ", "status": "check"})


def _fragment_from_other_labels(space, others, vocabulary, whole_labels, label, words, untyped):
    last = words[-1]
    raw_last = label.upper().split()[-1] if label.split() else ""
    named = _named_words(label)
    if space.get("number") and "." in raw_last and named and not re.search(r"\(", raw_last):
        # A dotted abbreviation that is the start of a word in another label of the same number
        # ("NO. 2 F.O." beside "NO.2 F.O.T.").
        base = re.sub(r"[^0-9]", "", str(space["number"]))
        for other in others:
            if base and re.sub(r"[^0-9]", "", str(other.get("number") or "")) == base:
                if any(word.startswith(named[-1]) and len(word) > len(named[-1]) for word in _words(other["label"])):
                    return f"'{raw_last}' is the start of '{other['label'][:30]}': the label is cut"
    family = "".join(named)
    # Only an untyped label without a number (two dotted letters and a side, "X. Y. (P)"): a numbered or typed tank whose letters
    # end another family ("W.B.T." and "T.S.W.B.T.") is a tank of its own.
    if 2 <= len(family) <= 4 and space.get("kind") in ("other_space", "other_tank") and not space.get("number"):
        for other in others:
            other_family = "".join(_named_words(other["label"]))
            if (other_family != family and other_family.endswith(family)
                    and len(other_family) - len(family) <= 3 and not other_family.endswith("S" + family[-1:])):
                return f"the end of the label '{other['label'][:40]}': the label is cut at its start"
    # A dotted abbreviation ("O.T.") is not a cut word, only a plain word of three letters or more.
    if (len(last) >= 3 and "." not in raw_last and last not in vocabulary
            and any(word.startswith(last) and len(word) > len(last) for word in vocabulary)):
        return f"'{last}' is the start of a longer word printed on the sheet: the label is cut"
    if (len(words) == 1 and space.get("kind") in ("other_space", "other_tank") and words[0] in vocabulary
            and words[0] not in whole_labels):
        return f"'{words[0]}' is printed only as a part of longer labels on the sheet"
    if untyped and not space.get("number") and len(family) >= 3:
        # The letters of a typed, numbered tank or hold without its number ("X.Y.T.K(P)" beside
        # "NO.1 X.Y.TK(P&S)"): that space read a second time (round u6r5: its box took 90 % of
        # the cargo tank).
        for other in others:
            if (other.get("kind") not in ("other_space", "other_tank") and other.get("number")
                    and "".join(_named_words(other["label"])) == family):
                return f"the label of '{other['label'][:40]}' read without its number"
    region = (space["source_record"].get("regions") or [{}])[0].get("box_px")
    for other in others:
        other_region = (other["source_record"].get("regions") or [{}])[0].get("box_px")
        other_words = _words(other["label"])
        if (region and other_region and len(other_words) > len(words)
                and space.get("kind") in ("other_space", "other_tank") and not space.get("number")
                and any(other_words[i:i + len(words)] == words for i in range(len(other_words) - len(words) + 1))
                and region[0] < other_region[2] and other_region[0] < region[2]
                and region[1] < other_region[3] and other_region[1] < region[3]):
            return f"a part of the label '{other['label'][:40]}' read at the same place"
    return None
