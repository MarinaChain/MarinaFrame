"""Intake of a dropped drawing set: pages, proposed view regions, and a run spec.

The desktop app calls this module (through app/core/src/intake.rs) so that a
person never writes a spec file:

    python -m vessel_reconstruction.intake prepare --out DIR [--render-dpi N] FILE...
    python -m vessel_reconstruction.intake write-spec --preview PREVIEW.json --out DIR

``prepare`` renders every page (PDF pages through ingest._read_image, rasters
with Pillow), reads its size and dpi, runs the sheet survey and proposes view
regions with a label and a confidence. It never refuses a page: a page without a
recognised view gets one ``other`` region and a warning.

``write-spec`` takes the preview after the person's edits, copies the source
files into DIR/sources, and writes DIR/intake.json (all pages and regions) and
DIR/spec.json. The spec is sheet-only (``sections: []``): in a live draft run
the model reads stations and scale in phase 1 and the domain materializes the
sections from that reading (materialize.py). No calibration is guessed here.

Labels are code proposals from ink layout, not certified view identities.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence
from scipy import ndimage

PREVIEW_SCHEMA = "marinaframe.intake.preview/1"
INTAKE_SCHEMA = "marinaframe.intake/1"
LABELS = ("body_plan", "half_breadth", "profile", "title_block", "other")
PDF_SUFFIXES = {".pdf"}
RASTER_SUFFIXES = {".png", ".tif", ".tiff", ".jpg", ".jpeg"}
# PDF pages are rendered at this resolution unless the caller asks otherwise.
DEFAULT_RENDER_DPI = 200
# Below this scan resolution thin lines lose detail.
LOW_DPI = 200
# Images smaller than this (longest side, pixels) give little room for lines.
SMALL_IMAGE_SIDE = 1000
# Region detection works on a copy with this longest side.
WORK_SIDE = 1200
THUMBNAIL_SIDE = 320
# Ink is darker than this grey level (0 black, 255 white).
INK_LEVEL = 160
# A view's region also takes in the light marks (grid lines, axes) touching its
# dark ink, so that it holds its datum lines and not only its curves.
GROUP_LEVEL = 235
# On a grey scan both levels follow the paper (its PAPER_PERCENTILE grey level):
# ink at least INK_CONTRAST, light marks at least LIGHT_CONTRAST darker.
PAPER_PERCENTILE = 90
INK_CONTRAST = 80
LIGHT_CONTRAST = 20
# Ink components smaller than this (work pixels) are scan specks.
SPECK_PIXELS = 4
# Light marks are searched at most this many box sizes around the dark ink.
LIGHT_GROWTH = 1.0
# A row or column with more ink than this fraction is a border or frame line.
FRAME_LINE_FRACTION = 0.5
# Ink is grouped into views by closing gaps of this fraction of the page side.
GROUP_GAP_FRACTION = 0.015
# Groups smaller than this fraction of the page are text or specks.
MIN_REGION_FRACTION = 0.002
# A view this many times wider than tall is a profile or half-breadth plan.
ELONGATED_ASPECT = 2.2
# Smallest share of the page for a body plan panel.
MIN_BODY_FRACTION = 0.01
# A body plan panel (one station or a half body plan) can be tall and narrow.
MIN_BODY_ASPECT = 0.3
# A title block is at most this share of the page.
MAX_TITLE_FRACTION = 0.15
# Text boxes per megapixel of region above which a region reads as text.
TEXT_DENSITY = 120.0
# A frame line covers more than this fraction of each side of a framed block.
FRAME_SIDE_FRACTION = 0.8
# Share of the box size searched inward from each side for a frame line.
FRAME_SEARCH_FRACTION = 0.08


class IntakeError(ValueError):
    """A file that cannot be read at all (the other pages still continue)."""


# ------------------------------------------------------------------ pages
def _dpi_of(image: Image.Image) -> float | None:
    value = image.info.get("dpi")
    if isinstance(value, (tuple, list)) and value and isinstance(value[0], (int, float)) and value[0] > 1:
        # PNG stores pixels per metre, so 150 dpi reads back as 150.0124.
        return round(float(value[0]), 1)
    return None


def _on_paper(frame: Image.Image) -> np.ndarray:
    """RGB pixels with transparency composited onto white paper (as ingest does)."""
    rgba = frame.convert("RGBA")
    paper = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    paper.alpha_composite(rgba)
    return np.asarray(paper.convert("RGB")).copy()


def _pdf_pages(path: Path, render_dpi: float):
    import fitz
    from .ingest import _read_image
    with fitz.open(path) as document:
        count = document.page_count
    for index in range(count):
        image, _ = _read_image({"file": path.name, "page_index": index, "render_dpi": render_dpi}, path.parent)
        yield {"kind": "pdf", "page_index": index, "dpi": float(render_dpi), "dpi_source": "pdf_render"}, image


def _raster_pages(path: Path):
    with Image.open(path) as opened:
        for index, frame in enumerate(ImageSequence.Iterator(opened)):
            dpi = _dpi_of(frame) or _dpi_of(opened)
            yield ({"kind": "raster", "page_index": index, "dpi": dpi,
                    "dpi_source": "file_metadata" if dpi else "unknown"}, _on_paper(frame))


def read_pages(path: Path, render_dpi: float = DEFAULT_RENDER_DPI):
    """Yield ``(page_info, rgb_array)`` for every page of one file."""
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        yield from _pdf_pages(path, render_dpi)
    elif suffix in RASTER_SUFFIXES:
        yield from _raster_pages(path)
    else:
        raise IntakeError(f"{path.name}: only PDF, PNG, TIFF and JPEG files can be read.")


def thumbnail_base64(image: np.ndarray) -> tuple[str, float]:
    """A small PNG of the page (base64) and its scale from page pixels."""
    picture = Image.fromarray(image)
    scale = min(1.0, THUMBNAIL_SIDE / max(picture.size))
    picture = picture.resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii"), scale


# ------------------------------------------------------------------ regions
def _gray(image: np.ndarray) -> np.ndarray:
    return image.mean(axis=2) if image.ndim == 3 else image.astype(float)


def ink_levels(gray: np.ndarray) -> tuple[float, float]:
    """Grey levels below which a page is dark ink and light marks (grid, axes).

    A scan's paper is grey and noisy, not white: both levels sit at least
    INK_CONTRAST and LIGHT_CONTRAST below the paper, and never above the
    levels of a clean white sheet.
    """
    paper = float(np.percentile(gray, PAPER_PERCENTILE))
    return min(INK_LEVEL, paper - INK_CONTRAST), min(GROUP_LEVEL, paper - LIGHT_CONTRAST)


def ink_groups(image: np.ndarray) -> list[list[int]]:
    """Boxes (page pixels) of the separate ink groups on the page, largest first."""
    height, width = image.shape[:2]
    step = max(1, int(np.ceil(max(height, width) / WORK_SIDE)))
    gray = _gray(image)[::step, ::step]
    ink_level, light_level = ink_levels(gray)
    ink = gray < ink_level
    # Scan specks would bridge the gaps between views.
    labels, _ = ndimage.label(ink, structure=np.ones((3, 3)))
    sizes = np.bincount(labels.ravel())
    ink &= (sizes >= SPECK_PIXELS)[labels]
    # Sheet borders and frames would join every view into one group.
    ink[ink.mean(axis=1) > FRAME_LINE_FRACTION, :] = False
    ink[:, ink.mean(axis=0) > FRAME_LINE_FRACTION] = False
    gap = max(3, round(GROUP_GAP_FRACTION * max(ink.shape)))
    grouped = ndimage.binary_closing(ink, structure=np.ones((gap, gap)))
    grouped = ndimage.binary_dilation(grouped, structure=np.ones((gap // 2 + 1, gap // 2 + 1)))
    labels, _ = ndimage.label(grouped)
    boxes = []
    minimum = MIN_REGION_FRACTION * ink.shape[0] * ink.shape[1]
    for found in ndimage.find_objects(labels):
        if found is None:
            continue
        rows, cols = found
        if (rows.stop - rows.start) * (cols.stop - cols.start) < minimum:
            continue
        boxes.append([cols.start, rows.start, cols.stop, rows.stop])
    boxes = _merge_overlapping([_with_light_marks(gray, box, light_level) for box in boxes])
    boxes = [[b[0] * step, b[1] * step, min(width, b[2] * step), min(height, b[3] * step)] for b in boxes]
    return sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)


def _with_light_marks(gray: np.ndarray, box: list[int], light_level: float = GROUP_LEVEL) -> list[int]:
    """Grow a dark-ink box over the light grid and axes it touches.

    Grid lines are lighter than hull lines; a view's region must hold them, since
    the datums (centreline, baseline) are drawn there. The search stays within
    LIGHT_GROWTH times the box size, so paper noise cannot grow it far.
    """
    left, top, right, bottom = box
    grow_x, grow_y = int(LIGHT_GROWTH * (right - left)), int(LIGHT_GROWTH * (bottom - top))
    window = [max(0, left - grow_x), max(0, top - grow_y),
              min(gray.shape[1], right + grow_x), min(gray.shape[0], bottom + grow_y)]
    light = gray[window[1]:window[3], window[0]:window[2]] < light_level
    labels, _ = ndimage.label(light, structure=np.ones((3, 3)))
    inner = labels[top - window[1]:bottom - window[1], left - window[0]:right - window[0]]
    touching = set(np.unique(inner)) - {0}
    if not touching:
        return box
    rows, cols = np.nonzero(np.isin(labels, list(touching)))
    grown = [window[0] + int(cols.min()), window[1] + int(rows.min()),
             window[0] + int(cols.max()) + 1, window[1] + int(rows.max()) + 1]
    # Light marks touching from everywhere (paper noise of a degraded scan) fill
    # the whole search window; keep the dark-ink box then.
    if grown[0] <= window[0] and grown[1] <= window[1] and grown[2] >= window[2] and grown[3] >= window[3] \
            and (left, top, right, bottom) != tuple(window):
        return box
    return [min(grown[0], left), min(grown[1], top), max(grown[2], right), max(grown[3], bottom)]


def _merge_overlapping(boxes: list[list[int]]) -> list[list[int]]:
    merged = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                a, b = merged[i], merged[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    merged[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del merged[j]
                    changed = True
                    break
            if changed:
                break
    return merged


def _survey(image: np.ndarray) -> dict:
    """The sheet survey (vessel_description.survey_sheet) of a reduced copy, in page pixels."""
    from .vessel_description import survey_sheet
    height, width = image.shape[:2]
    step = max(1, int(np.ceil(max(height, width) / WORK_SIDE)))
    survey = survey_sheet(image[::step, ::step], {"sections": []})
    survey["text_boxes"] = [[v * step for v in box] for box in survey["text_boxes"]]
    survey["step"] = step
    return survey


def framed(image: np.ndarray, box: list[int]) -> bool:
    """True when a rectangle is drawn around the box (as around a title block)."""
    left, top, right, bottom = box
    gray = _gray(image)
    ink_level, _ = ink_levels(gray)
    # Group boxes are grown by the grouping gap, so search inward this far for the line.
    band = max(4, int(FRAME_SEARCH_FRACTION * min(right - left, bottom - top)))

    def side_ink(strip, axis):
        return float((strip < ink_level).any(axis=axis).mean()) if strip.size else 0.0

    sides = [side_ink(gray[top:top + band, left:right], 0), side_ink(gray[bottom - band:bottom, left:right], 0),
             side_ink(gray[top:bottom, left:left + band], 1), side_ink(gray[top:bottom, right - band:right], 1)]
    return min(sides) > FRAME_SIDE_FRACTION


def _features(image: np.ndarray, box: list[int], text_boxes: list) -> dict:
    height, width = image.shape[:2]
    left, top, right, bottom = box
    area = max(1, (right - left) * (bottom - top))
    inside = sum(1 for t in text_boxes if left <= t[0] and top <= t[1] and t[2] <= right and t[3] <= bottom)
    return {"aspect": (right - left) / max(1, bottom - top), "page_fraction": area / (width * height),
            "centre": ((left + right) / 2 / width, (top + bottom) / 2 / height),
            "text_density": inside / (area / 1e6), "framed": framed(image, box)}


def classify(boxes: list[list[int]], image: np.ndarray, text_boxes: list) -> list[dict]:
    """Label each box with a proposed view and a confidence (0..1), with reasons."""
    regions = []
    for box in boxes:
        f = _features(image, box, text_boxes)
        label, confidence, reason = "other", 0.3, "no layout rule matched"
        cx, cy = f["centre"]
        lower_right = cx > 0.6 and cy > 0.6
        if f["page_fraction"] <= MAX_TITLE_FRACTION and f["framed"] and f["aspect"] < ELONGATED_ASPECT:
            label, confidence, reason = ("title_block", 0.7 if lower_right else 0.55,
                                         "framed block" + (" at the lower right" if lower_right else ""))
        elif f["page_fraction"] <= MAX_TITLE_FRACTION and lower_right and f["text_density"] >= TEXT_DENSITY:
            label, confidence, reason = "title_block", 0.5, "small text-dense block at the lower right"
        elif f["aspect"] >= ELONGATED_ASPECT and f["page_fraction"] >= MIN_BODY_FRACTION:
            label, confidence, reason = "profile", 0.45, "long, low view"
        elif f["page_fraction"] >= MIN_BODY_FRACTION and MIN_BODY_ASPECT < f["aspect"] < ELONGATED_ASPECT:
            label, confidence, reason = "body_plan", 0.5, "compact view of curves"
        elif f["text_density"] >= TEXT_DENSITY:
            label, confidence, reason = "other", 0.4, "text or table"
        regions.append({"region_px": [int(v) for v in box], "label": label, "confidence": confidence,
                        "evidence": reason, "framed": f["framed"],
                        **{k: round(f[k], 4) for k in ("aspect", "page_fraction", "text_density")}})
    # Two long views stacked: the upper is the profile, the lower the half-breadth plan.
    long_views = sorted((r for r in regions if r["label"] == "profile"), key=lambda r: r["region_px"][1])
    if len(long_views) >= 2:
        long_views[0].update(confidence=0.6, evidence="upper of the long views")
        for region in long_views[1:]:
            region.update(label="half_breadth", confidence=0.55, evidence="lower of the long views")
    regions.sort(key=lambda r: (r["region_px"][1], r["region_px"][0]))
    for index, region in enumerate(regions):
        region["region_id"] = f"r{index + 1}"
    return regions


def page_warnings(info: dict, image: np.ndarray, regions: list[dict]) -> list[dict]:
    warnings = []
    dpi = info.get("dpi")
    if info["kind"] == "raster" and dpi is None:
        warnings.append({"code": "dpi_unknown", "message": "The file does not say its resolution."})
    elif dpi is not None and dpi < LOW_DPI:
        warnings.append({"code": "low_dpi", "message": f"Scan {dpi:g} dpi: lines may be read less exactly."})
    if max(image.shape[:2]) < SMALL_IMAGE_SIDE:
        warnings.append({"code": "small_image",
                         "message": f"The page is only {image.shape[1]} x {image.shape[0]} pixels."})
    if all(r["label"] == "other" for r in regions):
        warnings.append({"code": "no_view_found",
                         "message": "No body plan, half-breadth or profile was found. Label the views yourself."})
    return warnings


def survey_page(image: np.ndarray) -> list[dict]:
    """Proposed view regions of one page; never empty."""
    survey = _survey(image)
    regions = classify(ink_groups(image), image, survey["text_boxes"])
    if not regions:
        height, width = image.shape[:2]
        regions = [{"region_id": "r1", "region_px": [0, 0, width, height], "label": "other",
                    "confidence": 0.1, "evidence": "no separate ink groups"}]
    return regions


# ------------------------------------------------------------------ prepare
def sheet_result(path: Path, info: dict, image: np.ndarray, regions: list[dict], ask=None) -> dict | None:
    """The sheet type and scale of one page (drawing_set.analyse_page); None when it cannot be read."""
    from .drawing_set import analyse_page
    try:
        gray = image.mean(axis=2).astype(np.uint8) if image.ndim == 3 else image
        facts = {"dpi": info.get("dpi"), "full_px": [int(image.shape[1]), int(image.shape[0])]}
        return analyse_page(path=path, page_index=info["page_index"], gray=gray, info=facts, file_name=path.name,
                            regions=regions, ask=ask)
    except Exception:  # typing is a help; a page it cannot read is still a page
        return None


def prepare(files: list[Path], out_dir: Path, render_dpi: float = DEFAULT_RENDER_DPI, ask=None) -> dict:
    """The intake preview of ``files``. A file that cannot be read is a warning.

    Every page also gets ``sheet`` (type, confidence, source, scale) and the preview gets ``set`` (the
    drawings checklist and the scale agreement), see docs/DRAWING_SET_INTAKE.md. ``ask`` is an optional
    model transport used only for sheets whose type the code cannot settle.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pages, warnings = [], []
    for path in files:
        path = Path(path).resolve()
        try:
            for info, image in read_pages(path, render_dpi):
                regions = survey_page(image)
                thumbnail, scale = thumbnail_base64(image)
                pages.append({"page_id": f"p{len(pages) + 1}", "file": str(path), "file_name": path.name,
                              **info, "width_px": int(image.shape[1]), "height_px": int(image.shape[0]),
                              "thumbnail_png_base64": thumbnail, "thumbnail_scale": round(scale, 6),
                              "regions": regions, "warnings": page_warnings(info, image, regions),
                              "skip": False, "sheet": sheet_result(path, info, image, regions, ask)})
        except Exception as exc:  # A broken file must not stop the other pages.
            warnings.append({"code": "unreadable_file", "file": str(path),
                             "message": f"{path.name} could not be read ({type(exc).__name__})."})
    from .drawing_set import analyse_set
    preview = {"schema": PREVIEW_SCHEMA, "pages": pages, "warnings": warnings, "render_dpi": render_dpi,
               "particulars": {}, "engineering_approved": False, "set": analyse_set(pages),
               "note": "View labels are code proposals from ink layout; edit them before the run."}
    (out_dir / "preview.json").write_text(json.dumps(preview, indent=2) + "\n")
    return preview


