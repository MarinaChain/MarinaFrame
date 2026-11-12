"""The fine pass of a commercial GA reading: code finds label text, the model reads it zoomed.

Plan: docs/plans/2026-11-12-ga-commercial.md ("Coarse to fine").

The coarse pass (``ga_commercial``) sends the sheet reduced and in tiles; on a dense scanned
sheet (a tanker GA with diagonal tank labels inside X-shaped outlines) labels are then too
small or at an angle. This pass:

1. finds text blobs by code: glyph-sized connected components of ink, joined into words and
   lines in any direction; the direction of a blob comes from its glyph centres;
2. keeps the blobs that no space of the coarse pass explains, diagonal blobs first;
3. turns each blob level and enlarges it (at most ``MAX_ZOOM``, from the investigation tools)
   into one numbered cell of a contact sheet, at most 1,024 px a side;
4. sends the contact sheets in ``ga_labels`` requests through the Rust controller (Claude only,
   receipted) and adds every label read as a space whose source record is the blob's region.

Counts are then checked again (``ga_commercial.finish_counts``), across views.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from . import source_record
from .investigation import MAX_VIEW_SIDE_PX, MAX_ZOOM
from .provenance import write_json

PURPOSE = "ga_labels"
REQUEST_SCHEMA = "marinaframe.vision_request.v1"
INK_LEVEL = 160
# Glyph size on GA scans (pixels of the sheet): smaller is noise, larger is drawing.
MIN_GLYPH_PX = 5
MAX_GLYPH_PX = 40
# A blob needs this many glyphs to be a label, and is at most this long (longer is a dimension
# string or a row of frame numbers).
MIN_GLYPHS = 3
MAX_BLOB_PX = 700
MAX_GLYPH_ASPECT = 5.0
# Glyph centres of a single text line spread this many times more along it than across it.
LINE_LIKE_RATIO = 12.0
# Text lines run level or diagonal on a GA; a blob steeper than this is a chain of line pieces
# (or rare vertical text) and goes last.
MAX_TEXT_ANGLE_DEG = 60.0
# A crop is at most this long in its cell, so eight cells fit a 1,024 px sheet, unless its
# glyphs would then be smaller than MIN_CELL_GLYPH_PX.
CELL_SIDE_PX = 500
MIN_CELL_GLYPH_PX = 14
# Text is enlarged so that a glyph is about this tall in the cell.
TARGET_GLYPH_PX = 26
# A blob more than this many degrees off level is turned level before the model sees it.
LEVEL_TOLERANCE_DEG = 8.0
# Room around a blob in the crop (sheet pixels) and the red id band above each cell. Labels with
# wide letter spacing ("N O . 3   W . B . T") can split into blobs; the crop reaches beyond the
# blob so the rest of the label is in the cell (review round 1: the last word of a label was read
# alone).
CROP_PAD_PX = 6
# The crop reaches along the text line (the pieces of a letter-spaced label are joined before,
# ``join_collinear``; this room is for a piece that was not) and little across it (a
# neighbouring label is another space).
CROP_PAD_ALONG_GLYPHS = 4.0
CROP_PAD_ACROSS_GLYPHS = 2.0
# Glyphs closer than this many glyph heights join into one blob (letters and words of a label).
JOIN_GAP_GLYPHS = 1.0
# Height of the band kept from a diagonal crop after it is turned level, in glyph heights,
# besides the room across the line: two lines of text and the space between them.
ROTATED_BAND_GLYPHS = 3.5
ID_BAND_PX = 20
# Pieces of one label on one text line join when the gap between them along the line is at
# most this many glyph heights ("NO. 5   W.  B.  TK (P&S)" is drawn with wide gaps; review
# round 2: the number and the tank name were read as two spaces).
JOIN_ALONG_GLYPHS = 5.0
JOIN_ANGLE_DEG = 15.0
JOIN_HEIGHT_RATIO = 1.5
# Crops per request: six contact sheets of up to twelve cells (the controller's limit is 72).
CELLS_PER_IMAGE = 12
IMAGES_PER_REQUEST = 6
# Fine requests per ship: requests go out until every text blob that the coarse pass does not
# explain is read, up to this many (the product setting is ``ga_commercial.MAX_REQUESTS_PER_SHIP``:
# one coarse request and this many fine requests). Crops are packed in priority order; crops
# beyond the ceiling are not read and are counted in ``crops_not_read``.
MAX_FINE_REQUESTS = 5
MAX_IMAGE_BYTES = 1_048_576
MAX_TOTAL_IMAGE_BYTES = 1_400_000


@dataclass(frozen=True)
class Candidate:
    """One text blob on the sheet: its box (sheet pixels), direction and glyph statistics."""
    box: tuple[int, int, int, int]
    angle_deg: float
    glyphs: int
    glyph_height: float


def text_candidates(gray: np.ndarray) -> list[Candidate]:
    """Text blobs of a sheet: glyph-sized ink components joined across letter and word gaps."""
    ink = gray < INK_LEVEL
    labels, count = ndimage.label(ink)
    if count == 0:
        return []
    objects = ndimage.find_objects(labels)
    glyph = np.zeros(count + 1, dtype=bool)
    heights = np.zeros(count + 1)
    for index, window in enumerate(objects, start=1):
        height = window[0].stop - window[0].start
        width = window[1].stop - window[1].start
        # A dash of a broken line is long and thin; a letter is not (an "I" or "1" is at most
        # about 4:1, and a word has several letters).
        if (MIN_GLYPH_PX <= max(height, width) <= MAX_GLYPH_PX and min(height, width) >= 2
                and max(height, width) <= MAX_GLYPH_ASPECT * min(height, width)):
            glyph[index] = True
            heights[index] = max(height, width)
    glyph_mask = glyph[labels]
    if not glyph_mask.any():
        return []
    typical = float(np.median(heights[glyph]))
    # Letters of a word are about half a glyph apart, words about one glyph: close both in any
    # direction (a disk, not a horizontal bar, so diagonal labels join too).
    radius = max(2, int(round(typical * JOIN_GAP_GLYPHS)))
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    blobs, blob_count = ndimage.label(ndimage.binary_dilation(glyph_mask, structure=xx ** 2 + yy ** 2 <= radius ** 2))
    centres = ndimage.center_of_mass(glyph_mask, labels, np.flatnonzero(glyph))
    members: dict[int, list[tuple[float, float, float]]] = {}
    for label_index, (cy, cx) in zip(np.flatnonzero(glyph), centres):
        blob = blobs[int(round(cy)), int(round(cx))]
        if blob:
            members.setdefault(int(blob), []).append((cx, cy, heights[label_index]))
    candidates = []
    for blob, window in enumerate(ndimage.find_objects(blobs), start=1):
        found = members.get(blob, [])
        if window is None or len(found) < MIN_GLYPHS:
            continue
        top, bottom = window[0].start, window[0].stop
        left, right = window[1].start, window[1].stop
        if max(right - left, bottom - top) > MAX_BLOB_PX:
            continue
        points = np.array([(x, y) for x, y, _ in found])
        angle = 0.0
        spread = points - points.mean(axis=0)
        values, vectors = np.linalg.eigh(spread.T @ spread)
        # A line of text: one direction much longer than the other (a cell of furniture symbols
        # beside a level label is not, and must stay level).
        if values[1] > LINE_LIKE_RATIO * max(values[0], 1e-6):
            dx, dy = vectors[:, 1]
            angle = math.degrees(math.atan2(dy, dx))
            angle = (angle + 90) % 180 - 90  # -90..90: reading direction left to right
        candidates.append(Candidate((left, top, right, bottom), round(angle, 1), len(found),
                                    float(np.median([h for _, _, h in found]))))
    return join_collinear(candidates)


def _same_line(a: Candidate, b: Candidate) -> bool:
    """True when two blobs are pieces of one text line with a short gap between them."""
    if max(a.glyph_height, b.glyph_height) > JOIN_HEIGHT_RATIO * min(a.glyph_height, b.glyph_height):
        return False
    ax, ay = (a.box[0] + a.box[2]) / 2, (a.box[1] + a.box[3]) / 2
    bx, by = (b.box[0] + b.box[2]) / 2, (b.box[1] + b.box[3]) / 2
    dx, dy = bx - ax, by - ay
    distance = math.hypot(dx, dy)
    if distance == 0:
        return False
    line = (math.degrees(math.atan2(dy, dx)) + 90) % 180 - 90
    # Both pieces run along the line that joins them.
    for piece in (a, b):
        if abs((piece.angle_deg - line + 90) % 180 - 90) > JOIN_ANGLE_DEG:
            return False
    cos, sin = abs(dx) / distance, abs(dy) / distance

    def half_length(c: Candidate) -> float:
        # The piece is a thin strip along the line; its box projects to about its length.
        return min((c.box[2] - c.box[0]) / max(cos, 1e-6), (c.box[3] - c.box[1]) / max(sin, 1e-6)) / 2

    gap = distance - half_length(a) - half_length(b)
    return gap <= JOIN_ALONG_GLYPHS * max(a.glyph_height, b.glyph_height)


def join_collinear(candidates: list[Candidate]) -> list[Candidate]:
    """Join the pieces of letter-spaced labels: blobs on one text line with short gaps."""
    parent = list(range(len(candidates)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(candidates):
        for j in range(i + 1, len(candidates)):
            if root(i) != root(j) and _same_line(a, candidates[j]):
                parent[root(j)] = root(i)
    groups: dict[int, list[Candidate]] = {}
    for index, candidate in enumerate(candidates):
        groups.setdefault(root(index), []).append(candidate)
    joined = []
    for members in groups.values():
        box = (min(c.box[0] for c in members), min(c.box[1] for c in members),
               max(c.box[2] for c in members), max(c.box[3] for c in members))
        if len(members) == 1 or max(box[2] - box[0], box[3] - box[1]) > MAX_BLOB_PX:
            joined.extend(members)
            continue
        longest = max(members, key=lambda c: c.glyphs)
        joined.append(Candidate(box, longest.angle_deg, sum(c.glyphs for c in members),
                                float(np.median([c.glyph_height for c in members]))))
    return joined


def _covered(box, boxes, margin: float = 10.0) -> bool:
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(b[0] - margin <= x <= b[2] + margin and b[1] - margin <= y <= b[3] + margin for b in boxes)


def unexplained(candidates: list[Candidate], explained_boxes: list[list[float]],
                later_boxes: list[list[float]] = (), limit: int | None = None) -> list[Candidate]:
    """Blobs no coarse space or particular explains: diagonal first, then the longest.

    Blobs inside ``later_boxes`` (accommodation deck plans: cabins and stores) go last, so the
    crop budget reaches tank and hold labels first.
    """
    kept = [c for c in candidates if not _covered(c.box, explained_boxes)]
    def order(c: Candidate):
        steep = abs(c.angle_deg) > MAX_TEXT_ANGLE_DEG
        diagonal = LEVEL_TOLERANCE_DEG < abs(c.angle_deg) <= MAX_TEXT_ANGLE_DEG
        return (_covered(c.box, later_boxes, 0.0), steep, not diagonal, -c.glyphs, c.box[1], c.box[0])
    kept.sort(key=order)
    return kept[:limit]


def crop_box(candidate: Candidate, width: int, height: int) -> tuple[int, int, int, int]:
    """The sheet box of a blob's crop: the blob with room for the rest of its label.

    The room is long along the blob's text direction and short across it; the axis-aligned box
    that holds both is the crop (it is turned level afterwards).
    """
    left, top, right, bottom = candidate.box
    along = CROP_PAD_ALONG_GLYPHS * candidate.glyph_height
    across = CROP_PAD_ACROSS_GLYPHS * candidate.glyph_height
    angle = math.radians(candidate.angle_deg)
    pad_x = CROP_PAD_PX + int(along * abs(math.cos(angle)) + across * abs(math.sin(angle)))
    pad_y = CROP_PAD_PX + int(along * abs(math.sin(angle)) + across * abs(math.cos(angle)))
    return max(0, left - pad_x), max(0, top - pad_y), min(width, right + pad_x), min(height, bottom + pad_y)


def crop_image(sheet: Image.Image, candidate: Candidate) -> Image.Image:
    """The blob turned level and enlarged so a glyph is about ``TARGET_GLYPH_PX`` tall."""
    crop = sheet.crop(crop_box(candidate, sheet.width, sheet.height))
    if LEVEL_TOLERANCE_DEG < abs(candidate.angle_deg) <= MAX_TEXT_ANGLE_DEG:
        crop = crop.rotate(candidate.angle_deg, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
        # The box of a diagonal label holds much paper beside the text line; after the turn the
        # text is a level band through the centre. Keep that band (room for a second line), so
        # more cells fit one contact sheet.
        band = int((2 * CROP_PAD_ACROSS_GLYPHS + ROTATED_BAND_GLYPHS) * candidate.glyph_height) + 2 * CROP_PAD_PX
        if crop.height > band:
            top = (crop.height - band) // 2
            crop = crop.crop((0, top, crop.width, top + band))
    zoom = min(MAX_ZOOM, max(1.0, TARGET_GLYPH_PX / max(candidate.glyph_height, 1.0)))
    cell_limit = max(CELL_SIDE_PX, MIN_CELL_GLYPH_PX / max(candidate.glyph_height, 1.0) * max(crop.size))
    zoom = min(zoom, min(cell_limit, MAX_VIEW_SIDE_PX - 8) / max(crop.size))
    size = (max(1, round(crop.width * zoom)), max(1, round(crop.height * zoom)))
    return crop.resize(size, Image.Resampling.LANCZOS) if size != crop.size else crop


def contact_sheets(crops: list[tuple[str, Image.Image]]) -> list[tuple[Image.Image, list[dict]]]:
    """Pack (crop_id, image) cells into sheets of at most 1,024 px a side; a red id above each."""
    sheets, cells, x, y, row_height, width = [], [], 0, 0, 0, 0
    canvas_cells: list[tuple[str, Image.Image, int, int]] = []

    def flush():
        nonlocal canvas_cells, cells, x, y, row_height, width
        if not canvas_cells:
            return
        height = y + row_height
        canvas = Image.new("RGB", (max(width, 1), max(height, 1)), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        for crop_id, image, cx, cy in canvas_cells:
            draw.text((cx + 2, cy + 3), crop_id, fill=(220, 0, 0))
            canvas.paste(image.convert("RGB"), (cx, cy + ID_BAND_PX))
            draw.rectangle([cx, cy + ID_BAND_PX, cx + image.width - 1, cy + ID_BAND_PX + image.height - 1],
                           outline=(220, 0, 0))
        sheets.append((canvas, cells))
        canvas_cells, cells, x, y, row_height, width = [], [], 0, 0, 0, 0

    for crop_id, image in crops:
        cell_w, cell_h = image.width + 8, image.height + ID_BAND_PX + 8
        if x + cell_w > MAX_VIEW_SIDE_PX:
            x, y, row_height = 0, y + row_height, 0
        if y + cell_h > MAX_VIEW_SIDE_PX or len(cells) == CELLS_PER_IMAGE:
            flush()
        canvas_cells.append((crop_id, image, x, y))
        cells.append({"crop_id": crop_id, "cell": [x, y, x + image.width, y + ID_BAND_PX + image.height]})
        x += cell_w
        row_height = max(row_height, cell_h)
        width = max(width, x)
    flush()
    return sheets


def _write_request(directory: Path, pages: list, by_id: dict, sheet: Image.Image, source_sha: str) -> list[dict]:
    """One ``ga_labels`` request directory from contact sheets; returns its crop-map rows."""
    directory.mkdir(parents=True, exist_ok=False)
    images, listing, rows = [], [], []
    for page_index, (canvas, cells) in enumerate(pages):
        image_id = f"p{page_index + 1}"
        buffer = BytesIO()
        canvas.quantize(colors=32).save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()
        (directory / f"{image_id}.png").write_bytes(data)
        images.append({"image_id": image_id, "file": f"{image_id}.png", "sha256": hashlib.sha256(data).hexdigest(),
                       "bytes": len(data), "width": canvas.width, "height": canvas.height,
                       "view": "label_crops", "crop_box_px": [0, 0, canvas.width, canvas.height]})
        for cell in cells:
            listing.append({"crop_id": cell["crop_id"], "image_id": image_id, "cell": cell["cell"]})
            candidate = by_id[cell["crop_id"]]
            rows.append({"crop_id": cell["crop_id"], "request": directory.name, "image_id": image_id,
                         "box_px": list(crop_box(candidate, sheet.width, sheet.height)),
                         "blob_px": list(candidate.box), "angle_deg": candidate.angle_deg,
                         "glyphs": candidate.glyphs})
    if sum(i["bytes"] for i in images) > MAX_TOTAL_IMAGE_BYTES:
        raise ValueError("label crops exceed the provider request size")
    write_json(directory / "request.json", {
        "schema_version": REQUEST_SCHEMA, "purpose": PURPOSE, "source_sha256": source_sha,
        "engineering_approved": False, "context": {"crops": listing}, "images": images})
    return rows


def prepare(sheet_path: Path, candidates: list[Candidate], out: Path,
            max_requests: int = MAX_FINE_REQUESTS, call=None, first_crop: int = 1) -> tuple[list[dict], list[dict]]:
    """Write (and with ``call`` send) the ``ga_labels`` requests; return (crop map, readings).

    Crops go out in priority order, one request after the other, up to ``max_requests``. A crop
    that a reply leaves out is asked once more in a later request while the budget lasts
    (a reply sometimes answers only the first cells). The crop map (host side only) has one
    row per crop sent, with the last request that showed it.
    """
    sheet = Image.open(sheet_path).convert("L")
    by_id = {f"c{index + first_crop:02d}": c for index, c in enumerate(candidates)}
    images = {crop_id: crop_image(sheet, c) for crop_id, c in by_id.items()}
    source_sha = hashlib.sha256(Path(sheet_path).read_bytes()).hexdigest()
    pending, asked_again = list(by_id), set()
    rows: dict[str, dict] = {}
    readings = []
    while pending and len(readings) < max_requests:
        pages = contact_sheets([(crop_id, images[crop_id]) for crop_id in pending])[:IMAGES_PER_REQUEST]
        directory = Path(out) / f"labels-{len(readings) + 1}"
        sent = _write_request(directory, pages, by_id, sheet, source_sha)
        rows.update({row["crop_id"]: row for row in sent})
        pending = pending[len(sent):]
        reading = call(directory, Path(out) / f"{directory.name}-provider") if call else {}
        readings.append(reading)
        if call:
            answered = {crop["crop_id"] for crop in ((reading.get("reply") or {}).get(PURPOSE) or {}).get("crops", [])}
            again = [row["crop_id"] for row in sent if row["crop_id"] not in answered | asked_again]
            asked_again.update(again)
            pending += again
    return list(rows.values()), readings


# Words a label must contain before a fine-pass reading of it counts as a counted kind. A cell
# read without context can name a cut label wrongly (review round 1: a cut hold label typed as a
# cargo tank on a bulk carrier); a label that does not say what it is goes to the other kinds.
KIND_WORDS = {
    "cargo_hold": r"\bHOLD\b",
    "cargo_hatch": r"\bHATCH\b|\bH\.?\s?C\b",
    # A hose-handling, provision or engine-room crane is a crane but not a cargo crane.
    "cargo_crane": r"^(?!.*\b(?:HOSE|PROV|PROVISION|STORE|STORES|ENGINE|E/R|DAVIT|MISC|HOIST)\b).*\bCRANE\b",
    "cargo_tank": r"C\.?\s?O\.?\s?T|C\.?\s?T\b|CARGO\s+(?:OIL\s+)?T(?:AN)?K|\bCOT\b",
    "slop_tank": r"\bSLOP\b",
}


def joined_letters(text: str) -> str:
    """Letter-spaced words joined: 'NO.9 H O L D' -> 'NO.9 HOLD' (GA titles are often spaced)."""
    return re.sub(r"\b([A-Z])\s(?=[A-Z]\b)", r"\1", text)


def checked_kind(kind: str, text: str) -> str:
    """The kind of a label after the text check above (counted kinds must say what they are)."""
    pattern = KIND_WORDS.get(kind)
    if pattern is None or re.search(pattern, joined_letters(text.upper())):
        return kind
    return "other_tank" if kind.endswith("_tank") else "other_space"


# A label whose text names its kind gets that kind when the model gave a general one (review
# round 2: "NO.4 C.T.(P)" came back as other_tank, "NO.9 H O L D" as other_space). A numbered
# hold or cargo tank needs its number in the label; a hatch is never promoted (an access hatch
# is not a cargo hatch).
PROMOTIONS = [
    ("slop_tank", ("other_tank",), r"\bSLOP\b"),
    ("cargo_tank", ("other_tank",), r"^(?:NO\.?\s*)?\d+\s*(?:C\.\s?O\.\s?T|C\.\s?T|COT|CARGO\s+(?:OIL\s+)?T(?:AN)?K)\b"),
    ("cargo_hold", ("other_space",), r"^(?:NO\.?\s*)?\d+\s*[A-Z]?\s*(?:CARGO\s+)?HOLD\b"),
    ("ballast_tank", ("other_tank", "other_space"),
     r"W\.?\s?B\.?\s?T|B\.?\s?W\.?\s?T|\bBALLAST\b|\b[AF]\.\s?P\.\s?T\b|\bPEAK\s+T(?:AN)?K"),
    ("fuel_tank", ("other_tank",), r"\bF\.\s?O\.\s?T|\bH\.?\s?F\.?\s?O\b|\bD\.\s?O\.\s?T|\bM\.?\s?[DG]\.?\s?O\b|\bFUEL\s+OIL\b"),
]


def promoted_kind(kind: str, text: str) -> str:
    """The kind that the label's own words name, when the model gave a general kind."""
    upper = joined_letters(text.upper())
    for target, sources, pattern in PROMOTIONS:
        if kind in sources and re.search(pattern, upper):
            return target
    return kind


