"""Hull-clipped preliminary tanker compartments; not a statutory assessment.

Coordinates: x aft perpendicular to forward perpendicular, y port negative,
z above keel. CAD native coordinates must already use these datums. Explicit
units are required, since the application's usual CAD working unit is mm.
"""
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path

ANNEX_I = ('IMO MEPC.117(52), 15 October 2004, Annex I',
           'https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.117(52).pdf')
SOLAS = ('IMO MSC.216(82), 8 December 2006, SOLAS II-1/12',
         'https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MSCResolutions/MSC.216(82).pdf')
METHOD = 'closed_hull_planar_partition'
VERSION = '1.0.0'


def protection_dimensions(deadweight_t: float, breadth_m: float) -> tuple[float, float]:
    """Reg.19.3 scalar minima; NOT a curved-shell clearance assessment."""
    if not isfinite(deadweight_t) or deadweight_t < 5000 or not isfinite(breadth_m) or breadth_m <= 0:
        raise ValueError('Require >=5000 t deadweight and positive finite breadth.')
    return max(1., min(0.5 + deadweight_t / 20000, 2.)), max(1., min(breadth_m / 15, 2.))


@dataclass(frozen=True)
class ArrangementInput:
    length_m: float
    breadth_m: float
    depth_m: float
    deadweight_t: float
    rule_length_m: float
    solas_length_m: float
    cargo_rows: int
    cargo_columns: int
    engine_room_length_m: float
    forepeak_length_m: float
    slop_length_m: float
    slop_columns: int
    fuel_reserve_length_m: float
    sources: tuple[str, ...]
    bulb_extension_m: float = 0.

    def __post_init__(self):
        positive = (self.length_m, self.breadth_m, self.depth_m, self.deadweight_t,
                    self.rule_length_m, self.solas_length_m, self.engine_room_length_m,
                    self.forepeak_length_m, self.slop_length_m, self.fuel_reserve_length_m)
        if any(isinstance(v, bool) or not isfinite(v) or v <= 0 for v in positive):
            raise ValueError('Dimensions, rule lengths and deadweight must be finite and positive.')
        if not isfinite(self.bulb_extension_m) or self.bulb_extension_m < 0:
            raise ValueError('Bulb extension must be finite and nonnegative.')
        counts = (self.cargo_rows, self.cargo_columns, self.slop_columns)
        if any(type(v) is not int or not 1 <= v <= 30 for v in counts):
            raise ValueError('Tank counts must be integers in 1..30.')
        if self.cargo_rows * self.cargo_columns + self.slop_columns > 300:
            raise ValueError('At most 300 cargo and slop compartments per draft.')
        if (not isinstance(self.sources, tuple) or not self.sources
                or any(not isinstance(s, str) or not s.strip() for s in self.sources)):
            raise ValueError('At least one nonempty source citation is required.')
        w, h = protection_dimensions(self.deadweight_t, self.breadth_m)
        if (2*w >= self.breadth_m or h >= self.depth_m
                or self.fuel_reserve_length_m >= self.engine_room_length_m
                or self.engine_room_length_m + self.forepeak_length_m + self.slop_length_m >= self.length_m):
            raise ValueError('Tank extents leave no positive cargo or machinery region.')


def _quantity(value, unit, sources, *, method=METHOD):
    return dict(value=value, unit=unit, uncertainty=None,
                uncertainty_reason='No validated geometric/structural uncertainty band available.',
                method=method, method_version=VERSION, sources=list(sources), status='review_required')


@dataclass(frozen=True)
class Compartment:
    name: str
    kind: str
    bounds_m: tuple[float, float, float, float, float, float]
    volume_m3: float
    centre_m: tuple[float, float, float]

    @property
    def capacity_98_m3(self):
        """Geometric volume times fill factor; structure is not deducted."""
        return 0.98 * self.volume_m3

    def to_record_fragment(self, sources):
        return dict(name=self.name, kind=self.kind,
                    boundaries=_quantity(dict(operation='hull_intersection',
                        axes=['x_min', 'x_max', 'y_min', 'y_max', 'z_min', 'z_max'],
                        limits=list(self.bounds_m)), 'm', sources),
                    volume=_quantity(self.volume_m3, 'm3', sources),
                    centre=_quantity(list(self.centre_m), 'm', sources),
                    capacity_98=_quantity(self.capacity_98_m3, 'm3', sources))