# ------------------------------------------------------------------ write spec
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return slug[:64] or "vessel"


def spec_page(pages: list[dict]) -> dict:
    """The page the run reads: the most confident body plan, else the first page."""
    kept = [p for p in pages if not p.get("skip")]
    if not kept:
        raise IntakeError("Every page is skipped; keep at least one page.")

    def body_confidence(page):
        return max((r.get("confidence", 0) for r in page.get("regions", []) if r.get("label") == "body_plan"),
                   default=-1)

    return max(kept, key=lambda p: (body_confidence(p), -kept.index(p)))


def _copy_sources(pages: list[dict], sources_dir: Path) -> dict:
    """Copy each distinct source file once; return original path -> copied name."""
    sources_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    for page in pages:
        original = Path(page["file"])
        if str(original) in copied:
            continue
        name = re.sub(r"[^A-Za-z0-9._-]", "_", original.name) or "page"
        while (sources_dir / name).exists():
            name = "_" + name
        shutil.copyfile(original, sources_dir / name)
        copied[str(original)] = name
    return copied


def _spec_source(page: dict, copied: dict, out_dir: Path) -> dict:
    """The spec ``source`` of the chosen page; one TIFF frame becomes its own PNG."""
    name = copied[page["file"]]
    if page["kind"] == "pdf":
        return {"file": f"sources/{name}", "page_index": page["page_index"], "render_dpi": page["dpi"],
                "transformation": f"PDF page {page['page_index'] + 1} rendered at {page['dpi']:g} dpi."}
    with Image.open(out_dir / "sources" / name) as opened:
        frames = getattr(opened, "n_frames", 1)
        if frames == 1 and opened.width * opened.height > _worker_pixel_budget():
            return _reduced_source(opened, name, out_dir)
        if frames == 1:
            return {"file": f"sources/{name}", "transformation": "Original raster; no preprocessing."}
        opened.seek(page["page_index"])
        frame_name = f"{Path(name).stem}-frame{page['page_index'] + 1}.png"
        Image.fromarray(_on_paper(opened)).save(out_dir / "sources" / frame_name)
    return {"file": f"sources/{frame_name}",
            "transformation": f"Frame {page['page_index'] + 1} of {name} saved as PNG; pixels unchanged."}


