"""Read a commercial ship's general arrangement (GA): particulars, counts and spaces.

Plan and protocol: docs/plans/2026-11-12-ga-commercial.md.

Division of work:

- Code prepares the images (a reduced whole sheet plus higher-resolution tiles,
  within the provider's 2,048 px / 1 Mpx image limit), maps every model box
  back to sheet pixels, checks that each box holds ink, parses printed
  particulars with their units (``particulars._LENGTH``), refuses implausible
  or ambiguous values, checks counts against the labelled items, and writes a
  ``source-record/v1`` record for every value and space.
- The model (Claude Sonnet 5.5 through the Claude subscription, purpose
  ``ga_reading`` of ``marinaframe vision-request``) reads the labels and
  judges what each drawn space is. Every request is receipted by the Rust
  controller. This module never contacts a provider itself.

Every value is ``read``, ``guessed`` or ``unknown`` (null). Nothing is
approved; ``engineering_approved`` is always false.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
from PIL import Image

from . import source_record
from .particulars import _LENGTH, _PREFIX_LENGTH, _length
from .provenance import write_json

SCHEMA = "marinaframe.ga_reading.v1"
REQUEST_SCHEMA = "marinaframe.vision_request.v1"
PURPOSE = "ga_reading"
MODEL = "claude-sonnet-5-5"
# Provider limits (rust-control/src/provider.rs check_png and vision.rs).
MAX_SIDE_PX = 2048
MAX_PIXELS = 1_048_576
MAX_IMAGE_BYTES = 1_048_576
MAX_IMAGES = 6
# The provider refuses a request body above 2 MiB (provider.rs); images travel
# as base64 (4/3 of their bytes), so all images together stay below this.
MAX_TOTAL_IMAGE_BYTES = 1_400_000
# When the images are too large together, they are sent with this many grey
# levels (line drawings keep their text) and then at smaller scales.
REDUCED_GREY_LEVELS = 16
# Neighbouring tiles share this fraction of the tile size, so a label cut by
# one tile edge is whole in the other tile. A hold label on the dev sheets is
# up to about 7 % of the sheet width; on a five-strip tiling 15 % of a strip
# covers it with margin.
TILE_OVERLAP = 0.15
# Rounding of tile edges to whole pixels can add a pixel row or column.
SCALE_MARGIN = 0.99
# A box with less ink than this share of its pixels lies on blank paper.
MIN_INK_SHARE = 0.002
INK_LEVEL = 160

LENGTH_FIELDS = {"loa": "loa_m", "lbp": "lbp_m", "breadth": "breadth_m", "depth": "depth_m",
                 "draft": "draft_m", "scantling_draft": "scantling_draft_m"}
# Plausible ranges of commercial ships. A printed value outside its range is
# a misreading or a unit the parser did not understand, so it is not used.
PLAUSIBLE = {"loa_m": (20.0, 500.0), "lbp_m": (20.0, 500.0), "breadth_m": (4.0, 80.0),
             "depth_m": (2.0, 50.0), "draft_m": (1.0, 35.0), "scantling_draft_m": (1.0, 35.0),
             "deadweight_t": (100.0, 600_000.0)}
COUNT_KINDS = {"cargo_holds": "cargo_hold", "cargo_hatches": "cargo_hatch", "cargo_cranes": "cargo_crane",
               "cargo_tanks": "cargo_tank", "slop_tanks": "slop_tank", "container_bays": "container_bay"}
# Requests for one ship in a reading (the product setting; ``--max-requests-per-ship``): one
# coarse request, then fine requests until every unexplained text blob is read, up to this total.
MAX_REQUESTS_PER_SHIP = 6

# Counting definitions (decided by the PM, 2026-11-12). Each is a setting with the default
# below; the sentences go to the model in the request context and code counts by the same rule.
DEFINITIONS = {
    # Holds numbered with halves (No.4A, No.4F) are two holds when a transverse bulkhead
    # separates them and each has its own main hatch. False: one hold per number.
    "split_holds_are_separate": True,
    # A tank whose label says SLOP is a slop tank, also a centreline "slop holding tank".
    # False: a slop holding tank is not counted.
    "slop_holding_tank_is_slop": True,
}


def definition_sentences(definitions: dict) -> list[str]:
    """The counting rules of a run as sentences for the model."""
    holds = ("A cargo hold is a cargo space that transverse bulkheads separate from the next one and that has its "
             "own main hatch. ")
    if definitions["split_holds_are_separate"]:
        holds += ("Holds labelled as halves of one number (No.4A, No.4F) are two holds when a transverse bulkhead "
                  "separates them and each has its own main hatch; they are one hold when they are one space with "
                  "one label or one hatch.")
    else:
        holds += "Holds labelled as halves of one number (No.4A, No.4F) count as one hold."
    slop = "A slop tank is a tank whose printed label says SLOP (SLOP TK, SLOP TANK"
    if definitions["slop_holding_tank_is_slop"]:
        slop += ", SLOP HOLDING TK, also on the centreline)."
    else:
        slop += "); a slop holding tank is not counted."
    slop += " Residue, waste-oil, sludge and other tanks are not slop tanks."
    return [holds,
            "On a bulk carrier the cargo holds and the main cargo hatches are usually equal in number; when your "
            "two counts differ, look again at both before you answer.",
            slop]


# ------------------------------------------------------------------ images

@dataclass(frozen=True)
class Tile:
    """One attached image: the sheet region it shows and its scale."""
    image_id: str
    view: str
    sheet: str
    crop_box_px: tuple[int, int, int, int]
    width: int
    height: int


def _fit_scale(width: float, height: float) -> float:
    """Largest scale (at most 1) that keeps an image inside the provider limits."""
    return min(1.0, MAX_SIDE_PX / max(width, height), math.sqrt(MAX_PIXELS / (width * height)))


def tile_grid(width: int, height: int, max_tiles: int) -> tuple[int, int, float]:
    """Columns, rows and scale of the tiling that shows the sheet at the highest scale."""
    best = (1, 1, _fit_scale(width, height))
    for columns in range(1, max_tiles + 1):
        for rows in range(1, max_tiles // columns + 1):
            tile_w = width / columns * (1 + TILE_OVERLAP * (columns > 1))
            tile_h = height / rows * (1 + TILE_OVERLAP * (rows > 1))
            scale = _fit_scale(tile_w, tile_h) * SCALE_MARGIN
            # Prefer fewer tiles unless more tiles give clearly more detail.
            if scale > best[2] * 1.05:
                best = (columns, rows, scale)
    return best


def tile_boxes(width: int, height: int, columns: int, rows: int) -> list[tuple[int, int, int, int]]:
    """Overlapping crop boxes [left, top, right, bottom] in sheet pixels."""
    boxes = []
    for row in range(rows):
        for column in range(columns):
            pad_x = width / columns * TILE_OVERLAP / 2 if columns > 1 else 0
            pad_y = height / rows * TILE_OVERLAP / 2 if rows > 1 else 0
            left = max(0, math.floor(width * column / columns - pad_x))
            right = min(width, math.ceil(width * (column + 1) / columns + pad_x))
            top = max(0, math.floor(height * row / rows - pad_y))
            bottom = min(height, math.ceil(height * (row + 1) / rows + pad_y))
            boxes.append((left, top, right, bottom))
    return boxes


def _png(image: Image.Image, scale: float, grey_levels: int | None = None) -> tuple[bytes, int, int]:
    """Deterministic grayscale PNG at ``scale``, reduced further only to meet the byte limit."""
    while True:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        scaled = image.resize(size, Image.Resampling.LANCZOS) if size != image.size else image
        if grey_levels:
            step = 256 // grey_levels
            scaled = scaled.point(lambda v: min(255, (v // step) * step + step // 2))
        buffer = BytesIO()
        scaled.save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()
        if len(data) <= MAX_IMAGE_BYTES and size[0] * size[1] <= MAX_PIXELS and max(size) <= MAX_SIDE_PX:
            return data, size[0], size[1]
        scale *= 0.9


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plan_images(ga: Path | None, particulars: Path | None) -> list[tuple[str, str, Path, tuple, float]]:
    """(image_id, view, source file, crop box, scale) of every image of a request.

    With a GA: the reduced whole sheet, then tiles, then the particulars table.
    Without a GA (a particulars table only): the table, tiled when it is large.
    """
    primary = Path(ga or particulars)
    width, height = Image.open(primary).size
    view = "sheet_overview" if ga else "particulars_table"
    slots = MAX_IMAGES - (1 if ga and particulars else 0)
    columns, rows, scale = tile_grid(width, height, slots - 1)
    plan = [("sheet", view, primary, (0, 0, width, height),
             scale if columns * rows == 1 else _fit_scale(width, height))]
    if columns * rows > 1:
        tile_view = "tile" if ga else "particulars_table"
        for index, box in enumerate(tile_boxes(width, height, columns, rows)):
            name = f"{tile_view}:r{index // columns + 1}c{index % columns + 1}" if ga else tile_view
            plan.append((f"t{index + 1}", name, primary, box, scale))
    if ga and particulars:
        table_size = Image.open(particulars).size
        plan.append(("table", "particulars_table", Path(particulars), (0, 0, *table_size), _fit_scale(*table_size)))
    return plan


def prepare(ga: Path | None, out: Path, particulars: Path | None = None, definitions: dict | None = None) -> dict:
    """Write one ``ga_reading`` request directory (request.json and PNG images)."""
    if ga is None and particulars is None:
        raise ValueError("a GA or a particulars table image is required")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    plan = _plan_images(ga, particulars)
    opened = {path: Image.open(path).convert("L") for path in {item[2] for item in plan}}
    # Fit all images into the request size: full grey levels first, then fewer
    # grey levels, then smaller scales.
    for grey_levels, shrink in [(None, 1.0), (REDUCED_GREY_LEVELS, 1.0), *[(REDUCED_GREY_LEVELS, 0.9 ** k)
                                                                         for k in range(1, 12)]]:
        encoded = [_png(opened[path].crop(box), scale * shrink, grey_levels) for _, _, path, box, scale in plan]
        if sum(len(data) for data, _, _ in encoded) <= MAX_TOTAL_IMAGE_BYTES:
            break
    else:
        raise ValueError("the images do not fit the provider request size")
    entries, tiles = [], []
    for (image_id, view, path, box, _), (data, w, h) in zip(plan, encoded):
        name = f"{image_id}.png"
        (out / name).write_bytes(data)
        entries.append({"image_id": image_id, "file": name, "sha256": _sha256(data), "bytes": len(data),
                        "width": w, "height": h, "view": view, "crop_box_px": list(box)})
        tiles.append(Tile(image_id, view, path.name, tuple(box), w, h))
    primary = Path(ga or particulars)
    width, height = opened[primary].size
    definitions = {**DEFINITIONS, **(definitions or {})}
    manifest = {"schema_version": REQUEST_SCHEMA, "purpose": PURPOSE,
                "source_sha256": _sha256(primary.read_bytes()), "engineering_approved": False,
                "context": {"coordinate_frame": "attachment_pixels",
                            "sheet_size_px": [width, height],
                            "note": "Tiles overlap; list an item seen in two tiles once.",
                            "definitions": definition_sentences(definitions)},
                "images": entries}
    write_json(out / "request.json", manifest)
    # The host-side record of which file each image shows; never sent to the model.
    sources = {}
    if ga:
        sources["ga"] = {"file": Path(ga).name, "sha256": manifest["source_sha256"], "size_px": [width, height]}
    if particulars:
        table_size = Image.open(particulars).size
        sources["particulars"] = {"file": Path(particulars).name, "sha256": _sha256(Path(particulars).read_bytes()),
                                  "size_px": list(table_size)}
    write_json(out / "sources.json", {"sources": sources, "tiles": [t.__dict__ for t in tiles],
                                      "definitions": definitions})
    return manifest


# ------------------------------------------------------------------ the receipted model call

def call_model(binary: Path, request: Path, out: Path, basis: str, model: str = MODEL) -> dict:
    """One receipted ``ga_reading`` request through the Rust controller; returns its reading record."""
    completed = subprocess.run([str(binary), "vision-request", "--request", str(request), "--out", str(out),
                                "--provider-transfer-basis", basis, "--model", model],
                               capture_output=True, text=True)
    reading_path = Path(out) / "vision_reading.json"
    if reading_path.exists():
        return json.loads(reading_path.read_text())
    return failed_reading(Path(out), model, completed.stderr)


def failed_reading(out: Path, model: str, stderr: str) -> dict:
    """A reading record for a request that wrote none, built from the receipts on disk.

    Every receipt is a request that counts against the budget; with no reply, every value of
    the case becomes an abstention (``interpret``), not a missing output.
    """
    receipts = [json.loads(path.read_text()) for path in sorted((out / "receipts").glob("*.json"))]
    usage = {"requests_intended": len(receipts),
             "requests_completed": sum(r.get("state") == "completed" for r in receipts),
             "prompt_tokens": sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in receipts),
             "completion_tokens": sum((r.get("usage") or {}).get("completion_tokens", 0) for r in receipts),
             "observed_cost_usd": sum(r.get("observed_cost_usd") or 0.0 for r in receipts)}
    try:
        error = json.loads(stderr.strip().splitlines()[-1]).get("error_code")
    except (ValueError, IndexError, AttributeError):
        error = "unreadable_error"
    return {"requested_model": model, "endpoint": None, "usage": usage, "receipts": receipts, "reply": None,
            "stop_reason": f"vision_request_failed: {error}"}


def usage_of(reading: dict) -> dict:
    """Requests, tokens and the CLI's API-price estimate (``list_cost``) of one reading."""
    receipts = reading.get("receipts") or []
    list_cost = sum((r.get("usage") or {}).get("list_cost") or 0.0 for r in receipts)
    usage = reading.get("usage") or {}
    return {"requests": usage.get("requests_intended", len(receipts)),
            "completed": usage.get("requests_completed", 0),
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
            "observed_cost_usd": usage.get("observed_cost_usd", 0.0), "list_cost_usd": round(list_cost, 6),
            "model": reading.get("requested_model"), "endpoint": reading.get("endpoint")}


