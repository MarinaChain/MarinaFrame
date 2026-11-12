"""Draft symmetric hull variation by smooth longitudinal station shifts.

Coordinates and calculations use metres. Endpoints and the parallel middle
body stay fixed. This is a Lackenby-type area-curve redistribution, not an
implementation of a particular published Lackenby regression. The existing
ruled builder retains longitudinal panel joints; it does not make a C2 skin.
"""
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares


@dataclass
class HullSections:
    x_m: np.ndarray
    z_m: np.ndarray
    half_breadths_m: np.ndarray
    length_m: float
    breadth_m: float
    draft_m: float
    parallel_body_m: tuple[float, float]

    def __post_init__(self):
        self.x_m = np.asarray(self.x_m, dtype=float).copy()
        self.z_m = np.asarray(self.z_m, dtype=float).copy()
        self.half_breadths_m = np.asarray(self.half_breadths_m, dtype=float).copy()
        if (self.x_m.ndim != 1 or self.z_m.ndim != 1 or len(self.x_m) < 4
                or len(self.z_m) < 2
                or self.half_breadths_m.shape != (len(self.x_m), len(self.z_m))):
            raise ValueError('Expected ordered stations and a common height grid.')
        values = np.r_[self.x_m, self.z_m, self.half_breadths_m.ravel(),
                       self.length_m, self.breadth_m, self.draft_m, self.parallel_body_m]
        if not np.isfinite(values).all():
            raise ValueError('Hull coordinates and dimensions must be finite.')
        a, b = self.parallel_body_m
        if (min(self.length_m, self.breadth_m, self.draft_m) <= 0
                or np.any(np.diff(self.x_m) <= 0) or np.any(np.diff(self.z_m) <= 0)
                or np.any(self.half_breadths_m < 0)
                or not 0 < a < b < self.length_m
                or abs(self.x_m[0]) > 1e-9 or abs(self.x_m[-1] - self.length_m) > 1e-9
                or abs(self.z_m[0]) > 1e-9 or self.z_m[-1] < self.draft_m):
            raise ValueError('Invalid dimensions, station order, draft or parallel body.')


def _areas(hull: HullSections, level: float) -> np.ndarray:
    heights = np.r_[hull.z_m[hull.z_m < level], level]
    widths = np.array([np.interp(heights, hull.z_m, row) for row in hull.half_breadths_m])
    return 2 * np.trapezoid(widths, heights, axis=1)


def _integrals(hull: HullSections, start: float, end: float) -> tuple[float, float]:
    """Exact volume and first moment for linearly matched section ordinates."""
    area = _areas(hull, hull.draft_m)
    x = np.r_[start, hull.x_m[(hull.x_m > start) & (hull.x_m < end)], end]
    a = np.interp(x, hull.x_m, area)
    dx = np.diff(x)
    volume = np.sum(dx * (a[:-1] + a[1:]) / 2)
    moment = np.sum(dx * (x[:-1] * (2 * a[:-1] + a[1:])
                          + x[1:] * (a[:-1] + 2 * a[1:])) / 6)
    return float(volume), float(moment)


def section_properties(hull: HullSections) -> tuple[float, float]:
    """Cb on stated L*B*T basis and LCB in metres from the aft endpoint."""
    volume, moment = _integrals(hull, 0, hull.length_m)
    if volume <= 0:
        raise ValueError('Hull must enclose positive immersed volume.')
    return volume / (hull.length_m * hull.breadth_m * hull.draft_m), moment / volume