# A reduced source fills this share of the worker's pixel budget (margin for rounding).
REDUCED_SHARE_OF_BUDGET = 0.98


def _worker_pixel_budget() -> int:
    from .resources import DEFAULT_POLICY
    return DEFAULT_POLICY.pixels


def _reduced_source(opened: Image.Image, name: str, out_dir: Path) -> dict:
    """A raster above the worker's pixel budget, reduced to fit it (a full-size HAER scan is
    about 138 Mpx; the worker reads at most 16 Mpx). The original stays in sources/ for the
    body-plan reader, which measures at full resolution."""
    factor = (REDUCED_SHARE_OF_BUDGET * _worker_pixel_budget() / (opened.width * opened.height)) ** 0.5
    size = (max(1, int(opened.width * factor)), max(1, int(opened.height * factor)))
    reduced = opened.convert("L").resize(size, Image.Resampling.LANCZOS)
    reduced_name = f"{Path(name).stem}-reduced.png"
    reduced.save(out_dir / "sources" / reduced_name)
    return {"file": f"sources/{reduced_name}",
            "transformation": (f"{name} ({opened.width} x {opened.height} px) reduced to {size[0]} x {size[1]} px "
                               f"(factor {factor:.4f}) to fit the worker's source pixel budget.")}


def _constraints(particulars: dict) -> dict:
    """Known particulars the person typed (metres). Unknown fields are left out."""
    constraints = {}
    for field, name in (("loa_m", "length_m"), ("beam_m", "beam_m"), ("depth_m", "depth_m")):
        value = particulars.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            constraints[name] = float(value)
    return constraints


