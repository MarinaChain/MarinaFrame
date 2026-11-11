"""Scantling statistics per ship type and cell: built blocks against the BOM (plan section 3).

Reads the block JSON files written by ``benchmarks.steel_t3.run`` and the BOM of each design.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.steel_t3.scantlings --label baseline

Plates: thickness in whole mm, by count and by area. Stiffener webs: profile
``web height (10 mm bins) x thickness (mm)``. Flanges: ``width (10 mm bins) x thickness (mm)``.
Each distribution is compared by total variation distance (TVD, 0 = equal, 1 = disjoint).
Output (git-ignored): ``work/steel-t3/<label>/scantlings.json`` and a Markdown summary.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import statistics
import sys

from .run import OUT, SAMPLE, loose_file

PLATE_LABELS = {"bottom_shell", "side_shell", "shell_strake", "deck", "longitudinal_bulkhead", "hopper_plate",
                "transverse_bulkhead", "floor", "bracket"}
HEIGHT_BIN_MM = 10  # web height and flange width bins


def _bin(metres: float) -> int:
    return int(round(metres * 1000 / HEIGHT_BIN_MM) * HEIGHT_BIN_MM)


def _mm(value: float | None) -> int | None:
    return None if value is None else int(round(value))


def bom_scantlings(subset: str, design: int) -> dict:
    """BOM rows split into plates, stiffener webs and flanges (thickness in metres in the BOM)."""
    plates, plate_area, webs, flanges, missing = Counter(), Counter(), Counter(), Counter(), 0
    with open(loose_file(subset, design, "Structural_Elements.csv"), newline="") as handle:
        for row in csv.DictReader(handle):
            if not row["Thickness"]:
                missing += 1
                continue
            thickness = _mm(float(row["Thickness"]) * 1000)
            if row["Type"] != "Stiffener":
                plates[thickness] += 1
                plate_area[thickness] += float(row["area_pannel"] or 0.0)
            elif row["Class"] == "Stiffener_Flange":
                flanges[f"{_bin(float(row['L2']))}x{thickness}"] += 1
            else:
                webs[f"{_bin(float(row['L2']))}x{thickness}"] += 1
    return {"plates": plates, "plate_area": plate_area, "webs": webs, "flanges": flanges, "missing": missing}


def block_scantlings(block: dict) -> dict:
    """Built members split the same way. Web height: printed table row, else the section extent."""
    rows = block["printed"]["rows"]
    plates, plate_area, webs, flanges, missing = Counter(), Counter(), Counter(), Counter(), 0
    for member in block["members"]:
        thickness = _mm(member["thickness_mm"])
        if thickness is None:
            missing += 1
            continue
        label = member["label"]
        x0, y0, z0, x1, y1, z1 = member["box"]
        row = rows.get(member["table_row"] or "")
        if label in PLATE_LABELS:
            plates[thickness] += 1
            plate_area[thickness] += member["area_m2"]
        elif label == "flange":
            width = row["width_m"] if row and row.get("width_m") else max(y1 - y0, z1 - z0, x1 - x0)
            flanges[f"{_bin(width)}x{thickness}"] += 1
        else:
            height = row["height_m"] if row and row.get("height_m") else max(y1 - y0, z1 - z0)
            webs[f"{_bin(height)}x{thickness}"] += 1
    return {"plates": plates, "plate_area": plate_area, "webs": webs, "flanges": flanges, "missing": missing}


def tvd(a: Counter, b: Counter) -> float | None:
    total_a, total_b = sum(a.values()), sum(b.values())
    if not total_a or not total_b:
        return None
    return round(0.5 * sum(abs(a[k] / total_a - b[k] / total_b) for k in set(a) | set(b)), 4)


def _median_key(counts: Counter) -> float | None:
    values = [k for k, n in counts.items() for _ in range(int(n))]
    return statistics.median(values) if values else None


def compare(pred: dict, true: dict) -> dict:
    return {
        "plates": {"n_pred": sum(pred["plates"].values()), "n_bom": sum(true["plates"].values()),
                   "tvd_count": tvd(pred["plates"], true["plates"]),
                   "tvd_area": tvd(pred["plate_area"], true["plate_area"]),
                   "median_mm_pred": _median_key(pred["plates"]), "median_mm_bom": _median_key(true["plates"]),
                   "top_pred": pred["plates"].most_common(5), "top_bom": true["plates"].most_common(5)},
        "webs": {"n_pred": sum(pred["webs"].values()), "n_bom": sum(true["webs"].values()),
                 "tvd": tvd(pred["webs"], true["webs"]),
                 "top_pred": pred["webs"].most_common(5), "top_bom": true["webs"].most_common(5)},
        "flanges": {"n_pred": sum(pred["flanges"].values()), "n_bom": sum(true["flanges"].values()),
                    "tvd": tvd(pred["flanges"], true["flanges"]),
                    "top_pred": pred["flanges"].most_common(5), "top_bom": true["flanges"].most_common(5)},
        "missing_thickness": {"pred": pred["missing"], "bom": true["missing"]},
    }


def _add(total: dict, part: dict) -> None:
    for key in ("plates", "plate_area", "webs", "flanges"):
        total[key].update(part[key])
    total["missing"] += part["missing"]


def _empty() -> dict:
    return {"plates": Counter(), "plate_area": Counter(), "webs": Counter(), "flanges": Counter(), "missing": 0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    args = parser.parse_args(argv)
    blocks = OUT / args.label / "blocks"
    groups: dict[str, tuple[dict, dict, int]] = {}
    no_block = []
    for (subset, ship_type), designs in SAMPLE.items():
        for design in designs:
            path = blocks / f"{subset}_{design}.json"
            if not path.exists():
                no_block.append(f"{subset}/{design}")
                continue
            pred = block_scantlings(json.loads(path.read_text()))
            true = bom_scantlings(subset, design)
            for key in (f"{subset}/{ship_type}", f"type/{ship_type}", "all"):
                p, t, n = groups.setdefault(key, (_empty(), _empty(), 0))
                _add(p, pred)
                _add(t, true)
                groups[key] = (p, t, n + 1)
    report = {"engineering_approved": False, "label": args.label,
              "units": {"thickness": "mm (whole)", "web_height_and_flange_width": f"mm ({HEIGHT_BIN_MM} mm bins)",
                        "plate_area": "m2", "counts": "members (built) or BOM rows"},
              "designs_without_block": no_block,
              "groups": {key: {"n_designs": n, **compare(p, t)} for key, (p, t, n) in sorted(groups.items())}}
    out = OUT / args.label / "scantlings.json"
    out.write_text(json.dumps(report, indent=1))
    lines = ["| Group | Designs | Plate TVD count / area | Plate median mm built / BOM | Web TVD | Flange TVD |",
             "|---|---|---|---|---|---|"]
    for key, item in report["groups"].items():
        p = item["plates"]
        lines.append(f"| {key} | {item['n_designs']} | {p['tvd_count']} / {p['tvd_area']} | "
                     f"{p['median_mm_pred']} / {p['median_mm_bom']} | {item['webs']['tvd']} | {item['flanges']['tvd']} |")
    (OUT / args.label / "scantlings.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"-> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
