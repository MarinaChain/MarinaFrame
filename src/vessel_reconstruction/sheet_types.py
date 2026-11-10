"""What kind of drawing is this sheet? Code first, a small vision question only when code is unsure.

``type_sheet`` gives ``{type, confidence, source, evidence, alternatives}`` for one sheet. The type is
one of SHEET_TYPES (docs/DRAWING_SET_INTAKE.md). Evidence, in order of trust:

1. text on the sheet: the PDF text layer, else OCR (the ``tesseract`` program, when installed);
2. the file name (many sets are named by their sheet title; it can be switched off);
3. the layout of the page (the intake's view regions).

Each rule is a keyword with a weight. The sheet takes the type with the highest total, and the
confidence follows the total and the margin to the second type. When the confidence is below
``VISION_BELOW`` and a model transport ``ask`` is given, one picture of the page is sent to the model
with one question. The answer is a proposal with ``source`` ``model:...``; the person can edit it.
Nothing here says a type is certain, and nothing is "approved" or "verified".
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

SHEET_TYPES = ("lines_plan", "general_arrangement", "profile", "midship_section", "shell_expansion",
               "construction_profile", "tank_plan", "hydrostatics", "other")
SHEET_TYPE_LABELS = {"lines_plan": "Lines plan", "general_arrangement": "General arrangement",
                     "profile": "Profile", "midship_section": "Midship section",
                     "shell_expansion": "Shell expansion", "construction_profile": "Construction profile and decks",
                     "tank_plan": "Tank or capacity plan", "hydrostatics": "Hydrostatic tables", "other": "Other"}
MODEL = "claude-sonnet-5-5"

# Below this confidence the model is asked (when a transport is given).
VISION_BELOW = 0.7
# A text total below this is too little to name a type.
MIN_TOTAL = 2.0
# Confidence = BASE + PER_TOTAL * total + PER_MARGIN * (total - second total), kept in [FLOOR, CEILING].
CONFIDENCE_BASE = 0.35
CONFIDENCE_PER_TOTAL = 0.08
CONFIDENCE_PER_MARGIN = 0.07
CONFIDENCE_FLOOR = 0.2
# A sheet with no matching rule is 'other' at this confidence (0.1 more when a rule matched but too weakly).
NO_RULE_CONFIDENCE = 0.2
CONFIDENCE_CEILING = 0.95
# One keyword counts at most this many times (a repeated word is not more evidence).
MAX_REPEAT = 2
# Layout hint: a page with a body-plan view and a long view votes for a lines plan with this weight.
LAYOUT_LINES_WEIGHT = 1.0
# OCR reads a copy with this longest side (pixels); the page is not otherwise changed.
OCR_SIDE = 3200
OCR_TIMEOUT_S = 90
# Text from a PDF layer shorter than this is treated as no text layer.
MIN_LAYER_CHARS = 25
# A text layer at least this long is enough; a shorter one is read together with OCR.
LONG_LAYER_CHARS = 400
# OCR words below this confidence (0-100) are noise.
OCR_MIN_CONFIDENCE = 30
# Headings are words at least this many times taller than the median word.
TITLE_HEIGHT_RATIO = 1.8
# Notes and labels count this share of a heading's weight (headings are counted in both).
BODY_SHARE = 0.5
# The picture sent to the model has this longest side.
VISION_SIDE = 1400

# (pattern, weight). Patterns run on lower-case text with hyphens and underscores read as spaces.
RULES: dict[str, list[tuple[str, float]]] = {
    "lines_plan": [
        (r"body\s*plan", 3.5), (r"half\s*breadth", 3.5), (r"sheer\s*plan", 3.5), (r"lines\s*plan", 4.0),
        (r"table\s+of\s+offsets", 3.0), (r"\boffsets\b", 1.5), (r"\blines\b", 1.5), (r"\bbuttocks?\b", 1.0),
        (r"\bwater\s*lines?\b", 0.8), (r"\bstations?\b", 0.8), (r"\bsheer\b", 1.0),
        # The main-particulars block a lines plan carries.
        (r"rise\s+of\s+floor|rake\s+of\s+keel|breadth\s+moulded|moulded\s+breadth", 1.2),
    ],
    "general_arrangement": [
        (r"general\s+arrangement", 4.5), (r"\barrangement\b", 1.5), (r"deck\s+plans?", 2.5),
        (r"\bdecks?\b", 0.8), (r"accommodation", 1.5), (r"plan\s+of\s+hold|hold\s+plan", 2.5),
        (r"forecastle|bridge\s+deck|boat\s+deck|poop\s+deck|wheelhouse", 1.5), (r"\bplans?\b", 0.4),
    ],
    "profile": [
        (r"(outboard|inboard)\s+profile", 3.5), (r"\bprofile\b", 1.2), (r"hog\s+diagram", 2.0),
        (r"\belevation\b", 0.5),
    ],
    "midship_section": [
        (r"mid\s*ship\s+section", 4.5), (r"\bmid\s*ship\b", 2.0), (r"typical\s+section", 3.0),
        (r"sections?\s+(at|aft|fwd|forward|through)", 2.5), (r"looking\s+(aft|forward|fwd)", 1.5),
        (r"\bsections?\b", 1.0), (r"solid\s+floor", 2.0), (r"transverse\s+section", 3.5),
    ],
    "shell_expansion": [
        (r"shell\s+expansion", 5.0), (r"shell\s+plating", 3.5), (r"\bexpansion\b", 2.0),
        (r"\bstrakes?\b", 1.5), (r"plate\s+thickness", 1.0),
    ],
    "construction_profile": [
        (r"(construction|structural)\s+(profile|plan|drawing)", 4.0), (r"\bscantlings?\b", 2.5),
        (r"\bgirders?\b", 1.0), (r"\bpillars?\b", 1.0), (r"\bwelding\b", 1.5), (r"\bstiffeners?\b", 1.2),
        (r"\bfloors?\b", 0.5), (r"profile\s+and\s+plan", 1.5), (r"\bbulkheads?\b", 0.6),
    ],
    "tank_plan": [
        (r"tank\s+(plan|arrangement|schedule|capacity)", 4.5), (r"capacity\s+plan", 4.5), (r"\bcapacity\b", 1.5),
        (r"\bsounding", 2.5), (r"\bullage\b", 2.0), (r"\btanks?\b", 1.2), (r"deep\s+tank", 1.5),
        (r"(fuel|ballast|fresh\s*water|cargo\s+oil|lube|sewage|grey\s*water)\s+(oil\s+)?tank", 1.5),
        (r"\bm3\b|m³|cu\.?\s*ft|\bbbls?\b|barrels", 0.8),
    ],
    "hydrostatics": [
        (r"hydrostatics?\b|hydrostatic\s+(tables?|curves?|data|particulars)", 5.0),
        (r"curves?\s+of\s+form", 4.5), (r"bonjean", 4.5), (r"cross\s+curves", 4.5),
        (r"\b(kmt|kml|lcb|lcf|tpc|mct|mtc|kb)\b", 1.5), (r"\bdisplacement\b", 1.0), (r"trim\s+table", 2.0),
        (r"loading\s+(manual|condition)|stability\s+booklet", 2.5),
    ],
    "other": [
        (r"title\s+sheet", 4.0), (r"index\s+of\s+(drawings|sheets)|drawing\s+(list|index)", 4.0),
        (r"\brigging\b", 3.0), (r"\bengines?\b|machinery|piping|\bwindlass\b|\bcapstan\b|steering\s+gear", 2.5),
        (r"\b(aft|forward)\s+(cabin|deckhouse)|deckhouse", 2.0), (r"axonometric|exploded", 2.0),
        (r"operation\s+\"?pluto|cover\s+sheet|\bnotes\b", 1.0),
    ],
}
_COMPILED = {kind: [(re.compile(pattern), weight) for pattern, weight in rules] for kind, rules in RULES.items()}


def _normal(text: str) -> str:
    return re.sub(r"[\s_\-]+", " ", text.lower())


def keyword_scores(text: str) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Total weight per type for ``text``, and the words that matched."""
    text = _normal(text)
    totals = {kind: 0.0 for kind in SHEET_TYPES}
    words: dict[str, list[str]] = {kind: [] for kind in SHEET_TYPES}
    for kind, rules in _COMPILED.items():
        for pattern, weight in rules:
            found = pattern.findall(text)
            if found:
                match = pattern.search(text)
                totals[kind] += weight * min(len(found), MAX_REPEAT)
                words[kind].append(match.group(0).strip())
    return totals, words


