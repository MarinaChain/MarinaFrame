"""Full public half-shell sections from source triangles, without common trimming.

Imported coordinates are explicitly metres despite the public file's MM label.
Only coincident positive-y cuts are merged. Disconnected vertical ranges remain
separate centreline regions; no breadth is extrapolated across missing skin.
"""
import numpy as np


def section_regions_from_segments(segments, *, tolerance_m=.005, height_step_m=.1):
    """Convert (y,z) shell segments to source-supported centreline regions."""
    segments = np.array(segments, dtype=float, copy=True)
    if (segments.ndim != 3 or segments.shape[1:] != (2, 2)
            or not len(segments) or not np.isfinite(segments).all()
            or not 0 < tolerance_m <= .005 or not 0 < height_step_m <= .1):
        raise ValueError('Require finite section segments and bounded sampling tolerances.')
    if segments[:, :, 0].min() < -tolerance_m:
        raise ValueError('Expected a positive-y half shell.')
    segments[:, :, 0] = np.maximum(segments[:, :, 0], 0)
    # Flat bottom patches and centreline strips are closures, not outer skin.
    keep = ((np.ptp(segments[:, :, 1], axis=1) > 1e-9)
            & (segments[:, :, 0].max(axis=1) > tolerance_m))
    segments = segments[keep]
    intervals = sorted((float(p[:, 1].min()), float(p[:, 1].max())) for p in segments)
    ranges = []
    for low, high in intervals:
        if ranges and low <= ranges[-1][1] + tolerance_m:
            ranges[-1][1] = max(ranges[-1][1], high)
        else:
            ranges.append([low, high])
    regions = []
    for low, high in ranges:
        if high - low < 1e-8:
            continue
        levels = np.linspace(low, high, max(5, int(np.ceil((high - low) / height_step_m)) + 1))
        rows = []
        for z in levels:
            a, b = segments[:, 0], segments[:, 1]
            hit = ((np.minimum(a[:, 1], b[:, 1]) <= z + 1e-9)
                   & (np.maximum(a[:, 1], b[:, 1]) >= z - 1e-9))
            if not hit.any():
                # Only a declared sub-tolerance seam may interpolate endpoints.
                nearest = np.argmin(abs(segments[:, :, 1] - z))
                y = segments.reshape(-1, 2)[nearest, 0]
            else:
                y_values = a[hit, 0] + (z - a[hit, 1]) / (b[hit, 1] - a[hit, 1]) * (b[hit, 0] - a[hit, 0])
                y_values = y_values[y_values > tolerance_m]
                if len(y_values) and np.ptp(y_values) > tolerance_m:
                    raise ValueError(f'Unsupported multiple positive shell intersections at z={z:.6f}.')
                y = float(y_values.max()) if len(y_values) else 0.
            rows.append([max(0., float(z)), 0., float(y)])
        if max(r[2] for r in rows) > tolerance_m:
            regions.append(dict(kind='centreline', rows_m=rows))
    if not regions:
        raise ValueError('No source-supported section regions.')
    return regions


def triangle_section(triangles, x_m):
    """Intersect source triangles with x, preserving individual edge segments."""
    triangles = np.asarray(triangles, dtype=float)
    points = [[] for _ in range(len(triangles))]
    for p, q in ((0, 1), (1, 2), (2, 0)):
        a, b = triangles[:, p], triangles[:, q]
        hit = ((a[:, 0] <= x_m) & (b[:, 0] > x_m)) | ((b[:, 0] <= x_m) & (a[:, 0] > x_m))
        indices = np.flatnonzero(hit)
        crossings = a[hit] + ((x_m - a[hit, 0]) / (b[hit, 0] - a[hit, 0]))[:, None] * (b[hit] - a[hit])
        for index, point in zip(indices, crossings[:, 1:]):
            points[index].append(point)
    return np.asarray([p for p in points if len(p) == 2])


def sample_full_iges(path, *, face_indices, source_aft_x_m, source_fore_x_m,
                     parallel_source_x_m, draft_m, depth_m, stations=161):
    """Read all selected source regions at full longitudinal extent.

    Source x increases aft and source z points down. Terminal cuts are inset by
    1 mm to avoid tangent degeneracy. The resulting terminal closures and any
    source seam up to 5 mm are explicit approximation limits, not missing ends.
    """
    import cadquery as cq
    from OCP.IGESControl import IGESControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from . import topology
    from .display_mesh import shape_mesh
    from .hull_variation import HullSections

    if not source_fore_x_m < source_aft_x_m or stations < 4 or not 0 < draft_m < depth_m:
        raise ValueError('Invalid full-hull dimensions or station count.')
    reader = IGESControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError('Cannot read public IGES.')
    if reader.IGESModel().GlobalSection().UnitFlag() != 2:
        raise ValueError('Require explicitly stated MM-labelled metre coordinates.')
    reader.TransferRoots()
    faces = topology.faces(cq.Shape.cast(reader.OneShape()))
    if (not face_indices or len(set(face_indices)) != len(face_indices)
            or any(i < 0 or i >= len(faces) for i in face_indices)):
        raise ValueError('Require unique source face indices.')
    triangles = []
    for index in face_indices:
        vertices, indices = shape_mesh(faces[index], .002, .1)
        triangles.extend(vertices[indices])
    triangles = np.asarray(triangles)
    triangles[:, :, 2] *= -1
    source_x = np.unique(np.r_[np.linspace(source_fore_x_m + .001, source_aft_x_m - .001, stations),
                              parallel_source_x_m])
    regions = []
    for x in source_x[::-1]:
        station = section_regions_from_segments(triangle_section(triangles, x))
        # Only remove sub-tolerance native baseline/deck roundoff.
        for region in station:
            rows = np.asarray(region['rows_m'])
            if rows[:, 0].min() < -.005 or rows[:, 0].max() > depth_m + .005:
                raise ValueError('Source section exceeds declared vertical bounds.')
            rows[:, 0] = np.clip(rows[:, 0], 0, depth_m)
            region['rows_m'] = rows.tolist()
        regions.append(station)
    x = source_x[-1] - source_x[::-1]
    levels = np.array([0., draft_m, depth_m])
    # Compatibility envelope is not used for integration or CAD when regions exist.
    widths = np.array([[max((np.interp(z, np.asarray(r['rows_m'])[:, 0],
                                      np.asarray(r['rows_m'])[:, 2], left=0, right=0)
                            for r in station), default=0) for z in levels] for station in regions])
    breadth = 2 * max(row[2] for station in regions for r in station for row in r['rows_m'])
    parallel = tuple(sorted(source_x[-1] - p for p in parallel_source_x_m))
    hull = HullSections(x, levels, widths, float(x[-1]), breadth, draft_m, parallel, regions=regions)
    return hull, dict(status='draft', engineering_approved=False, selected_faces=face_indices,
                      source_aft_x_m=source_aft_x_m, source_fore_x_m=source_fore_x_m,
                      source_to_local_aft_offset_m=float(source_x[-1]),
                      terminal_inset_m=.001, mesh_deflection_m=.002, height_step_m=.1,
                      seam_tolerance_m=.005, stations=len(x), triangles=len(triangles),
                      limits=['Separate source regions remain separate; no gap bridging.',
                              'Region matching can end with planar caps; inspect build audit.'])
