"""The model question on the sheets code cannot settle (confidence below VISION_BELOW, no file name).

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.drawing_set.evaluate_vision TYPES.json --out FILE

Uses the Claude CLI on the subscription (claude-sonnet-5-5), one small picture per sheet; receipts go to
work/drawing_set/receipts/claude.jsonl. Reports the model's accuracy on those sheets and the combined accuracy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vessel_reconstruction.calibration_reading import claude_ask
from vessel_reconstruction.sheet_types import VISION_BELOW, vision_type

from .common import SOURCES, load_gray

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("types")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    rows = json.loads(Path(args.types).read_text())["rows"]
    ask = claude_ask(receipts=Path("work/drawing_set/receipts"))
    unsure = [r for r in rows if r["no_name"]["confidence"] < VISION_BELOW]
    out = []
    for row in unsure:
        gray, _ = load_gray(SOURCES / row["file"])
        answer = vision_type(gray, ask)
        out.append({"file": row["file"], "label": row["label"], "code": row["no_name"]["type"],
                    "model": answer["type"] if answer else None, "model_confidence": answer["confidence"] if answer else None})
        Path(args.out).write_text(json.dumps(out, indent=1))
    answered = [o for o in out if o["model"]]
    print(json.dumps({"asked": len(out), "answered": len(answered),
                      "code_right": sum(o["code"] == o["label"] for o in out),
                      "model_right": sum(o["model"] == o["label"] for o in answered)}))
