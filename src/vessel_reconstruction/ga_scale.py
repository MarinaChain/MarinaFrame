"""Measure a commercial GA with its own printed frame scale.

Plan: docs/plans/2026-11-12-ga-commercial.md ("Measured from the frame scale").

A GA prints a frame scale: frame numbers along the base line of the profile (and often along
the centreline of the plans) and the frame spacings ("FR. SP. = 800 MM") with the places where
the spacing changes. With them, drawn ink can be measured in metres.

Division of work:

- The model (purpose ``ga_scale``; up to seven requests a ship: the scale request, sent again
  while the scale is not established, then up to four extents requests) only points: at frame numbers,
  at the marks A.P. and F.P., at the spacing texts and the places where the spacing changes, at a few
  named places of the hull, and at the drawn boundary of each space that was read.
- Code builds the frame-spacing table, fits pixels to metres on every view with a frame scale
  (robust to a misread number), and measures LBP, LOA, depth, breadth and the extent of each
  space. When the scale cannot be established (no spacing printed, too few frame numbers, the
  numbers do not fit the spacings) every measured value is null with the reason.

A measured value has status ``measured_from_scale``. It is never a printed particular: the
``particulars`` of a reading hold printed values only (the GA exam scores those), and measured
values live in ``measured``. ``arrangement_input`` writes the file the arrangement step reads
(docs/GA_ARRANGEMENT_INPUT.md), where a particular is the printed value when there is one and
else the measured one, with its status.

Axes: metres; x forward from the aft perpendicular (frame 0), y to port, z up from the base line.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image

from . import source_record
from .ga_labels import label_family
from .provenance import write_json

PURPOSE = "ga_scale"
REQUEST_SCHEMA = "marinaframe.vision_request.v1"
INPUT_SCHEMA = "marinaframe.ga_reading.v1"
MEASURED = "measured_from_scale"
# A depth that was not measured at the deck line: the median top of the read cargo spaces took
# the place of a pointed line that was the deck at the centreline, a rail, or missing. It is an
# estimate; downstream must not treat it as measured (and must not check it against those tops).
DERIVED = "derived_from_space_tops"
# A pointed depth that only boxes with an uncertain boundary agree with: shown, never measured.
UNCONFIRMED = "unconfirmed_from_uncertain_boxes"

# Frame spacings of commercial ships (mm): ordinary frames from about 500 mm, numbered web frames
# of large tankers up to a few metres. A printed spacing outside this range is a misreading.
SPACING_RANGE_MM = (300.0, 5000.0)
# A spacing printed without a unit is metres below this value ("F.S. 0.70") and millimetres
# above it ("FR. SP. 800"); only one of the two lies in the range above.
UNITLESS_METRES_BELOW = 10.0
# A frame scale needs this many frame numbers that fit the spacings.
MIN_TICKS = 4
# A tick whose place is further from the fitted scale than this is a misread number or a place
# pointed wrongly; it is left out of the fit (pixels of the sheet, and frame widths).
MIN_OUTLIER_PX = 4.0
OUTLIER_FRAMES = 1.5
# A range with this many frame numbers is checked against its printed spacing: the pixels per
# frame of the numbers must give the printed spacing within the tolerance (a range with fewer
# numbers is too short for this: three numbers at a ship's end were 17 % off on a good table).
MIN_RANGE_TICKS = 5
RANGE_SLOPE_TOLERANCE = 0.15
# Two readings of one printed spacing text (from two requests) lie this close (sheet pixels).
SAME_LABEL_PX = 40.0
# This many neighbouring frame numbers off the fitted scale are not misreadings: the table is wrong.
MAX_OUTLIER_RUN = 2
# At most this share of the ticks may be left out; with more, the scale is not established.
MAX_OUTLIER_SHARE = 0.34
# The fitted scale must place its own ticks within one frame width (root mean square).
MAX_RMS_FRAMES = 1.0
# Two marks of the same thing on overlapping images are one mark when this close (sheet pixels).
SAME_MARK_PX = 10.0
# Scale requests for one ship: another is sent only while the scale is not established. The
# marks of all attempts are read together (a change of spacing that one reply leaves out is in
# the next; the frame numbers decide between two readings of a printed spacing).
SCALE_ATTEMPTS = 3
# A plan without frame numbers takes the scale of the profile only when its hull is drawn as
# long as the profile's hull, within this share (one sheet, one drawing scale; four pointed hull
# ends of about 1 % each).
SAME_SCALE_TOLERANCE = 0.04
# A place pointed by the model is taken to be this exact (pixels of the attached image).
POINT_SIGMA_IMAGE_PX = 2.0
# Room around a view's box in its images: the frame scale and the spacing line lie below the
# profile, outside a tight view box.
VIEW_PAD_X = 0.04
VIEW_PAD_Y = 0.30
MAX_IMAGES = 6
MAX_SPACES = 150
# Spaces asked in one extents request. Asked for 71 spaces at once the model boxed 20 (round u1;
# 43 of 43 when asked for 43), so the spaces go out in requests of this size, most useful first.
EXTENT_SPACES_PER_REQUEST = 20
DECK_EQUIPMENT = ("cargo_crane", "cargo_hatch")
MAX_EXTENT_REQUESTS = 4
# The order in which spaces are asked: holds and cargo tanks, then the tanks beside them (a wing
# ballast tank makes a cargo tank narrower than the hull), then the rest.
EXTENT_PRIORITY = ("cargo_hold", "cargo_tank", "slop_tank", "ballast_tank", "fuel_tank", "engine_room",
                   "cargo_hatch", "accommodation_deck", "other_tank", "cargo_crane", "container_bay", "other_space")
# Sanity bounds of commercial hull proportions; a measured set outside them is not used.
LBP_OVER_LOA = (0.85, 1.001)
LENGTH_OVER_BREADTH = (3.0, 12.0)
BREADTH_OVER_DEPTH = (1.0, 4.5)
# The moulded depth is taken amidships: the pointed deck line must lie in this part of the hull
# length (clear of the poop, the forecastle and, on most ships, the deckhouse).
MIDSHIP_SHARE = (0.25, 0.75)
# Spaces that lie below the upper deck: the deck is not lower than the top of any of them.
BELOW_DECK_KINDS = ("cargo_hold", "cargo_tank", "slop_tank", "ballast_tank", "fuel_tank", "engine_room")
# Without a pointed deck line, the depth is taken from the tops of the cargo spaces only when
# this many of them agree and another kind of space (or the lowest deckhouse tier) ends there too.
MIN_DECK_TOPS = 3
# A deck line pointed this little above the tops of the cargo spaces is the deck at the
# centreline (camber) or the top of the rail or bulwark, not the deck at side: bulwarks are
# about 1.0 to 1.4 m high and camber is below 1 m. Higher than this, the cargo spaces end
# below the deck (topside tanks).
RAIL_OR_CAMBER_M = 1.5
# The A.P. mark and frame 0 are the same place; they may be pointed this many frame widths apart.
AP_MARK_FRAMES = 2.0
# A space whose box ends this close to the centreline (metres) ends on it.
CENTRE_TOLERANCE_M = 0.6

PLAN_KINDS = ("deck_plan", "tank_top_plan")


# ------------------------------------------------------------------ printed text

def parse_tick(label: str):
    """('frame', n), ('ap', None), ('fp', None) or None for the printed text of a scale mark."""
    text = re.sub(r"[\s.]", "", label.upper())
    if text in ("AP", "A/P"):
        return "ap", None
    if text in ("FP", "F/P"):
        return "fp", None
    match = re.fullmatch(r"(?:FR|F)?(-?\d{1,3})", text)
    return ("frame", int(match[1])) if match else None


def parse_spacing_mm(printed: str) -> float | None:
    """Millimetres of a printed frame spacing, or None.

    '800 MM', '700mm', '0.80 M', 'F.S. 0.70', 'FS ~720', '3,200 mm'. A comma can be a decimal
    or a thousands mark; the value is used only when exactly one reading lies in the range.
    """
    text = re.sub(r"\b(?:F\.?\s?S\.?|FR\.?\s?SP\.?|FRAME\s+SPAC(?:E|ING))", " ", printed.upper())
    match = re.fullmatch(r"[\s:=~≈]*(\d+(?:[.,]\d+)?)\s*(MM|M)?\.?\s*", text)
    if not match:
        return None
    number = match[1]
    readings = {float(number.replace(",", "."))}
    if re.fullmatch(r"\d{1,3},\d{3}", number):
        readings.add(float(number.replace(",", "")))
    in_range = set()
    for value in readings:
        if match[2] == "M" or (match[2] is None and value < UNITLESS_METRES_BELOW):
            value *= 1000.0
        if SPACING_RANGE_MM[0] <= value <= SPACING_RANGE_MM[1]:
            in_range.add(value)
    return in_range.pop() if len(in_range) == 1 else None


# ------------------------------------------------------------------ the frame-spacing table

class FrameTable:
    """Frame spacings [{from_frame, to_frame, spacing_mm}] in rising frame order; frame 0 is the AP.

    The first and last spans have open ends for the mathematics (``from_frame`` / ``to_frame``
    are then the ends of the drawn scale, kept for the output).
    """

    def __init__(self, spans: list[dict]):
        if not spans:
            raise ValueError("a frame table needs a span")
        self.spans = spans

    def spacing_m(self, frame: float) -> float:
        """The spacing forward of ``frame``."""
        for span in self.spans[:-1]:
            if frame < span["to_frame"]:
                return span["spacing_mm"] / 1000.0
        return self.spans[-1]["spacing_mm"] / 1000.0

    def _knots(self) -> list[tuple[float, float]]:
        """(frame, x) at every change of spacing, with x = 0 at frame 0."""
        inner = [float(span["to_frame"]) for span in self.spans[:-1]]
        knots, x = [], 0.0
        # Walk aft and forward from frame 0 over the inner boundaries.
        forward = sorted(f for f in inner if f > 0)
        aft = sorted((f for f in inner if f <= 0), reverse=True)
        at = 0.0
        for boundary in forward:
            x += (boundary - at) * self.spacing_m((at + boundary) / 2)
            knots.append((boundary, x))
            at = boundary
        at, x = 0.0, 0.0
        for boundary in aft:
            x -= (at - boundary) * self.spacing_m((at + boundary) / 2)
            knots.append((boundary, x))
            at = boundary
        knots.append((0.0, 0.0))
        return sorted(set(knots))

    def x_m(self, frame: float) -> float:
        """Metres forward of frame 0 (negative aft of it)."""
        knots = self._knots()
        if frame <= knots[0][0]:
            return knots[0][1] - (knots[0][0] - frame) * self.spans[0]["spacing_mm"] / 1000.0
        for (f0, x0), (f1, x1) in zip(knots, knots[1:]):
            if frame <= f1:
                return x0 + (frame - f0) * (x1 - x0) / (f1 - f0)
        return knots[-1][1] + (frame - knots[-1][0]) * self.spans[-1]["spacing_mm"] / 1000.0

    def frame_at(self, x_m: float) -> float:
        """The (fractional) frame at ``x_m``."""
        knots = self._knots()
        if x_m <= knots[0][1]:
            return knots[0][0] - (knots[0][1] - x_m) / (self.spans[0]["spacing_mm"] / 1000.0)
        for (f0, x0), (f1, x1) in zip(knots, knots[1:]):
            if x_m <= x1:
                return f0 + (x_m - x0) * (f1 - f0) / (x1 - x0)
        return knots[-1][0] + (x_m - knots[-1][1]) / (self.spans[-1]["spacing_mm"] / 1000.0)


def _theil_sen(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """A line y = a + b x that a few wrong points do not move (median of the pairwise slopes)."""
    i, j = np.triu_indices(len(x), 1)
    apart = x[i] != x[j]
    slope = float(np.median((y[j] - y[i])[apart] / (x[j] - x[i])[apart]))
    return float(np.median(y - slope * x)), slope


def _range_slope(ticks: list[tuple[int, float]]) -> float:
    """Sheet pixels per frame of the frame numbers of one range (a few wrong ones do not move it)."""
    frames = np.array([t[0] for t in ticks], float)
    places = np.array([t[1] for t in ticks], float)
    return _theil_sen(frames, places)[1]


def consistent_ticks(ticks: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Frame numbers whose places rise (or fall) with the numbers: (frame, sheet x) sorted by x.

    The spacing can change several times along a ship, so the places are not on one straight
    line; but they are in order. The longest ordered run of the numbers is kept; a misread
    number that breaks the order is left out (one that keeps the order is left to ``fit_axis``).
    """
    unique = {}
    for frame, x in ticks:
        unique.setdefault(frame, []).append(x)
    # The same number pointed twice at different places is not used.
    points = sorted(((frame, float(np.mean(xs))) for frame, xs in unique.items()
                     if max(xs) - min(xs) <= SAME_MARK_PX), key=lambda p: p[1])
    if len(points) < 2:
        return []

    def longest_rising(values: list[float]) -> list[int]:
        best = [[index] for index in range(len(values))]
        for index, value in enumerate(values):
            for before in range(index):
                if values[before] < value and len(best[before]) + 1 > len(best[index]):
                    best[index] = best[before] + [index]
        return max(best, key=len)

    frames = [float(frame) for frame, _ in points]
    rising, falling = longest_rising(frames), longest_rising([-f for f in frames])
    return [points[index] for index in (rising if len(rising) >= len(falling) else falling)]


