"""Replay a cited L1 engine-table arithmetic check, not ship validation.

Run from the worktree with PYTHONPATH=src. Supply the ignored JSON transcription
from main work/weights/engine-reference-table.json. No third-party values are
bundled in this script; tables retain their own source citations.
"""
import argparse
import json
from pathlib import Path

from vessel_reconstruction.weights_efficiency.engine import EngineLayout, EngineRequest, select_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    row = json.loads(args.table.read_text())
    basis = row.pop("basis")
    row["sources"] = tuple(row["sources"])
    layout = EngineLayout(**row)
    # Fixed sensitivity example, not inferred ship service margins.
    sea_margin = .15
    engine_margin = .10
    request = EngineRequest(layout.sfoc_rating_kw * (1-engine_margin) / (1+sea_margin),
                            layout.sfoc_rating_rpm, sea_margin, engine_margin,
                            ("source-table arithmetic check; margins are illustrative",))
    matches = select_engine(request, (layout,))
    if len(matches) != 1:
        raise ValueError("source rating is not feasible in its own layout/SFOC table")
    result = matches[0].to_record_fragment()
    result["table_basis"] = basis
    result["validation_scope"] = "Source-table arithmetic only; not the public-ship gate."
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("Source-table check completed; public-ship validation is separate.")


if __name__ == "__main__":
    main()
