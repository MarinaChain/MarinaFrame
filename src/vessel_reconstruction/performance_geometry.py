"""Draft symmetric outer-shell particulars from possibly unoriented surfaces.

For closed consistently oriented meshes use performance.hull_particulars_from_mesh.
Public IGES patches can have mixed face normals. This explicit envelope method
integrates transverse cuts, without pretending that they are a closed solid.
It is limited to one symmetric outer hull, without tunnels or interior cavities.
"""
import math
import numpy as np

from .exports.hydrostatics import clip_below


def _half_widths(mesh: np.ndarray, x: float, heights: np.ndarray) -> np.ndarray:
    # Match the existing benchmark's half-open plane intersection convention.
    x = x + 1e-10
    low = mesh[:, :, 0].min(axis=1)
    high = mesh[:, :, 0].max(axis=1)
    faces = mesh[(low < x) & (x < high)]
    # Pair triangle edge hits by face rather than concatenate across faces.
    segments = []
    for face in faces:
        cross = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            start, end = face[a], face[b]
            if min(start[0], end[0]) <= x < max(start[0], end[0]):
                cross.append((start + (x-start[0])/(end[0]-start[0])*(end-start))[1:])
        if len(cross) == 2:
            segments.append(cross)
    if not segments:
        return np.zeros_like(heights)
    seg = np.asarray(segments)
    y0, z0, y1, z1 = seg[:, 0, 0], seg[:, 0, 1], seg[:, 1, 0], seg[:, 1, 1]
    widths = []
    for z in heights:
        hit = (np.minimum(z0,z1) <= z) & (z <= np.maximum(z0,z1)) & (z0 != z1)
        y = y0[hit] + (z-z0[hit])/(z1[hit]-z0[hit])*(y1[hit]-y0[hit])
        widths.append(float(np.abs(y).max()) if len(y) else 0.0)
    return np.asarray(widths)


def surface_particulars(triangles: np.ndarray, *, waterline_z_m: float, lpp_m: float,
                       aft_perpendicular_x_m: float, forward_x_sign: int, half_hull: bool,
                       station_count: int = 401, height_count: int = 401) -> dict:
    """Integrate an explicitly symmetric shell in metres and stated coordinates.

    Transom area is the immersed section at the aft perpendicular, not the aft
    mesh extremum (which can include overhangs/bosses). Bulb area must be measured
    separately at the forward perpendicular; it is not inferred here.
    """
    mesh = np.asarray(triangles, dtype=float)
    if mesh.ndim != 3 or mesh.shape[1:] != (3,3) or not mesh.size or not np.isfinite(mesh).all():
        raise ValueError("triangles must have finite shape (n,3,3)")
    if (not all(math.isfinite(v) for v in (waterline_z_m,lpp_m,aft_perpendicular_x_m))
            or lpp_m <= 0 or forward_x_sign not in (-1,1)
            or not isinstance(half_hull,bool) or station_count < 21 or height_count < 21):
        raise ValueError("invalid geometry coordinate or sampling basis")
    keel = float(mesh[:,:,2].min())
    if not keel < waterline_z_m <= float(mesh[:,:,2].max()):
        raise ValueError("waterline must cut the mesh above its keel")
    draft = waterline_z_m-keel
    xmin, xmax = float(mesh[:,:,0].min()), float(mesh[:,:,0].max())
    # Samples stay just inside end panels so a rectangular test is integrated
    # across its full length; the tolerance is far below mesh chord precision.
    epsilon = max((xmax-xmin)*1e-10,1e-12)
    x = np.linspace(xmin+epsilon,xmax-epsilon,station_count)
    heights = np.linspace(keel,waterline_z_m,height_count)
    half_width = np.array([_half_widths(mesh,float(xx),heights) for xx in x])
    areas = np.trapezoid(2*half_width,heights,axis=1)
    widths = 2*half_width[:,-1]
    volume = float(np.trapezoid(areas,x))
    beam = float(2*half_width.max())
    area_max = float(areas.max())
    wet_x = x[widths > 1e-9]
    if volume <= 0 or beam <= 0 or area_max <= 0 or len(wet_x) < 2:
        raise ValueError("mesh cuts do not define an immersed hull")
    lwl = float(wet_x[-1]-wet_x[0])
    waterplane = float(np.trapezoid(widths,x))
    lcb = float(np.trapezoid(areas*x,x)/volume)
    wet = clip_below(mesh,waterline_z_m)
    wet = wet[~np.all(wet[:,:,2] == waterline_z_m,axis=1)]
    surface = float(np.linalg.norm(np.cross(wet[:,1]-wet[:,0],wet[:,2]-wet[:,0]),axis=1).sum()/2)
    if half_hull:
        surface *= 2
    transom_x = aft_perpendicular_x_m + forward_x_sign*epsilon
    transom_area = float(np.trapezoid(2*_half_widths(mesh,transom_x,heights),heights))
    midpoint = aft_perpendicular_x_m+forward_x_sign*lpp_m/2
    return dict(lwl_m=lwl,beam_m=beam,draft_m=draft,volume_m3=volume,
                cm=area_max/(beam*draft),cwp=waterplane/(lwl*beam),
                lcb_percent_lwl_forward=100*forward_x_sign*(lcb-midpoint)/lwl,
                wetted_surface_m2=surface,transom_area_m2=transom_area,
                geometry_warnings=[
                    "Draft symmetric outer-envelope integration; no tunnels or interior cavities.",
                    "Surface area assumes supplied patches contain no duplicate or centreline panels.",
                    "Largest sampled section substitutes for midship; bulb area needs a separate FP section."],
                method="transverse envelope quadrature + clipped shell triangle area",
                station_count=station_count,height_count=height_count,engineering_approved=False)
