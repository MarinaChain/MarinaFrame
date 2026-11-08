"""Replay the section edits of recorded W18d rounds through the current combined fit score.

For each run case the script rebuilds the anchored first hull from the
saved domain state, then applies the model's ``propose_section`` edits in
their recorded order. Each edit is scored with the current keep rule
(``whole_vessel_score.keep_edit`` plus the controller's ink protection) and
with truth (RMS station half-breadth error, % of the truth half-beam).
Kept edits are applied for the next step; rejected ones are not.

Usage::

    python benchmarks/score_alignment_replay.py --out work/w19b2/replay-before.json \
        work/w17/runs/w18d-corrected work/w17/runs/w18d-step4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import score_alignment as sa  # noqa: E402


def recorded_edits(task: Path, state: dict) -> list[dict]:
    """The propose_section edits of a task in order: section, curve, and the recorded decision."""
    events = sorted((task / "events").glob("*.json"))
    proposals, arguments = [], {}
    for path in events:
        event = json.loads(path.read_text())
        payload = event.get("payload", {})
        if payload.get("operation") != "propose_section":
            continue
        if event.get("kind") == "worker_intent":
            arguments = json.loads((task / payload["request"]["path"]).read_text()).get("arguments") or {}
        elif event.get("kind") == "worker_result":
            receipt = json.loads((task / payload["receipt"]["path"]).read_text())
            proposals.append({"result": receipt.get("result") or {}, "arguments": arguments})
    # Authored candidates in the order they were written.
    authored_dir = task / "domain" / "authored"
    authored = sorted(authored_dir.glob("*.json"), key=lambda p: p.stat().st_mtime_ns)
    curves = {}
    for path in authored:
        # Rejected edits are dropped from the restored catalog; the authored file keeps the curve.
        record = json.loads(path.read_text())
        if "authored" in record:
            curves.setdefault(record["section_id"], []).append((record["candidate_id"],
                                                                 record["authored"]["points_yz_m"]))
    used = {sid: 0 for sid in curves}
    edits = []
    for proposal in proposals:
        result = proposal["result"]
        sid = result.get("section_id") or proposal["arguments"].get("section_id")
        comparison = result.get("fit_comparison") or {}
        if sid is None or sid not in curves:
            continue
        candidate_id = result.get("candidate_id")
        if candidate_id is None:
            if result.get("repeated_proposal"):
                continue
            index = min(used[sid], len(curves[sid]) - 1)
            candidate_id, curve = curves[sid][index]
        else:
            curve = next(c for cid, c in curves[sid] if cid == candidate_id)
        used[sid] = [cid for cid, _ in curves[sid]].index(candidate_id) + 1
        edits.append({"section_id": sid, "candidate_id": candidate_id, "curve": np.asarray(curve, dtype=float),
                      "recorded_keep": bool(comparison.get("keep", result.get("status") != "kept_previous_curve")),
                      "recorded_fit_before": comparison.get("fit_before"),
                      "recorded_fit_after": comparison.get("fit_after")})
    return edits


def first_hull(state: dict) -> dict:
    table = state["vessel_table"]
    first = {s["id"]: s for s in state["first_hull_spec"]["sections"]}
    curves = {}
    for row in table["stations"]:
        authored = first.get(row["id"], {}).get("authored")
        curves[row["id"]] = np.asarray(authored["points_yz_m"] if authored else row["points_yz_m"], dtype=float)
    return curves


def replay_case(case_dir: Path) -> dict:
    task = case_dir / "task"
    state = json.loads((task / "domain" / "state.json").read_text())
    name = case_dir.name
    case = sa.load_case({"case": name, "kind": "body", "dir": str(sa.BODY_FACTORY / "inputs" / name),
                         "truth": str(sa.BODY_FACTORY / "sealed" / "truth" / (name.rsplit("-L", 1)[0] + ".npz"))})
    half_beam = float(state["score_half_beam_m"])
    views = case["views_body"]
    hull = first_hull(state)
    waterlines = state["vessel_table"]["z_m"]  # the controller keeps the first hull's waterlines
    current = sa.score_hull(hull, case, views, half_beam, waterlines)
    steps = [{"step": "first_hull", "fit": current["combined_fit"], "truth_pct": sa.hull_truth_pct(hull, case)}]
    for edit in recorded_edits(task, state):
        proposal = {**hull, edit["section_id"]: edit["curve"]}
        after = sa.score_hull(proposal, case, views, half_beam, waterlines)
        truth_before = sa.hull_truth_pct(hull, case)
        truth_after = sa.hull_truth_pct(proposal, case)
        keep = sa.controller_keep(current, after, edit["section_id"])
        steps.append({"step": "kept" if keep else "rejected", "section_id": edit["section_id"],
                      "candidate_id": edit["candidate_id"], "fit_before": current["combined_fit"],
                      "fit_after": after["combined_fit"], "truth_before_pct": round(truth_before, 3),
                      "truth_after_pct": round(truth_after, 3),
                      "truth_worse": truth_after > truth_before + sa.TRUTH_TIE_PCT,
                      "recorded_keep": edit["recorded_keep"], "recorded_fit_before": edit["recorded_fit_before"],
                      "recorded_fit_after": edit["recorded_fit_after"]})
        if keep:
            hull, current = proposal, after
    final_truth = sa.hull_truth_pct(hull, case)
    return {"case": name, "run": case_dir.parent.name, "first_truth_pct": round(steps[0]["truth_pct"], 3),
            "final_truth_pct": round(final_truth, 3), "steps": steps,
            "false_keeps": sum(1 for s in steps[1:] if s["step"] == "kept" and s["truth_worse"]),
            "true_rejects": sum(1 for s in steps[1:] if s["step"] == "rejected" and s["truth_worse"])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    results = []
    for run in args.runs:
        for case_dir in sorted(p for p in run.iterdir() if (p / "task" / "domain" / "state.json").exists()):
            state = json.loads((case_dir / "task" / "domain" / "state.json").read_text())
            if not state.get("first_hull_spec") or not state.get("vessel_table"):
                continue
            results.append(replay_case(case_dir))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1, default=float))
    for r in results:
        print(f"{r['run']:16s} {r['case']:18s} truth {r['first_truth_pct']:6.2f} -> {r['final_truth_pct']:6.2f} %  "
              f"false keeps {r['false_keeps']}")
        for s in r["steps"][1:]:
            print(f"    {s['section_id']} {s['step']:8s} fit {s['fit_before']} -> {s['fit_after']} "
                  f"(recorded {s['recorded_fit_before']} -> {s['recorded_fit_after']}, keep {s['recorded_keep']})  "
                  f"truth {s['truth_before_pct']} -> {s['truth_after_pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
