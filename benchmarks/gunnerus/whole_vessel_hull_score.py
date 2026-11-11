"""Score the whole-vessel hull (one B-spline face per run side) with the hull scorer.

``score.py`` meshes the model with the kernel mesher at 0.1 mm. On a hull side that is one
degree-1 B-spline face of many spans, that mesher is very slow (no result after 20 minutes on
Gunnerus) and leaves holes at coarse settings. This wrapper gives ``score.py`` the exact
triangulation of the same surface instead: two triangles per bilinear patch from the surface
poles (``display_mesh.shape_mesh`` with no column left out), and the kernel mesh for the other
faces. Everything else (cuts, grids, metrics, truth cache) is ``score.py`` unchanged. The sealed
hull benchmark does not use this module.

Usage: the arguments of ``benchmarks.gunnerus.score``.
"""
from __future__ import annotations

import numpy as np

from benchmarks.gunnerus import score

# A side column is left out only within this distance (mm) of its chord at every station:
# in practice none (the score.py deflection is 0.1 mm).
EXACT_TOLERANCE_MM = 1e-6


def exact_triangles(shape, deflection_mm: float, angular_rad: float = 0.2) -> np.ndarray:
    import cadquery as cq

    from vessel_reconstruction.display_mesh import shape_mesh

    vertices, triangles = shape_mesh(cq.Shape.cast(shape), min(deflection_mm, EXACT_TOLERANCE_MM), angular_rad)
    return vertices[triangles] / 1000.0


def main() -> None:
    score.mesh_triangles = exact_triangles
    score.main()


if __name__ == '__main__':
    main()
