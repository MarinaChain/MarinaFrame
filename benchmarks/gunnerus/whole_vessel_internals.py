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

from vessel_reconstruction import tanks
from vessel_reconstruction.ship_measure import read_dxf
from vessel_reconstruction.tanks import HullSlicer, clipped_outline, tank_slabs_in_hull

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
# Slab steps of the hull clip (m). The tank mesh for volumes and sounding tables uses fine slabs
# (0.10 m in x, rows of 0.02 m); the STEP and GLB solids (and G4) use 0.25 m slabs with rows of
# 0.05 m, as before (fine STEP solids took 33 min and 419 MB on Gunnerus). Plates: one slab.
TANK_SLAB_M = 0.10
TANK_ROW_DZ_M = 0.02
SLAB_M = 0.25
OUTLINE_DZ_M = 0.05
# Phantom cross marks (two diagonals from corner to corner) bound a tank in the plans (layer
# S0PH1). A diagonal spans at least CROSS_MIN_MM in x and y; the
# two diagonals of one cross share their x ends within CROSS_TOL_MM.
PLAN_CROSS_LAYERS = ('S0PH1',)
CROSS_MIN_MM = 200.0
CROSS_TOL_MM = 30.0
# Text width per character as a share of the text height (label centre estimate).
CHAR_WIDTH_SHARE = 0.6
# A gap between two tank-top runs at one level that is shorter than this is bridged (a centre-line
# trunk or opening in the longitudinal section; the tanks beside it keep the level).
MAX_TANK_TOP_GAP_M = 3.0
# Profile lines that can be a tank or hold floor: horizontal, at least this long, and at least
# DECK_CLEARANCE_MM below the 1-deck line.
PROFILE_FLOOR_LAYERS = ('S0CO1', 'S0CO3')
MIN_FLOOR_MM = 500.0
DECK_CLEARANCE_MM = 300.0
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
    triangles: np.ndarray | None = None  # closed tank mesh (tanks only)


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


def label_anchors(path: Path, window) -> list[tuple[float, float, str]]:
    """Plan labels at the estimated middle of their first line (x, y, text).

    A TEXT insert is the left end of the baseline; an MTEXT insert with attachment 1 is the top
    left corner. The width is estimated from the character count and the text height.
    """
    import ezdxf

    x0, y0, x1, y1 = window
    found = []
    for entity in ezdxf.readfile(path).modelspace():
        kind = entity.dxftype()
        if kind not in ('TEXT', 'MTEXT'):
            continue
        text = entity.plain_text() if kind == 'MTEXT' else entity.dxf.text
        point = entity.dxf.insert
        if not (x0 <= point.x <= x1 and y0 <= point.y <= y1):
            continue
        height = entity.dxf.char_height if kind == 'MTEXT' else entity.dxf.height
        first_line = text.splitlines()[0].strip() if text.strip() else ''
        middle_x = point.x + CHAR_WIDTH_SHARE * height * len(first_line) / 2
        top_left = kind == 'MTEXT' and entity.dxf.get('attachment_point', 1) == 1
        middle_y = point.y - height / 2 if top_left else point.y + height / 2
        found.append((float(middle_x), float(middle_y), ' '.join(text.split())))
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
                              'evidence': f'line {handle} at the "TANKTOP {value} AB.BL" level',
                              'source': 'traced'})
    tank_tops = bridge_tank_top_gaps(_merge_runs(tank_tops))
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


def bridge_tank_top_gaps(tops: list[dict]) -> list[dict]:
    """Add a run (source "guessed") over a short gap between two runs at the same level.

    The longitudinal section is cut on the centre line; a centre-line trunk (on Gunnerus the
    HIPAP unit, x 26.5 to 29.0 m) interrupts the tank-top line there, not beside it.
    """
    ordered = sorted(tops, key=lambda t: t['x_m'][0])
    bridged = list(ordered)
    for left, right in zip(ordered, ordered[1:]):
        gap = right['x_m'][0] - left['x_m'][1]
        if left['z_m'] == right['z_m'] and 1e-3 < gap <= MAX_TANK_TOP_GAP_M:
            bridged.append({'z_m': left['z_m'], 'x_m': [left['x_m'][1], right['x_m'][0]], 'source': 'guessed',
                            'evidence': f'gap of {gap:.2f} m between two runs at {left["z_m"]:.2f} m (centre-line '
                                        'opening); level of both neighbours'})
    return sorted(bridged, key=lambda t: t['x_m'][0])