# ------------------------------------------------------------------ interpretation

def _number_options(text: str) -> list[float]:
    """Every reading of a printed number: a lone comma may be decimal or thousands."""
    text = text.strip()
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", text):
        options = {float(text.replace(",", ""))}
        if text.count(",") == 1 and "." not in text:
            options.add(float(text.replace(",", ".")))
        return sorted(options)
    if re.fullmatch(r"\d+,\d+", text):
        return [float(text.replace(",", "."))]
    if re.fullmatch(r"\d+(\.\d+)?|\.\d+", text):
        return [float(text)]
    return []


def parse_length(printed: str, unit_context: str | None, field: str) -> tuple[float | None, str]:
    """Metres from a printed length, or (None, reason). Ambiguity is refused, never resolved."""
    text = " ".join(printed.replace(" ", " ").split())
    has_unit = bool(re.search(r"[a-zA-Z'’′\"”]", text))
    if not has_unit and unit_context:
        unit = re.sub(r"[\[\]()]", "", unit_context).strip()
        text = f"{text} {unit}"
    match = _LENGTH.fullmatch(text) or _PREFIX_LENGTH.fullmatch(text)
    if not match:
        return None, f"no unit or unreadable value in {printed[:48]!r}"
    if match.groupdict().get("metric") is not None:
        factor = {"mm": 0.001, "cm": 0.01}.get(match["unit"].lower(), 1.0)
        options = [value * factor for value in _number_options(match["metric"])]
    else:
        options = [_length(match)] if _length(match) is not None else []
    low, high = PLAUSIBLE[field]
    plausible = sorted({round(v, 6) for v in options if v is not None and low <= v <= high})
    if len(plausible) == 1:
        return plausible[0], "parsed"
    if not plausible:
        return None, f"{printed[:48]!r} is not a plausible {field}"
    return None, f"{printed[:48]!r} has more than one plausible reading"


