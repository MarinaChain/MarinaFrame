"""Parallel source inspection gives the same catalog as one worker, in request order."""
import copy

import numpy as np

from vessel_reconstruction import parallel
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.ingest import _dilate_5x5
from vessel_reconstruction.investigation import _ink_at, _ink_hits

from test_agent_tools import drawing


def test_worker_count_uses_setting_then_cores_and_stays_within_pieces(monkeypatch):
    monkeypatch.setenv(parallel.WORKERS_ENVIRONMENT_VARIABLE, "3")
    assert parallel.worker_count(12) == 3
    assert parallel.worker_count(2) == 2
    monkeypatch.setenv(parallel.WORKERS_ENVIRONMENT_VARIABLE, "0")  # invalid: taken as unset
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 10)
    assert parallel.worker_count(12) == 8
    monkeypatch.delenv(parallel.WORKERS_ENVIRONMENT_VARIABLE)
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 2)
    assert parallel.worker_count(12) == 1


def test_split_evenly_and_run_in_order_keep_the_order():
    assert parallel.split_evenly(list("abcde"), 3) == [["a", "b"], ["c", "d"], ["e"]]
    assert parallel.split_evenly(list("ab"), 5) == [["a"], ["b"]]
    assert parallel.run_in_order(lambda n: n * n, [3, 1, 2], 3) == [9, 1, 4]


def test_vectorized_ink_reading_and_dilation_match_the_scalar_forms():
    rng = np.random.default_rng(7)
    mask = rng.random((40, 30)) < 0.2
    # Half-pixel points check the round-half-to-even rule; some points are outside.
    points = np.concatenate([rng.uniform(-3, 43, (300, 2)), np.array([[2.5, 3.5], [0.5, -0.5], [29.5, 39.5]])])
    assert _ink_hits(mask, points).tolist() == [_ink_at(mask, x, y) for x, y in points]
    from scipy import ndimage
    for shape in [(40, 30), (1, 1), (2, 7), (5, 1)]:
        sample = rng.random(shape) < 0.1
        assert np.array_equal(_dilate_5x5(sample), ndimage.binary_dilation(sample, np.ones((5, 5), dtype=bool)))


def _catalog(tools):
    catalog = copy.deepcopy(tools.state["catalog"])
    for entry in catalog.values():
        entry.pop("implementation_sha256", None)
    return catalog


def test_parallel_inspection_matches_one_worker(tmp_path, monkeypatch):
    path, _ = drawing(tmp_path / "input")
    monkeypatch.setenv(parallel.WORKERS_ENVIRONMENT_VARIABLE, "1")
    one = DomainTools(tmp_path / "one", path)
    single = one.execute("inspect_source", {})
    monkeypatch.setenv(parallel.WORKERS_ENVIRONMENT_VARIABLE, "3")
    three = DomainTools(tmp_path / "three", path)
    several = three.execute("inspect_source", {})
    assert single["ok"] and several["ok"]
    assert several["resources"]["workers"] == 3
    assert several["returned_section_ids"] == single["returned_section_ids"] == ["s0", "s1", "s2"]
    assert _catalog(three) == _catalog(one)
    # One source page per call, showing every inspected section.
    pages = [a for a in three.state["inspection_artifacts"] if a["kind"] == "source_page"]
    assert len(pages) == 1
    kinds = [a["kind"] for a in three.state["inspection_artifacts"]]
    assert kinds == [a["kind"] for a in one.state["inspection_artifacts"]]