def tank_top_run(section: LongSection, x: float) -> dict | None:
    for top in section.tank_tops:
        if top['x_m'][0] - 1e-6 <= x <= top['x_m'][1] + 1e-6:
            return top
    return None


def tank_top_at(section: LongSection, x: float) -> float | None:
    run = tank_top_run(section, x)
    return run['z_m'] if run else None


# --- tank arrangement -----------------------------------------------------------------------

@dataclass
class TankRow:
    number: str | None
    name: str
    frames: tuple[str, str]
    volume_m3: float | None
    group: str | None = None  # content group from the table section header
    density_t_m3: float | None = None  # printed in the group header, or printed mass / volume
    mass_t: float | None = None


# Table section headers -> content groups of the capacity plan.
GROUP_WORDS = (('ballast', 'water ballast'), ('fresh water', 'fresh water'), ('fuel oil', 'fuel oil'),
               ('misc', 'misc'), ('dry', 'dry'))


def _number(text: str | None) -> float | None:
    return float(text) if text and re.fullmatch(r'\d+\.\d+', text.strip()) else None


def _table_lines(texts) -> list[dict[str, str]]:
    """Cells of the tank table by row (top to bottom); columns by the header x."""
    header = {t[2]: (t[0], t[1]) for t in texts if t[2] in ('No', 'Name', 'Net volume, m³', 'Mass, t')}
    range_header = next((t for t in texts if t[2].startswith('Area of location')), None)
    if len({'No', 'Name', 'Net volume, m³'} & set(header)) < 3 or range_header is None:
        raise ValueError('tank table header not found')
    columns = {'no': header['No'][0], 'name': header['Name'][0], 'range': range_header[0],
               'volume': header['Net volume, m³'][0]}
    if 'Mass, t' in header:
        columns['mass'] = header['Mass, t'][0]
    lines: dict[int, dict[str, str]] = {}
    for x, y, text in texts:
        if y >= header['No'][1] - 100:
            continue
        for key, cx in columns.items():
            if abs(x - cx) < 200:
                lines.setdefault(round(y / 50), {})[key] = text
    return [lines[key] for key in sorted(lines, reverse=True)]


def _group_of(header: str) -> str | None:
    lower = header.lower()
    return next((group for word, group in GROUP_WORDS if word in lower), None)


def read_tank_table(texts) -> list[TankRow]:
    """Rows of the tank table: number, name, 'a...b' frame range, net volume, mass, and the
    content group and density from the section header above the row ("FUEL OIL TANKS ρ = 0.83")."""
    rows, group, density = [], None, None
    for cells in _table_lines(texts):
        name = cells.get('name', '').strip()
        match = re.fullmatch(r'(\w+)\.\.\.(\w+)', cells.get('range', ''))
        if not match and 'no' in cells and not name:
            group = _group_of(cells['no'])
            printed = re.search(r'ρ\s*=\s*(\d+(?:\.\d+)?)', cells['no'])
            density = float(printed.group(1)) if printed else None
            continue
        if name.startswith('Total') or not match or not name:
            continue
        volume, mass = _number(cells.get('volume')), _number(cells.get('mass'))
        row_density = density if density is not None else (round(mass / volume, 3) if mass and volume else None)
        rows.append(TankRow(cells.get('no'), name, (match.group(1), match.group(2)), volume, group,
                            row_density, mass))
    return rows


def read_table_totals(texts) -> dict[str, dict]:
    """Printed group totals ("Total fuel oil": volume and mass) by content group."""
    totals, group = {}, None
    for cells in _table_lines(texts):
        name = cells.get('name', '').strip()
        if 'no' in cells and not name and not cells.get('range'):
            group = _group_of(cells['no'])
        elif name.startswith('Total') and group:
            totals[group] = {'volume_m3': _number(cells.get('volume')), 'mass_t': _number(cells.get('mass'))}
    return totals