def label_kind(kind: str, text: str, definitions: dict) -> str:
    """The kind of a read label after the text checks, the promotions and the counting definitions."""
    kind = promoted_kind(checked_kind(kind, text), text)
    if (kind == "slop_tank" and not definitions["slop_holding_tank_is_slop"]
            and re.search(r"\bHOLDING\b", joined_letters(text.upper()))):
        return "other_tank"
    return kind


def label_family(text: str) -> str:
    """The words of a label without its number and side: 'NO. 3 T. S. W. B. T. (P/S)' -> 'TSWBT'.

    Tanks of different families share numbers in one view (NO.3 T.S.W.B.T. above a hold, NO.3
    W.B.T. below it); a label is the same space as another only when its family is the same.
    """
    upper = joined_letters(text.upper())
    upper = re.sub(r"\(\s*(?:P\s*[&/,]\s*S|P|S|C)\s*\)", " ", upper)  # side marks
    upper = re.sub(r"\bNO\b\.?", " ", upper)
    return re.sub(r"[^A-Z]", "", upper)


def merge(result: dict, crop_map: list[dict], readings: list[dict], sheet_name: str, page_px) -> dict:
    """Add the labels read to the spaces; return the per-ship fine-pass statistics."""
    from .ga_commercial import DEFINITIONS, add_space, finish_counts
    definitions = result.get("definitions") or DEFINITIONS
    answers = {}
    for reading in readings:
        for crop in ((reading.get("reply") or {}).get(PURPOSE) or {}).get("crops", []):
            answers[crop["crop_id"]] = crop
    added = 0
    known = {(s["kind"], s["view_id"], s["number"], label_family(s["label"])) for s in result["spaces"] if s["number"]}
    for crop in crop_map:
        answer = answers.get(crop["crop_id"])
        if answer is None:
            result["checks"].append({"code": "label_crop_unanswered", "status": "check", "label": crop["crop_id"]})
            continue
        # Every label of a cell has the cell's sheet region as its source (a dense cell holds several).
        region = source_record.region(sheet_name, view=None, box_px=crop["box_px"], page_px=page_px)
        if region["box_px"] is None:
            continue
        for index, label in enumerate(answer["labels"]):
            kind = label_kind(label["kind"], label["text"], definitions)
            if kind in ("cargo_hold", "cargo_tank") and not re.search(r"\d", label["text"]):
                # A crop that shows only "HOLD" or "C.O.TK" is a piece of a numbered label.
                kind = "other_tank" if kind.endswith("_tank") else "other_space"
            if kind != label["kind"]:
                result["checks"].append({"code": "fine_kind_not_in_text", "status": "changed",
                                         "label": label["text"][:64], "kind": label["kind"]})
            space = add_space(result, f"{kind}-{crop['crop_id']}-{index + 1}", kind,
                              label["text"], label["number"], "read", region, "fine")
            key = (space["kind"], space["view_id"], space["number"], label_family(space["label"]))
            if space["number"] and key in known:
                # The coarse pass already listed this numbered space of this family in this view.
                result["spaces"].remove(space)
                continue
            known.add(key)
            added += 1
    finish_counts(result)
    return {"crops": len(crop_map), "answered": sum(c["crop_id"] in answers for c in crop_map),
            "spaces_added": added, "requests": len(readings)}


