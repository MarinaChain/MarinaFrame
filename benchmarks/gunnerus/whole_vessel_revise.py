"""Re-run one Gunnerus whole-vessel part from a person's mark (thin wrapper).

The work is in ``vessel_reconstruction.part_revise`` (the app runs the same worker). This
wrapper only adds what a Gunnerus run folder made before 2026-11-09 lacks: the drawing views
(``whole_vessel/views.json``), from the Gunnerus host calibration and the source folder.

Load the keys in the same shell first (never print them)::

    source scripts/load_opencode_keys.sh
    PYTHONPATH=src python -m benchmarks.gunnerus.whole_vessel_revise --folder <run folder> \\
        --sources work/sources/gunnerus --part wheelhouse --note "What to change"
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from vessel_reconstruction import part_revise
from vessel_reconstruction.ship_measure import source_hash


def gunnerus_views(sources: Path) -> dict:
    """``whole_vessel/views.json`` of a Gunnerus GA run (benchmarks/gunnerus/whole_vessel.py VIEWS)."""
    from benchmarks.gunnerus.whole_vessel import GA_FILE, VIEWS

    drawing = (sources / GA_FILE).resolve()
    sha = source_hash(drawing)
    return {'schema': part_revise.VIEWS_SCHEMA, 'views': {
        name: {'kind': view.kind, 'file': str(drawing), 'sha256': sha, 'bounds': list(view.bounds),
               'origin': list(view.origin), 'metres_per_unit': view.metres_per_unit, 'y_down': False,
               'layers': view.layers}
        for name, view in VIEWS.items()}}


def write_views(folder: Path, sources: Path) -> Path:
    path = folder / part_revise.VIEWS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gunnerus_views(sources), indent=2) + '\n')
    return path


def revise(folder: Path, pack: dict | None, part_id: str, note: str, call=None, settings=None) -> dict:
    """Rebuild one part from a mark. ``pack`` (crops) is optional: without it the worker makes
    its own from ``whole_vessel/views.json``. ``settings`` is kept for older callers; the worker
    always uses ``part_revise.SETTINGS``. Refusals raise ``PartReviseError`` (a ValueError)."""
    return part_revise.revise_part(folder, part_id, note, call=call, pack=pack)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True, help='Run folder that holds whole_vessel/')
    parser.add_argument('--sources', type=Path, help='Gunnerus source folder; writes whole_vessel/views.json')
    parser.add_argument('--part', required=True)
    parser.add_argument('--note', required=True)
    args = parser.parse_args()
    folder = args.folder.resolve()
    if args.sources:
        write_views(folder, args.sources)
    started = time.time()
    entry = part_revise.revise_part(folder, args.part, args.note)
    print(json.dumps({'part': entry['id'], 'revision': entry['revision'], 'status': entry['status'],
                      'geometry': entry['geometry'], 'volume_m3': entry.get('volume_m3'),
                      'seconds': round(time.time() - started, 1)}, indent=2))


if __name__ == '__main__':
    main()
