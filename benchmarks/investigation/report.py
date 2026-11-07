"""Collect W11 paired results without discarding failed or unbuilt cases.

Only development inputs belong here. Images stay in work/: provider-transfer
permission does not authorize redistribution of drawing derivatives.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .arms import summarize


def collect(root: Path, live_folder: str = "v2-llm") -> list[dict]:
    rows = []
    for sheet in sorted(root.iterdir()):
        inputs = sheet / "input"
        if not (inputs / "spec.json").exists():
            continue
        for arm, folder in (("abstain", "final-abstain"), ("draft", "final-draft"), ("llm", live_folder)):
            run = sheet / folder
            if not (run / "arm_record.json").exists():
                continue
            summary = summarize(run, inputs, None, None)
            receipts = []
            for path in sorted((run / "task" / "receipts").glob("request-*.json")):
                receipt = json.loads(path.read_text())
                receipts.append({key: receipt.get(key) for key in (
                    "request_id", "state", "returned_model", "completion_id", "http_status",
                    "response_sha256", "request_sha256", "prompt_sha256", "usage",
                    "observed_cost_usd", "latency_seconds", "error_code", "images")})
            rows.append({"case_id": sheet.name, "arm": arm, "run": str(run),
                         **summary, "provider_receipts": receipts})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live-folder", default="v2-llm")
    args = parser.parse_args()
    rows = collect(args.root, args.live_folder)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps({"rows": len(rows), "out": str(args.out)}))


if __name__ == "__main__":
    main()
