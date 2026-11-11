"""Summarize W12 measurements and unique provider receipts after evaluation.

Run from the worktree root: python -m benchmarks.llm_setup_review.summarize
The evidence root is work/w12; final compact reports go to outputs/llm_setup_review.
"""
from pathlib import Path
import hashlib
import json

import numpy as np

ROOT = Path("work/w12")
OUT = Path("outputs/llm_setup_review")


def summarize():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(path.read_text()) for path in sorted((ROOT / "setup-evaluation").glob("*.json"))
            if path.name != "results.json"]
    metrics = {}
    for key in ["centreline_x_px", "baseline_y_px", "pixels_per_metre"]:
        values = [value[key] for row in rows if row.get("layout_truth") == "separate"
                  for value in row.get("values", [])]
        error = "relative_error" if key == "pixels_per_metre" else "absolute_error_px"
        available = [value[error] for value in values if value.get(error) is not None]
        checked = [value[error] for value in values if value.get("checked") and value.get(error) is not None]
        metrics[key] = {
            "proposed": len(available), "total_panels": len(values), "checked": len(checked),
            "median_error": float(np.median(available)) if available else None,
            "p90_error": float(np.percentile(available, 90)) if available else None,
            "checked_median_error": float(np.median(checked)) if checked else None,
        }
    receipts = {}
    for path in ROOT.rglob("receipts/*.json"):
        receipt = json.loads(path.read_text())
        if receipt.get("purpose") in {"sheet_setup", "build_review"}:
            receipts[receipt["request_id"]] = (path, receipt)
    usage = {"requests": len(receipts), "states": {}, "prompt_tokens": 0, "completion_tokens": 0,
             "observed_cost_usd": 0.0, "list_cost_usd": 0.0, "missing_cost": 0, "images": 0}
    inventory = []
    for request_id, (path, receipt) in sorted(receipts.items()):
        state = receipt["state"]
        usage["states"][state] = usage["states"].get(state, 0) + 1
        for key in ["prompt_tokens", "completion_tokens"]:
            usage[key] += receipt.get("usage", {}).get(key, 0)
        cost = receipt.get("observed_cost_usd")
        usage["observed_cost_usd"] += cost or 0
        usage["missing_cost"] += cost is None
        usage["list_cost_usd"] += receipt.get("usage", {}).get("list_cost", 0)
        usage["images"] += len(receipt.get("images", []))
        inventory.append({"request_id": request_id, "file": str(path),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "purpose": receipt["purpose"], "state": state,
                          "usage": receipt.get("usage", {}), "images": receipt.get("images", [])})
    for entry in inventory:
        reading = Path(entry["file"]).parent.parent
        suffix = reading.name.removeprefix("reading-")
        request = reading.parent / f"request-{suffix}" / "request.json"
        if request.exists():
            manifest = json.loads(request.read_text())
            entry["request_manifest"] = str(request)
            entry["image_geometry"] = [
                {key: image[key] for key in ["image_id", "sha256", "bytes", "width", "height", "crop_box_px"]}
                for image in manifest["images"]
            ]
    counts = {"panel_count_exact_separate": 0, "station_labels_exact_cases": 0,
              "units_missing_cases": 0, "symmetry_port_starboard_cases": 0, "datum_baseline_cases": 0}
    box_errors = []
    for row in rows:
        case = row["case_id"]
        path = ROOT / "setup-evaluation" / case / "proposal.json"
        if not path.exists():
            continue
        overview = json.loads(path.read_text())["overview"]
        labels = [station["label"] for station in overview.get("stations", [])]
        counts["station_labels_exact_cases"] += labels == [str(i) for i in range(1, 10)]
        counts["units_missing_cases"] += "missing" in overview.get("units", {})
        counts["symmetry_port_starboard_cases"] += overview.get("symmetry", {}).get("value") == "port_starboard"
        counts["datum_baseline_cases"] += overview.get("vertical_datum", {}).get("value") == "baseline"
        if row.get("layout_truth") != "separate":
            continue
        truth = json.loads((ROOT / "factory/inputs" / case / "spec.json").read_text())
        counts["panel_count_exact_separate"] += len(overview.get("panels", [])) == len(truth["sections"])
        for panel, section in zip(overview.get("panels", []), truth["sections"]):
            box_errors.extend(abs(a - b) for a, b in zip(panel["box_px"], section["roi_px"]))
    counts["panel_box_corner_median_absolute_error_px"] = float(np.median(box_errors)) if box_errors else None
    counts["panel_box_corner_p90_absolute_error_px"] = float(np.percentile(box_errors, 90)) if box_errors else None
    summary = {
        "per_value_counts": counts, "development_cases": len(rows),
        "case_errors": sum("error" in row for row in rows),
        "layout_correct": sum(row.get("layout_proposed") == {"separate": "separate_panels", "overlay": "overlaid_body_plan"}.get(row.get("layout_truth")) for row in rows),
        "station_positions_missing": sum(row.get("station_positions_missing", 0) for row in rows),
        "specs_ready": sum(row.get("spec_ready", False) for row in rows),
        "metrics_separate_only": metrics, "usage": usage,
    }
    for name, value in [("summary", summary), ("case_results", rows), ("receipt_inventory", inventory)]:
        (OUT / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    summarize()
