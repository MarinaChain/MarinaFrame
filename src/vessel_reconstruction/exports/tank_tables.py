"""Capacity plan and sounding tables as CSV files (tank model of ``vessel_reconstruction.tanks``).

Files (``<stem>`` is ``<vessel>_<revision>_DRAFT``):
  <stem>_capacity_plan.csv          one row per tank: volumes at 100 % and 98 %, density, weight,
                                    LCG, TCG, VCG, largest free-surface moment, source labels
  <stem>_sounding_<tank id>.csv     one row per sounding level of that tank

Every file starts with the draft stamp lines (prefixed '#'). Text cells go through
``safe_text_cell``; numbers are written as formatted numbers.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

# The module, not its names: ``tanks`` imports ``exports.hydrostatics``, so this import can run while
# ``tanks`` is still loading.
from .. import tanks as tank_model
from .csv_safety import safe_text_cell
from .source import safe_name

CAPACITY_COLUMNS = (
    ("id", None), ("name", None), ("content", None), ("frames", None), ("built", None),
    ("volume_100_m3", 3), ("volume_98_m3", 3), ("density_t_m3", 3), ("weight_98_t", 3),
    ("lcg_m", 3), ("tcg_m", 3), ("vcg_m", 3), ("max_free_surface_moment_tm", 3), ("printed_volume_m3", 3))
LABEL_KEYS = ("name", "content", "frames", "volume", "density", "centroid")
SOUNDING_COLUMNS = (("sounding_m", 3), ("ullage_m", 3), ("volume_m3", 3), ("fill_pct", 2), ("lcg_m", 3),
                    ("tcg_m", 3), ("vcg_m", 3), ("free_surface_m2", 3), ("i_transverse_m4", 3),
                    ("i_longitudinal_m4", 3))
SOUNDING_NOTE = ("Sounding from the lowest point of the tank, vertical, even keel (sounding pipe position not "
                 "drawn: origin guessed). Ullage = tank height - sounding. Free surface inertias about the "
                 "surface's own centroid.")


def _cell(value, digits):
    if value is None:
        return ""
    if digits is None:
        return safe_text_cell(value)
    return f"{value:.{digits}f}"


def capacity_csv_text(rows: list[dict], stamp_lines: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for line in stamp_lines:
        writer.writerow([f"# {line}"])
    writer.writerow(["# Volumes are moulded volumes of the built tank solids; weight at 98 % fill. "
                     "Source labels: traced (drawing linework), read (printed text), guessed (default)."])
    writer.writerow([name for name, _ in CAPACITY_COLUMNS] + [f"source_{key}" for key in LABEL_KEYS] + ["notes"])
    for row in rows:
        labels = row.get("source_labels") or {}
        writer.writerow([_cell(row.get(name), digits) for name, digits in CAPACITY_COLUMNS]
                        + [safe_text_cell(labels.get(key) or "") for key in LABEL_KEYS]
                        + [safe_text_cell(row.get("notes") or "")])
    return buffer.getvalue()


def sounding_csv_text(tank, rows: list[dict], stamp_lines: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for line in stamp_lines:
        writer.writerow([f"# {line}"])
    writer.writerow([f"# Tank {safe_text_cell(tank.id)}: {safe_text_cell(tank.name)} ({tank.content}). "
                     + SOUNDING_NOTE])
    writer.writerow([name for name, _ in SOUNDING_COLUMNS])
    for row in rows:
        writer.writerow([_cell(row.get(name), digits) for name, digits in SOUNDING_COLUMNS])
    return buffer.getvalue()


def write_tank_tables(tanks: list, out_dir: Path, stem: str, stamp_lines: list[str],
                      interval_m: float | None = None) -> tuple[list[dict], list[tuple[Path, str, dict]]]:
    """Write the capacity plan and one sounding table per built tank (``tanks.Tank`` list).

    Returns the capacity rows and the written files as (path, role, extra) entries.
    """
    interval_m = interval_m or tank_model.SOUNDING_INTERVAL_M
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = tank_model.capacity_plan(tanks)
    capacity = out_dir / f"{stem}_capacity_plan.csv"
    capacity.write_text(capacity_csv_text(rows, stamp_lines), encoding="utf-8")
    entries = [(capacity, "capacity_plan", {"tanks": len(rows)})]
    for tank in tanks:
        if tank.triangles is None:
            continue
        path = out_dir / f"{stem}_sounding_{safe_name(tank.id)}.csv"
        path.write_text(sounding_csv_text(tank, tank_model.sounding_table(tank.triangles, interval_m), stamp_lines),
                        encoding="utf-8")
        entries.append((path, "sounding_table", {"tank": tank.id, "interval_m": interval_m}))
    return rows, entries
