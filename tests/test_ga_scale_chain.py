"""The printed dimension chain of a GA profile (ga_scale_chain): spans tied to frames.

Synthetic data only; no model is called and no partner drawing is used.
"""
from __future__ import annotations

import pytest

from vessel_reconstruction import ga_scale_chain as chain
from vessel_reconstruction.ga_scale_frames import Axis, FrameTable

# 800 mm frames from frame 0 at x 100 px, 10 px a metre: frame f is at 100 + 8 f.
TABLE = FrameTable([{"from_frame": 0, "to_frame": 200, "spacing_mm": 800.0}])
AXIS = Axis(offset=100.0, px_per_m=10.0, rms_px=0.5, ticks_used=20, ticks_read=20, basis="frame scale of this view")


def _px(frame: float) -> float:
    return 100 + 8.0 * frame


def _span(printed, first, last, text_at=None):
    middle = text_at if text_at is not None else (_px(first) + _px(last)) / 2
    return {"printed": printed, "at": (middle, 520.0), "from": (_px(first), 530.0), "to": (_px(last), 530.0)}


@pytest.mark.parametrize("printed, metres", [
    ("28400", 28.4), ("28,400", 28.4), ("28.400", 28.4), ("28400 mm", 28.4), ("28.4 m", 28.4),
    ("35@800=28000", 28.0), ("about", None), ("0.1 m", None), ("28400 - 29000", None),
])
def test_a_printed_span_reads_as_one_plausible_length(printed, metres):
    assert chain.parse_span_m(printed) == (pytest.approx(metres) if metres else None)


def _read(spans):
    result = {"frames": {"status": "read"}, "checks": []}
    work = {"table": TABLE, "axes": {"v1": AXIS}, "raw": {"chains": {"v1": spans}}}
    kept = chain.read_printed_spans(result, work)
    reasons = sorted(c["reason"] for c in result["checks"] if c["code"] == "printed_span_ignored")
    return kept, result["frames"].get("printed_spans", []), reasons


def test_a_span_between_two_frame_marks_is_printed_truth():
    kept, spans, reasons = _read([_span("28000", 40, 75)])
    assert kept == 1 and reasons == []
    assert spans == [{"from_frame": 40, "to_frame": 75, "length_m": 28.0, "text": "28000", "status": "printed"}]


@pytest.mark.parametrize("span, reason", [
    (_span("28000", 40.5, 75.5), "an end mark of the span is not at a frame"),
    (_span("28000", 40, 75, text_at=_px(80)), "the text of the span is not between its marks"),
    (_span("30000", 40, 75), "the printed length does not fit the frames of its marks"),
    (_span("frame", 40, 75), "the span does not read as one plausible length"),
])
def test_a_span_that_cannot_be_tied_is_ignored_with_its_reason(span, reason):
    kept, spans, reasons = _read([span])
    assert kept == 0 and spans == [] and reasons == [reason]


def test_two_different_lengths_for_the_same_frames_are_both_refused():
    # 28.0 m and 28.2 m both fit frames 40-75 within half a frame; which is printed is not known.
    kept, _, reasons = _read([_span("28000", 40, 75), _span("28200", 40, 75)])
    assert kept == 0 and reasons == ["two different lengths are printed for the same frames"] * 2


def _hold(space_id, first, last, x0):
    return {"id": space_id, "kind": "cargo_hold", "extent": {
        "frames": [first, last], "x_m": [x0, x0 + 0.8 * (last - first) + 0.6], "status": {"x": "measured_from_scale"}}}


def test_a_hold_takes_the_one_printed_span_of_its_frames():
    spaces = [_hold("h1", 40, 75, 32.0), _hold("h2", 75, 110, 60.0)]
    frames = {"printed_spans": [{"from_frame": 40, "to_frame": 75, "length_m": 28.0, "text": "28000"}]}
    first, second = chain.holds_with_printed_spans(spaces, frames)
    assert first["extent"]["status"]["x"] == "printed" and first["extent"]["printed_span"] == "28000"
    assert first["extent"]["x_m"][1] - first["extent"]["x_m"][0] == pytest.approx(28.0)
    assert first["extent"]["measured_box_m"] == {"x_m": [32.0, 60.6]}
    assert second["extent"]["status"]["x"] == "measured_from_scale"  # no span of its own


def test_a_span_that_matches_two_holds_is_tied_to_neither():
    # A span of frames 40-75 matches a hold of 40-75 and one of 41-76 (one frame either way).
    spaces = [_hold("h1", 40, 75, 32.0), _hold("h2", 41, 76, 32.8)]
    frames = {"printed_spans": [{"from_frame": 40, "to_frame": 75, "length_m": 28.0, "text": "28000"}]}
    assert all(s["extent"]["status"]["x"] == "measured_from_scale" for s in chain.holds_with_printed_spans(spaces, frames))
