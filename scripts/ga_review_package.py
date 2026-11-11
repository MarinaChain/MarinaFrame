"""Evidence package for an independent review of GA readings (development ships only).

For each case of a development run folder (``ga_commercial batch --out``) this writes, under a
git-ignored folder:

- up to three view crops (profile, deck plan, tank top / bottom plan) with MarinaFrame's boxes
  drawn on them (blue: label read, orange: best guess, green: the drawn extent of a space
  measured with the frame scale), at most 1,600 px wide;
- ``answers.txt``: the extracted particulars, counts and space labels of the case, per view.

The package is for a development reviewer (a second opinion to investigate, not truth). Never
point this at holdout cases or anything under ``sealed/``.

    python scripts/ga_review_package.py --run RUN_DIR --inputs INPUTS --cases GA-005 ... --out PKG
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw

VIEW_ORDER = ("profile", "deck_plan", "tank_top_plan")
MAX_WIDTH_PX = 1600


def _boxes(result: dict):
    for space in result["spaces"]:
        record = space["source_record"]
        regions = record.get("regions") or record.get("inputs") or []
        for region in regions:
            if region.get("box_px"):
                yield space, region["box_px"], record["kind"]


def answers_text(case: str, result: dict) -> str:
    lines = [f"Case {case}. Ship type: {result['ship_type'].get('value') or 'not read'}."]
    lines.append("Particulars (metres or tonnes; null = not read):")
    for key, item in result["particulars"].items():
        lines.append(f"  {key}: {item.get('value')}" + (f" (printed {item['printed']!r})" if item.get("printed") else ""))
    measured = result.get("measured") or {}
    if measured:
        lines.append("Measured with the drawing's frame scale (not printed values; null = not measured):")
        for key, item in measured.items():
            lines.append(f"  {key}: {item.get('value')} [{item.get('status')}; {(item.get('reason') or '')[:100]}]")
        spans = (result.get("frames") or {}).get("spacings") or []
        if spans:
            lines.append("  frame table: " + ", ".join(f"frames {s['from_frame']}-{s['to_frame']} at {s['spacing_mm']:.0f} mm"
                                                     for s in spans))
    lines.append("Counts (null = abstained, with reason):")
    for key, item in result["counts"].items():
        why = item.get("evidence") or item.get("reason") or ""
        lines.append(f"  {key}: {item.get('value')}  [{why[:120]}]")
    views = {v["view_id"]: f"{v['kind']} {v['title']}".strip() for v in result.get("views", [])}
    lines.append("Spaces listed (view: label [number] status):")
    for space in result["spaces"]:
        extent = space.get("extent") or {}
        where = ""
        if extent:
            where = f" extent frames {extent.get('frames')}"
            for axis in ("x_m", "y_m", "z_m"):
                if extent.get(axis):
                    where += f" {axis[0]} {extent[axis][0]}..{extent[axis][1]} m"
        lines.append(f"  {views.get(space.get('view_id'), 'no view')}: {space['label'] or '(unlabelled)'}"
                     f" [{space['number'] or '-'}] {space['status']} {space['kind']}{where}")
    return "\n".join(lines)


def view_crops(result: dict, sheet: Image.Image) -> list[tuple[str, Image.Image]]:
    marked = sheet.convert("RGB")
    draw = ImageDraw.Draw(marked)
    for space, box, kind in _boxes(result):
        colour = (0, 90, 255) if kind == "read" else (255, 140, 0)
        draw.rectangle(box, outline=colour, width=3)
    for space in result["spaces"]:
        outline = (space.get("extent") or {}).get("outline_box_px")
        if outline:
            draw.rectangle(outline, outline=(0, 160, 60), width=2)
    crops = []
    for wanted in VIEW_ORDER:
        view = next((v for v in result.get("views", []) if v["kind"] == wanted), None)
        if view is None:
            continue
        crop = marked.crop(tuple(int(round(v)) for v in view["box_px"]))
        if crop.width > MAX_WIDTH_PX:
            crop = crop.resize((MAX_WIDTH_PX, round(crop.height * MAX_WIDTH_PX / crop.width)), Image.Resampling.LANCZOS)
        crops.append((f"{wanted}", crop))
    if not crops:  # a sheet without named views: the whole sheet
        crop = marked
        if crop.width > MAX_WIDTH_PX:
            crop = crop.resize((MAX_WIDTH_PX, round(crop.height * MAX_WIDTH_PX / crop.width)), Image.Resampling.LANCZOS)
        crops.append(("sheet", crop))
    return crops


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--cases", required=True, nargs="+")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    index = {}
    for case in args.cases:
        reading = args.run / case / "ga_reading.json"
        if not reading.exists():
            continue
        result = json.loads(reading.read_text())
        ga = result["sources"].get("ga")
        if ga is None:
            continue
        folder = args.out / case
        folder.mkdir(parents=True, exist_ok=True)
        files = []
        for name, crop in view_crops(result, Image.open(args.inputs / ga["file"])):
            path = folder / f"{name}.png"
            crop.save(path)
            files.append(str(path.resolve()))
        (folder / "answers.txt").write_text(answers_text(case, result) + "\n")
        index[case] = {"images": files, "answers": str((folder / "answers.txt").resolve())}
    (args.out / "index.json").write_text(json.dumps(index, indent=2))
    print(json.dumps({"cases": len(index)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
