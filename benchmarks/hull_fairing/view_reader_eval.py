"""Plan/profile evidence error against development truth: old reader against view_reader_v2.

Development data only (work/factory-3view truth; never work/factory-sealed-*).
The readers see only the drawing, the intake regions and the stored scale; truth
is opened here, after reading, to score the evidence.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_fairing.view_reader_eval --split fit \
        --old work/view-reader-v2/old-evidence --output work/view-reader-v2/eval-fit.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.hull_fairing.collect_three_view import PROTOCOL_PATH
from benchmarks.hull_fairing.replay import FACTORY, ROUNDS, WORK, delivered_build
from scripts import round_digest
from vessel_reconstruction import draft_fit, view_measure, view_reader_v2

# A height within this of a truth waterline names that waterline.
HEIGHT_MATCH_M = 0.15


# --------------------------------------------------------------------------
# Truth lookups (development truth lines)
# --------------------------------------------------------------------------

def _crossings(pieces, value, along: int, across: int) -> list[float]:
    found = []
    for piece in pieces:
        p = np.asarray(piece, dtype=float)
        a, b = p[:-1], p[1:]
        hit = (np.minimum(a[:, along], b[:, along]) <= value) & (value <= np.maximum(a[:, along], b[:, along])) \
            & (a[:, along] != b[:, along])
        t = (value - a[hit, along]) / (b[hit, along] - a[hit, along])
        found += list(a[hit, across] + t * (b[hit, across] - a[hit, across]))
    return found


class Truth:
    def __init__(self, case: str):
        hull = round_digest.truth_hull_name(case)
        self.lines = json.loads((FACTORY / "sealed" / "lines" / f"{hull}.json").read_text())
        self.params = json.loads((FACTORY / "params" / f"{case}.json").read_text())
        self.waterlines = {float(w["z_m"]): w["xy_m"] for w in self.lines["waterlines"]}
        deck = np.asarray(self.lines["deck_xyz_m"], dtype=float)
        self.deck = deck[np.argsort(deck[:, 0])]
        self.half_beam = float(self.lines["max_half_breadth_m"])
        with np.load(FACTORY / "sealed" / "truth" / f"{hull}.npz") as grid:
            self.grid = {key: grid[key] for key in ("x_m", "z_m", "half_breadth")}

    def waterline_y(self, z: float, x: float) -> float:
        ys = _crossings(self.waterlines[z], x, 0, 1)
        return float(max(ys)) if ys else float("nan")

    def deck_y(self, x: float) -> float:
        if not self.deck[0, 0] <= x <= self.deck[-1, 0]:
            return float("nan")
        return float(np.interp(x, self.deck[:, 0], self.deck[:, 1]))

    def deck_z(self, x: float) -> float:
        if not self.deck[0, 0] <= x <= self.deck[-1, 0]:
            return float("nan")
        return float(np.interp(x, self.deck[:, 0], self.deck[:, 2]))

    def nearest_height(self, z: float) -> float | None:
        best = min(self.waterlines, key=lambda h: abs(h - z))
        return best if abs(best - z) <= HEIGHT_MATCH_M else None

    def profile_z(self, x: float, which: str) -> float:
        """Keel (lowest section point, keel_xz_m) or deck-at-side height (deck_xyz_m) at x."""
        if which == "top":
            return self.deck_z(x)
        for piece in self.lines["keel_xz_m"]:
            p = np.asarray(piece, dtype=float)
            if p[0, 0] <= x <= p[-1, 0]:
                return float(np.interp(x, p[:, 0], p[:, 1]))
        return float("nan")

    def profile_x(self, z: float, which: str) -> float:
        """Stern or stem x at height z: midpoint of the truth grid step where breadth starts (0.5 m grid)."""
        zs = self.grid["z_m"]
        if not zs[0] <= z <= zs[-1]:
            return float("nan")
        j = int(np.clip(np.searchsorted(zs, z), 1, len(zs) - 1))
        share = (z - zs[j - 1]) / (zs[j] - zs[j - 1])
        breadth = (1 - share) * self.grid["half_breadth"][:, j - 1] + share * self.grid["half_breadth"][:, j]
        present = np.flatnonzero(breadth > 0)
        xs = self.grid["x_m"]
        if not len(present):
            return float("nan")
        if which == "stern":
            i = present[0]
            return float(xs[i] if i == 0 else 0.5 * (xs[i - 1] + xs[i]))
        i = present[-1]
        return float(xs[i] if i == len(xs) - 1 else 0.5 * (xs[i] + xs[i + 1]))


# --------------------------------------------------------------------------
# Scoring one point set
# --------------------------------------------------------------------------

def _stats(errors) -> dict:
    values = np.asarray([e for e in errors if np.isfinite(e)], dtype=float)
    if not len(values):
        return {"n": 0, "rms_m": None, "max_m": None, "median_abs_m": None}
    return {"n": int(len(values)), "rms_m": float(np.sqrt(np.mean(values ** 2))),
            "max_m": float(np.max(np.abs(values))), "median_abs_m": float(np.median(np.abs(values)))}


def _curve_key(claimed) -> str:
    return "deck" if claimed == "deck" else f"wl_{claimed:g}"


def score_points(points: list[dict], truth: Truth) -> dict:
    result = _score_points(points, truth)
    labels = sorted({p["source_label"] for p in points if p["view"] == "half_breadth_plan"})
    result["plan"]["by_source_label"] = {
        label: {k: v for k, v in _score_points([p for p in points if p["view"] != "half_breadth_plan"
                                               or p["source_label"] == label], truth)["plan"].items()
                if k != "by_curve"} for label in labels}
    return result


def _score_points(points: list[dict], truth: Truth) -> dict:
    plan = [p for p in points if p["view"] == "half_breadth_plan"]
    by_curve, identity, unscored = {}, [], 0
    for point in plan:
        x, y = point["x_m"], point["y_m"]
        candidates = {h: truth.waterline_y(h, x) for h in truth.waterlines}
        candidates["deck"] = truth.deck_y(x)
        candidates = {k: v for k, v in candidates.items() if np.isfinite(v)}
        if point["target"] == "deck":
            claimed = "deck"
        else:
            claimed = truth.nearest_height(point["z_m"])
        if claimed is None or claimed not in candidates:
            # A height that is no truth waterline, or a waterline the hull lacks at x.
            identity.append(False)
            key = "spurious_height" if claimed is None else f"{_curve_key(claimed)}_absent"
            by_curve.setdefault(key, []).append(float("nan"))
            unscored += 1
            continue
        error = y - candidates[claimed]
        nearest = min(candidates, key=lambda k: abs(candidates[k] - y))
        identity.append(nearest == claimed or abs(candidates[nearest] - candidates[claimed]) < 1e-3
                        or abs(error) <= 0.01 * truth.half_beam)
        key = _curve_key(claimed)
        by_curve.setdefault(key, []).append(error)
    all_errors = [e for errors in by_curve.values() for e in errors]
    profile = {}
    for target in ("keel", "top", "stem", "stern"):
        errors = []
        for p in points:
            if p["view"] != "profile" or p["target"] != target:
                continue
            if target in ("keel", "top"):
                errors.append(p["z_m"] - truth.profile_z(p["x_m"], target))
            else:
                errors.append(p["x_m"] - truth.profile_x(p["z_m"], target))
        profile[target] = _stats(errors)
    return {"plan": {"points": len(plan), "all": _stats(all_errors),
                     "by_curve": {k: {**_stats(v), "points": len(v)} for k, v in sorted(by_curve.items())},
                     "identity_correct": int(sum(identity)), "identity_share": float(np.mean(identity)) if identity else None,
                     "unscored_identity": unscored,
                     "within_1pct_half_beam": float(np.mean([abs(e) <= .01 * truth.half_beam for e in all_errors
                                                             if np.isfinite(e)])) if all_errors else None,
                     "negative": int(sum(p["y_m"] < 0 for p in plan))},
            "profile": profile}


def heights_score(heights: list[float], truth: Truth) -> dict:
    true = [float(z) for z in truth.params["waterline_z_m"]]
    matched = {t: min(heights, key=lambda h: abs(h - t)) for t in true if heights
               and min(abs(h - t) for h in heights) <= HEIGHT_MATCH_M}
    spurious = [h for h in heights if all(abs(h - t) > HEIGHT_MATCH_M for t in true)]
    return {"truth": true, "read": [round(h, 3) for h in heights], "matched": len(matched),
            "missing": len(true) - len(matched), "spurious": len(spurious),
            "max_error_m": max((abs(v - t) for t, v in matched.items()), default=None)}


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------

def case_inputs(case_dir: Path):
    domain = case_dir / "task/domain"
    build = delivered_build(case_dir)
    intake = json.loads((domain / "input/intake.json").read_text())
    spec = json.loads((build / "input_spec.json").read_text())
    hints = next(p["regions"] for p in intake["pages"] if p["page_id"] == intake["spec_page_id"])
    grey = view_measure.load_grey(domain / "input/source.png")
    ppm = float(spec["sections"][0]["calibration"]["pixels_per_metre"])
    return build, grey, draft_fit.reference_views(grey, hints, ppm)


def old_points(old_dir: Path, case: str, build: str) -> tuple[list[dict], dict, list[float]]:
    record = json.loads((old_dir / f"{case}--{build}.json").read_text())
    points = [p for p in record["points"] if p["view"] != "body_plan"]
    heights = record["views"].get("profile", {}).get("waterlines_z_m", [])
    return points, record["coverage"], heights


def new_points(grey, views) -> tuple[list[dict], dict, list[float], dict]:
    reading = view_reader_v2.read_views(grey, views)
    points, coverage = view_reader_v2.evidence_points(reading)
    heights = [w["z_m"] for w in reading["profile"].waterlines] if reading.get("profile") else []
    return points, coverage, heights, reading


def draw_overlay(grey, reading, points, path: Path) -> None:
    """New reader's plan curves and profile keel/top drawn on the sheet (for inspection)."""
    from PIL import Image, ImageDraw
    image = Image.fromarray(np.clip(grey, 0, 255).astype(np.uint8)).convert("RGB")
    draw = ImageDraw.Draw(image)
    colours = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180), (70, 240, 240),
               (240, 50, 230), (128, 128, 0), (0, 128, 128)]
    profile, plan = reading["profile"], reading["plan"]
    pv = profile.view
    for column in range(len(profile.x_m)):
        for values, colour in ((profile.keel_z_m, (230, 25, 75)), (profile.top_z_m, (0, 130, 200))):
            if np.isfinite(values[column]):
                x, y = pv.sheet_xy(column + 0.5, profile.baseline_row - values[column] * profile.ppm)
                draw.point((x, y), fill=colour)
    for w in profile.waterlines:
        x0, y0 = pv.sheet_xy(0, w["row"])
        x1, y1 = pv.sheet_xy(pv.crop.shape[1], w["row"])
        draw.line((x0, y0, x1, y1), fill=(60, 180, 75) if w["grid_row"] else (245, 130, 48))
    if plan is not None:
        v = plan.view
        x0, y0 = v.sheet_xy(0, plan.centre_row)
        x1, y1 = v.sheet_xy(v.crop.shape[1], plan.centre_row)
        draw.line((x0, y0, x1, y1), fill=(0, 200, 0))
        for index, (cid, curve) in enumerate(plan.curves.items()):
            colour = colours[index % len(colours)]
            for column, y in enumerate(curve["y_m"]):
                if np.isfinite(y):
                    x, row = v.sheet_xy(column + 0.5, plan.centre_row - y * plan.ppm)
                    draw.point((x, row), fill=colour)
                elif curve["status"][column].startswith("abstain"):
                    x, row = v.sheet_xy(column + 0.5, plan.centre_row + 3 + index)
                    draw.point((x, row), fill=colour)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def evaluate(split: str, old_dir: Path, overlays: Path | None) -> dict:
    protocol = json.loads(PROTOCOL_PATH.read_text())
    rows = []
    for name in protocol[f"{split}_cases"]:
        if name == "bue_girl":
            rows.append({"case": name, "available": False,
                         "reason": "intake has only a body-plan region; no plan or profile view to read"})
            continue
        case_dir = WORK / ROUNDS[int(name[-1])] / name
        build, grey, views = case_inputs(case_dir)
        truth = Truth(name)
        o_points, o_coverage, o_heights = old_points(old_dir, name, build.name)
        n_points, n_coverage, n_heights, reading = new_points(grey, views)
        if overlays is not None:
            draw_overlay(grey, reading, n_points, overlays / f"{name}.png")
        old_plan = o_coverage.get("half_breadth_plan", {})
        rows.append({"case": name, "build": build.name, "available": True,
                     "old": {**score_points(o_points, truth), "heights": heights_score(o_heights, truth),
                             "coverage": o_coverage,
                             "plan_abstention_share": (old_plan.get("missing", 0) / old_plan["attempted"])
                             if old_plan.get("attempted") else None},
                     "new": {**score_points(n_points, truth), "heights": heights_score(n_heights, truth),
                             "coverage": n_coverage, "plan_abstention_share": _abstention(n_coverage),
                             "slope": reading.get("slope")}})
        print(name, json.dumps({k: {"plan": rows[-1][k]["plan"]["all"], "id": rows[-1][k]["plan"]["identity_share"],
                                    "heights": rows[-1][k]["heights"]["read"]} for k in ("old", "new")}), flush=True)
    return {"split": split, "settings": view_reader_v2.SETTINGS, "rows": rows, "engineering_approved": False}


def _abstention(coverage: dict) -> float | None:
    plan = coverage.get("half_breadth_plan", {})
    if not plan.get("attempted"):
        return None
    return sum(plan["abstained"].values()) / plan["attempted"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("fit", "check"), required=True)
    parser.add_argument("--old", type=Path, required=True, help="old-reader evidence folder (collect_three_view)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlays", type=Path)
    args = parser.parse_args()
    result = evaluate(args.split, args.old, args.overlays)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1, allow_nan=False, default=float) + "\n")


if __name__ == "__main__":
    main()
