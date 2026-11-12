"""Commercial GA frames; rules and constants unchanged."""
from __future__ import annotations

from .ga_scale_settings import (
    CHOSEN_BY_FIT,
    FIT_CHOICE_ERROR,
    FIT_CHOICE_MARGIN,
    LOCAL_FIT_GAIN,
    MAX_OUTLIER_RUN,
    MAX_OUTLIER_SHARE,
    MAX_RMS_FRAMES,
    MIN_OUTLIER_PX,
    MIN_RANGE_TICKS,
    MIN_TICKS,
    OUTLIER_FRAMES,
    RANGE_SLOPE_TOLERANCE,
    SAME_LABEL_PX,
    SAME_MARK_PX,
    SHORT_RANGE_TOLERANCE,
    SPACING_RANGE_MM,
    STANDARD_SPACINGS_MM,
    STRAIGHT_RUN_TOLERANCE,
    UNITLESS_METRES_BELOW,
)
from dataclasses import dataclass
import math
import numpy as np
import re


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
    cuts, edges, inside, groups, locals_found = _group_spacing_texts(ticks, labels, boundaries, _one_frame)
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
    values, cuts, inside, anchor, chosen_by_fit, reason = _select_range_spacings(
        ticks, found, inside, edges, cuts, px_per_m)
    if reason:
        return None, reason
    cut_frames, wrong, texts_of_wrong = _place_spacing_changes(ticks, labels, cuts, values, inside, anchor, px_per_m)
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


def _group_spacing_texts(ticks, labels, boundaries, _one_frame):
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
    return cuts, edges, inside, groups, locals_found


def _place_spacing_changes(ticks, labels, cuts, values, inside, anchor, px_per_m):
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
    return cut_frames, wrong, texts_of_wrong


def _select_range_spacings(ticks, found, inside, edges, cuts, px_per_m):
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
                    return None, None, None, None, None, "the frame numbers of a range do not fit its printed spacing"
                fitting = {chosen}
                frames_here = [frame for frame, _ in inside[index]]
                chosen_by_fit.append((min(frames_here), max(frames_here), chosen))
        if len(fitting) > 1:
            return None, None, None, None, None, "two different frame spacings are printed with no change drawn between them"
        values.append(next(iter(fitting)) if fitting else None)
    # A range without a printed spacing: at an end of the scale it takes no part; between two
    # ranges, or with frame numbers inside it, the scale is not established.
    for index, value in enumerate(values):
        if value is not None:
            continue
        low, high = edges[index], edges[index + 1]
        if index not in (0, len(values) - 1) or any(low < place <= high for _, place in ticks):
            return None, None, None, None, None, "a part of the frame scale has no printed spacing"
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

    return values, cuts, inside, anchor, chosen_by_fit, None
