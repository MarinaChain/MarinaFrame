"""Regenerate a subset of frozen benchmark-factory cases (W12 evaluation).

The full factory needs the whole hull catalogue (about 10 minutes and 1.6 GB). This
script builds only the hulls of the requested cases, renders those cases with the
frozen factory code, and compares every drawing hash with the frozen manifest.

    python -m benchmarks.llm_setup_review.sample --cases sysser45-L1 wigley-L0 --root work/w12/factory
    python -m benchmarks.llm_setup_review.sample --setup-sample --root work/w12/factory

The output folder has the factory layout: ``inputs/<case>/{drawing.png,spec.json}`` and
``params/<case>.json`` (the generator's own record of the true setup values).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from benchmarks.factory import generate as G
from benchmarks.factory import hulls as H

# Development hulls for the sheet-setup evaluation: 10 hulls x 4 levels = 40 cases.
# Three hulls use the overlay layout (12 cases); the rest use separate panels.
SETUP_SAMPLE_HULLS = (
    "wigley", "dtmb5415", "series60", "shipd-1-01410", "shipd-2-01040", "shipd-2-05051",
    "shipd-1-00045", "shipd-1-00617", "shipd-1-00679", "shipd-2-04723",
)
SETUP_SAMPLE_LEVELS = (0, 1, 2, 3)


def hull_record(hull_id: str) -> dict:
    manifest = json.loads((G.MANIFEST_DIR / "hulls.json").read_text())
    return next(h for h in manifest["hulls"] if h["hull_id"] == hull_id)


def build_hull(hull_id: str, root: Path) -> None:
    """Build and cache one hull exactly as ``generate hulls`` does."""
    if (root / "hulls" / f"{hull_id}.npz").exists():
        return
    record = hull_record(hull_id)
    provenance = record["provenance"]
    scratch = root / "scratch" / hull_id
    if record["family"] == "dsyhs":
        hull = H.load_dsyhs(provenance["member"], scratch)
    elif provenance.get("source") == "shipd":
        vectors, keys = H.shipd_vectors()
        row = keys.index((provenance["set"], provenance["row"]))
        hull = H.load_shipd(keys[row], vectors[row], record["family"])
    else:
        recipe = next(h for h in H.NAMED_HULLS if h.hull_id == hull_id)
        hull = H.load_named(recipe, scratch)
    H.cache_hull(hull, root / "hulls")


def frozen_cases() -> dict[str, dict]:
    rows = [json.loads(line) for line in (G.MANIFEST_DIR / "cases.jsonl").read_text().splitlines()]
    return {row["case_id"]: row for row in rows}


def regenerate(case_ids: list[str], root: Path) -> list[dict]:
    frozen = frozen_cases()
    unknown = [c for c in case_ids if c not in frozen]
    if unknown:
        raise SystemExit(f"cases not in the frozen manifest: {unknown}")
    by_hull: dict[str, list[dict]] = {}
    manifest = json.loads((G.MANIFEST_DIR / "hulls.json").read_text())
    planned = {c["case_id"]: c for c in G.plan_cases(manifest)}
    for case_id in case_ids:
        by_hull.setdefault(planned[case_id]["hull_id"], []).append(planned[case_id])
    report = []
    for hull_id, cases in sorted(by_hull.items()):
        build_hull(hull_id, root)
        G.render_hull_cases((root, hull_id, cases))
        for case in cases:
            drawing = root / "inputs" / case["case_id"] / "drawing.png"
            report.append({"case_id": case["case_id"], "drawing_sha256_matches_frozen":
                           G.sha256_file(drawing) == frozen[case["case_id"]]["drawing_sha256"]})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--setup-sample", action="store_true")
    args = parser.parse_args()
    cases = list(args.cases)
    if args.setup_sample:
        cases += [f"{h}-L{level}" for h in SETUP_SAMPLE_HULLS for level in SETUP_SAMPLE_LEVELS]
    np.seterr(all="ignore")
    report = regenerate(sorted(set(cases)), args.root)
    print(json.dumps({"cases": len(report), "hash_mismatches": [r["case_id"] for r in report
                                                                if not r["drawing_sha256_matches_frozen"]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