# A dropped label whose reason says it was cut may be read whole from a wider crop.
CUT_REASONS = ("the label is cut", "unclosed parenthesis", "start of a longer word", "single letter",
               "the end of the label", "a part of the label")
# The wider crop: the label's blob with this many glyph heights more on every side.
REREAD_PAD_GLYPHS = 6.0
# Crop ids are "c" and at most three digits (the ga_labels contract).
MAX_CROP_NUMBER = 999


def reread_cut_labels(result: dict, dropped: list[tuple[dict, str]], sheet_path: Path, out: Path, call,
                      max_requests: int, fine_crops: list[dict]) -> dict:
    """Read the labels dropped as cut once more from wider crops, within the requests left.

    ``dropped`` is (space, reason) from ``drop_fragments``; ``fine_crops`` the crop map of the
    fine pass (a fine-pass label keeps its blob's direction and size). New labels join the
    spaces as in the fine pass; the caller drops fragments again.
    """
    stats = {"cut_labels": 0, "crops": 0, "requests": 0, "spaces_added": 0}
    rows = {row["crop_id"]: row for row in fine_crops}
    candidates, seen = [], set()
    for space, reason in dropped:
        if not any(words in reason for words in CUT_REASONS):
            continue
        stats["cut_labels"] += 1
        match = re.search(r"-(c\d+)-\d+$", space["id"])
        row = rows.get(match[1]) if match else None
        if row:
            left, top, right, bottom = row["blob_px"]
            angle, glyphs = row["angle_deg"], row["glyphs"]
        else:
            box = (space["source_record"].get("regions") or [{}])[0].get("box_px")
            if not box:
                continue
            left, top, right, bottom = box
            angle, glyphs = 0.0, 3
        # The glyph height: the short side of a level blob; a diagonal blob's short side holds
        # more than one glyph height, so half of it.
        short_side = min(right - left, bottom - top)
        glyph = max(MIN_GLYPH_PX, short_side if abs(angle) <= LEVEL_TOLERANCE_DEG else short_side / 2)
        key = (round(left), round(top), round(right), round(bottom))
        if key in seen:
            continue
        seen.add(key)
        pad = REREAD_PAD_GLYPHS * glyph
        candidates.append(Candidate(box=(int(left - pad), int(top - pad), int(right + pad), int(bottom + pad)),
                                    angle_deg=angle, glyphs=glyphs, glyph_height=float(glyph)))
    first = 1 + max([int(row["crop_id"][1:]) for row in fine_crops] or [0])
    candidates = candidates[:max(0, MAX_CROP_NUMBER - first + 1)]
    if not candidates or max_requests < 1:
        return stats
    sheet = Image.open(sheet_path)
    candidates = [Candidate(box=(max(0, c.box[0]), max(0, c.box[1]), min(sheet.width, c.box[2]),
                                 min(sheet.height, c.box[3])), angle_deg=c.angle_deg, glyphs=c.glyphs,
                            glyph_height=c.glyph_height) for c in candidates]
    crop_map, readings = prepare(sheet_path, candidates, out, max_requests, call, first_crop=first)
    write_json(Path(out) / "crops.json", {"crops": crop_map})
    merged = merge(result, crop_map, readings, Path(sheet_path).name, [sheet.width, sheet.height])
    stats.update(crops=len(crop_map), requests=len(readings), spaces_added=merged.get("spaces_added", 0))
    return stats


