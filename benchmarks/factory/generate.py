"""Deterministic generator of benchmark-factory cases.

Subcommands (run in this order; every step is a pure function of the committed code and the sources):

``hulls``   build the hull catalogue: canonical meshes, sealed truth tables, hull manifest.
``render``  draw every case (hull x degradation level) and write the specification.
``freeze``  hash everything and write the frozen split manifest, before any scoring.

Folders under ``work/factory`` (git-ignored; override with ``--root``):

    hulls/        canonical meshes and native shapes (generator side only)
    inputs/<case>/drawing.png, spec.json     the ONLY files that inference reads
    params/<case>.json                       every rendering parameter and seed
    sealed/truth/<hull>.npz                  truth tables; inference never reads this folder
    runs/<run>/<case>/...                    runner outputs

Committed manifests: ``benchmarks/factory/manifests/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from . import hulls as H
from . import render as R
from . import splits as S
from . import truth as T

ROOT = H.ROOT
DEFAULT_ROOT = ROOT / "work" / "factory"
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"
JOBS = 3  # native jobs at most, as the machine is shared


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> dict:
    run = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()  # noqa: E731
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


def station_curves(hull: H.Hull, fractions=R.STATION_FRACTIONS) -> list[R.Station]:
    stations = []
    for index, x in enumerate(T.station_positions(hull.length_m, fractions)):
        curves = R.clean_deck_edge(hull.drawn_section(x), hull.depth_m)
        stations.append(R.Station(f"s{index + 1:02d}", x, curves))
    return stations


def feasible(stations: list[R.Station], depth: float) -> bool:
    for station in stations:
        if not station.curves:
            return False
        longest = max(len(c) for c in station.curves)
        height = max(c[:, 1].max() for c in station.curves) - min(c[:, 1].min() for c in station.curves)
        if longest < 10 or height < 0.25 * depth:
            return False
    return True


# --- hulls -----------------------------------------------------------------------------------
def _entry(hull: H.Hull, split: str, root: Path) -> dict:
    record = T.build_truth(hull, root / "sealed" / "truth" / f"{hull.hull_id}.npz")
    H.cache_hull(hull, root / "hulls")
    provenance = {k: v for k, v in hull.provenance.items() if k not in ("native_bounds",)}
    return {"hull_id": hull.hull_id, "family": hull.family, "split": split, "length_m": hull.length_m,
            "depth_m": hull.depth_m, "max_half_breadth_m": hull.max_half_breadth_m, "half_hull": hull.half_hull,
            "draft_m": record["draft_m"], "provenance": provenance,
            "truth_sha256": sha256_file(root / "sealed" / "truth" / f"{hull.hull_id}.npz")}


def _build_named(args) -> dict | None:
    hull_id, root = args
    recipe = next(h for h in H.NAMED_HULLS if h.hull_id == hull_id)
    hull = H.load_named(recipe, root / "scratch" / hull_id)
    if not feasible(station_curves(hull), hull.depth_m):
        return {"hull_id": hull_id, "skipped": "infeasible sections"}
    return _entry(hull, S.NAMED_SPLITS[hull_id], root)


def _build_dsyhs(args) -> dict | None:
    member, root = args
    hull = H.load_dsyhs(member, root / "scratch" / Path(member).stem)
    if not feasible(station_curves(hull), hull.depth_m):
        return {"hull_id": hull.hull_id, "skipped": "infeasible sections"}
    return _entry(hull, S.DSYHS_SPLIT, root)


def _build_shipd_cluster(args) -> list[dict]:
    cluster, split, candidates, root = args
    entries, kept = [], 0
    for key, vector in candidates:
        if kept >= S.HULLS_PER_CLUSTER:
            break
        try:
            hull = H.load_shipd(key, vector, f"shipd-c{cluster:02d}")
            stations = station_curves(hull)
        except Exception as exc:  # recorded, not hidden
            entries.append({"hull_id": f"{key[0]}:{key[1]}", "skipped": f"{type(exc).__name__}: {exc}"})
            continue
        if not feasible(stations, hull.depth_m):
            entries.append({"hull_id": hull.hull_id, "skipped": "infeasible sections"})
            continue
        entries.append(_entry(hull, split, root))
        kept += 1
    return entries


def cmd_hulls(root: Path, jobs: int) -> None:
    started = time.perf_counter()
    entries = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        entries += list(pool.map(_build_named, [(h.hull_id, root) for h in H.NAMED_HULLS]))
        print(f"named hulls done {time.perf_counter() - started:.0f}s", flush=True)
        members = H.dsyhs_members()[::S.DSYHS_STRIDE]
        entries += list(pool.map(_build_dsyhs, [(m, root) for m in members]))
        print(f"DSYHS done {time.perf_counter() - started:.0f}s", flush=True)
        vectors, keys = H.shipd_vectors()
        labels = S.shipd_cluster_labels(vectors)
        split_of = S.cluster_splits()
        jobs_args = []
        for cluster in range(S.N_CLUSTERS):
            rows = S.candidate_rows(labels, cluster)
            jobs_args.append((cluster, split_of[cluster], [(keys[r], vectors[r]) for r in rows], root))
        for part in pool.map(_build_shipd_cluster, jobs_args):
            entries += part
    kept = [e for e in entries if "skipped" not in e]
    skipped = [e for e in entries if "skipped" in e]
    MANIFEST_DIR.mkdir(exist_ok=True)
    kept.sort(key=lambda e: e["hull_id"])
    (MANIFEST_DIR / "hulls.json").write_text(json.dumps({"hulls": kept, "skipped": skipped, "cluster_split": {
        str(k): v for k, v in S.cluster_splits().items()}, "seed": S.SEED}, indent=1) + "\n")
    print(json.dumps({"hulls": len(kept), "skipped": len(skipped), "seconds": time.perf_counter() - started}))


# --- cases -----------------------------------------------------------------------------------
def plan_cases(manifest: dict) -> list[dict]:
    cases = []
    for hull in manifest["hulls"]:
        layout = S.layout_for(hull["hull_id"])
        for level in S.LEVELS:
            case_id = f"{hull['hull_id']}-L{level}"
            cases.append({"case_id": case_id, "hull_id": hull["hull_id"], "family": hull["family"], "split": hull["split"],
                          "level": level, "layout": layout, "seed": S.case_seed(case_id)})
    return cases


def render_hull_cases(args) -> list[dict]:
    root, hull_id, cases = args
    hull = H.load_cached(root / "hulls", hull_id)
    stations = station_curves(hull)
    licence = hull.provenance.get("licence_terms") or "see hull manifest"
    results = []
    for case in cases:
        params = R.sample_params(case["level"], case["layout"], case["seed"])
        vessel_id = "factory-" + hashlib.sha256(case["case_id"].encode()).hexdigest()[:12]
        image, spec, record = R.make_case(stations, hull.depth_m, hull.max_half_breadth_m, hull.length_m, params, vessel_id,
                                          str(licence)[:200], "Synthetic body plan drawn from CAD sections (benchmark factory).")
        folder = root / "inputs" / case["case_id"]
        folder.mkdir(parents=True, exist_ok=True)
        from PIL import Image

        Image.fromarray(image).save(folder / "drawing.png", optimize=False, compress_level=6)
        spec["source"]["sha256"] = sha256_file(folder / "drawing.png")
        (folder / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")
        (root / "params").mkdir(exist_ok=True)
        (root / "params" / f"{case['case_id']}.json").write_text(json.dumps(
            {**case, "render": params, "geometry": record, "station_x_m": [s.x_m for s in stations]}, indent=1) + "\n")
        results.append({**case, "image_size": record["image_size"]})
    return results


def cmd_render(root: Path, jobs: int, only_split: str | None, limit: int | None) -> None:
    started = time.perf_counter()
    manifest = json.loads((MANIFEST_DIR / "hulls.json").read_text())
    cases = plan_cases(manifest)
    if only_split:
        cases = [c for c in cases if c["split"] == only_split]
    if limit:
        cases = cases[:limit]
    by_hull: dict[str, list] = {}
    for case in cases:
        by_hull.setdefault(case["hull_id"], []).append(case)
    tasks = [(root, h, c) for h, c in sorted(by_hull.items())]
    done = 0
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for results in pool.map(render_hull_cases, tasks):
            done += len(results)
            if done % 40 < 4:
                print(f"rendered {done}/{len(cases)} {time.perf_counter() - started:.0f}s", flush=True)
    print(json.dumps({"cases": done, "seconds": time.perf_counter() - started}))


def cmd_freeze(root: Path) -> None:
    manifest = json.loads((MANIFEST_DIR / "hulls.json").read_text())
    hulls_by_id = {h["hull_id"]: h for h in manifest["hulls"]}
    rows = []
    for case in plan_cases(manifest):
        folder = root / "inputs" / case["case_id"]
        params_file = root / "params" / f"{case['case_id']}.json"
        if not (folder / "drawing.png").exists():
            raise SystemExit(f"missing rendered case {case['case_id']}")
        params = json.loads(params_file.read_text())
        rows.append({**case, "drawing_sha256": sha256_file(folder / "drawing.png"),
                     "spec_sha256": sha256_file(folder / "spec.json"),
                     "params_sha256": sha256_file(params_file),
                     "truth_sha256": hulls_by_id[case["hull_id"]]["truth_sha256"],
                     "render": params["render"], "image_size": params["geometry"]["image_size"]})
    MANIFEST_DIR.mkdir(exist_ok=True)
    with (MANIFEST_DIR / "cases.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    counts: dict = {}
    for row in rows:
        counts.setdefault(row["split"], {"cases": 0, "hulls": set(), "families": set()})
        counts[row["split"]]["cases"] += 1
        counts[row["split"]]["hulls"].add(row["hull_id"])
        counts[row["split"]]["families"].add(row["family"])
    frozen = {"frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "generator_commit": git_head(),
              "seed": S.SEED, "cases_file": "cases.jsonl", "cases_sha256": sha256_file(MANIFEST_DIR / "cases.jsonl"),
              "hulls_sha256": sha256_file(MANIFEST_DIR / "hulls.json"),
              "splits": {k: {"cases": v["cases"], "hulls": len(v["hulls"]), "families": sorted(v["families"])}
                         for k, v in counts.items()},
              "rule": "A family is never split across development, validation and test; scoring has not started when this file is written."}
    (MANIFEST_DIR / "split_manifest.json").write_text(json.dumps(frozen, indent=1) + "\n")
    print(json.dumps({k: {"cases": v["cases"], "hulls": v["hulls"]} for k, v in frozen["splits"].items()}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["hulls", "render", "freeze"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--jobs", type=int, default=JOBS)
    parser.add_argument("--split")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.jobs > JOBS:
        raise SystemExit("at most 3 concurrent jobs on this machine")
    if args.command == "hulls":
        cmd_hulls(args.root, args.jobs)
    elif args.command == "render":
        cmd_render(args.root, args.jobs, args.split, args.limit)
    else:
        cmd_freeze(args.root)


if __name__ == "__main__":
    sys.exit(main())