def parse_mass(printed: str, unit_context: str | None) -> tuple[float | None, str]:
    """Metric tonnes from a printed deadweight, or (None, reason)."""
    text = " ".join(printed.split())
    match = re.fullmatch(r"([\d.,]+)\s*(?:metric\s+)?(t|mt|tonnes?|tons?|m/t|ltons?|long\s+tons?)?\.?", text, re.I)
    unit = (match[2] if match and match[2] else (unit_context or "")).strip().lower()
    if not match or not unit:
        return None, f"no unit or unreadable value in {printed[:48]!r}"
    if "l" in unit.replace("metric", ""):
        return None, "long tons are not converted"
    low, high = PLAUSIBLE["deadweight_t"]
    plausible = sorted({v for v in _number_options(match[1]) if low <= v <= high})
    if len(plausible) == 1:
        return plausible[0], "parsed"
    return None, f"{printed[:48]!r} has no single plausible tonnage"


def _sheet_box(tile: Tile, box_px) -> list[float]:
    """Model box (pixels of the attached image) to source pixels of the tile's sheet."""
    left, top, right, bottom = tile.crop_box_px
    scale_x, scale_y = (right - left) / tile.width, (bottom - top) / tile.height
    x0, y0, x1, y1 = (float(v) for v in box_px)
    return [left + x0 * scale_x, top + y0 * scale_y, left + x1 * scale_x, top + y1 * scale_y]


