"""OCCT section reconstruction for public CFD hulls. All coordinates are metres."""
import math

import cadquery as cq
import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt


def station_positions(start, end, count=321):
    """Cosine spacing retains both end stations and resolves bow/stern curvature."""
    if not math.isfinite(start + end) or end <= start or count < 200:
        raise ValueError('Require increasing bounds and at least 200 stations')
    return start + (end - start) * (1 - np.cos(np.linspace(0, math.pi, count))) / 2


def slice_half_breadths(source, x, deck, levels=161, edge_samples=201):
    """Intersect trimmed source faces, then sample the outer starboard envelope.

    Sampled edge polylines are intersected with common heights. Horizontal
    segments retain their outer endpoint, so a flat bottom is not lost.
    Gaps and competing breadths are recorded, never silently called source data.
    """
    operation = BRepAlgoAPI_Section(source.wrapped, gp_Pln(gp_Pnt(x, 0, 0), gp_Dir(1, 0, 0)), False)
    operation.Build()
    if not operation.IsDone():
        raise ValueError('OCCT section failed')
    edges = cq.Shape.cast(operation.Shape()).Edges()
    polylines = []
    for edge in edges:
        points = np.array([p.toTuple() for p in edge.sample(edge_samples)[0]])
        if len(points) >= 2:
            polylines.append(points[:, 1:3])
    if not polylines:
        raise ValueError('No section edges at station')
    all_points = np.concatenate(polylines)
    bottom = float(all_points[:, 1].min())
    if bottom >= deck:
        raise ValueError('No section below deck')
    source_top = float(all_points[:, 1].max())
    deck_extension = max(0., deck - source_top)
    # Only a submicrometre endpoint discrepancy may reach the declared deck.
    # Larger missing ends fail; submerged source-trim gaps stay in evidence.
    if deck_extension > 1e-6:
        raise ValueError('Incomplete section below declared deck')
    heights = np.linspace(bottom, deck, levels)
    breadths = []
    gaps = []
    spread = []
    for z in heights:
        candidates = []
        sample_z = min(z, source_top)
        for points in polylines:
            for a, b in zip(points[:-1], points[1:]):
                if min(a[1], b[1]) - 1e-6 <= sample_z <= max(a[1], b[1]) + 1e-6:
                    if abs(b[1] - a[1]) < 1e-12:
                        candidates.extend([a[0], b[0]])
                    else:
                        fraction = np.clip((sample_z - a[1]) / (b[1] - a[1]), 0, 1)
                        candidates.append(a[0] + fraction * (b[0] - a[0]))
        positive = [max(0., float(y)) for y in candidates if y >= -1e-6]
        if not positive:
            gaps.append(float(z))
            breadths.append(float('nan'))
        else:
            breadths.append(max(positive))
            spread.append(max(positive) - min(positive))
    valid = np.isfinite(breadths)
    if np.count_nonzero(valid) < 2 or not valid[0] or not valid[-1]:
        raise ValueError(f'Incomplete section at keel or deck: bottom={bottom}, deck={deck}, gaps={gaps}')
    # Distinguish missing trim joins from empty space between two source
    # branches that both terminate at the centreline (bulb and upper stem).
    endpoints = np.concatenate([points[[0, -1]] for points in polylines])
    centreline_gaps = []
    breadths = np.interp(heights, heights[valid], np.array(breadths)[valid])
    for index, z in enumerate(heights):
        if valid[index]:
            continue
        below = endpoints[endpoints[:, 1] < z]
        above = endpoints[endpoints[:, 1] > z]
        if len(below) and len(above):
            lower = below[np.argmax(below[:, 1])]
            upper = above[np.argmin(above[:, 1])]
            if abs(lower[0]) <= 1e-6 and abs(upper[0]) <= 1e-6:
                breadths[index] = 0.
                centreline_gaps.append(float(z))
    return np.column_stack([breadths, heights]), dict(
        section_edges=len(edges), deck_extension_m=deck_extension,
        intersection_height_tolerance_m=1e-6, interpolated_gap_heights_m=gaps,
        centreline_gap_heights_m=centreline_gaps,
        max_competing_breadth_m=max(spread, default=0.))


def loft_sections(positions, profiles):
    """Mirror matching half profiles and cap the ruled solid at both ends."""
    if len(positions) != len(profiles) or len(positions) < 2 or np.any(np.diff(positions) <= 0):
        raise ValueError('Require matching profiles and strictly increasing stations')
    wires = []
    for x, profile in zip(positions, profiles):
        profile = np.asarray(profile, dtype=float)
        if not np.all(np.isfinite(profile)) or np.any(profile[:, 0] < 0):
            raise ValueError('Invalid half-breadth profile')
        half = [cq.Vector(x, y, z) for y, z in profile]
        mirrored = [cq.Vector(x, -y, z) for y, z in profile[::-1]]
        clean = []
        for point in half + mirrored:
            if not clean or (point - clean[-1]).Length > 1e-10:
                clean.append(point)
        if (clean[-1] - clean[0]).Length <= 1e-10:
            clean.pop()
        wires.append(cq.Wire.makePolygon(clean, close=True))
    solid = cq.Solid.makeLoft(wires, ruled=True)
    if not solid.isValid() or not solid.Closed() or solid.Volume() <= 0:
        raise ValueError('Section loft is not a valid closed positive-volume solid')
    return solid


def submerged_particulars(solid, draft):
    """Clip at draft; exclude the artificial horizontal waterplane face."""
    bounds = solid.BoundingBox()
    margin = max(bounds.xlen, bounds.ylen, bounds.zlen, 1.)
    clip = cq.Solid.makeBox(bounds.xlen + 2 * margin, bounds.ylen + 2 * margin,
                           draft - bounds.zmin + margin,
                           cq.Vector(bounds.xmin - margin, bounds.ymin - margin, bounds.zmin - margin))
    wet = solid.intersect(clip)
    area = 0.
    for face in wet.Faces():
        box = face.BoundingBox()
        if abs(box.zmin - draft) < 1e-6 and abs(box.zmax - draft) < 1e-6:
            continue
        area += face.Area()
    return dict(volume_m3=wet.Volume(), wetted_area_m2=area)


def triangulate(solid, deflection=0.0001, angular_deflection=0.2):
    """Tessellate connected topology and weld coordinates at 1 nm resolution."""
    vertices, faces = solid.tessellate(deflection, angular_deflection)
    coordinates = np.round(np.array([point.toTuple() for point in vertices]), 9)
    triangles = coordinates[np.asarray(faces)]
    area_vectors = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return triangles[np.linalg.norm(area_vectors, axis=1) > 0]


def sample_distances(source, points):
    """Exact trimmed-shape distance at each supplied point, not a global bound."""
    return [source.distance(cq.Vertex.makeVertex(*map(float, point))) for point in points]