@dataclass
class PlanView:
    window: tuple
    frame0_x: float
    centre_y: float
    mask: np.ndarray  # True = ink
    labels: np.ndarray  # region label per pixel (0 = ink)

    def to_pixel(self, x_dxf: float, y_dxf: float) -> tuple[int, int]:
        return (int((y_dxf - self.window[1]) / PLAN_PIXEL_MM), int((x_dxf - self.window[0]) / PLAN_PIXEL_MM))

    def side_mask(self, side: int | None) -> np.ndarray:
        """+1 keeps the port half (y > 0), -1 the starboard half, None the whole view."""
        rows_index = np.arange(self.labels.shape[0])[:, None] * np.ones((1, self.labels.shape[1]), bool)
        if side is None:
            return np.ones(self.labels.shape, bool)
        centre_row = (self.centre_y - self.window[1]) / PLAN_PIXEL_MM
        return (rows_index >= centre_row) if side > 0 else (rows_index < centre_row)

    def box_mask(self, box) -> np.ndarray:
        """Pixels inside a DXF box (x0, y0, x1, y1)."""
        r0, c0 = self.to_pixel(box[0], box[1])
        r1, c1 = self.to_pixel(box[2], box[3])
        mask = np.zeros(self.labels.shape, bool)
        mask[max(r0, 0):max(r1, 0), max(c0, 0):max(c1, 0)] = True
        return mask

    def mask_columns(self, mask: np.ndarray) -> dict[float, tuple[float, float]]:
        """Ship x (m) of each pixel column of a mask -> (y min, y max) in ship metres."""
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


def label_match_quality(text: str, row: TankRow) -> int:
    """How well a plan label names a table row: 2 full number or name, 1 shortened name, 0 none.

    "No 11sb FO" names "No 11sb"; "Cargo hold" names "Cargo hold aft"; "Grey water New" names
    "Gray water new". A full match wins over a shortened one ("Black water" is No 7sb, not
    "Black water new").
    """
    text = _normal(text)
    if row.number and (text == _normal(row.number) or text.startswith(_normal(row.number) + ' ')):
        return 2
    name = _normal(row.name)
    if text == name:
        return 2
    if (len(text) >= 8 and name.startswith(text)) or (not row.number and text.startswith(name[:12])):
        return 1
    return 0


def label_matches(text: str, row: TankRow) -> bool:
    return label_match_quality(text, row) > 0


def cross_boxes(entities, window, layers=PLAN_CROSS_LAYERS) -> list[tuple[float, float, float, float, bool]]:
    """Boxes (x0, y0, x1, y1, rectangular) of phantom cross marks: two diagonals with opposite
    slopes and the same x ends. A tank plan draws one cross per tank from corner to corner.

    Rectangular: both diagonals span the same y range, so the box is the tank plan (the hull clip
    trims any part outside the hull). Otherwise a corner lies on a curved side; the box is the union
    of both diagonals and only bounds the region at the label."""
    x_lo, y_lo, x_hi, y_hi = window
    diagonals = []
    for entity in entities:
        if entity['layer'] not in layers:
            continue
        for a, b in zip(entity['points'], entity['points'][1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            if abs(dx) < CROSS_MIN_MM or abs(dy) < CROSS_MIN_MM:
                continue
            if not (x_lo <= min(a[0], b[0]) and max(a[0], b[0]) <= x_hi and y_lo <= min(a[1], b[1])
                    and max(a[1], b[1]) <= y_hi):
                continue
            diagonals.append((min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]),
                              np.sign(dx * dy)))
    boxes = set()
    for i, first in enumerate(diagonals):
        for second in diagonals[i + 1:]:
            same_ends = abs(first[0] - second[0]) < CROSS_TOL_MM and abs(first[1] - second[1]) < CROSS_TOL_MM
            overlap = min(first[3], second[3]) - max(first[2], second[2]) > CROSS_MIN_MM
            if same_ends and overlap and first[4] != second[4]:
                rectangular = abs(first[2] - second[2]) < CROSS_TOL_MM and abs(first[3] - second[3]) < CROSS_TOL_MM
                boxes.add((round(min(first[0], second[0])), round(min(first[2], second[2])),
                           round(max(first[1], second[1])), round(max(first[3], second[3])), rectangular))
    return sorted(boxes)