def _ink_share(ink: np.ndarray, box: list[float]) -> float:
    left, top, right, bottom = (int(round(v)) for v in box)
    patch = ink[max(0, top):max(0, bottom), max(0, left):max(0, right)]
    return float(patch.mean()) if patch.size else 0.0


def _number_key(number: str | None) -> str | None:
    """'No. 3', '3', 'NO3' -> '3'; '4 A' -> '4A'. None for an unnumbered item."""
    if not number:
        return None
    key = re.sub(r"^(?:NO\.?|N°)\s*", "", number.strip().upper())
    key = re.sub(r"[\s.]", "", key)
    return key or None


def interpret(reading: dict, request_dir: Path, sources_dir: Path) -> dict:
    """Turn a completed reading into particulars, counts and spaces with source records."""
    request_dir, sources_dir = Path(request_dir), Path(sources_dir)
    meta = json.loads((request_dir / "sources.json").read_text())
    tiles = {t["image_id"]: Tile(**{**t, "crop_box_px": tuple(t["crop_box_px"])}) for t in meta["tiles"]}
    sizes = {s["file"]: s["size_px"] for s in meta["sources"].values()}
    ga_name = (meta["sources"].get("ga") or meta["sources"]["particulars"])["file"]
    ink = {name: np.asarray(Image.open(sources_dir / name).convert("L")) < INK_LEVEL for name in sizes}
    result = {"schema": SCHEMA, "engineering_approved": False, "model": reading.get("requested_model"),
              "sources": meta["sources"], "usage": usage_of(reading),
              "definitions": {**DEFINITIONS, **meta.get("definitions", {})},
              "particulars": {}, "ship_type": {"value": None, "status": "unknown"},
              "counts": {}, "views": [], "spaces": [], "checks": []}
    reply = (reading.get("reply") or {}).get(PURPOSE)
    if reply is None:
        reason = reading.get("stop_reason") or "the model gave no valid reply"
        for field in [*LENGTH_FIELDS.values(), "deadweight_t"]:
            result["particulars"][field] = {"value": None, "status": "unknown", "reason": reason}
        for name in COUNT_KINDS:
            result["counts"][name] = {"value": None, "status": "unknown", "reason": reason}
        return result

    def region_of(image_id: str, box_normalized, view: str | None = None) -> tuple[dict, float]:
        tile = tiles[image_id]
        box = _sheet_box(tile, box_normalized)
        record = source_record.region(tile.sheet, view=view, box_px=box, page_px=sizes[tile.sheet])
        return record, _ink_share(ink[tile.sheet], box)

    for refused in reply.get("refused") or []:
        result["checks"].append({"code": refused["error_code"], "status": "refused",
                                 "label": str(refused["entry"].get("label") or refused["entry"].get("field"))[:64]})
    ship_type = reply["ship_type"]
    if "value" in ship_type:
        result["ship_type"] = {"value": ship_type["value"], "status": "read", "evidence": ship_type["evidence"]}
    else:
        result["ship_type"]["reason"] = ship_type["missing"]

    # Particulars: the model gives printed text; code parses it or abstains.
    printed = {p["field"]: p for p in reply["particulars"]}
    for field, key in [*LENGTH_FIELDS.items(), ("deadweight", "deadweight_t")]:
        entry = printed.get(field)
        if entry is None:
            result["particulars"][key] = {"value": None, "status": "unknown", "reason": "not found printed"}
            continue
        view = "table" if tiles[entry["image_id"]].view.startswith("particulars_table") else None
        region, share = region_of(entry["image_id"], entry["box"], view)
        if key == "deadweight_t":
            value, why = parse_mass(entry["printed"], entry["unit_context"])
        else:
            value, why = parse_length(entry["printed"], entry["unit_context"], key)
        if value is not None and share < MIN_INK_SHARE:
            value, why = None, "the value's box holds no ink"
        item = {"value": value, "status": "read" if value is not None else "unknown",
                "printed": entry["printed"], "unit_context": entry["unit_context"], "evidence": entry["evidence"]}
        if value is None:
            item["reason"] = why
        item["source_record"] = source_record.read([region]) if value is not None else source_record.unknown(why)
        result["particulars"][key] = item
    loa, lbp = result["particulars"]["loa_m"], result["particulars"]["lbp_m"]
    if loa["value"] is not None and lbp["value"] is not None and lbp["value"] > loa["value"] * 1.001:
        for item in (loa, lbp):
            item.update(value=None, status="unknown", reason="LBP read longer than LOA")
            item["source_record"] = source_record.unknown("LBP read longer than LOA")
        result["checks"].append({"code": "lbp_above_loa", "status": "check"})

    # Views: where each drawn view lies on the sheet, so every space can name its view.
    for view in reply.get("views") or []:
        region, _ = region_of(view["image_id"], view["box"])
        if region["box_px"] is None:
            continue
        result["views"].append({"view_id": view["view_id"], "kind": view["kind"], "title": view["title"],
                                "sheet": region["sheet"], "box_px": region["box_px"]})

    # Spaces: every item with its region; boxes on blank paper are dropped.
    for index, item in enumerate(reply["items"]):
        region, share = region_of(item["image_id"], item["box"])
        if share < MIN_INK_SHARE or region["box_px"] is None:
            result["checks"].append({"code": "item_box_without_ink", "status": "dropped", "label": item["label"]})
            continue
        kind = item["kind"]
        if item["basis"] == "read":
            # The same text check as the fine pass: a label read as a cargo crane must not say HOSE.
            from .ga_labels import label_kind
            kind = label_kind(kind, item["label"], result["definitions"])
            if kind != item["kind"]:
                result["checks"].append({"code": "coarse_kind_not_in_text", "status": "changed",
                                         "label": item["label"][:64], "kind": item["kind"]})
        add_space(result, f"{kind}-{index + 1:03d}", kind, item["label"], item["number"],
                  "read" if item["basis"] == "read" else "guessed", region, "coarse")
    result["model_counts"] = reply["counts"]
    finish_counts(result)
    return result


