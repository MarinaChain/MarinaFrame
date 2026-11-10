"""Read labelled vessel particulars, without deriving values or choosing between conflicts.

Dimensions use metres and displacement uses metric tonnes. Source boxes use page
pixels when words are available; text-only callers explicitly retain a null box.
``resolve`` keeps typed fields separate from readings, including after page edits.
"""
from __future__ import annotations

import math
from pathlib import Path
import re

FIELDS = ("loa_m", "lpp_m", "beam_m", "depth_m", "draft_m", "scantling_draft_m",
          "displacement_t", "built_year", "builder", "imo")
_MOULDED = r"(?:moulded|molded|mld\.?)"
_DRAFT = r"dra(?:ft|ught)"
# Longer labels precede bare draft so a scantling reading cannot become design draft.
LABELS = {
    "loa_m": r"l\.?\s*o\.?\s*a\.?|length\s+(?:over\s*all|o\.?\s*a\.?)",
    "lpp_m": r"l\.?\s*(?:b\.?\s*p|p\.?\s*p)\.?|length\s+bet(?:ween|w\.?|v\.?)\s+perp(?:endiculars|s|\.)?",
    "beam_m": rf"(?:beam|breadth)(?:\s*\(?{_MOULDED}\)?)?|{_MOULDED}\s+(?:beam|breadth)",
    "depth_m": rf"depth(?:\s*\(?{_MOULDED}\)?)?|{_MOULDED}\s+depth",
    "scantling_draft_m": rf"scantling\s+{_DRAFT}|{_DRAFT}\s*\(?scantling\)?",
    "draft_m": rf"design\s+{_DRAFT}|{_DRAFT}\s*\(?design\)?|{_DRAFT}",
    "displacement_t": r"displacement(?:\s*\(?(?:design|loaded)\)?)?",
    "built_year": r"year\s+(?:of\s+)?build|year\s+built|(?m:^[ \t]*built\s+in)|built(?:\s+year)?",
    "builder": r"builder|built\s+by",
    "imo": r"IMO(?:\s+(?:no\.?|number))?",
}
# A unit is required: unlabelled numbers, frame labels and scale ratios are not dimensions.
_NUMBER = r"(?:\d+(?:[.,]\d+)?|[.,]\d+)"
_FRACTION = r"(?:\d+\s+)?\d+\s*/\s*\d+"
_INCHES = rf"(?:{_FRACTION}|{_NUMBER})"
_LENGTH = re.compile(
    rf"(?P<feet>{_NUMBER})\s*(?:['’′]|ft\b|feet\b)"
    rf"(?:\s*-?\s*(?P<inches>{_INCHES})\s*(?:[\"”″]|in\b))?"
    rf"|(?P<metric>{_NUMBER})\s*\[?\s*(?P<unit>mm|cm|metres?|meters?|m)\b\]?", re.I)
_MASS = re.compile(r"(?P<value>\d+(?:,\d{3})*(?:\.\d+)?|\d+,\d+)\s*\[?\s*(?:metric\s+ton(?:ne)?s?|tonnes?|t)\b\]?", re.I)
_SEPARATOR = r"[\s:=]*"
_PREFIX_LENGTH = re.compile(
    rf"[\[(]\s*(?P<unit>mm|cm|metres?|meters?|m)\s*[\])]"
    rf"{_SEPARATOR}(?P<metric>{_NUMBER})(?![\d.,])", re.I)


def _fraction(text: str) -> float:
    parts = text.split()
    fraction = parts.pop()
    if "/" in fraction:
        top, bottom = fraction.split("/")
        value = float(top) / float(bottom)
    else:
        value = float(fraction)
    return sum(float(part) for part in parts) + value


def _length(match: re.Match) -> float | None:
    feet = match.groupdict().get("feet")
    if feet is not None:
        try:
            inches = _fraction(re.sub(r"\s*/\s*", "/", match["inches"] or "0"))
        except ZeroDivisionError:
            return None
        if inches >= 12:
            return None
        return (float(feet.replace(",", ".")) + inches / 12) * 0.3048
    factor = {"mm": 0.001, "cm": 0.01}.get(match["unit"].lower(), 1.0)
    return float(match["metric"].replace(",", ".")) * factor