@dataclass(frozen=True)
class Arrangement:
    inputs: ArrangementInput
    compartments: tuple[Compartment, ...]
    hull_volume_m3: float
    hull_basis: dict

    @property
    def partition_relative_error(self):
        return abs(sum(c.volume_m3 for c in self.compartments) / self.hull_volume_m3 - 1)

    @property
    def cargo_capacity_98_m3(self):
        return sum(c.capacity_98_m3 for c in self.compartments if c.kind == 'cargo')

    @property
    def segregated_ballast_m3(self):
        return sum(c.volume_m3 for c in self.compartments if c.kind == 'ballast')

    def to_record_fragment(self):
        sources = self.inputs.sources
        return dict(status='review_required', engineering_approved=False,
                    hull_basis=self.hull_basis,
                    compartments=[c.to_record_fragment(sources) for c in self.compartments],
                    hull_volume=_quantity(self.hull_volume_m3, 'm3', sources),
                    partition_relative_error=_quantity(self.partition_relative_error, '1', sources),
                    cargo_capacity_98=_quantity(self.cargo_capacity_98_m3, 'm3', sources),
                    segregated_ballast_capacity=_quantity(self.segregated_ballast_m3, 'm3', sources),
                    rule_screens=_rule_screens(self),
                    limits=['Geometric volumes: no steel, piping, insulation or unpumpable deductions.',
                            'Flat deck, planar bulkheads; no stability, structural or piping assessment.',
                            'Peaks and protective spaces assigned ballast; loading suitability not established.',
                            'Fuel is an aft reserve envelope, not a reg.12A fuel-tank design.',
                            'No statutory compliance or engineering acceptance is asserted.'])


def _rule_screens(result):
    p = result.inputs
    w, h = protection_dimensions(p.deadweight_t, p.breadth_m)
    oil = [c for c in result.compartments if c.kind in ('cargo', 'slop')]
    total_oil = sum(c.capacity_98_m3 for c in oil)
    slop = sum(c.capacity_98_m3 for c in oil if c.kind == 'slop')
    # Historical conservative screen: all outermost columns are wing tanks.
    # A one-column tank is treated as centre, as it spans the centreline.
    tank_checks = []
    for c in oil:
        columns = p.cargo_columns if c.kind == 'cargo' else p.slop_columns
        centre = c.bounds_m[2] < 0 < c.bounds_m[3]
        cap = 50000 if centre or columns == 1 else 22500
        tank_checks.append(c.volume_m3 <= cap and c.bounds_m[1]-c.bounds_m[0] <= max(10., 0.1*p.rule_length_m))
    offset = min(p.bulb_extension_m/2, 0.015*p.solas_length_m, 3.)
    distance = p.forepeak_length_m + offset
    collision_min = min(0.05*p.solas_length_m, 10.)
    collision_max = max(0.08*p.solas_length_m, 0.05*p.solas_length_m + 3.)

    def screen(satisfied, reason, **values):
        return dict(status='review_required', screen_satisfied=satisfied, limitations=reason, **values)

    q = lambda value, unit: _quantity(value, unit, ANNEX_I, method='historical_annex_i_screen')
    return {
        '18': screen(None, 'Capacity only; lightship, ballast draft, trim and propeller immersion unresolved.',
                     minimum_ballast_draft=q(2 + 0.02*p.rule_length_m, 'm'),
                     maximum_stern_trim=q(0.015*p.rule_length_m, 'm'),
                     available_ballast=q(result.segregated_ballast_m3, 'm3')),
        '19': screen(None, 'Scalar minima only. Planar sides do not establish perpendicular shell/bilge clearance.',
                     minimum_side=q(w, 'm'), minimum_bottom=q(h, 'm')),
        '23': screen(None, 'Single-tank full release is a scenario, NOT mean outflow. Damage probabilities, pressure balance and tide unresolved. Applies from delivery 2010-01-01.',
                     largest_single_tank_release=q(max(c.capacity_98_m3 for c in oil), 'm3'),
                     mean_outflow=q(None, '1'),
                     mean_outflow_limit=q(0.015 if total_oil <= 200000 else 0.012 if total_oil >= 400000 else 0.012 + 0.003*(400000-total_oil)/200000, '1')),
        '26': screen(all(tank_checks), 'Historical conservative tank volume/length screen only. Reg.26.7 excludes delivery from 2010-01-01; reg.25 hypothetical outflow and piping not calculated.'),
        '29': screen(slop >= 0.03*total_oil and sum(c.kind == 'slop' for c in oil) >= (2 if p.deadweight_t >= 70000 else 1), 'Conservative 3% of cargo plus slop at equal fill basis; reg.29.3 requires two tanks from 70000 t. Cleaning/transfer equipment and adequacy not checked.',
                     required_slop=q(0.03*total_oil, 'm3'), available_slop=q(slop, 'm3')),
        'SOLAS-II-1-12': screen(collision_min <= distance <= collision_max,
                     'Pinned MSC.216(82) position screen only; caller supplies regulatory length and bulb extension. Openings, deck extent and exceptions unresolved.',
                     distance=_quantity(distance, 'm', SOLAS), minimum=_quantity(collision_min, 'm', SOLAS),
                     maximum=_quantity(collision_max, 'm', SOLAS)),
    }