def view_of(result: dict, sheet: str, box: list[float]) -> dict | None:
    """The smallest drawn view whose box holds the centre of ``box``."""
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    holding = [v for v in result["views"] if v["sheet"] == sheet
               and v["box_px"][0] <= x <= v["box_px"][2] and v["box_px"][1] <= y <= v["box_px"][3]]
    return min(holding, key=lambda v: (v["box_px"][2] - v["box_px"][0]) * (v["box_px"][3] - v["box_px"][1]),
               default=None)


RECORD_VIEWS = {"profile": "profile", "deck_plan": "plan", "tank_top_plan": "plan", "accommodation_plan": "plan",
                "section": "section", "particulars_table": "table"}


def add_space(result: dict, space_id: str, kind: str, label: str, number: str | None, status: str,
              region: dict, found_by: str) -> dict:
    """Add one space with its source record and the view it lies in."""
    view = view_of(result, region["sheet"], region["box_px"])
    region = {**region, "view": RECORD_VIEWS.get(view["kind"]) if view else None}
    number = _number_with_side(number, label)
    if status == "read":
        record = source_record.read([region])
    else:
        record = source_record.guessed("identified from the drawn outline by the model; no printed label", [region])
    space = {"id": space_id, "kind": kind, "label": label, "number": number, "status": status,
             "view_id": view["view_id"] if view else None, "found_by": found_by,
             "source_record": source_record.validate(record)}
    result["spaces"].append(space)
    return space


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
    if re.search(r"\d\s*\.?\s*[A-Z]\.?$", label.upper()) and len(words[-1]) == 1 and len(words) <= 2:
        return "a single letter after the number: the label is cut"
    last = words[-1]
    raw_last = label.upper().split()[-1] if label.split() else ""
    # A dotted abbreviation ("O.T.") is not a cut word, only a plain word of three letters or more.
    if (len(last) >= 3 and "." not in raw_last and last not in vocabulary
            and any(word.startswith(last) and len(word) > len(last) for word in vocabulary)):
        return f"'{last}' is the start of a longer word printed on the sheet: the label is cut"
    if (len(words) == 1 and space.get("kind") in ("other_space", "other_tank") and words[0] in vocabulary
            and words[0] not in whole_labels):
        return f"'{words[0]}' is printed only as a part of longer labels on the sheet"
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


