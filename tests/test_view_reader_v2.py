"""View reader v2 on a small synthetic lines drawing (no truth files, no stored hull)."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import view_reader_v2 as reader

PPM = 10.0
X0 = 150.0          # sheet column of x = 0
BASE = 230.0        # profile baseline row (z = 0)
CL = 400.0          # plan centreline row
HEIGHTS = (2.0, 4.0, 6.0, 8.0)
DECK_Z = 10.0


def stern_x(z):
    return max(0.0, 5.0 - 5.0 * z / 3.0)


def stem_x(z):
    return 50.0 + z


def breadth(x, z):
    aft, fore = stern_x(z), stem_x(z)
    if not aft <= x <= fore:
        return np.nan
    return (3.0 + 0.2 * z) * np.sin(np.pi * (x - aft) / (fore - aft)) ** 0.5


def sheet() -> np.ndarray:
    image = Image.new("L", (1000, 460), 255)
    draw = ImageDraw.Draw(image)
    # Profile grid, baseline and labels (labels are grey blocks left of the view).
    for z in (0.0, *HEIGHTS):
        row = BASE - z * PPM
        draw.line((100, row, 900, row), fill=128 if z == 0 else 210, width=1)
        draw.rectangle((70, row - 3, 92, row + 3), fill=90)
    draw.line((100, CL, 900, CL), fill=128, width=1)
    # Profile outline: keel, stern, stem and deck.
    zs = np.linspace(0, DECK_Z, 60)
    outline = [(X0 + stern_x(z) * PPM, BASE - z * PPM) for z in zs[::-1]]
    outline += [(X0 + stem_x(z) * PPM, BASE - z * PPM) for z in zs]
    draw.line(outline + [outline[0]], fill=20, width=3)
    # Plan waterlines and deck line.
    for z in (*HEIGHTS, DECK_Z):
        xs = np.linspace(stern_x(z), stem_x(z), 400)
        draw.line([(X0 + x * PPM, CL - breadth(x, z) * PPM) for x in xs], fill=20, width=3)
    return np.asarray(image, dtype=float)


def views():
    return {"profile": {"roi_px": [100, 50, 900, 250], "calibration": {"pixels_per_metre": PPM}},
            "half_breadth_plan": {"roi_px": [100, 280, 900, 420], "calibration": {"pixels_per_metre": PPM}}}


def test_reads_heights_profile_and_named_plan_curves():
    reading = reader.read_views(sheet(), views())
    profile, plan = reading["profile"], reading["plan"]
    assert [round(w["z_m"], 1) for w in profile.waterlines] == list(HEIGHTS)
    middle = np.abs(profile.x_m - 25.0) < 10
    assert np.nanmax(np.abs(profile.keel_z_m[middle])) < 0.15
    assert np.nanmax(np.abs(profile.top_z_m[middle] - DECK_Z)) < 0.15
    names = {w["id"]: w["z_m"] for w in profile.waterlines}
    named = 0
    for cid, curve in plan.curves.items():
        z = DECK_Z if cid == "deck" else names[cid]
        for x, y, status in zip(plan.x_m, curve["y_m"], curve["status"]):
            if status not in reader.NAMED:
                assert np.isnan(y)
                continue
            named += 1
            assert y > 0
            assert abs(y - breadth(x, round(z))) < 0.2, (cid, x, y)
    assert named > 500


def test_evidence_points_are_positive_and_count_abstentions():
    reading = reader.read_views(sheet(), views())
    points, coverage = reader.evidence_points(reading)
    plan = [p for p in points if p["view"] == "half_breadth_plan"]
    assert plan and all(p["y_m"] > 0 for p in plan)
    stats = coverage["half_breadth_plan"]
    assert stats["negative"] == 0
    assert stats["points"] + sum(stats["abstained"].values()) == stats["attempted"]
    assert {p["source_label"] for p in points} <= {"traced", "repaired"}


def test_nearest_abstains_when_two_runs_fit_the_line():
    runs = [(10.0, 12.0, 11.0), (13.0, 15.0, 14.0)]
    assert reader._nearest(runs, 12.4, 3.0, 3.0) is reader.AMBIGUOUS
    assert reader._nearest(runs, 10.5, 1.0, 3.0) == (11.0, False)
    assert reader._nearest(runs, 30.0, 3.0, 3.0) is None


def test_seed_refuses_coincident_ends():
    runs = {column: [(97.0, 99.0, 98.0)] for column in range(200)}
    column_of = int
    ends = {"a": (None, 100.0, 1.0), "b": (None, 101.0, 2.0)}
    assert reader.seed(ends, "a", 1, column_of, runs, 100.0, 3.0) is None
    ends = {"a": (None, 100.0, 1.0), "b": (None, 150.0, 2.0)}
    assert reader.seed(ends, "a", 1, column_of, runs, 100.0, 3.0) == (94, 98.0)
