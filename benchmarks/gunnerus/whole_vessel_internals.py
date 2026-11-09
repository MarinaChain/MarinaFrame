"""Gunnerus internals (whole-vessel step 2, development case): tank top, bulkheads and tanks.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, section 4 (metrics G1 to G5 in 4.3.2).
Deterministic reading of two vector drawings (no model call):

- Construction plan, longitudinal section: baseline, frame axis, tank-top levels with their
  x extents ("TANKTOP 1250 AB.BL" labels on their lines), 1-deck level, bulkhead lines.
- Tank arrangement: frame axis, tank table (number, name, frame range, net volume), tank
  outlines in the "below tank top" and "below 1-deck" plans, bulkhead lines in the profile.

Parts are clipped to the built hull by slicing its display mesh (no CAD Boolean: on this hull
one Boolean took minutes). Every part is a draft: ``engineering_approved`` is false.

Usage (outputs are drawing derivatives: keep them in a git-ignored folder)::

    PYTHONPATH=src:. python -m benchmarks.gunnerus.whole_vessel_internals \\
        --sources work/sources/gunnerus --assembly work/whole-vessel/final \\
        --out work/whole-vessel/internals-001 [--truth-mesh <truth dir>/truth_mesh.npz]
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shutil
import statistics
import time

import numpy as np

from vessel_reconstruction.ship_measure import read_dxf

LONG_SECTION = 'extended/CJOB/Construction Plan Longitudinal Section Rev0.dxf'
TANK_PLAN = 'extended/CJOB/Tank Arrangement Rev0.dxf'

# The drawings are in millimetres at full size.
MM = 1000.0
FRAME_SPACING_MM = 500.0  # title block "FRAME DISTANCE 500 [mm]"
# The lengthened midbody has lettered frames A to J between frames 27 and 28.
FRAME_LETTERS = 'ABCDEFGHIJ'
# Frame-axis labels are on one text row; a row with this many numbered frames is the axis.
MIN_AXIS_LABELS = 12
# Host calibration (a person read these windows from the sheets, as in step 1; not geometry).
# Windows are DXF millimetres [x0, y0, x1, y1].
LONG_SECTION_WINDOW = (105000, 88000, 150000, 104000)
TANK_PROFILE_WINDOW = (2000, 30000, 42000, 36000)
TANK_TOP_PLAN_WINDOW = (2000, 6500, 42000, 17200)
DECK_PLAN_WINDOW = (2000, 17200, 42000, 28500)
# Boundary layers of the tank plans (outlines and tank boundaries). The phantom layer S0PH1
# holds the tank cross marks and the centre-line layer S0CE1 the axes: both are left out.
PLAN_LAYERS = ('S0CO1', 'S0CO3', 'S0CO5', 'S0DA1')
STRUCTURE_LAYERS = ('S0CO1', 'S0CO3', 'S0CO5')
# A bulkhead line in a profile reaches the deck within this distance and is at least this long.
DECK_REACH_MM = 250.0
MIN_BULKHEAD_MM = 1500.0
# A main bulkhead's foot lies at most this high above the base (a deck-to-platform wall is not one).
MAX_FOOT_MM = 2000.0
BULKHEAD_CLUSTER_MM = 150.0
# A plan region larger than this is a room, not a tank (the largest tank in the table is 42 m3).
MAX_TANK_PLAN_M2 = 30.0
# Raster cell of the plan region reader (mm).
PLAN_PIXEL_MM = 20.0
# Slicing steps of the hull clip (m): x step of the slab solids and the volume integral, z row.
SLAB_M = 0.25
VOLUME_DX_M = 0.05
ROW_DZ_M = 0.01
# Row step of the slab outlines (display and STEP solids; the volume integral uses ROW_DZ_M).
OUTLINE_DZ_M = 0.05
# Gap fills (source "guessed"): plate thickness where no plate label is read.
PLATE_GUESS_M = 0.010


@dataclass
class Part:
    id: str
    op: str
    label: str
    slabs: list[tuple[float, float, list[list[float]]]]  # (x0, x1, polygon [[y, z], ...])
    source_labels: dict[str, str]
    provenance: dict[str, dict]
    geometry: dict
    volume_m3: float = 0.0
    notes: list[str] = field(default_factory=list)


# --- frame axis -------------------------------------------------------------------------

def frame_index(label: str) -> int | None:
    """Frame number to an index of 500 mm steps from frame 0 (letters after frame 27)."""
    label = label.strip()
    if label in FRAME_LETTERS and label:
        return 27 + FRAME_LETTERS.index(label) + 1
    if re.fullmatch(r'-?\d{1,2}', label):
        number = int(label)
        return number if number <= 27 else number + len(FRAME_LETTERS)
    return None


def frame_x_m(label: str) -> float | None:
    index = frame_index(label)
    return None if index is None else index * FRAME_SPACING_MM / MM


def _texts(path: Path, window) -> list[tuple[float, float, str]]:
    import ezdxf

    def walk(entities, depth=0):
        # The frame axis is a block: its labels are texts inside an INSERT.
        for entity in entities:
            if entity.dxftype() == 'INSERT' and depth < 2:
                try:
                    yield from walk(entity.virtual_entities(), depth + 1)
                except (ValueError, TypeError, AttributeError):
                    continue
            elif entity.dxftype() in ('TEXT', 'MTEXT'):
                yield entity

    x0, y0, x1, y1 = window
    found = []
    for entity in walk(ezdxf.readfile(path).modelspace()):
        text = entity.plain_text() if entity.dxftype() == 'MTEXT' else entity.dxf.text
        point = entity.dxf.insert
        if x0 <= point.x <= x1 and y0 <= point.y <= y1:
            found.append((float(point.x), float(point.y), ' '.join(text.split())))
    return found


def calibrate_frames(texts, grid_lines_x: list[float]) -> float:
    """DXF x of frame 0.

    The axis labels give frame 0 to within a label width; the structure lines lie on the frame
    grid. The frame-0 line is the grid line (phase = the most common x mod 500 of the lines)
    nearest to the label estimate.
    """
    rows: dict[int, list[tuple[float, int]]] = {}
    for x, y, text in texts:
        index = frame_index(text)
        if index is not None and not text.isalpha():
            rows.setdefault(round(y / 100), []).append((x, index))
    axis = max(rows.values(), key=len)
    if len(axis) < MIN_AXIS_LABELS:
        raise ValueError('no frame axis found')
    estimate = statistics.median(x - index * FRAME_SPACING_MM for x, index in axis)
    phases = np.round(np.mod(grid_lines_x, FRAME_SPACING_MM)).astype(int)
    values, counts = np.unique(phases, return_counts=True)
    phase = float(values[np.argmax(counts)])
    base = estimate - np.mod(estimate - phase, FRAME_SPACING_MM)
    return float(min((base, base + FRAME_SPACING_MM), key=lambda v: abs(v - estimate)))


def _segments(entities, window, layers, orientation: str, min_length: float):
    """Straight horizontal ('h') or vertical ('v') pieces of polylines inside a window."""
    x0, y0, x1, y1 = window
    found = []
    for entity in entities:
        if entity['layer'] not in layers:
            continue
        points = entity['points']
        for a, b in zip(points, points[1:]):
            if not (x0 <= min(a[0], b[0]) and max(a[0], b[0]) <= x1 and y0 <= min(a[1], b[1])
                    and max(a[1], b[1]) <= y1):
                continue
            if orientation == 'h' and abs(a[1] - b[1]) < 2 and abs(a[0] - b[0]) >= min_length:
                found.append((a[1], min(a[0], b[0]), max(a[0], b[0]), entity['id']))
            if orientation == 'v' and abs(a[0] - b[0]) < 2 and abs(a[1] - b[1]) >= min_length:
                found.append((a[0], min(a[1], b[1]), max(a[1], b[1]), entity['id']))
    return found


# --- longitudinal section ------------------------------------------------------------------

@dataclass
class LongSection:
    frame0_x: float
    baseline_y: float
    deck_z_m: float
    tank_tops: list[dict]  # {'z_m', 'x_m': [x0, x1], 'evidence'}
    bulkheads_x_m: list[float]


def read_long_section(path: Path) -> LongSection:
    entities = read_dxf(path)
    texts = _texts(path, LONG_SECTION_WINDOW)
    verticals = _segments(entities, LONG_SECTION_WINDOW, ('S0CO5',), 'v', MIN_BULKHEAD_MM)
    frame0 = calibrate_frames(texts, [v[0] for v in verticals])
    # Baseline: the longest horizontal line at the height of the "BASELINE" label.
    base_label = next(t for t in texts if t[2].upper() == 'BASELINE')
    horizontals = _segments(entities, LONG_SECTION_WINDOW, ('S0PH1',) + STRUCTURE_LAYERS, 'h', 800)
    near = [h for h in horizontals if abs(h[0] - base_label[1]) < 300]
    baseline = max(near, key=lambda h: h[2] - h[1])[0]
    levels = {}
    for x, y, text in texts:
        match = re.search(r'(?:(TANKTOP)\s+)?(\d{3,5})\s*AB\.?BL', text.upper())
        if match:
            levels.setdefault('tanktop' if match.group(1) else 'level', []).append((x, int(match.group(2))))
    deck_label = next(t for t in texts if t[2].upper() == '1-DECK')
    deck_mm = min((v for x, v in levels.get('level', [])), key=lambda v: abs(baseline + v - deck_label[1]))
    tank_tops = []
    for x_label, value in levels.get('tanktop', []):
        lines = [h for h in horizontals if abs(h[0] - (baseline + value)) < 15]
        for y, xa, xb, handle in lines:
            tank_tops.append({'z_m': value / MM, 'x_m': [(xa - frame0) / MM, (xb - frame0) / MM],
                              'evidence': f'line {handle} at the "TANKTOP {value} AB.BL" level'})
    tank_tops = _merge_runs(tank_tops)
    deck_y = baseline + deck_mm
    bulkheads = [x for x, _ in bulkhead_lines(verticals, frame0, deck_y, deck_mm)]
    return LongSection(frame0, baseline, deck_mm / MM, tank_tops, bulkheads)


def bulkhead_lines(verticals, frame0_x: float, deck_y: float, deck_mm: float) -> list[tuple[float, str]]:
    """Main transverse bulkheads: vertical lines from low in the hull up to (or through) the deck.

    A line counts when its foot is at most MAX_FOOT_MM above the base and its top reaches the
    deck level. Lines closer than BULKHEAD_CLUSTER_MM are one bulkhead.
    """
    found: list[tuple[float, str]] = []
    for x, low, high, handle in sorted(verticals):
        if low > deck_y - deck_mm + MAX_FOOT_MM or high < deck_y - DECK_REACH_MM:
            continue
        x_m = round((x - frame0_x) / MM, 3)
        if found and x_m - found[-1][0] < BULKHEAD_CLUSTER_MM / MM:
            continue
        found.append((x_m, handle))
    return found


def _merge_runs(tops: list[dict]) -> list[dict]:
    """Join collinear tank-top pieces at one level that touch (gap < 0.1 m)."""
    merged: list[dict] = []
    for top in sorted(tops, key=lambda t: (t['z_m'], t['x_m'][0])):
        last = merged[-1] if merged else None
        if last and last['z_m'] == top['z_m'] and top['x_m'][0] <= last['x_m'][1] + 0.1:
            last['x_m'][1] = max(last['x_m'][1], top['x_m'][1])
            last['evidence'] += '; ' + top['evidence']
        else:
            merged.append({**top, 'x_m': list(top['x_m'])})
    return merged


def tank_top_at(section: LongSection, x: float) -> float | None:
    for top in section.tank_tops:
        if top['x_m'][0] - 1e-6 <= x <= top['x_m'][1] + 1e-6:
            return top['z_m']
    return None


# --- tank arrangement -----------------------------------------------------------------------

@dataclass
class TankRow:
    number: str | None
    name: str
    frames: tuple[str, str]
    volume_m3: float | None


def read_tank_table(texts) -> list[TankRow]:
    """Rows of the tank table: number, name, 'a...b' frame range, net volume (columns by x)."""
    header = {t[2]: (t[0], t[1]) for t in texts if t[2] in ('No', 'Name', 'Net volume, m³')}
    range_header = next(t for t in texts if t[2].startswith('Area of location'))
    if len(header) < 3:
        raise ValueError('tank table header not found')
    columns = {'no': header['No'][0], 'name': header['Name'][0], 'range': range_header[0],
               'volume': header['Net volume, m³'][0]}
    lines: dict[int, dict[str, str]] = {}
    for x, y, text in texts:
        if y >= header['No'][1] - 100:
            continue
        for key, cx in columns.items():
            if abs(x - cx) < 200:
                lines.setdefault(round(y / 50), {})[key] = text
    rows = []
    for cells in lines.values():
        if cells.get('name', '').startswith('Total'):
            continue
        match = re.fullmatch(r'(\w+)\.\.\.(\w+)', cells.get('range', ''))
        if not match or 'name' not in cells:
            continue
        volume = cells.get('volume')
        rows.append(TankRow(cells.get('no'), cells['name'].strip(), (match.group(1), match.group(2)),
                            float(volume) if volume and re.fullmatch(r'\d+\.\d+', volume) else None))
    return rows


@dataclass
class PlanView:
    window: tuple
    frame0_x: float
    centre_y: float
    mask: np.ndarray  # True = ink
    labels: np.ndarray  # region label per pixel (0 = ink)

    def to_pixel(self, x_dxf: float, y_dxf: float) -> tuple[int, int]:
        return (int((y_dxf - self.window[1]) / PLAN_PIXEL_MM), int((x_dxf - self.window[0]) / PLAN_PIXEL_MM))

    def region_columns(self, region: int, side: int | None = None) -> dict[float, tuple[float, float]]:
        """Ship x (m) of each pixel column of a region -> (y min, y max) in ship metres.

        ``side`` +1 keeps the port half (y > 0), -1 the starboard half, None the whole region.
        """
        mask = self.labels == region
        if side is not None:
            centre_row = (self.centre_y - self.window[1]) / PLAN_PIXEL_MM
            rows_index = np.arange(mask.shape[0])[:, None]
            mask &= (rows_index >= centre_row) if side > 0 else (rows_index < centre_row)
        rows, cols = np.nonzero(mask)
        spans = {}
        for col in np.unique(cols):
            ys = rows[cols == col]
            x_dxf = self.window[0] + (col + 0.5) * PLAN_PIXEL_MM
            y0 = self.window[1] + ys.min() * PLAN_PIXEL_MM
            y1 = self.window[1] + (ys.max() + 1) * PLAN_PIXEL_MM
            spans[(x_dxf - self.frame0_x) / MM] = ((y0 - self.centre_y) / MM, (y1 - self.centre_y) / MM)
        return spans


def plan_view(entities, window, frame0_x: float) -> PlanView:
    import cv2

    x0, y0, x1, y1 = window
    width, height = int((x1 - x0) / PLAN_PIXEL_MM) + 1, int((y1 - y0) / PLAN_PIXEL_MM) + 1
    ink = np.zeros((height, width), np.uint8)
    outline_y = []
    for entity in entities:
        if entity['layer'] not in PLAN_LAYERS:
            continue
        points = np.array(entity['points'])
        if not (points[:, 0].min() >= x0 and points[:, 0].max() <= x1 and points[:, 1].min() >= y0
                and points[:, 1].max() <= y1):
            continue
        pixels = np.column_stack([(points[:, 0] - x0) / PLAN_PIXEL_MM, (points[:, 1] - y0) / PLAN_PIXEL_MM])
        cv2.polylines(ink, [np.round(pixels).astype(np.int32)], False, 1, 2)
        if entity['layer'] == 'S0CO5' and np.ptp(points[:, 0]) > 4000:
            outline_y.extend([points[:, 1].min(), points[:, 1].max()])
    # The hull outline is symmetric: the centre line lies midway between its extreme y.
    centre = (min(outline_y) + max(outline_y)) / 2
    count, labels = cv2.connectedComponents((ink == 0).astype(np.uint8), connectivity=4)
    return PlanView(window, frame0_x, centre, ink.astype(bool), labels)


def _normal(text: str) -> str:
    return ' '.join(text.lower().replace('grey', 'gray').split())


def label_matches(text: str, row: TankRow) -> bool:
    """A plan label names a table row: its number ("No 11sb FO" names "No 11sb"), or its name."""
    text = _normal(text)
    if row.number and (text == _normal(row.number) or text.startswith(_normal(row.number) + ' ')):
        return True
    name = _normal(row.name)
    # "Cargo hold" names "Cargo hold aft"; "New Fuel Oil tank" names "New fuel oil tank".
    return text == name or (len(text) >= 8 and name.startswith(text)) or (
        not row.number and text.startswith(name[:12]))


def tank_regions(view: PlanView, texts, rows: list[TankRow]) -> dict[int, tuple[int, str, int | None]]:
    """Table row index -> (plan region, label text, side) for rows whose label lies in a region.

    A region that holds the labels of a port and a starboard tank is split at the centre line
    (side +1 port, -1 starboard; None: whole region). A region open to the sheet edge or larger
    than MAX_TANK_PLAN_M2 is not a tank (the linework leaks into a room).
    """
    found: dict[int, tuple[int, str, int | None]] = {}
    label_y: dict[int, float] = {}
    border = set(np.unique(np.concatenate([view.labels[0], view.labels[-1], view.labels[:, 0],
                                           view.labels[:, -1]])))
    pixel_m2 = (PLAN_PIXEL_MM / MM) ** 2
    for index, row in enumerate(rows):
        for x, y, text in texts:
            if not label_matches(text, row):
                continue
            r, c = view.to_pixel(x + 150, y + 100)  # a point inside the first characters
            if not (0 <= r < view.labels.shape[0] and 0 <= c < view.labels.shape[1]):
                continue
            region = int(view.labels[r, c])
            if not region or region in border or (view.labels == region).sum() * pixel_m2 > MAX_TANK_PLAN_M2:
                continue
            side = 1 if y > view.centre_y else -1
            owner = next((i for i, v in found.items() if v[0] == region), None)
            if owner is None:
                found[index] = (region, text, None)
                label_y[index] = y
                break
            if found[owner][2] is None and (1 if label_y[owner] > view.centre_y else -1) != side:
                found[owner] = (found[owner][0], found[owner][1], -side)
                found[index] = (region, text, side)
                break
    return found


def profile_bulkheads(entities, frame0_x: float, deck_level_y: float, deck_mm: float) -> list[tuple[float, str]]:
    verticals = _segments(entities, TANK_PROFILE_WINDOW, ('S0CO3',), 'v', MIN_BULKHEAD_MM)
    return bulkhead_lines(verticals, frame0_x, deck_level_y, deck_mm)


# --- hull clip --------------------------------------------------------------------------

class HullSlicer:
    """Cross-sections of a closed triangle mesh (metres) by planes x = const."""

    def __init__(self, triangles: np.ndarray):
        self.t = triangles
        self.xmin = triangles[:, :, 0].min(axis=1)
        self.xmax = triangles[:, :, 0].max(axis=1)

    def segments(self, x: float) -> np.ndarray:
        """Section segments [[y0, z0], [y1, z1]] at x."""
        tri = self.t[(self.xmin <= x) & (self.xmax >= x)]
        # Nudge vertices that lie exactly on the plane so each crossing edge is counted once.
        d = tri[:, :, 0] - x
        d = np.where(d == 0, 1e-9, d)
        crossings, points = [], []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            cross = (d[:, i] * d[:, j]) < 0
            t = np.where(cross, d[:, i] / np.where(cross, d[:, i] - d[:, j], 1), 0)
            crossings.append(cross)
            points.append(tri[:, i, 1:] + t[:, None] * (tri[:, j, 1:] - tri[:, i, 1:]))
        crossings = np.stack(crossings, axis=1)  # (n, 3)
        points = np.stack(points, axis=1)  # (n, 3, 2)
        two = crossings.sum(axis=1) == 2
        order = np.argsort(~crossings[two], axis=1, kind='stable')[:, :2]
        return np.take_along_axis(points[two], order[:, :, None], axis=1)

    def intervals(self, x: float, zs: np.ndarray) -> list[list[tuple[float, float]]]:
        """Inside y-intervals of the section at x for each z (even-odd rule)."""
        segs = self.segments(x)
        result = []
        for z in zs:
            if len(segs) == 0:
                result.append([])
                continue
            z0, z1 = segs[:, 0, 1], segs[:, 1, 1]
            hit = (np.minimum(z0, z1) <= z) & (np.maximum(z0, z1) > z)
            s = segs[hit]
            t = (z - s[:, 0, 1]) / (s[:, 1, 1] - s[:, 0, 1])
            ys = np.sort(s[:, 0, 0] + t * (s[:, 1, 0] - s[:, 0, 0]))
            result.append([(float(ys[i]), float(ys[i + 1])) for i in range(0, len(ys) - 1, 2)])
        return result


def clipped_area_and_outline(slicer: HullSlicer, x: float, y_range, z_range, dz: float = ROW_DZ_M):
    """Area of (hull section at x) inside the y and z ranges, and its outline polygon [[y, z]]."""
    height = z_range[1] - z_range[0]
    if height <= 0:
        return 0.0, None
    # Equal rows over the range (a thin plate is one row).
    rows = max(1, int(np.ceil(height / dz - 1e-9)))
    step = height / rows
    zs = z_range[0] + (np.arange(rows) + 0.5) * step
    left, right, area = [], [], 0.0
    for z, intervals in zip(zs, slicer.intervals(x, zs)):
        pieces = [(max(a, y_range[0]), min(b, y_range[1])) for a, b in intervals]
        pieces = [p for p in pieces if p[1] > p[0]]
        if not pieces:
            continue
        area += sum(b - a for a, b in pieces) * step
        left.append([min(p[0] for p in pieces), float(z)])
        right.append([max(p[1] for p in pieces), float(z)])
    if not left:
        return area, None
    # Close the outline at the row ends so the solid spans the whole z range of its rows.
    bottom, top = left[0][1] - step / 2, left[-1][1] + step / 2
    outline = ([[left[0][0], bottom]] + left + [[left[-1][0], top], [right[-1][0], top]]
               + right[::-1] + [[right[0][0], bottom]])
    return area, outline


def slab_part(slicer: HullSlicer, x_range, y_of_x, z_of_x, slab: float = SLAB_M):
    """Volume (integral at VOLUME_DX_M) and slab polygons of the hull inside the given ranges."""
    volume = 0.0
    for x in np.arange(x_range[0] + VOLUME_DX_M / 2, x_range[1], VOLUME_DX_M):
        y_range, z_range = y_of_x(x), z_of_x(x)
        if y_range and z_range:
            volume += clipped_area_and_outline(slicer, x, y_range, z_range)[0] * VOLUME_DX_M
    slabs = []
    edges = list(np.arange(x_range[0], x_range[1], slab)) + [x_range[1]]
    for xa, xb in zip(edges, edges[1:]):
        if xb - xa < 1e-3:
            continue
        xm = (xa + xb) / 2
        y_range, z_range = y_of_x(xm), z_of_x(xm)
        if not (y_range and z_range):
            continue
        _, outline = clipped_area_and_outline(slicer, xm, y_range, z_range, dz=OUTLINE_DZ_M)
        if outline:
            slabs.append((float(xa), float(xb), outline))
    return volume, slabs


def plate_part(slicer: HullSlicer, x: float, z_range, thickness: float):
    """A transverse plate at x: the hull section between z_range, thickness centred on x."""
    _, outline = clipped_area_and_outline(slicer, x, (-50.0, 50.0), z_range, dz=OUTLINE_DZ_M)
    return [(x - thickness / 2, x + thickness / 2, outline)] if outline else []


def hull_triangles_from_glb(path: Path) -> np.ndarray:
    import trimesh

    scene = trimesh.load(path, force='scene')
    for name, geometry in scene.geometry.items():
        if name == 'hull':
            v = np.asarray(geometry.vertices)
            # glTF Y-up (x, z, -y) back to the ship frame (x, y, z), millimetres to metres.
            ship = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]]) / MM
            return ship[np.asarray(geometry.faces)]
    raise ValueError(f'{path}: no hull node')


# --- build -----------------------------------------------------------------------------

def build(sources: Path, slicer: HullSlicer) -> tuple[list[Part], dict]:
    long_path, tank_path = sources / LONG_SECTION, sources / TANK_PLAN
    section = read_long_section(long_path)
    tank_entities = read_dxf(tank_path)
    tank_texts = _texts(tank_path, (0, 0, 80000, 60000))
    grid = [v[0] for v in _segments(tank_entities, TANK_TOP_PLAN_WINDOW, ('S0CO3',), 'v', 1000)]
    frame0 = calibrate_frames([t for t in tank_texts if TANK_TOP_PLAN_WINDOW[1] <= t[1] <= TANK_TOP_PLAN_WINDOW[3]],
                              grid)
    table = read_tank_table(tank_texts)
    reading = {'long_section': {'frame0_dxf_x': section.frame0_x, 'baseline_dxf_y': section.baseline_y,
                                'deck_z_m': section.deck_z_m, 'tank_tops': section.tank_tops,
                                'bulkheads_x_m': section.bulkheads_x_m},
               'tank_plan': {'frame0_dxf_x': frame0, 'table_rows': len(table)}}
    parts: list[Part] = []

    # Tank top (inner bottom) plates: one per level run.
    for number, top in enumerate(section.tank_tops):
        z = top['z_m']
        x0, x1 = top['x_m']
        _, slabs = slab_part(slicer, (x0, x1), lambda x: (-50.0, 50.0), lambda x: (z - PLATE_GUESS_M, z))
        parts.append(Part(
            f'tank_top_{number + 1}', 'deck', f'Tank top (double bottom) at {z:.2f} m, x {x0:.1f} to {x1:.1f} m',
            slabs, {'level': 'traced', 'extent': 'traced', 'thickness': 'guessed'},
            {'level': {'source': 'traced', 'basis': top['evidence']},
             'extent': {'source': 'traced', 'basis': 'line ends in the longitudinal section; breadth from the hull'},
             'thickness': {'source': 'guessed', 'basis': f'plate {PLATE_GUESS_M * 1000:.0f} mm (no plate label read)'}},
            {'level': z, 'extent': [x0, x1], 'thickness': PLATE_GUESS_M}))

    # Main transverse bulkheads from the tank-arrangement profile.
    deck_line = max((h for h in _segments(tank_entities, TANK_PROFILE_WINDOW, ('S0CO3',), 'h', 4000)),
                    key=lambda h: h[2] - h[1])[0]
    bulkheads = profile_bulkheads(tank_entities, frame0, deck_line, section.deck_z_m * MM)
    reading['tank_plan']['profile_bulkheads_x_m'] = [x for x, _ in bulkheads]
    for x, handle in bulkheads:
        slabs = plate_part(slicer, x, (-1.0, section.deck_z_m), PLATE_GUESS_M)
        parts.append(Part(
            f'bulkhead_x{x:05.1f}'.replace('.', '_'), 'bulkhead', f'Transverse bulkhead at x {x:.2f} m',
            slabs, {'position': 'traced', 'extent': 'traced', 'thickness': 'guessed'},
            {'position': {'source': 'traced', 'basis': f'profile line {handle} (tank arrangement), to the deck'},
             'extent': {'source': 'traced', 'basis': 'built hull section from the base to the 1-deck'},
             'thickness': {'source': 'guessed', 'basis': f'plate {PLATE_GUESS_M * 1000:.0f} mm'}},
            {'position': x, 'deck_z': section.deck_z_m, 'thickness': PLATE_GUESS_M}))

    # Tanks: double-bottom tanks in the plan below the tank top; the others below the 1-deck.
    views = {'below_tank_top': plan_view(tank_entities, TANK_TOP_PLAN_WINDOW, frame0),
             'below_1_deck': plan_view(tank_entities, DECK_PLAN_WINDOW, frame0)}
    placed: dict[int, tuple[str, int, str, int | None]] = {}
    for key in ('below_tank_top', 'below_1_deck'):
        window = TANK_TOP_PLAN_WINDOW if key == 'below_tank_top' else DECK_PLAN_WINDOW
        texts = [t for t in tank_texts if window[0] <= t[0] <= window[2] and window[1] <= t[1] <= window[3]]
        for index, (region, text, side) in tank_regions(views[key], texts, table).items():
            placed.setdefault(index, (key, region, text, side))
    reading['tank_plan']['tanks_placed'] = len(placed)
    used_ids = set()
    for index, row in enumerate(table):
        identity = re.sub(r'\W+', '_', (row.number or row.name).lower()).strip('_')
        while identity in used_ids:
            identity += '_2'
        used_ids.add(identity)
        if index not in placed:
            parts.append(Part(f'tank_{identity}', 'tank', f'{row.number or ""} {row.name}'.strip(),
                              [], {}, {}, {'table_frames': list(row.frames), 'table_volume_m3': row.volume_m3},
                              notes=['no enclosed plan region holds its label: not built']))
            continue
        key, region, text, side = placed[index]
        spans = views[key].region_columns(region, side)
        xs = np.array(sorted(spans))
        x_range = (float(xs.min()) - PLAN_PIXEL_MM / MM / 2, float(xs.max()) + PLAN_PIXEL_MM / MM / 2)

        def y_of_x(x, spans=spans, xs=xs):
            nearest = xs[np.argmin(np.abs(xs - x))]
            return spans[float(nearest)] if abs(nearest - x) <= PLAN_PIXEL_MM / MM else None

        if key == 'below_tank_top':
            def z_of_x(x):
                top = tank_top_at(section, x)
                return (-1.0, top) if top else None
            z_basis = 'from the hull bottom to the tank top of the longitudinal section'
            z_source = 'traced'
        else:
            def z_of_x(x):
                return (tank_top_at(section, x) or -1.0, section.deck_z_m)
            z_basis = 'from the tank top (or the hull bottom) to the 1-deck level; the tank height is not drawn'
            z_source = 'guessed'
        volume, slabs = slab_part(slicer, x_range, y_of_x, z_of_x)
        parts.append(Part(
            f'tank_{identity}', 'tank', f'{row.number or ""} {row.name}'.strip().strip(),
            slabs, {'outline': 'traced', 'height': z_source},
            {'outline': {'source': 'traced', 'basis': f'enclosed region at the label "{text}" in the {key} plan'},
             'height': {'source': z_source, 'basis': z_basis}},
            {'x_m': [round(x_range[0], 3), round(x_range[1], 3)], 'plan': key,
             'table_frames': list(row.frames), 'table_volume_m3': row.volume_m3},
            volume_m3=volume))
    return parts, reading


# --- export -----------------------------------------------------------------------------

def part_solid(part: Part):
    import cadquery as cq

    solids = []
    for x0, x1, outline in part.slabs:
        points = [(x0 * MM, y * MM, z * MM) for y, z in outline]
        wire = cq.Wire.makePolygon([cq.Vector(*p) for p in points], close=True)
        face = cq.Face.makeFromWires(wire)
        solids.append(cq.Solid.extrudeLinear(face, cq.Vector((x1 - x0) * MM, 0, 0)))
    return cq.Compound.makeCompound(solids) if solids else None


def component_entry(part: Part, solid) -> dict:
    built = solid is not None
    guessed = any(v == 'guessed' for v in part.source_labels.values())
    box = None
    volume = None
    if built:
        bb = solid.BoundingBox()
        box = {'min': [bb.xmin / MM, bb.ymin / MM, bb.zmin / MM], 'max': [bb.xmax / MM, bb.ymax / MM, bb.zmax / MM]}
        volume = part.volume_m3 if part.op == 'tank' else abs(solid.Volume()) / MM ** 3
    return {'id': part.id, 'op': part.op, 'kind': 'structure', 'label': part.label,
            'status': 'draft_guess' if guessed or not built else 'measured_draft', 'built': built,
            'reason': '; '.join(part.notes) or ('internal part from the construction plans and the tank '
                                                'arrangement; clipped to the built hull'),
            'source': {'view': 'plan' if part.op == 'tank' else 'profile', 'region': part.id,
                       'method': 'construction_plan_reader'},
            'source_labels': part.source_labels, 'provenance': part.provenance,
            'args': {name: f'{part.id}_{name}' for name in part.source_labels},
            'geometry': part.geometry, 'bbox_m': box, 'volume_m3': volume,
            'engineering_approved': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--assembly', type=Path, required=True, help='step 1 assembly folder (whole_vessel/, GLB)')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--truth-mesh', type=Path, help='truth_mesh.npz for the containment metric G4')
    args = parser.parse_args()
    import cadquery as cq

    from vessel_reconstruction.display_mesh import shape_mesh, write_glb

    started = time.time()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    glb = args.assembly / 'whole-vessel-draft.glb'
    slicer = HullSlicer(hull_triangles_from_glb(glb))
    parts, reading = build(args.sources, slicer)
    folder = out / 'whole_vessel'
    shutil.copytree(args.assembly / 'whole_vessel', folder)
    record = json.loads((folder / 'execution.json').read_text())
    components = [c for c in record['result']['components'] if c.get('kind') != 'structure']
    meshes = {}
    for part in parts:
        solid = part_solid(part)
        if solid is not None:
            cq.exporters.export(cq.Workplane().add(solid), str(folder / f'{part.id}.step'), exportType='STEP')
            meshes[part.id] = shape_mesh(solid, 1.0, 0.5)
        components.append(component_entry(part, solid))
    record['result']['components'] = components
    (folder / 'execution.json').write_text(json.dumps(record, indent=2) + '\n')
    write_glb_with_existing(glb, meshes, out / 'whole-vessel-draft.glb')
    summary = {'engineering_approved': False, 'status': 'draft_only', 'reading': reading,
               'parts': [component_entry(p, None) | {'built': bool(p.slabs), 'volume_m3': p.volume_m3}
                         for p in parts], 'seconds': time.time() - started}
    if args.truth_mesh:
        from benchmarks.gunnerus.whole_vessel_internals_metrics import score
        summary['metrics'] = score(parts, reading, np.load(args.truth_mesh)['triangles'])
    (out / 'internals.json').write_text(json.dumps(summary, indent=2, default=str) + '\n')
    print(json.dumps(summary.get('metrics', {}), indent=2, default=str))


def write_glb_with_existing(existing: Path, meshes: dict, path: Path) -> None:
    """The step 1 GLB with one more node per internal part (same Y-up, millimetres)."""
    import trimesh

    scene = trimesh.load(existing, force='scene')
    for name, (vertices, triangles) in meshes.items():
        y_up = np.column_stack([vertices[:, 0], vertices[:, 2], -vertices[:, 1]])
        scene.add_geometry(trimesh.Trimesh(vertices=y_up, faces=triangles, process=False),
                           node_name=name, geom_name=name)
    path.write_bytes(scene.export(file_type='glb', include_normals=True))


if __name__ == '__main__':
    main()
