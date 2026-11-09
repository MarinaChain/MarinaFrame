"""Parts above the hull that follow the hull: decks, bulwarks and deckhouses.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, section 3.8.

Before this module every part above the hull was its GA plan outline extruded straight up.
The GA outline is the outermost line of the plan view (often the rail or the forecastle top), so
where the hull side is narrower at the deck (bow, stern) the part stood out past the hull.

``HullSide`` is the hull's half-breadth as a function of x and z, read from the same lines-plan
station sections that the hull loft uses. Above a station's drawn top the side continues with
the flare of its top rows (a labelled extrapolation, at most ``MAX_EXTRAPOLATION_M``).

Coordinates: x from frame 0 (positive forward), y to port, z from the baseline, metres.
"""
from __future__ import annotations

import numpy as np

# Height step of the half-breadth grid. The station rows are about 0.05 m apart near the deck.
HULL_GRID_M = 0.05
# The flare above a station's top is the slope of its rows over this height below the top.
FLARE_FIT_M = 0.5
# The side is continued with the flare at most this far above the drawn top; higher, it is
# constant (a bulwark or rail stands at most about 1.5 m above the drawn sheer).
MAX_EXTRAPOLATION_M = 1.5
# Two stations closer than this in x are one station (the larger half-breadth wins).
SAME_STATION_M = 1e-6


class HullSide:
    """Half-breadth of the hull side on a grid of stations (x) and heights (z)."""

    def __init__(self, x_m, z_m, half_breadth_m):
        self.x = np.asarray(x_m, dtype=float)
        self.z = np.asarray(z_m, dtype=float)
        self.half_breadth_grid = np.asarray(half_breadth_m, dtype=float)
        if self.half_breadth_grid.shape != (len(self.x), len(self.z)) or len(self.x) < 2 or len(self.z) < 2:
            raise ValueError('hull side grid shape')

    @classmethod
    def from_sections(cls, sections: list[dict]) -> HullSide:
        """Grid from station sections: ``{'x_m', 'regions': [{'rows_m': [[z, y_in, y_out], ...]}]}``."""
        stations = sorted(sections, key=lambda section: section['x_m'])
        rows = [np.asarray(region['rows_m'], dtype=float) for s in stations for region in s['regions']]
        z_low = min(r[:, 0].min() for r in rows)
        z_high = max(r[:, 0].max() for r in rows) + MAX_EXTRAPOLATION_M
        z = np.arange(np.floor(z_low / HULL_GRID_M), np.ceil(z_high / HULL_GRID_M) + 1) * HULL_GRID_M
        xs, grid = [], []
        for section in stations:
            values = station_half_breadths(section['regions'], z)
            if xs and section['x_m'] - xs[-1] < SAME_STATION_M:
                grid[-1] = np.maximum(grid[-1], values)
                continue
            xs.append(float(section['x_m']))
            grid.append(values)
        return cls(xs, z, np.array(grid))

    def to_dict(self) -> dict:
        return {'x_m': self.x.round(4).tolist(), 'z_m': self.z.round(4).tolist(),
                'half_breadth_m': self.half_breadth_grid.round(4).tolist()}

    @classmethod
    def from_dict(cls, data: dict) -> HullSide:
        return cls(data['x_m'], data['z_m'], data['half_breadth_m'])

    @property
    def x_range(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[-1])

    def half_breadth(self, x, z) -> np.ndarray:
        """Half-breadth at (x, z), linear in both; zero outside the station range in x."""
        x, z = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(z, dtype=float))
        shape = x.shape
        x, z = x.ravel(), np.clip(z.ravel(), self.z[0], self.z[-1])
        position = (z - self.z[0]) / (self.z[1] - self.z[0])
        lower = np.clip(np.floor(position).astype(int), 0, len(self.z) - 2)
        weight = position - lower
        station = np.clip(np.searchsorted(self.x, x, side='right') - 1, 0, len(self.x) - 2)
        t = np.clip((x - self.x[station]) / (self.x[station + 1] - self.x[station]), 0.0, 1.0)

        def at(stations):
            grid = self.half_breadth_grid
            return grid[stations, lower] * (1 - weight) + grid[stations, lower + 1] * weight

        result = at(station) * (1 - t) + at(station + 1) * t
        inside = (x >= self.x[0]) & (x <= self.x[-1])
        return np.where(inside, result, 0.0).reshape(shape)

    def outside_distance(self, x, y, z, *, x_step_m: float = 0.02) -> np.ndarray:
        """Plan distance of each point outside the hull side at its own height (0 when inside).

        The distance is the smaller of the lateral distance (``|y|`` less the half-breadth at x)
        and the longitudinal distance to the nearest x where the side is at least ``|y|`` wide
        (the bow and stern ends). Points: arrays of the same length.
        """
        x, y, z = (np.asarray(v, dtype=float).ravel() for v in (x, y, z))
        half_breadth = self.half_breadth(x, z)
        # Where the hull has no side at this x and z (beyond its ends) only the x distance counts.
        lateral = np.where(half_breadth > 0, np.maximum(np.abs(y) - half_breadth, 0.0), np.inf)
        result = np.where(np.isfinite(lateral), lateral, 0.0)
        outside = np.nonzero(lateral > 0)[0]
        grid_x = np.arange(self.x[0], self.x[-1] + x_step_m, x_step_m)
        for index in outside:
            wide = grid_x[self.half_breadth(grid_x, np.full_like(grid_x, z[index])) >= max(abs(y[index]), 1e-9)]
            longitudinal = float(np.abs(wide - x[index]).min()) if len(wide) else np.inf
            best = min(lateral[index], longitudinal)
            # No side at this height at all: the point is as far out as it is from the centreline.
            result[index] = best if np.isfinite(best) else abs(y[index])
        return result


def station_half_breadths(regions: list[dict], z: np.ndarray) -> np.ndarray:
    """Outer half-breadth of one station at each height of ``z``.

    Inside the drawn rows: the largest outer offset over the regions. Above the drawn top: the
    top offset plus the flare of the top rows, for at most ``MAX_EXTRAPOLATION_M``. Below the
    lowest row: zero.
    """
    values = np.zeros_like(z)
    top_z, top_rows = -np.inf, None
    for region in regions:
        rows = np.asarray(region['rows_m'], dtype=float)
        rows = rows[np.argsort(rows[:, 0], kind='stable')]
        inside = (z >= rows[0, 0]) & (z <= rows[-1, 0])
        values[inside] = np.maximum(values[inside], np.interp(z[inside], rows[:, 0], rows[:, 2]))
        if rows[-1, 0] > top_z:
            top_z, top_rows = rows[-1, 0], rows
    above = z > top_z
    if top_rows is not None and above.any():
        top_y = top_rows[-1, 2]
        below = top_rows[top_rows[:, 0] <= top_z - FLARE_FIT_M]
        flare = 0.0
        if len(below):
            reference_z = top_z - FLARE_FIT_M
            reference_y = np.interp(reference_z, top_rows[:, 0], top_rows[:, 2])
            flare = (top_y - reference_y) / FLARE_FIT_M
        rise = np.minimum(z[above] - top_z, MAX_EXTRAPOLATION_M)
        values[above] = np.maximum(top_y + flare * rise, 0.0)
    return values
