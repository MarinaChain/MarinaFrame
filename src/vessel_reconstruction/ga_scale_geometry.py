"""Commercial GA geometry; rules and constants unchanged."""
from __future__ import annotations

from . import source_record
from .ga_scale_settings import (
    SIDE_WORDS,
)
from pathlib import Path
import json
import re


# ------------------------------------------------------------------ interpretation

def _tiles(request_dir: Path) -> dict[str, dict]:
    return {t["image_id"]: t for t in json.loads((Path(request_dir) / "sources.json").read_text())["tiles"]}


def _to_sheet(tile: dict, x: float, y: float) -> tuple[float, float]:
    left, top, right, bottom = tile["crop_box_px"]
    return left + x * (right - left) / tile["width"], top + y * (bottom - top) / tile["height"]


def _view_id(tile: dict) -> str:
    return tile["view"].split(":")[1]


def _unknown(reason: str) -> dict:
    return {"value": None, "status": "unknown", "reason": reason, "source_record": source_record.unknown(reason)}


def _point_region(sheet: str, page_px, view: str | None, *points) -> dict:
    """A region that holds the given sheet points (with a little room), for hover-to-source."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return source_record.region(sheet, view=view, page_px=page_px,
                                box_px=[min(xs) - 12, min(ys) - 12, max(xs) + 12, max(ys) + 12])


def side_of_label(label: str) -> str | None:
    """'both', 'port', 'starboard' or 'centre' when the printed label says the side."""
    text = label.upper()
    for pattern, side in SIDE_WORDS:
        if re.search(pattern, text):
            return side
    return None
