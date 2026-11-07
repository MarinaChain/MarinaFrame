"""Generate and freeze hull-disjoint (v2), without running inference or scoring.

Run once: python -m benchmarks.factory.sealed_v2
Verify generation only: python -m benchmarks.factory.sealed_v2 --verify
The existing factory manifests and generation code are not modified.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
from pathlib import Path

import numpy as np

from . import generate as G
from . import hulls as H
from . import splits as S
from . import truth as T

SEED = 20261108
N_CLUSTERS = 256
CLUSTER_COUNT = 9
HULLS_PER_CLUSTER = 4
SPLIT = "hull-disjoint (v2)"
CAVEAT = "Clusters can share broad families with the frozen splits; this is not family-disjoint."
DEFAULT_ROOT = H.ROOT / "work" / "factory-sealed-v2"
MANIFEST_DIR = G.MANIFEST_DIR / "sealed-v2"
MIN_FREE_BYTES = 15 * 1024 ** 3


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def check_disk(root: Path) -> None:
    if shutil.disk_usage(root).free < MIN_FREE_BYTES:
        raise RuntimeError("Stopped: less than 15 GiB free disk space")


def previous_hulls() -> tuple[set[str], dict[str, str]]:
    """Frozen cases are the authority for prior rendering, across every old split."""
    used, hashes = set(), {}
    for path in sorted(G.MANIFEST_DIR.rglob("cases.jsonl")):
        if MANIFEST_DIR in path.parents:
            continue
        hashes[str(path.relative_to(H.ROOT))] = G.sha256_file(path)
        used.update(json.loads(line)["hull_id"] for line in path.read_text().splitlines())
    old_hulls = G.MANIFEST_DIR / "hulls.json"
    hashes[str(old_hulls.relative_to(H.ROOT))] = G.sha256_file(old_hulls)
    old = json.loads(old_hulls.read_text())
    used.update(h["hull_id"] for h in old["hulls"])
    # Do not recycle previously rejected candidates either.
    for item in old["skipped"]:
        hull_id = item["hull_id"]
        if ":" in hull_id:
            name, row = hull_id.split(":")
            hull_id = hull_id_for((name, int(row)))
        used.add(hull_id)
    if not used:
        raise ValueError("No frozen hull history found")
    return used, hashes


def hull_id_for(key) -> str:
    return f"shipd-{key[0].split('_')[-1]}-{key[1]:05d}"


def eligible_clusters(labels: np.ndarray, keys: list, used: set[str]) -> tuple[list[int], list[int]]:
    occupied = {int(label) for label, key in zip(labels, keys) if hull_id_for(key) in used}
    eligible = [int(c) for c in np.unique(labels)
                if int(c) not in occupied and np.count_nonzero(labels == c) >= HULLS_PER_CLUSTER]
    return eligible, sorted(occupied)


def plan_cases(hulls: list[dict]) -> list[dict]:
    return [{"case_id": f"{h['hull_id']}-{layout}-L{level}", "hull_id": h["hull_id"],
             "family": h["family"], "split": SPLIT, "layout": layout, "level": level,
             "seed": S.case_seed(f"v2:{SEED}:{h['hull_id']}:{layout}:L{level}")}
            for h in hulls for layout in ("separate", "overlay") for level in S.LEVELS]


def source_hashes() -> dict:
    paths = [H.shipd_root() / "code" / "HullParameterization.py"]
    paths += [H.shipd_root() / "data" / "Ship_D_Dataset" / name / "Input_Vectors.csv" for name in H.SHIPD_SETS]
    return {str(p.relative_to(H.sources_root())): G.sha256_file(p) for p in paths}


def generate(root: Path) -> None:
    from scipy.cluster.vq import kmeans2
    import scipy
    import PIL
    import cv2

    if (MANIFEST_DIR / "split_manifest.json").exists() or root.exists():
        raise FileExistsError("Refusing to overwrite an existing generation or frozen split")
    root.mkdir(parents=True)
    check_disk(root)
    vectors, keys = H.shipd_vectors()
    used, history = previous_hulls()
    mean, spread = vectors.mean(axis=0), vectors.std(axis=0)
    spread[spread == 0] = 1.0
    centres, labels = kmeans2((vectors - mean) / spread, N_CLUSTERS, iter=10,
                              seed=np.random.default_rng(SEED), minit="++", missing="raise")
    eligible, occupied = eligible_clusters(labels, keys, used)
    order = np.random.default_rng(SEED + 1).permutation(eligible).tolist()
    if len(order) < CLUSTER_COUNT:
        raise ValueError("Not enough unoccupied clusters")
    selection = {"name": SPLIT, "caveat": CAVEAT, "seed": SEED, "partition_clusters": N_CLUSTERS,
                 "algorithm": "scipy.cluster.vq.kmeans2, minit=++, iter=10, Euclidean standardised parameters",
                 "cluster_order_seed": SEED + 1, "candidate_seed_rule": "seed + 100 + cluster",
                 "mean": mean.tolist(), "spread": spread.tolist(), "centres": centres.tolist(),
                 "labels": labels.tolist(), "key_order": "SHIPD_SETS order, then zero-based CSV row",
                 "occupied_clusters": occupied, "eligible_cluster_order": order,
                 "excluded_hull_ids": sorted(used), "previous_manifest_sha256": history,
                 "sources_sha256": source_hashes(), "clusters": [], "skipped": [],
                 "versions": {"python": platform.python_version(), "numpy": np.__version__,
                              "scipy": scipy.__version__, "pillow": PIL.__version__, "opencv": cv2.__version__},
                 "mesh": {"num_wl": H.SHIPD_NUM_WL, "points_per_wl": H.SHIPD_POINTS_PER_WL,
                          "bit_AddTransom": 1, "bit_AddDeckLid": 0, "bit_RefineBowAndStern": 0,
                          "canonical_length_m": H.CANONICAL_LENGTH_M},
                 "truth": {"x_step_m": T.X_STEP_M, "z_steps": T.Z_STEPS, "draft_fraction": T.DRAFT_FRACTION}}
    hulls = []
    for cluster in order:
        rows = np.random.default_rng(SEED + 100 + cluster).permutation(np.flatnonzero(labels == cluster)).tolist()
        kept = []
        for row in rows:
            check_disk(root)
            key, vector = keys[row], vectors[row]
            hull_id = hull_id_for(key)
            try:
                hull = H.load_shipd(key, vector, f"shipd-v2-c{cluster:03d}")
                if not G.feasible(G.station_curves(hull), hull.depth_m):
                    raise ValueError("infeasible sections")
            except Exception as exc:
                selection["skipped"].append({"hull_id": hull_id, "cluster": cluster,
                                              "reason": f"{type(exc).__name__}: {exc}"})
                continue
            hull.provenance["parameters"] = vector.tolist()
            hull.provenance["partition_seed"] = SEED
            entry = G._entry(hull, SPLIT, root)
            kept.append(entry)
            print(f"built {hull_id} cluster {cluster} ({len(kept)}/4)", flush=True)
            if len(kept) == HULLS_PER_CLUSTER:
                break
        if len(kept) != HULLS_PER_CLUSTER:
            raise RuntimeError(f"Cluster {cluster} has fewer than four feasible hulls; do not silently change selection")
        hulls.extend(kept)
        selection["clusters"].append({"cluster": cluster, "candidate_rows": rows,
                                     "hull_ids": [h["hull_id"] for h in kept]})
        write_json(root / "selection.json", selection)
        write_json(root / "hulls.json", {"hulls": hulls})
        if len(selection["clusters"]) == CLUSTER_COUNT:
            break
    for hull in hulls:
        check_disk(root)
        G.render_hull_cases((root, hull["hull_id"], plan_cases([hull])))
        print(f"rendered {hull['hull_id']} (8 drawings)", flush=True)
    freeze(root, hulls, selection)
    verify(root)


def freeze(root: Path, hulls: list[dict], selection: dict) -> None:
    by_id = {h["hull_id"]: h for h in hulls}
    rows = []
    for case in plan_cases(hulls):
        case_id = case["case_id"]
        files = {"drawing": f"inputs/{case_id}/drawing.png", "spec": f"inputs/{case_id}/spec.json",
                 "params": f"params/{case_id}.json", "truth": f"sealed/truth/{case['hull_id']}.npz"}
        params = json.loads((root / files["params"]).read_text())
        rows.append({**case, "files": files, **{f"{k}_sha256": G.sha256_file(root / v) for k, v in files.items()},
                     "render": params["render"], "image_size": params["geometry"]["image_size"]})
        if rows[-1]["truth_sha256"] != by_id[case["hull_id"]]["truth_sha256"]:
            raise ValueError("Truth changed during generation")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    write_json(MANIFEST_DIR / "selection.json", selection)
    write_json(MANIFEST_DIR / "hulls.json", {"name": SPLIT, "caveat": CAVEAT, "hulls": hulls})
    (MANIFEST_DIR / "cases.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    code = [Path(__file__), Path(G.__file__), Path(H.__file__), Path(S.__file__), Path(T.__file__),
            Path(G.R.__file__), H.ROOT / "benchmarks/gunnerus/hull_metrics.py"]
    write_json(MANIFEST_DIR / "split_manifest.json", {
        "name": SPLIT, "caveat": CAVEAT, "seed": SEED, "generator_commit": G.git_head(),
        "generator_sha256": {str(p.relative_to(H.ROOT)): G.sha256_file(p) for p in code},
        "files_sha256": {p: G.sha256_file(MANIFEST_DIR / p) for p in ("selection.json", "hulls.json", "cases.jsonl")},
        "root": str(root.relative_to(H.ROOT)), "hulls": len(hulls), "clusters": CLUSTER_COUNT, "cases": len(rows),
        "counts": {layout: {str(level): sum(r["layout"] == layout and r["level"] == level for r in rows)
                            for level in S.LEVELS} for layout in ("separate", "overlay")},
        "rule": "Score only at frozen checkpoints: deterministic abstain vs deterministic draft vs LLM-first; never during development.",
        "scoring_started": False})


def verify(root: Path) -> None:
    """Check generated bytes and truth completeness, never inference or score quality."""
    from vessel_reconstruction.schema import validate_spec

    frozen = json.loads((MANIFEST_DIR / "split_manifest.json").read_text())
    for name, digest in frozen["generator_sha256"].items():
        if G.sha256_file(H.ROOT / name) != digest:
            raise ValueError(f"Generator changed: {name}")
    for name, digest in frozen["files_sha256"].items():
        if G.sha256_file(MANIFEST_DIR / name) != digest:
            raise ValueError(f"Manifest hash mismatch: {name}")
    hulls = json.loads((MANIFEST_DIR / "hulls.json").read_text())["hulls"]
    selection = json.loads((MANIFEST_DIR / "selection.json").read_text())
    if source_hashes() != selection["sources_sha256"]:
        raise ValueError("Generation sources changed")
    used, history = previous_hulls()
    if history != selection["previous_manifest_sha256"]:
        raise ValueError("Frozen history changed")
    keys = H.shipd_vectors()[1]
    eligible, _ = eligible_clusters(np.array(selection["labels"]), keys, used)
    if any(c["cluster"] not in eligible for c in selection["clusters"]):
        raise ValueError("Selected cluster contains a previous hull")
    if used & {h["hull_id"] for h in hulls}:
        raise ValueError("Hull overlap")
    rows = [json.loads(line) for line in (MANIFEST_DIR / "cases.jsonl").read_text().splitlines()]
    if len(hulls) != 36 or len(rows) != 288 or len({r["case_id"] for r in rows}) != 288:
        raise ValueError("Incomplete split")
    if [{k: r[k] for k in plan_cases(hulls)[0]} for r in rows] != plan_cases(hulls):
        raise ValueError("Case plan changed")
    for row in rows:
        for kind, path in row["files"].items():
            if G.sha256_file(root / path) != row[f"{kind}_sha256"]:
                raise ValueError(f"Hash mismatch: {path}")
        folder = root / "inputs" / row["case_id"]
        if {p.name for p in folder.iterdir()} != {"drawing.png", "spec.json"}:
            raise ValueError("Unexpected inference input")
        errors = validate_spec(json.loads((folder / "spec.json").read_text()), folder)
        if errors:
            raise ValueError(str(errors))
    for hull in hulls:
        path = root / "sealed" / "truth" / f"{hull['hull_id']}.npz"
        with np.load(path, allow_pickle=False) as data:
            if set(data.files) != {"x_m", "z_m", "half_breadth", "width", "record"}:
                raise ValueError(f"Incomplete truth: {path}")
            x, z = T.grids(hull["length_m"], hull["depth_m"])
            if not np.array_equal(data["x_m"], x) or not np.array_equal(data["z_m"], z):
                raise ValueError("Truth grid mismatch")
            for field in ("half_breadth", "width"):
                if data[field].shape != (len(x), len(z)) or not np.isfinite(data[field]).all() or (data[field] < 0).any():
                    raise ValueError(f"Invalid truth array: {path} {field}")
            record = json.loads(str(data["record"]))
            if record["hull_id"] != hull["hull_id"] or any(
                    not np.isfinite(record[k]) or record[k] <= 0
                    for k in ("draft_m", "volume_below_draft_m3", "waterplane_area_m2")):
                raise ValueError("Incomplete truth record")
    if (root / "runs").exists():
        raise ValueError("Unexpected reader outputs in sealed generation root")
    print("Verified generation only: 288 drawings/specs/params and 36 complete truth tables; no inference or scoring.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(DEFAULT_ROOT)
    else:
        generate(DEFAULT_ROOT)


if __name__ == "__main__":
    main()
