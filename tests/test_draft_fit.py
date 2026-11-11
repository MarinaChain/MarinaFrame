"""Draft fit in a code-measured frame (draft_fit.py) on a synthetic three-view sheet."""
import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import draft_fit
from vessel_reconstruction.vessel_model import StationRow, VesselTable

PPM = 5.0  # pixels per metre
X0 = 50  # x = 0 (the hull's aft extreme) in sheet columns
BASELINE = 110  # profile row of z = 0
CENTRELINE = 250  # plan row of the centreline
DEPTH = 10.0
HALF_BEAM = 8.0
HINTS = [{"label": "profile", "region_px": [40, 20, 620, 125]},
         {"label": "half_breadth", "region_px": [40, 150, 620, 260]},
         {"label": "body_plan", "region_px": [640, 20, 760, 125]}]


def half_breadth(x: float, z: float) -> float:
    """A wall-sided hull whose ends rake out with height: it spans x 10 - z to 90 + z."""
    aft, fore = 10.0 - z, 90.0 + z
    return HALF_BEAM * float(np.clip(min(x - aft, fore - x) / 10.0, 0.0, 1.0))


def sheet() -> np.ndarray:
    image = Image.new("RGB", (800, 280), (240, 238, 230))
    draw = ImageDraw.Draw(image)
    grid = (200, 200, 200)
    for z in (2.0, 4.0, 6.0, 8.0):  # profile waterline grid rows
        draw.line([(40, BASELINE - z * PPM), (620, BASELINE - z * PPM)], fill=grid, width=1)
    draw.line([(40, CENTRELINE), (620, CENTRELINE)], fill=grid, width=1)  # plan centreline
    ink = (20, 20, 20)
    # Profile outline: keel, stern and stem rakes, deck.
    draw.line([(X0 + 10 * PPM, BASELINE), (X0 + 90 * PPM, BASELINE)], fill=ink, width=2)
    draw.line([(X0 + 10 * PPM, BASELINE), (X0, BASELINE - DEPTH * PPM)], fill=ink, width=2)
    draw.line([(X0 + 90 * PPM, BASELINE), (X0 + 100 * PPM, BASELINE - DEPTH * PPM)], fill=ink, width=2)
    draw.line([(X0, BASELINE - DEPTH * PPM), (X0 + 100 * PPM, BASELINE - DEPTH * PPM)], fill=ink, width=2)
    # Plan: each waterline's half-breadth above the centreline.
    for z in (2.0, 4.0, 6.0, 8.0, DEPTH):
        xs = np.linspace(10.0 - z, 90.0 + z, 200)
        draw.line([(X0 + x * PPM, CENTRELINE - half_breadth(x, z) * PPM) for x in xs], fill=ink, width=2)
    return np.asarray(image)


def table(shift_m: float = 0.0) -> VesselTable:
    rows = []
    for x in np.arange(0.0, 101.0, 5.0):
        heights = np.linspace(0.0, DEPTH, 21)
        points = [[half_breadth(x, z), z] for z in heights]
        rows.append(StationRow(f"s{int(x)}", x + shift_m, points, "fitted" if 10 <= x <= 90 else "inferred"))
    return VesselTable(rows, [2.0, 4.0, 6.0, 8.0])


SPEC = {"sections": [{"id": "s50", "roi_px": [640, 20, 760, 125],
                      "calibration": {"pixels_per_metre": PPM, "centerline_px": 700.0, "baseline_px": BASELINE}}]}


def test_reference_frame_is_measured_on_the_outlines():
    views = draft_fit.reference_views(sheet(), HINTS, PPM)
    profile, plan = views["profile"]["calibration"], views["half_breadth_plan"]["calibration"]
    assert abs(profile["x_origin_px"] - X0) <= 2 and abs(profile["baseline_px"] - BASELINE) <= 2
    assert abs(plan["centerline_px"] - CENTRELINE) <= 1 and plan["x_origin_px"] == profile["x_origin_px"]
    # The grid rows, and the deck line (a plan view draws the deck as well).
    assert views["profile"]["waterlines_z_m"][:4] == [2.0, 4.0, 6.0, 8.0]


def test_a_cut_short_intake_region_is_widened_to_the_outline():
    hints = [{**HINTS[0], "region_px": [300, 20, 620, 125]}, HINTS[1]]
    views = draft_fit.reference_views(sheet(), hints, PPM)
    assert abs(views["profile"]["calibration"]["x_origin_px"] - X0) <= 2


def test_a_hull_moved_along_x_fits_worse():
    image = sheet()
    right = draft_fit.score(table(), SPEC, image, HINTS, PPM, HALF_BEAM)
    moved = draft_fit.score(table(3.0), SPEC, image, HINTS, PPM, HALF_BEAM)
    assert right["views"]["profile"]["fit"] > moved["views"]["profile"]["fit"]
    assert right["views"]["half_breadth_plan"]["fit"] > moved["views"]["half_breadth_plan"]["fit"]
    assert right["draft_fit"] > moved["draft_fit"]
    fits = [(right["views"].get(kind) or {}).get("fit") or 0.0 for kind in draft_fit.FIT_VIEWS]
    assert abs(right["draft_fit"] - sum(fits) / 3) < 1e-3  # views weigh equally


def test_end_x_interpolates_where_the_breadth_starts():
    xs = np.array([0.0, 10.0, 20.0])
    # On the line through the first two stations with breadth: 0 at 5 m.
    assert draft_fit._end_x(xs, np.array([np.nan, 2.0, 6.0])) == 5.0
    assert draft_fit._end_x(xs, np.array([np.nan, 8.0, 9.0])) == 0.0  # clamped into the gap
    assert draft_fit._end_x(xs, np.array([0.0, 2.0, 6.0])) == 5.0
    assert draft_fit._end_x(xs, np.array([1.0, 2.0, 3.0])) == 0.0
    assert np.isnan(draft_fit._end_x(xs, np.array([np.nan, np.nan, 0.0])))