def spacing_table(ticks: list[tuple[int, float]], labels: list[tuple[float, float]],
                  boundaries: list[float], _retry: bool = True,
                  _one_frame: tuple[float, ...] = ()) -> tuple[FrameTable | None, str]:
    """The frame table of one view, or (None, reason).

    ``ticks``: (frame, sheet x) of the frame numbers; ``labels``: (spacing mm, sheet x) of the
    printed spacings; ``boundaries``: sheet x of every drawn change of spacing.

    The range with the most frame numbers gives the scale (pixels per metre) from its printed
    spacing. Each change of spacing is then placed on a frame from the frame numbers next to it
    (or, in a range without numbers, from the change before it and the printed spacing).
    """
    ticks = consistent_ticks(ticks)
    if len(ticks) < 2:
        return None, "fewer than two frame numbers were read on the frame scale"
    if not labels:
        return None, "no frame spacing is printed"
    bow_right = ticks[-1][0] > ticks[0][0]
    cuts = []
    for place in sorted(boundaries):
        if not cuts or place - cuts[-1] > SAME_MARK_PX:
            cuts.append(place)
    edges = [-math.inf, *cuts, math.inf]
    inside = [[t for t in ticks if low < t[1] <= high] for low, high in zip(edges, edges[1:])]
    # The printed texts of each range: texts at one place are readings of one printed value.
    groups: list[list[tuple[float, set]]] = []
    for low, high in zip(edges, edges[1:]):
        here = sorted((place, mm) for mm, place in labels if low < place <= high)
        texts: list[tuple[float, set]] = []
        for index, (place, mm) in enumerate(here):
            if index and place - here[index - 1][0] <= SAME_LABEL_PX:
                texts[-1][1].add(mm)
            else:
                texts.append((place, {mm}))
        groups.append(texts)
    # A range too short to hold its text (one frame between two drawn changes) has it printed
    # beside it, in a neighbouring range, which then shows two different spacings. Such a text
    # belongs to the short range: the neighbour's text nearest to it moves there.
    for index, texts in enumerate(groups):
        if texts or len(inside[index]) > 1 or index in (0, len(groups) - 1):
            continue
        for neighbour, near_edge in ((index + 1, edges[index + 1]), (index - 1, edges[index])):
            others = groups[neighbour]
            if len({frozenset(values) for _, values in others}) < 2:
                continue
            nearest = min(range(len(others)), key=lambda k: abs(others[k][0] - near_edge))
            groups[index] = [others.pop(nearest)]
            break
    locals_found: list[tuple[float, float, float]] = []  # (sheet x, local mm, main mm)
    for index, texts in enumerate(groups):
        # The text of a short range whose drawn changes were left out (see below) is a one-frame
        # spacing inside the range around it, when that range prints one other spacing.
        forced = [(place, values) for place, values in texts
                  if any(abs(place - spot) <= SAME_MARK_PX for spot in _one_frame)]
        others = {value for place, values in texts for value in values if (place, values) not in forced}
        if forced and len(others) == 1 and all(len(values) == 1 for _, values in forced):
            main = next(iter(others))
            groups[index] = [text for text in texts if text not in forced]
            locals_found += [(place, next(iter(values)), main) for place, values in forced]
            continue
        local = _local_intervals(texts, inside[index])
        if local is not None:
            main, places = local
            groups[index] = [text for text in texts if text[1] == {main}]
            locals_found += [(place, mm, main) for place, mm in places]
    found = []
    for texts in groups:
        # Texts at two places with two values are two printed spacings, and the change between
        # them was not marked.
        texts = [values for _, values in texts]
        agreed = set.intersection(*texts) if texts else set()
        if texts and not agreed:
            return None, "two different frame spacings are printed with no change drawn between them"
        found.append(agreed)
    # Pixels per metre from the range with the most frame numbers among those with one spacing.
    sure = [index for index in range(len(found)) if len(found[index]) == 1 and len(inside[index]) >= 2]
    if not sure:
        return None, ("two different frame spacings are printed with no change drawn between them"
                      if any(len(f) > 1 for f in found) else "no range of the frame scale has two frame numbers")
    anchor = max(sure, key=lambda index: len(inside[index]))
    px_per_m = _range_slope(inside[anchor]) / (next(iter(found[anchor])) / 1000.0)  # negative: bow to the left
    values: list[float | None] = []
    chosen_by_fit: list[tuple[int, int, float]] = []  # (first frame, last frame, mm) of a range
    printed = set().union(*found) if found else set()
    for index, candidates in enumerate(found):
        # The frame numbers of a range show its spacing: they decide between two readings of
        # the printed value (two requests can read "600" and "800" at one place), and they
        # refuse a printed value that the numbers contradict (a misread value, or a change
        # of spacing that was not marked).
        fitting = candidates
        if len(inside[index]) >= (2 if len(candidates) > 1 else MIN_RANGE_TICKS):
            slope = _range_slope(inside[index])
            fitting = {mm for mm in candidates
                       if abs(slope / (px_per_m * mm / 1000.0) - 1) <= RANGE_SLOPE_TOLERANCE}
            if candidates and not fitting:
                chosen = _spacing_from_fit(inside[index], px_per_m, printed)
                if chosen is None:
                    return None, "the frame numbers of a range do not fit its printed spacing"
                fitting = {chosen}
                frames_here = [frame for frame, _ in inside[index]]
                chosen_by_fit.append((min(frames_here), max(frames_here), chosen))
        if len(fitting) > 1:
            return None, "two different frame spacings are printed with no change drawn between them"
        values.append(next(iter(fitting)) if fitting else None)
    # A range without a printed spacing: at an end of the scale it takes no part; between two
    # ranges, or with frame numbers inside it, the scale is not established.
    for index, value in enumerate(values):
        if value is not None:
            continue
        low, high = edges[index], edges[index + 1]
        if index not in (0, len(values) - 1) or any(low < place <= high for _, place in ticks):
            return None, "a part of the frame scale has no printed spacing"
    while values[0] is None:
        values.pop(0)
        cuts.pop(0)
    while values[-1] is None:
        values.pop()
        cuts.pop()
    # The same spacing on both sides of a mark is no change.
    for index in range(len(values) - 1, 0, -1):
        if values[index] == values[index - 1]:
            values.pop(index)
            cuts.pop(index - 1)
    edges = [-math.inf, *cuts, math.inf]
    inside = [[t for t in ticks if low < t[1] <= high] for low, high in zip(edges, edges[1:])]
    anchor = max(range(len(values)), key=lambda index: len(inside[index]))

    def frame_from_ticks(cut: float, region: int) -> list[float]:
        """The frame at ``cut`` as the three nearest frame numbers of ``region`` place it: near
        numbers need a short step along the scale, and three outvote one misread number."""
        step = px_per_m * values[region] / 1000.0
        nearest = sorted(inside[region], key=lambda tick: abs(tick[1] - cut))[:3]
        return [frame + (cut - place) / step for frame, place in nearest]

    cut_frames: list[int | None] = [None] * len(cuts)
    # Outward from the anchor range: first the cuts ahead of it on the sheet, then those before.
    for order in (range(anchor, len(cuts)), range(anchor - 1, -1, -1)):
        for index in order:
            estimates = frame_from_ticks(cuts[index], index) + frame_from_ticks(cuts[index], index + 1)
            if not estimates:
                # No frame number on either side: from the neighbouring change and the spacing between.
                inner = index - 1 if index >= anchor else index + 1
                region = index if index >= anchor else index + 1
                step = px_per_m * values[region] / 1000.0
                estimates = [cut_frames[inner] + (cuts[index] - cuts[inner]) / step]
            cut_frames[index] = int(round(float(np.median(estimates))))
    # A short range between two drawn changes must span its frames at its printed spacing (round
    # u10: a change drawn four frames past a one-frame "1200" made a 1200 mm range of four
    # frames, and a hold 2 m short). Such a pair of changes is left out and the table built again:
    # the text then counts as a one-frame spacing that the frame numbers must confirm.
    wrong, texts_of_wrong = [], []
    for index in range(1, len(values) - 1):
        if len(inside[index]) >= 2:
            continue  # its frame numbers checked it above
        drawn_m = abs(cuts[index] - cuts[index - 1]) / abs(px_per_m)
        expected_m = (cut_frames[index] - cut_frames[index - 1]) * values[index] / 1000.0
        if abs(abs(drawn_m) - abs(expected_m)) > SHORT_RANGE_TOLERANCE * values[index] / 1000.0:
            wrong += [cuts[index - 1], cuts[index]]
            low, high = sorted((cuts[index - 1], cuts[index]))
            texts_of_wrong += [place for mm, place in labels if low <= place <= high and mm == values[index]]
    if wrong:
        if not _retry:
            return None, "a short range between two drawn changes does not span its frames at its spacing"
        kept = [place for place in boundaries if all(abs(place - bad) > SAME_MARK_PX for bad in wrong)]
        return spacing_table(ticks, labels, kept, _retry=False, _one_frame=tuple(texts_of_wrong))
    spans = [{"from_frame": low, "to_frame": high, "spacing_mm": value}
             for low, high, value in zip([None, *cut_frames], [*cut_frames, None], values)]
    if not bow_right:
        spans = [{"from_frame": s["to_frame"], "to_frame": s["from_frame"], "spacing_mm": s["spacing_mm"]}
                 for s in reversed(spans)]
    inner = [s["to_frame"] for s in spans[:-1]]
    if inner != sorted(set(inner)):
        return None, "the changes of frame spacing are not in frame order"
    numbers = [frame for frame, _ in ticks]
    spans[0]["from_frame"] = min(numbers + inner)
    spans[-1]["to_frame"] = max(numbers + inner)
    for first, last, mm in chosen_by_fit:
        for span in spans:
            if span["spacing_mm"] == mm and span["from_frame"] <= last and first <= span["to_frame"]:
                span["status"] = CHOSEN_BY_FIT
    for place, mm, main in locals_found:
        spans = _with_local_interval(spans, _local_frame(ticks, place, mm / main), mm)
        if spans is None:
            return None, "a local frame spacing does not lie inside a range of its main spacing"
    return FrameTable(spans), "established"


# When the frame numbers of a range contradict its printed spacing in every reply (round u9n2:
# a printed "800" read as "600" three times), the spacing the numbers fit is taken, if it is one
# of these (or another value printed on the scale) and fits clearly better than the rest. Its
# span is marked as chosen by the fit, not read.
STANDARD_SPACINGS_MM = (500.0, 550.0, 600.0, 650.0, 700.0, 750.0, 800.0, 850.0, 900.0, 950.0, 1000.0)
CHOSEN_BY_FIT = "chosen_by_frame_number_fit"
FIT_CHOICE_ERROR = 0.03     # the chosen spacing is within 3 % of what the numbers show
FIT_CHOICE_MARGIN = 0.05    # and every other spacing is off by at least 5 % (and twice as much)
# The two halves of the range must show one spacing: a range that holds two spacings (a change
# not drawn) fits neither, and its mean would fit a wrong one (600 and 800 average to 750).
STRAIGHT_RUN_TOLERANCE = 0.06


def _spacing_from_fit(ticks: list[tuple[int, float]], px_per_m: float, printed: set[float]) -> float | None:
    """The spacing (mm) that the frame numbers of one range show clearly, or None."""
    if len(ticks) < MIN_RANGE_TICKS:
        return None
    ordered = sorted(ticks)
    half = len(ordered) // 2
    first, second = _range_slope(ordered[:half + 1]), _range_slope(ordered[half:])
    if second == 0 or abs(first / second - 1) > STRAIGHT_RUN_TOLERANCE:
        return None
    shown_mm = abs(_range_slope(ordered) / px_per_m) * 1000.0
    errors = sorted((abs(shown_mm / mm - 1), mm) for mm in set(STANDARD_SPACINGS_MM) | set(printed))
    (best, chosen), (runner_up, _) = errors[0], errors[1]
    if best <= FIT_CHOICE_ERROR and runner_up >= max(FIT_CHOICE_MARGIN, 2 * best):
        return chosen
    return None


# A local spacing printed for one frame inside a range of another spacing ("1200" under two
# close bulkheads in a range of 800; review round 4) lengthens the scale after it by
# (local / main - 1) frames. One such frame is a few pixels, about the scatter of the frame
# numbers (round u8: 5 px against +-3 px), so the frame numbers of the whole range decide: a
# line through them must fit with the local frames at most this share of the residual it has
# without them.
LOCAL_FIT_GAIN = 0.8
# A short range's drawn length may differ from its frames at its spacing by this share of one
# frame (the places of its two changes are each pointed to about a quarter frame).
SHORT_RANGE_TOLERANCE = 0.5


def _bracket(ticks: list[tuple[int, float]], place: float) -> tuple[tuple[int, float], tuple[int, float]] | None:
    """The two neighbouring frame numbers (in sheet order) around sheet x ``place``, or None."""
    ordered = sorted(ticks, key=lambda tick: tick[1])
    for before, after in zip(ordered, ordered[1:]):
        if before[1] < place < after[1]:
            return before, after
    return None


def _line_rms(frames: list[float], places: list[float]) -> float:
    """The residual (pixels) of the least-squares line through (frame, place)."""
    slope, offset = np.polyfit(frames, places, 1)
    return float(np.sqrt(np.mean((np.polyval([slope, offset], frames) - np.asarray(places)) ** 2)))


def _local_intervals(texts: list[tuple[float, set]], ticks: list[tuple[int, float]]):
    """(main mm, [(place, local mm)]) when a range prints a second spacing only for single
    frames, which its frame numbers confirm; else None.

    Each of the two values is tried as the main spacing; the other value's frames must make the
    frame numbers of the range fit one line clearly better (``LOCAL_FIT_GAIN``).
    """
    values = {next(iter(values)) for _, values in texts if len(values) == 1}
    if len(values) != 2 or any(len(values_here) != 1 for _, values_here in texts) or len(ticks) < MIN_RANGE_TICKS:
        return None
    frames = [float(frame) for frame, _ in ticks]
    places = [place for _, place in ticks]
    plain = _line_rms(frames, places)
    best = None
    for main in values:
        locals_here = [(place, next(iter(here))) for place, here in texts if here != {main}]
        if any(_bracket(ticks, place) is None for place, _ in locals_here):
            continue
        starts = [(_local_frame(ticks, place, mm / main), mm / main) for place, mm in locals_here]
        # A frame number forward of a local frame k..k+1 lies (ratio - 1) main frames further on.
        stretched = [frame + sum(ratio - 1 for start, ratio in starts if frame >= start + 1) for frame in frames]
        fit = _line_rms(stretched, places)
        if fit <= LOCAL_FIT_GAIN * plain and (best is None or fit < best[0]):
            best = (fit, main, locals_here)
    return None if best is None else (best[1], best[2])


def _local_frame(ticks: list[tuple[int, float]], place: float, ratio: float) -> int:
    """The frame where a local interval starts: its text is printed at the middle of it."""
    (frame_a, x_a), (frame_b, x_b) = _bracket(ticks, place)
    rising = frame_b > frame_a
    # The gap in main frames: the frame numbers apart, and the local frame's extra length.
    gap = (frame_b - frame_a) + (ratio - 1 if rising else 1 - ratio)
    offset = (place - x_a) * gap / (x_b - x_a)  # main frames from frame_a to the text
    # The text is at the middle of the local frame k..k+1: k + ratio/2 from below when the
    # numbers rise along the sheet, k + 1 - ratio/2 from above when they fall.
    return int(round(frame_a + offset - ratio / 2 if rising else frame_a + offset + ratio / 2 - 1))


def _with_local_interval(spans: list[dict], frame: int, mm: float) -> list[dict] | None:
    """The spans with frames ``frame``..``frame + 1`` at ``mm``; None when no span holds them."""
    for index, span in enumerate(spans):
        if span["from_frame"] <= frame and frame + 1 <= span["to_frame"]:
            parts = [{"from_frame": span["from_frame"], "to_frame": frame, "spacing_mm": span["spacing_mm"]},
                     {"from_frame": frame, "to_frame": frame + 1, "spacing_mm": mm},
                     {"from_frame": frame + 1, "to_frame": span["to_frame"], "spacing_mm": span["spacing_mm"]}]
            return spans[:index] + [part for part in parts if part["to_frame"] > part["from_frame"]] + spans[index + 1:]
    return None


@dataclass(frozen=True)
class Axis:
    """Sheet x of one view as metres: ``px = offset + px_per_m * x_m`` (negative when the bow is left)."""
    offset: float
    px_per_m: float
    rms_px: float
    ticks_used: int
    ticks_read: int
    basis: str  # "frame scale of this view" or "scale of the profile; hull ends matched"

    def x_m(self, px: float) -> float:
        return (px - self.offset) / self.px_per_m

    def length_m(self, pixels: float) -> float:
        return abs(pixels / self.px_per_m)


def fit_axis(ticks: list[tuple[int, float]], table: FrameTable) -> tuple[Axis | None, str]:
    """Fit sheet pixels to metres from the frame numbers of one view, or (None, reason)."""
    ticks = consistent_ticks(ticks)
    read = len(ticks)
    if read < MIN_TICKS:
        return None, f"only {read} frame numbers fit one scale"
    metres = np.array([table.x_m(frame) for frame, _ in ticks])
    places = np.array([place for _, place in ticks])
    offset, slope = _theil_sen(metres, places)
    frame_px = abs(slope) * min(s["spacing_mm"] for s in table.spans) / 1000.0
    keep = np.abs(places - (offset + slope * metres)) <= max(MIN_OUTLIER_PX, OUTLIER_FRAMES * frame_px)
    run = longest = 0
    for kept in keep[np.argsort(places)]:
        run = 0 if kept else run + 1
        longest = max(longest, run)
    if keep.sum() < MIN_TICKS or keep.sum() < (1 - MAX_OUTLIER_SHARE) * read or longest > MAX_OUTLIER_RUN:
        return None, "the frame numbers do not fit the printed spacings"
    # Outliers are single misread numbers. When every number of one spacing range is off the fit,
    # the spacing of a range is wrong (a misread "600" for "800" gives a fit of the other range
    # that leaves this one out), and the whole scale is refused.
    frames = np.array([frame for frame, _ in ticks])
    for index, span in enumerate(table.spans):
        # A frame where the spacing changes starts the next range; the last range keeps its end.
        last = index == len(table.spans) - 1
        inside = (frames >= span["from_frame"]) & ((frames <= span["to_frame"]) if last else
                                                   (frames < span["to_frame"]))
        if inside.sum() >= 2 and not keep[inside].any():
            return None, "the frame numbers of one spacing range do not fit its printed spacing"
    slope, offset = np.polyfit(metres[keep], places[keep], 1)
    rms = float(np.sqrt(np.mean((places[keep] - (offset + slope * metres[keep])) ** 2)))
    if rms > MAX_RMS_FRAMES * frame_px:
        return None, "the frame numbers do not fit the printed spacings"
    return Axis(float(offset), float(slope), rms, int(keep.sum()), read, "frame scale of this view"), "fitted"


