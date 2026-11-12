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
            raise ValueError(f'Waterline patch seam does not meet in breadth: {result[-1].tolist()} to {part[0].tolist()}.')
        result = np.vstack([result[:-1], (result[-1] + part[0]) / 2, part[1:]])
    if np.any(np.diff(result[:, 0]) <= 0):
        raise ValueError('Waterline is not a single-valued monotone-x curve.')
    return result


def main_component(parts: list[np.ndarray], interior_x_m: float,
                   seam_tolerance_m: float = 0.005) -> tuple[np.ndarray, list[list[float]]]:
    """Keep the connected waterline containing a stated interior station."""
    ordered = sorted([p[np.argsort(p[:, 0], kind='stable')] for p in parts], key=lambda p: float(p[0, 0]))
    groups = []
    for part in ordered:
        if (not groups or part[0, 0] > groups[-1][-1][-1, 0] + seam_tolerance_m
                or abs(part[0, 1] - groups[-1][-1][-1, 1]) > seam_tolerance_m):
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


def sample_supported_iges(path, *, face_indices: list[int], source_extent_m: tuple[float, float],
                          source_z_levels_m: list[float], draft_source_z_m: float,
                          interior_x_m: float, parallel_source_x_m: tuple[float, float],
                          stations: int = 81, reverse_x: bool = False,
                          source_z_direction: int = 1, seam_tolerance_m: float = 0.005):
    """Sample only common supported main-shell domains in imported MM coordinates.

    Numerical coordinates are explicitly interpreted as metres (the public
    KVLCC2 file is labelled MM but contains ship-sized metre values). A positive
    source_z_level denotes physical height above the source keel; the sign
    selects the native vertical direction. The lowest sampled layer is omitted,
    not extrapolated. Terminal caps are planar builder closures, not source skin.
    """
    import cadquery as cq
    from OCP.IGESControl import IGESControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from . import topology
    from .hull_variation import HullSections

    levels = np.asarray(source_z_levels_m, dtype=float)
    if (len(levels) < 5 or np.any(np.diff(levels) <= 0) or not np.isfinite(levels).all()
            or source_z_direction not in (-1, 1) or stations < 4
            or not levels[0] < draft_source_z_m <= levels[-1]
            or draft_source_z_m not in levels):
        raise ValueError('Require ordered finite levels including draft, vertical sign and >=4 stations.')
    reader = IGESControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError('Cannot read reference IGES.')
    if reader.IGESModel().GlobalSection().UnitFlag() != 2:
        raise ValueError('Supported sampler requires the stated MM coordinate convention.')
    reader.TransferRoots()
    faces = topology.faces(cq.Shape.cast(reader.OneShape()))
    if not face_indices or len(set(face_indices)) != len(face_indices) or any(i < 0 or i >= len(faces) for i in face_indices):
        raise ValueError('Selected face indices must be unique and within the source.')
    lines, excluded = [], []
    for height in levels:
        parts = []
        for index in face_indices:
            cut = BRepAlgoAPI_Section(faces[index].wrapped,
                  gp_Pln(gp_Pnt(0, 0, source_z_direction * height), gp_Dir(0, 0, 1)))
            if not cut.IsDone():
                raise ValueError('Reference waterline cut failed.')
            for edge in topology.edges(cq.Shape.cast(cut.Shape())):
                points = np.array([v.toTuple()[:2] for v in edge.sample(401)[0]])
                if len(points) > 1 and np.ptp(points[:, 0]) > 1e-8:
                    if points[:, 1].min() < -seam_tolerance_m:
                        raise ValueError('Selected shell is not a positive-y half hull.')
                    points[:, 1] = np.maximum(points[:, 1], 0)
                    parts.append(points)
        line, omitted = main_component(parts, interior_x_m, seam_tolerance_m)
        lines.append(line)
        excluded.append(omitted)
    low, high, waterlines = common_extent(lines, levels.tolist(), source_extent_m)
    for row, pieces in zip(waterlines, excluded):
        row['disconnected_intervals_m'] = pieces
    p0, p1 = parallel_source_x_m
    if not low < p0 < p1 < high:
        raise ValueError('Parallel body must be inside the common supported interval.')
    source_x = np.unique(np.r_[np.linspace(low, high, stations), p0, p1])
    widths = np.column_stack([np.interp(source_x, line[:, 0], line[:, 1]) for line in lines])
    length = high - low
    if reverse_x:
        x = high - source_x[::-1]
        widths = widths[::-1]
        parallel = (high - p1, high - p0)
    else:
        x = source_x - low
        parallel = (p0 - low, p1 - low)
    hull = HullSections(x, levels - levels[0], widths, length, 2 * widths.max(),
                        draft_source_z_m - levels[0], parallel)
    report = dict(status='draft', engineering_approved=False, selected_faces=face_indices,
                  excluded_faces=[i for i in range(len(faces)) if i not in face_indices],
                  waterlines=waterlines, source_extent_m=list(source_extent_m),
                  retained_source_extent_m=[low, high], reverse_x=reverse_x,
                  source_z_direction=source_z_direction, keel_layer_excluded_m=float(levels[0]),
                  station_count=len(x), waterline_count=len(levels),
                  edge_samples=401, seam_tolerance_m=seam_tolerance_m,
                  ends='planar terminal caps at common supported end sections; no extrapolation')
    return hull, report
