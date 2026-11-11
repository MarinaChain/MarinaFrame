"""Three arms on a sample of the benchmark factory DEVELOPMENT split (never validation or sealed).

``prepare --root DIR``  rebuild the truth and drawings of the sample hulls with the frozen
                        factory code (benchmarks/factory) and check every drawing hash against
                        manifests/cases.jsonl; inputs go to DIR/<case>/input
``score --root DIR``    score every arm that left a model (verified model.step or draft
                        model-draft.step) with the factory scorer and its predeclared gate
                        (RMS station half-breadth <= 2 % of the half-beam, volume within range <= 5 %)

Run the arms with ``arms.py batch --root DIR --sheets <cases> --arms abstain,draft,llm``.
The sample: the first 6 overlay hulls and the first 4 separate-layout hulls of the
development split by hull id, each at all four degradation levels (40 cases).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from benchmarks.factory import generate as G  # noqa: E402
from benchmarks.factory import hulls as H  # noqa: E402
from benchmarks.factory import report as RP  # noqa: E402
from benchmarks.factory import splits as S  # noqa: E402
from benchmarks.factory import truth as T  # noqa: E402

MANIFESTS = ROOT / "benchmarks" / "factory" / "manifests"
OVERLAY_HULLS, SEPARATE_HULLS = 6, 4


def sample() -> list[dict]:
    hulls = json.loads((MANIFESTS / "hulls.json").read_text())["hulls"]
    development = sorted((h for h in hulls if h["split"] == "development"), key=lambda h: h["hull_id"])
    overlay = [h for h in development if S.layout_for(h["hull_id"]) == "overlay"][:OVERLAY_HULLS]
    separate = [h for h in development if S.layout_for(h["hull_id"]) == "separate"][:SEPARATE_HULLS]
    return overlay + separate


def _build(entry: dict, root: Path):
    provenance = entry["provenance"]
    if provenance.get("source") == "shipd":
        vectors, keys = H.shipd_vectors()
        row = keys.index((provenance["set"], provenance["row"]))
        hull = H.load_shipd(keys[row], vectors[row], provenance["family_cluster"])
    else:
        recipe = next(h for h in H.NAMED_HULLS if h.hull_id == entry["hull_id"])
        hull = H.load_named(recipe, root / "scratch" / entry["hull_id"])
    if hull.hull_id != entry["hull_id"]:
        raise SystemExit(f"rebuilt hull {hull.hull_id} is not {entry['hull_id']}")
    G._entry(hull, entry["split"], root)
    truth = root / "sealed" / "truth" / f"{hull.hull_id}.npz"
    if G.sha256_file(truth) != entry["truth_sha256"]:
        raise SystemExit(f"{hull.hull_id}: truth hash differs from the frozen manifest")


def prepare(root: Path) -> dict:
    cases = {json.loads(line)["case_id"]: json.loads(line) for line in (MANIFESTS / "cases.jsonl").read_text().splitlines()}
    planned = G.plan_cases({"hulls": sample()})
    prepared = []
    for entry in sample():
        _build(entry, root)
        hull_cases = [c for c in planned if c["hull_id"] == entry["hull_id"]]
        for case in G.render_hull_cases((root, entry["hull_id"], hull_cases)):
            rendered = root / "inputs" / case["case_id"]
            if G.sha256_file(rendered / "drawing.png") != cases[case["case_id"]]["drawing_sha256"]:
                raise SystemExit(f"{case['case_id']}: drawing hash differs from the frozen manifest")
            target = root / case["case_id"] / "input"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(rendered), str(target))
            prepared.append({"case_id": case["case_id"], "layout": case["layout"], "level": case["level"]})
    shutil.rmtree(root / "scratch", ignore_errors=True)
    shutil.rmtree(root / "hulls", ignore_errors=True)
    (root / "sample.json").write_text(json.dumps(prepared, indent=1) + "\n")
    return {"cases": len(prepared), "case_ids": [c["case_id"] for c in prepared]}


def score(root: Path) -> dict:
    rows = []
    for case in json.loads((root / "sample.json").read_text()):
        params = json.loads((root / "params" / f"{case['case_id']}.json").read_text())
        stations = [{"id": f"s{i + 1:02d}", "x_m": x} for i, x in enumerate(params["station_x_m"])]
        for arm in ("abstain", "draft", "llm"):
            run = root / case["case_id"] / arm
            if not (run / "summary.json").exists():
                continue
            summary = json.loads((run / "summary.json").read_text())
            status = json.loads((run / "controller_stdout.json").read_text() or "{}")
            candidate = status.get("current_candidate") or {}
            model = None
            if candidate.get("path"):
                folder = run / "task" / candidate["path"]
                model = next((folder / n for n in ("model.step", "model-draft.step") if (folder / n).exists()), None)
            row = {"case_id": case["case_id"], "layout": case["layout"], "level": case["level"], "arm": arm,
                   "status": summary["status"], "sections_with_line": summary["sections_with_line"],
                   "guess_kinds": summary["guess_kinds"], "model": model is not None, "correct": False}
            if model is not None:
                result = T.score_model(root / "sealed" / "truth" / f"{params['hull_id']}.npz", model, stations)
                if result.get("status") == "scored":
                    hb = result["truth"]["max_half_breadth_m"]
                    main = result["summary"].get("half_breadth_main")
                    volume = result["hydrostatics_at_design_draft"]["volume_error_relative_within_range"]
                    row["rms_pct_half_beam"] = 100 * main["rms_of_station_rms_m"] / hb if main else None
                    row["volume_error_within_range"] = volume
                    row["correct"] = bool(main and row["rms_pct_half_beam"] <= 100 * RP.RMS_GATE_FRACTION
                                          and volume is not None and abs(volume) <= RP.VOLUME_GATE)
                else:
                    row["score_status"] = result.get("status")
            rows.append(row)
    (root / "scores.json").write_text(json.dumps(rows, indent=1) + "\n")
    return {"rows": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["prepare", "score", "cases"])
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.root)
    elif args.command == "score":
        result = score(args.root)
    else:
        result = ",".join(c["case_id"] for c in json.loads((args.root / "sample.json").read_text()))
    print(json.dumps(result) if not isinstance(result, str) else result)


if __name__ == "__main__":
    main()
