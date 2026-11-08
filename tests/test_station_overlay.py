"""Built station cuts on the source body plan, and the per-section scoreboard."""
from __future__ import annotations

import json

import numpy as np
import pytest

from draft_fixture import draft_drawing
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.station_overlay import build_overlay, score_section, slice_mesh

PPM = 50.0
CALIBRATION = {"centerline_px": 20.0, "baseline_px": 180.0, "pixels_per_metre": PPM}


def _vertical(y_m, z_top=3.0, count=31):
    """A vertical line at half-breadth y_m, as samples and as segments."""
    points = np.array([[y_m, z] for z in np.linspace(0, z_top, count)])
    return points, np.stack([points[:-1], points[1:]], axis=1)


def _ink_image(y_m):
    """A white panel with one black vertical ink line at half-breadth y_m."""
    image = np.full((200, 200), 255, dtype=np.uint8)
    column = int(round(CALIBRATION["centerline_px"] + y_m * PPM))
    image[30:181, column] = 0
    return image


def test_scoreboard_of_a_synthetic_section_measures_the_offset_in_metres():
    reference, _ = _vertical(1.0)
    _, cut = _vertical(1.05)
    row = score_section({"section_id": "s0"}, reference, cut, PPM)
    assert row["status"] == "scored"
    assert row["max_m"] == pytest.approx(.05) and row["rms_m"] == pytest.approx(.05)
    assert row["max_px"] == pytest.approx(2.5)
    assert score_section({"section_id": "s0"}, reference, cut[:0], PPM)["status"] == "no_cut"
    assert score_section({"section_id": "s0"}, None, cut, PPM)["status"] == "no_reference"


def test_mesh_slice_of_a_cube_is_its_square_outline():
    corners = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=float)
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    triangles = np.array([t for a, b, c, d in faces for t in ((a, b, c), (a, c, d))])
    segments = slice_mesh(corners, triangles, .5)
    assert len(segments) == 2 * 8  # two slices, two triangles on each of four side faces
    points = segments.reshape(-1, 2)
    on_edge = np.isclose(points, 0) | np.isclose(points, 1)
    assert on_edge.any(axis=1).all()
    assert len(slice_mesh(corners, triangles, 2.0)) == 0


def test_overlay_scores_draws_and_labels_every_station(tmp_path):
    """Built cut 0.05 m outboard of its reference; the ink is 0.2 m further out."""
    reference, _ = _vertical(1.0)
    sections = [{"id": sid, "x_m": x, "roi_px": [0, 20, 200, 190], "calibration": CALIBRATION}
                for sid, x in (("s0", 0.0), ("s1", 1.0), ("s2", 2.0))]

    def cut(x_m):
        if x_m == 1.0:
            raise RuntimeError("cut failed")
        return _vertical(1.05)[1] if x_m == 0.0 else np.zeros((0, 2, 2))

    overlay = build_overlay(sections=sections, labels={"s0": "ai_corrected", "s1": "interpolated"},
                            references={"s0": ("authored_curve", reference)}, image=_ink_image(1.25),
                            cut=cut, out=tmp_path, cut_tolerance_m=.001)
    rows = {row["section_id"]: row for row in overlay["scoreboard"]}
    assert rows["s0"]["status"] == "scored" and rows["s0"]["label"] == "ai_corrected"
    assert rows["s0"]["reference"] == "authored_curve" and rows["s0"]["max_m"] == pytest.approx(.05)
    ink = rows["s0"]["ink_fit"]
    assert ink["max_m"] == pytest.approx(.2, abs=1 / PPM) and ink["near_fraction"] == 0
    assert rows["s1"]["status"] == "cut_failed" and rows["s1"]["label"] == "interpolated"
    assert rows["s2"]["status"] == "no_cut" and rows["s2"]["label"] == "not_built"
    assert overlay["worst_section_id"] == "s0" and overlay["worst_ink_fit_section_id"] == "s0"
    kinds = [a["kind"] for a in overlay["artifacts"]]
    assert kinds == ["station_overlay", "station_overlay_sheet", "station_scoreboard"]
    assert overlay["artifacts"][0]["section_ids"] == ["s0", "s1", "s2"]  # overlapping regions: one panel
    for artifact in overlay["artifacts"]:
        assert (tmp_path / artifact["file"]).stat().st_size > 0
    stored = json.loads((tmp_path / "station-scoreboard.json").read_text())
    assert stored["scoreboard"] == json.loads(json.dumps(overlay["scoreboard"]))


@pytest.mark.cad
def test_draft_render_has_station_overlay_and_scoreboard(tmp_path, monkeypatch):
    path, _ = draft_drawing(tmp_path / "input", count=4, blank=("s2",))
    tools = DomainTools(tmp_path / "task", path)
    tools.execute("inspect_source", {})
    built = tools.execute("build_draft", {})
    assert built["ok"], built
    rendered = tools.execute("render_candidate", {"view": "body"})
    assert rendered["ok"], rendered
    overlay = rendered["station_overlay"]
    assert overlay["status"] == "rendered", overlay
    rows = {row["section_id"]: row for row in overlay["scoreboard"]}
    assert list(rows) == ["s0", "s1", "s2", "s3"]
    assert rows["s2"]["label"] == "interpolated"
    for sid in ("s0", "s1", "s3"):
        assert rows[sid]["status"] == "scored" and rows[sid]["max_m"] < .05, rows[sid]
        assert rows[sid]["ink_fit"]["rms_m"] < .05, rows[sid]
    by_kind = {}
    for artifact in rendered["artifacts"]:
        by_kind.setdefault(artifact["kind"], []).append(artifact)
        assert (tmp_path / "task" / artifact["path"]).is_file()
    assert len(by_kind["station_overlay"]) == 4  # one panel per separate station region
    assert len(by_kind["station_overlay_sheet"]) == len(by_kind["station_scoreboard"]) == 1
    assert all(a["model_eligible"] is False for a in by_kind["station_overlay"])
    # An overlay failure never fails the render.
    monkeypatch.setattr(DomainTools, "_source", lambda self: (_ for _ in ()).throw(OSError("gone")))
    again = tools.execute("render_candidate", {"view": "body"})
    assert again["ok"] and again["station_overlay"]["status"] == "skipped"
    assert "station_overlay" not in {a["kind"] for a in again["artifacts"]}