# ------------------------------------------------------------------ text of a sheet
def pdf_text(path: Path, page_index: int) -> str:
    """The text layer of one PDF page ('' when it has none)."""
    import fitz
    with fitz.open(path) as document:
        return document[page_index].get_text() or ""


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_read(gray: np.ndarray, runner=subprocess.run, side: int = OCR_SIDE) -> tuple[str, str]:
    """``(text, title)`` by the ``tesseract`` program: all words, and the words set much larger than the rest.

    ('', '') when it is not installed or fails. Large words are the sheet's headings; small words are
    notes and labels, which name tanks and decks on sheets that are not tank or deck plans.
    """
    if not ocr_available():
        return "", ""
    picture = Image.fromarray(gray)
    scale = side / max(picture.size)
    if scale < 1:
        picture = picture.resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))),
                                 Image.LANCZOS)
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "page.png"
        picture.save(source)
        try:
            done = runner(["tesseract", str(source), "stdout", "--psm", "11", "tsv"], capture_output=True,
                          text=True, timeout=OCR_TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError):
            return "", ""
    if done.returncode != 0:
        return "", ""
    words = []
    for line in done.stdout.splitlines()[1:]:
        fields = line.split("\t")
        if len(fields) == 12 and fields[11].strip() and float(fields[10]) >= OCR_MIN_CONFIDENCE:
            words.append((fields[11].strip(), int(fields[9])))
    if not words:
        return "", ""
    median = float(np.median([height for _, height in words]))
    title = [word for word, height in words if height >= TITLE_HEIGHT_RATIO * median]
    return " ".join(word for word, _ in words), " ".join(title)


