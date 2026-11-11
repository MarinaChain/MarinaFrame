"""Degraded scans and view-pixel coordinates (L1 sheets of the three-view factory, live)."""
from __future__ import annotations

import numpy as np

from vessel_reconstruction import intake
from vessel_reconstruction.investigation_tools import InvestigationTools


def test_ink_levels_follow_a_grey_paper_and_never_exceed_a_white_sheet():
    white = np.full((100, 100), 255.0)
    assert intake.ink_levels(white) == (intake.INK_LEVEL, intake.GROUP_LEVEL)
    grey = np.full((100, 100), 222.0)  # a scan's paper
    ink, light = intake.ink_levels(grey)
    assert ink == 222 - intake.INK_CONTRAST and light == 222 - intake.LIGHT_CONTRAST


def test_a_grey_noisy_page_keeps_its_views_apart():
    rng = np.random.default_rng(1)
    page = np.clip(222 + rng.normal(0, 4, (600, 1200)), 0, 255)
    page[rng.random(page.shape) < 0.0002] = 30  # scan specks
    for top, bottom in ((100, 200), (300, 400)):  # a profile outline, and a plan 98 px below it
        page[top:top + 2, 100:500] = 20  # under half the page width (not a frame line)
        page[bottom:bottom + 2, 100:500] = 20
        page[top:bottom, 100:102] = 20
        page[top:bottom, 498:500] = 20
    boxes = intake.ink_groups(np.repeat(page[:, :, None], 3, axis=2).astype(np.uint8))
    views = sorted((b for b in boxes if b[2] - b[0] > 300), key=lambda b: b[1])
    assert len(views) == 2 and views[0][3] < views[1][1]


def test_a_setup_in_its_evidence_views_pixels_is_converted_to_sheet_pixels():
    named = {"view_id": "profile", "region_px": [148, 148, 1963, 397]}
    evidence = {"view_id": "view-1", "crop_box_px": [148, 148, 1963, 397], "pixel_size": [1024, 140],
                "view_px_per_source_px": [1024 / 1815, 140 / 249]}
    setup = {"view": "profile", "region_px": [0, 0, 1000, 140], "pixels_per_metre": 18.0,
             "baseline_px": 140.0, "x_origin_px": 7.0, "centreline_px": None}
    note = InvestigationTools._setup_in_view_frame(setup, named, evidence)
    assert note and setup["region_px"] == named["region_px"]
    assert abs(setup["baseline_px"] - 397) < 1 and abs(setup["x_origin_px"] - (148 + 7 * 1815 / 1024)) < 1
    # A setup already in sheet pixels is left alone.
    sheet = {"view": "profile", "region_px": [150, 150, 1960, 395], "baseline_px": 390.0, "x_origin_px": 160.0}
    assert InvestigationTools._setup_in_view_frame(sheet, named, evidence) is None and sheet["baseline_px"] == 390