def _smallest_box_at(boxes, x: float, y: float):
    inside = [b for b in boxes if b[0] <= x <= b[2] and b[1] <= y <= b[3]]
    return min(inside, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if inside else None


@dataclass
class TankPlace:
    """Where a table row lies in one plan: region at its label, side, and its cross box."""
    region: int | None  # enclosed region (None: the region leaks or is a room)
    text: str
    side: int | None = None  # set when a region holds a port and a starboard tank
    box: tuple | None = None

    def mask(self, view: PlanView) -> np.ndarray:
        use_region = self.region and not (self.box is not None and self.box[4])
        mask = view.labels == self.region if use_region else np.ones(view.labels.shape, bool)
        mask = mask & view.side_mask(self.side)
        if self.box is not None:
            mask &= view.box_mask(self.box)
        return mask

    def basis(self, plan: str) -> str:
        parts = []
        rectangular = self.box is not None and self.box[4]
        if self.region and not rectangular:
            parts.append(f'enclosed region at the label "{self.text}" in the {plan} plan')
        if self.box is not None:
            kind = 'rectangular cross mark' if rectangular else 'cross mark'
            parts.append(f'inside its {kind} at the label "{self.text}" (DXF box {self.box[:4]})')
        return '; '.join(parts)


def tank_regions(view: PlanView, texts, rows: list[TankRow], boxes=()) -> dict[int, TankPlace]:
    """Table row index -> place for rows whose label lies in a region or a cross mark.

    A label inside a cross mark takes the region at the label cut to the cross box, or the box
    alone when the region is not a tank. Otherwise a region that holds the labels of a port and a
    starboard tank is split at the centre line. A region open to the sheet edge or larger than
    MAX_TANK_PLAN_M2 is not a tank (the linework leaks into a room).
    """
    found: dict[int, TankPlace] = {}
    label_y: dict[int, float] = {}
    border = set(np.unique(np.concatenate([view.labels[0], view.labels[-1], view.labels[:, 0],
                                           view.labels[:, -1]])))
    pixel_m2 = (PLAN_PIXEL_MM / MM) ** 2
    for index, row in enumerate(rows):
        candidates = sorted(((label_match_quality(t[2], row), t) for t in texts), key=lambda c: -c[0])
        for quality, (x, y, text) in candidates:
            if quality == 0:
                break
            r, c = view.to_pixel(x, y)
            if not (0 <= r < view.labels.shape[0] and 0 <= c < view.labels.shape[1]):
                continue
            region = int(view.labels[r, c])
            if not region or region in border or (view.labels == region).sum() * pixel_m2 > MAX_TANK_PLAN_M2:
                region = None
            box = _smallest_box_at(boxes, x, y)
            if box is not None:
                found[index] = TankPlace(region, text, None, box)
                break
            if region is None:
                continue
            side = 1 if y > view.centre_y else -1
            owner = next((i for i, v in found.items() if v.region == region and v.box is None), None)
            if owner is None:
                found[index] = TankPlace(region, text)
                label_y[index] = y
                break
            if found[owner].side is None and (1 if label_y[owner] > view.centre_y else -1) != side:
                found[owner].side = -side
                found[index] = TankPlace(region, text, side)
                break
    return found


def profile_bulkheads(entities, frame0_x: float, deck_level_y: float, deck_mm: float) -> list[tuple[float, str]]:
    verticals = _segments(entities, TANK_PROFILE_WINDOW, ('S0CO3',), 'v', MIN_BULKHEAD_MM)
    return bulkhead_lines(verticals, frame0_x, deck_level_y, deck_mm)


@dataclass
class Profile:
    """Tank-arrangement profile (centre line): 1-deck runs and horizontal floor lines (DXF mm)."""
    frame0_x: float
    deck_runs: list[tuple[float, float, float]]  # (x0, x1, y)
    floors: list[tuple[float, float, float, str]]  # (y, x0, x1, handle)

    @property
    def main_deck_y(self) -> float:
        return max(self.deck_runs, key=lambda r: r[1] - r[0])[2]

    def deck_y(self, x_dxf: float) -> float:
        covering = [r for r in self.deck_runs if r[0] <= x_dxf <= r[1]]
        return covering[0][2] if covering else self.main_deck_y

    def floor_z(self, x_m: float, deck_z_m: float) -> float | None:
        """Height (m above base) of the highest floor line under the 1-deck at ship x.

        The profile is measured from its own 1-deck line at the same x and placed under the deck
        level of the longitudinal section (the two drawings share the deck, not their baselines).
        """
        x_dxf = self.frame0_x + x_m * MM
        deck_y = self.deck_y(x_dxf)
        candidates = [y for y, x0, x1, _ in self.floors
                      if x0 <= x_dxf <= x1 and deck_y - deck_z_m * MM <= y <= deck_y - DECK_CLEARANCE_MM]
        return deck_z_m - (deck_y - max(candidates)) / MM if candidates else None


def read_profile(entities, frame0_x: float) -> Profile:
    decks = _segments(entities, TANK_PROFILE_WINDOW, ('S0CO3',), 'h', 4000)
    main_y = max(decks, key=lambda h: h[2] - h[1])[0]
    # The deck steps up forward (sheer step); keep the long runs near the main deck line.
    runs = [(x0, x1, y) for y, x0, x1, _ in decks if abs(y - main_y) < 400]
    floors = _segments(entities, TANK_PROFILE_WINDOW, PROFILE_FLOOR_LAYERS, 'h', MIN_FLOOR_MM)
    return Profile(frame0_x, runs, floors)


# --- hull clip (product code: vessel_reconstruction.tanks) ---------------------------------

def plate_part(slicer: HullSlicer, x: float, z_range, thickness: float):
    """A transverse plate at x: the hull section between z_range, thickness centred on x."""
    _, outline = clipped_outline(slicer, x, (-50.0, 50.0), z_range, OUTLINE_DZ_M)
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
               'tank_plan': {'frame0_dxf_x': frame0, 'table_rows': len(table),
                             'table_totals': read_table_totals(tank_texts)}}
    parts: list[Part] = []

    # Tank top (inner bottom) plates: one per level run.
    for number, top in enumerate(section.tank_tops):
        z = top['z_m']
        x0, x1 = top['x_m']
        slabs = tank_slabs_in_hull(slicer, (x0, x1), lambda x: (-50.0, 50.0), lambda x, z=z: (z - PLATE_GUESS_M, z),
                                   SLAB_M, OUTLINE_DZ_M)
        parts.append(Part(
            f'tank_top_{number + 1}', 'deck', f'Tank top (double bottom) at {z:.2f} m, x {x0:.1f} to {x1:.1f} m',
            slabs, {'level': top['source'], 'extent': top['source'], 'thickness': 'guessed'},
            {'level': {'source': top['source'], 'basis': top['evidence']},
             'extent': {'source': top['source'], 'basis': 'line ends in the longitudinal section; breadth from the hull'},
             'thickness': {'source': 'guessed', 'basis': f'plate {PLATE_GUESS_M * 1000:.0f} mm (no plate label read)'}},
            {'level': z, 'extent': [x0, x1], 'thickness': PLATE_GUESS_M}))

    # Main transverse bulkheads from the tank-arrangement profile.
    profile = read_profile(tank_entities, frame0)
    bulkheads = profile_bulkheads(tank_entities, frame0, profile.main_deck_y, section.deck_z_m * MM)
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
    placed: dict[int, tuple[str, TankPlace]] = {}
    for key in ('below_tank_top', 'below_1_deck'):
        window = TANK_TOP_PLAN_WINDOW if key == 'below_tank_top' else DECK_PLAN_WINDOW
        boxes = cross_boxes(tank_entities, window)
        for index, place in tank_regions(views[key], label_anchors(tank_path, window), table, boxes).items():
            placed.setdefault(index, (key, place))
    reading['tank_plan']['tanks_placed'] = len(placed)
    used_ids = set()
    for index, row in enumerate(table):
        identity = re.sub(r'\W+', '_', (row.number or row.name).lower()).strip('_')
        while identity in used_ids:
            identity += '_2'
        used_ids.add(identity)
        table_geometry = {'table_frames': list(row.frames), 'table_volume_m3': row.volume_m3,
                          'group': row.group, 'density_t_m3': row.density_t_m3}
        if index not in placed:
            parts.append(Part(f'tank_{identity}', 'tank', f'{row.number or ""} {row.name}'.strip(),
                              [], {}, {}, table_geometry,
                              notes=['no plan region or cross mark holds its label: not built']))
            continue
        key, place = placed[index]
        parts.append(tank_part(f'tank_{identity}', row, key, place, views[key], section, profile, slicer,
                               table_geometry))
    return parts, reading


