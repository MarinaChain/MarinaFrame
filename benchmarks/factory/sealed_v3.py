"""Generate and freeze hull-disjoint (v3), without running inference or scoring.

Run once:          python -m benchmarks.factory.sealed_v3
Verify (hashes):   python -m benchmarks.factory.sealed_v3 --verify
Determinism check: python -m benchmarks.factory.sealed_v3 --regen-check

v3 follows hull-disjoint (v2) and reuses its frozen generator, renderer, truth builder and gate.
``sealed_v2.py`` is not modified: v2's frozen manifest hashes that file.

Selection, beyond v2:
- Partition: the frozen v2 partition of Ship-D (256 k-means clusters), read from the v2 selection.json,
  so that "cluster" means the same thing in v2 and v3.
- Excluded hulls: every hull used or rejected by v1 (as in v2), plus every v2 hull and v2 rejected candidate.
  A cluster that contains any excluded hull is excluded. This makes v3 cluster-disjoint from v2.
- Broad families: v1 clustered Ship-D into 44 families and used all 44. A v3 candidate must not be in
  any v1 family that contains a v2 hull. v1 families cannot be avoided, because v1 used all of them.

Data goes to the main checkout's ignored ``work/factory-sealed-v3`` (also from a linked worktree).
Manifests go to ``benchmarks/factory/manifests-sealed-v3``. That folder is outside ``manifests/``,
because ``sealed_v2.previous_hulls`` hashes every ``cases.jsonl`` below ``manifests/`` and a new file
there would make the v2 verification fail.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import generate as G
from . import hulls as H
from . import sealed_v2 as V2
from . import splits as S
from . import truth as T

SEED = 20261201
CLUSTER_COUNT = 9
HULLS_PER_CLUSTER = 4
LAYOUTS = ("separate", "overlay")
SPLIT = "hull-disjoint (v3)"
CAVEAT = ("Hull-disjoint from v1 and v2 and cluster-disjoint from v2; no hull shares a v1 family with a v2 hull. "
          "Every hull is in a broad family used by the frozen v1 splits; this is not family-disjoint from v1.")
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests-sealed-v3"
V2_DIR = V2.MANIFEST_DIR
V2_FILES = ("cases.jsonl", "hulls.json", "selection.json", "split_manifest.json")
DATA_FOLDER = Path("work") / "factory-sealed-v3"
EXPECTED_HULLS = CLUSTER_COUNT * HULLS_PER_CLUSTER
EXPECTED_CASES = EXPECTED_HULLS * len(LAYOUTS) * len(S.LEVELS)


def data_home() -> Path:
    """Main checkout: the parent of the shared git directory, also when run from a linked worktree."""
    common = subprocess.run(["git", "-C", str(H.ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


def use_shared_sources(home: Path) -> None:
    """Read Ship-D from the main checkout when this checkout has no local copy. Never download."""
    if (H.sources_root() / "shipd").exists():
        return
    shared = home / "work" / "sources"
    if not (shared / "shipd").exists():
        raise FileNotFoundError(f"Ship-D sources not found in {H.sources_root()} or {shared}; not downloading")
    H.sources_root = lambda: shared  # hulls.py is frozen by hash, so it is not edited


def previous_hulls() -> tuple[set[str], dict[str, str]]:
    """v1 history (as v2 defines it) plus every v2 hull and rejected v2 candidate."""
    used, hashes = V2.previous_hulls()
    for name in V2_FILES:
        path = V2_DIR / name
        hashes[str(path.relative_to(H.ROOT))] = G.sha256_file(path)
    used.update(h["hull_id"] for h in json.loads((V2_DIR / "hulls.json").read_text())["hulls"])
    used.update(s["hull_id"] for s in json.loads((V2_DIR / "selection.json").read_text())["skipped"])
    return used, hashes


def v2_partition() -> tuple[np.ndarray, list[int]]:
    """Frozen v2 cluster labels for every Ship-D row, and the clusters v2 selected."""
    selection = json.loads((V2_DIR / "selection.json").read_text())
    return np.array(selection["labels"]), [c["cluster"] for c in selection["clusters"]]


def v1_families(vectors: np.ndarray, keys: list) -> np.ndarray:
    """Recompute the v1 family label of every row and check it against the frozen v1 hull catalogue."""
    labels = S.shipd_cluster_labels(vectors)
    row_of = {V2.hull_id_for(key): row for row, key in enumerate(keys)}
    for hull in json.loads((G.MANIFEST_DIR / "hulls.json").read_text())["hulls"]:
        if hull["hull_id"] in row_of and hull["family"] != f"shipd-c{labels[row_of[hull['hull_id']]]:02d}":
            raise ValueError(f"v1 families do not reproduce: {hull['hull_id']}")
    return labels


def blocked_families(v1_labels: np.ndarray, keys: list) -> list[int]:
    """v1 families that contain at least one v2 hull."""
    row_of = {V2.hull_id_for(key): row for row, key in enumerate(keys)}
    v2_hulls = json.loads((V2_DIR / "hulls.json").read_text())["hulls"]
    return sorted({int(v1_labels[row_of[h["hull_id"]]]) for h in v2_hulls})


def candidate_rows(labels: np.ndarray, v1_labels: np.ndarray, blocked: list[int], cluster: int) -> list[int]:
    """Seeded order of the rows of one cluster that are outside the blocked v1 families."""
    rows = np.flatnonzero((labels == cluster) & ~np.isin(v1_labels, blocked))
    return np.random.default_rng(SEED + 100 + cluster).permutation(rows).tolist()


def eligible_clusters(labels: np.ndarray, v1_labels: np.ndarray, blocked: list[int], keys: list,
                      used: set[str]) -> tuple[list[int], list[int]]:
    """Clusters with no excluded hull and enough candidates outside the blocked families."""
    unoccupied, occupied = V2.eligible_clusters(labels, keys, used)
    allowed = ~np.isin(v1_labels, blocked)
    eligible = [c for c in unoccupied if np.count_nonzero((labels == c) & allowed) >= HULLS_PER_CLUSTER]
    return eligible, occupied


def plan_cases(hulls: list[dict]) -> list[dict]:
    return [{"case_id": f"{h['hull_id']}-{layout}-L{level}", "hull_id": h["hull_id"],
             "family": h["family"], "split": SPLIT, "layout": layout, "level": level,
             "seed": S.case_seed(f"v3:{SEED}:{h['hull_id']}:{layout}:L{level}")}
            for h in hulls for layout in LAYOUTS for level in S.LEVELS]


def generate(root: Path, manifest_dir: Path) -> None:
    import scipy
    import PIL
    import cv2

    if (manifest_dir / "split_manifest.json").exists() or root.exists():
        raise FileExistsError("Refusing to overwrite an existing generation or frozen split")
    root.mkdir(parents=True)
    V2.check_disk(root)
    vectors, keys = H.shipd_vectors()
    used, history = previous_hulls()
    labels, v2_clusters = v2_partition()
    if len(labels) != len(keys):
        raise ValueError("v2 partition does not match the Ship-D rows")
    v1_labels = v1_families(vectors, keys)
    blocked = blocked_families(v1_labels, keys)
    eligible, occupied = eligible_clusters(labels, v1_labels, blocked, keys, used)
    order = np.random.default_rng(SEED + 1).permutation(eligible).tolist()
    selection = {"name": SPLIT, "caveat": CAVEAT, "seed": SEED,
                 "partition": "frozen v2 partition: labels in benchmarks/factory/manifests/sealed-v2/selection.json",
                 "v2_selected_clusters": v2_clusters,
                 "v1_family_rule": "splits.shipd_cluster_labels (k=44); reproduced for every v1 Ship-D hull",
                 "v1_family_labels": v1_labels.tolist(), "blocked_v1_families": blocked,
                 "cluster_order_seed": SEED + 1,
                 "candidate_rule": "rows of the cluster outside blocked_v1_families, permuted with seed + 100 + cluster",
                 "short_cluster_rule": "a cluster with fewer than four feasible candidates is recorded and passed over",
                 "key_order": "SHIPD_SETS order, then zero-based CSV row",
                 "occupied_clusters": occupied, "eligible_cluster_order": order,
                 "excluded_hull_ids": sorted(used), "previous_manifest_sha256": history,
                 "sources_sha256": V2.source_hashes(), "clusters": [], "short_clusters": [], "skipped": [],
                 "versions": {"python": platform.python_version(), "numpy": np.__version__,
                              "scipy": scipy.__version__, "pillow": PIL.__version__, "opencv": cv2.__version__},
                 "mesh": {"num_wl": H.SHIPD_NUM_WL, "points_per_wl": H.SHIPD_POINTS_PER_WL,
                          "bit_AddTransom": 1, "bit_AddDeckLid": 0, "bit_RefineBowAndStern": 0,
                          "canonical_length_m": H.CANONICAL_LENGTH_M},
                 "truth": {"x_step_m": T.X_STEP_M, "z_steps": T.Z_STEPS, "draft_fraction": T.DRAFT_FRACTION}}
    hulls = []
    for cluster in order:
        rows = candidate_rows(labels, v1_labels, blocked, cluster)
        kept = []
        for row in rows:
            V2.check_disk(root)
            key, vector = keys[row], vectors[row]
            hull_id = V2.hull_id_for(key)
            try:
                hull = H.load_shipd(key, vector, f"shipd-v3-c{cluster:03d}")
                if not G.feasible(G.station_curves(hull), hull.depth_m):
                    raise ValueError("infeasible sections")
            except Exception as exc:
                selection["skipped"].append({"hull_id": hull_id, "cluster": cluster,
                                              "reason": f"{type(exc).__name__}: {exc}"})
                continue
            hull.provenance["parameters"] = vector.tolist()
            hull.provenance["partition_seed"] = SEED
            hull.provenance["v1_family"] = f"shipd-c{v1_labels[row]:02d}"
            kept.append(G._entry(hull, SPLIT, root))
            print(f"built {hull_id} cluster {cluster} ({len(kept)}/{HULLS_PER_CLUSTER})", flush=True)
            if len(kept) == HULLS_PER_CLUSTER:
                break
        if len(kept) != HULLS_PER_CLUSTER:
            # Pre-declared rule: pass the cluster over. Its built truth stays on disk but is never listed.
            selection["short_clusters"].append({"cluster": cluster, "feasible": [h["hull_id"] for h in kept]})
            continue
        hulls.extend(kept)
        selection["clusters"].append({"cluster": cluster, "candidate_rows": rows,
                                     "hull_ids": [h["hull_id"] for h in kept]})
        if len(selection["clusters"]) == CLUSTER_COUNT:
            break
    if len(selection["clusters"]) != CLUSTER_COUNT:
        raise RuntimeError("Not enough eligible clusters with four feasible hulls")
    for hull in hulls:
        V2.check_disk(root)
        G.render_hull_cases((root, hull["hull_id"], plan_cases([hull])))
        print(f"rendered {hull['hull_id']} ({len(LAYOUTS) * len(S.LEVELS)} drawings)", flush=True)
    freeze(root, manifest_dir, hulls, selection)


def freeze(root: Path, manifest_dir: Path, hulls: list[dict], selection: dict) -> None:
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
    manifest_dir.mkdir(parents=True, exist_ok=True)
    V2.write_json(manifest_dir / "selection.json", selection)
    V2.write_json(manifest_dir / "hulls.json", {"name": SPLIT, "caveat": CAVEAT, "hulls": hulls})
    (manifest_dir / "cases.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    V2.write_json(manifest_dir / "split_manifest.json", {
        "name": SPLIT, "caveat": CAVEAT, "seed": SEED, "generator_commit": G.git_head(),
        "generator_sha256": generator_hashes(),
        "files_sha256": {p: G.sha256_file(manifest_dir / p) for p in ("selection.json", "hulls.json", "cases.jsonl")},
        "root": str(DATA_FOLDER), "root_base": "main checkout (parent of the git common directory)",
        "hulls": len(hulls), "clusters": CLUSTER_COUNT, "cases": len(rows),
        "counts": {layout: {str(level): sum(r["layout"] == layout and r["level"] == level for r in rows)
                            for level in S.LEVELS} for layout in LAYOUTS},
        "rule": "Score only at a pre-registered frozen checkpoint; never during development.",
        "scoring_started": False})


def generator_hashes() -> dict[str, str]:
    code = [Path(__file__), Path(V2.__file__), Path(G.__file__), Path(H.__file__), Path(S.__file__),
            Path(T.__file__), Path(G.R.__file__), H.ROOT / "benchmarks/gunnerus/hull_metrics.py"]
    return {str(p.relative_to(H.ROOT)): G.sha256_file(p) for p in code}


def verify(root: Path, manifest_dir: Path = MANIFEST_DIR) -> None:
    """Check selection rules and generated bytes. Truth is checked by hash only and never opened."""
    from vessel_reconstruction.schema import validate_spec

    frozen = json.loads((manifest_dir / "split_manifest.json").read_text())
    if frozen["generator_sha256"] != generator_hashes():
        raise ValueError("Generator changed")
    for name, digest in frozen["files_sha256"].items():
        if G.sha256_file(manifest_dir / name) != digest:
            raise ValueError(f"Manifest hash mismatch: {name}")
    hulls = json.loads((manifest_dir / "hulls.json").read_text())["hulls"]
    selection = json.loads((manifest_dir / "selection.json").read_text())
    if V2.source_hashes() != selection["sources_sha256"]:
        raise ValueError("Generation sources changed")
    used, history = previous_hulls()
    if history != selection["previous_manifest_sha256"]:
        raise ValueError("Frozen v1/v2 history changed")
    keys = H.shipd_vectors()[1]
    labels, v2_clusters = v2_partition()
    v1_labels = np.array(selection["v1_family_labels"])
    blocked = blocked_families(v1_labels, keys)
    if blocked != selection["blocked_v1_families"]:
        raise ValueError("Blocked v1 families changed")
    eligible, _ = eligible_clusters(labels, v1_labels, blocked, keys, used)
    chosen = [c["cluster"] for c in selection["clusters"]]
    if any(c not in eligible or c in v2_clusters for c in chosen):
        raise ValueError("Selected cluster contains a previous hull or a v2 cluster")
    row_of = {V2.hull_id_for(key): row for row, key in enumerate(keys)}
    for hull in hulls:
        row = row_of[hull["hull_id"]]
        if hull["hull_id"] in used or int(v1_labels[row]) in blocked or int(labels[row]) not in chosen:
            raise ValueError(f"Selection rule broken: {hull['hull_id']}")
    rows = [json.loads(line) for line in (manifest_dir / "cases.jsonl").read_text().splitlines()]
    if len(hulls) != EXPECTED_HULLS or len(rows) != EXPECTED_CASES or len({r["case_id"] for r in rows}) != EXPECTED_CASES:
        raise ValueError("Incomplete split")
    if [{k: r[k] for k in plan_cases(hulls)[0]} for r in rows] != plan_cases(hulls):
        raise ValueError("Case plan changed")
    truth_by_hull = {h["hull_id"]: h["truth_sha256"] for h in hulls}
    for row in rows:
        if row["truth_sha256"] != truth_by_hull[row["hull_id"]]:
            raise ValueError("Truth hash differs between cases and hulls")
        for kind, path in row["files"].items():
            if G.sha256_file(root / path) != row[f"{kind}_sha256"]:
                raise ValueError(f"Hash mismatch: {path}")
        folder = root / "inputs" / row["case_id"]
        if {p.name for p in folder.iterdir()} != {"drawing.png", "spec.json"}:
            raise ValueError("Unexpected inference input")
        errors = validate_spec(json.loads((folder / "spec.json").read_text()), folder)
        if errors:
            raise ValueError(str(errors))
    if (root / "runs").exists():
        raise ValueError("Unexpected reader outputs in sealed generation root")
    print(f"Verified generation only: {EXPECTED_CASES} drawings/specs/params and {EXPECTED_HULLS} truth hashes; "
          "truth not opened; no inference or scoring.")


def regen_check(root: Path) -> None:
    """Generate again into a temporary folder inside the data root and compare all manifests byte for byte."""
    again = root / "regen-check"
    with tempfile.TemporaryDirectory() as scratch:
        try:
            generate(again, Path(scratch))
            for name in ("selection.json", "hulls.json", "cases.jsonl"):
                if (Path(scratch) / name).read_bytes() != (MANIFEST_DIR / name).read_bytes():
                    raise ValueError(f"Regeneration differs: {name}")
        finally:
            shutil.rmtree(again, ignore_errors=True)
    print("Regeneration is byte-identical: selection, hulls and every input, parameter and truth hash.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--regen-check", action="store_true")
    args = parser.parse_args()
    home = data_home()
    use_shared_sources(home)
    root = home / DATA_FOLDER
    if args.verify:
        verify(root)
    elif args.regen_check:
        regen_check(root)
    else:
        generate(root, MANIFEST_DIR)
        verify(root)


if __name__ == "__main__":
    main()