def _body_plan_reading(sheet: Path, out_dir: Path, ask=None) -> dict | None:
    """The automatic body-plan reading of the spec page, when the setting is on (body_plan_intake).

    Any failure is recorded, never raised: the hull path then uses the model's reading alone.
    """
    from . import body_plan_intake
    if not body_plan_intake.enabled() or sheet.suffix.lower() not in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
        return None
    try:
        return body_plan_intake.read_at_intake(sheet, out_dir, ask=ask)
    except Exception as exc:  # noqa: BLE001 - the reader is optional; the model path continues
        return {"schema": body_plan_intake.SCHEMA, "usable_for_build": False,
                "reason": f"body-plan reading failed: {type(exc).__name__}: {str(exc)[:200]}",
                "engineering_approved": False}


def write_spec(preview: dict, out_dir: Path) -> dict:
    """Copy sources and write intake.json and a sheet-only spec.json in ``out_dir``."""
    from .schema import validate_spec
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = [p for p in preview.get("pages", []) if not p.get("skip")]
    chosen = spec_page(pages)
    copied = _copy_sources(pages, out_dir / "sources")
    source = _spec_source(chosen, copied, out_dir)
    source["sha256"] = _sha256(out_dir / source["file"])
    particulars = preview.get("particulars") or {}
    name = str(particulars.get("vessel_name") or "").strip()
    source["description"] = f"Drawing set dropped in the MarinaFrame app ({len(pages)} page(s))."
    intake = {"schema": INTAKE_SCHEMA, "spec_page_id": chosen["page_id"], "particulars": particulars,
              "pages": [{key: value for key, value in page.items() if key != "thumbnail_png_base64"}
                        | {"source_file": f"sources/{copied[page['file']]}"} for page in pages],
              "engineering_approved": False,
              "note": "Region labels are proposals (code) and edits (person); not certified view identities."}
    original = out_dir / "sources" / copied[chosen["file"]]
    reading = _body_plan_reading(original, out_dir)
    if reading is not None:
        with Image.open(out_dir / source["file"]) as spec_image, Image.open(original) as original_image:
            reading["spec_page_scale"] = spec_image.width / original_image.width
        intake["body_plan_reading"] = reading
    (out_dir / "intake.json").write_text(json.dumps(intake, indent=2) + "\n")
    spec = {"schema_version": "1.0", "vessel_id": _slug(name or Path(chosen["file"]).stem), "units": "m",
            "source": source, "symmetry": "port_starboard",
            "symmetry_evidence": "Assumed for a lines drawing (one half drawn); the model checks it in phase 1.",
            "end_closure": "flat_at_terminal_stations", "sections": [], "components": [],
            "intake": {"file": "intake.json", "sha256": _sha256(out_dir / "intake.json")}}
    constraints = _constraints(particulars)
    if constraints:
        spec["constraints"] = constraints
    if name:
        spec["scope_note"] = f"Vessel name given at intake: {name[:200]}"
    (out_dir / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    gaps = validate_spec(spec, out_dir, allow_sheet_only=True)
    return {"spec_path": str(out_dir / "spec.json"), "intake_path": str(out_dir / "intake.json"),
            "spec_page_id": chosen["page_id"], "gaps": gaps}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--render-dpi", type=float, default=DEFAULT_RENDER_DPI)
    prep.add_argument("--vision", action="store_true",
                      help="ask the model about sheets whose type the code cannot settle (Claude CLI, subscription)")
    prep.add_argument("files", type=Path, nargs="+")
    write = sub.add_parser("write-spec")
    write.add_argument("--preview", type=Path, required=True)
    write.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            ask = None
            if args.vision:
                from .calibration_reading import claude_ask
                ask = claude_ask()
            result = prepare(args.files, args.out, args.render_dpi, ask)
        else:
            result = write_spec(json.loads(args.preview.read_text()), args.out)
    except (IntakeError, OSError, ValueError, KeyError) as exc:
        json.dump({"error": type(exc).__name__, "message": str(exc)[:500]}, sys.stdout)
        return 1
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
