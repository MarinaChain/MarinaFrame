"""Synthetic tests only: never run a reader or scorer on the sealed split."""
import json
from collections import Counter
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip('cv2', reason='the factory renderer needs the plan-raster extra (OpenCV)')

from benchmarks.factory import sealed_v2 as V


def test_exclude_whole_cluster_with_previously_rendered_hull():
    keys = [("Constrained_Randomized_Set_1", row) for row in range(12)]
    labels = np.repeat([0, 1, 2], 4)
    eligible, occupied = V.eligible_clusters(labels, keys, {"shipd-1-00001"})
    assert eligible == [1, 2]
    assert occupied == [0]


def test_case_plan_pairs_both_layouts_and_all_levels():
    hulls = [{"hull_id": f"h{i}", "family": f"shipd-v2-c{i // 4:03d}"} for i in range(36)]
    cases = V.plan_cases(hulls)
    assert len(cases) == len({c["case_id"] for c in cases}) == 288
    assert set(c["split"] for c in cases) == {"hull-disjoint (v2)"}
    assert Counter((c["layout"], c["level"]) for c in cases) == {
        (layout, level): 36 for layout in ("overlay", "separate") for level in range(4)}
    assert cases == V.plan_cases(hulls)
    assert len({c["seed"] for c in cases}) == 288


def test_disk_floor_stops_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(V.shutil, "disk_usage", lambda _: SimpleNamespace(free=V.MIN_FREE_BYTES - 1))
    with pytest.raises(RuntimeError, match="15 GiB"):
        V.check_disk(tmp_path)


def test_history_includes_rendered_hulls_and_skips(monkeypatch, tmp_path):
    (tmp_path / "cases.jsonl").write_text(json.dumps({"hull_id": "shipd-1-00000"}) + "\n")
    (tmp_path / "hulls.json").write_text(json.dumps({"hulls": [], "skipped": [
        {"hull_id": "Constrained_Randomized_Set_1:1"}]}))
    monkeypatch.setattr(V.G, "MANIFEST_DIR", tmp_path)
    monkeypatch.setattr(V.H, "ROOT", tmp_path)
    used, hashes = V.previous_hulls()
    assert used == {"shipd-1-00000", "shipd-1-00001"}
    assert set(hashes) == {"cases.jsonl", "hulls.json"}


def test_table_names_v2_without_loading_sealed_truth(monkeypatch):
    from benchmarks.factory import report

    row = {"split": V.SPLIT, "hull_id": "synthetic", "family": "shipd-v2-c001", "level": 0,
           "layout": "overlay", "outcome": "abstained", "correct": False, "seconds": 1}
    monkeypatch.setattr(report, "load_rows", lambda *_: [row])
    text = report.cmd_table(None, [], None)
    assert "Split: hull-disjoint (v2)" in text
    assert V.CAVEAT in text


def test_runner_can_select_separate_manifest_without_inference(tmp_path):
    from benchmarks.factory.runner import load_cases

    (tmp_path / "cases.jsonl").write_text(json.dumps({"case_id": "synthetic", "split": V.SPLIT}) + "\n")
    assert load_cases(V.SPLIT, None, None, tmp_path) == [{"case_id": "synthetic", "split": V.SPLIT}]