# ------------------------------------------------------------------ request images

def _pad(box, sheet_size) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    pad_x, pad_y = (right - left) * VIEW_PAD_X, max(40.0, (bottom - top) * VIEW_PAD_Y)
    return (max(0, math.floor(left - pad_x)), max(0, math.floor(top - pad_y)),
            min(sheet_size[0], math.ceil(right + pad_x)), min(sheet_size[1], math.ceil(bottom + pad_y)))


def chosen_views(result: dict) -> dict[str, dict]:
    """The largest profile, deck plan and tank top plan of a reading, by kind."""
    def area(view):
        left, top, right, bottom = view["box_px"]
        return (right - left) * (bottom - top)
    chosen = {}
    for kind in ("profile", *PLAN_KINDS):
        views = [v for v in result.get("views", []) if v["kind"] == kind]
        if views:
            chosen[kind] = max(views, key=area)
    return chosen


def _write_request(plan: list[tuple[str, str, tuple, float]], sheet_path: Path, out: Path, context) -> None:
    """One ``ga_scale`` request directory: (image_id, view, sheet box, scale) images of the sheet.

    ``context`` is the request context, or a function of ``{image_id: (width, height)}`` that
    returns it. Images can be sent smaller than planned (request size), so anything in image
    pixels must come from the sizes actually written.
    """
    from . import ga_commercial as ga
    out.mkdir(parents=True, exist_ok=False)
    sheet = Image.open(sheet_path).convert("L")
    for grey_levels, shrink in [(None, 1.0), (ga.REDUCED_GREY_LEVELS, 1.0),
                                *[(ga.REDUCED_GREY_LEVELS, 0.9 ** k) for k in range(1, 12)]]:
        encoded = [ga._png(sheet.crop(box), scale * shrink, grey_levels) for _, _, box, scale in plan]
        if sum(len(data) for data, _, _ in encoded) <= ga.MAX_TOTAL_IMAGE_BYTES:
            break
    else:
        raise ValueError("the images do not fit the provider request size")
    entries, tiles = [], []
    for (image_id, view, box, _), (data, width, height) in zip(plan, encoded):
        (out / f"{image_id}.png").write_bytes(data)
        entries.append({"image_id": image_id, "file": f"{image_id}.png", "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data), "width": width, "height": height, "view": view,
                        "crop_box_px": list(box)})
        tiles.append({"image_id": image_id, "view": view, "sheet": Path(sheet_path).name,
                      "crop_box_px": list(box), "width": width, "height": height})
    if callable(context):
        context = context({entry["image_id"]: (entry["width"], entry["height"]) for entry in entries})
    write_json(out / "request.json", {
        "schema_version": REQUEST_SCHEMA, "purpose": PURPOSE,
        "source_sha256": hashlib.sha256(Path(sheet_path).read_bytes()).hexdigest(),
        "engineering_approved": False, "context": context, "images": entries})
    write_json(out / "sources.json", {"tiles": tiles})


def prepare_scale(result: dict, sheet_path: Path, out: Path, previous_reason: str | None = None) -> bool:
    """The request that reads the frame scale: the profile and the plans in high-resolution parts.

    A request sent again after a refused reading says why the reading was refused, so the model
    looks again for what was missing (for example the drawn mark where the spacing changes).
    """
    from . import ga_commercial as ga
    views = chosen_views(result)
    wanted = [views[kind] for kind in ("profile", "deck_plan", "tank_top_plan") if kind in views]
    if not wanted:
        return False
    sheet_size = Image.open(sheet_path).size
    plan = []
    for view in wanted:
        left, top, right, bottom = _pad(view["box_px"], sheet_size)
        limit = MAX_IMAGES // len(wanted)  # the images of a request are shared equally by the views
        best = (1, ga._fit_scale(right - left, bottom - top))
        for columns in range(2, limit + 1):
            width = (right - left) / columns * (1 + ga.TILE_OVERLAP)
            scale = ga._fit_scale(width, bottom - top) * ga.SCALE_MARGIN
            if scale > best[1] * 1.05:
                best = (columns, scale)
        columns, scale = best
        for part, box in enumerate(ga.tile_boxes(right - left, bottom - top, columns, 1)):
            plan.append((f"{view['view_id']}p{part + 1}", f"{view['kind']}:{view['view_id']}:part{part + 1}",
                         (left + box[0], top + box[1], left + box[2], top + box[3]), scale))
    context = {"want": ["scale"]}
    if previous_reason:
        context["previous_attempt"] = (f"The previous reading of this frame scale was refused: {previous_reason}. "
                                       "Look again at the whole scale, also for every drawn mark where the frame "
                                       "spacing changes (an arrow end, a tick or a dimension line end).")
    _write_request(plan, sheet_path, out, context)
    return True


PROFILE_PLACES = ("hull_aft_end", "hull_fore_end", "base_line", "upper_deck_at_side")
PLAN_PLACES = ("centre_line", "shell_side_a", "shell_side_b")


def missing_places(work: dict) -> list[str]:
    """Named places and perpendicular marks that the scale request did not point.

    The first extents request names them, so the model points what the measurements still need
    (development round u3: F.P. or a shell side left out, so LBP or breadth was not measured).
    """
    raw = work.get("raw") or {}
    kinds = work["kinds"]
    named = {view: set(places) for view, places in raw.get("points", {}).items()}
    profile = [view for view, kind in kinds.items() if kind == "profile"]
    plans = [view for view, kind in kinds.items() if kind in PLAN_KINDS]
    missing = []
    if profile:
        missing += [name for name in PROFILE_PLACES if not any(name in named.get(v, ()) for v in profile)]
    if plans and not any(set(PLAN_PLACES) <= named.get(v, set()) for v in plans):
        missing += [name for name in PLAN_PLACES if not any(name in named.get(v, ()) for v in plans)]
    # The LBP needs A.P. and F.P. on the profile's frame scale, so they count there only.
    marks = {name for view in profile for name in raw.get("marks", {}).get(view, {})}
    if profile:
        missing += [label for name, label in (("ap", "A.P."), ("fp", "F.P.")) if name not in marks]
    return missing


def prepare_extents(result: dict, sheet_path: Path, out: Path, missing: list[str] = (),
                    only_ids: set[str] | None = None,
                    exclude: dict[str, list[dict]] | None = None) -> list[Path]:
    """The requests that box the drawn boundary of each read space: one image per whole view.

    The spaces go out in requests of ``EXTENT_SPACES_PER_REQUEST`` (at most
    ``MAX_EXTENT_REQUESTS``), holds and tanks first; only the first request also asks for the
    named places. ``exclude`` gives, per space id, the spaces whose labels its box must not hold
    (a redrawn box). Returns the request directories (``out``, ``out-2``, ...); empty when
    nothing can be asked.
    """
    from . import ga_commercial as ga
    views = chosen_views(result)
    if not views:
        return []
    sheet_size = Image.open(sheet_path).size
    plan, boxes = [], {}
    for view in views.values():
        box = _pad(view["box_px"], sheet_size)
        scale = ga._fit_scale(box[2] - box[0], box[3] - box[1])
        boxes[view["view_id"]] = (box, scale)
        plan.append((view["view_id"], f"{view['kind']}:{view['view_id']}", box, scale))
    profile = views.get("profile")
    spaces = []
    # Several labels read from one crop of the fine pass share its region; the place of each
    # label is then not known, so its boundary cannot be asked for.
    shared: dict[tuple, int] = {}
    for space in result["spaces"]:
        key = tuple(space["source_record"].get("regions", [{}])[0].get("box_px") or ())
        shared[key] = shared.get(key, 0) + 1
    for space in result["spaces"]:
        if space["status"] != "read" or (only_ids is not None and space["id"] not in only_ids):
            continue
        in_shared_crop = shared[tuple(space["source_record"]["regions"][0]["box_px"] or ())] > 1
        entry = {"space_id": space["id"], "kind": space["kind"], "label": space["label"][:64]}
        if space["view_id"] in boxes and in_shared_crop:
            # Several labels were read from one crop of the fine pass: the place of this label
            # in it is not known. The crop goes as "near" with the label text (round u8: 457
            # read spaces, 48 of them fuel tanks, were never asked for).
            entry.update(image_id=space["view_id"], at=None,
                         near=tuple(space["source_record"]["regions"][0]["box_px"]))
        elif in_shared_crop:
            continue
        elif space["view_id"] in boxes:
            region = space["source_record"]["regions"][0]["box_px"]
            # The label centre in sheet pixels; it is put in image pixels once the image size is known.
            entry.update(image_id=space["view_id"],
                         at=((region[0] + region[2]) / 2, (region[1] + region[3]) / 2))
            if exclude and space["id"] in exclude:
                entry["exclude"] = [{"label": other["label"][:64], "at": _label_centre(other)}
                                    for other in exclude[space["id"]]]
        elif space["kind"] == "accommodation_deck" and profile:
            entry.update(image_id=profile["view_id"], at=None)
        else:
            continue
        spaces.append(entry)
    if not spaces:
        return []
    order = {kind: index for index, kind in enumerate(EXTENT_PRIORITY)}
    # Stable: within a kind, labels with a known place first, then reading order.
    spaces.sort(key=lambda entry: order.get(entry["kind"], len(order)))  # stable: reading order within a kind
    # Labels with a known place and labels from a shared crop ("near") go in separate requests,
    # the known ones first: mixed in one request, the model marked most boxes "uncertain"
    # (round u9n: outline boxes fell from 23 of 52 to 10 of 77 on one ship).
    known = [entry for entry in spaces if "near" not in entry]
    near = [entry for entry in spaces if "near" in entry]
    chunks = ([known[i:i + EXTENT_SPACES_PER_REQUEST] for i in range(0, len(known), EXTENT_SPACES_PER_REQUEST)]
              + [near[i:i + EXTENT_SPACES_PER_REQUEST] for i in range(0, len(near), EXTENT_SPACES_PER_REQUEST)])
    chunks = chunks[:MAX_EXTENT_REQUESTS]
    directories = []
    for index, chunk in enumerate(chunks):
        want = ["extents", "points"] if index == 0 else ["extents"]
        note = None
        if index == 0 and missing:
            note = {"places": list(missing),
                    "note": "These were not pointed yet; point each one that is drawn. Named places go in "
                            "points; the perpendicular marks go in ticks, at the frame scale."}

        def context(sizes: dict, chunk=chunk, want=want, note=note) -> dict:
            placed = []
            for entry in chunk:
                if entry["at"] is not None:
                    (left, top, right, bottom), _ = boxes[entry["image_id"]]
                    width, height = sizes[entry["image_id"]]

                    def in_image(point, left=left, top=top, right=right, bottom=bottom, width=width, height=height):
                        return [round((point[0] - left) * width / (right - left)),
                                round((point[1] - top) * height / (bottom - top))]

                    entry = {**entry, "at": in_image(entry["at"])}
                    if "exclude" in entry:
                        entry["exclude"] = [{**other, "at": in_image(other["at"])} for other in entry["exclude"]]
                if entry.get("near") is not None:
                    (left, top, right, bottom), _ = boxes[entry["image_id"]]
                    width, height = sizes[entry["image_id"]]
                    near = entry["near"]
                    entry = {**entry, "near": [round((near[0] - left) * width / (right - left)),
                                               round((near[1] - top) * height / (bottom - top)),
                                               round((near[2] - left) * width / (right - left)),
                                               round((near[3] - top) * height / (bottom - top))]}
                placed.append(entry)
            context = {"want": want, "spaces": placed}
            if note:
                context["missing"] = note
            return context

        directory = out if index == 0 else out.with_name(f"{out.name}-{index + 1}")
        _write_request(plan, sheet_path, directory, context)
        directories.append(directory)
    return directories


# ------------------------------------------------------------------ interpretation

def _tiles(request_dir: Path) -> dict[str, dict]:
    return {t["image_id"]: t for t in json.loads((Path(request_dir) / "sources.json").read_text())["tiles"]}


def _to_sheet(tile: dict, x: float, y: float) -> tuple[float, float]:
    left, top, right, bottom = tile["crop_box_px"]
    return left + x * (right - left) / tile["width"], top + y * (bottom - top) / tile["height"]


def _view_id(tile: dict) -> str:
    return tile["view"].split(":")[1]


def _unknown(reason: str) -> dict:
    return {"value": None, "status": "unknown", "reason": reason, "source_record": source_record.unknown(reason)}


