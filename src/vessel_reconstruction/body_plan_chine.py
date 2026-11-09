"""Conservative hard-chine joining after the frozen body-plan reader.

Crossing positions and kinds stay unchanged. A join needs two independently traced
ends and a common knuckle series across stations; an isolated corner is not enough.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from vessel_reconstruction import body_plan_reader as bpr

# Two line widths allow raster end caps to stop on different sides of a corner.
END_WIDTHS = 2.0
# Never bridge more than 1/20 of a waterline spacing, even on thick scans.
END_SPACING_SHARE = 0.05
# Fit outside the end cap, over 1/10 spacing, to distinguish a knuckle from noise.
FIT_SPACING_SHARE = 0.10
# A 20-degree turn is a resolved knuckle, not the gradual bend of a fair section.
MIN_TURN_DEGREES = 20.0
# Three stations establish a series, rather than one accidental pair of touches.
MIN_SERIES_JOINS = 3
# Chine height may depart from a straight series by 1/25 waterline spacing.
SERIES_RESIDUAL_SHARE = 0.04


@dataclass(frozen=True)
class _Join:
    lower: int
    upper: int
    row: float
    column: float
    gap: float


def measure_side(ink: np.ndarray, sheet: bpr.SheetLayout, side: bpr.SideLayout,
                 curve_width: float | None = None) -> bpr.SideReading:
    """Measure with the frozen reader, then join only a detected chine series."""
    reading = bpr.measure_side(ink, sheet, side, curve_width)
    return join_chine(ink, sheet, reading)


def _end(chain: bpr.Chain, upper: bool, fit_rows: float):
    points = np.asarray(chain.path, dtype=float)
    if len(points) < 3:
        return None
    points = points[np.argsort(points[:, 0])]
    endpoint = points[0] if upper else points[-1]
    distance = np.abs(points[:, 0] - endpoint[0])
    fitted = points[(distance >= 3) & (distance <= fit_rows)]
    if len(fitted) < 5 or np.ptp(fitted[:, 0]) < fit_rows / 2:
        return None
    slope, intercept = np.polyfit(fitted[:, 0], fitted[:, 1], 1)
    return endpoint, float(slope), float(intercept)


def _meeting(lower: bpr.Chain, upper: bpr.Chain, spacing: float, tolerance: float):
    below = _end(lower, True, spacing * FIT_SPACING_SHARE)
    above = _end(upper, False, spacing * FIT_SPACING_SHARE)
    if below is None or above is None:
        return None
    p, lower_slope, lower_intercept = below
    q, upper_slope, upper_intercept = above
    gap = float(np.linalg.norm(p - q))
    if gap > tolerance:
        return None
    turn = abs(np.degrees(np.arctan(lower_slope) - np.arctan(upper_slope)))
    if turn < MIN_TURN_DEGREES:
        return None
    row = (upper_intercept - lower_intercept) / (lower_slope - upper_slope)
    column = lower_slope * row + lower_intercept
    # The fitted intersection must be at the trace ends, not far along their extensions.
    if max(np.linalg.norm(np.array([row, column]) - end) for end in (p, q)) > tolerance:
        return None
    return float(row), float(column), gap


def _series(candidates: list[_Join], reading: bpr.SideReading, spacing: float) -> list[_Join]:
    # Ambiguous endpoints are left alone, rather than assigned by nearest distance.
    unique = [c for c in candidates
              if sum(other.lower == c.lower for other in candidates) == 1
              and sum(other.upper == c.upper for other in candidates) == 1]
    if len(unique) < MIN_SERIES_JOINS:
        return []
    unique.sort(key=lambda c: reading.layout.sign * c.column, reverse=True)
    # Both pieces must retain the same nesting order at their measured waterlines.
    for first, second in zip(unique, unique[1:]):
        for a, b in ((first.lower, second.lower), (first.upper, second.upper)):
            ca, cb = reading.chains[a], reading.chains[b]
            shared = set(ca.nodes) & set(cb.nodes)
            if not shared or any(ca.nodes[w] >= cb.nodes[w] for w in shared):
                return []
    xs = np.array([c.column for c in unique])
    ys = np.array([c.row for c in unique])
    if np.ptp(xs) <= spacing * END_SPACING_SHARE:
        return []
    residual = np.abs(ys - np.polyval(np.polyfit(xs, ys, 1), xs))
    return unique if max(residual) <= spacing * SERIES_RESIDUAL_SHARE else []


def join_chine(ink: np.ndarray, sheet: bpr.SheetLayout,
               reading: bpr.SideReading) -> bpr.SideReading:
    """Return a new reading for a supported chine, or the original object unchanged.

    Only disjoint chains on adjacent waterlines can join. The ink argument is kept
    in this interface so callers use the same image for measurement and joining;
    the endpoints themselves come from the frozen reader's ink-followed paths.
    """
    if ink.ndim != 2:
        raise ValueError('chine joining requires a two-dimensional ink mask')
    spacing = bpr.waterline_spacing(sheet)
    widths = [c.width_px for cs in reading.stations.values() for c in cs]
    if not widths:
        return reading
    tolerance = min(END_WIDTHS * float(np.median(widths)), spacing * END_SPACING_SHARE)
    levels = {w: i for i, w in enumerate(sheet.waterlines_low_to_high())}
    groups: dict[int, list[_Join]] = {}
    for i, lower in enumerate(reading.chains):
        lower_top = max(levels[w] for w in lower.nodes)
        for j, upper in enumerate(reading.chains):
            if i == j or min(levels[w] for w in upper.nodes) != lower_top + 1:
                continue
            meeting = _meeting(lower, upper, spacing, tolerance)
            if meeting is not None:
                row, column, gap = meeting
                groups.setdefault(lower_top, []).append(_Join(i, j, row, column, gap))
    joins = [join for candidates in groups.values() for join in _series(candidates, reading, spacing)]
    if not joins:
        return reading
    # Do not consume an intermediate fragment twice in separate chine series.
    used: set[int] = set()
    chains = []
    for join in joins:
        if join.lower in used or join.upper in used:
            continue
        lower, upper = reading.chains[join.lower], reading.chains[join.upper]
        path = [p for p in lower.path if p[0] >= join.row]
        path += [(join.row, join.column)]
        path += [p for p in upper.path if p[0] < join.row]
        chains.append(bpr.Chain(lower.side, {**lower.nodes, **upper.nodes},
                                lower.inferred_links + upper.inferred_links + 1, path))
        used.update((join.lower, join.upper))
    chains.extend(chain for index, chain in enumerate(reading.chains) if index not in used)
    chains = bpr.order_chains(chains, reading.stations, sheet.centre_column, reading.layout.sign)
    return replace(reading, chains=chains)
