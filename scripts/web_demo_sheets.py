"""Drawing sheets that a demo run's source records name but its run folder does not hold
(docs/WEB_DEMO.md, "Extra sheets"). The R/V Gunnerus whole-vessel stage read its DXF sheets
straight from the data set, so the run lists only the lines-plan raster; the hover cards of its
parts then had no sheet to show.

For each listed sheet this renders the DXF to a PNG (at most MAX_EDGE_PX on the long edge) with a
known transform from DXF model units to pixels, so a box recorded in DXF units (the "DXF box"
of a part's basis) lands on the same place of the picture. Renders are cached by the DXF's
SHA-256. Needs ezdxf and matplotlib (the repository .venv has both).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# The long edge of a rendered sheet. Same limit as the drawing images of the demo.
MAX_EDGE_PX = 4000
# The short preview of the Sources list (the app's own thumbnail side, app/core/src/sources.rs).
THUMB_EDGE_PX = 320
# Matplotlib draws at this resolution; the figure size gives the pixel size.
RENDER_DPI = 100
# The sheet frame: one of the FRAME_CANDIDATES largest entity boxes that holds at least
# FRAME_SHARE of the entities' centres.
FRAME_SHARE = 0.8
FRAME_CANDIDATES = 5
# Without a frame, a group of fewer than OUTLIER_SHARE of the entities, apart from the rest by a
# gap of at least OUTLIER_GAP of the span, is left out (revision clouds, stray points).
OUTLIER_SHARE = 0.1
OUTLIER_GAP = 0.1
# Part of the render cache key: a new value renders every sheet again.
RENDER_VERSION = 4


@dataclass(frozen=True)
class Render:
    """A rendered sheet: its PNG, its pixel size and the DXF extents it shows."""

    png: Path
    width: int
    height: int
    # DXF model extents shown: (min x, min y, max x, max y).
    extents: tuple[float, float, float, float]

    def box_px(self, box: tuple[float, float, float, float]) -> list[float]:
        """A DXF box (x0, y0, x1, y1) in the picture's pixels [left, top, right, bottom]."""
        min_x, min_y, max_x, max_y = self.extents
        scale = self.width / (max_x - min_x)
        x0, y0, x1, y1 = box
        return [
            round((min(x0, x1) - min_x) * scale, 1),
            round((max_y - max(y0, y1)) * scale, 1),
            round((max(x0, x1) - min_x) * scale, 1),
            round((max_y - min(y0, y1)) * scale, 1),
        ]


import re
import shutil

# A box in DXF model units, as the whole-vessel stage writes it into a part's basis.
DXF_BOX = re.compile(r"DXF box \(\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\)")


class SheetError(Exception):
    """A listed sheet is missing or is not the file the selection names."""


def dxf_box_of(component: dict) -> tuple[float, float, float, float] | None:
    """The DXF box of a part's outline basis, or None."""
    for argument in component.get("arguments") or []:
        if argument.get("name") != "outline":
            continue
        match = DXF_BOX.search(argument.get("basis") or "")
        if match:
            return tuple(float(value) for value in match.groups())
    return None


