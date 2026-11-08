"""Synthetic tests only: never run a reader or scorer on the sealed split, and never open its truth."""
import json
from collections import Counter

import numpy as np

from benchmarks.factory import report
from benchmarks.factory import sealed_v2 as V2
from benchmarks.factory import sealed_v3 as V3


def test_cluster_with_v2_hull_or_too_few_unblocked_rows_is_not_eligible():
    keys = [("Constrained_Randomized_Set_1", row) for row in range(15)]
    labels = np.repeat([0, 1, 2], 5)
    # Cluster 0 holds a previous hull; cluster 1 has only three rows outside the blocked v1 family 7.
    v1_labels = np.array([0] * 5 + [7, 7, 0, 0, 0] + [0] * 5)
    eligible, occupied = V3.eligible_clusters(labels, v1_labels, [7], keys, {"shipd-1-00002"})
    assert eligible == [2]
    assert occupied == [0]


def test_candidates_skip_blocked_families_and_are_seeded():
    labels = np.array([4, 4, 4, 4, 4, 5])
    v1_labels = np.array([1, 2, 1, 3, 1, 1])
    rows = V3.candidate_rows(labels, v1_labels, [2, 3], 4)
    assert sorted(rows) == [0, 2, 4]
    assert rows == V3.candidate_rows(labels, v1_labels, [2, 3], 4)


def test_case_plan_pairs_both_layouts_and_all_levels_with_new_seeds():
    hulls = [{"hull_id": f"h{i}", "family": f"shipd-v3-c{i // 4:03d}"} for i in range(36)]
    cases = V3.plan_cases(hulls)
    assert len(cases) == len({c["case_id"] for c in cases}) == V3.EXPECTED_CASES == 288
    assert {c["split"] for c in cases} == {"hull-disjoint (v3)"}
    assert Counter((c["layout"], c["level"]) for c in cases) == {
        (layout, level): 36 for layout in ("overlay", "separate") for level in range(4)}
    assert len({c["seed"] for c in cases}) == 288
    v2_seeds = {c["seed"] for c in V2.plan_cases(hulls)}
    assert not v2_seeds & {c["seed"] for c in cases}


def test_v3_manifests_stay_outside_the_v2_history_glob():
    assert V2.MANIFEST_DIR.parent not in V3.MANIFEST_DIR.parents
    assert V3.MANIFEST_DIR.parent == V2.MANIFEST_DIR.parent.parent
    assert V3.SEED not in (V2.SEED, V2.SEED + 1)


def test_frozen_v3_manifest_is_disjoint_from_v1_and_v2():
    """Reads committed manifests only: hull ids, clusters and hashes, never truth arrays."""
    frozen = json.loads((V3.MANIFEST_DIR / "split_manifest.json").read_text())
    for name, digest in frozen["files_sha256"].items():
        assert V2.G.sha256_file(V3.MANIFEST_DIR / name) == digest
    hulls = {h["hull_id"] for h in json.loads((V3.MANIFEST_DIR / "hulls.json").read_text())["hulls"]}
    selection = json.loads((V3.MANIFEST_DIR / "selection.json").read_text())
    used, history = V3.previous_hulls()
    assert history == selection["previous_manifest_sha256"]
    assert len(hulls) == 36 and not hulls & used
    v2_selection = json.loads((V2.MANIFEST_DIR / "selection.json").read_text())
    v2_clusters = {c["cluster"] for c in v2_selection["clusters"]}
    assert not v2_clusters & {c["cluster"] for c in selection["clusters"]}
    rows = [json.loads(line) for line in (V3.MANIFEST_DIR / "cases.jsonl").read_text().splitlines()]
    assert len(rows) == 288 and {r["hull_id"] for r in rows} == hulls


def test_report_names_v3_with_its_caveat(monkeypatch):
    assert report.SPLIT_CAVEATS[V3.SPLIT] == V3.CAVEAT
    row = {"split": V3.SPLIT, "hull_id": "synthetic", "family": "shipd-v3-c001", "level": 0,
           "layout": "overlay", "outcome": "abstained", "correct": False, "seconds": 1}
    monkeypatch.setattr(report, "load_rows", lambda *_: [row])
    text = report.cmd_table(None, [], None)
    assert "Split: hull-disjoint (v3)" in text
    assert V3.CAVEAT in text