def _point_region(sheet: str, page_px, view: str | None, *points) -> dict:
    """A region that holds the given sheet points (with a little room), for hover-to-source."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return source_record.region(sheet, view=view, page_px=page_px,
                                box_px=[min(xs) - 12, min(ys) - 12, max(xs) + 12, max(ys) + 12])


def read_scale(result: dict, reading: dict, request_dir: Path, earlier: dict | None = None) -> dict:
    """The frame table, the axis of every view and the measured principal dimensions.

    Sets ``result["frames"]`` and ``result["measured"]`` and returns the working data
    (axes and named points per view) for ``read_extents``. ``earlier`` is the working data of
    an earlier scale request of the same ship: its marks are read together with this reply's.
    """
    sheet = result["sources"]["ga"]["file"]
    page_px = result["sources"]["ga"]["size_px"]
    kinds = {v["view_id"]: v["kind"] for v in result.get("views", [])}
    reply = (reading.get("reply") or {}).get(PURPOSE)
    work = {"axes": {}, "points": {}, "table": None, "sheet": sheet, "page_px": page_px, "kinds": kinds}
    before = (earlier or {}).get("raw")
    if reply is None and before:
        work["raw"] = before
        return _measure(result, work)
    if reply is None:
        reason = reading.get("stop_reason") or "the model gave no valid reply for the frame scale"
        result["frames"] = {"status": "unknown", "spacings": [], "reason": reason,
                            "source_record": source_record.unknown(reason)}
        result["measured"] = {field: _unknown(reason) for field in MEASURED_FIELDS}
        return work
    tiles = _tiles(request_dir)
    ticks: dict[str, list] = {}
    marks: dict[str, dict] = {}
    spacing_labels: dict[str, list] = {}
    cuts: dict[str, list] = {}
    points: dict[str, dict] = {}
    sigma_px = 0.0
    for tile in tiles.values():
        sigma_px = max(sigma_px, POINT_SIGMA_IMAGE_PX * (tile["crop_box_px"][2] - tile["crop_box_px"][0]) / tile["width"])
    for tick in reply["ticks"]:
        view = _view_id(tiles[tick["image_id"]])
        x, y = _to_sheet(tiles[tick["image_id"]], tick["x"], tick["y"])
        parsed = parse_tick(tick["label"])
        if parsed is None:
            result["checks"].append({"code": "scale_mark_not_understood", "status": "dropped", "label": tick["label"][:16]})
        elif parsed[0] == "frame":
            ticks.setdefault(view, []).append((parsed[1], x, y))
        else:
            marks.setdefault(view, {}).setdefault(parsed[0], []).append((x, y))
    for label in reply["spacing_labels"]:
        view = _view_id(tiles[label["image_id"]])
        x, _ = _to_sheet(tiles[label["image_id"]], label["x"], label["y"])
        mm = parse_spacing_mm(label["printed"])
        if mm is None:
            result["checks"].append({"code": "frame_spacing_not_understood", "status": "dropped",
                                     "label": label["printed"][:32]})
        else:
            spacing_labels.setdefault(view, []).append((mm, x))
    for cut in reply["spacing_boundaries"]:
        view = _view_id(tiles[cut["image_id"]])
        cuts.setdefault(view, []).append(_to_sheet(tiles[cut["image_id"]], cut["x"], cut["y"])[0])
    for point in reply["points"]:
        view = _view_id(tiles[point["image_id"]])
        points.setdefault(view, {}).setdefault(point["name"], []).append(
            _to_sheet(tiles[point["image_id"]], point["x"], point["y"]))
    if before:
        for view, found in before["ticks"].items():
            ticks.setdefault(view, []).extend(found)
        for view, named in before["marks"].items():
            for name, places in named.items():
                marks.setdefault(view, {}).setdefault(name, []).extend(places)
        for view, found in before["spacing_labels"].items():
            spacing_labels.setdefault(view, []).extend(found)
        for view, found in before["cuts"].items():
            cuts.setdefault(view, []).extend(found)
        # A named place keeps its first pointing (two pointings of a hull end differ by more
        # than two pointings of a printed mark).
        for view, named in before["points"].items():
            points.setdefault(view, {}).update(named)
        sigma_px = max(sigma_px, before["sigma_px"])
    work["raw"] = {"ticks": ticks, "marks": marks, "spacing_labels": spacing_labels, "cuts": cuts,
                   "points": points, "sigma_px": sigma_px}
    return _measure(result, work)


# Checks that ``_measure`` writes; it runs again when the extents request adds named places.
MEASURE_CHECKS = ("frame_scale_not_fitted", "ap_mark_not_at_frame_0", "deck_point_not_amidships",
                  "measured_value_implausible", "measured_lengths_disagree", "measured_breadth_disagrees",
                  "measured_depth_disagrees")
MEASURED_FIELDS = ("lbp_m", "loa_m", "breadth_m", "depth_m")


def _measure(result: dict, work: dict) -> dict:
    """The frame table, the axes and the principal dimensions from the marks collected in ``work``."""
    from .ga_commercial import PLAUSIBLE, RECORD_VIEWS
    fields = MEASURED_FIELDS
    sheet, page_px, kinds = work["sheet"], work["page_px"], work["kinds"]
    raw = work["raw"]
    ticks, marks, spacing_labels, cuts, points = (raw[key] for key in ("ticks", "marks", "spacing_labels",
                                                                       "cuts", "points"))
    sigma_px = raw["sigma_px"]
    result["checks"] = [c for c in result["checks"] if c.get("code") not in MEASURE_CHECKS]
    work.update(axes={}, points={}, table=None)

    def abstain(reason: str) -> dict:
        result["frames"] = {"status": "unknown", "spacings": [], "reason": reason,
                            "source_record": source_record.unknown(reason)}
        result["measured"] = {field: _unknown(reason) for field in fields}
        return work

    def one(places: list | None):
        """One place from marks of the same thing on overlapping images; None when they differ."""
        if not places:
            return None
        xs, ys = [p[0] for p in places], [p[1] for p in places]
        if max(xs) - min(xs) > SAME_MARK_PX or max(ys) - min(ys) > SAME_MARK_PX:
            return None
        return float(np.mean(xs)), float(np.mean(ys))

    work["points"] = {view: {name: place for name, places in named.items() if (place := one(places))}
                      for view, named in points.items()}
    # The frame table: from the profile when it prints the spacings, else from a plan.
    order = sorted(spacing_labels, key=lambda view: kinds.get(view) != "profile")
    table, reason, table_view = None, "no frame spacing is printed", None
    for view in order:
        table, reason = spacing_table([(f, x) for f, x, _ in ticks.get(view, [])], spacing_labels[view],
                                      cuts.get(view, []))
        if table:
            table_view = view
            break
    if table is None:
        return abstain(reason)
    for view, found in ticks.items():
        axis, why = fit_axis([(f, x) for f, x, _ in found], table)
        if axis:
            work["axes"][view] = axis
        else:
            result["checks"].append({"code": "frame_scale_not_fitted", "status": "check", "view": view, "reason": why})
    primary = next((view for view in [table_view, *work["axes"]] if view in work["axes"]), None)
    if primary is None:
        return abstain("the frame numbers do not fit the printed spacings")
    axis = work["axes"][primary]
    work["table"] = table
    # A plan without its own frame numbers: the scale of the primary view, when both views draw
    # the hull equally long (one sheet, one scale); its origin comes from the hull's aft end.
    primary_ends = work["points"].get(primary, {})
    for view, named in work["points"].items():
        if view in work["axes"] or not {"hull_aft_end", "hull_fore_end"} <= named.keys():
            continue
        if not {"hull_aft_end", "hull_fore_end"} <= primary_ends.keys():
            continue
        own = named["hull_fore_end"][0] - named["hull_aft_end"][0]
        reference = primary_ends["hull_fore_end"][0] - primary_ends["hull_aft_end"][0]
        if reference and abs(own / reference - 1) <= SAME_SCALE_TOLERANCE:
            aft_m = axis.x_m(primary_ends["hull_aft_end"][0])
            work["axes"][view] = Axis(named["hull_aft_end"][0] - axis.px_per_m * aft_m, axis.px_per_m, axis.rms_px,
                                      0, 0, "scale of the frame-scale view; hull ends matched")
    # The table reaches from the aft end to the fore end of the hull (and holds frame 0).
    ends = [table.frame_at(axis.x_m(primary_ends[name][0])) for name in ("hull_aft_end", "hull_fore_end")
            if name in primary_ends]
    # (A hull end a little past a frame does not add a frame.)
    table.spans[0]["from_frame"] = min([table.spans[0]["from_frame"], 0, *(math.floor(f + 0.25) for f in ends)])
    table.spans[-1]["to_frame"] = max([table.spans[-1]["to_frame"], *(math.ceil(f - 0.25) for f in ends)])
    tick_xy = [(x, y) for _, x, y in ticks[primary]]
    scale_region = _point_region(sheet, page_px, RECORD_VIEWS.get(kinds.get(primary)), *tick_xy)
    span_px = max(x for x, _ in tick_xy) - min(x for x, _ in tick_xy)
    result["frames"] = {
        "status": "read", "spacings": table.spans, "frame_zero": "aft perpendicular",
        "boundaries_status": MEASURED,
        "scale": {"view_id": primary, "px_per_m": round(abs(axis.px_per_m), 4),
                  "direction": "bow_right" if axis.px_per_m > 0 else "bow_left",
                  "ticks_used": axis.ticks_used, "ticks_read": axis.ticks_read, "rms_px": round(axis.rms_px, 2)},
        "source_record": source_record.validate(source_record.read([scale_region]))}

    def measured(pixels: float, view_axis: Axis, how: str, regions: list[dict]) -> dict:
        value = view_axis.length_m(pixels)
        # Two pointed places and the fit of the scale itself.
        sigma = math.hypot(sigma_px, view_axis.rms_px)
        uncertainty = 2 * sigma / abs(view_axis.px_per_m) + value * axis.rms_px / max(span_px, 1.0)
        return {"value": round(value, 2), "status": MEASURED, "uncertainty_m": round(uncertainty, 2),
                "method": how, "scale_basis": view_axis.basis,
                "note": "measured on the drawing with its printed frame scale; not a printed particular",
                "source_record": source_record.validate(source_record.read([*regions, scale_region]))}

    out = {}
    profile = next((view for view in work["axes"] if kinds.get(view) == "profile"), None)
    named = work["points"].get(profile, {}) if profile else {}
    record_view = "profile"
    ap, fp = one(marks.get(profile, {}).get("ap")), one(marks.get(profile, {}).get("fp"))
    if profile is None:
        for field in ("lbp_m", "loa_m", "depth_m"):
            out[field] = _unknown("the profile has no fitted frame scale")
    else:
        profile_axis = work["axes"][profile]
        if fp is None:
            out["lbp_m"] = _unknown("the forward perpendicular (F.P.) is not marked on the frame scale")
        else:
            # Frame 0 is the AP by the table; a printed A.P. mark must agree with it.
            ap_px = profile_axis.offset
            frame_px = abs(profile_axis.px_per_m) * table.spacing_m(0)
            if ap is not None and abs(ap[0] - ap_px) > max(SAME_MARK_PX, AP_MARK_FRAMES * frame_px):
                result["checks"].append({"code": "ap_mark_not_at_frame_0", "status": "check"})
                out["lbp_m"] = _unknown("the A.P. mark does not lie at frame 0 of the frame scale")
            else:
                out["lbp_m"] = measured(fp[0] - ap_px, profile_axis, "frame 0 (A.P.) to the F.P. mark on the frame scale",
                                        [_point_region(sheet, page_px, record_view, fp, (ap_px, fp[1]))])
        if {"hull_aft_end", "hull_fore_end"} <= named.keys():
            aft, fore = named["hull_aft_end"], named["hull_fore_end"]
            out["loa_m"] = measured(fore[0] - aft[0], profile_axis, "aft end to fore end of the hull in the profile",
                                    [_point_region(sheet, page_px, record_view, aft),
                                     _point_region(sheet, page_px, record_view, fore)])
        else:
            out["loa_m"] = _unknown("the profile does not show both ends of the hull")
        hull = sorted(named[name][0] for name in ("hull_aft_end", "hull_fore_end") if name in named)
        if len(hull) < 2:  # without both hull ends, the ends of the frame scale
            hull = [min(x for _, x, _ in ticks[profile]), max(x for _, x, _ in ticks[profile])]
        if {"base_line", "upper_deck_at_side"} <= named.keys() and not (
                MIDSHIP_SHARE[0] <= (named["upper_deck_at_side"][0] - hull[0]) / (hull[1] - hull[0]) <= MIDSHIP_SHARE[1]):
            # A deck line pointed near an end of the ship can be the poop or forecastle deck. It
            # is dropped, so that the extents request can point the deck line again.
            raw["points"][profile].pop("upper_deck_at_side")
            out["depth_m"] = _unknown("the upper deck line was not pointed amidships")
            result["checks"].append({"code": "deck_point_not_amidships", "status": "check"})
        elif {"base_line", "upper_deck_at_side"} <= named.keys():
            base, deck = named["base_line"], named["upper_deck_at_side"]
            out["depth_m"] = measured(base[1] - deck[1], profile_axis,
                                      "base line to the upper deck at side amidships in the profile",
                                      [_point_region(sheet, page_px, record_view, base),
                                       _point_region(sheet, page_px, record_view, deck)])
        else:
            out["depth_m"] = _unknown("the base line or the upper deck at side was not found in the profile")
    out["breadth_m"] = _unknown("no plan view with a scale shows both sides of the shell")
    for view, view_axis in work["axes"].items():
        sides = work["points"].get(view, {})
        if kinds.get(view) in PLAN_KINDS and {"shell_side_a", "shell_side_b"} <= sides.keys():
            a, b = sides["shell_side_a"], sides["shell_side_b"]
            out["breadth_m"] = measured(a[1] - b[1], view_axis, "shell side to shell side amidships in the plan",
                                        [_point_region(sheet, page_px, "plan", a),
                                         _point_region(sheet, page_px, "plan", b)])
            break

    def refuse(names, reason, code):
        for name in names:
            out[name] = _unknown(reason)
        result["checks"].append({"code": code, "status": "check"})

    def value(name):
        return out[name]["value"]

    for name in fields:
        if value(name) is not None and not PLAUSIBLE[name][0] <= value(name) <= PLAUSIBLE[name][1]:
            refuse([name], f"the measured {name} is not plausible", "measured_value_implausible")
    if value("lbp_m") and value("loa_m") and not LBP_OVER_LOA[0] <= value("lbp_m") / value("loa_m") <= LBP_OVER_LOA[1]:
        refuse(["lbp_m", "loa_m"], "measured LBP and LOA do not fit each other", "measured_lengths_disagree")
    length = value("lbp_m") or value("loa_m")
    if length and value("breadth_m") and not (LENGTH_OVER_BREADTH[0] <= length / value("breadth_m")
                                              <= LENGTH_OVER_BREADTH[1]):
        refuse(["breadth_m"], "the measured breadth does not fit the measured length", "measured_breadth_disagrees")
    if value("breadth_m") and value("depth_m") and not (BREADTH_OVER_DEPTH[0] <= value("breadth_m") / value("depth_m")
                                                        <= BREADTH_OVER_DEPTH[1]):
        refuse(["depth_m"], "the measured depth does not fit the measured breadth", "measured_depth_disagrees")
    result["measured"] = out
    return work


SIDE_WORDS = [(r"\(?\bP\s?[&/]\s?S\b\)?|\(P,\s?S\)", "both"), (r"\(P\)|\bPORT\b", "port"),
              (r"\(S\)|\bSTBD\b|\bSTARBOARD\b", "starboard"), (r"\(C\)|\bCENT(?:RE|ER)\b", "centre")]


def side_of_label(label: str) -> str | None:
    """'both', 'port', 'starboard' or 'centre' when the printed label says the side."""
    text = label.upper()
    for pattern, side in SIDE_WORDS:
        if re.search(pattern, text):
            return side
    return None


def read_extents(result: dict, work: dict, reading: dict, request_dir: Path) -> dict:
    """Give each boxed space its ``extent`` (frames, metres and status per axis); return statistics."""
    stats = {"asked": 0, "boxed": 0, "with_extent": 0}
    reply = (reading.get("reply") or {}).get(PURPOSE)
    marks = [] if reply is None else [t for t in reply["ticks"] if (parse_tick(t["label"]) or ("frame",))[0] != "frame"]
    if reply is not None and work.get("table") is not None and (reply["points"] or marks):
        # Named places that the scale request left out (a plan it did not look at) come from
        # the whole-view images; a place already pointed at high resolution is kept.
        tiles = _tiles(request_dir)
        raw, added = work["raw"], 0
        for point in reply["points"]:
            tile = tiles[point["image_id"]]
            named = raw["points"].setdefault(_view_id(tile), {})
            if point["name"] not in named:
                named[point["name"]] = [_to_sheet(tile, point["x"], point["y"])]
                raw["sigma_px"] = max(raw["sigma_px"], POINT_SIGMA_IMAGE_PX
                                      * (tile["crop_box_px"][2] - tile["crop_box_px"][0]) / tile["width"])
                added += 1
        # A.P. and F.P. marks that the scale request left out (needed for the LBP).
        for tick in marks:
            name = parse_tick(tick["label"])[0]
            tile = tiles[tick["image_id"]]
            view_marks = raw["marks"].setdefault(_view_id(tile), {})
            if name in view_marks:
                continue  # a mark already pointed in this view is kept
            view_marks[name] = [_to_sheet(tile, tick["x"], tick["y"])]
            added += 1
        if added:
            stats["points_added"] = added
            _measure(result, work)
    table = work.get("table")
    if reply is None or table is None:
        stats["reason"] = ("the frame scale was not established" if table is None
                           else reading.get("stop_reason") or "the model gave no valid reply for the extents")
        return stats
    tiles = _tiles(request_dir)
    request = json.loads((Path(request_dir) / "request.json").read_text())
    stats["asked"] = len(request["context"]["spaces"])
    asked = {s["space_id"]: s for s in request["context"]["spaces"]}
    spaces = {s["id"]: s for s in result["spaces"]}
    kinds = work["kinds"]
    for entry in reply["extents"]:
        space = spaces.get(entry["space_id"])
        tile = tiles[entry["image_id"]]
        view = _view_id(tile)
        if space is None or entry["space_id"] not in asked or asked[entry["space_id"]]["image_id"] != view:
            result["checks"].append({"code": "extent_of_unknown_space", "status": "dropped",
                                     "label": entry["space_id"][:64]})
            continue
        stats["boxed"] += 1
        axis = work["axes"].get(view)
        if axis is None or "extent" in space:
            continue
        left, top = _to_sheet(tile, entry["box"][0], entry["box"][1])
        right, bottom = _to_sheet(tile, entry["box"][2], entry["box"][3])
        status = MEASURED if entry["basis"] == "outline" else "guessed"
        ends = sorted((axis.x_m(left), axis.x_m(right)))
        frames = [int(round(table.frame_at(x))) for x in ends]
        if frames[0] == frames[1]:
            continue
        extent = {"frames": frames, "x_m": [round(table.x_m(f), 3) for f in frames],
                  "x_measured_m": [round(x, 2) for x in ends], "status": {"x": status},
                  "view_id": view, "outline_box_px": [round(v, 1) for v in (left, top, right, bottom)],
                  "basis": entry["basis"],
                  "method": "ends of the drawn boundary measured on the frame scale, given to the nearest frame"}
        named = work["points"].get(view, {})
        if kinds.get(view) == "profile" and "base_line" in named:
            base = named["base_line"][1]
            low, high = (base - bottom) / abs(axis.px_per_m), (base - top) / abs(axis.px_per_m)
            extent["z_m"] = [round(max(low, 0.0), 2), round(high, 2)]
            extent["status"]["z"] = status
        elif kinds.get(view) in PLAN_KINDS and "centre_line" in named:
            centre = named["centre_line"][1]
            # Seen from above with the bow to the right, port is up the sheet; bow left, down.
            sign = 1.0 if axis.px_per_m > 0 else -1.0
            sides = sorted((sign * (centre - top) / abs(axis.px_per_m), sign * (centre - bottom) / abs(axis.px_per_m)))
            extent["y_m"] = [round(sides[0], 2), round(sides[1], 2)]
            extent["status"]["y"] = status
        region = (space["source_record"].get("regions") or [{}])[0].get("box_px")
        if region and sum((s["source_record"].get("regions") or [{}])[0].get("box_px") == region
                          for s in result["spaces"]) > 1:
            region = None  # read from a crop shared with other labels: its own place is not known
        if region:
            # Where the label of this space is printed, in the metres of the extent (overlap rules).
            cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
            if "z_m" in extent:
                extent["label_at_m"] = [round(axis.x_m(cx), 2), round((base - cy) / abs(axis.px_per_m), 2)]
            elif "y_m" in extent:
                extent["label_at_m"] = [round(axis.x_m(cx), 2), round(sign * (centre - cy) / abs(axis.px_per_m), 2)]
        side = side_of_label(space["label"])
        if side is None and "y_m" in extent:
            low, high = extent["y_m"]
            side = ("port" if low >= -CENTRE_TOLERANCE_M else "starboard" if high <= CENTRE_TOLERANCE_M else "centre")
        if side:
            extent["side"] = side
        if entry.get("outline"):
            def to_metres(px, py, axis=axis, named=named, view=view):
                if "z_m" in extent:
                    return [round(axis.x_m(px), 2), round((named["base_line"][1] - py) / abs(axis.px_per_m), 2)]
                return [round(axis.x_m(px), 2), round(sign * (named["centre_line"][1] - py) / abs(axis.px_per_m), 2)]

            points_px = [_to_sheet(tile, x, y) for x, y in entry["outline"]]
            reason = _outline_problem(points_px, extent["outline_box_px"], space, result["spaces"], view)
            if reason is None and ("z_m" in extent or "y_m" in extent):
                extent["outline"] = {"plane": "xz" if "z_m" in extent else "xy",
                                     "points_m": [to_metres(x, y) for x, y in points_px],
                                     "points_px": [[round(x, 1), round(y, 1)] for x, y in points_px],
                                     "status": OUTLINE_STATUS}
                stats["outlines"] = stats.get("outlines", 0) + 1
            else:
                result["checks"].append({"code": "outline_dropped", "status": "dropped", "label": space["label"][:64],
                                         "reason": reason or "the view has no base line or centre line"})
        space["extent"] = extent
        stats["with_extent"] += 1
    return stats


# An outline is a trace of the drawn boundary by the model: its points are placed with the
# frame scale but the trace itself is not measured, so it has its own status and changes no
# axis status (PM decision, 2026-11-12).
OUTLINE_STATUS = "traced"
# Points of an outline may lie this far outside its box (pixels of the sheet) for the line width.
OUTLINE_BOX_TOLERANCE_PX = 3.0


def _inside_polygon(point, polygon) -> bool:
    """Whether ``point`` lies inside ``polygon`` (even-odd rule)."""
    x, y = point
    inside = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _outline_problem(points, box, space: dict, spaces: list[dict], view: str) -> str | None:
    """Why an outline is not kept, or None: it must lie inside its box, hold the space's own
    label and hold no other label of the view (a label of the same family or a note of the same
    kind is the same space, as for the boxes)."""
    left, top, right, bottom = box
    tolerance = OUTLINE_BOX_TOLERANCE_PX
    if not all(left - tolerance <= x <= right + tolerance and top - tolerance <= y <= bottom + tolerance
               for x, y in points):
        return "the outline leaves its box"
    own = _label_centre(space)
    if own is None or not _inside_polygon(own, points):
        return "the outline does not hold the space's own label"
    for other in spaces:
        if other is space or other["status"] != "read" or other.get("view_id") != view:
            continue
        if label_family(other["label"]) == label_family(space["label"]):
            continue
        if other["kind"] == space["kind"] and other["kind"] not in ("other_space", "other_tank"):
            continue
        centre = _label_centre(other)
        if centre is not None and _inside_polygon(centre, points):
            return f"the outline holds the label of '{other['label'][:40]}'"
    return None


# Overlap rules: a box that takes in a labelled neighbour (lane W, round u4r: holds lost 80-92 % of
# their volume to tank boxes drawn over them).
STRIP_COVER = 0.8  # a neighbour that spans this share of a box along one axis is a strip of it
EDGE_TOLERANCE_M = 0.5


def _span(extent: dict) -> tuple[str, list[float], list[float]] | None:
    """The other axis name and the x and other-axis ranges of an extent, or None."""
    other = "z_m" if "z_m" in extent else "y_m" if "y_m" in extent else None
    if other is None:
        return None
    return other, list(extent.get("x_measured_m") or extent["x_m"]), list(extent[other])


def _holds(extent: dict, point) -> bool:
    span = _span(extent)
    if span is None or point is None:
        return False
    _, xs, vs = span
    return xs[0] < point[0] < xs[1] and vs[0] < point[1] < vs[1]


def _cover(outer: list[float], inner: list[float]) -> float:
    """The share of ``outer`` that ``inner`` covers."""
    length = outer[1] - outer[0]
    return max(0.0, min(outer[1], inner[1]) - max(outer[0], inner[0])) / length if length > 0 else 0.0


def _label_centre(space: dict) -> tuple[float, float] | None:
    """The centre of a space's printed label in sheet pixels, or None."""
    box = (space["source_record"].get("regions") or [{}])[0].get("box_px")
    return None if not box else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def covered_labels(result: dict) -> dict[str, list[dict]]:
    """For each measured box, the spaces without a box of their own whose label it holds.

    The overlap rules between two boxes cannot see a neighbour that was not boxed (a store above
    a peak tank, a residue tank beside a slop tank; review round 4). A box that holds such a
    label takes in that space. Not counted: a label of the same family (the same space read
    twice), and in a profile a tank printed for the sides (a wing or topside tank seen in
    projection).
    """
    kinds = {view["view_id"]: view["kind"] for view in result.get("views", [])}
    found: dict[str, list[dict]] = {}
    for big in result["spaces"]:
        extent = big.get("extent")
        if (not extent or extent.get("projection_of") or "outline_box_px" not in extent
                or "guessed" in extent["status"].values()):
            continue
        left, top, right, bottom = extent["outline_box_px"]
        for small in result["spaces"]:
            if (small is big or "extent" in small or small["status"] != "read"
                    or small.get("view_id") != extent["view_id"]):
                continue
            centre = _label_centre(small)
            if centre is None or not (left < centre[0] < right and top < centre[1] < bottom):
                continue
            if label_family(small["label"]) == label_family(big["label"]):
                continue
            if small["kind"] == big["kind"] and small["kind"] not in ("other_space", "other_tank"):
                continue  # a note on the same hatch or hold ("STEEL HATCH COVER"; lane W, round u6r7)
            if kinds.get(extent["view_id"]) == "profile" and side_of_label(small["label"]) in ("both", "port", "starboard"):
                continue
            found.setdefault(big["id"], []).append(small)
    return found