def drop_fragments(result: dict) -> int:
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


# ------------------------------------------------------------------ app run folder

def write_app_run(result: dict, sources_dir: Path, task: Path, name: str) -> Path:
    """A run folder the desktop app opens: the GA page, the reading, no 3D model."""
    import shutil
    task = Path(task)
    (task / "ga_reading").mkdir(parents=True, exist_ok=False)
    (task / "domain").mkdir()
    ga = (result["sources"].get("ga") or result["sources"]["particulars"])["file"]
    shutil.copy2(Path(sources_dir) / ga, task / "ga_reading" / ga)
    if "particulars" in result["sources"] and "ga" in result["sources"]:
        shutil.copy2(Path(sources_dir) / result["sources"]["particulars"]["file"], task / "ga_reading")
    write_json(task / "ga_reading" / "ga_reading.json", result)
    write_json(task / "domain" / "state.json", {"inspection_artifacts": [
        {"kind": "source_page", "path": f"ga_reading/{ga}"}]})
    write_json(task / "state.json", {"state": {
        "task_id": name, "status": "awaiting_human_review", "kind": "ga_reading", "engineering_approved": False,
        "config": {"source_spec": f"/{name}/spec.json", "policy": "deterministic", "model": result.get("model")}}})
    return task


def overlay(result: dict, sources_dir: Path, out_png: Path) -> None:
    """Draw every read (blue) and guessed (orange) box on the GA sheet, for visual checks."""
    from PIL import ImageDraw
    ga = (result["sources"].get("ga") or result["sources"]["particulars"])["file"]
    canvas = Image.open(Path(sources_dir) / ga).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    records = [(s["label"] or s["kind"], s["source_record"]) for s in result["spaces"]]
    records += [(f"{k}={v['value']}", v["source_record"]) for k, v in result["particulars"].items()
                if v.get("source_record", {}).get("kind") == "read"]
    for label, record in records:
        colour = (0, 90, 255) if record["kind"] == "read" else (255, 140, 0)
        for region in record.get("regions") or record.get("inputs") or []:
            if region.get("sheet") == ga and region.get("box_px"):
                draw.rectangle(region["box_px"], outline=colour, width=3)
                draw.text((region["box_px"][0], region["box_px"][3] + 2), label[:24], fill=colour)
    canvas.save(out_png)


