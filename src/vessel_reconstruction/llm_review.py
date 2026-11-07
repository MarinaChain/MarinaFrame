"""Station overlays for the vision-model veto reviewer (W12).

The Rust controller runs ``python -m vessel_reconstruction.llm_review render --run RUN --out DIR``
at finalization when a task asked for the model review. For every section of the
verified run, this module writes one image:

- left half: the source drawing crop around the section region;
- right half: the same crop with the cut of the exported STEP at that station drawn
  over it as a thin magenta line, projected with the section's own calibration
  (centreline column, baseline row, pixels per metre).

Only the starboard hull side of the cut is drawn. The flat top closure that the
engine adds (a modelling assumption, not a drawn line) is left out, so that the
model compares only lines that the drawing can show.

The images are evidence for a model that can only veto. Nothing here measures,
scores or approves the candidate. The manifest binds every image to the STEP hash.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

IMAGES_VERSION = "marinaframe.review_images.v1"
MAGENTA = (230, 0, 200)
# Pixels of context kept around the declared section region.
CROP_MARGIN_PX = 24
GAP_PX = 16
# The provider accepts at most 1,048,576 pixels and 1 MiB per image.
MAX_PIXELS = 1_000_000
MAX_BYTES = 900_000
MAX_SIDE_PX = 2000
# Cut points closer than this to the centreline belong to the centreline
# closure of the solid, not to the drawn hull side (metres).
CENTRELINE_EPSILON_M = 1e-4
# A cut segment within this height of the section top and horizontal is the
# top closure (metres).
TOP_CLOSURE_TOLERANCE_M = 1e-3
# Colours of the overlay image; a small palette keeps PNG files below the byte limit.
PALETTE_COLOURS = 48


def _starboard_segments(edges, top_z_m: float):
    """Cut edges as (y, z) metre segments on the starboard side, without the top closure."""
    import numpy as np
    segments = []
    for edge in edges:
        points, _ = edge.sample(2 if edge.geomType() == "LINE" else 24)
        yz = np.array([[p.y / 1000, p.z / 1000] for p in points])
        for a, b in zip(yz[:-1], yz[1:]):
            if a[0] < CENTRELINE_EPSILON_M and b[0] < CENTRELINE_EPSILON_M:
                continue
            flat_top = (abs(a[1] - b[1]) < TOP_CLOSURE_TOLERANCE_M
                        and min(a[1], b[1]) > top_z_m - TOP_CLOSURE_TOLERANCE_M)
            if flat_top:
                continue
            segments.append((a, b))
    return segments


def _fit(image, max_pixels: int):
    from PIL import Image
    width, height = image.size
    scale = min(1.0, (max_pixels / (width * height)) ** 0.5, MAX_SIDE_PX / max(width, height))
    if scale < 1.0:
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)
    return image


def _encode(image, path: Path) -> None:
    """Write a palette PNG below the byte limit, shrinking if needed."""
    from PIL import Image
    budget = MAX_PIXELS
    while True:
        fitted = _fit(image, budget)
        fitted.convert("P", palette=Image.ADAPTIVE, colors=PALETTE_COLOURS).save(path, optimize=True)
        if path.stat().st_size <= MAX_BYTES:
            return
        budget = int(budget * 0.7)
        if budget < 40_000:
            raise ValueError("Review image cannot meet the byte limit.")


def station_image(source, section: dict, edges, top_z_m: float):
    """The side-by-side review image of one section and its crop box in source pixels."""
    from PIL import Image, ImageDraw
    calibration = section["evidence"]["calibration"]
    roi = section["evidence"]["roi_px"]
    left = max(0, int(roi[0]) - CROP_MARGIN_PX)
    top = max(0, int(roi[1]) - CROP_MARGIN_PX)
    right = min(source.width, int(roi[2]) + CROP_MARGIN_PX)
    bottom = min(source.height, int(roi[3]) + CROP_MARGIN_PX)
    crop = source.crop((left, top, right, bottom)).convert("RGB")
    overlay = crop.copy()
    draw = ImageDraw.Draw(overlay)
    ppm = float(calibration["pixels_per_metre"])
    centre, base = float(calibration["centerline_px"]), float(calibration["baseline_px"])

    def project(point):
        return (centre + point[0] * ppm - left, base - point[1] * ppm - top)

    for a, b in _starboard_segments(edges, top_z_m):
        draw.line([project(a), project(b)], fill=MAGENTA, width=2)
    width, height = crop.size
    canvas = Image.new("RGB", (2 * width + GAP_PX, height), (255, 255, 255))
    canvas.paste(crop, (0, 0))
    canvas.paste(overlay, (width + GAP_PX, 0))
    return canvas, [left, top, right, bottom]


def render(run: Path, out: Path) -> dict:
    from PIL import Image
    from .agent_render_worker import _cut_edges, _reimport
    from .provenance import digest_file, safe_relative_file, write_json
    shape, record, audit = _reimport(run)
    regions = "region_loft" in record["metrics"]
    source_entry = record["sources"][0]
    source_path = safe_relative_file(run, source_entry["file"])
    if digest_file(source_path) != source_entry["sha256"]:
        raise ValueError("Captured source changed.")
    out.mkdir(parents=True, exist_ok=False)
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    images = []
    for index, section in enumerate(record["sections"]):
        if "points_yz_m" not in section:
            continue  # multi-piece sections have no single drawn line to compare
        x_m = float(section["x_m"])
        top_z_m = max(float(p[1]) for p in section["points_yz_m"])
        edges = _cut_edges(shape, x_m, regions)
        canvas, box = station_image(source, section, edges, top_z_m)
        name = f"station-{index:03d}.png"
        _encode(canvas, out / name)
        with Image.open(out / name) as written:
            width, height = written.size
        images.append({"review_id": f"s{index:03d}", "section_id": section["id"], "x_m": x_m, "file": name,
                       "sha256": digest_file(out / name), "bytes": (out / name).stat().st_size,
                       "width": width, "height": height, "crop_box_px": box})
    manifest = {"schema_version": IMAGES_VERSION, "step_sha256": audit["step_sha256"],
                "source_sha256": source_entry["sha256"], "engineering_approved": False, "images": images}
    write_json(out / "manifest.json", manifest)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("render", help="write station overlay images and their manifest")
    command.add_argument("--run", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = render(args.run, args.out)
    print(json.dumps({"images": len(manifest["images"]), "step_sha256": manifest["step_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
