"""Add drawing sheets to a run folder (docs/DESKTOP_KIT.md, "Sheets added to a run").

A later stage of some runs reads drawings straight from the drawing set: the R/V Gunnerus
whole-vessel stage read its DXF sheets, so the run itself holds only the lines-plan raster and its
part records name sheets the run does not have. This step renders each listed sheet to a PNG
inside the run (`sources/sheets/`) and writes the record the desktop app reads
(`sources/sheets.json`, app/core/src/sources.rs `ADDED_SHEETS_FILE`). On the sheet marked
`dxf_boxes_view`, each part's "DXF box" (model units, from its outline basis) is stored as a box
in pixels of the picture, so the app can frame that part on the sheet.

The run's own records (state, events, whole_vessel/execution.json) are not changed. Running the
step again replaces the record and the pictures.

    .venv/bin/python scripts/add_run_sheets.py --task RUN --slug gunnerus \
        --sheets-root work/sources/gunnerus [--selection scripts/web_demo_runs.json]

The sheet list (names, SHA-256, roles) is the `extra_sheets` entry of the selection file; a sheet
whose SHA-256 differs is refused. Needs ezdxf and matplotlib (the repository .venv has both).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_demo_sheets import DXF_BOX, SheetError, render_dxf, sha256_of  # noqa: E402

RECORD = "sources/sheets.json"
SHEETS_FOLDER = "sources/sheets"
SCHEMA = "marinaframe.run-sheets.v1"
EXECUTION = "whole_vessel/execution.json"
NOTE = "Read by a later stage straight from the drawing set; shown rendered from its DXF (SHA-256 of the DXF)."


def outline_dxf_box(entry: dict) -> tuple[float, float, float, float] | None:
    """The DXF box of a part's outline, from its provenance in the ship-cad output."""
    for key, record in (entry.get("provenance") or {}).items():
        if key != "outline" and not key.endswith("_outline"):
            continue
        match = DXF_BOX.search(str((record or {}).get("basis") or ""))
        if match:
            return tuple(float(value) for value in match.groups())
    return None


def part_boxes(task: Path, render) -> dict[str, list[float]]:
    """Each part with a DXF box, in pixels of `render`."""
    path = task / EXECUTION
    if not path.is_file():
        return {}
    components = json.loads(path.read_text())["result"].get("components") or []
    boxes = {}
    for entry in components:
        box = outline_dxf_box(entry)
        if box and entry.get("id"):
            boxes[entry["id"]] = render.box_px(box)
    return boxes


def add_sheets(task: Path, sheets_root: Path, listed: list[dict], cache: Path, now_ms: int) -> dict:
    """Render the listed sheets into `task` and write the record. Returns the record."""
    if not (task / "state.json").is_file():
        raise SheetError(f"{task}: not a run folder (no state.json)")
    folder = task / SHEETS_FOLDER
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    sheets = []
    for sheet in listed:
        path = sheets_root / sheet["sheet"]
        if not path.is_file():
            raise SheetError(f"{sheet['sheet']}: not found under {sheets_root}")
        digest = sha256_of(path)
        if digest != sheet["sha256"]:
            raise SheetError(f"{sheet['sheet']}: SHA-256 {digest} is not the listed {sheet['sha256']}")
        render = render_dxf(path, cache)
        file = f"{SHEETS_FOLDER}/{digest[:16]}.png"
        shutil.copyfile(render.png, task / file)
        entry = {
            "name": sheet["sheet"],
            "role": sheet["role"],
            "file": file,
            "sha256": digest,
            "width_px": render.width,
            "height_px": render.height,
            "dxf_extents": list(render.extents),
            "note": NOTE,
            "added_ms": now_ms,
        }
        view = sheet.get("dxf_boxes_view")
        if view:
            entry["part_boxes"] = {"view": view, "boxes": part_boxes(task, render)}
        sheets.append(entry)
    record = {"schema": SCHEMA, "sheets": sheets}
    (task / RECORD).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def listed_sheets(selection: Path, slug: str) -> list[dict]:
    runs = json.loads(selection.read_text())["runs"]
    entry = next((run for run in runs if run["slug"] == slug), None)
    if entry is None or "extra_sheets" not in entry:
        raise SheetError(f"{selection}: no extra_sheets for {slug}")
    return entry["extra_sheets"]["sheets"]


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--sheets-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, default=root / "scripts/web_demo_runs.json")
    parser.add_argument("--cache", type=Path, default=root / "work/web-demo-runs/sheet-cache")
    args = parser.parse_args(argv)
    try:
        record = add_sheets(
            args.task, args.sheets_root, listed_sheets(args.selection, args.slug), args.cache, int(time.time() * 1000)
        )
    except SheetError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    boxes = sum(len(sheet.get("part_boxes", {}).get("boxes", {})) for sheet in record["sheets"])
    print(f"added {len(record['sheets'])} sheets, {boxes} part boxes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
