"""Compare the unchanged default solver with the PM's digitised Wigley curve.

Run with PYTHONPATH=src and the project venv. Input data stays outside git.
The JSON output includes every reference row and separate warm timing evidence.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import platform
from pathlib import Path
from time import perf_counter

import numpy as np

from vessel_reconstruction.resistance_thin_ship import HullOffsets, wave_resistance


def machine_state():
    return {"load_average_1_5_15": os.getloadavg(), "logical_cpu_count": os.cpu_count()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    reference_bytes = args.reference.read_bytes()
    reference = list(csv.DictReader(io.StringIO("\n".join(
        line for line in reference_bytes.decode().splitlines() if not line.startswith("#")
    ))))
    x = np.linspace(-0.5, 0.5, 129)
    z = np.linspace(-0.0625, 0, 65)
    y = 0.05 * (1 - 4 * x[:, None]**2) * (1 - (z[None, :] / 0.0625)**2)
    hull = HullOffsets(x, z, y, 0.0625, 0.1487, (
        "Classic Wigley L/B=10 L/T=16; Lazauskas 2009 Table 7.1 S/L²=.1487",
    ))
    before = machine_state()
    start = perf_counter()
    wave_resistance(hull, speed_m_s=0.2 * np.sqrt(9.81))
    cold_ms = (perf_counter() - start) * 1000
    rows = []
    for point in reference:
        fn = float(point["fn"])
        expected = float(point["cw_fig7_1"])
        computed = wave_resistance(hull, speed_m_s=fn * np.sqrt(9.81)).cw.value
        rows.append({"fn": fn, "reference_cw": expected, "computed_cw": computed,
                     "difference_x1000": 1000 * (computed - expected),
                     "relative_error_percent": 100 * (computed / expected - 1)})
    timing_before = machine_state()
    timing = []
    for fn in (0.2, 0.3, 0.4, 0.5):
        speed = fn * np.sqrt(9.81)
        durations = []
        for _ in range(100):
            start = perf_counter()
            wave_resistance(hull, speed_m_s=speed)
            durations.append((perf_counter() - start) * 1000)
        timing.append({"fn": fn, "min_ms": min(durations),
                       "median_ms": float(np.median(durations)),
                       "p95_ms": float(np.percentile(durations, 95)),
                       "max_ms": max(durations), "calls_ge_50_ms": sum(t >= 50 for t in durations)})
    payload = {"reference_sha256": hashlib.sha256(reference_bytes).hexdigest(),
               "source_kind": "digitised Fig. 7.1, not author-published numerical tabulation",
               "platform": platform.platform(), "numpy_version": np.__version__,
               "before": before, "timing_before": timing_before, "after": machine_state(),
               "panels_x_z": [128, 64], "angle_count": 512, "lambda_max": 24,
               "wetted_surface_m2": 0.1487, "cold_first_call_ms": cold_ms,
               "relative_error_limit_percent": 2, "timing_limit_ms_exclusive": 50,
               "rows": rows, "warm_repetitions_per_fn": 100, "timing": timing}
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