# ------------------------------------------------------------------ command line

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff")


def case_files(inputs: Path, case: str) -> tuple[Path | None, Path | None]:
    """The GA (``<case>_GA.*``) and the particulars table (the one other ``<case>_*`` image)."""
    files = sorted(p for p in Path(inputs).glob(f"{case}_*") if p.suffix.lower() in IMAGE_SUFFIXES)
    ga = [p for p in files if p.stem.upper() == f"{case}_GA".upper()]
    others = [p for p in files if p not in ga]
    if len(ga) > 1 or len(others) > 1 or not files:
        raise ValueError(f"{case}: expected one {case}_GA image and at most one other image, found {len(files)}")
    return (ga[0] if ga else None), (others[0] if others else None)


def add_usage(total: dict, more: dict) -> dict:
    """The sum of two usage records (``usage_of``)."""
    keys = ("requests", "completed", "prompt_tokens", "completion_tokens", "observed_cost_usd", "list_cost_usd")
    return {**total, **{key: round(total.get(key, 0) + more.get(key, 0), 6) for key in keys}}


def read_one(ga: Path | None, particulars: Path | None, out: Path, binary: Path, basis: str,
             model: str = MODEL, app_task: Path | None = None, fine: bool = True,
             measure: bool = False, case_id: str | None = None,
             max_requests: int = MAX_REQUESTS_PER_SHIP, definitions: dict | None = None) -> dict:
    """Coarse request, interpretation, the fine pass and the frame-scale pass; writes ``out/ga_reading.json``.

    With ``measure`` the frame-scale pass (``ga_scale``, up to seven more requests) adds ``frames``,
    ``measured`` and the extent of each space, and writes ``out/ga_arrangement_input.json``.

    ``result["passes"]`` records per ship the requests and crops each pass needed.
    """
    from .ga_labels import fine_pass
    out = Path(out).resolve()
    prepare(ga, out / "request", particulars, definitions)
    binary = Path(binary).resolve()
    reading = call_model(binary, out / "request", out / "provider", basis, model)
    sources_dir = Path(ga or particulars).resolve().parent
    result = interpret(reading, out / "request", sources_dir)
    result["case_id"] = case_id or out.name
    images = len(json.loads((out / "request" / "request.json").read_text())["images"])
    result["passes"] = {"coarse": {"requests": result["usage"]["requests"], "images": images}}
    if fine and ga is not None and reading.get("reply") is not None:
        readings = []

        def call(request_dir: Path, provider_dir: Path) -> dict:
            readings.append(call_model(binary, request_dir, provider_dir, basis, model))
            return readings[-1]

        # The coarse request is one of the ship's requests; the fine pass gets the rest.
        stats = fine_pass(result, Path(ga).resolve(), out / "fine", call, max_requests - 1)
        for fine_reading in readings:
            result["usage"] = add_usage(result["usage"], usage_of(fine_reading))
        result["passes"]["fine"] = stats
    if reading.get("reply") is not None:
        result["passes"]["fragments_dropped"] = drop_fragments(result)
    if measure and ga is not None and reading.get("reply") is not None:
        measure_one(result, Path(ga).resolve(), out, binary, basis, model, case_id or out.name)
    write_json(out / "ga_reading.json", result)
    if app_task:
        write_app_run(result, sources_dir, app_task, out.name)
    return result