# A short untyped label ("X. T. (P)": two letters) names a small tank or room. A box guessed for
# it on every axis may be at most this many times its label box in each direction (lane W, round
# u6r3: such a label got a guessed box along a whole hold).
SMALL_LABEL_LETTERS = 4
SMALL_LABEL_BOX_FACTOR = 2.0


def _all_guessed(extent: dict) -> bool:
    return bool(extent.get("status")) and set(extent["status"].values()) == {"guessed"}


def withhold_oversized_guesses(result: dict) -> int:
    """Remove the guessed box of a short untyped label that is far larger than its label box."""
    from .ga_commercial import _named_words
    withheld = 0
    for space in result["spaces"]:
        extent = space.get("extent")
        region = (space["source_record"].get("regions") or [{}])[0].get("box_px")
        if (not extent or not region or "outline_box_px" not in extent or not _all_guessed(extent)
                or space["kind"] not in ("other_space", "other_tank")
                or len("".join(_named_words(space["label"]))) > SMALL_LABEL_LETTERS):
            continue
        left, top, right, bottom = extent["outline_box_px"]
        if (right - left > SMALL_LABEL_BOX_FACTOR * (region[2] - region[0])
                or bottom - top > SMALL_LABEL_BOX_FACTOR * (region[3] - region[1])):
            space.pop("extent")
            space["extent_withheld"] = "a guessed box far larger than the short label of a small space"
            result["checks"].append({"code": "extent_withheld", "status": "dropped", "label": space["label"][:64],
                                     "reason": "guessed box larger than its short label allows"})
            withheld += 1
    return withheld


def resolve_overlaps(result: dict) -> dict:
    """Keep each extent off the labelled spaces beside it, per view; return statistics.

    - A box that holds another space's label while that space's box does not hold its own label
      takes in a neighbour. When the neighbour is a strip at one edge of the box (a double-bottom
      tank under a hold, a wing tank beside a cargo tank, a peak at a hold end), the box ends at
      the neighbour's boundary. Otherwise its axes become ``guessed``.
    - Two boxes that hold each other's labels in a profile are a projection (a wing tank drawn
      over a cargo tank): the space that is not cargo is marked ``projection_of`` and gets no
      extent in the arrangement input unless a plan gives its breadth. In a plan, both boxes are
      wrong and their y becomes ``guessed``.
    """
    stats = {"trimmed": 0, "guessed": 0, "projections": 0}
    spaces = [s for s in result["spaces"] if _span(s.get("extent", {})) and s["extent"].get("label_at_m")]
    by_view: dict[str, list[dict]] = {}
    for space in spaces:
        by_view.setdefault(space["extent"]["view_id"], []).append(space)
    cargo = ("cargo_hold", "cargo_tank")
    for members in by_view.values():
        # A tank printed for the sides that overlaps a cargo space in the profile (topside, wing or
        # hopper tanks; round u6: topside tanks over two holds) is a projection, whichever hold
        # its label lies over.
        for tank in members:
            span = _span(tank["extent"])
            if (span[0] != "z_m" or tank["kind"] in cargo
                    or side_of_label(tank["label"]) not in ("both", "port", "starboard")):
                continue
            for hold in members:
                if hold["kind"] not in cargo:
                    continue
                _, hxs, hvs = _span(hold["extent"])
                if (_cover(hxs, span[1]) > 0.2 and _cover(hvs, span[2]) > 0.2
                        and not (span[2][1] <= hvs[0] + EDGE_TOLERANCE_M)):  # not a tank under the hold
                    tank["extent"]["projection_of"] = hold["id"]
                    stats["projections"] += 1
                    break
        def area(space):
            _, xs, vs = _span(space["extent"])
            return (xs[1] - xs[0]) * (vs[1] - vs[0])
        members.sort(key=area, reverse=True)
        for big in members:
            for small in members:
                if small is big or area(small) > area(big):
                    continue
                a, b = big["extent"], small["extent"]
                if label_family(big["label"]) == label_family(small["label"]) and big["kind"] == small["kind"]:
                    continue  # the same space read twice
                a_holds_b, b_holds_a = _holds(a, b["label_at_m"]), _holds(b, a["label_at_m"])
                other, axs, avs = _span(a)
                if a_holds_b and b_holds_a:
                    if other == "z_m":
                        for this, that in ((big, small), (small, big)):
                            if this["kind"] not in cargo and that["kind"] in cargo:
                                this["extent"]["projection_of"] = that["id"]
                                stats["projections"] += 1
                    else:
                        for this in (big, small):
                            this["extent"]["status"]["y"] = "guessed"
                        stats["guessed"] += 2
                        result["checks"].append({"code": "plan_boxes_hold_each_others_labels", "status": "changed",
                                                 "label": f"{big['label'][:30]} / {small['label'][:30]}"})
                    continue
                if not a_holds_b:
                    continue
                _, bxs, bvs = _span(b)
                trimmed = False
                if _span(b)[0] == other and _cover(axs, bxs) >= STRIP_COVER:
                    if bvs[0] <= avs[0] + EDGE_TOLERANCE_M < bvs[1] < avs[1]:
                        a[other][0] = round(bvs[1], 2)  # the neighbour is a strip along the bottom or one side
                        trimmed = True
                    elif avs[0] < bvs[0] < avs[1] - EDGE_TOLERANCE_M <= bvs[1]:
                        a[other][1] = round(bvs[0], 2)  # along the top or the other side
                        trimmed = True
                elif _span(b)[0] == other and _cover(avs, bvs) >= STRIP_COVER and "frames" in b:
                    if bxs[0] <= axs[0] + EDGE_TOLERANCE_M < bxs[1] < axs[1]:
                        a["frames"][0], a["x_m"][0] = b["frames"][1], b["x_m"][1]
                        a["x_measured_m"] = [round(bxs[1], 2), a["x_measured_m"][1]] if "x_measured_m" in a else None
                        trimmed = True
                    elif axs[0] < bxs[0] < axs[1] - EDGE_TOLERANCE_M <= bxs[1]:
                        a["frames"][1], a["x_m"][1] = b["frames"][0], b["x_m"][0]
                        a["x_measured_m"] = [a["x_measured_m"][0], round(bxs[0], 2)] if "x_measured_m" in a else None
                        trimmed = True
                if a.get("x_measured_m") is None:
                    a.pop("x_measured_m", None)
                if trimmed:
                    a.setdefault("trimmed_by", []).append(small["id"])
                    stats["trimmed"] += 1
                elif (other == "z_m" and big["kind"] in cargo and small["kind"] not in cargo
                        and side_of_label(small["label"]) in ("both", "port", "starboard")):
                    # A tank printed for the sides ("(P/S)") inside a cargo space in the profile, and
                    # not a strip at its edge, is a wing, topside or hopper tank seen in projection
                    # (round u6: topside fuel tanks boxed over the holds).
                    b["projection_of"] = big["id"]
                    stats["projections"] += 1
                    continue
                if _holds(a, b["label_at_m"]):
                    for axis in a["status"]:
                        a["status"][axis] = "guessed"
                    a.setdefault("covers", []).append(small["id"])
                    stats["guessed"] += 1
                    result["checks"].append({"code": "extent_covers_a_labelled_neighbour", "status": "changed",
                                             "label": f"{big['label'][:30]} / {small['label'][:30]}"})
    # A box that still holds the label of a space without a box takes in that space: it is not
    # a measured boundary (its axes become guessed).
    spaces = {space["id"]: space for space in result["spaces"]}
    for big_id, neighbours in covered_labels(result).items():
        extent = spaces[big_id]["extent"]
        for axis in extent["status"]:
            extent["status"][axis] = "guessed"
        extent.setdefault("covers", []).extend(small["id"] for small in neighbours)
        stats["guessed"] += 1
        result["checks"].append({"code": "extent_covers_a_labelled_neighbour", "status": "changed",
                                 "label": f"{spaces[big_id]['label'][:30]} / {neighbours[0]['label'][:30]}"})
    # An outline traced inside the first box no longer fits a box the rules changed.
    for space in result["spaces"]:
        extent = space.get("extent") or {}
        changed = (extent.get("trimmed_by") or extent.get("covers") or extent.get("projection_of")
                   or (extent.get("basis") == "outline" and "guessed" in extent.get("status", {}).values()))
        if "outline" in extent and changed:
            extent.pop("outline")
            result["checks"].append({"code": "outline_dropped", "status": "dropped", "label": space["label"][:64],
                                     "reason": "the overlap rules changed its box"})
    return stats


