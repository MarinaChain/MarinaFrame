"""An empty candidate catalog discloses why each traced interpretation was rejected.

Authentic pattern (Wapama HAER CA-67 sheet 5 and Balclutha HAER CA-54 sheets 7
and 48): in overlaid body plans and structural sections the trace hops between
station curves, grid lines, lettering and leader lines. The catalog dropped
those traces without a record, so the inspection showed no candidate and no
reason. This raster is synthetic: short strokes that alternate between two
columns force such a hopping trace.
"""
import json

from PIL import Image, ImageDraw

from vessel_reconstruction.agent_tools import inspect_source_worker

CENTRE, BASE, HEIGHT = 20, 250, 210


def hopping_source(tmp_path):
    image = Image.new("RGB", (260, 290), "white")
    draw = ImageDraw.Draw(image)
    for index, top in enumerate(range(BASE - HEIGHT, BASE + 1, 3)):
        x = CENTRE + (60 if index % 2 else 100)
        draw.line((x, top, x, min(BASE, top + 2)), fill=(20,) * 3, width=2)
    image.save(tmp_path / "drawing.png")
    spec = {"schema_version": "1.0", "vessel_id": "hopping-trace", "units": "m",
            "source": {"file": "drawing.png"},
            "sections": [{"id": "s0", "x_m": 0., "roi_px": [5, 20, 255, 270],
                          "calibration": {"centerline_px": CENTRE, "baseline_px": BASE,
                                          "pixels_per_metre": 70.},
                          "z_min_m": 0., "z_max_m": 3.}]}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    return path


def test_hopping_trace_is_rejected_with_a_recorded_reason(tmp_path):
    entry = inspect_source_worker(hopping_source(tmp_path), ["s0"], tmp_path / "out")["sections"][0]
    assert entry["candidates"] == []
    assert entry["grid_evidence"]["unique_non_grid_candidate_id"] is None
    reasons = {r["hypothesis"]: r["reason"] for r in entry["rejected_trace_hypotheses"]}
    assert reasons["all_contrast_continuity"] == "not_representable_as_bounded_corridor"
    hop = next(r for r in entry["rejected_trace_hypotheses"] if r["hypothesis"] == "all_contrast_continuity")
    assert hop["maximum_step_px_per_row"] >= 40 and hop["observed_row_fraction"] >= .9
