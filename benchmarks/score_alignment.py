"""Does the label-free combined fit score agree with truth on model-like edits?

W19b2. No model runs here. For each development case (body-plan factory
``work/w17/factory`` and three-view factory ``work/factory-3view``) the script
makes hulls from the case truth: the truth hull, a few "first hulls" with
realistic station errors, and many one-station edits from each of them
(shift, scale, height shift, station swap, grid-line substitution, partial
stroke bridging, authored neighbour blends, bumps, truncated tops, smooth
trace noise, and repairs towards truth). Each hull is scored with the
combined fit (``whole_vessel_score.score_table``) and with truth (RMS of the
station half-breadth error, % of the truth half-beam).

Reported per case and overall:

* pairwise agreement: for each edit from a base hull, does "score improves"
  agree with "truth improves" (edits whose truth change is below
  ``TRUTH_TIE_PCT`` are ties and not counted);
* false keeps: edits the keep rule accepts although truth gets worse;
* Spearman rank correlation of the score and truth over all hulls of a case.

Usage::

    python benchmarks/score_alignment.py --out work/w19b2/eval-before.json [--cases 'shipd-1-00679*']

Truth files are read only to compute the reference metric; the score never
sees them.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vessel_reconstruction import view_measure  # noqa: E402
from vessel_reconstruction.fit_feedback import measurement_table  # noqa: E402
from vessel_reconstruction.vessel_model import StationRow, VesselTable, waterline_grid  # noqa: E402
from vessel_reconstruction.whole_vessel_score import keep_edit, score_table  # noqa: E402

WORK = Path("/Users/jonathanjie/Documents/workspace/MarinaFrame/work")
BODY_FACTORY = WORK / "w17" / "factory"
THREE_VIEW_FACTORY = WORK / "factory-3view"
# Truth changes smaller than this (% of the truth half-beam) are ties.
TRUTH_TIE_PCT = 0.05
# Edits whose truth change is at most this (% B/2) count as "small".
SMALL_EDIT_PCT = 1.0
# Number of "first hull" bases with realistic errors, besides the truth hull.
ERROR_BASES = 2
# One-station edits scored per station and base (repairs always; the rest sampled).
EDITS_PER_STATION = 14
# Body-plan grid column spacing assumed for grid-line substitution (metres).
GRID_STEP_M = 2.0
# Samples of a resampled station curve.
CURVE_SAMPLES = 120
# Controller ink protection (agent_tools): a station whose ink near-fraction is
# at least this keeps its curve unless the new curve has no worse ink RMS.
INK_PROTECT_NEAR = 0.9


# --------------------------------------------------------------------------
# Cases and truth
# --------------------------------------------------------------------------

def list_cases(pattern: str) -> list[dict]:
    cases = []
    for factory, kind in ((BODY_FACTORY, "body"), (THREE_VIEW_FACTORY, "three_view")):
        for case_dir in sorted((factory / "inputs").iterdir()):
            if any(fnmatch.fnmatch(case_dir.name, one) for one in pattern.split(",")):
                cases.append({"case": case_dir.name, "kind": kind, "dir": str(case_dir),
                              "truth": str(factory / "sealed" / "truth"
                                           / (case_dir.name.rsplit("-L", 1)[0].replace("-3v", "") + ".npz"))})
    return cases


def truth_curve(truth: dict, x_m: float) -> np.ndarray:
    """Station curve (y, z) of the truth at x: the outer half-breadth at each truth height."""
    index = int(np.argmin(np.abs(truth["x_m"] - x_m)))
    hb, z = truth["half_breadth"][index], truth["z_m"]
    return from_function(hb, z)


def station_truth_error(curve: np.ndarray, truth: dict, x_m: float) -> float:
    """RMS half-breadth error (m) of one station curve on the truth height grid."""
    index = int(np.argmin(np.abs(truth["x_m"] - x_m)))
    reference = truth["half_breadth"][index]
    built = view_measure.outer_half_breadth(curve, truth["z_m"])
    built = np.nan_to_num(built, nan=0.0)
    return float(np.sqrt(np.mean((built - reference) ** 2)))


def hull_truth_pct(curves: dict, case: dict) -> float:
    """RMS over stations of the station RMS, % of the truth half-beam (the round digest's scale)."""
    errors = [station_truth_error(curves[s["id"]], case["truth_data"], s["x_m"]) for s in case["sections"]]
    return 100.0 * float(np.sqrt(np.mean(np.square(errors)))) / case["truth_half_beam_m"]


# --------------------------------------------------------------------------
# Curve edits
# --------------------------------------------------------------------------

def as_function(curve: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Outer half-breadth of a curve at heights z (0 outside the curve)."""
    return np.nan_to_num(view_measure.outer_half_breadth(curve, z), nan=0.0)


def from_function(y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Station curve from half-breadths at heights z: from the keel point on the centreline up to the
    highest height with breadth (the deck edge); no points above the hull."""
    keep = np.flatnonzero(y > 1e-6)
    if not len(keep):
        return np.array([[0.0, z[0]], [0.0, z[-1]]])
    first, last = max(0, keep[0] - 1), keep[-1]
    points = np.column_stack([np.maximum(y[first:last + 1], 0.0), z[first:last + 1]])
    points[0, 0] = 0.0
    return points


def heights(curve: np.ndarray) -> np.ndarray:
    return np.linspace(curve[:, 1].min(), curve[:, 1].max(), CURVE_SAMPLES)


def variants(sid: str, base: dict, case: dict, rng: np.random.Generator) -> list[tuple[str, np.ndarray]]:
    """One-station edits of a base hull: (edit type, new curve)."""
    order = [s["id"] for s in case["sections"]]
    index = order.index(sid)
    truth = case["truth_curves"][sid]
    current = base[sid]
    half_beam = case["truth_half_beam_m"]
    z = heights(truth)
    y_truth = as_function(truth, z)
    y_now = as_function(current, z)
    top, depth = float(z[-1]), float(z[-1] - z[0])
    edits = []
    if not np.allclose(y_now, y_truth, atol=1e-4):
        edits.append(("repair_full", truth))
        for share in (0.25, 0.5, 0.75):
            edits.append((f"repair_{share}", from_function(y_now + share * (y_truth - y_now), z)))
    for pct in (0.5, 1.0, 2.0, 4.0, 8.0):
        sign = rng.choice([-1.0, 1.0])
        edits.append((f"shift_{pct}", from_function(np.where(y_now > 0, y_now + sign * pct / 100 * half_beam, 0), z)))
    for factor in (0.97, 1.03, 0.9, 1.1):
        edits.append((f"scale_{factor}", from_function(y_now * factor, z)))
    for dz_pct in (-3.0, 3.0):
        dz = dz_pct / 100 * depth
        edits.append((f"zshift_{dz_pct}", from_function(np.interp(z - dz, z, y_now, left=0.0, right=y_now[-1]), z)))
    for neighbour in (index - 1, index + 1):
        if 0 <= neighbour < len(order):
            edits.append(("swap_truth_neighbour", case["truth_curves"][order[neighbour]]))
            edits.append(("swap_base_neighbour", base[order[neighbour]]))
    # Grid-line substitution: the trace runs up a grid column near the hull.
    mid = y_truth[len(z) // 2]
    column = max(GRID_STEP_M, GRID_STEP_M * round(mid / GRID_STEP_M))
    edits.append(("grid_full", np.array([[0.0, z[0]], [column, z[0]], [column, top]])))
    split = z[0] + rng.uniform(0.3, 0.7) * depth
    below = z <= split
    grid_top = np.vstack([np.column_stack([y_truth[below], z[below]]), [[column, split], [column, top]]])
    edits.append(("grid_upper", from_polyline(grid_top)))
    # Partial stroke bridged by straight lines.
    za, zb = sorted(rng.uniform(0.15, 0.85, 2) * depth + z[0])
    inside = (z >= za) & (z <= zb)
    if inside.sum() >= 3:
        stroke = np.column_stack([y_truth[inside], z[inside]])
        bridged = np.vstack([[[0.0, z[0]]], stroke, [[y_truth[-1], top]]])
        edits.append(("partial_bridge", from_polyline(bridged)))
        stroke_now = np.column_stack([y_now[inside], z[inside]])
        edits.append(("partial_bridge_base", from_polyline(np.vstack([[[0.0, z[0]]], stroke_now, [[y_now[-1], top]]]))))
    # Authored blend of the neighbours' current curves, with a fullness factor (the model's "blend").
    if 0 < index < len(order) - 1:
        low, high = as_function(base[order[index - 1]], z), as_function(base[order[index + 1]], z)
        for fullness in (0.95, 1.0, 1.05):
            edits.append((f"blend_{fullness}", from_function(0.5 * (low + high) * fullness, z)))
    # Local bump (a wrong stroke for part of the height).
    for amp_pct in (2.0, 6.0):
        centre = z[0] + rng.uniform(0.2, 0.9) * depth
        bump = amp_pct / 100 * half_beam * rng.choice([-1, 1]) * np.exp(-0.5 * ((z - centre) / (0.08 * depth)) ** 2)
        edits.append((f"bump_{amp_pct}", from_function(np.where(y_now > 0, y_now + bump, 0), z)))
    # Top read short or long (labels at the top of the body plan).
    for cut in (0.9, 0.97):
        keep = z <= z[0] + cut * depth
        edits.append((f"top_short_{cut}", from_function(y_now[keep], z[keep])))
    # Smooth trace jitter of about 1-2 px.
    ppm = case["ppm"]
    jitter = np.convolve(rng.normal(0, 1.5 / ppm, len(z) + 20), np.ones(9) / 9, mode="same")[10:-10] * 3
    edits.append(("jitter", from_function(np.where(y_now > 0, y_now + jitter, 0), z)))
    return edits


def from_polyline(points: np.ndarray) -> np.ndarray:
    """A polyline section with strictly rising heights (the table needs a z-sorted row)."""
    points = np.asarray(points, dtype=float)
    z = np.linspace(points[:, 1].min(), points[:, 1].max(), CURVE_SAMPLES)
    return from_function(as_function(points, z), z)


def error_base(case: dict, rng: np.random.Generator, strength: float) -> dict:
    """A "first hull": truth with 2-4 stations replaced by realistic wrong curves."""
    base = dict(case["truth_curves"])
    order = [s["id"] for s in case["sections"]]
    count = int(rng.integers(2, 5))
    for sid in rng.choice(order, size=count, replace=False):
        options = [v for v in variants(sid, base, case, rng) if not v[0].startswith("repair")]
        weights = np.array([strength if v[0].startswith(("grid", "partial", "swap", "shift_4", "shift_8", "bump_6"))
                            else 1.0 for v in options])
        pick = rng.choice(len(options), p=weights / weights.sum())
        base[sid] = options[pick][1]
    return base


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def load_case(case: dict) -> dict:
    case = dict(case)
    case_dir = Path(case["dir"])
    case["spec"] = json.loads((case_dir / "spec.json").read_text())
    case["sections"] = [{"id": s["id"], "x_m": float(s["x_m"])} for s in case["spec"]["sections"]]
    truth = np.load(case["truth"])
    case["truth_data"] = {k: truth[k] for k in ("x_m", "z_m", "half_breadth")}
    case["truth_half_beam_m"] = float(np.nanmax(truth["half_breadth"]))
    case["truth_curves"] = {s["id"]: truth_curve(case["truth_data"], s["x_m"]) for s in case["sections"]}
    case["grey"] = view_measure.load_grey(case_dir / "drawing.png")
    case["ppm"] = float(case["spec"]["sections"][0]["calibration"]["pixels_per_metre"])
    case["views_body"] = view_measure.views_from_spec(case["spec"])
    if case["kind"] == "three_view":
        case["views_three"] = view_measure.views_from_three_view(json.loads((case_dir / "views.json").read_text()))
    return case


def score_hull(curves: dict, case: dict, views: dict, half_beam_m: float, waterlines=None) -> dict:
    """Combined fit of a hull. ``waterlines`` stay fixed across a case's edits, as in the live
    controller (its table keeps the first hull's waterlines); default: the hull's own grid."""
    rows = [StationRow(s["id"], s["x_m"], np.asarray(curves[s["id"]]).tolist(), "fitted") for s in case["sections"]]
    table = VesselTable(rows, waterlines if waterlines is not None else waterline_grid(rows))
    board = score_table(measurement_table(table), views, case["grey"], half_beam_m=half_beam_m, overlays=False)
    return {"combined_fit": board["combined_fit"], "cells": board["cells"], "half_beam_m": board["half_beam_m"],
            "station_ink_fit": board["station_ink_fit"], "board": board}


def controller_keep(before: dict, after: dict, sid: str) -> bool:
    """The live controller's decision (agent_tools.execute): keep rule plus ink protection."""
    decision = keep_edit(before["board"], after["board"], before["cells"], after["cells"])
    old_ink = before["station_ink_fit"].get(sid) or {}
    new_ink = after["station_ink_fit"].get(sid) or {}
    if old_ink.get("near_fraction", 0) >= INK_PROTECT_NEAR and old_ink.get("rms_m") is not None:
        if (new_ink.get("rms_m") if new_ink.get("rms_m") is not None else float("inf")) > old_ink["rms_m"] + 1e-6:
            return False
    return bool(decision["keep"])


def evaluate_case(case_ref: dict) -> dict:
    started = time.time()
    case = load_case(case_ref)
    seed = int.from_bytes(case["case"].encode()[:8].ljust(8, b"\0"), "little") % (2 ** 32)
    rng = np.random.default_rng(seed)
    modes = [("body", case["views_body"])]
    if case["kind"] == "three_view":
        modes.append(("three_view", case["views_three"]))
    bases = [("truth", dict(case["truth_curves"]))]
    for k in range(ERROR_BASES):
        bases.append((f"first{k + 1}", error_base(case, rng, strength=1.0 + 2.0 * k)))
    # A label-free half-beam per case, as the controller fixes it from its first hull.
    half_beam = max(float(np.max(np.asarray(c)[:, 0])) for c in bases[1][1].values())
    first_rows = [StationRow(s["id"], s["x_m"], np.asarray(bases[1][1][s["id"]]).tolist(), "fitted")
                  for s in case["sections"]]
    waterlines = waterline_grid(first_rows)
    results = {mode: {"pairs": [], "hulls": []} for mode, _ in modes}
    for base_name, base in bases:
        base_truth = hull_truth_pct(base, case)
        base_scores = {mode: score_hull(base, case, views, half_beam, waterlines) for mode, views in modes}
        for mode, _ in modes:
            results[mode]["hulls"].append({"base": base_name, "truth_pct": base_truth,
                                           "fit": base_scores[mode]["combined_fit"]})
        for section in case["sections"]:
            sid = section["id"]
            edits = variants(sid, base, case, rng)
            repairs = [e for e in edits if e[0].startswith("repair")]
            others = [e for e in edits if not e[0].startswith("repair")]
            picked = rng.choice(len(others), size=min(len(others), EDITS_PER_STATION - len(repairs)), replace=False)
            for edit_type, curve in repairs + [others[k] for k in sorted(picked)]:
                edited = {**base, sid: curve}
                truth_pct = hull_truth_pct(edited, case)
                for mode, views in modes:
                    after = score_hull(edited, case, views, half_beam, waterlines)
                    before = base_scores[mode]
                    results[mode]["hulls"].append({"base": base_name, "truth_pct": truth_pct,
                                                   "fit": after["combined_fit"]})
                    # Each edit is also scored backwards (undoing it), so improving and
                    # worsening edits are balanced and the keep rule meets both.
                    for direction, (a, b, ta, tb) in (("forward", (before, after, base_truth, truth_pct)),
                                                      ("reverse", (after, before, truth_pct, base_truth))):
                        results[mode]["pairs"].append({
                            "base": base_name, "station": sid, "edit": edit_type, "direction": direction,
                            "truth_before": ta, "truth_after": tb,
                            "fit_before": a["combined_fit"], "fit_after": b["combined_fit"],
                            "keep": bool(keep_edit(a["board"], b["board"], a["cells"], b["cells"])["keep"]),
                            "controller_keep": controller_keep(a, b, sid)})
    return {"case": case["case"], "kind": case["kind"], "seconds": round(time.time() - started, 1),
            "modes": {mode: {"summary": summarize(r["pairs"], r["hulls"]), **r} for mode, r in results.items()}}


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def spearman(a, b) -> float | None:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return None
    ra, rb = np.argsort(np.argsort(a[ok])), np.argsort(np.argsort(b[ok]))
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def summarize(pairs: list[dict], hulls: list[dict]) -> dict:
    def stats(selected):
        decided = [p for p in selected if p["fit_before"] is not None and p["fit_after"] is not None
                   and abs(p["truth_after"] - p["truth_before"]) >= TRUTH_TIE_PCT]
        if not decided:
            return {"pairs": 0}
        forward = [p for p in decided if p.get("direction", "forward") == "forward"]
        agree = [(p["fit_after"] > p["fit_before"]) == (p["truth_after"] < p["truth_before"]) for p in forward]
        worse = [p for p in decided if p["truth_after"] > p["truth_before"]]
        better = [p for p in decided if p["truth_after"] < p["truth_before"]]
        return {"pairs": len(forward), "agreement": round(float(np.mean(agree)), 4) if agree else None,
                "worsening_edits": len(worse),
                "false_keep_rate": round(float(np.mean([p["keep"] for p in worse])), 4) if worse else None,
                "controller_false_keep_rate": (round(float(np.mean([p["controller_keep"] for p in worse])), 4)
                                               if worse else None),
                "improving_edits": len(better),
                "true_keep_rate": round(float(np.mean([p["keep"] for p in better])), 4) if better else None,
                "controller_true_keep_rate": (round(float(np.mean([p["controller_keep"] for p in better])), 4)
                                              if better else None)}
    small = [p for p in pairs if abs(p["truth_after"] - p["truth_before"]) <= SMALL_EDIT_PCT]
    near_good = [p for p in pairs if min(p["truth_before"], p["truth_after"]) <= 5.0
                 and abs(p["truth_after"] - p["truth_before"]) <= SMALL_EDIT_PCT]
    first_hulls = [p for p in pairs if p["base"] != "truth"]
    return {"all": stats(pairs), "small_edits": stats(small), "small_near_good_hull": stats(near_good),
            "from_first_hulls": stats(first_hulls),
            "spearman_fit_vs_minus_truth": spearman([h["fit"] if h["fit"] is not None else np.nan for h in hulls],
                                                     [-h["truth_pct"] for h in hulls])}


def pooled(results: list[dict]) -> dict:
    out = {}
    for mode in ("body", "three_view"):
        pairs = [p for r in results if mode in r["modes"] for p in r["modes"][mode]["pairs"]]
        if not pairs:
            continue
        spearmans = [r["modes"][mode]["summary"]["spearman_fit_vs_minus_truth"] for r in results if mode in r["modes"]]
        spearmans = [s for s in spearmans if s is not None]
        summary = summarize(pairs, [])
        summary.pop("spearman_fit_vs_minus_truth")
        summary["median_case_spearman"] = round(float(np.median(spearmans)), 4) if spearmans else None
        by_edit = {}
        for p in pairs:
            by_edit.setdefault(p["edit"].split("_")[0], []).append(p)
        summary["by_edit"] = {k: summarize(v, [])["all"] for k, v in sorted(by_edit.items())}
        out[mode] = summary
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", default="*", help="comma-separated case name patterns")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args(argv)
    cases = list_cases(args.cases)
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(evaluate_case, cases))
    report = {"method": "w19b2_score_alignment_v1", "truth_tie_pct": TRUTH_TIE_PCT, "pooled": pooled(results),
              "cases": [{"case": r["case"], "kind": r["kind"], "seconds": r["seconds"],
                         **{m: v["summary"] for m, v in r["modes"].items()}} for r in results]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1))
    pairs_path = args.out.with_suffix(".pairs.jsonl")
    with pairs_path.open("w") as handle:
        for r in results:
            for mode, v in r["modes"].items():
                for p in v["pairs"]:
                    handle.write(json.dumps({"case": r["case"], "mode": mode, **p}) + "\n")
    print(json.dumps(report["pooled"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
