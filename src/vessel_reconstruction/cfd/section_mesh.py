"""Closed triangle strips from measured half-sections; no BRep construction."""
import numpy as np

from .surface import validate_surface


def build_section_mesh(sections, samples=321):
    positions = np.array([s['x_m'] for s in sections], dtype=float)
    if len(positions) < 2 or not np.all(np.isfinite(positions)) or np.any(np.diff(positions) <= 0):
        raise ValueError('Require finite strictly increasing stations')
    profiles = []
    fractions = []
    fixed = {0., 1.}
    for section in sections:
        points = np.array(section['points_yz_m'], dtype=float, copy=True)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.all(np.isfinite(points)):
            raise ValueError('Expected finite half-breadth points')
        if np.any(points[:, 0] < 0) or np.any(np.diff(points[:, 1]) <= 0):
            raise ValueError('Require nonnegative breadth and increasing heights')
        # Ten nanometres model scale: numerical coincidence only, not fairing.
        points[abs(points[:, 0]) <= 1e-8, 0] = 0.
        differences = np.diff(points, axis=0)
        lengths = np.linalg.norm(differences, axis=1)
        arc = np.r_[0., np.cumsum(lengths)]
        arc /= arc[-1]
        directions = differences / lengths[:, None]
        turns = np.arccos(np.clip(np.sum(directions[:-1] * directions[1:], axis=1), -1, 1))
        fixed.update(arc[1:-1][turns >= np.deg2rad(10)].tolist())
        profiles.append(points)
        fractions.append(arc)
    knots = np.unique(np.r_[np.linspace(0, 1, samples), sorted(fixed)])
    rings = []
    for x, points, arc in zip(positions, profiles, fractions):
        yz = np.column_stack([np.interp(knots, arc, points[:, axis]) for axis in (0, 1)])
        yz[abs(yz[:, 0]) <= 1e-8, 0] = 0.
        rings.append(np.column_stack([np.full(len(knots), x), yz]))
    triangles = []
    labels = []

    def triangle(a, b, c, label):
        # Identical centreline vertices collapse a quad into a triangle.
        if np.linalg.norm(np.cross(b - a, c - a)) > 0:
            triangles.append([a, b, c])
            labels.append(label)

    def quad(a, b, c, d, label):
        triangle(a, b, c, label)
        triangle(a, c, d, label)

    for left, right in zip(rings[:-1], rings[1:]):
        for sign in (1, -1):
            a, b = left * [1, sign, 1], right * [1, sign, 1]
            for j in range(len(knots) - 1):
                if sign == 1:
                    quad(a[j], b[j], b[j+1], a[j+1], 'skin')
                else:
                    quad(a[j+1], b[j+1], b[j], a[j], 'skin')
        for sign in (1, -1):
            for endpoint, label in ((-1, 'deck'), (0, 'keel')):
                a, b = left[endpoint] * [1,sign,1], right[endpoint] * [1,sign,1]
                ca, cb = a * [1,0,1], b * [1,0,1]
                if (endpoint == -1) == (sign == 1):
                    quad(a, b, cb, ca, label)
                else:
                    quad(ca, cb, b, a, label)
    for index, ring in enumerate((rings[0], rings[-1])):
        for j in range(len(knots) - 1):
            for sign in (1, -1):
                a, b = ring[j] * [1,sign,1], ring[j+1] * [1,sign,1]
                ca, cb = a * [1,0,1], b * [1,0,1]
                if (index == 0) == (sign == 1):
                    quad(ca, a, b, cb, 'end')
                else:
                    quad(cb, b, a, ca, 'end')
    triangles = np.asarray(triangles)
    # One global reversal preserves local edge pairing while choosing outward.
    volume = np.einsum('ij,ij->i', triangles[:,0], np.cross(triangles[:,1], triangles[:,2])).sum() / 6
    if volume < 0:
        triangles = triangles[:, ::-1]
    validate_surface(triangles)
    return triangles, dict(station_count=len(rings), points_per_half_section=len(knots),
                           fixed_knot_count=len(fixed), centreline_weld_tolerance_m=1e-8,
                           triangle_labels=labels)


def mesh_particulars(triangles, draft):
    """Clip skin triangles; a waterplane-origin cap has zero tetrahedral volume."""
    area = 0.
    volume = 0.
    origin = np.array([0., 0., draft])
    for triangle in np.asarray(triangles):
        polygon = []
        for a, b in zip(triangle, np.roll(triangle, -1, axis=0)):
            inside_a, inside_b = a[2] <= draft, b[2] <= draft
            if inside_a:
                polygon.append(a)
            if inside_a != inside_b:
                point = a + (b - a) * ((draft - a[2]) / (b[2] - a[2]))
                point[2] = draft
                polygon.append(point)
        for j in range(1, len(polygon) - 1):
            a, b, c = np.array([polygon[0], polygon[j], polygon[j+1]])
            cross = np.cross(b-a, c-a)
            if not all(p[2] == draft for p in (a,b,c)):
                area += np.linalg.norm(cross) / 2
            volume += np.dot(a-origin, np.cross(b-origin, c-origin)) / 6
    return dict(volume_m3=float(volume), wetted_area_m2=float(area))