def add_extra_sheets(run_dir: Path, sheets_root: Path, listed: list[dict], cache: Path) -> list[str]:
    """Render each listed sheet, add it to the run's sources and page previews, and give the
    source-record regions on it their page size (and, on the sheet whose model frame the parts'
    DXF boxes use, the box in pixels). Returns the SHA-256 of every sheet added."""
    sources_file = run_dir / "sources.json"
    pages_file = run_dir / "pages.json"
    task_file = run_dir / "task.json"
    sources = json.loads(sources_file.read_text())
    pages = json.loads(pages_file.read_text())
    view = json.loads(task_file.read_text())
    added = []
    renders = {}
    # A run that holds its sheets itself (scripts/add_run_sheets.py) lists them already.
    held = {source["name"] for source in sources["sources"]}
    for sheet in listed:
        if sheet["sheet"] in held:
            continue
        path = sheets_root / sheet["sheet"]
        if not path.is_file():
            raise SheetError(f"{sheet['sheet']}: not found under {sheets_root}")
        digest = sha256_of(path)
        if digest != sheet["sha256"]:
            raise SheetError(f"{sheet['sheet']}: SHA-256 {digest} is not the listed {sheet['sha256']}")
        full = render_dxf(path, cache)
        thumb = render_dxf(path, cache, THUMB_EDGE_PX)
        source_id = f"sheet-{digest[:16]}"
        for size, render in (("full", full), ("thumb", thumb)):
            file = f"pages/{source_id}-0-{size}.png"
            (run_dir / file).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(render.png, run_dir / file)
            pages[f"{source_id}|0|{size}"] = {"mime": "image/png", "text": None, "width": render.width, "height": render.height, "file": file}
        sources["sources"].append({
            "id": source_id,
            "name": sheet["sheet"],
            "kind": "drawing",
            "role": sheet["role"],
            "status": "current",
            "version": 1,
            "pages": [{"index": 0, "sheet_type": sheet["role"], "scale": None, "width_px": full.width, "height_px": full.height, "dpi": None, "replaced": False}],
            "size_bytes": path.stat().st_size,
            "sha256": digest,
            "added_ms": None,
            "used_from": "r0000",
            "used_to": None,
            "replaced_by": None,
            "note": "Read by the whole-vessel stage from the drawing set; shown here rendered from its DXF.",
            "previewable": True,
        })
        renders[sheet["sheet"]] = (full, sheet.get("dxf_boxes_view"))
        added.append(digest)
    for component in view.get("components") or []:
        record = component.get("source_record") or {}
        box = dxf_box_of(component)
        for region in record.get("regions") or []:
            known = renders.get(region.get("sheet"))
            if not known:
                continue
            render, boxes_view = known
            region["page_px"] = [render.width, render.height]
            if box and boxes_view and region.get("view") == boxes_view and region.get("box_px") is None:
                region["box_px"] = render.box_px(box)
    sources_file.write_text(json.dumps(sources, indent=2, sort_keys=True) + "\n")
    pages_file.write_text(json.dumps(pages, indent=2, sort_keys=True) + "\n")
    task_file.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n")
    return added


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def drawing_extents(model, bbox) -> tuple[float, float, float, float]:
    """The part of the model space the drawing fills: its sheet frame, else the extents without
    outlier groups. A few entities far from the sheet (a revision cloud, a point at the origin)
    would otherwise shrink the drawing to a corner of the picture."""
    boxes = [box for box in bbox.multi_flat(model, fast=True) if box.has_data]
    if not boxes:
        raise ValueError("no drawing entities")

    # A drawing sheet has a frame: the largest box that holds most of the entities.
    centres = [((box.extmin.x + box.extmax.x) / 2, (box.extmin.y + box.extmax.y) / 2) for box in boxes]
    by_area = sorted(boxes, key=lambda box: (box.extmax.x - box.extmin.x) * (box.extmax.y - box.extmin.y), reverse=True)
    for frame in by_area[:FRAME_CANDIDATES]:
        inside = sum(
            frame.extmin.x <= x <= frame.extmax.x and frame.extmin.y <= y <= frame.extmax.y for x, y in centres
        )
        if inside >= FRAME_SHARE * len(centres):
            return frame.extmin.x, frame.extmin.y, frame.extmax.x, frame.extmax.y

    kept = without_outlier_groups(boxes)
    min_x = min(box.extmin.x for box in kept)
    min_y = min(box.extmin.y for box in kept)
    max_x = max(box.extmax.x for box in kept)
    max_y = max(box.extmax.y for box in kept)
    if max_x <= min_x or max_y <= min_y:
        raise ValueError("drawing entities have no extent")
    return min_x, min_y, max_x, max_y


def without_outlier_groups(boxes: list) -> list:
    """`boxes` without small groups set apart from the drawing: along x, then y, while the
    widest gap between neighbouring box centres is at least OUTLIER_GAP of the span and
    splits off fewer than OUTLIER_SHARE of the boxes, that side goes."""
    kept = list(boxes)
    for axis in ("x", "y", "x", "y"):
        def centre(box):
            return (getattr(box.extmin, axis) + getattr(box.extmax, axis)) / 2

        ordered = sorted(kept, key=centre)
        values = [centre(box) for box in ordered]
        span = values[-1] - values[0]
        if span <= 0 or len(values) < 3:
            continue
        gap, at = max((values[i + 1] - values[i], i) for i in range(len(values) - 1))
        low_count, high_count = at + 1, len(values) - at - 1
        if gap < OUTLIER_GAP * span:
            continue
        if low_count < OUTLIER_SHARE * len(values):
            kept = ordered[at + 1:]
        elif high_count < OUTLIER_SHARE * len(values):
            kept = ordered[: at + 1]
    return kept


def render_dxf(dxf: Path, cache: Path, max_edge: int = MAX_EDGE_PX) -> Render:
    """Render the model space of `dxf` (black lines on white) to a PNG under `cache`."""
    cache.mkdir(parents=True, exist_ok=True)
    key = f"{sha256_of(dxf)}-{max_edge}-v{RENDER_VERSION}"
    png = cache / f"{key}.png"
    facts = cache / f"{key}.json"
    if png.exists() and facts.exists():
        known = json.loads(facts.read_text())
        return Render(png, known["width"], known["height"], tuple(known["extents"]))

    import ezdxf
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf import bbox
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    document = ezdxf.readfile(dxf)
    model = document.modelspace()
    min_x, min_y, max_x, max_y = drawing_extents(model, bbox)
    scale = max_edge / max(max_x - min_x, max_y - min_y)
    width = max(1, round((max_x - min_x) * scale))
    height = max(1, round((max_y - min_y) * scale))

    figure = plt.figure(figsize=(width / RENDER_DPI, height / RENDER_DPI), dpi=RENDER_DPI)
    axes = figure.add_axes((0, 0, 1, 1))
    axes.set_axis_off()
    config = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK)
    Frontend(RenderContext(document), MatplotlibBackend(axes), config=config).draw_layout(model, finalize=False)
    # Exactly the extents, so DXF units map to pixels by `scale` with no margin.
    axes.set_xlim(min_x, max_x)
    axes.set_ylim(min_y, max_y)
    axes.set_aspect("auto")
    figure.savefig(png, dpi=RENDER_DPI, facecolor="white")
    plt.close(figure)

    from PIL import Image

    with Image.open(png) as image:
        width, height = image.size
    extents = (min_x, min_y, max_x, max_y)
    facts.write_text(json.dumps({"width": width, "height": height, "extents": extents}))
    return Render(png, width, height, extents)
