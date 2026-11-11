"""Generate the three-view (``lines_3view``) development set.

Run from the repository root (also from a linked worktree)::

    python -m benchmarks.factory.generate_lines            # render the set
    python -m benchmarks.factory.generate_lines --verify   # check every file hash in the manifest

Hulls: development hulls of the v1 factory only (never sealed v2/v3 hulls). Every hull is drawn at
levels L0-L3. Data goes to the main checkout's ignored ``work/factory-3view`` folder::

    inputs/<case>/drawing.png, spec.json, views.json   the only files inference reads
    params/<case>.json                                  rendering parameters, station x, WL z, buttock y
    sealed/truth/<hull>.npz                             truth table (same builder as the body-plan factory)
    sealed/lines/<hull>.json                            exact waterline, buttock, profile and deck cuts
    samples/                                            two sample sheets for people
    manifest.json                                       hashes, cross-view check, round set

The case seed is ``splits.case_seed`` of the case id with a ``lines_3view`` prefix, so these cases
never share noise with the body-plan cases of the same hull.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from . import generate as G
from . import hulls as H
from . import lines as L
from . import render as R
from . import render_lines as RL
from . import sealed_v3 as V3
from . import splits as S
from . import truth as T

DATA_FOLDER = Path("work") / "factory-3view"
HULL_IDS = ("dtmb5415", "series60", "shipd-1-08158", "shipd-1-09867", "shipd-1-00679", "shipd-2-02216")
# Whole-vessel design round set R-3view (docs/plans/2026-11-08-whole-vessel-design.md section 7):
# DTMB L0, a Ship-D hull drawn as `separate` in v1 at L2, two v1 `overlay` Ship-D hulls at L0 and L2.
ROUND_SET_3VIEW = ("dtmb5415-3v-L0", "shipd-1-08158-3v-L2", "shipd-1-09867-3v-L0", "shipd-1-00679-3v-L2")
SAMPLE_CASES = ("dtmb5415-3v-L0", "dtmb5415-3v-L2")
MAX_JOBS = 3
SHIPD_SET_PREFIX = "Constrained_Randomized_Set_"


def case_id(hull_id: str, level: int) -> str:
    return f"{hull_id}-3v-L{level}"


def development_entry(hull_id: str) -> dict:
    manifest = json.loads((G.MANIFEST_DIR / "hulls.json").read_text())
    entry = next(h for h in manifest["hulls"] if h["hull_id"] == hull_id)
    if entry["split"] != "development":
        raise ValueError(f"{hull_id} is not a development hull")
    return entry


def sealed_hull_ids() -> set[str]:
    ids = set()
    for path in (G.MANIFEST_DIR / "sealed-v2" / "hulls.json", V3.MANIFEST_DIR / "hulls.json"):
        ids.update(h["hull_id"] for h in json.loads(path.read_text())["hulls"])
    return ids


def load_hull(hull_id: str, scratch: Path) -> H.Hull:
    entry = development_entry(hull_id)
    named = [h for h in H.NAMED_HULLS if h.hull_id == hull_id]
    if named:
        return H.load_named(named[0], scratch / hull_id)
    _, set_number, row = hull_id.split("-")
    vectors, keys = H.shipd_vectors()
    key = (SHIPD_SET_PREFIX + set_number, int(row))
    return H.load_shipd(key, vectors[keys.index(key)], entry["family"])


def render_hull(args) -> dict:
    root, hull_id = args
    V3.use_shared_sources(V3.data_home())  # worker processes do not inherit the parent's source folder
    started = time.perf_counter()
    hull = load_hull(hull_id, root / "scratch")
    truth_path = root / "sealed" / "truth" / f"{hull_id}.npz"
    record = T.build_truth(hull, truth_path)
    entry = development_entry(hull_id)
    stations = G.station_curves(hull)
    lines = L.build_lines(hull, stations, record["draft_m"])
    lines_path = root / "sealed" / "lines" / f"{hull_id}.json"
    lines_path.parent.mkdir(parents=True, exist_ok=True)
    lines_path.write_text(json.dumps(lines.to_json()) + "\n")
    licence = str(hull.provenance.get("licence_terms") or "see hull manifest")[:200]
    cases = []
    for level in S.LEVELS:
        cid = case_id(hull_id, level)
        params = R.sample_params(level, RL.LAYOUT, S.case_seed(f"{RL.LAYOUT}:{cid}"))
        vessel_id = "factory-" + hashlib.sha256(cid.encode()).hexdigest()[:12]
        image, spec, views, geometry = RL.make_lines_case(
            lines, params, vessel_id, licence, "Synthetic three-view lines drawing from CAD cuts (benchmark factory).")
        folder = root / "inputs" / cid
        folder.mkdir(parents=True, exist_ok=True)
        Image.fromarray(image).save(folder / "drawing.png", optimize=False, compress_level=6)
        spec["source"]["sha256"] = G.sha256_file(folder / "drawing.png")
        (folder / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")
        (folder / "views.json").write_text(json.dumps(views, indent=2) + "\n")
        check = L.cross_check(lines, geometry["ppm"])
        params_record = {
            "case_id": cid, "hull_id": hull_id, "family": entry["family"], "split": "development", "level": level,
            "layout": RL.LAYOUT, "seed": params["seed"], "render": params, "geometry": geometry,
            "station_x_m": [s.x_m for s in stations], "waterline_z_m": list(lines.waterlines),
            "buttock_y_m": list(lines.buttocks), "profile_offset_y_m": L.PROFILE_OFFSET_M,
            "waterline_grid_step_m": lines.waterline_step_m, "buttock_grid_step_m": lines.buttock_step_m}
        (root / "params").mkdir(exist_ok=True)
        (root / "params" / f"{cid}.json").write_text(json.dumps(params_record, indent=1) + "\n")
        cases.append({"case_id": cid, "hull_id": hull_id, "family": entry["family"], "level": level,
                      "image_size": geometry["image_size"],
                      "cross_check_pairs": len(check),
                      "cross_check_max_px": max((r["difference_px"] for r in check), default=None),
                      **{f"{kind}_sha256": G.sha256_file(folder / f"{kind}.{ext}")
                         for kind, ext in (("drawing", "png"), ("spec", "json"), ("views", "json"))},
                      "params_sha256": G.sha256_file(root / "params" / f"{cid}.json")})
    return {"hull": {"hull_id": hull_id, "family": entry["family"], "source": hull.provenance.get("source"),
                     "length_m": hull.length_m, "depth_m": hull.depth_m, "max_half_breadth_m": hull.max_half_breadth_m,
                     "draft_m": record["draft_m"], "truth_sha256": G.sha256_file(truth_path),
                     "truth_sha256_v1_manifest": entry["truth_sha256"],
                     "lines_sha256": G.sha256_file(lines_path),
                     "waterlines": len(lines.waterlines), "buttocks": len(lines.buttocks),
                     "seconds": round(time.perf_counter() - started, 1)},
            "cases": cases}


def generator_hashes() -> dict[str, str]:
    code = [Path(__file__), Path(L.__file__), Path(RL.__file__), Path(G.__file__), Path(H.__file__), Path(R.__file__),
            Path(S.__file__), Path(T.__file__), H.ROOT / "benchmarks/gunnerus/hull_metrics.py"]
    return {str(p.relative_to(H.ROOT)): G.sha256_file(p) for p in code}


def generate(root: Path, jobs: int) -> None:
    sealed = sealed_hull_ids() & set(HULL_IDS)
    if sealed:
        raise SystemExit(f"sealed hulls must not be drawn: {sorted(sealed)}")
    V3.use_shared_sources(V3.data_home())
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(render_hull, [(root, h) for h in HULL_IDS]))
    shutil.rmtree(root / "scratch", ignore_errors=True)
    samples = root / "samples"
    samples.mkdir(exist_ok=True)
    for cid in SAMPLE_CASES:
        shutil.copyfile(root / "inputs" / cid / "drawing.png", samples / f"{cid}.png")
    cases = [c for r in results for c in r["cases"]]
    manifest = {
        "name": "factory lines_3view development set", "layout": RL.LAYOUT, "levels": list(S.LEVELS),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "generator_commit": G.git_head(),
        "generator_sha256": generator_hashes(), "root": str(DATA_FOLDER),
        "hulls": [r["hull"] for r in results], "cases": cases, "round_set_3view": list(ROUND_SET_3VIEW),
        "samples": [f"samples/{cid}.png" for cid in SAMPLE_CASES],
        "cross_check": {"rule": "plan waterline half-breadth at each station x vs body-plan station half-breadth at each WL z",
                        "pairs": sum(c["cross_check_pairs"] for c in cases),
                        "max_px": max(c["cross_check_max_px"] for c in cases if c["cross_check_max_px"] is not None)},
        "rule": "Development hulls only; no sealed v2/v3 hull. Inputs never contain truth.",
        "seconds": round(time.perf_counter() - started, 1)}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps({"cases": len(cases), "cross_check": manifest["cross_check"], "seconds": manifest["seconds"]}))


def verify(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["generator_sha256"] != generator_hashes():
        raise SystemExit("generator code changed since generation")
    for case in manifest["cases"]:
        folder = root / "inputs" / case["case_id"]
        for kind, ext in (("drawing", "png"), ("spec", "json"), ("views", "json")):
            if G.sha256_file(folder / f"{kind}.{ext}") != case[f"{kind}_sha256"]:
                raise SystemExit(f"hash mismatch: {case['case_id']} {kind}")
        if G.sha256_file(root / "params" / f"{case['case_id']}.json") != case["params_sha256"]:
            raise SystemExit(f"hash mismatch: {case['case_id']} params")
    for hull in manifest["hulls"]:
        if G.sha256_file(root / "sealed" / "truth" / f"{hull['hull_id']}.npz") != hull["truth_sha256"]:
            raise SystemExit(f"truth hash mismatch: {hull['hull_id']}")
    print(f"Verified {len(manifest['cases'])} three-view cases and {len(manifest['hulls'])} truth tables.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="data folder (default: main checkout work/factory-3view)")
    parser.add_argument("--jobs", type=int, default=MAX_JOBS)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.jobs > MAX_JOBS:
        raise SystemExit(f"at most {MAX_JOBS} concurrent jobs on this machine")
    root = args.root or V3.data_home() / DATA_FOLDER
    if args.verify:
        verify(root)
    else:
        generate(root, args.jobs)


if __name__ == "__main__":
    sys.exit(main())