def generate_arrangement(hull, inputs: ArrangementInput, *, hull_units: str) -> Arrangement:
    """Intersect a single closed hull with disjoint partition cells.

    ``hull`` is a CadQuery shape or STEP path. Use hull_units='mm' for existing
    application CAD candidates and 'm' only for explicitly metre-native shapes.
    The supplied shell must cover the entire declared below-deck domain.
    """
    import cadquery as cq

    if hull_units not in ('m', 'mm'):
        raise ValueError('hull units must be m or mm.')
    basis = dict(coordinates='x AP to FP; y signed; z above keel',
                 input_units=hull_units, sources=list(inputs.sources))
    if isinstance(hull, (str, Path)):
        path = Path(hull)
        basis['sha256'] = sha256(path.read_bytes()).hexdigest()
        imported = cq.importers.importStep(str(path)).vals()
        hull = cq.Compound.makeCompound(imported)
    if hull_units == 'mm':
        hull = hull.scale(0.001)
    solids = hull.Solids()
    if (len(solids) != 1 or not hull.isValid()
            or not all(shell.Closed() for shell in solids[0].Shells())):
        raise ValueError('Hull must contain one valid closed solid.')
    hull = solids[0]
    b = hull.BoundingBox()
    p = inputs
    expected = (0., p.length_m, -p.breadth_m/2, p.breadth_m/2, 0.)
    actual = (b.xmin, b.xmax, b.ymin, b.ymax, b.zmin)
    if any(abs(a-e) > 0.001 for a, e in zip(actual, expected)) or b.zmax < p.depth_m-0.001:
        raise ValueError('Hull bounds must match declared AP/FP, breadth, keel and cover depth.')
    L, B, D = p.length_m, p.breadth_m, p.depth_m
    side, bottom = protection_dimensions(p.deadweight_t, B)
    inner = B/2 - side
    aft = p.engine_room_length_m
    forward = L-p.forepeak_length_m
    cargo_start = aft+p.slop_length_m
    cells = []

    def cell(name, kind, x0, x1, y0, y1, z0, z1):
        cells.append((name, kind, (x0, x1, y0, y1, z0, z1)))

    cell('fuel-reserve', 'fuel', 0, p.fuel_reserve_length_m, -B/2, B/2, 0, D)
    cell('engine-room', 'machinery', p.fuel_reserve_length_m, aft, -B/2, B/2, 0, D)
    cell('forepeak', 'ballast', forward, L, -B/2, B/2, 0, D)
    cell('double-bottom', 'ballast', aft, forward, -B/2, B/2, 0, bottom)
    cell('port-wing', 'ballast', aft, forward, -B/2, -inner, bottom, D)
    cell('starboard-wing', 'ballast', aft, forward, inner, B/2, bottom, D)
    for kind, start, end, rows, columns in (
            ('slop', aft, cargo_start, 1, p.slop_columns),
            ('cargo', cargo_start, forward, p.cargo_rows, p.cargo_columns)):
        for row in range(rows):
            x0, x1 = start+(end-start)*row/rows, start+(end-start)*(row+1)/rows
            for col in range(columns):
                y0, y1 = -inner+2*inner*col/columns, -inner+2*inner*(col+1)/columns
                cell(f'{kind}-{row+1}-{col+1}', kind, x0, x1, y0, y1, bottom, D)
    compartments = []
    for name, kind, bounds in cells:
        x0, x1, y0, y1, z0, z1 = bounds
        box = cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, cq.Vector(x0, y0, z0))
        part = hull.intersect(box)
        volume = part.Volume()
        if volume <= 1e-9:
            continue  # A partition cell outside the real shell is not a tank.
        if len(part.Solids()) != 1:
            raise ValueError(f'Tank {name} has disconnected hull intersection regions.')
        if not part.isValid():
            raise ValueError(f'Invalid hull intersection for {name}.')
        compartments.append(Compartment(name, kind, bounds, volume, tuple(part.Center().toTuple())))
    deck_box = cq.Solid.makeBox(L, B, D, cq.Vector(0, -B/2, 0))
    volume = hull.intersect(deck_box).Volume()
    if volume <= 0 or not any(c.kind == 'cargo' for c in compartments) or not any(c.kind == 'slop' for c in compartments):
        raise ValueError('Hull must enclose positive below-deck, cargo and slop volumes.')
    result = Arrangement(p, tuple(compartments), volume, basis)
    if result.partition_relative_error > 0.01:
        raise ValueError('Compartment sum differs from below-deck hull volume by more than 1%.')
    return result
