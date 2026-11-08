"""Offsets table: half-breadths at the drawn stations and a set of waterlines.

Half-breadths are read from the built section curves in ``result.json``
(``points_yz_m``, or every piece of a multi-piece section). The half-breadth at
a waterline is the largest |y| where the station curve crosses that height. A
cell is left empty when the station does not reach the waterline (below its
keel or above its top), so an empty cell is never read as zero breadth.

Waterline heights come from the specification (``waterlines_m``) when it
gives them; otherwise ``DEFAULT_WATERLINE_INTERVALS`` equal steps from the
lowest keel point to the highest top point, both ends included.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import io
from pathlib import Path

import numpy as np

DEFAULT_WATERLINE_INTERVALS = 10
# Heights are written to the nearest millimetre.
HEIGHT_DECIMALS = 3
# Half-breadths are written to the nearest millimetre.
BREADTH_DECIMALS = 3


@dataclass(frozen=True)
class OffsetsTable:
    station_ids: list[str]
    x_m: list[float]
    source_labels: list[str]
    keel_z_m: list[float]
    top_z_m: list[float]
    waterlines_m: list[float]
    half_breadths_m: list[list[float | None]]  # [station][waterline]
    waterline_basis: str


def section_curves(section: dict) -> list[np.ndarray]:
    """All (y, z) polylines of a section: its curve, or each piece's outer and inner curve."""
    if "points_yz_m" in section:
        return [np.asarray(section["points_yz_m"], dtype=float)]
    curves = []
    for piece in section.get("pieces", []):
        for key in ("points_yz_m", "inner_points_yz_m"):
            if piece.get(key):
                curves.append(np.asarray(piece[key], dtype=float))
    return curves


def half_breadth_at(curves: list[np.ndarray], z: float) -> float | None:
    """Largest |y| where any curve meets height z (ends included); None when no curve reaches z."""
    widest = None
    for curve in curves:
        if len(curve) < 2:
            continue
        y0, z0, y1, z1 = curve[:-1, 0], curve[:-1, 1], curve[1:, 0], curve[1:, 1]
        low, high = np.minimum(z0, z1), np.maximum(z0, z1)
        hit = (low <= z) & (z <= high)
        if not hit.any():
            continue
        rise = z1[hit] - z0[hit]
        flat = np.abs(rise) < 1e-12
        fraction = np.where(flat, 0.0, (z - z0[hit]) / np.where(flat, 1.0, rise))
        crossing = np.abs(y0[hit] + fraction * (y1[hit] - y0[hit]))
        # A horizontal segment at z lies on the waterline over its whole length.
        candidates = np.concatenate([crossing, np.abs(y1[hit][flat])])
        value = float(candidates.max())
        widest = value if widest is None else max(widest, value)
    return widest


def waterline_heights(sections: list[dict], spec: dict, intervals: int) -> tuple[list[float], str]:
    given = spec.get("waterlines_m")
    if isinstance(given, list) and given and all(isinstance(v, (int, float)) for v in given):
        return sorted(round(float(v), HEIGHT_DECIMALS) for v in given), "specification waterlines_m"
    if intervals < 1:
        raise ValueError("At least one waterline interval is needed.")
    all_z = np.concatenate([c[:, 1] for s in sections for c in section_curves(s) if len(c)])
    keel, top = float(all_z.min()), float(all_z.max())
    heights = [round(keel + (top - keel) * k / intervals, HEIGHT_DECIMALS) for k in range(intervals + 1)]
    return heights, f"{intervals} equal steps from the lowest keel point to the highest top point"


def offsets_table(sections: list[dict], spec: dict | None = None,
                  intervals: int = DEFAULT_WATERLINE_INTERVALS) -> OffsetsTable:
    sections = sorted(sections, key=lambda s: float(s["x_m"]))
    if not sections:
        raise ValueError("The build has no sections.")
    waterlines, basis = waterline_heights(sections, spec or {}, intervals)
    rows, keels, tops = [], [], []
    for section in sections:
        curves = section_curves(section)
        z_values = np.concatenate([c[:, 1] for c in curves]) if curves else np.zeros(1)
        keels.append(round(float(z_values.min()), HEIGHT_DECIMALS))
        tops.append(round(float(z_values.max()), HEIGHT_DECIMALS))
        row = []
        for z in waterlines:
            value = half_breadth_at(curves, z)
            row.append(None if value is None else round(value, BREADTH_DECIMALS))
        rows.append(row)
    return OffsetsTable(station_ids=[str(s["id"]) for s in sections], x_m=[float(s["x_m"]) for s in sections],
                        source_labels=[str(s.get("source_label", "unlabelled")) for s in sections],
                        keel_z_m=keels, top_z_m=tops, waterlines_m=waterlines, half_breadths_m=rows,
                        waterline_basis=basis)


def offsets_csv_text(table: OffsetsTable, stamp_lines: list[str]) -> str:
    """CSV text: stamp and datum lines starting with '#', then one row per station."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for line in stamp_lines:
        writer.writerow([f"# {line}"])
    writer.writerow([f"# Waterlines: {table.waterline_basis}. Empty cell: the station does not reach "
                     "that waterline."])
    header = ["station", "x_m", "source_label", "keel_z_m", "top_z_m"]
    header += [f"hb_at_z_{z:.{HEIGHT_DECIMALS}f}_m" for z in table.waterlines_m]
    writer.writerow(header)
    for index, station in enumerate(table.station_ids):
        cells = ["" if v is None else f"{v:.{BREADTH_DECIMALS}f}" for v in table.half_breadths_m[index]]
        writer.writerow([station, f"{table.x_m[index]:.3f}", table.source_labels[index],
                         f"{table.keel_z_m[index]:.3f}", f"{table.top_z_m[index]:.3f}", *cells])
    return buffer.getvalue()


def write_offsets_csv(table: OffsetsTable, path: Path, stamp_lines: list[str]) -> Path:
    path.write_text(offsets_csv_text(table, stamp_lines), encoding="utf-8")
    return path
