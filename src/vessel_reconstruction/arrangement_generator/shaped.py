"""Explicit internal surfaces for draft tank capacities.

All coordinates use x AP-to-FP, signed y and z above keel. Envelopes are
caller-supplied geometry, not surfaces inferred from a target capacity. Section
normal offsets below are two-dimensional; they do not establish 3D shell
clearance or statutory compliance.
"""
from dataclasses import dataclass
from math import hypot, isfinite

from . import _quantity

MAX_STATIONS = 300
MAX_VERTICES = 128
# Metre-native OCCT booleans need a small absolute sliver allowance, not a
# percentage of tank volume (which could hide real overlaps in large tanks).
OVERLAP_TOLERANCE_M3 = 1e-7


@dataclass(frozen=True)
class EnvelopeStation:
    x_m: float
    polygon_yz_m: tuple[tuple[float, float], ...]

    def __post_init__(self):
        if (not isfinite(self.x_m) or not 3 <= len(self.polygon_yz_m) <= MAX_VERTICES
                or any(len(p) != 2 or not all(isfinite(v) for v in p) for p in self.polygon_yz_m)):
            raise ValueError('Require a finite station and 3..128 finite polygon vertices.')


def _closed_solid(shape, label):
    try:
        solids = shape.Solids()
        valid = (len(solids) == 1 and shape.isValid()
                 and len(shape.Faces()) == len(solids[0].Faces())
                 and len(shape.Edges()) == len(solids[0].Edges())
                 and len(shape.Vertices()) == len(solids[0].Vertices())
                 and all(s.Closed() for s in solids[0].Shells())
                 and solids[0].Volume() > 0)
    except (AttributeError, TypeError):
        valid = False
    if not valid:
        raise ValueError(f'{label} must contain one valid positive closed solid.')
    return solids[0]


def build_envelope(stations: tuple[EnvelopeStation, ...]):
    """Close a ruled envelope through matching ordered polygon vertices.

    Vertex correspondence is explicit: callers must insert corner points in
    every station in the same order. No smoothing or extrapolation is done.
    Geometry is metre-native. A flat transverse polygon is never a box proxy.
    """
    import cadquery as cq

    if not 2 <= len(stations) <= MAX_STATIONS:
        raise ValueError('Require 2..300 envelope stations.')
    size = len(stations[0].polygon_yz_m)
    if (any(len(s.polygon_yz_m) != size for s in stations)
            or any(b.x_m <= a.x_m for a, b in zip(stations, stations[1:]))):
        raise ValueError('Stations must increase in x and have matching vertex counts.')
    try:
        wires = []
        for s in stations:
            wire = cq.Wire.makePolygon([cq.Vector(s.x_m, y, z) for y, z in s.polygon_yz_m], close=True)
            face = cq.Face.makeFromWires(wire)
            if not face.isValid() or face.Area() <= 0:
                raise ValueError('Envelope polygon is invalid or self-crossed.')
            wires.append(wire)
        shape = cq.Solid.makeLoft(wires, ruled=True)
        return _closed_solid(shape, 'Envelope')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'Cannot construct ruled envelope: {type(exc).__name__}') from exc