def measure_one(result: dict, ga: Path, out: Path, binary: Path, basis: str, model: str, case_id: str) -> dict:
    """The frame-scale pass on a reading: ``frames``, ``measured`` and space extents (up to seven requests).

    Measured values are kept apart from the printed particulars; ``out/ga_arrangement_input.json``
    is the file for the arrangement step (see ``ga_scale``).
    """
    from . import ga_scale
    readings = []
    result["case_id"] = case_id

    def call(request_dir: Path, provider_dir: Path) -> dict:
        readings.append(call_model(binary, request_dir, provider_dir, basis, model))
        return readings[-1]

    result.setdefault("passes", {})["scale"] = ga_scale.scale_pass(result, ga, Path(out) / "scale", call)
    for reading in readings:
        result["usage"] = add_usage(result["usage"], usage_of(reading))
    write_json(Path(out) / "ga_arrangement_input.json", ga_scale.arrangement_input(result, case_id))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m vessel_reconstruction.ga_commercial")
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Write a ga_reading request directory.")
    prep.add_argument("--ga", type=Path)
    prep.add_argument("--particulars", type=Path)
    prep.add_argument("--out", required=True, type=Path)
    read = commands.add_parser("read", help="Prepare, call the model once (receipted) and interpret.")
    read.add_argument("--ga", type=Path)
    read.add_argument("--particulars", type=Path)
    read.add_argument("--app-task", type=Path, help="Also write a run folder for the desktop app.")
    batch = commands.add_parser("batch", help="Read cases <case>_* of an inputs folder, one request each.")
    batch.add_argument("--inputs", required=True, type=Path)
    batch.add_argument("--cases", required=True, nargs="+")
    batch.add_argument("--max-requests", required=True, type=int,
                       help="Campaign budget: stop before a case when this many requests were sent.")
    measure = commands.add_parser("measure", help="Frame-scale pass on an existing reading (up to seven requests).")
    measure.add_argument("--reading", required=True, type=Path, help="A ga_reading.json of this GA.")
    measure.add_argument("--ga", required=True, type=Path)
    measure.add_argument("--case", required=True)
    for command in (read, batch):
        # Off by default: the GA exam run (plan, "What the evaluator runs") sends three requests
        # a ship and reads printed values only.
        command.add_argument("--measure", action="store_true",
                             help="Also measure with the printed frame scale (up to seven more requests a ship).")
        command.add_argument("--max-requests-per-ship", type=int, default=MAX_REQUESTS_PER_SHIP,
                             help="Ceiling of requests for one ship: one coarse request, then fine requests "
                                  "until every label blob is read (default %(default)s).")
        command.add_argument("--one-hold-per-number", action="store_true",
                             help="Definition: holds numbered as halves (4A, 4F) count as one hold.")
        command.add_argument("--slop-holding-tank-not-slop", action="store_true",
                             help="Definition: a slop holding tank is not counted as a slop tank.")
    for command in (read, batch, measure):
        command.add_argument("--out", required=True, type=Path)
        command.add_argument("--binary", required=True, type=Path)
        command.add_argument("--basis", required=True)
        command.add_argument("--model", default=MODEL)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        manifest = prepare(args.ga, args.out, args.particulars)
        print(json.dumps({"ok": True, "images": len(manifest["images"]), "engineering_approved": False}))
        return 0
    if args.command == "measure":
        result = json.loads(args.reading.read_text())
        args.out.mkdir(parents=True, exist_ok=False)
        measure_one(result, args.ga.resolve(), args.out.resolve(), args.binary.resolve(), args.basis, args.model,
                    args.case)
        write_json(args.out / "ga_reading.json", result)
        print(json.dumps({"ok": True, "scale": result["passes"]["scale"], "engineering_approved": False}))
        return 0
    definitions = {"split_holds_are_separate": not args.one_hold_per_number,
                   "slop_holding_tank_is_slop": not args.slop_holding_tank_not_slop}
    if args.command == "read":
        result = read_one(args.ga, args.particulars, args.out, args.binary, args.basis, args.model, args.app_task,
                          measure=args.measure, max_requests=args.max_requests_per_ship, definitions=definitions)
        print(json.dumps({"ok": bool(result["spaces"] or result["counts"].get("cargo_holds", {}).get("status") == "read"),
                          "usage": result["usage"], "engineering_approved": False}))
        return 0
    ledger = {"schema": "marinaframe.ga_batch.v1", "model": args.model, "max_requests": args.max_requests,
              "cases": {}, "engineering_approved": False}
    sent = 0
    for case in args.cases:
        if sent >= args.max_requests:
            ledger["cases"][case] = {"status": "not_run_budget"}
            continue
        try:
            ga, particulars = case_files(args.inputs, case)
            result = read_one(ga, particulars, args.out / case, args.binary, args.basis, args.model,
                              measure=args.measure, case_id=case, max_requests=args.max_requests_per_ship,
                              definitions=definitions)
            sent += result["usage"]["requests"]
            ledger["cases"][case] = {"status": "read", "usage": result["usage"]}
        except (OSError, ValueError, RuntimeError) as error:
            ledger["cases"][case] = {"status": "failed", "error": str(error)[:300]}
        write_json(args.out / "batch.json", ledger)
    totals = {key: sum(c.get("usage", {}).get(key, 0) for c in ledger["cases"].values())
              for key in ("requests", "prompt_tokens", "completion_tokens", "list_cost_usd")}
    ledger["totals"] = totals
    write_json(args.out / "batch.json", ledger)
    print(json.dumps({"ok": True, "totals": totals, "engineering_approved": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
