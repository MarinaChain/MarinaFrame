"""Shared loading for the drawing-set benchmarks: labelled sheets, reduced grey pages, cached OCR text."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
SOURCES = Path("/Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources")
LABELS = Path("work/drawing_set/labels.json")
CACHE = Path("work/drawing_set/cache")
WORK_SIDE = 3200


def labelled() -> dict[str, dict]:
    return json.loads(LABELS.read_text())


def load_gray(path: Path, side: int = WORK_SIDE) -> tuple[np.ndarray, dict]:
    """A grey copy with longest side ``side`` (anti-aliased) and the page facts (full size, dpi, pdf points)."""
    info: dict = {}
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(path) as document:
            page = document[0]
            info["pdf_points"] = [page.rect.width, page.rect.height]
            zoom = side / max(page.rect.width, page.rect.height)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
            gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width).copy()
        info["full_px"] = [round(info["pdf_points"][0] / 72 * 200), round(info["pdf_points"][1] / 72 * 200)]
        info["dpi"] = 200.0
        return gray, info
    with Image.open(path) as opened:
        info["full_px"] = list(opened.size)
        dpi = opened.info.get("dpi")
        info["dpi"] = float(dpi[0]) if dpi and dpi[0] > 1 else None
        picture = opened.convert("L")
    scale = side / max(picture.size)
    if scale < 1:
        picture = picture.resize((round(picture.width * scale), round(picture.height * scale)), Image.BOX)
    return np.asarray(picture).copy(), info


def cached_text(path: Path, gray: np.ndarray, ocr) -> tuple[str, str, str]:
    """PDF text or OCR text, cached on disk by path (OCR of a big scan takes seconds)."""
    from vessel_reconstruction.sheet_types import sheet_text
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (hashlib.sha1(str(path).encode()).hexdigest() + ".v2.json")
    if key.exists():
        data = json.loads(key.read_text())
        return data["text"], data["title"], data["where"]
    text, title, where = sheet_text(path, 0, gray, ocr)
    key.write_text(json.dumps({"text": text, "title": title, "where": where, "path": str(path)}))
    return text, title, where
