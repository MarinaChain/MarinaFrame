"""Replay stored dev builds without and with hull fairing (docs/HULL_FAIRING.md 3).

Each build's recorded section inputs (``extracted_sections.json``) are rebuilt with the current
builder, as recorded ("before") and faired ("after"), and scored with the frozen factory scorer
against DEVELOPMENT truth (``work/factory-3view``). BUE GIRL is scored at its truth cells. Never
use this on sealed data. Outputs stay outside the repository.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_fairing.replay --out work/hull-fairing/replay.json
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path

import numpy as np

from benchmarks.factory import truth
from scripts import round_digest
from vessel_reconstruction import fairing, geometry

MAIN = Path(__file__).resolve().parents[2]
WORK = Path("/Users/jonathanjie/Documents/workspace/MarinaFrame/work")
FACTORY = WORK / "factory-3view"
ROUNDS = ("round-3view-L0-sonnet-4f92e9f", "round-3view-L1-sonnet-4f92e9f")
BUE_GIRL_CASE = WORK / "autocal-live-6" / "bue_girl"
BUE_GIRL_TRUTH = Path("/private/tmp/claude-501/bue-girl/truth_s2.json")
# Injected bad cell (docs/HULL_FAIRING.md 3.4): added at mid-height, tapering linearly to zero over
# this fraction of the section height on each side.
CELL_HALF_SPAN = 0.05


def delivered_build(case_dir: Path) -> Path:
    step = round_digest.latest_valid_draft_step(round_digest.load_events(case_dir), case_dir)
    return step.parent


def stored_builds(case_dir: Path) -> list[Path]:
    return sorted(p for p in (case_dir / "task/domain/builds").iterdir()
                  if p.name.startswith(("first-", "r0")) and (p / "extracted_sections.json").exists())


def load_sections(build: Path) -> list[dict]:
    return json.loads((build / "extracted_sections.json").read_text())["sections"]


def build_step(sections: list[dict], folder: Path) -> Path:
    shape, _ = geometry.build_hull(sections, fit_complexity=True)
    path = folder / "model.step"
    shape.exportStep(str(path))
    return path


def factory_score(case: str, step: Path) -> dict:
    params = json.loads((FACTORY / "params" / f"{case}.json").read_text())
    stations = [{"id": f"s{i + 1:02d}", "x_m": x} for i, x in enumerate(params["station_x_m"])]
    result = truth.score_model(FACTORY / "sealed" / "truth" / f"{round_digest.truth_hull_name(case)}.npz",
                               step, stations)
    rms = 100 * result["summary"]["half_breadth_main"]["rms_of_station_rms_m"] / result["truth"]["max_half_breadth_m"]
    volume = 100 * result["hydrostatics_at_design_draft"]["volume_error_relative_within_range"]
    return {"rms_pct": rms, "volume_pct": volume, "passes": rms <= 2.0 and abs(volume) <= 5.0}


def bue_girl_score(sections: list[dict]) -> dict:
    from benchmarks.auto_calibration import live_score
    from benchmarks.bue_girl import holdout_value
    table = live_score.hull_table({"table": {"stations": sections}})
    scored = holdout_value.score(table, holdout_value.load_truth(BUE_GIRL_TRUTH))
    return scored


def injected(sections: list[dict], station_id: str, amount_m: float, whole: bool = False) -> list[dict]:
    """Sections with a bad cell (or a whole station shifted) at ``station_id``."""
    result = []
    for section in sections:
        if section.get("id") == station_id:
            points = np.asarray(section["points_yz_m"], dtype=float)
            z = points[:, 1]
            t = (z - z.min()) / (z.max() - z.min())
            bump = np.full(len(t), amount_m) if whole else amount_m * np.clip(1 - np.abs(t - 0.5) / CELL_HALF_SPAN, 0, 1)
            if not whole and not np.any(np.isclose(t, 0.5)):
                # Put a point at mid-height so the cell's peak is a vertex of the polyline.
                mid = z.min() + 0.5 * (z.max() - z.min())
                points = np.vstack([points, [np.interp(mid, z, points[:, 0]), mid]])
                points = points[np.argsort(points[:, 1])]
                z = points[:, 1]
                t = (z - z.min()) / (z.max() - z.min())
                bump = amount_m * np.clip(1 - np.abs(t - 0.5) / CELL_HALF_SPAN, 0, 1)
            points[:, 0] = np.where(points[:, 0] > 0, points[:, 0] + bump, 0)
            section = {**section, "points_yz_m": points.tolist()}
        result.append(section)
    return result


def half_breadth_at_mid(sections: list[dict], station_id: str) -> float:
    section = next(s for s in sections if s.get("id") == station_id)
    points = np.asarray(section["points_yz_m"], dtype=float)
    points = points[np.argsort(points[:, 1])]
    mid = points[0, 1] + 0.5 * (points[-1, 1] - points[0, 1])
    return float(np.interp(mid, points[:, 1], points[:, 0]))


def robustness(sections: list[dict], options: dict) -> list[dict]:
    """How far the faired section moves at an injected bad cell or misread station."""
    traced = sorted((s for s in sections if s.get("source_label") in ("traced", "read")), key=lambda s: s["x_m"])
    if len(traced) < 3:
        return []
    x0 = min(s["x_m"] for s in sections)
    length = max(s["x_m"] for s in sections) - x0
    targets = {}
    for name, share in (("midship", 0.5), ("quarter", 0.25)):
        targets[name] = min(traced, key=lambda s: abs((s["x_m"] - x0) / length - share))["id"]
    base, _ = fairing.fair_sections(sections, **options)
    half_beam = fairing._half_beam(fairing._parse(sections))
    rows = []
    for name, station_id in targets.items():
        for kind, amount, whole in (("cell +0.2 m", 0.2, False), ("cell +5 % half-beam", .05 * half_beam, False),
                                    ("station +5 % half-beam", .05 * half_beam, True)):
            bad = injected(sections, station_id, amount, whole)
            faired, _ = fairing.fair_sections(bad, **options)
            moved = half_breadth_at_mid(faired, station_id) - half_breadth_at_mid(base, station_id)
            rows.append({"place": name, "station": station_id, "kind": kind, "injected_m": amount,
                         "current_moves_m": half_breadth_at_mid(bad, station_id) - half_breadth_at_mid(sections, station_id),
                         "faired_moves_m": moved, "share": moved / amount})
    return rows


def replay_case(case_dir: Path, build: Path, options: dict, *, bue_girl: bool = False, robust: bool = False) -> dict:
    sections = load_sections(build)
    faired, report = fairing.fair_sections(sections, **options)
    half_beam = report.get("parameters", {}).get("half_beam_m")
    row = {"case": case_dir.name, "build": build.name, "applied": report["applied"],
           "moves_by_label": report.get("moves_by_label"), "check_items": len(report["check_items"]),
           "fairness_before": fairing.fairness_metrics(sections, half_beam),
           "fairness_after": fairing.fairness_metrics(faired, half_beam)}
    if bue_girl:
        row["before"], row["after"] = bue_girl_score(sections), bue_girl_score(faired)
    else:
        with tempfile.TemporaryDirectory() as folder:
            row["before"] = factory_score(case_dir.name, build_step(sections, Path(folder)))
        with tempfile.TemporaryDirectory() as folder:
            row["after"] = factory_score(case_dir.name, build_step(faired, Path(folder)))
    if robust:
        row["robustness"] = robustness(sections, options)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--all-builds", action="store_true", help="every first-hull and revision build")
    parser.add_argument("--fairing-length", type=float, default=fairing.FAIRING_LENGTH_SPACINGS)
    parser.add_argument("--no-keep-ends", action="store_true")
    parser.add_argument("--robustness", action="store_true")
    parser.add_argument("--cases", nargs="*", help="case names to run (default all)")
    args = parser.parse_args()
    options = {"fairing_length_spacings": args.fairing_length,
               "keep_ends": not args.no_keep_ends}
    rows = []
    case_dirs = [d for r in ROUNDS for d in sorted((WORK / r).glob("*-L?"))]
    if args.cases:
        case_dirs = [d for d in case_dirs if d.name in args.cases]
    for case_dir in case_dirs:
        builds = stored_builds(case_dir) if args.all_builds else [delivered_build(case_dir)]
        for build in builds:
            row = replay_case(case_dir, build, options, robust=args.robustness)
            rows.append(row)
            print(f"{row['case']:24s} {row['build']:22s} {row['before']['rms_pct']:6.2f} -> {row['after']['rms_pct']:6.2f} "
                  f"vol {row['before']['volume_pct']:+5.1f} -> {row['after']['volume_pct']:+5.1f}", flush=True)
    if not args.cases or "bue_girl" in args.cases:
        row = replay_case(BUE_GIRL_CASE, delivered_build(BUE_GIRL_CASE), options, bue_girl=True, robust=args.robustness)
        rows.append(row)
        print("bue_girl", json.dumps({k: row[k] for k in ("before", "after")}, default=str)[:400], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"options": options, "rows": rows, "engineering_approved": False},
                                   indent=1, default=str))


if __name__ == "__main__":
    main()
