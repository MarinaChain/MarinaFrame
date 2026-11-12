"""Experimental independent station identity; never use nesting rank as a name.

Reference vectors must come from another drawing view, not scored offsets.
Protocol: docs/plans/2026-11-12-polyline-naming.md, amendment 2b3d46b.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

import numpy as np

MIN_SHARED_LEVELS = 3
MAX_RMS_M = 0.05
UNMATCHED_COST_M = 0.05
MIN_MARGIN_M = 0.02
MIN_COST_RATIO = 2.0
LABEL_DISTANCE_WIDTHS = 2.0


@dataclass
class NamingResult:
    names: dict[int, int]  # section index -> independently identified station
    unnamed: list[int]
    costs_m: list[list[float | None]]


def plan_vectors(plan, station_positions_m: dict[int, float]) -> dict[int, dict]:
    """Sample independently traced plan curves at calibrated longitudinal positions.

    Level keys are physical heights. Do not interpolate across an abstained column,
    extrapolate beyond the view, or use the deck as a drawn waterline.
    """
    from vessel_reconstruction.view_reader_v2 import NAMED

    result = {name: {} for name in station_positions_m}
    if plan is None or not len(plan.x_m):
        return result
    for name, position in station_positions_m.items():
        if not math.isfinite(position) or not plan.x_m[0] <= position <= plan.x_m[-1]:
            continue
        column = int(np.argmin(np.abs(plan.x_m - position)))
        for curve_id, curve in plan.curves.items():
            height = curve['z_m']
            value = curve['y_m'][column]
            if (curve_id != 'deck' and height is not None and math.isfinite(height)
                    and curve['status'][column] in NAMED and math.isfinite(value)):
                result[name][float(height)] = float(value)
    return result


def _shape_cost(section: dict, reference: dict) -> float:
    common = [level for level in section.keys() & reference.keys()
              if math.isfinite(section[level]) and math.isfinite(reference[level])]
    if len(common) < MIN_SHARED_LEVELS:
        return math.inf
    return math.sqrt(sum((section[level] - reference[level]) ** 2 for level in common) / len(common))


def _align(costs: np.ndarray, forbidden=None) -> tuple[float, list[tuple[int, int]]]:
    """Minimum-cost order-preserving alignment with explicit section/station skips."""
    count, station_count = costs.shape
    totals = np.full((count + 1, station_count + 1), math.inf)
    totals[0, :] = 0.
    totals[:, 0] = np.arange(count + 1) * UNMATCHED_COST_M
    moves = {}
    for i in range(1, count + 1):
        for j in range(1, station_count + 1):
            choices = [(totals[i - 1, j] + UNMATCHED_COST_M, 'section'),
                       (totals[i, j - 1], 'station')]
            cost = costs[i - 1, j - 1]
            if cost <= MAX_RMS_M and forbidden != (i - 1, j - 1):
                choices.append((totals[i - 1, j - 1] + cost, 'match'))
            totals[i, j], moves[i, j] = min(choices, key=lambda item: item[0])
    pairs = []
    i, j = count, station_count
    while i and j:
        move = moves[i, j]
        if move == 'match':
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif move == 'section':
            i -= 1
        else:
            j -= 1
    return float(totals[count, station_count]), list(reversed(pairs))


def match_sections(sections: list[dict], references: dict[int, dict]) -> NamingResult:
    """Jointly align vectors in calibrated half order, then reject local/global ambiguity.

    ``references`` insertion order is the drawing's known order, not numeric ID order.
    Neither longitudinal spacing nor the number of missing sections supplies an identity.
    """
    stations = list(references)
    costs = np.array([[_shape_cost(section, references[name]) for name in stations]
                      for section in sections], dtype=float).reshape(len(sections), len(stations))
    best_total, pairs = _align(costs)
    names = {}
    for section_index, station_index in pairs:
        best = costs[section_index, station_index]
        competitors = [cost for index, cost in enumerate(costs[section_index]) if index != station_index]
        second = min(competitors, default=math.inf)
        if second < MIN_COST_RATIO * best or second - best < MIN_MARGIN_M:
            continue
        alternative, _ = _align(costs, forbidden=(section_index, station_index))
        if alternative - best_total < MIN_MARGIN_M:
            continue
        names[section_index] = stations[station_index]
    serial_costs = [[float(cost) if math.isfinite(cost) else None for cost in row] for row in costs]
    return NamingResult(names, [index for index in range(len(sections)) if index not in names], serial_costs)


def name_half(half, layout, drawn_level_rows: dict[float, float], references: dict[int, dict],
              labels: list[tuple[int, float, float]], permitted: set[int] | None = None):
    """Copy a traced half and replace every polyline rank name with independent identity.

    ``drawn_level_rows`` maps physical heights to calibrated body-plan rows.
    Synthetic measuring rows are not independent drawn levels. Existing unnamed
    traces participate too; shared knuckles and short outlines stay excluded.
    A half read as a whole remains so even if every section is unnamed: otherwise
    downstream code could silently restore rank-named baseline curves.
    """
    from copy import deepcopy
    from vessel_reconstruction import body_plan_polyline as polyline

    result = deepcopy(half)
    sections = result.stations + result.engaged + result.unnamed
    # Lists can share a trace after engagement; keep each geometric object once.
    unique = list({id(section): section for section in sections}.values())
    fragments = polyline._fragments(unique)
    eligible = [section for section in unique if not section.shared_knuckle
                and not any(section is fragment for fragment in fragments)]
    # Use only rows covered by every side for the existing fore/aft nesting order.
    # A short trace must not be extrapolated simply to obtain an ordering key.
    rows = [row for row in drawn_level_rows.values()
            if all(section.sheer[0] <= row <= section.chine[0] for section in eligible)]
    eligible.sort(key=lambda section: polyline._nesting_key(section, rows, layout))
    for section in unique:
        section.station = None
    vectors = [{height: value for height, row in drawn_level_rows.items()
                if (value := section.half_breadth_m(row, layout)) is not None}
               for section in eligible]
    usable = any(sum(math.isfinite(value) for value in vector.values()) >= MIN_SHARED_LEVELS
                 for vector in references.values())
    if usable:
        matched = match_sections(vectors, references)
        assigned, costs = matched.names, matched.costs_m
        source = 'cross-view joint shape alignment'
    else:
        assigned = match_labels([section.side_points() for section in eligible], labels,
                                permitted if permitted is not None else set(references), result.line_width_px)
        costs = []
        source = 'positioned printed labels' if labels else 'no independent identity evidence'
    result.stations, result.engaged = [], []
    result.unnamed = [section for section in unique if not any(section is item for item in eligible)]
    for index, section in enumerate(eligible):
        if index not in assigned:
            result.unnamed.append(section)
            continue
        section.station = assigned[index]
        section.notes.append(f'independent identity: {source}')
        if result.read:
            result.stations.append(section)
        elif polyline.is_clear_knuckle(section, layout):
            if section.bottom_alternatives:
                polyline.side_and_knuckle_only(section)
            result.engaged.append(section)
        else:
            section.station = None
            result.unnamed.append(section)
    result.notes.append(f'position naming: {source}; {len(result.unnamed)} sections unnamed')
    return result, {'source': source, 'unnamed_sections': len(result.unnamed),
                    'named_stations': [section.station for section in result.stations + result.engaged],
                    'pair_costs_m': costs}


def _distance_to_side(points: np.ndarray, row: float, column: float) -> float:
    """Distance to line segments, not just vertices of a sparsely sampled side."""
    if not len(points):
        return math.inf
    point = np.array([row, column])
    if len(points) == 1:
        return float(np.linalg.norm(points[0] - point))
    starts, vectors = points[:-1], np.diff(points, axis=0)
    lengths_squared = np.sum(vectors * vectors, axis=1)
    fractions = np.divide(np.sum((point - starts) * vectors, axis=1), lengths_squared,
                          out=np.zeros_like(lengths_squared), where=lengths_squared > 0)
    closest = starts + np.clip(fractions, 0, 1)[:, None] * vectors
    return float(np.min(np.linalg.norm(closest - point, axis=1)))


def match_labels(sides: list[np.ndarray], labels: list[tuple[int, float, float]],
                 permitted: set[int], line_width_px: float) -> dict[int, int]:
    """Fallback for already positioned labels only; duplicate claims never name a section."""
    if not math.isfinite(line_width_px) or line_width_px <= 0:
        return {}
    claims = []
    for name, row, column in labels:
        if name not in permitted or not math.isfinite(row) or not math.isfinite(column):
            continue
        nearby = [index for index, points in enumerate(sides)
                  if _distance_to_side(points, row, column) <= LABEL_DISTANCE_WIDTHS * line_width_px]
        if len(nearby) == 1:
            claims.append((nearby[0], name))
    section_counts = Counter(index for index, _ in claims)
    name_counts = Counter(name for _, name in claims)
    return {index: name for index, name in claims if section_counts[index] == name_counts[name] == 1}
