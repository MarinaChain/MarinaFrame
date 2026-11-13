"""Write an already triangulated, closed full-body surface without CAD dependencies."""
from collections import Counter
import math
from pathlib import Path


def validate_surface(triangles):
    triangles = [tuple(tuple(float(x) for x in point) for point in triangle) for triangle in triangles]
    edges = Counter()
    volume = 0.
    if not triangles:
        raise ValueError('Empty surface')
    for triangle in triangles:
        if len(triangle) != 3 or any(len(p) != 3 or not all(math.isfinite(x) for x in p) for p in triangle):
            raise ValueError('Expected finite triangles in metres')
        a, b, c = triangle
        u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        if math.hypot(*cross) == 0:
            raise ValueError('Degenerate triangle')
        volume += sum(a[i]*cross[i] for i in range(3)) / 6
        for start, end in ((a, b), (b, c), (c, a)):
            edges[start, end] += 1
    if any(count != 1 or edges[end, start] != 1 for (start, end), count in edges.items()):
        raise ValueError('Surface must be closed, manifold and consistently oriented')
    if volume <= 0:
        raise ValueError('Surface must have positive outward-oriented volume')
    return triangles


def write_stl(path: Path, triangles):
    """Reject open/half hulls; callers must close and orient their CAD tessellation first."""
    triangles = validate_surface(triangles)
    with Path(path).open('x', encoding='ascii') as stream:
        stream.write('solid hull\n')
        for triangle in triangles:
            stream.write('  facet normal 0 0 0\n    outer loop\n')
            for point in triangle:
                stream.write('      vertex ' + ' '.join(format(v, '.17g') for v in point) + '\n')
            stream.write('    endloop\n  endfacet\n')
        stream.write('endsolid hull\n')
