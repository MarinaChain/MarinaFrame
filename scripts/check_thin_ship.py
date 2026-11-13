"""Reproducible synthetic panel/angle/tail checks and warm evaluation timing.

Run from repo with PYTHONPATH=src python scripts/check_thin_ship.py.
This does not claim the published-tabulation exit gate has passed.
"""
import json
import platform
from time import perf_counter

import numpy as np

from vessel_reconstruction.resistance_thin_ship import HullOffsets, wave_resistance


def wigley(nx=129, nz=65):
    x = np.linspace(-0.5, 0.5, nx)
    z = np.linspace(-0.0625, 0, nz)
    y = 0.05 * (1 - 4 * x[:, None]**2) * (1 - (z[None, :] / 0.0625)**2)
    return HullOffsets(x, z, y, 0.0625, 0.15, ("synthetic Wigley L=1 B=.1 T=.0625; arbitrary S=.15 m²",))


def main():
    hull = wigley()
    fine = wigley(257, 129)
    rows = []
    for fn in (0.2, 0.3, 0.4, 0.5):
        speed = fn * np.sqrt(9.81)
        baseline = wave_resistance(hull, speed_m_s=speed)
        variants = {
            "double_panels": wave_resistance(fine, speed_m_s=speed),
            "double_angles": wave_resistance(hull, speed_m_s=speed, angle_count=1024),
            "larger_tail": wave_resistance(hull, speed_m_s=speed, angle_count=1024, lambda_max=48),
        }
        durations = []
        for _ in range(100):
            start = perf_counter()
            wave_resistance(hull, speed_m_s=speed)
            durations.append((perf_counter() - start) * 1000)
        rows.append({"fn": fn, "cw": baseline.cw.value,
                     "relative_changes_percent": {name: 100 * (r.cw.value / baseline.cw.value - 1)
                                                  for name, r in variants.items()},
                     "timing_ms": {"min": min(durations), "median": float(np.median(durations)),
                                   "p95": float(np.percentile(durations, 95)), "max": max(durations)}})
    print(json.dumps({"platform": platform.platform(), "processor": platform.machine(),
                      "resolution": hull.half_breadths_m.shape, "angle_count": 512, "lambda_max": 24,
                      "repetitions": 100, "rows": rows,
                      "published_table_gate": "not run: no matching published numerical tabulation obtained",
                      "kcs": "not run: development offsets not yet prepared",
                      "kvlcc2": "not run: blind-case boundary; PM independent evaluation required"}, indent=2))


if __name__ == "__main__":
    main()