def tops_of_uncertain_cargo(result: dict, kinds: dict) -> list[float]:
    """The tops of cargo holds and tanks boxed in the profile with an "uncertain" boundary."""
    return [space["extent"]["z_m"][1] for space in result["spaces"]
            if space["kind"] in ("cargo_hold", "cargo_tank") and "z_m" in space.get("extent", {})
            and space["extent"].get("basis") == "uncertain"
            and kinds.get(space["extent"]["view_id"]) == "profile"]


def check_depth(result: dict, work: dict) -> None:
    """Check the measured depth against the tops of the spaces below the deck (profile).

    The upper deck is not lower than the top of any hold or tank below it. A measured depth is
    kept only when this check can be made and passes. The top of a hold can be lower than the
    deck (topside tanks above it), so a pointed deck line above the tops is kept and marked "not
    confirmed". A deck line below a top is a contradiction: the depth is then the median top of
    the cargo spaces when they agree (status ``derived_from_space_tops``), else null. A deck line
    with no boxed space to check it against is null. Without a deck line pointed amidships, the
    depth is the median top of the cargo spaces when at least three agree and another kind of
    space, or the lowest deckhouse tier, ends there too.
    """
    kinds = work["kinds"]

    table = work["table"]
    ends = [table.x_m(span_end) for span_end in (table.spans[0]["from_frame"], table.spans[-1]["to_frame"])]
    midship = [ends[0] + share * (ends[1] - ends[0]) for share in MIDSHIP_SHARE]

    def tops_of(wanted, amidships_only=False) -> list[float]:
        tops = []
        for space in result["spaces"]:
            extent = space.get("extent", {})
            if (space["kind"] not in wanted or "z_m" not in extent or extent["basis"] != "outline"
                    or kinds.get(extent["view_id"]) != "profile"):
                continue
            centre = (extent["x_m"][0] + extent["x_m"][1]) / 2
            if amidships_only and not midship[0] <= centre <= midship[1]:
                continue  # a space under the poop or the forecastle ends above the upper deck
            tops.append(extent["z_m"][1])
        return tops

    cargo = tops_of(("cargo_hold", "cargo_tank"))
    others = tops_of([kind for kind in BELOW_DECK_KINDS if kind not in ("cargo_hold", "cargo_tank")], True)
    tiers = [s["extent"]["z_m"][0] for s in result["spaces"]
             if s["kind"] == "accommodation_deck" and "z_m" in s.get("extent", {})]
    depth = result["measured"]["depth_m"]
    own = ("depth_below_a_space_top", "depth_not_confirmed_by_space_tops", "depth_taken_from_cargo_space_tops")
    result["checks"] = [c for c in result["checks"] if c.get("code") not in own]
    seen = {"cargo_space_tops_m": sorted(cargo), "other_space_tops_m": sorted(others),
            "lowest_deckhouse_tier_m": min(tiers, default=None)}
    axis = work["axes"][next(view for view in work["axes"] if kinds.get(view) == "profile")]
    # Two measurements, each two pointed places on the fitted scale.
    one = (2 * POINT_SIGMA_IMAGE_PX + 2 * axis.rms_px) / abs(axis.px_per_m)
    allowed = 2 * max(depth.get("uncertainty_m") or 0.0, one)
    highest = max(cargo + others, default=None)
    pointed = depth["value"]
    reference = float(np.median(cargo)) if cargo else None
    # The cargo spaces agree on one top, nothing below the deck is higher, and there are enough of them.
    tops_agree = (len(cargo) >= MIN_DECK_TOPS and all(abs(top - reference) <= allowed for top in cargo)
                  and highest <= reference + allowed)

    def from_tops(why: str, how: str) -> dict:
        regions = [s["source_record"]["regions"][0] for s in result["spaces"]
                   if s["kind"] in ("cargo_hold", "cargo_tank") and "z_m" in s.get("extent", {})]
        return {"value": round(reference, 2), "status": DERIVED, "uncertainty_m": round(allowed, 2),
                "method": f"median top of {len(cargo)} cargo spaces boxed in the profile, on the frame scale; " + how,
                "scale_basis": axis.basis, "pointed_depth_m": pointed, "reason": why,
                "note": "an estimate from the read spaces, not a measured deck line and not a printed particular",
                "cross_check": {**seen, "pointed_depth_m": pointed, "result": "taken from the tops of the cargo spaces"},
                "source_record": source_record.validate(source_record.read(
                    [*regions[:source_record.MAX_REGIONS - 1], result["frames"]["source_record"]["regions"][0]]))}

    # The cargo spaces are the reference for the deck at side: when enough of them agree on one
    # top and the pointed deck line lies there, a space of another kind boxed above that line is
    # the wrong box (development round u3: wing ballast tanks boxed 3.6 m above the deck), not a
    # wrong deck line. Its height is then a guess and the depth stands.
    cargo_agree = len(cargo) >= MIN_DECK_TOPS and all(abs(top - reference) <= allowed for top in cargo)
    if pointed is not None and cargo_agree and abs(pointed - reference) <= allowed and highest > pointed + allowed:
        above = 0
        for space in result["spaces"]:
            extent = space.get("extent", {})
            if (space["kind"] in BELOW_DECK_KINDS and space["kind"] not in ("cargo_hold", "cargo_tank")
                    and "z_m" in extent and extent["basis"] == "outline" and kinds.get(extent["view_id"]) == "profile"
                    and midship[0] <= (extent["x_m"][0] + extent["x_m"][1]) / 2 <= midship[1]
                    and extent["z_m"][1] > pointed + allowed):
                extent["status"]["z"] = "guessed"
                extent["z_note"] = "boxed above the deck at side that the cargo spaces confirm; height not measured"
                above += 1
        result["checks"].append({"code": "extent_above_the_deck", "status": "changed", "count": above})
        depth["cross_check"] = {**seen, "result": "agrees with the tops of the cargo spaces; spaces of other kinds "
                                                  "boxed above the deck are taken as guesses"}
        return
    if pointed is not None:
        # A depth stays measured only when the check passes: some space below the deck was boxed
        # in the profile and none of them is higher than the deck line.
        if highest is None:
            reason = "the deck line could not be checked: no space below the deck was boxed in the profile"
            unsure = tops_of_uncertain_cargo(result, kinds)
            middle = float(np.median(unsure)) if unsure else None
            if (len(unsure) >= MIN_DECK_TOPS and all(abs(top - middle) <= allowed for top in unsure)
                    and abs(pointed - middle) <= allowed):
                # Boxes the model marked "uncertain" agree with the pointed line: a depth with its
                # own status, never measured or derived, and never used to confirm a box (PM, round
                # u10; the circular-check lesson).
                result["measured"]["depth_m"] = {
                    "value": pointed, "status": UNCONFIRMED, "uncertainty_m": round(allowed, 2),
                    "method": "the pointed deck line at side, agreeing with the tops of cargo spaces boxed "
                              "in the profile with an uncertain boundary",
                    "scale_basis": axis.basis, "pointed_depth_m": pointed, "reason": reason,
                    "note": "not confirmed: no space below the deck has a clear boundary in the profile",
                    "cross_check": {**seen, "uncertain_cargo_tops_m": sorted(unsure),
                                    "result": "agrees with the tops of uncertain cargo boxes"},
                    "source_record": depth["source_record"]}
                result["checks"].append({"code": "depth_unconfirmed_from_uncertain_boxes", "status": "check"})
                return
            result["measured"]["depth_m"] = {**_unknown(reason), "pointed_depth_m": pointed,
                                             "cross_check": {**seen, "result": "not checked"}}
            result["checks"].append({"code": "depth_not_checked", "status": "check"})
        elif pointed < highest - allowed:
            # The deck line or the boxes are wrong. When the cargo spaces agree on one top, that
            # top is the depth (a derived estimate); otherwise there is no depth.
            result["checks"].append({"code": "depth_below_a_space_top", "status": "check"})
            reason = (f"the pointed deck line ({pointed} m) lies below the top of a space boxed under the deck "
                      f"({round(highest, 2)} m)")
            # Another space below the deck ends at the pointed line: the boxes disagree among
            # themselves (development round u4: cargo tanks boxed to the rail above the deck while a
            # ballast tank ends at the deck line), so the cargo tops cannot replace the line.
            confirmed_by_other = any(abs(top - pointed) <= allowed for top in others)
            if confirmed_by_other:
                reason += "; another space below the deck ends at the pointed line, so the boxes disagree"
            # Cargo boxes a rail or bulwark height above the pointed line: the boxes may end on the
            # rail (development round u5) as well as the line may be below the deck; code cannot
            # tell which, so the cargo tops do not replace the line.
            rail_apart = highest - pointed <= RAIL_OR_CAMBER_M
            if rail_apart and not confirmed_by_other:
                reason += "; the boxes end a rail height above it, so which line is the deck at side is not clear"
            if tops_agree and not confirmed_by_other and not rail_apart:
                result["measured"]["depth_m"] = from_tops(reason, "the pointed line lay below them")
                result["checks"].append({"code": "depth_taken_from_cargo_space_tops", "status": "check"})
            else:
                result["measured"]["depth_m"] = {**_unknown(reason), "pointed_depth_m": pointed,
                                                 "cross_check": {**seen, "result": "contradicted"}}
        elif pointed <= highest + allowed:
            depth["cross_check"] = {**seen, "result": "agrees with the top of the spaces below the deck"}
        elif tops_agree and pointed - reference <= RAIL_OR_CAMBER_M:
            # The moulded depth is to the deck AT SIDE, where the cargo spaces end.
            result["measured"]["depth_m"] = from_tops(
                f"the pointed deck line ({pointed} m) lies a rail or camber height above the cargo spaces: "
                "the deck at the centreline or a rail, not the deck at side",
                "the pointed line lay a rail or camber height above them")
            result["checks"].append({"code": "depth_taken_from_cargo_space_tops", "status": "check"})
        else:
            depth["cross_check"] = {**seen, "result": "not confirmed: the deck line lies above the tops of the "
                                                      "boxed spaces (topside tanks, or another deck)"}
            result["checks"].append({"code": "depth_not_confirmed_by_space_tops", "status": "check"})
        return
    support = [top for top in [*others, *tiers] if reference is not None and abs(top - reference) <= allowed]
    if tops_agree and support:
        result["measured"]["depth_m"] = from_tops(
            "no deck line was measured at side amidships (" + depth.get("reason", "") + ")",
            "another space or the lowest deckhouse tier ends at the same height")


# A redrawn box keeps at least this share of the first box's area. A larger cut is more often a
# box that avoids a label printed over the space (a side tank's label over a hold) than a
# boundary found (rounds u6r5 and u6r6: holds and cargo tanks cut to strips of 28-51 %; the
# redrawn boxes that ended at a neighbour kept 65-84 %).
REDRAW_MIN_AREA_SHARE = 0.6


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def redraw_covering_boxes(result: dict, work: dict, sheet_path: Path, out: Path, call, readings: list) -> dict:
    """One more request for the boxes that hold the label of a space without a box (review round 4).

    The request names, per box, the labels it must leave out. A redrawn box is kept only when it
    holds none of them; otherwise the first box stays (and the overlap rules mark it guessed).
    """
    covered = covered_labels(result)
    if not covered:
        return {}
    spaces = {space["id"]: space for space in result["spaces"]}
    directories = prepare_extents(result, sheet_path, out / "extents-redraw", only_ids=set(covered), exclude=covered)
    if not directories:
        return {}
    directory = directories[0]
    asked = {entry["space_id"] for entry in json.loads((directory / "request.json").read_text())["context"]["spaces"]}
    first = {space_id: spaces[space_id].pop("extent") for space_id in asked}
    readings.append(call(directory, directory.with_name(f"{directory.name}-provider")))
    read_extents(result, work, readings[-1], directory)
    def holds(box, space):
        centre = _label_centre(space)
        return centre is not None and box[0] < centre[0] < box[2] and box[1] < centre[1] < box[3]

    kept = 0
    for space_id, old in first.items():
        new = spaces[space_id].get("extent")
        if new is not None:
            inside = [other for other in covered[space_id] if holds(new["outline_box_px"], other)]
            # A box shrunk off its own label is not the space (round u6r5: cargo tanks redrawn
            # as a strip at the bottom to leave out a label).
            lost_own = holds(old["outline_box_px"], spaces[space_id]) and not holds(new["outline_box_px"],
                                                                                  spaces[space_id])
            shrunk = _area(new["outline_box_px"]) < REDRAW_MIN_AREA_SHARE * _area(old["outline_box_px"])
            if not inside and not lost_own and not shrunk:
                new["redrawn"] = "drawn again without the labels of the spaces beside it"
                kept += 1
                continue
        spaces[space_id]["extent"] = old
    return {"redraw_requests": 1, "redraw_asked": len(asked), "redraw_kept": kept}


