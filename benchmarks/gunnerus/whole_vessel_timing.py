"""Stage timing of a full Gunnerus whole-vessel build (docs/plans/2026-11-11-build-speed.md).

Wraps the stage functions by name (no source change) and runs the normal entry points
(``whole_vessel.main`` for step 1, ``whole_vessel_assembly.main``). Outputs are drawing
derivatives: keep them in a git-ignored folder::

    PYTHONPATH=src:. python -m benchmarks.gunnerus.whole_vessel_timing step1 \\
        --sources work/sources/gunnerus --out work/build-speed/run/step1 [--in-process] [--profile P]
    PYTHONPATH=src:. python -m benchmarks.gunnerus.whole_vessel_timing assembly \\
        --sources work/sources/gunnerus --step1 work/build-speed/run/step1 --out work/build-speed/run/asm

Writes ``<out>-timings.json``: cumulative seconds and calls per wrapped stage (stages overlap).
``--profile P`` also writes a cProfile file (cProfile misattributes time around OCP calls).
"""
from __future__ import annotations

import cProfile
import json
import sys
import time
from collections import defaultdict
from functools import wraps
from pathlib import Path

TIMES: dict = defaultdict(float)
CALLS: dict = defaultdict(int)


def wrap(module, name, label=None):
    original = getattr(module, name)
    label = label or f'{module.__name__.split(".")[-1]}.{name}'

    @wraps(original)
    def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            TIMES[label] += time.perf_counter() - started
            CALLS[label] += 1
    setattr(module, name, timed)


def option(argv, name):
    return Path(argv[argv.index(name) + 1]) if name in argv else None


def main() -> None:
    stage, argv = sys.argv[1], sys.argv[2:]
    profile_path = option(argv, '--profile')
    if profile_path:
        index = argv.index('--profile')
        argv = argv[:index] + argv[index + 2:]
    out = option(argv, '--out').resolve()
    if stage == 'step1':
        from benchmarks.gunnerus import whole_vessel as entry
        from benchmarks.gunnerus import whole_vessel_appendages, whole_vessel_detail
        from vessel_reconstruction import ship_cad, ship_cad_worker
        wrap(entry, 'build_inputs')
        wrap(whole_vessel_appendages, 'add_appendages')
        wrap(whole_vessel_detail, 'add_detail')
        wrap(ship_cad_worker, 'run', 'worker.run (sandboxed, all parts)')
        wrap(ship_cad, 'execute', 'ship_cad.execute (in process, all parts)')
    elif stage == 'assembly':
        import cadquery
        from benchmarks.gunnerus import vector_path
        from benchmarks.gunnerus import whole_vessel_assembly as entry
        from vessel_reconstruction import display_mesh, geometry
        for name in ('build_hull', 'build_hull_to_deck', 'read_shape', 'export_all', 'write_app_parts', 'render'):
            wrap(entry, name)
        wrap(vector_path, 'read_sections')
        wrap(vector_path, '_build_regions')
        wrap(geometry, 'precise_volume_mm3')
        wrap(geometry, 'build_region_hull')
        wrap(display_mesh, 'shape_mesh')
        wrap(display_mesh, 'write_glb')
        wrap(cadquery.exporters, 'export', 'cadquery.exporters.export (STEP)')
    else:
        raise SystemExit(f'unknown stage {stage}')
    sys.argv = [entry.__file__] + argv
    started = time.perf_counter()
    if profile_path:
        profiler = cProfile.Profile()
        profiler.runcall(entry.main)
        profiler.dump_stats(str(profile_path))
    else:
        entry.main()
    total = time.perf_counter() - started
    record = {'stage': stage, 'total_seconds': round(total, 3),
              'stages': {label: {'seconds': round(TIMES[label], 3), 'calls': CALLS[label]} for label in TIMES}}
    (out.parent / f'{out.name}-timings.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2), file=sys.stderr)


if __name__ == '__main__':
    main()