def tank_part(part_id: str, row: TankRow, plan: str, place: TankPlace, view: PlanView, section: LongSection,
              profile: 'Profile', slicer: HullSlicer, table_geometry: dict) -> Part:
    """A tank solid: plan extent, vertical limits, clipped to the hull; volume from its mesh."""
    spans = view.mask_columns(place.mask(view))
    xs = np.array(sorted(spans))
    half_pixel = PLAN_PIXEL_MM / MM / 2
    x_range = (float(xs.min()) - half_pixel, float(xs.max()) + half_pixel)

    def y_of_x(x):
        nearest = xs[np.argmin(np.abs(xs - x))]
        return spans[float(nearest)] if abs(nearest - x) <= 2 * half_pixel else None

    on_centre_line = any(y0 < 0 < y1 for y0, y1 in spans.values())
    if plan == 'below_tank_top':
        def z_of_x(x):
            top = tank_top_at(section, x)
            return (-1.0, top) if top else None
        bridged = any((tank_top_run(section, x) or {}).get('source') == 'guessed' for x in xs)
        z_source = 'guessed' if bridged else 'traced'
        z_basis = 'from the hull bottom to the tank top of the longitudinal section' + (
            ' (a bridged gap: level of the neighbouring runs)' if bridged else '')
    elif on_centre_line and all(profile.floor_z(x, section.deck_z_m) for x in xs):
        def z_of_x(x):
            return (profile.floor_z(x, section.deck_z_m), section.deck_z_m)
        z_source = 'traced'
        z_basis = ('from the floor line of the tank-arrangement profile (height below the 1-deck line '
                   'there) to the 1-deck level')
    else:
        def z_of_x(x):
            return (tank_top_at(section, x) or -1.0, section.deck_z_m)
        z_source = 'guessed'
        z_basis = 'from the tank top (or the hull bottom) to the 1-deck level; the tank height is not drawn'
    fine = tank_slabs_in_hull(slicer, x_range, y_of_x, z_of_x, TANK_SLAB_M, TANK_ROW_DZ_M)
    slabs = tank_slabs_in_hull(slicer, x_range, y_of_x, z_of_x, SLAB_M, OUTLINE_DZ_M)
    triangles = tanks.slabs_triangles(fine)
    volume = tanks.fill_state(triangles, float(triangles[:, :, 2].max())).volume_m3 if triangles is not None else 0.0
    return Part(
        part_id, 'tank', f'{row.number or ""} {row.name}'.strip(), slabs, {'outline': 'traced', 'height': z_source},
        {'outline': {'source': 'traced', 'basis': place.basis(plan)}, 'height': {'source': z_source, 'basis': z_basis}},
        {'x_m': [round(x_range[0], 3), round(x_range[1], 3)], 'plan': plan, **table_geometry},
        volume_m3=volume, triangles=triangles)


