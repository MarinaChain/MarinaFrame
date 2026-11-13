"""True wetted surface, not projected sectional girth; analytic curved checks."""
import math

import numpy as np
import pytest
from scipy.integrate import quad

from vessel_reconstruction.exports.hydrostatics import mesh_hydrostatics


def wetted_area(triangles, draft):
    """Exercise production clipping and area, not a duplicate test formula."""
    return mesh_hydrostatics(triangles, draft, "synthetic z plane").wetted_surface_m2


def sphere_triangles(resolution):
    # Latitude/longitude facets with poles handled as single triangles.
    rows = []
    for theta in np.linspace(0, math.pi, resolution + 1):
        phi = np.linspace(0, 2 * math.pi, 2 * resolution, endpoint=False)
        rows.append(np.column_stack([np.sin(theta) * np.cos(phi),
                                     np.sin(theta) * np.sin(phi), np.full(len(phi), np.cos(theta))]))
    triangles = []
    for index, (a, b) in enumerate(zip(rows, rows[1:])):
        for j in range(len(a)):
            k = (j + 1) % len(a)
            if index:
                triangles.append([a[j], b[j], a[k]])
            if index < resolution - 1:
                triangles.append([a[k], b[j], b[k]])
    return np.asarray(triangles)


@pytest.mark.parametrize('vertical_radius', [1., 1.7])
def test_sphere_cap_and_spheroid_area_converge(vertical_radius):
    draft = .3 * vertical_radius
    # Surface of revolution: r(z)=sqrt(1-z²/c²).
    c = vertical_radius
    expected = quad(lambda z: 2 * math.pi * math.sqrt(1 + z*z*(1/c**4 - 1/c**2)),
                    -c, draft, epsabs=1e-11)[0]
    errors = []
    for resolution in [16, 32, 64]:
        triangles = sphere_triangles(resolution) * [1, 1, c]
        measured = wetted_area(triangles, draft)
        errors.append(abs(measured / expected - 1))
    assert errors[2] < errors[1] < errors[0]
    assert errors[-1] < .002


def test_horizontal_cylinder_segment_area_converges():
    draft, length = .3, 3.
    expected = length * (math.pi + 2 * math.asin(draft)) + 2 * (
        math.pi / 2 + math.asin(draft) + draft * math.sqrt(1 - draft*draft))
    errors = []
    for n in [32, 64, 128]:
        angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
        yz = np.column_stack([np.cos(angles), np.sin(angles)])
        a = np.column_stack([np.zeros(n), yz])
        b = a + [length, 0, 0]
        triangles = []
        for j in range(n):
            k = (j + 1) % n
            triangles.extend([[a[j], b[j], a[k]], [a[k], b[j], b[k]],
                              [[0, 0, 0], a[k], a[j]], [[length, 0, 0], b[j], b[k]]])
        errors.append(abs(wetted_area(np.asarray(triangles), draft) / expected - 1))
    assert errors[2] < errors[1] < errors[0]
    assert errors[-1] < .002
