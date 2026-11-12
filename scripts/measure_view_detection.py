"""Truth-free diagnosis of the fixed nine development lines sheets.

Only raster files are read. No benchmark module, truth file or model is used.
Evidence (including per-sheet regions) must stay in ignored work/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import draft_fit, intake

CASES = (
    ("pardon-me", "sources/haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif"),
    ("bue-girl", "sources/haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif"),
    ("thayer", "sources/haer/ca_thayer/loc_ca1506_sheet_04.tif"),
    ("balclutha", "sources/balclutha_ca54_s7.tif"),
    ("bumble-bee", "sources/haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif"),
    ("ec-collier", "dev-truth/ec-collier/md1203-sheet-00002a-lines.tif"),
    ("white-gull", "dev-truth/white-gull/md1939-sheet-00001a-lines.tif"),
    ("colleen", "dev-truth/colleen/md1887-sheet-00001a-lines.tif"),
    ("caleb-jones", "dev-truth/caleb-jones/md1860-sheet-00001a-lines.tif"),
)
# Preview detection is separate from full-resolution legacy reference extraction.
PREVIEW_SIDE = 2400


def source_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_sheet(path):
    limit = Image.MAX_IMAGE_PIXELS
    try:
        # Only the fixed, authorized development TIFFs reach this loader.
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as opened:
            size = opened.size
            raw_dpi = opened.info.get("dpi")
            dpi = [float(value) for value in raw_dpi] if raw_dpi else None
            picture = opened.convert("L")
    finally:
        Image.MAX_IMAGE_PIXELS = limit
    return picture, size, dpi


def save_regions(picture, regions, directory, prefix):
    preview = picture.convert("RGB")
    preview.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
    ratio = preview.width / picture.width
    crop_source = preview.copy()
    draw = ImageDraw.Draw(preview)
    for index, region in enumerate(regions):
        box = region["region_px"]
        scaled = [round(value * ratio) for value in box]
        draw.rectangle(scaled, outline="red", width=2)
        draw.text((scaled[0] + 2, scaled[1] + 2), f'{index}: {region["label"]}', fill="red")
        crop = crop_source.crop(tuple(scaled))
        crop.thumbnail((1200, 1200))
        crop.save(directory / f'{prefix}-{index}-{region["label"]}.png')
    preview.save(directory / f"{prefix}-overview.png")


def inspect(path, directory, experimental=False):
    picture, size, dpi = load_sheet(path)
    # Intake's survey needs RGB. Detection already decimates to WORK_SIDE;
    # use an exact integer stride first to bound memory on the 240 MP scans.
    step = max(1, int(np.ceil(max(size) / intake.WORK_SIDE)))
    grey = np.asarray(picture)
    small = np.repeat(grey[::step, ::step, None], 3, axis=2)
    regions = intake.survey_page(small)
    for region in regions:
        region["region_px"] = [min(size[i % 2], v * step) for i, v in enumerate(region["region_px"])]
    # Unit scale is deliberate: reference_views does not discover scale and
    # region success is independent of physical units. Do not report it as ppm.
    views = draft_fit.reference_views(grey, regions, 1.0)
    result = {"size_px": size, "dpi": dpi, "legacy_regions": regions,
              "legacy_reference_views": views, "scale_status": "supplied_only_by_legacy_api",
              "source_sha256": source_hash(path),
              "model_calls": 0, "truth_loaded": False, "engineering_approved": False}
    save_regions(picture, regions, directory, "legacy")
    if experimental:
        from vessel_reconstruction.lines_sheet_detection import detect_sheet
        result["experimental"] = detect_sheet(grey, dpi=dpi)
        save_regions(picture, result["experimental"]["regions"], directory, "experimental")
    return result


def check_output_directory(path):
    local_work = Path(__file__).resolve().parents[1] / "work"
    target = path.resolve()
    if not target.is_relative_to(local_work.resolve()):
        raise ValueError("per-sheet evidence must stay under this worktree's local work directory")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--experimental", action="store_true")
    args = parser.parse_args()
    try:
        args.out = check_output_directory(args.out)
    except ValueError as error:
        parser.error(str(error))
    for name, relative in CASES:
        directory = args.out / name
        directory.mkdir(parents=True, exist_ok=True)
        print(f"{name}: starting", flush=True)
        result = inspect(args.work_root / relative, directory, args.experimental)
        (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(f'{name}: reference views {list(result["legacy_reference_views"])}', flush=True)


if __name__ == "__main__":
    main()