def _read(text: str, source: dict, spans: list[tuple[int, int, list]] | None = None) -> list[dict]:
    found = []
    occupied = []
    for field, label in LABELS.items():
        for heading in re.finditer(rf"(?<!\w)(?:{label})(?!\w){_SEPARATOR}", text, re.I):
            if any(start <= heading.start() < end for start, end in occupied):
                continue
            tail = text[heading.end():]
            if field.endswith("_m"):
                value_match = _LENGTH.match(tail) or _PREFIX_LENGTH.match(tail)
                value = _length(value_match) if value_match else None
            elif field == "displacement_t":
                value_match = _MASS.match(tail)
                value = None
                if value_match:
                    number = value_match["value"]
                    # A single comma with fewer than three following digits is decimal.
                    if number.count(",") == 1 and "." not in number and len(number.split(",")[1]) != 3:
                        number = number.replace(",", ".")
                    else:
                        number = number.replace(",", "")
                    value = float(number)
            elif field in ("built_year", "imo"):
                pattern = r"(?:18|19|20)\d{2}(?!\w)" if field == "built_year" else r"[0-9]{7}(?!\w)"
                value_match = re.match(pattern, tail)
                value = value_match.group() if value_match else None
                if value is not None and field == "built_year":
                    value = int(value)
            else:
                # Names end at a new line or semicolon, never consume the next row.
                value_match = re.match(r"[^\n;]+", tail)
                value = value_match.group().strip() if value_match else None
            if value is None or value == "" or isinstance(value, (int, float)) and value <= 0:
                continue
            end = heading.end() + value_match.end()
            occupied.append((heading.start(), end))
            boxes = [box for start, stop, box in spans or [] if start < end and stop > heading.start()]
            bbox = ([min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None)
            found.append({"field": field, "value": value, "status": "read",
                          "source": {**source, "text": text[heading.start():end], "bbox": bbox}})
    return sorted(found, key=lambda item: FIELDS.index(item["field"]))


def read_text(text: str, *, source: dict) -> list[dict]:
    """Read text fixtures or cached text without pretending to know word positions."""
    return _read(text, source)


def read_words(words: list[dict], *, source: dict) -> list[dict]:
    """Read words in source reading order, preserving line breaks and matched boxes."""
    text, spans, previous = "", [], None
    for word in words:
        line = word.get("line")
        if text:
            text += "\n" if line != previous else " "
        start = len(text)
        text += word["text"]
        spans.append((start, len(text), word["bbox"]))
        previous = line
    return _read(text, source, spans)


def pdf_words(path: Path, page_index: int, full_px: list[int]) -> list[dict]:
    """PDF words, including short text layers; boxes mapped to the intake page pixels."""
    import fitz
    with fitz.open(path) as document:
        page = document[page_index]
        sx, sy = full_px[0] / page.rect.width, full_px[1] / page.rect.height
        words = []
        for word in page.get_text("words"):
            # PDF word coordinates are unrotated; intake images include page rotation.
            box = fitz.Rect(word[:4]) * page.rotation_matrix
            words.append({"text": word[4], "line": list(word[5:7]),
                          "bbox": [box.x0 * sx, box.y0 * sy, box.x1 * sx, box.y1 * sy]})
        return words


def _length_precision(reading: dict) -> float:
    """Half the last printed unit in metres, for a rounded dimension."""
    text = reading.get("source", {}).get("text", "")
    match = _LENGTH.search(text) or _PREFIX_LENGTH.search(text)
    if not match:
        return 0.0
    def step(number: str) -> float:
        number = number.replace(",", ".")
        return 10 ** -len(number.split(".", 1)[1]) if "." in number else 1.0
    feet = match.groupdict().get("feet")
    if feet is not None:
        inches = match.groupdict().get("inches")
        if inches:
            if "/" in inches:
                resolution = 1 / float(inches.rsplit("/", 1)[1])
            else:
                resolution = step(inches)
            return resolution * 0.0254 / 2
        return step(feet) * 0.3048 / 2
    factor = {"mm": 0.001, "cm": 0.01}.get(match["unit"].lower(), 1.0)
    return step(match["metric"]) * factor / 2


def resolve(pages: list[dict], typed: dict | None = None) -> dict:
    """Resolve equal readings, retain every source, and leave conflicting fields unset."""
    typed = typed or {}
    grouped: dict[str, list[dict]] = {}
    for page in pages:
        if page.get("skip"):
            continue
        for reading in (page.get("sheet") or {}).get("particulars", []):
            source = {**reading["source"], "sheet": page["page_id"], "file": page.get("file"),
                      "page_index": page.get("page_index", 0)}
            grouped.setdefault(reading["field"], []).append({**reading, "source": source})
    values = {field: value for field, value in typed.items() if value not in (None, "")}
    fields, checks = {}, []
    for field, readings in grouped.items():
        first = readings[0]["value"]
        def equal(reading):
            value = reading["value"]
            if isinstance(first, (int, float)) and isinstance(value, (int, float)):
                # Use the coarser reading's rounding interval, plus floating point noise.
                tolerance = 1e-6
                if field.endswith("_m"):
                    tolerance += max(_length_precision(readings[0]), _length_precision(reading))
                return math.isclose(first, value, rel_tol=0, abs_tol=tolerance)
            return first == value
        conflict = any(not equal(r) for r in readings)
        status = "typed" if field in values else "conflict" if conflict else "read"
        if status == "read":
            values[field] = first
        fields[field] = {"status": status, "value": values.get(field), "readings": readings}
        if conflict:
            checks.append({"code": "particulars_conflict", "field": field, "status": "check",
                           "message": f"The drawings give different values for {field}.", "readings": readings})
    for field, value in values.items():
        fields.setdefault(field, {"status": "typed", "value": value, "readings": []})
    return {"values": values, "fields": fields, "check_items": checks}