def offset_side(points_yz, distance_m):
    """Offset an ascending starboard shell polyline inward by a normal distance.

    Each straight segment is shifted toward the centreline. Adjacent shifted
    lines meet at their exact miter; endpoints follow the first/last normals.
    No fillet, end extension or 3D longitudinal normal is invented.
    """
    if (not isfinite(distance_m) or distance_m <= 0 or not 2 <= len(points_yz) <= MAX_VERTICES
            or any(len(p) != 2 or not all(isfinite(v) for v in p) for p in points_yz)):
        raise ValueError('Require a positive finite offset and finite side polyline.')
    shifted = []
    for a, b in zip(points_yz, points_yz[1:]):
        dy, dz = b[0]-a[0], b[1]-a[1]
        if dz <= 0:
            raise ValueError('Side polyline heights must strictly increase.')
        length = hypot(dy, dz)
        shifted.append(((a[0]-distance_m*dz/length, a[1]+distance_m*dy/length), (dy, dz)))
    result = [shifted[0][0]]
    for (a, u), (b, v) in zip(shifted, shifted[1:]):
        cross = u[0]*v[1]-u[1]*v[0]
        if abs(cross) <= 1e-12*hypot(*u)*hypot(*v):
            result.append(b)
        else:
            delta = (b[0]-a[0], b[1]-a[1])
            t = (delta[0]*v[1]-delta[1]*v[0])/cross
            result.append((a[0]+t*u[0], a[1]+t*u[1]))
    a, u = shifted[-1]
    result.append((a[0]+u[0], a[1]+u[1]))
    if any(y < 0 for y, _ in result) or any(b[1] <= a[1] for a, b in zip(result, result[1:])):
        raise ValueError('Offset collapses or reverses the inner side.')
    return tuple(result)


@dataclass(frozen=True)
class TankEnvelope:
    name: str
    kind: str
    envelope: object
    sources: tuple[str, ...]
    fill_fraction: float = .98
    usable_fraction: float = 1.

    def __post_init__(self):
        if (not isinstance(self.name, str) or not self.name.strip()
                or self.kind not in ('cargo', 'slop', 'ballast')
                or not isinstance(self.sources, tuple) or not self.sources
                or any(not isinstance(s, str) or not s.strip() for s in self.sources)
                or any(not isfinite(v) or not 0 < v <= 1 for v in (self.fill_fraction, self.usable_fraction))):
            raise ValueError('Require a name, tank kind, source citations and fractions in (0,1].')


@dataclass(frozen=True)
class TankMeasurement:
    specification: TankEnvelope
    volume_m3: float
    centre_m: tuple[float, float, float]

    @property
    def capacity_m3(self):
        return self.volume_m3*self.specification.fill_fraction*self.specification.usable_fraction

    def to_record_fragment(self):
        s = self.specification
        def quantity(value, unit):
            return _quantity(value, unit, s.sources, method='explicit_shaped_envelope_hull_intersection')
        return dict(name=s.name, kind=s.kind, status='review_required', engineering_approved=False,
                    volume=quantity(self.volume_m3, 'm3'), centre=quantity(list(self.centre_m), 'm'),
                    capacity=quantity(self.capacity_m3, 'm3'),
                    fill_fraction=quantity(s.fill_fraction, '1'), usable_fraction=quantity(s.usable_fraction, '1'),
                    limits=['Caller-supplied internal surfaces; no statutory clearance assertion.',
                            'Usable fraction is explicit input, not a fitted geometric correction.'])


def measure_tanks(hull, tanks: tuple[TankEnvelope, ...], *, units: str):
    """Intersect supplied internal envelopes with the hull and reject overlap.

    Hull and envelopes share declared units. Returned volumes/centres are in
    metres. Allocations need not fill the hull, but must be mutually disjoint.
    """
    if units not in ('m', 'mm'):
        raise ValueError('Declare m or mm for both hull and envelopes.')
    if not tanks or len(tanks) > 300 or len({t.name for t in tanks}) != len(tanks):
        raise ValueError('Require 1..300 uniquely named tank envelopes.')
    hull = _closed_solid(hull, 'Hull')
    if units == 'mm':
        hull = hull.scale(.001)
    parts, results = [], []
    for spec in tanks:
        envelope = _closed_solid(spec.envelope, spec.name)
        if units == 'mm':
            envelope = envelope.scale(.001)
        part = _closed_solid(hull.intersect(envelope), f'Intersection {spec.name}')
        for other in parts:
            if part.intersect(other).Volume() > OVERLAP_TOLERANCE_M3:
                raise ValueError(f'Tank {spec.name} overlaps another allocated tank.')
        parts.append(part)
        results.append(TankMeasurement(spec, part.Volume(), tuple(part.Center().toTuple())))
    return tuple(results)
