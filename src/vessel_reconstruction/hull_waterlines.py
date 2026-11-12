"""Supported waterline domains for an explicitly selected reference shell.

No extrapolation: a common supported interval is capped by the existing hull
builder. Distances discarded from each measured waterline remain in the report.
"""
import numpy as np


def join_waterline(parts: list[np.ndarray], seam_tolerance_m: float = 0.005) -> np.ndarray:
    """Join monotone-x patch cuts, accepting only coincident patch seams."""
    if not parts:
        raise ValueError('No waterline intersections.')
    ordered = []
    for part in parts:
        points = np.asarray(part, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError('Waterline cuts must contain finite x/y pairs.')
        points = points[np.argsort(points[:, 0], kind='stable')]
        if len(points) < 2 or np.ptp(points[:, 0]) < 1e-8:
            continue
        ordered.append(points)
    ordered.sort(key=lambda p: p[0, 0])
    if not ordered:
        raise ValueError('No longitudinal waterline segments.')
    result = ordered[0]
    for part in ordered[1:]:
        gap = part[0, 0] - result[-1, 0]
        if gap > seam_tolerance_m:
            raise ValueError(f'disconnected waterline: {gap:.6f} m gap')
        if gap < -seam_tolerance_m:
            raise ValueError('Overlapping waterline patches; select a single main shell.')
        if abs(part[0, 1] - result[-1, 1]) > seam_tolerance_m:
            raise ValueError('Waterline patch seam does not meet in breadth.')
        result = np.vstack([result[:-1], (result[-1] + part[0]) / 2, part[1:]])
    if np.any(np.diff(result[:, 0]) <= 0):
        raise ValueError('Waterline is not a single-valued monotone-x curve.')
    return result


def main_component(parts: list[np.ndarray], interior_x_m: float,
                   seam_tolerance_m: float = 0.005) -> tuple[np.ndarray, list[list[float]]]:
    """Keep the connected waterline containing a stated interior station."""
    ordered = sorted(parts, key=lambda p: float(np.min(p[:, 0])))
    groups = []
    for part in ordered:
        if not groups or np.min(part[:, 0]) > max(np.max(p[:, 0]) for p in groups[-1]) + seam_tolerance_m:
            groups.append([part])
        else:
            groups[-1].append(part)
    selected = [g for g in groups if min(np.min(p[:, 0]) for p in g) <= interior_x_m
                <= max(np.max(p[:, 0]) for p in g)]
    if len(selected) != 1:
        raise ValueError('A unique main waterline must pass through the interior station.')
    excluded = [[float(min(np.min(p[:, 0]) for p in g)), float(max(np.max(p[:, 0]) for p in g))]
                for g in groups if g is not selected[0]]
    return join_waterline(selected[0], seam_tolerance_m), excluded


def common_extent(lines: list[np.ndarray], heights_m: list[float],
                  source_extent_m: tuple[float, float]) -> tuple[float, float, list[dict]]:
    """Intersect supported domains; record missing and deliberately trimmed lengths."""
    if not lines or len(lines) != len(heights_m):
        raise ValueError('One supported line is required for each waterline.')
    low = max(float(p[0, 0]) for p in lines)
    high = min(float(p[-1, 0]) for p in lines)
    if low >= high:
        raise ValueError('Waterlines have no common closed-section extent.')
    source_low, source_high = source_extent_m
    report = []
    for z, line in zip(heights_m, lines):
        left, right = float(line[0, 0]), float(line[-1, 0])
        report.append(dict(z_m=float(z), supported_min_x_m=left, supported_max_x_m=right,
                           retained_min_x_m=low, retained_max_x_m=high,
                           left_missing_m=max(0, left - source_low),
                           right_missing_m=max(0, source_high - right),
                           left_omitted_m=low - left, right_omitted_m=right - high))
    return low, high, report
