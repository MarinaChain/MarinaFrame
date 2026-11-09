"""Gunnerus internal plates as structure-block members: IDs, thickness, steel table, OCX (G5).

Development case of docs/STRUCTURE_V2.md section 6 (plan metric G5 in section 4.3.2). The plates are
the internals that ``whole_vessel_internals.build`` already reads and clips to the built hull: tank
tops (double bottom) and main transverse bulkheads. Each becomes a block member with a stable ID,
its hull-clipped area and its thickness with a source label. The Gunnerus drawings print few plate
thicknesses and none is tied to these plates by a leader that this reader follows, so the thickness
is the reader's labelled guess.

    PYTHONPATH=src:. python -m benchmarks.gunnerus.structure_plates --sources work/sources/gunnerus \\
        --assembly work/whole-vessel/final --out work/step2/gunnerus \\
        --ocx-schema work/sources/ocx_schema/ocx/ocx_301
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.gunnerus import whole_vessel_internals as internals
from vessel_reconstruction.structure import ocx, steel
from vessel_reconstruction.tanks import HullSlicer

LABELS = {"deck": "deck", "bulkhead": "transverse_bulkhead"}


def _polygon_area(points) -> float:
    return abs(sum(y0 * z1 - y1 * z0 for (y0, z0), (y1, z1) in zip(points, points[1:] + points[:1]))) / 2


def plate_member(part, thickness_m: float) -> dict:
    """A hull-clipped plate part as a block member: area = steel volume / thickness, box of the slabs."""
    volume = sum((x1 - x0) * _polygon_area(polygon) for x0, x1, polygon in part.slabs)
    xs = [x for x0, x1, _ in part.slabs for x in (x0, x1)]
    ys = [p[0] for _, _, polygon in part.slabs for p in polygon]
    zs = [p[1] for _, _, polygon in part.slabs for p in polygon]
    box = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
    thin = min(range(3), key=lambda i: box[i + 3] - box[i])
    middle = (box[thin] + box[thin + 3]) / 2
    box[thin] = box[thin + 3] = middle  # mid-plane box, as the block members
    sources = dict(part.source_labels)
    return {"member_id": part.id, "label": LABELS[part.op], "group": "transverse" if part.op == "bulkhead"
            else "longitudinal", "box": box, "area_m2": volume / thickness_m,
            "thickness_mm": thickness_m * 1000, "thickness_source": sources.get("thickness", "guessed"),
            "material": None, "material_source": "guessed", "sources": sources, "table_row": None,
            "basis": part.label}


def g5(parts, members: list[dict]) -> dict:
    by_source: dict[str, int] = {}
    for part in parts:
        for value in part.source_labels.values():
            by_source[value] = by_source.get(value, 0) + 1
    built = [p for p in parts if p.slabs]
    return {"parts_built": len(built), "parts_requested": len(parts),
            "parts_built_by_kind": {op: sum(1 for p in built if p.op == op) for op in sorted({p.op for p in parts})},
            "argument_sources": by_source,
            "plates": len(members),
            "plates_with_id_and_thickness": sum(1 for m in members if m["member_id"] and m["thickness_mm"]),
            "plate_thickness_sources": {s: sum(1 for m in members if m["thickness_source"] == s)
                                        for s in sorted({m["thickness_source"] for m in members})}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ocx-schema", type=Path, required=True)
    args = parser.parse_args(argv)
    slicer = HullSlicer(internals.hull_triangles_from_glb(args.assembly / "whole-vessel-draft.glb"))
    parts, _ = internals.build(args.sources, slicer)
    plates = [p for p in parts if p.op in LABELS and p.slabs]
    members = [plate_member(p, internals.PLATE_GUESS_M) for p in plates]
    block = {"engineering_approved": False, "status": "draft_only", "members": members,
             "breadth_m": max(m["box"][4] for m in members), "depth_m": max(m["box"][5] for m in members),
             "stations": {"bulkheads": [m["box"][0] for m in members if m["label"] == "transverse_bulkhead"]}}
    args.out.mkdir(parents=True, exist_ok=True)
    steel.write_steel_tables(block, args.out, "gunnerus_DRAFT")
    path = args.out / "gunnerus_internals_DRAFT.3docx"
    ocx.export_ocx(block, path, name="Gunnerus internals (draft)")
    check = ocx.validate(path, args.ocx_schema)
    rows = steel.member_weights(members)
    report = {"engineering_approved": False, "G5": g5(parts, members),
              "steel_weight_t": round(sum(r["weight_t"] for r in rows), 3),
              "ocx": {"schema_valid": check.valid, "schema_errors": check.errors[:5],
                      "round_trip": ocx.round_trip(block, path)},
              "members": members}
    (args.out / "structure_plates.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "members"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