# --- export -----------------------------------------------------------------------------

def tank_model(parts: list[Part]) -> list[tanks.Tank]:
    """The tank model of the capacity plan: every table row, built or not."""
    model = []
    for part in parts:
        if part.op != 'tank':
            continue
        geometry = part.geometry
        built_labels = set(part.source_labels.values())
        density = geometry.get('density_t_m3')
        model.append(tanks.Tank(
            part.id, part.label, geometry.get('group') or 'misc', part.triangles,
            tuple(geometry['table_frames']), density,
            {'name': 'read', 'content': 'read', 'frames': 'read', 'density': 'read' if density else 'guessed',
             'geometry': 'traced' if built_labels == {'traced'} else 'guessed', 'sounding_origin': 'guessed'},
            geometry.get('table_volume_m3'), list(part.notes)))
    return model


def write_tank_outputs(parts: list[Part], out: Path) -> list[dict]:
    """Tank model file, capacity plan and sounding tables (git-ignored output folder)."""
    from vessel_reconstruction.exports.tank_tables import write_tank_tables

    model = tank_model(parts)
    tanks.save_tanks(model, out / 'tanks.npz')
    stamp = ['Draft tank model from MarinaFrame (Gunnerus internals, development case). Not approved for '
             'construction.', 'Units metres; x forward from frame 0, y to port, z up from the baseline.']
    rows, _ = write_tank_tables(model, out / 'tank_tables', 'Gunnerus_internals_DRAFT', stamp)
    return rows


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
    capacity = write_tank_outputs(parts, out)
    summary = {'engineering_approved': False, 'status': 'draft_only', 'reading': reading,
               'capacity_plan': capacity,
               'parts': [component_entry(p, None) | {'built': bool(p.slabs), 'volume_m3': p.volume_m3}
                         for p in parts], 'seconds': time.time() - started}
    if args.truth_mesh:
        from benchmarks.gunnerus.whole_vessel_internals_metrics import score
        summary['metrics'] = score(parts, reading, np.load(args.truth_mesh)['triangles'], capacity)
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