def ocr_text(gray: np.ndarray, runner=subprocess.run) -> str:
    return ocr_read(gray, runner)[0]


def sheet_text(path: Path | None, page_index: int, gray: np.ndarray | None, ocr=ocr_read) -> tuple[str, str, str]:
    """``(text, title, where)``: the PDF text layer and OCR of the page.

    A short text layer (a drawing exported with its lettering as outlines keeps only a few words) is
    read together with the OCR. ``ocr`` returns ``(text, title)`` or one string.
    """
    layer = ""
    if path is not None and Path(path).suffix.lower() == ".pdf":
        try:
            layer = pdf_text(Path(path), page_index)
        except Exception:  # a broken text layer is the same as none
            layer = ""
    if len(layer.strip()) >= LONG_LAYER_CHARS or gray is None:
        return (layer, "", "pdf_text") if len(layer.strip()) >= MIN_LAYER_CHARS else ("", "", "none")
    read = ocr(gray)
    text, title = (read, "") if isinstance(read, str) else read
    if layer.strip() and text.strip():
        return layer + "\n" + text, title, "pdf_text+ocr"
    if text.strip():
        return text, title, "ocr"
    return (layer, "", "pdf_text") if len(layer.strip()) >= MIN_LAYER_CHARS else ("", "", "none")


# ------------------------------------------------------------------ the decision
def _confidence(total: float, second: float) -> float:
    value = CONFIDENCE_BASE + CONFIDENCE_PER_TOTAL * total + CONFIDENCE_PER_MARGIN * (total - second)
    return round(min(CONFIDENCE_CEILING, max(CONFIDENCE_FLOOR, value)), 2)


