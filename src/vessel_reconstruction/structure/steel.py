"""Steel weight of a structure block: per member, per member group and in total (docs/STRUCTURE_V2.md 6.1).

A member's steel weight is its mid-plane area x thickness x density. The drawings print a steel
grade, not a density, so the density is a labelled guess. The steel table is a draft for weight and
renewal estimates: ``engineering_approved`` stays false.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from ..exports.csv_safety import safe_text_cell

STEEL_DENSITY_T_M3 = 7.85  # carbon and higher-strength hull steel; not printed (guessed)
DRAFT_STAMP = ("DRAFT - not for construction or class submission. engineering_approved=false",
               "Steel weight = mid-plane area x thickness x density; density 7.85 t/m3 (guessed).")

MEMBER_COLUMNS = (("member_id", None), ("label", None), ("group", None), ("area_m2", 4),
                  ("thickness_mm", 2), ("thickness_source", None), ("material", None),
                  ("material_source", None), ("volume_m3", 5), ("weight_t", 4), ("table_row", None),
                  ("placement_sources", None))
GROUP_COLUMNS = (("group_by", None), ("key", None), ("members", None), ("area_m2", 2), ("volume_m3", 4),
                 ("weight_t", 3), ("weight_share", 4))


def member_weights(members: list[dict], density_t_m3: float = STEEL_DENSITY_T_M3) -> list[dict]:
    """One row per member with its steel volume and weight (members without a thickness weigh 0)."""
    rows = []
    for member in members:
        thickness_m = (member["thickness_mm"] or 0.0) / 1000
        # A stiffener gives its own volume (section area x length); a plate is area x thickness.
        volume = member["volume_m3"] if member.get("volume_m3") is not None else member["area_m2"] * thickness_m
        sources = member.get("sources") or {}
        rows.append({**{key: member.get(key) for key, _ in MEMBER_COLUMNS},
                     "volume_m3": volume, "weight_t": volume * density_t_m3,
                     "placement_sources": " ".join(f"{k}={v}" for k, v in sorted(sources.items()))})
    return rows


def weight_totals(rows: list[dict]) -> list[dict]:
    """Totals by scoring label, by group, by thickness source and in all (rows of ``member_weights``)."""
    total_weight = sum(r["weight_t"] for r in rows)
    totals = []
    for group_by in ("label", "group", "thickness_source", "all"):
        buckets: dict[str, list[dict]] = {}
        for row in rows:
            buckets.setdefault("all" if group_by == "all" else str(row[group_by]), []).append(row)
        for key, items in sorted(buckets.items()):
            weight = sum(r["weight_t"] for r in items)
            totals.append({"group_by": group_by, "key": key, "members": len(items),
                           "area_m2": sum(r["area_m2"] for r in items),
                           "volume_m3": sum(r["volume_m3"] for r in items), "weight_t": weight,
                           "weight_share": weight / total_weight if total_weight else 0.0})
    return totals


def _cell(value, digits):
    if value is None:
        return ""
    if digits is None:
        return value if isinstance(value, int) else safe_text_cell(value)
    return f"{value:.{digits}f}"


def _table_text(columns, rows, stamp_lines) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for line in stamp_lines:
        writer.writerow([f"# {line}"])
    writer.writerow([name for name, _ in columns])
    for row in rows:
        writer.writerow([_cell(row.get(name), digits) for name, digits in columns])
    return buffer.getvalue()


def write_steel_tables(block: dict, out_dir: Path, stem: str,
                       density_t_m3: float = STEEL_DENSITY_T_M3) -> dict[str, Path]:
    """Write ``<stem>_steel_members.csv`` and ``<stem>_steel_totals.csv``; return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = member_weights(block["members"], density_t_m3)
    paths = {"members": out_dir / f"{stem}_steel_members.csv", "totals": out_dir / f"{stem}_steel_totals.csv"}
    paths["members"].write_text(_table_text(MEMBER_COLUMNS, rows, DRAFT_STAMP), encoding="utf-8")
    paths["totals"].write_text(_table_text(GROUP_COLUMNS, weight_totals(rows), DRAFT_STAMP), encoding="utf-8")
    return paths
