"""Commercial GA images."""
from __future__ import annotations

from .ga_commercial_settings import (
    DEFINITIONS,
    MAX_IMAGES,
    MAX_IMAGE_BYTES,
    MAX_PIXELS,
    MAX_SIDE_PX,
    MAX_TOTAL_IMAGE_BYTES,
    PURPOSE,
    REDUCED_GREY_LEVELS,
    REQUEST_SCHEMA,
    SCALE_MARGIN,
    TILE_OVERLAP,
    definition_sentences,
)
from .provenance import write_json
from PIL import Image
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import hashlib
import math
import numpy as np


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
    # "ga" or "particulars": which source file the tile shows (runs before 2026-11-12 lack it).
    source: str = ""


def load_grey(path: Path) -> Image.Image:
    """A source image in 8-bit grey, as the request shows it and the ink check reads it.

    16-bit grey is scaled to 8 bits and a transparent background is made white: a plain
    conversion clips 16-bit grey to white paper and ignores transparency, so a box over printed
    text could hold no ink (holdout exam, 2026-11-12: a particulars table). An 8-bit opaque image
    is unchanged.
    """
    image = Image.open(path)
    if image.mode in ("I", "I;16", "I;16B", "I;16L"):
        values = np.asarray(image, dtype=np.float64)
        scale = 255.0 / 65535.0 if values.size and values.max() > 255 else 1.0
        return Image.fromarray(np.clip(np.round(values * scale), 0, 255).astype(np.uint8), "L")
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        return Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba).convert("L")
    return image.convert("L")


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
    opened = {path: load_grey(path) for path in {item[2] for item in plan}}
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
        role = "particulars" if particulars is not None and Path(path) == Path(particulars) else "ga"
        tiles.append(Tile(image_id, view, path.name, tuple(box), w, h, role))
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
        sources["ga"] = {"file": Path(ga).name, "sha256": manifest["source_sha256"], "size_px": [width, height],
                         "path": str(Path(ga).resolve())}
    if particulars:
        table_size = Image.open(particulars).size
        sources["particulars"] = {"file": Path(particulars).name, "sha256": _sha256(Path(particulars).read_bytes()),
                                  "size_px": list(table_size), "path": str(Path(particulars).resolve())}
    write_json(out / "sources.json", {"sources": sources, "tiles": [t.__dict__ for t in tiles],
                                      "definitions": definitions})
    return manifest