def fine_pass(result: dict, sheet_path: Path, out: Path, call, max_requests: int = MAX_FINE_REQUESTS) -> dict:
    """Run the fine pass for one ship. ``call(request_dir, out_dir)`` sends one request.

    Requests go out until every unexplained text blob is read, at most ``max_requests``.
    """
    gray = np.asarray(Image.open(sheet_path).convert("L"))
    explained = [s["source_record"]["regions"][0]["box_px"] for s in result["spaces"]
                 if s["source_record"]["kind"] == "read"]
    explained += [s["source_record"]["inputs"][0]["box_px"] for s in result["spaces"]
                  if s["source_record"]["kind"] == "guessed" and s["source_record"]["inputs"][0].get("box_px")]
    explained += [p["source_record"]["regions"][0]["box_px"] for p in result["particulars"].values()
                  if p.get("source_record", {}).get("kind") == "read"]
    all_candidates = text_candidates(gray)
    accommodation = [v["box_px"] for v in result.get("views", []) if v["kind"] == "accommodation_plan"]
    chosen = unexplained(all_candidates, explained, accommodation)
    stats = {"text_blobs": len(all_candidates), "crops": 0, "answered": 0, "spaces_added": 0, "requests": 0}
    if not chosen or max_requests < 1:
        stats["crops_not_read"] = len(chosen)
        return stats
    crop_map, readings = prepare(sheet_path, chosen, out, max_requests, call)
    write_json(Path(out) / "crops.json", {"crops": crop_map})
    stats.update(merge(result, crop_map, readings, Path(sheet_path).name, list(gray.shape[::-1])))
    stats["text_blobs"] = len(all_candidates)
    # Chosen blobs left out because they did not fit the fine requests of the budget.
    stats["crops_not_read"] = len(chosen) - len(crop_map)
    return stats
