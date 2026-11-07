"""Run W12 development setup readings; compare truth only after each reading."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from benchmarks.llm_setup_review.sample import SETUP_SAMPLE_HULLS, SETUP_SAMPLE_LEVELS
from vessel_reconstruction.llm_setup import run_setup, seen, write_json


def evaluate(root: Path, out: Path, binary: Path, basis: str, jobs=2):
    out.mkdir(parents=True, exist_ok=False)
    cases = [f"{h}-L{level}" for h in SETUP_SAMPLE_HULLS for level in SETUP_SAMPLE_LEVELS]

    def one(case):
        directory = out / case
        try:
            report = run_setup(root / "inputs" / case / "drawing.png", directory, binary, basis)
            proposal = json.loads((directory / "proposal.json").read_text()) if (directory / "proposal.json").exists() else {}
            # Truth is intentionally first opened after the model calls finish.
            truth = json.loads((root / "inputs" / case / "spec.json").read_text())
            params = json.loads((root / "params" / f"{case}.json").read_text())
            overview = proposal.get("overview", {})
            rows = []
            for index, panel in enumerate(overview.get("panels", [])):
                if index >= len(truth["sections"]):
                    break
                target = truth["sections"][index]
                answer = proposal.get("panels", {}).get(panel["panel_id"], {})
                checked = report.get("panels", {}).get(panel["panel_id"], {})
                row = {"panel_id": panel["panel_id"], "mapping": "reading_order; not asserted for overlay layouts"}
                for key, target_key in [("centreline_x_px", "centerline_px"), ("baseline_y_px", "baseline_px")]:
                    value = seen(answer.get(key))
                    row[key] = {"proposed": value, "truth": target["calibration"][target_key],
                                "absolute_error_px": abs(value - target["calibration"][target_key]) if value is not None else None,
                                "checked": checked.get(key, {}).get("checked", False)}
                ppm = checked.get("pixels_per_metre", {}).get("value")
                row["pixels_per_metre"] = {"proposed": ppm, "truth": params["geometry"]["ppm"],
                                           "relative_error": abs(ppm / params["geometry"]["ppm"] - 1) if ppm else None,
                                           "checked": checked.get("pixels_per_metre", {}).get("checked", False)}
                rows.append(row)
            result = {"case_id": case, "split": params["split"], "layout_truth": params["layout"],
                      "layout_proposed": seen(overview.get("layout")), "panels_truth": len(truth["sections"]),
                      "panels_proposed": len(overview.get("panels", [])), "stations_proposed": len(overview.get("stations", [])),
                      "station_positions_missing": sum(seen(s.get("position")) is None for s in overview.get("stations", [])),
                      "units": overview.get("units"), "symmetry": overview.get("symmetry"), "datum": overview.get("vertical_datum"),
                      "values": rows, "failures": report.get("failures"), "usage": report.get("usage", {}),
                      "spec_ready": report.get("spec_ready", False)}
        except Exception as error:
            result = {"case_id": case, "error": str(error)}
        write_json(out / f"{case}.json", result)
        print(json.dumps({"case_id": case, "error": result.get("error"), "panels": result.get("panels_proposed")}), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(one, cases))
    write_json(out / "results.json", results)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--basis", required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    evaluate(args.root, args.out, args.binary, args.basis, args.jobs)


if __name__ == "__main__":
    main()