def decide(text: str = "", text_where: str = "none", file_name: str | None = None,
           regions: list[dict] | None = None, title: str = "") -> dict:
    """The code decision from text, file name and layout. Never raises; ``other`` at low confidence when nothing matches."""
    totals = {kind: 0.0 for kind in SHEET_TYPES}
    sources = {kind: set() for kind in SHEET_TYPES}
    evidence: dict[str, list[str]] = {kind: [] for kind in SHEET_TYPES}
    # With headings known, notes and labels count less; a text layer has no heading information.
    body_share = BODY_SHARE if title else 1.0
    for where, content, share in ((f"text:{text_where}", text, body_share), (f"title:{text_where}", title, 1.0),
                                  ("file_name", file_name or "", 1.0)):
        if not content:
            continue
        scores, words = keyword_scores(content)
        for kind in SHEET_TYPES:
            if scores[kind]:
                totals[kind] += scores[kind] * share
                sources[kind].add(where)
                evidence[kind] += [f"{where}: {word}" for word in words[kind][:3]]
    labels = {region.get("label") for region in regions or []}
    if "body_plan" in labels and labels & {"profile", "half_breadth"}:
        totals["lines_plan"] += LAYOUT_LINES_WEIGHT
        sources["lines_plan"].add("layout")
        evidence["lines_plan"].append("layout: body plan view with a long view")
    ranked = sorted(SHEET_TYPES, key=lambda kind: (-totals[kind], SHEET_TYPES.index(kind)))
    best, second = ranked[0], ranked[1]
    if totals[best] < MIN_TOTAL:
        return {"type": "other", "confidence": NO_RULE_CONFIDENCE if not totals[best] else NO_RULE_CONFIDENCE + 0.1,
                "source": "code:no_rule", "evidence": ["no title or keyword rule matched"],
                "alternatives": [{"type": kind, "score": round(totals[kind], 1)} for kind in ranked[:3] if totals[kind]]}
    source = "+".join(sorted(sources[best]))
    return {"type": best, "confidence": _confidence(totals[best], totals[second]),
            "source": source, "evidence": evidence[best][:4],
            "alternatives": [{"type": kind, "score": round(totals[kind], 1)} for kind in ranked[1:3] if totals[kind]]}


# ------------------------------------------------------------------ the vision question
VISION_PROMPT = (
    "This is one sheet of a ship drawing set. Choose the type of the sheet from this list:\n"
    "lines_plan (sheer plan, half-breadth plan, body plan, table of offsets), "
    "general_arrangement (general arrangement, deck plans), profile (outboard or inboard profile), "
    "midship_section (midship or transverse section), shell_expansion (shell plating laid flat), "
    "construction_profile (structural profile, decks, framing, scantlings), "
    "tank_plan (tank or capacity plan, tank schedule), hydrostatics (hydrostatic tables or curves of form), "
    "other (title sheet, rigging, machinery, details, anything else).\n"
    'Answer with JSON only: {"type": "<id>", "confidence": <0 to 1>, "evidence": "<six words>"}.')


def page_png(gray: np.ndarray, side: int = VISION_SIDE) -> bytes:
    picture = Image.fromarray(gray)
    scale = side / max(picture.size)
    if scale < 1:
        picture = picture.resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))),
                                 Image.LANCZOS)
    buffer = io.BytesIO()
    picture.convert("L").save(buffer, format="PNG")
    return buffer.getvalue()


def vision_type(gray: np.ndarray, ask) -> dict | None:
    """One small question to the model; None when it fails or answers outside the list."""
    try:
        answer = ask(VISION_PROMPT, [page_png(gray)])
        match = re.search(r"\{.*\}", answer, flags=re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
    except Exception:  # the transport or the answer failed: keep the code result
        return None
    kind = str(data.get("type", "")).strip()
    if kind not in SHEET_TYPES:
        return None
    try:
        stated = float(data.get("confidence", 0.6))
    except (TypeError, ValueError):
        stated = 0.6
    return {"type": kind, "confidence": round(min(0.9, max(0.3, stated)), 2), "source": f"model:{MODEL}",
            "evidence": [str(data.get("evidence", ""))[:80]]}


def type_sheet(*, path: Path | None = None, page_index: int = 0, gray: np.ndarray | None = None,
               file_name: str | None = None, regions: list[dict] | None = None, text: str | None = None,
               title: str = "", use_file_name: bool = True, ask=None, ocr=ocr_read) -> dict:
    """The type of one sheet. ``text`` overrides reading the page (tests, cached OCR)."""
    where = "given"
    if text is None:
        text, title, where = sheet_text(path, page_index, gray, ocr)
    elif not text:
        where = "none"
    result = decide(text, where, (file_name or (Path(path).name if path else None)) if use_file_name else None,
                    regions, title)
    result["text_source"] = where
    if ask is not None and gray is not None and result["confidence"] < VISION_BELOW:
        answer = vision_type(gray, ask)
        if answer is not None:
            result["code"] = {"type": result["type"], "confidence": result["confidence"], "source": result["source"]}
            result.update(answer)
            result["alternatives"] = [{"type": result["code"]["type"], "score": result["code"]["confidence"]}]
    return result