def vary_sections(reference: HullSections, *, length_m: float, breadth_m: float,
                  draft_m: float, cb: float, lcb_fraction: float) -> HullSections:
    """Scale L/B/T then move end-body stations to meet Cb and LCB/L.

    A quartic bump has zero displacement and slope at each end-body boundary.
    Amplitudes are bounded so the continuous station map stays monotone, not
    only the sampled stations. Unreachable requests raise ValueError.
    """
    target = np.array([length_m, breadth_m, draft_m, cb, lcb_fraction])
    if (not np.isfinite(target).all() or min(target[:3]) <= 0
            or not 0 < cb < 1 or not 0 < lcb_fraction < 1):
        raise ValueError('Targets must be finite, positive and within physical bounds.')
    x = reference.x_m * (length_m / reference.length_m)
    z = reference.z_m * (draft_m / reference.draft_m)
    widths = reference.half_breadths_m * (breadth_m / reference.breadth_m)
    parallel = tuple(v * length_m / reference.length_m for v in reference.parallel_body_m)
    basis = np.zeros((len(x), 2))
    for column, (lo, hi) in enumerate(((0, parallel[0]), (parallel[1], length_m))):
        mask = (x > lo) & (x < hi)
        t = (x[mask] - lo) / (hi - lo)
        basis[mask, column] = (hi - lo) * 16 * t ** 2 * (1 - t) ** 2

    def candidate(amplitudes):
        return HullSections(x + basis @ amplitudes, z, widths, length_m,
                            breadth_m, draft_m, parallel)

    def residual(amplitudes):
        actual_cb, lcb = section_properties(candidate(amplitudes))
        return np.array([actual_cb - cb, lcb / length_m - lcb_fraction])

    if np.max(np.abs(residual(np.zeros(2)))) < 1e-12:
        return candidate(np.zeros(2))
    # max |d(16*t²*(1-t)²)/dt| = 16*sqrt(3)/9 < 3.08.
    # |amplitude| <= .30 therefore leaves dx'/dx > .076.
    fit = least_squares(residual, np.zeros(2), bounds=(-0.30, 0.30),
                        xtol=1e-12, ftol=1e-12, gtol=1e-12)
    if not fit.success or np.max(np.abs(residual(fit.x))) > 1e-5:
        raise ValueError('Targets are unreachable with the fixed parallel body and monotone map.')
    return candidate(fit.x)


@dataclass
class Candidate:
    solid: object
    report: dict


def gross_capacity(hull: HullSections, aft_bulkhead_m: float, forward_bulkhead_m: float) -> float:
    """Gross envelope below design draft between bulkheads; no structure deductions."""
    if not 0 <= aft_bulkhead_m < forward_bulkhead_m <= hull.length_m:
        raise ValueError('Bulkheads must be ordered within the design length.')
    return _integrals(hull, aft_bulkhead_m, forward_bulkhead_m)[0]


def build_candidate(hull: HullSections, *, bulkheads_m: tuple[float, float] | None = None) -> Candidate:
    """Build the existing matched ruled solid and report existing mesh hydrostatics."""
    from .geometry import build_hull
    from .exports.hydrostatics import mesh_hydrostatics
    from .display_mesh import shape_mesh

    sections = [dict(id=str(index), x_m=float(x),
                     points_yz_m=np.column_stack([widths, hull.z_m]).tolist())
                for index, (x, widths) in enumerate(zip(hull.x_m, hull.half_breadths_m))]
    solid, _ = build_hull(sections, max_deviation_m=1e-6)
    vertices, indices = shape_mesh(solid, 0.1, 0.15)
    triangles = vertices[indices] / 1000
    hydro = mesh_hydrostatics(triangles, hull.draft_m, 'stated design draft',
                             reference_volume_m3=solid.Volume() / 1e9)
    relative = abs(hydro.checks['mesh_volume_m3'] / (solid.Volume() / 1e9) - 1)
    if relative > 0.001:
        raise ValueError('CAD and mesh volume differ by more than the fixed 0.1% gate.')
    bulkheads = bulkheads_m if bulkheads_m is not None else (0.2 * hull.length_m, 0.8 * hull.length_m)
    return Candidate(solid, dict(status='draft', engineering_approved=False,
        method='smooth end-body longitudinal shifts; existing matched ruled BRep',
        coefficient_basis='stated design length * breadth * draft',
        design_cb=hydro.volume_m3 / (hull.length_m * hull.breadth_m * hull.draft_m),
        hydrostatics=hydro.as_dict(), mesh_volume_relative_error=relative,
        bulkheads_m=list(bulkheads), gross_immersed_capacity_m3=gross_capacity(hull, *bulkheads),
        capacity_basis='gross immersed envelope only; excludes freeboard, structure and cargo deductions',
        limits=['Symmetric single-valued half-breadths; no tunnels or overhangs.',
                'Smooth station map, but ruled panels are not a C2 fair surface.',
                'No stability, scantling, deadweight or net cargo assessment.']))
