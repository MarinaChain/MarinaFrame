"""Raster path: lines-plan PDF -> provisional section spec for the normal pipeline.

Subcommands:

``measure``  Render the body-plan clip of a PDF page and list long straight
             dark lines (candidate centreline, baseline and grid lines) with
             their pixel positions. The operator (here an assistant) reads the
             calibration from this list and records it in the configuration.
``prepare``  Render the clip, build the composite source image and write the
             provisional ``spec.json``. The composite holds the half to the
             right of the centreline unchanged and the half to the left of the
             centreline mirrored, side by side, so that every station is a
             starboard half-section to the right of its panel centreline. The
             transformation is declared in ``source.transformation``.
``overlay``  Draw the retained contour candidates of a finished task over the composite.

Calibration values, station positions and vertical ranges in the configuration
are assistant-read drawing evidence; the spec says so in every ``evidence`` field.
No vector (DXF) data and no truth data enter this path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

GAP_PX = 40  # white columns between the two composite panels
# Columns kept across the centreline in each panel, so the whole centreline
# stroke and some paper lie inside the panel, as on a single-section drawing.
MARGIN_PX = 40


def render_clip(pdf: Path, page_index: int, clip_pt: list[float], dpi: float) -> np.ndarray:
    import fitz

    with fitz.open(pdf) as document:
        page = document[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=fitz.Rect(*clip_pt), alpha=False)
        array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        return array[:, :, :3].copy()


def long_lines(image: np.ndarray, *, dark: int = 128, min_fraction: float = 0.5) -> dict:
    """Rows and columns whose dark-pixel run covers at least min_fraction of the image."""
    gray = image.mean(axis=2)
    mask = gray < dark

    def longest_run(vector: np.ndarray) -> int:
        padded = np.concatenate([[0], vector.astype(np.int8), [0]])
        changes = np.flatnonzero(np.diff(padded))
        return int((changes[1::2] - changes[0::2]).max()) if len(changes) else 0

    rows = [(r, longest_run(mask[r])) for r in range(mask.shape[0])]
    cols = [(c, longest_run(mask[:, c])) for c in range(mask.shape[1])]
    return {"horizontal": [(r, n) for r, n in rows if n >= min_fraction * mask.shape[1]],
            "vertical": [(c, n) for c, n in cols if n >= min_fraction * mask.shape[0]]}


def compose(image: np.ndarray, centreline_px: float) -> tuple[np.ndarray, dict]:
    """Right half unchanged, then a gap, then the mirrored left half.

    Each panel keeps MARGIN_PX columns from the other side of the centreline.
    """
    cl = int(round(centreline_px))
    start = max(0, cl - MARGIN_PX)
    right = image[:, start:]
    stop = min(image.shape[1], cl + MARGIN_PX + 1)
    left_mirrored = image[:, :stop][:, ::-1]
    gap = np.full((image.shape[0], GAP_PX, 3), 255, dtype=np.uint8)
    composite = np.concatenate([right, gap, left_mirrored], axis=1)
    mirrored_x0 = right.shape[1] + GAP_PX
    layout = {"right_panel": {"x0": 0, "x1": right.shape[1], "centreline_px": centreline_px - start},
              "left_panel_mirrored": {"x0": mirrored_x0, "x1": composite.shape[1],
                                      # original column c maps to mirrored_x0 + (stop - 1 - c)
                                      "centreline_px": mirrored_x0 + (stop - 1 - centreline_px)}}
    return composite, layout


def cmd_measure(config: dict, base: Path, out: Path) -> None:
    from PIL import Image

    image = render_clip(base / config["pdf"], config["page_index"], config["clip_pt"], config["dpi"])
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(out / "clip.png")
    lines = long_lines(image)
    (out / "lines.json").write_text(json.dumps(lines) + "\n")
    print(json.dumps({"size": [image.shape[1], image.shape[0]],
                      "horizontal": lines["horizontal"][:80], "vertical": lines["vertical"][:80]}))


def cmd_prepare(config: dict, base: Path, out: Path) -> None:
    from PIL import Image

    image = render_clip(base / config["pdf"], config["page_index"], config["clip_pt"], config["dpi"])
    cal = config["calibration"]
    composite, layout = compose(image, cal["centreline_px"])
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(composite).save(out / "drawing.png")
    digest = hashlib.sha256((out / "drawing.png").read_bytes()).hexdigest()
    ppm, baseline = cal["pixels_per_metre"], cal["baseline_px"]
    height = composite.shape[0]
    sections = []
    for station in config["stations"]:
        panel = layout["right_panel"] if station["side"] == 1 else layout["left_panel_mirrored"]
        z_min, z_max = config["z_range_m"][str(station["side"])]
        top = int(np.floor(baseline - z_max * ppm)) - 2
        bottom = int(np.ceil(baseline - z_min * ppm)) + 2
        roi = [int(panel["x0"]), max(0, top), int(panel["x1"]), min(height, bottom)]
        sections.append({"id": station["id"], "x_m": station["x_m"], "roi_px": roi,
                         "calibration": {"centerline_px": panel["centreline_px"], "baseline_px": baseline,
                                         "pixels_per_metre": ppm},
                         "z_min_m": z_min, "z_max_m": z_max,
                         "evidence": ("Assistant-read, provisional: station position from the drawing's frame grid; "
                                      "ROI is the whole half body plan on this side; centreline, baseline and scale "
                                      "read from drawn grid lines. " + station.get("evidence", ""))})
    if config.get("plan_corridors") is not None:
        from vessel_reconstruction.plan_corridors import derive_contour_selection

        declared = config["plan_corridors"]
        # Both views are rendered from the very same source PDF and page.
        plan = render_clip(base / config["pdf"], config["page_index"], declared["clip_pt"], config["dpi"])
        records = []
        for section in sections:
            waterlines = declared["waterlines_by_section"].get(section["id"], [])
            if not waterlines:
                records.append({"section_id": section["id"], "anchors": [],
                                "contour_selection": None, "reason": "no_declared_waterlines",
                                "engineering_approved": False})
                continue
            record = derive_contour_selection(plan, section, declared["setup"], waterlines,
                                              half_width_px=declared["half_width_px"])
            records.append(record)
            if record["contour_selection"] is not None:
                section["contour_selection"] = record["contour_selection"]
                section["evidence"] += (" Contour selection is declared evidence from the plan view of the "
                                        "same drawing, never truth; see plan_corridors.json. "
                                        "Identity and calibration remain provisional.")
        report = {"source_sha256": hashlib.sha256((base / config["pdf"]).read_bytes()).hexdigest(),
                  "page_index": config["page_index"], "plan_clip_pt": declared["clip_pt"],
                  "dpi": config["dpi"], "engineering_approved": False, "sections": records}
        (out / "plan_corridors.json").write_text(json.dumps(report, indent=2) + "\n")
    spec = {"schema_version": "1.0", "vessel_id": config["vessel_id"], "units": "m",
            "source": {"file": "drawing.png", "sha256": digest, "license": config["license"],
                       "description": config["description"],
                       "transformation": (f"Rendered PDF page {config['page_index']} clip {config['clip_pt']} pt at "
                                          f"{config['dpi']} dpi; columns right of the centreline unchanged, then "
                                          f"{GAP_PX} white columns, then the columns left of the centreline mirrored; each panel keeps "
                                          f"{MARGIN_PX} columns across the centreline.")},
            "symmetry": "port_starboard",
            "symmetry_evidence": "Body plan draws one half per station; port-starboard symmetry is assumed.",
            "end_closure": "flat_at_terminal_stations", "sections": sections, "components": []}
    (out / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    (out / "layout.json").write_text(json.dumps({**layout, "image_size": [composite.shape[1], height]}, indent=2) + "\n")
    print(json.dumps({"drawing_sha256": digest, "size": [composite.shape[1], height], "sections": len(sections)}))


def cmd_overlay(drawing: Path, task: Path, out_png: Path) -> dict:
    """Draw every retained contour candidate of a finished task over its drawing.

    Candidates come from the task's inspection records (source pixels), so an
    abstained run is inspectable too. Colours cycle per candidate hypothesis.
    """
    from PIL import Image, ImageDraw

    image = Image.open(drawing).convert("RGB")
    draw = ImageDraw.Draw(image)
    colours = [(255, 0, 0), (0, 160, 0), (0, 0, 255), (255, 128, 0), (160, 0, 160)]
    summary = {}
    for record in sorted(task.glob("domain/inspections/*/section-*.json")):
        data = json.loads(record.read_text())
        hypotheses = []
        for index, candidate in enumerate(data.get("candidates", [])):
            points = [tuple(p) for p in candidate.get("source_points_px", [])]
            if len(points) >= 2:
                draw.line(points, fill=colours[index % len(colours)], width=2)
            hypotheses.append(candidate.get("hypothesis"))
        summary[data["section_id"]] = {"candidates": hypotheses,
                                       "retained_competing_count": data.get("retained_competing_count")}
    image.save(out_png)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["measure", "prepare", "overlay"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--drawing", type=Path)
    parser.add_argument("--task", type=Path)
    args = parser.parse_args()
    if args.command == "overlay":
        print(json.dumps(cmd_overlay(args.drawing, args.task, args.out), indent=1))
        return
    config = json.loads(args.config.read_text())
    if args.command == "measure":
        cmd_measure(config, args.config.parent, args.out)
    else:
        cmd_prepare(config, args.config.parent, args.out)


if __name__ == "__main__":
    main()
