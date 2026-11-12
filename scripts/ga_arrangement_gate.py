"""Regression check of a GA development round with the arrangement step's gate (lane W).

For every ``ga_arrangement_input.json`` under a run folder: no space left without volume after
smaller spaces are cut out of it, no fragment labels, and no cargo space losing more than
``ga_scale.GATE_MAX_CARGO_LOSS`` of its volume (the round s3b limit). Prints one line per ship
(no per-space values) and exits 1 when a ship fails. Development ships only.

    PYTHONPATH=src python scripts/ga_arrangement_gate.py work/ga-internal-23/dev-runs/<round>
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from vessel_reconstruction.ga_scale_arrangement import arrangement_gate


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__)
        return 2
    failed = 0
    for path in sorted(Path(args[0]).glob("**/ga_arrangement_input.json")):
        data = json.loads(path.read_text())
        report = arrangement_gate(data)
        failed += not report["passed"]
        print(f"{data.get('case_id', path.parent.name)}: {'pass' if report['passed'] else 'FAIL'}; "
              f"without volume {len(report['no_volume'])}; fragments {len(report['fragments'])}; "
              f"guessed over cargo {len(report['guessed_over_cargo'])}; "
              f"largest cargo loss {report['max_cargo_loss']}; depth {report['depth_status']}"
              + (f"; warnings: {', '.join(report['warnings'])}" if report["warnings"] else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
