"""Why a particular's box held no ink: numbers only, no image and no printed text.

For each case of a stored GA run (``ga_commercial batch --out``) and each particular in its
stored coarse reply, this prints which attached image the model gave the box on (its view and
size), the box mapped to the source image, whether it lies inside that image, the share of
ink in it at several grey levels, grey-level statistics inside it, and each source image's mode.
It reads the source images to measure them but prints no pixels and no printed values, so an
evaluator can run it on a holdout run and share the output with a development lane.

    PYTHONPATH=src python scripts/ga_ink_diagnostic.py --run RUN --inputs INPUTS [--cases C ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from vessel_reconstruction import ga_commercial_settings, ga_images, ga_interpretation

LEVELS = (160, 200, 230)


def diagnose(case_dir: Path, inputs: Path) -> dict:
    meta = json.loads((case_dir / "request" / "sources.json").read_text())
    reply = (json.loads((case_dir / "provider" / "vision_reading.json").read_text()).get("reply") or {}).get(ga_commercial_settings.PURPOSE)
    tiles = {t["image_id"]: ga_images.Tile(**{**t, "crop_box_px": tuple(t["crop_box_px"])}) for t in meta["tiles"]}
    report = {"sources": {}, "particulars": []}
    grey = {}
    for role, source in meta["sources"].items():
        path = inputs / source["file"]
        image = Image.open(path)
        report["sources"][role] = {"mode": image.mode, "size_px": list(image.size),
                                   "transparency": "transparency" in image.info,
                                   "hash_matches": ga_images._sha256(path.read_bytes()) == source.get("sha256")}
        grey[role] = np.asarray(ga_images.load_grey(path))
    if reply is None:
        report["note"] = "no stored reply"
        return report
    for entry in reply["particulars"]:
        tile = tiles[entry["image_id"]]
        role = tile.source or ("particulars" if tile.view.startswith("particulars_table") and "particulars" in meta["sources"]
                               else "ga")
        box = ga_interpretation._sheet_box(tile, entry["box"])
        height, width = grey[role].shape
        left, top, right, bottom = (int(round(v)) for v in box)
        patch = grey[role][max(0, top):max(0, bottom), max(0, left):max(0, right)]
        row = {"field": entry["field"], "image_id": entry["image_id"], "image_view": tile.view,
               "image_size_px": [tile.width, tile.height], "box_in_image": [round(float(v), 1) for v in entry["box"]],
               "source_role": role, "box_in_source": [round(v, 1) for v in box],
               "inside_source": 0 <= left < right <= width and 0 <= top < bottom <= height}
        if patch.size:
            row["ink_share"] = {str(level): round(float((patch < level).mean()), 4) for level in LEVELS}
            row["grey"] = {"min": int(patch.min()), "p10": int(np.percentile(patch, 10)),
                           "median": int(np.median(patch))}
        report["particulars"].append(row)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--cases", nargs="*")
    args = parser.parse_args(argv)
    out = {}
    for case_dir in sorted(p.parent for p in args.run.glob("*/ga_reading.json")):
        if args.cases and case_dir.name not in args.cases:
            continue
        out[case_dir.name] = diagnose(case_dir, args.inputs)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
