"""Read public symmetric IGES surfaces with explicit native-unit conventions."""
from pathlib import Path

import numpy as np

from .hull_variation import HullSections


def sample_iges(path: Path, *, source_aft_x: float, length_m: float, breadth_m: float,
                keel_z: float, draft_m: float, depth_m: float,
                parallel_body_m: tuple[float, float], stations: int = 81,
                heights: int = 41, native_units_per_metre: float = 1.0,
                source_z_direction: int = 1, coordinate_tolerance_m: float = 0.005) -> HullSections:
    """Sample positive-y shell sections, with no inferred missing bottom/top.

    Only MM-declared IGES is accepted. Coordinates below refer to the imported
    millimetre working coordinates; native_units_per_metre is an explicit
    correction for numerically mislabelled public files (KVLCC2 uses 1, not
    1000). It is not the IGES unit flag. The caller states aft x and keel z.
    Only an upright, symmetric, single-valued half hull is
    supported. Every requested height must intersect the supplied surface.
    Terminal sections are inset by 1e-5 L to avoid tangent plane degeneracies.
    """
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.IGESControl import IGESControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from . import topology

    if (stations < 4 or heights < 5 or not np.isfinite(native_units_per_metre)
            or native_units_per_metre <= 0 or source_z_direction not in (-1, 1)
            or not np.isfinite(coordinate_tolerance_m) or not 0 <= coordinate_tolerance_m <= 0.005):
        raise ValueError('Require >=4 stations, >=5 heights, positive scale, vertical sign and <=5 mm tolerance.')
    reader = IGESControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError('Cannot read IGES reference.')
    if reader.IGESModel().GlobalSection().UnitFlag() != 2:
        raise ValueError('Experimental sampler accepts MM-declared IGES only; convert units explicitly first.')
    reader.TransferRoots()
    shape = cq.Shape.cast(reader.OneShape())
    x = np.linspace(0, length_m, stations)
    z = np.linspace(0, depth_m, heights)
    # Include draft exactly so both integrations use the same waterline.
    z = np.unique(np.r_[z, draft_m])
    rows = []
    for position in x:
        inset = np.clip(position, length_m * 1e-5, length_m * (1 - 1e-5))
        plane = gp_Pln(gp_Pnt(source_aft_x + inset * native_units_per_metre, 0, 0), gp_Dir(1, 0, 0))
        cut = BRepAlgoAPI_Section(shape.wrapped, plane, False)
        cut.Build()
        if not cut.IsDone():
            raise ValueError(f'Cannot cut reference at x={position}.')
        edges = topology.edges(cq.Shape.cast(cut.Shape()))
        lines = []
        for edge in edges:
            points = np.array([v.toTuple() for v in edge.sample(200)[0]])
            if len(points) > 1:
                lines.extend(zip(points[:-1], points[1:]))
        if not lines:
            raise ValueError(f'No reference section at x={position}.')
        lines = np.asarray(lines) / native_units_per_metre
        lines[:, :, 2] = source_z_direction * (lines[:, :, 2] - keel_z / native_units_per_metre)
        rows.append([])
        for height in z:
            low, high = lines[:, :, 2].min(), lines[:, :, 2].max()
            if height < low - coordinate_tolerance_m or height > high + coordinate_tolerance_m:
                raise ValueError(f'Missing shell at x={position:.3f}, z={height:.3f}; unsupported section domain.')
            level = float(np.clip(height, low + 1e-9, high - 1e-9))
            p, q = lines[:, 0], lines[:, 1]
            dz = q[:, 2] - p[:, 2]
            crossing = ((np.minimum(p[:, 2], q[:, 2]) - 1e-7 <= level)
                        & (np.maximum(p[:, 2], q[:, 2]) + 1e-7 >= level) & (abs(dz) > 1e-12))
            if not crossing.any():
                raise ValueError(f'Missing shell at x={position:.3f}, z={height:.3f}; reduce sampled domain.')
            fraction = (level - p[crossing, 2]) / dz[crossing]
            y = p[crossing, 1] + fraction * (q[crossing, 1] - p[crossing, 1])
            positive = y[y > coordinate_tolerance_m]
            if len(positive) and np.ptp(positive) > coordinate_tolerance_m:
                raise ValueError(f'Unsupported multiple positive shell intersections at x={position}, z={height}.')
            if y.min() < -coordinate_tolerance_m:
                raise ValueError('Expected positive-y half hull; negative-side geometry is unsupported.')
            rows[-1].append(max(0, float(y.max())))
    return HullSections(x, z, np.asarray(rows), length_m, breadth_m, draft_m, parallel_body_m)