def scale_pass(result: dict, sheet_path: Path, out: Path, call) -> dict:
    """Run both ``ga_scale`` requests for one ship. ``call(request_dir, out_dir)`` sends one request."""
    stats = {"requests": 0}
    readings = []
    if "ga" not in result.get("sources", {}) or not prepare_scale(result, sheet_path, out / "scale"):
        reason = "no profile or plan view was found on the sheet"
        result["frames"] = {"status": "unknown", "spacings": [], "reason": reason,
                            "source_record": source_record.unknown(reason)}
        result["measured"] = {field: _unknown(reason) for field in ("lbp_m", "loa_m", "breadth_m", "depth_m")}
        return stats
    # Small print is read differently from one request to the next: while the scale is not
    # established, the scale request is sent again and the marks of all replies are read together.
    work = None
    for attempt in range(1, SCALE_ATTEMPTS + 1):
        name = "scale" if attempt == 1 else f"scale-{attempt}"
        if attempt > 1:
            prepare_scale(result, sheet_path, out / name, result["frames"].get("reason"))
        readings.append(call(out / name, out / f"{name}-provider"))
        combined = read_scale(result, readings[-1], out / name, work)
        if combined.get("table") is None and work is not None:
            # The marks of earlier replies can spoil a clean reply (round u8: changes of spacing
            # drawn on one side of a local spacing only in the first reply); this reply alone.
            alone = read_scale(result, readings[-1], out / name)
            if alone.get("table") is not None:
                combined = alone
            else:
                combined = read_scale(result, readings[-1], out / name, work)  # its reason is kept
        work = combined
        if work.get("table") is not None:
            break
    stats["scale_attempts"] = attempt
    stats["frames"] = result["frames"]["status"]
    stats["measured"] = sorted(k for k, v in result["measured"].items() if v["status"] == MEASURED)
    checked = False
    directories = (prepare_extents(result, sheet_path, out / "extents", missing_places(work))
                   if work.get("table") is not None else [])
    if directories:
        totals: dict = {}
        for directory in directories:
            readings.append(call(directory, directory.with_name(f"{directory.name}-provider")))
            part = read_extents(result, work, readings[-1], directory)
            for key, value in part.items():
                totals[key] = totals.get(key, 0) + value if isinstance(value, int) else value
        # Deck equipment (cranes, hatch covers) is few and comes late in the priority order; when
        # the spaces fill the requests it is left without an extent (lane W, round u6r: three cranes
        # skipped). One more request asks for the cranes and hatches still without one.
        deck = {space["id"] for space in result["spaces"]
                if space["kind"] in DECK_EQUIPMENT and space["status"] == "read" and "extent" not in space}
        if deck:
            for directory in prepare_extents(result, sheet_path, out / "extents-deck", only_ids=deck)[:1]:
                readings.append(call(directory, directory.with_name(f"{directory.name}-provider")))
                part = read_extents(result, work, readings[-1], directory)
                for key, value in part.items():
                    totals[key] = totals.get(key, 0) + value if isinstance(value, int) else value
                totals["deck_requests"] = 1
        totals.update(redraw_covering_boxes(result, work, sheet_path, out, call, readings))
        totals["requests"] = len(directories) + totals.get("deck_requests", 0) + totals.get("redraw_requests", 0)
        stats["extents"] = totals
        if any(work["kinds"].get(view) == "profile" for view in work["axes"]):
            check_depth(result, work)
            checked = True
    if any("extent" in space for space in result["spaces"]):
        # After the depth check: a trimmed hold ends at a topside tank, not at the deck.
        stats["overlaps"] = resolve_overlaps(result)
        stats["overlaps"]["small_label_boxes_withheld"] = withhold_oversized_guesses(result)
    if not checked and result["measured"]["depth_m"]["status"] == MEASURED:
        # A depth that the space tops could not check is not given (see check_depth).
        pointed = result["measured"]["depth_m"]["value"]
        result["measured"]["depth_m"] = {
            **_unknown("the deck line could not be checked: no space below the deck was boxed in the profile"),
            "pointed_depth_m": pointed}
        result["checks"].append({"code": "depth_not_checked", "status": "check"})
    stats["measured"] = sorted(k for k, v in result["measured"].items() if v["status"] == MEASURED)
    stats["derived"] = sorted(k for k, v in result["measured"].items() if v["status"] == DERIVED)
    stats["requests"] = len(readings)
    return stats


# ------------------------------------------------------------------ the arrangement input

def _identity(space: dict) -> tuple:
    """What makes two labels the same physical space in two views (the side left out)."""
    from .ga_commercial import _base_number, COUNT_KINDS
    if space["kind"] in COUNT_KINDS.values() and space.get("number"):
        return space["kind"], _base_number(space["number"])
    if space.get("number"):
        # A numbered tank: its number and the words of its label ("NO. 4 W. B. TK (P)" in a plan
        # is "4 W. B. TK (P&S)" in the profile; round u6).
        return space["kind"], _base_number(space["number"]), label_family(space["label"])
    text = space["label"].upper()
    for pattern, _ in SIDE_WORDS:
        text = re.sub(pattern, "", text)
    return space["kind"], re.sub(r"[^A-Z0-9]", "", text)


def _sides(space: dict) -> set[str]:
    side = space["extent"].get("side")
    return {"port", "starboard"} if side == "both" else {side} if side else set()


def merged_spaces(result: dict) -> list[dict]:
    """One entry per physical space: x and z from the profile, y from a plan.

    A reading lists a numbered hold or tank once in each view. Views of the same space are
    joined by kind and number (or label); a plan entry of one side takes the profile entry
    that is printed for both sides.
    """
    kinds = {v["view_id"]: v["kind"] for v in result.get("views", [])}
    groups: dict[tuple, list[dict]] = {}
    plain = []
    for space in result["spaces"]:
        if "extent" in space:
            groups.setdefault(_identity(space), []).append(space)
        else:
            plain.append({key: space[key] for key in ("id", "kind", "label", "number", "status", "source_record",
                                                      "extent_withheld") if key in space})
    merged = []
    for members in groups.values():
        members = _without_repeats(members)
        profiles = [s for s in members if kinds.get(s["extent"]["view_id"]) == "profile"]
        plans = [s for s in members if s not in profiles]
        used_profiles = set()
        seen = []
        for plan in plans:
            if plan["kind"] == "cargo_hold" and seen:
                # A hold spans the breadth and is not split by side: a second plan entry of the same
                # numbered hold is a second reading, whatever its note says ("(PORT USE W. B.)"
                # read as a port side; round u10).
                continue
            side = plan["extent"].get("side")
            # The same space in a second plan view: its sides are already given over the same
            # frames ("(P&S)" on the tank top repeats "(P)" and "(S)" of the deck plan).
            covered = set().union(*[_sides({"extent": other}) for other in seen
                                    if _overlap(plan["extent"], other) > 0.5])
            if _sides(plan) and _sides(plan) <= covered:
                continue
            seen.append(plan["extent"])
            partner = next((p for p in profiles if _overlap(plan["extent"], p["extent"]) > 0.5
                            and (not _sides(p) or not side or side in _sides(p) or side == "centre")), None)
            merged.append(_joined(plan, partner))
            if partner:
                used_profiles.add(partner["id"])
        group = [entry for entry in merged if any(m["id"] == entry["id"] for m in members)]
        for profile in profiles:
            if profile["id"] in used_profiles:
                continue
            if any(_overlap(profile["extent"], entry["extent"]) > 0.5 for entry in group):
                continue  # a second reading of a space already given over the same frames (round u6)
            merged.append(_joined(None, profile))
            group.append(merged[-1])  # a later profile reading of the same space is checked against it
    kinds_of_view = {v["view_id"]: v["kind"] for v in result.get("views", [])}
    cargo_footprints = [e["extent"] for e in merged
                        if e["kind"] in ("cargo_hold", "cargo_tank") and "y_m" in e["extent"]]
    out = []
    for entry in merged:
        extent = entry["extent"]
        if (entry["kind"] == "other_space" and "z_m" not in extent and "y_m" in extent
                and all(kinds_of_view.get(view) == "deck_plan" for view in entry.get("views", []))
                and any(_footprint_share(extent, cargo) >= 0.5 for cargo in cargo_footprints)):
            # A room seen only on a deck plan over a hold or cargo tank stands on the deck (a store,
            # a deck house) or is a cut label; as a box from the base line it would take the cargo
            # space's volume (round u6).
            entry = {key: value for key, value in entry.items() if key != "extent"}
            entry["extent_withheld"] = "seen only on the deck plan, over a cargo space; its height is not known"
            out.append(entry)
            continue
        if entry["extent"].get("projection_of") and "y_m" not in entry["extent"]:
            # A tank drawn over a cargo space in the profile, with no plan to give its breadth:
            # as a full-breadth box it would take the cargo space's volume.
            entry = {key: value for key, value in entry.items() if key != "extent"}
            entry["extent_withheld"] = "drawn over a cargo space in the profile; no plan gives its breadth"
            out.append(entry)
            continue
        out.extend(_split_pair(entry))
    return out + plain


def _split_pair(entry: dict) -> list[dict]:
    """A pair printed for both sides ("(P&S)") whose plan box lies on one side: two spaces.

    The model boxes the tank on the side where its label is; the other tank of the pair is its
    mirror about the centreline (status ``guessed``). As one entry with ``side: both`` the
    pair would read as one space across the whole y range (development round 3: wing tanks of
    a pair given as one, so the cargo tank between them looked full breadth).
    """
    extent = entry["extent"]
    if extent.get("side") != "both" or side_of_label(entry["label"]) != "both":
        return [entry]
    if "y_m" not in extent:
        # No plan breadth: one tank on each side (the arrangement step then gives each half the
        # breadth). As one "both" entry it reads as one space (lane W, round u6).
        return [{**entry, "id": f"{entry['id']}-{side[0]}", "extent": {**extent, "side": side}}
                for side in ("port", "starboard")]
    low, high = extent["y_m"]
    if low < -CENTRE_TOLERANCE_M and high > CENTRE_TOLERANCE_M:
        # Boxed across the centreline: the label says two tanks, split at the centreline.
        halves = _without_outline(extent, "xy")
        return [{**entry, "id": f"{entry['id']}-p", "extent": {**halves, "side": "port", "y_m": [0.0, high]}},
                {**entry, "id": f"{entry['id']}-s", "extent": {**halves, "side": "starboard", "y_m": [low, 0.0]}}]
    boxed = "port" if low >= -CENTRE_TOLERANCE_M else "starboard"
    other = "starboard" if boxed == "port" else "port"
    first = {**entry, "id": f"{entry['id']}-{boxed[0]}", "extent": {**extent, "side": boxed}}
    mirror_extent = {**extent, "side": other, "y_m": [round(-high, 2), round(-low, 2)],
                     "status": {**extent["status"], "y": "guessed"},
                     "y_note": "mirror of the other tank of the pair about the centreline"}
    if extent.get("outline_m"):
        mirror_extent["outline_m"] = [
            {**outline, "points": [[x, round(-v, 2)] for x, v in outline["points"]], "status": "guessed"}
            if outline["plane"] == "xy" else outline for outline in extent["outline_m"]]
    second = {**entry, "id": f"{entry['id']}-{other[0]}", "extent": mirror_extent}
    return [first, second]


def _without_outline(extent: dict, plane: str) -> dict:
    """The extent without its outline in ``plane`` (an axis of that plane was changed)."""
    kept = [outline for outline in extent.get("outline_m", []) if outline["plane"] != plane]
    extent = {key: value for key, value in extent.items() if key != "outline_m"}
    if kept:
        extent["outline_m"] = kept
    return extent


def _footprint_share(a: dict, b: dict) -> float:
    """The share of extent ``a``'s plan footprint (x by y) that lies over extent ``b``'s."""
    xa, ya, xb, yb = a["x_m"], a["y_m"], b["x_m"], b["y_m"]
    area = (xa[1] - xa[0]) * (ya[1] - ya[0])
    shared = (max(0.0, min(xa[1], xb[1]) - max(xa[0], xb[0])) * max(0.0, min(ya[1], yb[1]) - max(ya[0], yb[0])))
    return shared / area if area > 0 else 0.0


def _overlap(a: dict, b: dict) -> float:
    """The shared length of two extents as a share of the shorter one."""
    shared = min(a["x_m"][1], b["x_m"][1]) - max(a["x_m"][0], b["x_m"][0])
    shorter = min(a["x_m"][1] - a["x_m"][0], b["x_m"][1] - b["x_m"][0])
    return shared / shorter if shorter > 0 else 0.0


def _without_repeats(members: list[dict]) -> list[dict]:
    """One entry where a view lists the same space twice (both passes read its label)."""
    kept: list[dict] = []
    # A boundary that was seen goes before one placed from the label.
    for space in sorted(members, key=lambda s: s["extent"]["basis"] != "outline"):
        extent = space["extent"]
        if not any(extent["view_id"] == other["extent"]["view_id"] and extent.get("side") == other["extent"].get("side")
                   and _overlap(extent, other["extent"]) > 0.5 for other in kept):
            kept.append(space)
    return kept


def _joined(plan: dict | None, profile: dict | None) -> dict:
    first = plan or profile
    extent = {"status": {}}
    x_source = profile or plan
    extent["frames"] = x_source["extent"]["frames"]
    extent["x_m"] = x_source["extent"]["x_m"]
    extent["status"]["x"] = x_source["extent"]["status"]["x"]
    if profile and "z_m" in profile["extent"]:
        extent["z_m"] = profile["extent"]["z_m"]
        extent["status"]["z"] = profile["extent"]["status"]["z"]
    if plan and "y_m" in plan["extent"]:
        extent["y_m"] = plan["extent"]["y_m"]
        extent["status"]["y"] = plan["extent"]["status"]["y"]
    side = (plan or profile)["extent"].get("side")
    if side:
        extent["side"] = side
    if profile and profile["extent"].get("projection_of"):
        extent["projection_of"] = profile["extent"]["projection_of"]
    # Optional traces of a boundary that is not a rectangle: x and z from the profile, x and y
    # from the plan (lane W's builder may ignore them; an entry without them is as before).
    outlines = [{"plane": source["extent"]["outline"]["plane"], "points": source["extent"]["outline"]["points_m"],
                 "status": source["extent"]["outline"]["status"]}
                for source, plane in ((profile, "xz"), (plan, "xy"))
                if source and source["extent"].get("outline", {}).get("plane") == plane]
    if outlines:
        extent["outline_m"] = outlines
    regions = [region for space in (plan, profile) if space
               for region in space["source_record"].get("regions", [])][:source_record.MAX_REGIONS]
    return {"id": first["id"], "kind": first["kind"], "label": first["label"], "number": first.get("number"),
            "status": first["status"], "source_record": source_record.validate(source_record.read(regions)),
            "views": [s["extent"]["view_id"] for s in (plan, profile) if s], "extent": extent}


# The arrangement step's gate (lane W): no space left without volume, no fragment labels, and no
# cargo space losing more of its volume to smaller spaces than in round s3b (worst: 56 % of a
# hold, 58 % of a cargo tank).
GATE_MAX_CARGO_LOSS = 0.58
# Kinds whose missing extents the gate reports as a coverage warning, not a failure.
COVERAGE_KINDS = ("fuel_tank", "ballast_tank")
GATE_GRID = 20
GATE_KINDS = ("cargo_hold", "cargo_tank", "slop_tank", "ballast_tank", "fuel_tank", "other_tank", "engine_room",
              "other_space")


def _gate_box(space: dict, breadth: float, depth: float) -> np.ndarray | None:
    """A space's box with the arrangement step's rules for a missing y or z."""
    extent = space.get("extent")
    if not extent or "x_m" not in extent:
        return None
    side = extent.get("side", "both")
    y = extent.get("y_m") or {"port": [0.0, breadth / 2], "starboard": [-breadth / 2, 0.0],
                              "centre": [-0.15 * breadth, 0.15 * breadth]}.get(side, [-breadth / 2, breadth / 2])
    z = extent.get("z_m") or [0.0, depth]
    return np.array([sorted(extent["x_m"]), sorted(y), sorted(z)], dtype=float)


