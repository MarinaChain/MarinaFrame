"""The printed dimension chain along the profile: spans tied to frames (no extra request).

The scale request may return ``chain_spans``: each printed span of the dimension chain ("28400"
between two extension lines), with the centre of its text and its two end marks. A span is kept
only when it reads as one plausible length, both end marks lie on a frame of the fitted scale,
its text lies between its marks, and its length fits the frame table between those frames; two
different lengths for the same frames are both refused. Every other span goes to checks with a
reason (``printed_span_ignored``). Kept spans are printed truth: ``frames.printed_spans``.
"""
from __future__ import annotations

import re

# One printed length: "28400", "28,400", "28.400 mm", "28.4 m", or the total of "35@800=28000".
SPAN_TEXT = re.compile(r"^(?:.*=\s*)?(\d[\d.,]*)\s*(mm|m)?\.?\s*$", re.I)
SPAN_RANGE_M = (0.3, 400.0)
# An end mark lies on a frame when it is within this share of a frame of one.
MARK_TOLERANCE_FRAMES = 0.35
# The printed length must fit the frame table between the two frames within this share of a frame.
LENGTH_TOLERANCE_FRAMES = 0.5
PRINTED = "printed"


def parse_span_m(printed: str) -> float | None:
    """Metres of one printed span, or None. A number above 100 is millimetres, and a comma or dot
    in it is a thousands mark ("28,400" and "28.400" are both 28.4 m)."""
    match = SPAN_TEXT.match(printed.strip())
    if not match:
        return None
    number, unit = match.group(1), (match.group(2) or "").lower()
    try:
        value = float(number.replace(",", "."))
    except ValueError:
        return None
    if unit == "mm" or (unit != "m" and value > 100):
        value = float(re.sub(r"[.,]", "", number)) / 1000
    low, high = SPAN_RANGE_M
    return value if low <= value <= high else None


def read_printed_spans(result: dict, work: dict) -> int:
    """Tie the chain spans of the scale reply to frames; returns how many were kept."""
    table = work.get("table")
    chains = (work.get("raw") or {}).get("chains") or {}
    candidates, ignored = [], []
    for view, spans in chains.items():
        axis = work["axes"].get(view)
        for span in spans:
            reason, length = None, parse_span_m(span["printed"])
            if table is None or axis is None:
                reason = "the view of the span has no frame scale"
            elif length is None:
                reason = "the span does not read as one plausible length"
            else:
                ends = sorted(table.frame_at(axis.x_m(span[end][0])) for end in ("from", "to"))
                low_x, high_x = sorted((span["from"][0], span["to"][0]))
                if any(abs(end - round(end)) > MARK_TOLERANCE_FRAMES for end in ends):
                    reason = "an end mark of the span is not at a frame"
                elif not low_x < span["at"][0] < high_x:
                    reason = "the text of the span is not between its marks"
                else:
                    first, last = (int(round(end)) for end in ends)
                    between = table.x_m(last) - table.x_m(first)
                    if last <= first or abs(length - between) > LENGTH_TOLERANCE_FRAMES * table.spacing_m(first):
                        reason = "the printed length does not fit the frames of its marks"
                    else:
                        candidates.append({"from_frame": first, "to_frame": last, "length_m": round(length, 3),
                                           "text": span["printed"][:48], "status": PRINTED})
            if reason:
                ignored.append((span["printed"][:48], reason))
    kept, seen = [], {}
    for span in candidates:
        seen.setdefault((span["from_frame"], span["to_frame"]), []).append(span)
    for same in seen.values():
        if len({span["length_m"] for span in same}) > 1:
            ignored += [(span["text"], "two different lengths are printed for the same frames") for span in same]
        else:
            kept.append(same[0])
    for text, reason in ignored:
        result["checks"].append({"code": "printed_span_ignored", "status": "dropped", "label": text, "reason": reason})
    if kept:
        result["frames"]["printed_spans"] = sorted(kept, key=lambda span: span["from_frame"])
    return len(kept)


def holds_with_printed_spans(spaces: list[dict], frames: dict) -> list[dict]:
    """A hold whose frames match exactly one printed span (one frame either way), with that span
    matching no other hold, takes the printed length centred on its measured box (status
    ``printed``); the measured box is kept as ``measured_box_m``."""
    spans = frames.get("printed_spans") or []
    holds = [space for space in spaces if space["kind"] == "cargo_hold" and (space.get("extent") or {}).get("frames")]

    def matches(span, hold):
        first, last = hold["extent"]["frames"]
        return abs(span["from_frame"] - first) <= 1 and abs(span["to_frame"] - last) <= 1

    kept = []
    for space in spaces:
        if space in holds:
            found = [span for span in spans if matches(span, space)]
            if len(found) == 1 and sum(matches(found[0], other) for other in holds) == 1:
                extent = dict(space["extent"])
                extent.setdefault("measured_box_m", {"x_m": extent["x_m"]})
                middle = (extent["x_m"][0] + extent["x_m"][1]) / 2
                half = found[0]["length_m"] / 2
                extent["x_m"] = [round(middle - half, 2), round(middle + half, 2)]
                extent["status"] = {**extent["status"], "x": PRINTED}
                extent["printed_span"] = found[0]["text"]
                extent.pop("outline_m", None)  # a trace of the measured box, not of the printed length
                space = {**space, "extent": extent}
        kept.append(space)
    return kept
