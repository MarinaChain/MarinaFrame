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
# The crop reaches far along the text line (a long letter-spaced tank label still split into
# blobs in review round 2) and little across it (a neighbouring label is another space).
CROP_PAD_ALONG_GLYPHS = 8.0
CROP_PAD_ACROSS_GLYPHS = 2.0
# Glyphs closer than this many glyph heights join into one blob (letters and words of a label).
JOIN_GAP_GLYPHS = 1.0
ID_BAND_PX = 20
# Bounds per ship: crops read in the fine pass and requests sent for them.
MAX_CANDIDATES = 48
CELLS_PER_IMAGE = 8
IMAGES_PER_REQUEST = 6
# Fine requests per ship (the protocol budget is one coarse and at most two fine requests).
# Crops are packed in priority order; crops that do not fit these sheets are not read.
MAX_FINE_REQUESTS = 2
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
    return candidates


def _covered(box, boxes, margin: float = 10.0) -> bool:
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(b[0] - margin <= x <= b[2] + margin and b[1] - margin <= y <= b[3] + margin for b in boxes)


def unexplained(candidates: list[Candidate], explained_boxes: list[list[float]],
                later_boxes: list[list[float]] = ()) -> list[Candidate]:
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
    return kept[:MAX_CANDIDATES]


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


def prepare(sheet_path: Path, candidates: list[Candidate], out: Path) -> list[dict]:
    """Write the ``ga_labels`` request directories; return the crop map (host side only)."""
    sheet = Image.open(sheet_path).convert("L")
    crops = [(f"c{index + 1:02d}", crop_image(sheet, c)) for index, c in enumerate(candidates)]
    pages = contact_sheets(crops)[:MAX_FINE_REQUESTS * IMAGES_PER_REQUEST]
    crop_map = []
    by_id = {f"c{index + 1:02d}": c for index, c in enumerate(candidates)}
    source_sha = hashlib.sha256(Path(sheet_path).read_bytes()).hexdigest()
    for request_index in range(math.ceil(len(pages) / IMAGES_PER_REQUEST)):
        directory = Path(out) / f"labels-{request_index + 1}"
        directory.mkdir(parents=True, exist_ok=False)
        images, listing = [], []
        for page_index, (canvas, cells) in enumerate(pages[request_index * IMAGES_PER_REQUEST:
                                                          (request_index + 1) * IMAGES_PER_REQUEST]):
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
                crop_map.append({"crop_id": cell["crop_id"], "request": directory.name, "image_id": image_id,
                                 "box_px": list(crop_box(candidate, sheet.width, sheet.height)),
                                 "blob_px": list(candidate.box), "angle_deg": candidate.angle_deg,
                                 "glyphs": candidate.glyphs})
        if sum(i["bytes"] for i in images) > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError("label crops exceed the provider request size")
        write_json(directory / "request.json", {
            "schema_version": REQUEST_SCHEMA, "purpose": PURPOSE, "source_sha256": source_sha,
            "engineering_approved": False, "context": {"crops": listing}, "images": images})
    return crop_map


# Words a label must contain before a fine-pass reading of it counts as a counted kind. A cell
# read without context can name a cut label wrongly (review round 1: a cut hold label typed as a
# cargo tank on a bulk carrier); a label that does not say what it is goes to the other kinds.
KIND_WORDS = {
    "cargo_hold": r"\bHOLD\b",
    "cargo_hatch": r"\bHATCH\b|\bH\.?\s?C\b",
    # A hose-handling, provision or engine-room crane is a crane but not a cargo crane.
    "cargo_crane": r"^(?!.*\b(?:HOSE|PROV|PROVISION|STORE|STORES|ENGINE|E/R|DAVIT|MISC)\b).*\bCRANE\b",
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


def merge(result: dict, crop_map: list[dict], readings: list[dict], sheet_name: str, page_px) -> dict:
    """Add the labels read to the spaces; return the per-ship fine-pass statistics."""
    from .ga_commercial import add_space, finish_counts
    answers = {}
    for reading in readings:
        for crop in ((reading.get("reply") or {}).get(PURPOSE) or {}).get("crops", []):
            answers[crop["crop_id"]] = crop
    added = 0
    known = {(s["kind"], s["view_id"], s["number"]) for s in result["spaces"] if s["number"]}
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
            kind = checked_kind(label["kind"], label["text"])
            if kind != label["kind"]:
                result["checks"].append({"code": "fine_kind_not_in_text", "status": "changed",
                                         "label": label["text"][:64], "kind": label["kind"]})
            space = add_space(result, f"{kind}-{crop['crop_id']}-{index + 1}", kind,
                              label["text"], label["number"], "read", region, "fine")
            key = (space["kind"], space["view_id"], space["number"])
            if space["number"] and key in known:
                # The coarse pass already listed this numbered space in this view.
                result["spaces"].remove(space)
                continue
            known.add(key)
            added += 1
    finish_counts(result)
    return {"crops": len(crop_map), "answered": sum(c["crop_id"] in answers for c in crop_map),
            "spaces_added": added, "requests": len(readings)}


def fine_pass(result: dict, sheet_path: Path, out: Path, call) -> dict:
    """Run the fine pass for one ship. ``call(request_dir, out_dir)`` sends one request."""
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
    if not chosen:
        return stats
    crop_map = prepare(sheet_path, chosen, out)
    write_json(Path(out) / "crops.json", {"crops": crop_map})
    readings = [call(Path(out) / name, Path(out) / f"{name}-provider")
                for name in sorted({c["request"] for c in crop_map})]
    stats.update(merge(result, crop_map, readings, Path(sheet_path).name, list(gray.shape[::-1])))
    stats["text_blobs"] = len(all_candidates)
    # Chosen blobs left out because they did not fit the fine requests of the budget.
    stats["crops_not_read"] = len(chosen) - len(crop_map)
    return stats