def arrangement_gate(data: dict) -> dict:
    """The arrangement step's gate on an arrangement input, for regression checks.

    Spaces are cut from the smallest to the largest (each loses the parts that smaller spaces
    cover); the hull is not modelled. Returns the spaces left without volume, the fragment
    labels, each cargo space's loss, the spaces guessed on every axis that cover a cargo space
    (lane W, round u6r3), and ``passed``.
    """
    from .ga_commercial import _words, fragment_reason
    particulars = data.get("particulars", {})
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    spaces = [s for s in data["spaces"] if s["kind"] in GATE_KINDS]
    vocabulary_of = lambda space: {w for o in data["spaces"] if o is not space for w in _words(o["label"])}
    fragments = [s["label"] for s in data["spaces"]
                 if fragment_reason(s, [o for o in data["spaces"] if o is not s], vocabulary_of(s),
                                    {"".join(_words(o["label"])) for o in data["spaces"] if o is not s})]
    report = {"fragments": fragments, "no_volume": [], "cargo_loss": {}, "max_cargo_loss": None,
              "depth_status": (particulars.get("depth_m") or {}).get("status"),
              "guessed_over_cargo": []}
    if breadth and depth:
        report["guessed_over_cargo"] = [s["label"] for s in _guessed_over_cargo(spaces, breadth, depth)]
        boxes = [(s, _gate_box(s, breadth, depth)) for s in spaces]
        boxes = [(s, b) for s, b in boxes if b is not None and np.all(b[:, 1] > b[:, 0])]
        volume = lambda b: float(np.prod(b[:, 1] - b[:, 0]))
        for space, own in boxes:
            grid = np.meshgrid(*[np.linspace(own[i, 0], own[i, 1], GATE_GRID + 2)[1:-1] for i in range(3)],
                               indexing="ij")
            taken = np.zeros(grid[0].shape, dtype=bool)
            for other, box in boxes:
                if other is not space and volume(box) < volume(own):
                    taken |= np.all([(grid[i] > box[i, 0]) & (grid[i] < box[i, 1]) for i in range(3)], axis=0)
            loss = float(taken.mean())
            if loss >= 0.999:
                report["no_volume"].append(space["id"])
            if space["kind"] in ("cargo_hold", "cargo_tank"):
                report["cargo_loss"][space["id"]] = round(loss, 3)
        report["max_cargo_loss"] = max(report["cargo_loss"].values(), default=None)
    # Coverage warnings (not failures): a kind of tank with no extent on a ship whose other
    # spaces have extents; the fine pass reads different labels from run to run (PM, round u9n2).
    boxed = {s["kind"] for s in data["spaces"] if s.get("extent")}
    report["warnings"] = [f"no {kind.replace('_', ' ')} has an extent" for kind in COVERAGE_KINDS
                          if boxed and kind not in boxed]
    report["passed"] = (not report["fragments"] and not report["no_volume"] and not report["guessed_over_cargo"]
                        and (report["max_cargo_loss"] or 0.0) <= GATE_MAX_CARGO_LOSS)
    return report


def arrangement_input(result: dict, case_id: str) -> dict:
    """The reading in the form of docs/GA_ARRANGEMENT_INPUT.md.

    A particular is the printed value (status ``read``) when the drawing prints it, else the
    value measured with the frame scale (status ``measured_from_scale``), else null. This file
    is for the arrangement step only; the GA exam reads ``ga_reading.json``.
    """
    particulars = {}
    for field in ("loa_m", "lbp_m", "breadth_m", "depth_m"):
        printed = result.get("particulars", {}).get(field) or {}
        measured = (result.get("measured") or {}).get(field) or {}
        if printed.get("value") is not None:
            particulars[field] = {key: printed[key] for key in ("value", "status", "source_record")}
        elif measured.get("value") is not None:
            # The status says what the value is: measured_from_scale, or derived_from_space_tops.
            particulars[field] = {key: measured[key] for key in
                                  ("value", "status", "uncertainty_m", "method", "note", "reason", "pointed_depth_m",
                                   "cross_check", "source_record") if key in measured}
        else:
            reason = measured.get("reason") or printed.get("reason") or "not printed and not measured"
            particulars[field] = _unknown(reason)
    frames = result.get("frames") or {"status": "unknown", "spacings": []}
    spaces, dropped = _without_same_boxes(merged_spaces(result), particulars)
    spaces = _without_outboard_extents(spaces, particulars)
    spaces = _centred_when_off_centre(spaces, particulars)
    spaces = _deck_equipment_on_the_deck(spaces, particulars)
    spaces = _side_boxes_without_height(spaces, particulars)
    spaces = _without_guessed_over_cargo(spaces, particulars)
    spaces = _without_cargo_number_conflicts(spaces, particulars)
    return {"schema": INPUT_SCHEMA, "case_id": case_id, "engineering_approved": False,
            "sources": result["sources"], "ship_type": result.get("ship_type"),
            "particulars": particulars, "frames": frames, "spaces": spaces, "dropped": dropped}


# A box guessed on every axis that shares more than this share of its volume with a cargo
# space covers it (touching faces and rounding stay below it).
GUESSED_OVER_CARGO_SHARE = 0.02
CARGO_KINDS = ("cargo_hold", "cargo_tank")
# A box whose outer side reaches this share of the half breadth lies against the shell: a wing,
# topside or side tank beside the cargo space (often inside a cargo box drawn to the shell). It
# is not a small space guessed over the cargo space.
AT_SHELL_SHARE = 0.85
# Such a box against the shell may still take at most this share of a cargo space's volume (lane
# W, round u6r7; development ships: side, topside and bottom tanks took up to 12 %, boxes drawn
# from the shell to near the centreline 34-80 %).
SHELL_BOX_MAX_CARGO_SHARE = 0.15


def _guessed_over_cargo(spaces: list[dict], breadth: float, depth: float) -> list[dict]:
    """The spaces (not cargo) whose extent is guessed on every axis and covers a cargo space,
    with the missing y and z filled by the arrangement step's rules. A box against the shell (a
    side tank) counts only when it takes more than ``SHELL_BOX_MAX_CARGO_SHARE`` of the cargo
    space."""
    cargo = [box for space in spaces if space["kind"] in CARGO_KINDS
             and (box := _gate_box(space, breadth, depth)) is not None]
    found = []
    for space in spaces:
        extent = space.get("extent")
        if not extent or space["kind"] in CARGO_KINDS + DECK_EQUIPMENT or not _all_guessed(extent):
            continue  # a hatch or crane stands on the deck above the cargo space
        own = _gate_box(space, breadth, depth)
        if own is None or not np.all(own[:, 1] > own[:, 0]):
            continue
        at_shell = max(abs(own[1, 0]), abs(own[1, 1])) >= AT_SHELL_SHARE * breadth / 2
        volume = float(np.prod(own[:, 1] - own[:, 0]))
        for box in cargo:
            shared = float(np.prod(np.clip(np.minimum(own[:, 1], box[:, 1]) - np.maximum(own[:, 0], box[:, 0]),
                                           0.0, None)))
            if (shared > SHELL_BOX_MAX_CARGO_SHARE * float(np.prod(box[:, 1] - box[:, 0])) if at_shell
                    else shared > GUESSED_OVER_CARGO_SHARE * volume):
                found.append(space)
                break
    return found


# A hold or a space on the centreline whose y range is off the centreline by more than this share
# of the breadth (|y_min + y_max| / B) is not a measured breadth (lane W, round u6r7: a hold
# boxed from -7 to +12 m).
OFF_CENTRE_SHARE = 0.10
# A tank against the shell guessed on every axis, with no height drawn in a profile, is placed in
# this upper share of the depth: top-side, upper wing and gravity wing tanks lie under the deck
# (lane W, round u6r7: such tanks filled to full height became wing columns in a hold).
UPPER_BAND_SHARE = 0.3
# A tank in the lower part of the hull ("D.B.", "BTM", "HOPPER"): it gets no upper band.
LOWER_TANK = re.compile(r"\bD\s*\.?\s*B\b|\bD/B\b|BTM|BOTTOM|HOPPER|LOWER|DOUBLE")


# A crane or hatch box whose bottom is more than this above the deck is the crane house or a
# part of the hatch cover, not the whole (lane W, round u6r8: crane posts started 8 m above the
# deck); a hatch coaming or a crane pedestal stands on the deck.
DECK_EQUIPMENT_GAP_M = 1.0


def _deck_equipment_on_the_deck(spaces: list[dict], particulars: dict) -> list[dict]:
    """Cranes and hatches reach down to the deck; the extended bottom is guessed."""
    depth = (particulars.get("depth_m") or {}).get("value")
    if not depth:
        return spaces
    kept = []
    for space in spaces:
        extent = space.get("extent") or {}
        z = extent.get("z_m")
        if space["kind"] in DECK_EQUIPMENT and z and z[0] > depth + DECK_EQUIPMENT_GAP_M:
            extent = {**_without_outline(extent, "xz"), "z_m": [round(depth, 2), z[1]],
                      "status": {**extent["status"], "z": "guessed"},
                      "z_note": "the box began above the deck; extended down to the deck it stands on"}
            space = {**space, "extent": extent}
        kept.append(space)
    return kept


def _centred_when_off_centre(spaces: list[dict], particulars: dict) -> list[dict]:
    """A hold, or a space on the centreline, boxed clearly off the centreline: its y is centred
    with the same breadth and becomes guessed."""
    breadth = (particulars.get("breadth_m") or {}).get("value")
    if not breadth:
        return spaces
    kept = []
    for space in spaces:
        extent = space.get("extent") or {}
        y = extent.get("y_m")
        on_centre = space["kind"] == "cargo_hold" or extent.get("side") in ("centre", "both")
        if y and on_centre and abs(y[0] + y[1]) > OFF_CENTRE_SHARE * breadth:
            half = min((y[1] - y[0]) / 2, breadth / 2)
            extent = {**_without_outline(extent, "xy"), "y_m": [round(-half, 2), round(half, 2)],
                      "status": {**extent.get("status", {}), "y": "guessed"},
                      "y_note": "boxed off the centreline; centred with the same breadth"}
            space = {**space, "extent": extent}
        kept.append(space)
    return kept


def _side_boxes_without_height(spaces: list[dict], particulars: dict) -> list[dict]:
    """A tank against the shell guessed on every axis with no drawn height (no profile box) goes
    in an upper band under the deck; one named as a lower tank (double bottom, hopper) loses its
    extent instead."""
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    if not breadth or not depth:
        return spaces
    kept = []
    for space in spaces:
        extent = space.get("extent") or {}
        y = extent.get("y_m")
        if (extent and y and "z_m" not in extent and _all_guessed(extent)
                and space["kind"] not in CARGO_KINDS + DECK_EQUIPMENT
                and max(abs(y[0]), abs(y[1])) >= AT_SHELL_SHARE * breadth / 2):
            if LOWER_TANK.search(space["label"].upper()):
                space = {key: value for key, value in space.items() if key != "extent"}
                space["extent_withheld"] = "guessed against the shell with no height drawn"
            else:
                extent = {**extent, "z_m": [round(depth * (1 - UPPER_BAND_SHARE), 2), round(depth, 2)],
                          "status": {**extent["status"], "z": "guessed"},
                          "z_note": "no height drawn: placed in the upper part, under the deck"}
                space = {**space, "extent": extent}
        kept.append(space)
    return kept


# Two cargo spaces of different numbers that share this share of the smaller box are one place
# read with two numbers.
CARGO_CONFLICT_SHARE = 0.5


def _without_cargo_number_conflicts(spaces: list[dict], particulars: dict) -> list[dict]:
    """Two cargo spaces with different numbers boxed at one place: the views read the number
    differently (round u10: "NO.2", "NO.3" and "NO.5" at the same frames in three views), and
    code cannot tell which reading is right, so both lose their extents."""
    from .ga_commercial import _base_number
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    if not breadth or not depth:
        return spaces
    cargo = [(space, box) for space in spaces if space["kind"] in CARGO_KINDS and space.get("number")
             and (box := _gate_box(space, breadth, depth)) is not None and np.all(box[:, 1] > box[:, 0])]
    conflicting = set()
    for index, (a, box_a) in enumerate(cargo):
        for b, box_b in cargo[index + 1:]:
            if a["kind"] != b["kind"] or _base_number(a["number"]) == _base_number(b["number"]):
                continue
            shared = float(np.prod(np.clip(np.minimum(box_a[:, 1], box_b[:, 1])
                                           - np.maximum(box_a[:, 0], box_b[:, 0]), 0.0, None)))
            smaller = min(float(np.prod(box_a[:, 1] - box_a[:, 0])), float(np.prod(box_b[:, 1] - box_b[:, 0])))
            if shared > CARGO_CONFLICT_SHARE * smaller:
                conflicting.update((id(a), id(b)))
    kept = []
    for space in spaces:
        if id(space) in conflicting:
            space = {key: value for key, value in space.items() if key != "extent"}
            space["extent_withheld"] = "another cargo space with a different number is boxed at the same place"
        kept.append(space)
    return kept


def _without_guessed_over_cargo(spaces: list[dict], particulars: dict) -> list[dict]:
    """A box guessed on every axis does not cover a labelled cargo space (lane W, round u6r3: a
    small tank guessed along a whole hold took its port side): it loses its extent."""
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    if not breadth or not depth:
        return spaces
    covering = {id(space) for space in _guessed_over_cargo(spaces, breadth, depth)}
    kept = []
    for space in spaces:
        if id(space) in covering:
            space = {key: value for key, value in space.items() if key != "extent"}
            space["extent_withheld"] = "guessed on every axis and over a cargo space"
        kept.append(space)
    return kept


def _without_outboard_extents(spaces: list[dict], particulars: dict) -> list[dict]:
    """No space extent outside the hull: a box whose breadth lies mostly outboard of the half
    breadth (a ladder or a boat beside the ship; lane W, round u6r) loses its extent."""
    breadth = (particulars.get("breadth_m") or {}).get("value")
    if not breadth:
        return spaces
    half = breadth / 2
    kept = []
    for space in spaces:
        y = (space.get("extent") or {}).get("y_m")
        if y and y[1] > y[0]:
            outside = max(0.0, y[1] - max(y[0], half)) + max(0.0, min(y[1], -half) - y[0])
            if outside / (y[1] - y[0]) > 0.5:
                space = {key: value for key, value in space.items() if key != "extent"}
                space["extent_withheld"] = "outboard of the hull: not a space inside the ship"
        kept.append(space)
    return kept


# Two entries whose boxes share this share of each other's volume are one space read twice.
SAME_BOX_SHARE = 0.85


def _without_same_boxes(spaces: list[dict], particulars: dict) -> tuple[list[dict], list[dict]]:
    """One entry per box: two labels on one compartment (a misread repeat, a cut label) give
    two boxes, and the arrangement step would leave one of them without volume (round u6).

    The entry kept is the one with a counted or named kind, then a printed number, then the
    longer label; the other is listed in ``dropped`` with the reason.
    """
    breadth = (particulars.get("breadth_m") or {}).get("value")
    depth = (particulars.get("depth_m") or {}).get("value")
    if not breadth or not depth:
        return spaces, []
    boxes = {id(s): _gate_box(s, breadth, depth) for s in spaces if s["kind"] in GATE_KINDS}

    def rank(space):
        return (not space["kind"].startswith("other_"), bool(space.get("number")), len(space["label"]))

    dropped_ids, dropped = set(), []
    order = sorted((s for s in spaces if boxes.get(id(s)) is not None), key=rank, reverse=True)
    for index, keep in enumerate(order):
        if id(keep) in dropped_ids:
            continue
        a = boxes[id(keep)]
        for other in order[index + 1:]:
            if id(other) in dropped_ids:
                continue
            b = boxes[id(other)]
            shared = float(np.prod(np.clip(np.minimum(a[:, 1], b[:, 1]) - np.maximum(a[:, 0], b[:, 0]), 0, None)))
            if min(shared / float(np.prod(a[:, 1] - a[:, 0])), shared / float(np.prod(b[:, 1] - b[:, 0]))) >= SAME_BOX_SHARE:
                dropped_ids.add(id(other))
                dropped.append({"id": other["id"], "label": other["label"],
                                "reason": f"the same box as {keep['id']} ({keep['label'][:40]})"})
    return [s for s in spaces if id(s) not in dropped_ids], dropped
