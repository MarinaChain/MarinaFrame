"""Body panels of a sheet-only reading: split halves of one body plan, and datum snapping."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import materialize as mz

CENTRE_PX = 300
BASELINE_PX = 350


def overlaid_body_plan() -> np.ndarray:
    """A white sheet with a light centreline, a baseline and nested curves on both halves."""
    image = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(CENTRE_PX, 20), (CENTRE_PX, 380)], fill=(170, 170, 170), width=1)
    draw.line([(40, BASELINE_PX), (560, BASELINE_PX)], fill=(30, 30, 30), width=2)
    for half_width in (60, 120, 180, 240):
        draw.arc([CENTRE_PX - half_width, 60, CENTRE_PX + half_width, 2 * BASELINE_PX - 60], 90, 270,
                 fill=(15, 15, 15), width=3)
        draw.arc([CENTRE_PX - half_width, 60, CENTRE_PX + half_width, 2 * BASELINE_PX - 60], 270, 90,
                 fill=(15, 15, 15), width=3)
    return np.asarray(image)


def setup(region, centre, view_id="body"):
    return {"setup_id": f"setup-{region[0]}", "view": "body", "view_id": view_id, "region_px": region,
            "centreline_px": centre, "baseline_px": float(BASELINE_PX), "pixels_per_metre": 20.0,
            "grid_spacing_m": 2.0}


def state_with(setups, kind="body"):
    return {"described_views": [{"view_id": "body", "kind": kind, "region_px": [40, 20, 560, 380]}],
            "sheet_setups": {s["setup_id"]: s for s in setups}}


def test_halves_split_at_the_centreline_become_one_body_plan():
    # shipd-1-00679-3v-L0 live: the reading split the overlaid body plan into two
    # panels at a centreline read 6 px off the drawn one.
    reading = state_with([setup([40, 20, 294, 380], 294.0), setup([294, 20, 560, 380], 294.0)])
    warnings = []
    panels = mz.body_panels(overlaid_body_plan(), reading, [], warnings)
    assert len(panels) == 1
    assert panels[0]["region_px"][0] == 40 and panels[0]["region_px"][2] == 560
    # The drawn centreline near the model's reading is the datum.
    assert panels[0]["centreline_px"] == CENTRE_PX
    assert any("halves of one overlaid body plan" in w for w in warnings)
    stations = [{"id": str(i), "x_m": 10.0 * i, "side": ""} for i in range(1, 10)]
    pairs = mz.assign(stations, panels, warnings)
    assert [basis for *_, basis in pairs].count("aft half (left of centreline)") == 4


def test_separate_station_panels_stay_separate():
    # Two panels, each with its own centreline in its middle: separate panels.
    reading = state_with([setup([40, 20, 300, 380], 170.0), setup([300, 20, 560, 380], 430.0)])
    panels = mz._join_split_halves(list(reading["sheet_setups"].values()), {"body": "body"}, [])
    assert len(panels) == 2


def test_a_later_reading_is_measured_against_the_drawing_not_the_earlier_reading():
    # A second reading of a sheet-only task must not treat the first reading's
    # sections as declared (the profile station check would be skipped).
    from types import SimpleNamespace

    from vessel_reconstruction.investigation_tools import InvestigationTools

    captured, materialized = {"source": {}}, {"source": {}, "sections": [{"id": "1"}]}
    tools = SimpleNamespace(state={"sheet_only": True}, spec=materialized, captured_spec=captured)
    assert InvestigationTools._reading_spec(tools) is captured
    tools.state = {}
    assert InvestigationTools._reading_spec(tools) is materialized
