"""Tanks from a scanned (raster) tank or capacity plan: ink -> axes, regions, labels -> tank solids.

Design and metrics: docs/TANKS_V2.md. Code does all geometry; a model only reads the text of
crops that code cut out (frame numbers, scale-bar numbers, tank labels, a tank schedule). The
reader is not ship-specific: a sheet is described by a ``SheetSpec`` (view windows, which view
is a profile or a plan, the frame spacing or a scale bar), which a person fills in without truth.

Steps for one view (a window of the sheet):

1. Long horizontal and vertical lines by morphological opening (dashed lines are closed first).
2. Straight non-axis lines by a Hough transform; pairs of diagonals that cross inside each other
   (a tank's cross mark, drawn corner to corner) are erased, other lines are drawn solid so that
   dashed boundaries close.
3. Text: small ink components that are not part of a line, grouped into blocks.
4. Regions: 4-connected background of the boundary ink (text removed).
5. Axis: a long horizontal line with regular ticks. Each tick label is read by the model; code
   numbers the ticks, finds frame 0 and gives x in metres for each pixel column. A scale bar
   gives the scale only.

A tank is the plan region at its label; its vertical limits come from the profile region of
the same tank (matched by x overlap and label words) or, for a double-bottom plan, from the
lowest horizontal line above the baseline. Solids are clipped to the hull when a hull mesh is
given (lofted through hull sections, ``tanks.tank_loft_in_hull``); without a hull a tank is a
prism of its plan region.

Labels are tied to a sheet's schedule: a circled item number in a view takes the name of its
schedule row ("5" -> "RESERVE FEED WATER TANK NO.4P"). A region becomes a tank only with a tank
word or a schedule tank row (a hatch or a girder never does). A tank that only the profile names
(a deep tank, a peak) is built from its profile region, with the plan outlines' breadth at the
same frames (``profile_tanks``). Plans without frame numbers are aligned to the profile by their
bulkheads.

Every value carries a source label (``traced``, ``read`` or ``guessed``). ``engineering_approved``
is false for every result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
import math
from pathlib import Path
import re
import statistics
from typing import Callable

import numpy as np

from . import tanks

MM_PER_INCH = 25.4
FEET_M = 0.3048
# Grey level below which a pixel of a grey render is ink (as the GA raster path).
INK_THRESHOLD = 160

# Sizes on the paper (mm). The sheet resolution turns them into pixels, so the same constants
# work at 200, 300 and 400 dpi.
LINE_MIN_MM = 12.0  # a horizontal or vertical line is at least this long
DASH_GAP_MM = 2.5  # dashed horizontal and vertical lines: longest gap that is closed
# Straight non-axis lines: longest gap bridged (a dash-dot gap with its dot removed as text).
HOUGH_GAP_MM = 4.0
# Collinear pieces are joined over gaps up to this (a label written across a cross mark).
JOIN_GAP_MM = 15.0
HOUGH_MIN_MM = 5.0  # shortest straight non-axis line looked for
CROSS_MIN_MM = 6.0  # a cross-mark diagonal is at least this long
# A thin straight stroke at least this long is line ink (a dash of a dashed line), not a text
# seed. Letters such as "l" or "1" fall in this class too: they stay in the label crops (the
# crop margin), but a row of dashes cannot chain labels into one block.
DASH_MIN_MM = 1.5
# Spread across a dash (standard deviation of its pixels across the stroke) as a share of the line
# width: a straight stroke of width w has a spread of about 0.3 w.
DASH_SPREAD = 0.6
CHAR_MIN_MM = 0.9  # text character height range
CHAR_MAX_MM = 7.0
CHAR_MAX_WIDTH_MM = 9.0
# At most this many ticks in a row may be hidden (a tank boundary across the axis).
MAX_MISSING_TICKS = 2
TICK_MIN_MM = 0.8  # frame tick: total length range
TICK_MAX_MM = 9.0
AXIS_LABEL_BAND_MM = (0.6, 12.0)  # frame numbers sit this far below (or above) the axis line
# A cross mark's diagonals cross each other near their middles (the longer arm of a diagonal at
# most CROSS_ARM_RATIO times the shorter), and their x ends agree within CROSS_END_TOL (share of
# the length) or CROSS_END_MIN_MM.
CROSS_ARM_RATIO = 3.0
CROSS_SIDE_INKED = (0.5, 0.7)  # the less and the more inked end side
CROSS_END_TOL = 0.04
CROSS_END_MIN_MM = 1.5
# Hough pieces of one line differ in direction by up to this (degrees) when they are joined.
MERGE_ANGLE_DEG = 2.0
# Angles (degrees from the horizontal) of lines that count as horizontal or vertical.
AXIS_ANGLE_DEG = 4.0
# Share of the view width that an axis line (frame axis, centre line, baseline) covers.
AXIS_COVER = 0.35
# A region at most this many character heights larger than its label (in height and in width) is
# the label's enclosure (a circled item number), not a compartment.
ENCLOSURE_CHARS = 1.5
# A region that covers more than this share of the view is the background, not a tank.
MAX_REGION_SHARE = 0.25
# Profile: a region whose bottom is this close to the baseline sits on the bottom shell.
ON_BOTTOM_M = 0.30
# A profile region gives a plan tank's height only when their x extents overlap over this share
# of the longer one.
MIN_PROFILE_COVER = 0.6
# A deck line spans at least this share of the profile; a tank is at least this high (m).
DECK_MIN_COVER = 0.3
MIN_TANK_HEIGHT_M = 1.0
# Plan to profile alignment (scale-bar sheets): search range and bin (m); a long vertical line
# spans at least this share of its view's height.
ALIGN_SEARCH_M = 6.0
ALIGN_BIN_M = 0.1
ALIGN_MIN_LINE = 0.15
# An alignment counts as read from the drawing when at least this many bulkhead bins agree.
ALIGN_MIN_AGREEING = 5
# A plan's centre line is a long horizontal line within this distance (mm) of the outline's middle.
CENTRE_SNAP_MM = 3.0
# A baseline label lies within this many character heights of its line.
BASELINE_REACH = 4
# Double-bottom plans: the tank top is the lowest horizontal line at least this far above base.
MIN_DOUBLE_BOTTOM_M = 0.35
# A profile tank on the bottom no higher than this (m) is a double-bottom tank (deep double
# bottoms of large ships stay under about 2.5 m).
MAX_DOUBLE_BOTTOM_M = 2.5
# Text height in the question images (px): small print is enlarged to this.
QUESTION_TEXT_PX = 30
# Margin around a label block in its question crop (shares of the character height: above and
# below, left and right). Wider at the sides, where a letter that touched a line may be missing
# from the block.
LABEL_MARGIN = (0.4, 1.2)
QUESTION_WIDTH_PX = 2000
# Text blocks of one region closer than this many character heights are read as one label.
CLUSTER_CHARS = 2.0
QUESTION_MAX_HEIGHT_PX = 2000
# Steps of the solid: hull sections (or slabs without a hull) 0.10 m apart in x, rows of 0.02 m.
TANK_SLAB_M = 0.10
TANK_ROW_DZ_M = 0.02

# Content words (lower case, in order: the first match wins) -> capacity-plan content group.
CONTENT_WORDS = (
    ('dry ballast', 'dry'),  # solid ballast, not a liquid
    ('lub', 'lube oil'), ('l.o', 'lube oil'),
    ('fuel', 'fuel oil'), ('f.o', 'fuel oil'), ('diesel', 'fuel oil'), ('d.o', 'fuel oil'),
    ('fo', 'fuel oil'), ('settling', 'fuel oil'),
    ('ballast', 'water ballast'), ('technical water', 'water ballast'), ('tw', 'water ballast'),
    ('roll damp', 'water ballast'),
    ('fresh', 'fresh water'), ('f.w', 'fresh water'), ('culinary', 'fresh water'), ('potable', 'fresh water'), ('drinking', 'fresh water'),
    ('distill', 'fresh water'), ('feed', 'fresh water'), ('fw', 'fresh water'),
    ('sewage', 'misc'), ('sew', 'misc'), ('sludge', 'misc'), ('bilge', 'misc'), ('waste', 'misc'),
    ('grey', 'misc'), ('gray', 'misc'), ('black', 'misc'), ('misc', 'misc'),
    ('cargo tank', 'cargo oil'), ('cargo oil', 'cargo oil'),
    ('dry', 'dry'), ('void', 'dry'), ('cofferdam', 'dry'), ('hold', 'dry'), ('cargo', 'dry'),
    ('peak', 'water ballast'),  # a peak tank without a content word
)
# A content word must start a token ("fw" is not in "fwd"). A code of at most this many letters
# ("fw", "tw", "f.o", "dry") and the word "peak" must also end a token, so "'TWEEN DECK" is not
# "tw" and "PEAKED" is not a peak; longer words may be cut short ("lub" in "lubricating").
CONTENT_CODE_MAX_LETTERS = 3


def _content_pattern(word: str) -> re.Pattern:
    letters = word.replace('.', '')
    start = r'(?<![a-z0-9])'
    if word == 'peak':  # also "fore peak" written as one word
        return re.compile(start + r'(?:fore|after|aft)?peak(?![a-z0-9])')
    end = r'(?![a-z0-9])' if len(letters) <= CONTENT_CODE_MAX_LETTERS else ''
    return re.compile(start + re.escape(word) + end)


CONTENT_PATTERNS = tuple((_content_pattern(word), group) for word, group in CONTENT_WORDS)
# Words that do not tell two tanks apart when a plan label is matched to a profile label.
STOP_WORDS = {'no', 'tank', 'tanks', 'tk', 'new', 'dbb', 'dbl', 'bot', 'the', 'and', 'or', 'p', 'sb',
              's', 'port', 'stbd', 'ps'}
# A tank or compartment: one of these words, or a liquid content word (CONTENT_WORDS).
TANK_WORDS = re.compile(r'\b(tanks?|tk|deep\s*tank|peak|dbb|d\.\s*b\.?|double\s+bottom|hold)\b')
# Features drawn in plans that are never a tank, even beside a tank word ("DEEP TANK HATCH",
# "F.W. TANK COFFERDAM UNDER", "GIRDER OVER WEB NO.2 HATCH").
FEATURE_WORDS = re.compile(r'\b(hatch|girders?|cofferdam|trunk|escape|casing|winch|locker|web|companion|swash'
                           r'|recess|tunnel)\b')
# Rooms and spaces of a profile ("MACHINERY SPACE", "NO.7D BETWEEN DECKS", "HOLD"): a profile region
# whose label has one of these is not a tank, even when a tank's label leaked into it.
ROOM_WORDS = re.compile(r'\b(machinery|spaces?|holds?|between|decks?|stores|rooms?|flat|engine|boiler)\b')
# Words that give a tank its kind (first match wins), as a capacity plan names them.
KIND_PATTERNS = (
    ('deep tank', re.compile(r'\bdeep\s*tanks?\b|\bdeep\b')),
    ('peak', re.compile(r'\bpeak\b')),
    ('settling', re.compile(r'\bsettling\b')),
    ('double bottom', re.compile(r'\bd\.\s*b\b|\bdbb\b|\bdouble\s+bottom\b')),
)
# A tank on both sides of the centre line, named once ("NO.2 P/S", "P & S").
BOTH_SIDES = re.compile(r'\bp\s*[/&]\s*s\b', re.IGNORECASE)
# A schedule item number written alone in a view (often circled): one or two digits not after "No".
ITEM_TOKEN = re.compile(r'(?<![\w.])(?<!no )(?<!no\. )\(?(\d{1,2})\)?(?![\w\'"./-])', re.IGNORECASE)


# ---------------------------------------------------------------------------------------------
# Sheet and view description (host calibration, no geometry)


@dataclass
class ViewSpec:
    name: str
    kind: str  # 'plan' or 'profile'
    window: tuple[float, float, float, float]  # x0, y0, x1, y1 as shares of the sheet
    # Plans: 'double_bottom' (tanks below the tank top) or 'above' (other tanks).
    role: str = 'double_bottom'
    # Views are read as drawn with the bow to the right (a mirrored crop would mirror the text).


@dataclass
class SheetSpec:
    views: list[ViewSpec]
    frame_spacing_m: float | None = None  # read by a person from the sheet; None: scale bar
    scale_bar: tuple[float, float, float, float] | None = None  # window of a graphic scale bar
    scale_bar_unit_m: float = FEET_M
    schedule: tuple[float, float, float, float] | None = None  # window of a tank schedule
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# Ink


def skew_angle_deg(ink: np.ndarray, px_per_mm: float) -> float:
    """Skew of the drawing from its long near-horizontal lines (degrees; positive turns the
    lines counter-clockwise in the image). Measured on a reduced image."""
    import cv2

    step = max(1, int(round(px_per_mm / 4)))  # about 4 px per mm
    small = ink[::step, ::step].astype(np.uint8) * 255
    min_length = int(LINE_MIN_MM * 4 * 4)
    lines = cv2.HoughLinesP(small, 1, np.pi / 3600, threshold=min_length, minLineLength=min_length,
                            maxLineGap=4)
    if lines is None:
        return 0.0
    angles, weights = [], []
    for x0, y0, x1, y1 in lines[:, 0]:
        angle = math.degrees(math.atan2(-(y1 - y0), x1 - x0))
        if abs(angle) < 2.0:
            angles.append(angle)
            weights.append(math.hypot(x1 - x0, y1 - y0))
    if not angles:
        return 0.0
    order = np.argsort(angles)
    cumulative = np.cumsum(np.asarray(weights)[order])
    return float(np.asarray(angles)[order][np.searchsorted(cumulative, cumulative[-1] / 2)])


def deskew(ink: np.ndarray, px_per_mm: float) -> tuple[np.ndarray, float]:
    """The ink turned so that the long lines are horizontal, and the angle removed (degrees)."""
    import cv2

    angle = skew_angle_deg(ink, px_per_mm)
    if abs(angle) < 0.02:
        return ink, 0.0
    height, width = ink.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), -angle, 1.0)
    turned = cv2.warpAffine(ink.astype(np.uint8), matrix, (width, height), flags=cv2.INTER_NEAREST,
                            borderValue=0)
    return turned.astype(bool), angle


# ---------------------------------------------------------------------------------------------
# Lines, text and regions of one view


@dataclass
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    @property
    def angle_deg(self) -> float:
        """Angle from the horizontal in (-90, 90]."""
        angle = math.degrees(math.atan2(-(self.y1 - self.y0), self.x1 - self.x0))
        return angle - 180 if angle > 90 else angle + 180 if angle <= -90 else angle


def merge_collinear(segments: list[Segment], angle_tol: float, distance_tol: float, gap: float) -> list[Segment]:
    """Join Hough pieces of one straight line (same direction, same normal offset, touching),
    repeated until nothing more joins."""
    while True:
        merged = _merge_pass(segments, angle_tol, distance_tol, gap)
        if len(merged) == len(segments):
            return merged
        segments = merged


def _merge_pass(segments: list[Segment], angle_tol: float, distance_tol: float, gap: float) -> list[Segment]:
    merged: list[Segment] = []
    for segment in sorted(segments, key=lambda s: -s.length):
        for i, line in enumerate(merged):
            if abs(((segment.angle_deg - line.angle_deg) + 90) % 180 - 90) > angle_tol:
                continue
            direction = np.array([line.x1 - line.x0, line.y1 - line.y0]) / line.length
            normal = np.array([-direction[1], direction[0]])
            ends = np.array([[segment.x0, segment.y0], [segment.x1, segment.y1]]) - [line.x0, line.y0]
            if np.abs(ends @ normal).max() > distance_tol:
                continue
            along = sorted(ends @ direction)
            if along[0] > line.length + gap or along[1] < -gap:
                continue
            low, high = min(0.0, along[0]), max(line.length, along[1])
            start = np.array([line.x0, line.y0])
            a, b = start + low * direction, start + high * direction
            merged[i] = Segment(float(a[0]), float(a[1]), float(b[0]), float(b[1]))
            break
        else:
            merged.append(segment)
    return merged


def _intersection(a: Segment, b: Segment) -> tuple[float, float] | None:
    """Parameters (0..1 along a, along b) of the crossing point of two segments' lines."""
    p, r = np.array([a.x0, a.y0]), np.array([a.x1 - a.x0, a.y1 - a.y0])
    q, s = np.array([b.x0, b.y0]), np.array([b.x1 - b.x0, b.y1 - b.y0])
    denominator = r[0] * s[1] - r[1] * s[0]
    if abs(denominator) < 1e-9:
        return None
    t = ((q - p)[0] * s[1] - (q - p)[1] * s[0]) / denominator
    u = ((q - p)[0] * r[1] - (q - p)[1] * r[0]) / denominator
    return float(t), float(u)


def cross_marks(segments: list[Segment], stops: np.ndarray, px_per_mm: float,
                lines: np.ndarray | None = None) -> list[tuple[Segment, Segment]]:
    """Cross marks of tanks: two diagonals with opposite slopes that cross each other.

    Collinear diagonals of neighbouring tanks join into one Hough line, so each diagonal is cut
    to its arms: from the crossing point along the line until it meets a horizontal or vertical
    line (``stops``) or the line's end. A cross mark has its crossing near the middle of both
    diagonals (each arm ratio within CROSS_ARM_RATIO) and both diagonals have the same x ends
    (the box corners). With ``lines`` (line ink), at least one end side of the box (the line
    between the two left or the two right corners) must be drawn over CROSS_SIDE_INKED[1] of its
    length, and the other over CROSS_SIDE_INKED[0] (a corner may lie on a curved hull side): two
    crossing boundary lines with nothing between their ends are not a cross mark.
    Returns the four-arm diagonals as segments between their arm ends."""
    diagonals = [s for s in segments if AXIS_ANGLE_DEG < abs(s.angle_deg) < 90 - AXIS_ANGLE_DEG
                 and s.length >= CROSS_MIN_MM * px_per_mm]
    pairs = []
    for i, first in enumerate(diagonals):
        for second in diagonals[i + 1:]:
            if np.sign(first.angle_deg) == np.sign(second.angle_deg):
                continue
            crossing = _intersection(first, second)
            if crossing is None or not all(0.0 <= value <= 1.0 for value in crossing):
                continue
            point = np.array([first.x0, first.y0]) + crossing[0] * np.array([first.x1 - first.x0, first.y1 - first.y0])
            cut = [_arms(line, point, stops, px_per_mm) for line in (first, second)]
            if any(c is None for c in cut):
                continue
            (a0, a1), (b0, b1) = cut
            arms = [np.linalg.norm(a0 - point), np.linalg.norm(a1 - point), np.linalg.norm(b0 - point),
                    np.linalg.norm(b1 - point)]
            if min(arms) < CROSS_MIN_MM * px_per_mm / 2:
                continue
            ratios = (arms[0] / arms[1], arms[2] / arms[3])
            if not all(1 / CROSS_ARM_RATIO <= ratio <= CROSS_ARM_RATIO for ratio in ratios):
                continue
            ends_a = sorted((a0[0], a1[0]))
            ends_b = sorted((b0[0], b1[0]))
            length = min(arms[0] + arms[1], arms[2] + arms[3])
            tolerance = max(CROSS_END_MIN_MM * px_per_mm, CROSS_END_TOL * length)
            if abs(ends_a[0] - ends_b[0]) > tolerance or abs(ends_a[1] - ends_b[1]) > tolerance:
                continue
            if lines is not None:
                left = (min((a0, a1), key=lambda p: p[0]), min((b0, b1), key=lambda p: p[0]))
                right = (max((a0, a1), key=lambda p: p[0]), max((b0, b1), key=lambda p: p[0]))
                shares = sorted((_inked_share(lines, *left), _inked_share(lines, *right)))
                if shares[0] < CROSS_SIDE_INKED[0] or shares[1] < CROSS_SIDE_INKED[1]:
                    continue
            pairs.append((Segment(*a0, *a1), Segment(*b0, *b1)))
    return pairs


def _inked_share(lines: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    """Share of the points on the straight line from ``start`` to ``end`` that are line ink."""
    count = max(2, int(np.linalg.norm(end - start)))
    points = start + np.linspace(0, 1, count)[:, None] * (end - start)
    rows = np.clip(np.round(points[:, 1]).astype(int), 0, lines.shape[0] - 1)
    cols = np.clip(np.round(points[:, 0]).astype(int), 0, lines.shape[1] - 1)
    return float(lines[rows, cols].mean())


def _arms(line: Segment, point: np.ndarray, stops: np.ndarray, px_per_mm: float):
    """Both ends of the piece of ``line`` around ``point`` that no stop line crosses. Past the
    line's own end the walk goes on for up to twice HOUGH_GAP_MM to the stop line there (a dashed
    diagonal often ends short of its corner); without one the arm ends at the line's end."""
    direction = np.array([line.x1 - line.x0, line.y1 - line.y0]) / line.length
    start = np.array([line.x0, line.y0])
    at = float((point - start) @ direction)
    clear = 2.0 * px_per_mm  # a stop right at the crossing (a centre line) does not count
    reach = 2 * HOUGH_GAP_MM * px_per_mm
    ends = []
    for sign, limit in ((-1, at), (1, line.length - at)):
        distance = clear
        reached = limit
        while distance < limit + reach:
            x, y = point + sign * distance * direction
            r, c = int(round(y)), int(round(x))
            if not (0 <= r < stops.shape[0] and 0 <= c < stops.shape[1]):
                break
            if stops[r, c]:
                reached = distance
                break
            distance += 1.0
        ends.append(point + sign * reached * direction)
    return ends[0], ends[1]


@dataclass
class TextBlock:
    box: tuple[int, int, int, int]  # row0, col0, row1, col1 (view pixels, exclusive ends)
    char_height_px: float
    text: str = ''  # as read by the model

    @property
    def centre(self) -> tuple[float, float]:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2


@dataclass
class ViewInk:
    """The parsed ink of one view."""
    spec: ViewSpec
    origin: tuple[int, int]  # sheet row, column of the view's top left pixel
    ink: np.ndarray
    horizontal: np.ndarray  # long horizontal lines (dashed lines closed)
    vertical: np.ndarray
    text: np.ndarray  # text pixels
    blocks: list[TextBlock]
    crosses: list[tuple[Segment, Segment]]
    boundary: np.ndarray
    regions: np.ndarray  # region id per pixel (0 = boundary)
    line_width_px: float
    px_per_mm: float


def _line_width(lines: np.ndarray) -> float:
    """Median thickness of the horizontal lines (vertical run length through them)."""
    columns = lines[:, ::max(1, lines.shape[1] // 400)]
    padded = np.vstack([np.zeros((1, columns.shape[1]), bool), columns, np.zeros((1, columns.shape[1]), bool)])
    edges = np.diff(padded.astype(np.int8), axis=0)
    starts, ends = np.nonzero(edges == 1), np.nonzero(edges == -1)
    runs = ends[0] - starts[0] if len(starts[0]) == len(ends[0]) else np.array([2])
    return float(np.median(runs)) if len(runs) else 2.0


def small_components(ink: np.ndarray, px_per_mm: float, line_width: float) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Text pixels and dash pixels among the small ink components, and the text heights (px).

    A component no larger than a character is text, unless it is a straight stroke longer than
    DASH_MIN_MM: its pixels spread along one direction only (the spread across, a standard
    deviation, is at most DASH_SPREAD of the line width). That is a dash of a dashed line and
    stays line ink. A "T" or an "F" spreads in two directions and stays text."""
    from scipy import ndimage

    labels, count = ndimage.label(ink, structure=np.ones((3, 3)))
    if count == 0:
        return np.zeros(ink.shape, bool), np.zeros(ink.shape, bool), []
    boxes = ndimage.find_objects(labels)
    index = np.arange(1, count + 1)
    rows, cols = np.indices(ink.shape, sparse=True)
    area = ndimage.sum(ink, labels, index)
    mean_r = ndimage.sum(ink * rows, labels, index) / area
    mean_c = ndimage.sum(ink * cols, labels, index) / area
    var_r = ndimage.sum(ink * rows.astype(float) ** 2, labels, index) / area - mean_r ** 2
    var_c = ndimage.sum(ink * cols.astype(float) ** 2, labels, index) / area - mean_c ** 2
    cov = ndimage.sum(ink * (rows * cols).astype(float), labels, index) / area - mean_r * mean_c
    # Smaller eigenvalue of the 2 x 2 covariance: the spread across the stroke.
    half_trace = (var_r + var_c) / 2
    minor = half_trace - np.sqrt(np.maximum(((var_r - var_c) / 2) ** 2 + cov ** 2, 0))
    across = np.sqrt(np.maximum(minor, 0))
    char_min, char_max = CHAR_MIN_MM * px_per_mm, CHAR_MAX_MM * px_per_mm
    is_text = np.zeros(count + 1, bool)
    is_dash = np.zeros(count + 1, bool)
    heights = []
    for number, box in enumerate(boxes, start=1):
        height, width = box[0].stop - box[0].start, box[1].stop - box[1].start
        if height > char_max or width > CHAR_MAX_WIDTH_MM * px_per_mm:
            continue
        if math.hypot(height, width) >= DASH_MIN_MM * px_per_mm and across[number - 1] <= DASH_SPREAD * line_width:
            is_dash[number] = True
            continue
        if max(height, width) >= char_min / 3:
            is_text[number] = True
            if height >= char_min:
                heights.append(height)
    return is_text[labels], is_dash[labels], heights


def axis_line_masks(image: np.ndarray, px_per_mm: float, close_dashes: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Long solid horizontal and vertical lines (morphological opening).

    With ``close_dashes`` the ink is first closed along the line, which bridges dash gaps but
    also joins the letters of a word that touches a line into a bar; it is used only to find
    the rows of axis lines. Dashed boundaries are closed by the Hough step instead."""
    import cv2

    gap = max(3, int(round(DASH_GAP_MM * px_per_mm)))
    length = int(round(LINE_MIN_MM * px_per_mm))
    image = image.astype(np.uint8)
    masks = []
    for shape_close, shape_open in (((gap, 1), (length, 1)), ((1, gap), (1, length))):
        work = image
        if close_dashes:
            work = cv2.morphologyEx(work, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, shape_close))
        opened = cv2.morphologyEx(work, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, shape_open))
        masks.append(opened.astype(bool))
    return masks[0], masks[1]


def parse_view(ink: np.ndarray, spec: ViewSpec, origin: tuple[int, int], px_per_mm: float,
               centre_row: float | None = None) -> ViewInk:
    """Lines, text blocks, cross marks and closed regions of one view. ``centre_row`` (a plan's
    centre line) is not a boundary: a tank across the centre line stays one region (a region with
    a port and a starboard label is split later), and a cross mark's arms run across it."""
    import cv2

    gap = max(3, int(round(HOUGH_GAP_MM * px_per_mm)))
    join_gap = int(round(JOIN_GAP_MM * px_per_mm))
    # Pass 1: text out of the way, then the lines.
    horizontal, vertical = axis_line_masks(ink, px_per_mm)
    line_width = _line_width(horizontal)
    text, _, _ = small_components(ink & ~horizontal & ~vertical, px_per_mm, line_width)
    lines_only = ink & ~text
    horizontal, vertical = axis_line_masks(lines_only, px_per_mm)
    axis_lines = horizontal | vertical
    # Straight lines in the rest of the ink (diagonals, dashed diagonals, straight parts of curves).
    rest = (lines_only & ~cv2.dilate(axis_lines.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool))
    hough_min = int(round(HOUGH_MIN_MM * px_per_mm))
    found = cv2.HoughLinesP(rest.astype(np.uint8) * 255, 1, np.pi / 720, threshold=max(10, hough_min // 2),
                            minLineLength=hough_min, maxLineGap=gap)
    pieces = [Segment(*map(float, line)) for line in found[:, 0]] if found is not None else []
    # Dashed lines joined over dash gaps (drawn solid below), and long lines joined over labels
    # (for the cross marks only).
    dashed = merge_collinear(pieces, MERGE_ANGLE_DEG, max(3.0, 1.5 * line_width), gap)
    dashed = [s for s in dashed if s.length >= hough_min]
    long_lines = merge_collinear(dashed, MERGE_ANGLE_DEG, max(3.0, 1.5 * line_width), join_gap)
    stops = axis_lines.copy()
    if centre_row is not None:
        _clear_centre_line(stops, vertical, centre_row, line_width)
    side_ink = cv2.dilate(lines_only.astype(np.uint8), np.ones((2 * int(line_width) + 3,) * 2, np.uint8)).astype(bool)
    crosses = cross_marks(long_lines, stops, px_per_mm, side_ink)
    thickness = int(round(line_width)) + 2
    # Pass 2: with the cross marks erased, characters they touched become free.
    erased = ink.astype(np.uint8)
    for pair in crosses:
        for segment in pair:
            _erase_inside(erased, segment, thickness + 2)
    erased = erased.astype(bool) | axis_lines
    text, dashes, heights = small_components(erased & ~axis_lines, px_per_mm, line_width)
    char_height = float(np.median(heights)) if heights else 2.5 * px_per_mm
    # Blocks grow from letters only: straight strokes (dashes, and letters such as "l") stay
    # line ink, so a dashed line cannot chain labels into one block.
    blocks = text_blocks(text, char_height)
    # Boundary ink: everything but text and cross marks; dashed straight lines drawn solid so
    # that dashed boundaries close, then the cross marks erased again (their dashed pieces too).
    boundary = (erased & ~text).astype(np.uint8)
    for segment in dashed:
        cv2.line(boundary, (int(round(segment.x0)), int(round(segment.y0))),
                 (int(round(segment.x1)), int(round(segment.y1))), 1, max(1, int(round(line_width))))
    for pair in crosses:
        for segment in pair:
            _erase_inside(boundary, segment, thickness + 2)
    boundary = boundary.astype(bool) | axis_lines
    if centre_row is not None:
        _clear_centre_line(boundary, vertical, centre_row, line_width)
    regions = cv2.connectedComponents((~boundary).astype(np.uint8), connectivity=4)[1]
    return ViewInk(spec, origin, ink, horizontal, vertical, text, blocks, crosses, boundary, regions, line_width,
                   px_per_mm)


def _clear_centre_line(mask: np.ndarray, vertical: np.ndarray, row: float, line_width: float) -> None:
    """Remove the horizontal line at ``row`` from ``mask``, keeping vertical lines across it."""
    half = int(math.ceil(line_width)) + 1
    r0, r1 = max(0, int(round(row)) - half), int(round(row)) + half + 1
    mask[r0:r1] &= vertical[r0:r1]


def _erase_inside(image: np.ndarray, segment: Segment, thickness: int) -> None:
    """Erase a line but keep its ends (a corner on a curved side must stay closed)."""
    import cv2

    keep = 2 * thickness
    if segment.length <= 2 * keep:
        return
    direction = np.array([segment.x1 - segment.x0, segment.y1 - segment.y0]) / segment.length
    start = np.array([segment.x0, segment.y0]) + keep * direction
    end = np.array([segment.x1, segment.y1]) - keep * direction
    cv2.line(image, tuple(int(round(v)) for v in start), tuple(int(round(v)) for v in end), 0, thickness)


def text_blocks(text: np.ndarray, char_height: float) -> list[TextBlock]:
    """Group text pixels into blocks: the words of one text line. The lines of one label are
    joined later, per region (``reading_order``)."""
    import cv2
    from scipy import ndimage

    # Join characters and words of a line (gaps below about one character height); a small
    # vertical reach joins dots and accents to their letters, not lines to each other.
    kernel = np.ones((max(1, int(0.2 * char_height)), max(1, int(1.0 * char_height))), np.uint8)
    grown = cv2.dilate(text.astype(np.uint8), kernel)
    labels, _ = ndimage.label(grown)
    blocks = []
    for box in ndimage.find_objects(labels):
        inside = text[box]
        if not inside.any():
            continue
        rows, cols = np.nonzero(inside)
        r0, c0 = box[0].start + rows.min(), box[1].start + cols.min()
        r1, c1 = box[0].start + rows.max() + 1, box[1].start + cols.max() + 1
        if r1 - r0 < 0.6 * char_height and c1 - c0 < 0.6 * char_height:
            continue  # a dot or a stray mark
        blocks.append(TextBlock((int(r0), int(c0), int(r1), int(c1)), char_height))
    return blocks


# ---------------------------------------------------------------------------------------------
# Axes: frame ticks and scale bars


@dataclass
class Tick:
    column: float
    ordinal: int  # tick count from the first tick (missing ticks are counted)
    label: str = ''


@dataclass
class Axis:
    row: float  # view row of the axis line
    ticks: list[Tick]
    metres_per_ordinal: float
    ordinal_of_zero: float  # tick ordinal of frame 0 (or of value 0 on a scale bar)
    source: str  # 'read' when frame numbers were read, else 'guessed'
    evidence: str
    label_rows: tuple[int, int] | None = None  # view rows of the frame-number labels

    @property
    def px_per_m(self) -> float:
        columns = np.array([t.column for t in self.ticks])
        ordinals = np.array([t.ordinal for t in self.ticks])
        slope = np.polyfit(ordinals, columns, 1)[0]
        return abs(slope) / self.metres_per_ordinal

    def x_m(self, columns) -> np.ndarray:
        """Ship x (m) of view columns: piecewise linear through the ticks, extended at the ends."""
        cols = np.array([t.column for t in self.ticks], float)
        xs = (np.array([t.ordinal for t in self.ticks], float) - self.ordinal_of_zero) * self.metres_per_ordinal
        order = np.argsort(cols)
        cols, xs = cols[order], xs[order]
        columns = np.asarray(columns, float)
        inside = np.interp(columns, cols, xs)
        slope_low = (xs[1] - xs[0]) / (cols[1] - cols[0])
        slope_high = (xs[-1] - xs[-2]) / (cols[-1] - cols[-2])
        inside = np.where(columns < cols[0], xs[0] + (columns - cols[0]) * slope_low, inside)
        return np.where(columns > cols[-1], xs[-1] + (columns - cols[-1]) * slope_high, inside)


def axis_rows(view: ViewInk) -> list[float]:
    """Rows of long horizontal lines, solid or dashed (at least AXIS_COVER of the view width)."""
    horizontal, _ = axis_line_masks(view.ink & ~view.text, view.px_per_mm, close_dashes=True)
    cover = horizontal.sum(axis=1) / horizontal.shape[1]
    rows = np.flatnonzero(cover >= AXIS_COVER)
    bands = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1) if len(rows) else []
    return [float(band.mean()) for band in bands if len(band)]


def find_ticks(ink: np.ndarray, row: float, line_width: float, px_per_mm: float) -> list[float]:
    """Columns of short vertical strokes across the line at ``row``."""
    r = int(round(row))
    half = int(math.ceil(line_width / 2)) + 1
    reach = int(TICK_MAX_MM * px_per_mm)
    top, bottom = max(0, r - reach), min(ink.shape[0], r + reach + 1)
    strip = ink[top:bottom]
    centre = r - top
    lengths = np.zeros(ink.shape[1], int)
    up = np.zeros(ink.shape[1], int)
    down = np.zeros(ink.shape[1], int)
    # Ink run lengths up and down from just outside the line.
    alive = strip[centre - half - 1] if centre - half - 1 >= 0 else np.zeros(ink.shape[1], bool)
    for offset in range(centre - half - 1, -1, -1):
        alive = alive & strip[offset]
        up += alive
    alive = strip[centre + half + 1] if centre + half + 1 < strip.shape[0] else np.zeros(ink.shape[1], bool)
    for offset in range(centre + half + 1, strip.shape[0]):
        alive = alive & strip[offset]
        down += alive
    lengths = up + down
    is_tick = (lengths >= TICK_MIN_MM * px_per_mm) & (up < reach - 1) & (down < reach - 1) & (up + down > 0)
    columns = np.flatnonzero(is_tick)
    if not len(columns):
        return []
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > 1) + 1)
    max_width = 3 * line_width + 2
    return [float(g.mean()) for g in groups if len(g) <= max_width]


def regular_ticks(columns: list[float]) -> tuple[list[Tick], float]:
    """Ticks with ordinals from their spacing; the longest run of regular spacing is kept.

    Spacing is the median gap; a gap of about n spacings counts n - 1 missing ticks (a tank
    boundary across the axis hides a tick). Returns the ticks and the spacing (px)."""
    if len(columns) < 4:
        return [], 0.0
    columns = sorted(columns)
    gaps = np.diff(columns)
    spacing = float(np.median(gaps))
    runs, current = [], [Tick(columns[0], 0)]
    for column in columns[1:]:
        steps = (column - current[-1].column) / spacing
        if round(steps) > MAX_MISSING_TICKS + 1:
            runs.append(current)  # a long gap: the axis is interrupted
            current = [Tick(column, 0)]
            continue
        if steps < 0.6 or abs(steps - round(steps)) > 0.2:
            continue  # a mark between two ticks (a crossing line or a label stroke)
        current.append(Tick(column, current[-1].ordinal + int(round(steps))))
    runs.append(current)
    best = max(runs, key=len)
    return best, spacing


def axis_label_crops(view: ViewInk, row: float, ticks: list[Tick], spacing: float,
                     px_per_mm: float) -> tuple[list[np.ndarray], tuple[int, int]]:
    """One crop per tick of the row of labels below (or above, whichever holds more text) the
    axis. The label row is the text row band with the most ink in AXIS_LABEL_BAND_MM; the tick
    ends next to the line are a separate, thinner band and are left out."""
    near, far = (int(v * px_per_mm) for v in AXIS_LABEL_BAND_MM)
    r = int(round(row))
    below = view.text[r + near:r + far]
    above = view.text[max(0, r - far):max(0, r - near)]
    side = 1 if below.sum() >= above.sum() else -1
    band = (r + near, r + far) if side > 0 else (max(0, r - far), max(0, r - near))
    lo, hi = min(t.column for t in ticks), max(t.column for t in ticks)
    profile = view.text[band[0]:band[1], max(0, int(lo - spacing)):int(hi + spacing)].sum(axis=1)
    inked = np.flatnonzero(profile > 0)
    if len(inked):
        runs = np.split(inked, np.flatnonzero(np.diff(inked) > 2) + 1)
        best = max(runs, key=lambda run: profile[run].sum())
        band = (band[0] + int(best[0]), band[0] + int(best[-1]) + 1)
    half = int(spacing * 0.5)
    crops = []
    for tick in ticks:
        c = int(round(tick.column))
        crops.append(view.ink[band[0]:band[1], max(0, c - half):c + half])
    return crops, band


def parse_axis_label(text: str) -> tuple[str, int | None]:
    """('number', value) or ('letter', None) or ('', None)."""
    cleaned = text.strip().strip('.').replace(' ', '')
    if re.fullmatch(r'-?\d{1,3}', cleaned):
        return 'number', int(cleaned)
    if re.fullmatch(r'[A-Za-z]', cleaned):
        return 'letter', None
    return '', None


def fit_frame_axis(row: float, ticks: list[Tick], frame_spacing_m: float) -> Axis | None:
    """Frame 0 and frames per tick from the read numbers.

    For each numbered tick, ordinal - frames / frames_per_tick names the ordinal of frame 0.
    Inserted frames (letters after a frame number, as in a lengthened ship) shift the numbers
    after them; frame 0 is the value that the lowest frame numbers agree on."""
    numbered = [(t.ordinal, value) for t in ticks for kind, value in [parse_axis_label(t.label)]
                if kind == 'number']
    if len(numbered) < 2:
        return None
    numbered.sort(key=lambda item: item[1])
    ratios = [round((b[1] - a[1]) / (b[0] - a[0])) for a, b in zip(numbered, numbered[1:])
              if b[0] != a[0] and (b[1] - a[1]) / (b[0] - a[0]) >= 0.5]
    frames_per_tick = statistics.mode(ratios) if ratios else 1
    frames_per_tick = max(1, frames_per_tick)
    zeros = [ordinal - value / frames_per_tick for ordinal, value in numbered]
    # Frame 0 from the lowest numbers that at least one other number confirms.
    for index, zero in enumerate(zeros):
        agreeing = [z for z in zeros if abs(z - zero) < 0.25]
        if len(agreeing) >= 2:
            zero_ordinal = statistics.median(agreeing)
            break
    else:
        zero_ordinal = zeros[0]
    evidence = (f'{len(ticks)} ticks, {len(numbered)} numbers read; {frames_per_tick} frame(s) per tick; '
                f'frame spacing {frame_spacing_m} m (read)')
    return Axis(row, ticks, frame_spacing_m * frames_per_tick, zero_ordinal, 'read', evidence)


# A numbered tick is an outlier (a misread number) when it is further than this fraction of the
# value spacing between neighbouring numbers from the robust line: a quarter keeps every honest
# tick (reading noise is far below one spacing) and rejects any misread number, which is off by
# at least one spacing.
SCALE_BAR_OUTLIER_SPACINGS = 0.25


def fit_scale_bar(row: float, ticks: list[Tick], unit_m: float) -> Axis | None:
    """A scale bar: value = a + b * column from the numbered ticks.

    The line is fitted robustly (median pairwise slope), ticks whose number does not fit the line
    are dropped as misreads, and the axis is built from the remaining ticks only, so one wrong
    number can neither tilt the scale nor make x non-monotonic."""
    numbered = [(t.column, value) for t in ticks for kind, value in [parse_axis_label(t.label)]
                if kind == 'number']
    if len(numbered) < 2:
        return None
    numbered.sort()
    columns, values = np.array(numbered, float).T
    if np.ptp(columns) == 0:
        return None
    pairs = np.triu_indices(len(columns), k=1)
    separation = columns[pairs[1]] - columns[pairs[0]]
    usable = separation > 0
    slope = float(np.median(((values[pairs[1]] - values[pairs[0]])[usable]) / separation[usable]))
    intercept = float(np.median(values - slope * columns))
    spacing = float(np.median(np.abs(np.diff(values)))) or 1.0
    keep = np.abs(values - (intercept + slope * columns)) <= SCALE_BAR_OUTLIER_SPACINGS * spacing
    if keep.sum() < 2:
        return None
    columns, values = columns[keep], values[keep]
    # Store the fit as ticks one unit apart in value (ordinal = value).
    rebuilt = [Tick(float(c), int(v)) for c, v in zip(columns, values)]
    return Axis(row, rebuilt, unit_m, 0.0, 'read',
                f'scale bar: {len(columns)} of {len(numbered)} numbers fit, {1 / abs(slope):.3f} px per unit '
                f'(unit {unit_m} m)')


# ---------------------------------------------------------------------------------------------
# Model questions: code cuts the crops, the model returns their text only

Asker = Callable[[np.ndarray, str], dict]


def mosaic(crops: list[np.ndarray], scale: float) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """A white image with the crops (ink black) in numbered cells, row by row."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=22)
    tag_width, pad = 56, 14
    placed, x, y, row_height = [], pad, pad, 0
    images = []
    for crop in crops:
        image = Image.fromarray(np.where(crop, 0, 255).astype(np.uint8))
        if scale != 1:
            image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.LANCZOS)
        images.append(image)
    for image in images:
        width = tag_width + image.width + pad
        if x + width > QUESTION_WIDTH_PX and x > pad:
            x, y, row_height = pad, y + row_height + pad, 0
        placed.append((x, y, image))
        x += width
        row_height = max(row_height, image.height, 26)
    height = y + row_height + pad
    sheet = Image.new('L', (QUESTION_WIDTH_PX, height), 255)
    draw = ImageDraw.Draw(sheet)
    cells = []
    for number, (cx, cy, image) in enumerate(placed, start=1):
        draw.text((cx, cy), f'{number}:', fill=0, font=font)
        sheet.paste(image, (cx + tag_width, cy))
        left = cx + tag_width
        draw.rectangle((left - 3, cy - 3, left + image.width + 2, cy + image.height + 2), outline=150)
        cells.append((cx, cy, image.width, image.height))
    return np.asarray(sheet), cells


def read_crops(crops: list[np.ndarray], char_height_px: float, prompt: str, ask: Asker) -> list[str]:
    """Text of each crop, read by the model in pages of at most QUESTION_MAX_HEIGHT_PX."""
    if not crops:
        return []
    scale = min(3.0, max(0.5, QUESTION_TEXT_PX / max(char_height_px, 1.0)))
    answers: list[str] = []
    start = 0
    while start < len(crops):
        end = len(crops)
        while True:
            image, _ = mosaic(crops[start:end], scale)
            if image.shape[0] <= QUESTION_MAX_HEIGHT_PX or end - start == 1:
                break
            end = start + max(1, (end - start) * QUESTION_MAX_HEIGHT_PX // image.shape[0] - 1)
        reply = ask(image, prompt.format(count=end - start))
        answers.extend(str(reply.get(str(number), '') or '') for number in range(1, end - start + 1))
        start = end
    return answers


AXIS_PROMPT = (
    'The image has {count} numbered cells. Each cell is a crop of a ship drawing under one tick of '
    'a frame axis or a scale bar, and may show a frame number, a letter or a number of the scale '
    '(sometimes with parts of the neighbouring labels at the cell edges). For each cell give the one '
    'label nearest the cell centre exactly as printed, or "" if the cell has no complete label. '
    'Reply with one JSON object: {{"1": "...", "2": "...", ...}}.')
LABEL_PROMPT = (
    'The image has {count} numbered cells. Each cell is a crop of the text of one label on a ship '
    'tank or capacity plan (tank names and numbers, room names, deck names). Transcribe the text of '
    'each cell exactly as printed, lines joined with one space, or "" if it is not text. Do not guess '
    'text that is not visible. Reply with one JSON object: {{"1": "...", "2": "...", ...}}.')
SCHEDULE_PROMPT = (
    'The image is a tank table or schedule of rooms from a ship drawing. List every row that names a '
    'tank or compartment. For each row give: "key" (the tank number or item number as printed in the '
    'first column, e.g. "No 3 sb" or "15"), "name" (the name text), and "content" (the content of the '
    'tank in plain words, from the section header above the row or from the header of the column in '
    'which the row has its entries, e.g. "fuel oil", "water ballast", "technical water", "fresh '
    'water", "misc"; "" if the table does not say). Do not report any volumes, masses, capacities or '
    'frame numbers. Reply with one JSON object: {{"rows": [{{"key": "...", "name": "...", '
    '"content": "..."}}, ...]}}.')


def claude_asker(cache_dir: Path, model: str = 'claude-sonnet-5-5', call=None) -> Asker:
    """An ``Asker`` through the Claude Code CLI on the subscription (no API key), with a cache
    of answers per image and prompt in ``cache_dir`` (git-ignored) so a code change can be
    replayed without new model calls. ``call`` is a ``holdout_value.claude_call``-style function."""
    import base64

    from PIL import Image

    cache_dir.mkdir(parents=True, exist_ok=True)
    if call is None:
        from benchmarks.thayer.holdout_value import claude_call
        call = claude_call(model)

    def ask(image: np.ndarray, prompt: str) -> dict:
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, format='PNG')
        data = buffer.getvalue()
        key = hashlib.sha256(data + prompt.encode() + model.encode()).hexdigest()[:24]
        cached = cache_dir / f'{key}.json'
        if cached.exists():
            return json.loads(cached.read_text())['answer']
        (cache_dir / f'{key}.png').write_bytes(data)
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(data).decode()}}]}]
        answer, completed = {}, False
        for _ in range(2):
            text, receipt = call(messages, cache_dir / 'receipts')
            if receipt.get('state') != 'completed':
                continue  # timeout, rate limit or error: the text is not an answer
            completed = True
            answer = _json_object(text)
            if answer is not None:
                break
        if not completed:
            # Never cache a failed call: a replay would return {} as if the model had said so.
            raise RuntimeError(f'model call failed twice (receipts in {cache_dir / "receipts"})')
        answer = answer or {}
        cached.write_text(json.dumps({'prompt': prompt, 'model': model, 'answer': answer}, indent=1))
        return answer

    return ask


def _json_object(text: str) -> dict | None:
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------------------------------
# Labels, content and schedule


DUAL_USE = 'fuel oil or water ballast'


def content_of(*texts: str) -> str | None:
    """Content group from label or schedule words (first word match in CONTENT_WORDS, on word boundaries). A tank
    named for fuel oil and for ballast ("F.O. OR WATER BALLAST TANK") is dual-use."""
    for text in texts:
        lower = (text or '').lower()
        matched = [group for pattern, group in CONTENT_PATTERNS if pattern.search(lower)]
        if {'fuel oil', 'water ballast'} <= set(matched):
            return DUAL_USE
        if matched:
            return matched[0]
    return None


def tank_key(text: str) -> str | None:
    """Normalised tank number of a label: 'no 3 sb', 'no 11p' -> 'no 11 p', 'no. 2' -> 'no 2'.
    When a label repeats its number, the form with a side wins ("No 3 No 3 p" is "no 3 p")."""
    keys = []
    pattern = r'\bno\.?\s*(\d{1,2})\s*(p\s*[/&]\s*s|sb|ps|p|s|port|stbd)?\b'
    for match in re.finditer(pattern, (text or '').lower()):
        written = match.group(2) or ''
        side = '' if BOTH_SIDES.fullmatch(written) else {'port': 'p', 'ps': 'p', 'stbd': 'sb', 's': 'sb'}.get(
            written, written)
        keys.append(f'no {match.group(1)} {side}'.strip())
    if not keys:
        return None
    return next((key for key in keys if key.count(' ') == 2), keys[0])


def words(text: str) -> set[str]:
    tokens = re.findall(r'[a-z]+', (text or '').lower())
    return {t for t in tokens if t not in STOP_WORDS and len(t) > 1}


def is_tank_label(text: str) -> bool:
    """A label that names a tank or a compartment: a tank word ("tank", "peak", "D.B.", "hold")
    or a liquid content word, and no feature word (a hatch, a girder or a trunk is never a tank,
    even with a number: "NO.1 HATCH"). A tank number alone does not make a tank; a schedule row
    of that number may (``resolve_items``, ``schedule_row_for``)."""
    lower = (text or '').lower()
    if FEATURE_WORDS.search(lower):
        return False
    return bool(TANK_WORDS.search(lower)) or content_of(text) not in (None, 'dry')


def label_kind(text: str) -> str | None:
    """'deep tank', 'peak', 'settling' or 'double bottom' from the label words, else None."""
    lower = (text or '').lower()
    return next((kind for kind, pattern in KIND_PATTERNS if pattern.search(lower)), None)


def resolve_items(text: str, rows: list[dict]) -> str:
    """A label with schedule item numbers (a circled "5" that the sheet's schedule names
    "RESERVE FEED WATER TANK NO.4P") with each item number replaced by "#5 <name of row 5>".
    When an item names a tank, the label is that tank only (the region's other words are notes
    such as "GIRDER OVER"). ``rows`` are the schedule rows of the same sheet; a number without a
    row stays as it is."""
    names = {str(row.get('key', '')).strip(): row.get('name', '') for row in rows}
    if not names:
        return text

    def is_item(match: re.Match) -> bool:
        """A number is a schedule item when a row has it and it is not a stray number of a label
        that already names a tank ("NO.3 FUEL OIL TANK 5"); a circled "(5)" is always an item."""
        if not names.get(match.group(1)):
            return False
        if match.group(0).startswith('(') and match.group(0).endswith(')'):
            return True
        rest = (text or '')[:match.start()] + ' ' + (text or '')[match.end():]
        return not (is_tank_label(rest) or tank_key(rest))

    items = [match.group(1) for match in ITEM_TOKEN.finditer(text or '') if is_item(match)]
    tank_items = list(dict.fromkeys(item for item in items if is_tank_label(names[item])))
    if tank_items:
        # The tank the item names; other words in the region are notes ("GIRDER OVER", "VOID").
        return ' '.join(f'#{item} {names[item]}' for item in tank_items)

    def name(match: re.Match) -> str:
        item = match.group(1)
        return f'#{item} {names[item]}' if is_item(match) else match.group(0)

    return ' '.join(ITEM_TOKEN.sub(name, text or '').split())


# ---------------------------------------------------------------------------------------------
# Sheet reading


@dataclass
class ReadView:
    ink: ViewInk
    axis: Axis | None
    centre_row: float | None = None  # plans: centre line
    baseline_row: float | None = None  # profiles
    notes: list[str] = field(default_factory=list)
    name: str = ''  # the view's name in the reading record (with the sheet prefix of a case)

    @property
    def record_name(self) -> str:
        return self.name or self.ink.spec.name

    @property
    def px_per_m(self) -> float:
        return self.axis.px_per_m


@dataclass
class PlanTank:
    view: str
    label: str
    key: str | None
    region: int
    columns: dict[float, tuple[float, float]]  # ship x (m) -> (y min, y max) (m)
    x_range: tuple[float, float]
    side: int | None = None
    role: str | None = None  # the plan role of its view; None for a tank found in the profile

    @property
    def kind(self) -> str | None:
        """Kind from the label words; a tank of a double-bottom plan without one is a double
        bottom; else None (not known)."""
        return label_kind(self.label) or ('double bottom' if self.role == 'double_bottom' else None)


def read_view(ink: np.ndarray, spec: ViewSpec, px_per_mm: float, sheet: 'SheetSpec', ask: Asker,
              bar_axis: Axis | None) -> ReadView:
    height, width = ink.shape
    x0, y0, x1, y1 = spec.window
    r0, c0, r1, c1 = int(y0 * height), int(x0 * width), int(y1 * height), int(x1 * width)
    view_ink = ink[r0:r1, c0:c1]
    parsed = parse_view(view_ink, spec, (r0, c0), px_per_mm)
    view = ReadView(parsed, None)
    rows = axis_rows(parsed)
    best: tuple[list[Tick], float, float] | None = None
    for row in rows:
        ticks, spacing = regular_ticks(find_ticks(view_ink, row, parsed.line_width_px, px_per_mm))
        if len(ticks) >= 5 and (best is None or len(ticks) > len(best[0])):
            best = (ticks, spacing, row)
    if sheet.frame_spacing_m and best:
        ticks, spacing, row = best
        crops, label_rows = axis_label_crops(parsed, row, ticks, spacing, px_per_mm)
        has_text = [i for i, crop in enumerate(crops) if crop.any()]
        texts = read_crops([crops[i] for i in has_text], _char_px(parsed), AXIS_PROMPT, ask)
        for i, text in zip(has_text, texts):
            ticks[i].label = text
        view.axis = fit_frame_axis(row, ticks, sheet.frame_spacing_m)
        if view.axis is not None:
            view.axis.label_rows = label_rows
        if view.axis is None:
            view.notes.append('frame axis found but fewer than two frame numbers read')
    if view.axis is None and bar_axis is not None:
        # Scale only: x from the sheet's left edge, the same origin for every view (the views of
        # a capacity plan are drawn one above the other); plans are then aligned to the profile
        # (``align_to_profile``). The x origin is not a ship datum (guessed).
        scale = bar_axis.px_per_m
        view.axis = Axis(best[2] if best else float(height), [Tick(-c0, 0), Tick(-c0 + scale, 1)], 1.0, 0.0,
                         'guessed', 'scale bar scale; x from the sheet edge (guessed origin)')
    if spec.kind == 'plan':
        # The centre line is the frame axis (plans draw it on the centre line), else the
        # longest horizontal line nearest the middle of the view.
        symmetry = symmetry_row(parsed)
        near = [r for r in rows if symmetry is not None and abs(r - symmetry) <= CENTRE_SNAP_MM * px_per_mm]
        if best:
            view.centre_row = best[2]
        elif near:
            view.centre_row = min(near, key=lambda r: abs(r - symmetry))
        elif rows:
            middle = parsed.ink.shape[0] / 2
            view.centre_row = min(rows, key=lambda r: abs(r - middle))
        else:
            # A dash-dot centre line that is not found as a line: the outline's middle row.
            view.centre_row = symmetry
            if symmetry is not None:
                view.notes.append('centre line taken as the middle of the plan outline (symmetry)')
        if view.centre_row is not None:
            view.ink = parse_view(view_ink, spec, (r0, c0), px_per_mm, view.centre_row)
    return view


def symmetry_row(view: ViewInk) -> float | None:
    """Middle row of a plan's outline: the median, over the columns where the line ink spans at
    least a third of the view height, of the mean of the first and last inked rows."""
    lines = view.boundary
    inked = lines.any(axis=0)
    columns = np.flatnonzero(inked)[::max(1, lines.shape[1] // 400)]
    middles = []
    for column in columns:
        rows = np.flatnonzero(lines[:, column])
        if rows[-1] - rows[0] >= lines.shape[0] / 3:
            middles.append((rows[0] + rows[-1]) / 2)
    return float(np.median(middles)) if middles else None


def _char_px(view: ViewInk) -> float:
    heights = [b.char_height_px for b in view.blocks]
    return heights[0] if heights else 20.0


def read_labels(view: ReadView, ask: Asker, schedule: list[dict] = ()) -> tuple[list['RegionLabel'], list[TextBlock]]:
    """Labels of the view's regions, and the text blocks outside any region (frame-axis labels
    left out). Code groups the blocks of a region (each side of a plan's centre line apart) and
    cuts one crop around them; the model reads each crop. Item numbers of the sheet's schedule
    are replaced by their row names (``resolve_items``) before a region's sides are resolved."""
    parsed = view.ink
    blocks = parsed.blocks
    if view.axis is not None and view.axis.label_rows is not None:
        # Frame numbers (read with the axis) and the tick marks between them and the line.
        top = min(view.axis.label_rows[0], view.axis.row)
        bottom = max(view.axis.label_rows[1], view.axis.row)
        blocks = [b for b in blocks if not top <= b.centre[0] <= bottom]
    groups, free = label_groups(parsed, blocks, view.centre_row)
    # One crop per cluster of nearby blocks: a region's label and a note far from it (a circled
    # item number and "GIRDER OVER" in one leaky region) are read apart, then joined.
    clusters = [cluster_blocks(group.blocks) for group in groups]
    crops = [label_crop(parsed, cluster) for parts in clusters for cluster in parts]
    crops += [label_crop(parsed, [b]) for b in free]
    texts = iter(read_crops(crops, _char_px(parsed), LABEL_PROMPT, ask))
    for group, parts in zip(groups, clusters):
        group.text = ' '.join(' '.join(next(texts).split()) for _ in parts).strip()
        group.text = ' '.join(group.text.split())
    for block in free:
        block.text = ' '.join(next(texts).split())
    for group in groups:
        group.text = normalise_label(resolve_items(group.text, list(schedule)))
    return resolve_sides(groups), [b for b in free if b.text]


def normalise_label(text: str) -> str:
    """A label as read, with run-together words of a capacity plan split ("DEEPTANK")."""
    return re.sub(r'\b(deep)(tanks?)\b', r'\1 \2', text, flags=re.IGNORECASE)


def cluster_blocks(blocks: list[TextBlock]) -> list[list[TextBlock]]:
    """Blocks in clusters: blocks whose boxes, grown by CLUSTER_CHARS character heights, touch
    are one cluster (the lines of one label). Clusters in reading order (top, then left)."""
    reach = CLUSTER_CHARS * blocks[0].char_height_px
    parent = list(range(len(blocks)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(blocks):
        for j in range(i + 1, len(blocks)):
            b = blocks[j]
            if (a.box[0] - reach <= b.box[2] and b.box[0] - reach <= a.box[2]
                    and a.box[1] - reach <= b.box[3] and b.box[1] - reach <= a.box[3]):
                parent[root(i)] = root(j)
    clusters: dict[int, list[TextBlock]] = {}
    for i, block in enumerate(blocks):
        clusters.setdefault(root(i), []).append(block)
    return sorted(clusters.values(), key=lambda c: (min(b.box[0] for b in c), min(b.box[1] for b in c)))


def label_crop(view: ViewInk, blocks: list[TextBlock]) -> np.ndarray:
    """The ink around text blocks, a little larger than their union: the model reads the label
    as printed, with any line through it, and letters that code took for line ink are kept."""
    height = blocks[0].char_height_px
    rows, cols = int(LABEL_MARGIN[0] * height), int(LABEL_MARGIN[1] * height)
    r0, c0 = min(b.box[0] for b in blocks), min(b.box[1] for b in blocks)
    r1, c1 = max(b.box[2] for b in blocks), max(b.box[3] for b in blocks)
    return view.ink[max(0, r0 - rows):r1 + rows, max(0, c0 - cols):c1 + cols]


def region_at(view: ViewInk, block: TextBlock) -> int:
    """The region under a label: the region at its centre, else the most common region id inside
    its box (the centre may fall on a letter or a line). A label in a small box can reach out
    of it; its centre stays inside."""
    r0, c0, r1, c1 = block.box
    centre = view.regions[int(block.centre[0]), int(block.centre[1])]
    if centre:
        return int(centre)
    ids = view.regions[r0:r1, c0:c1]
    ids = ids[ids > 0]
    if not len(ids):
        return 0
    values, counts = np.unique(ids, return_counts=True)
    return int(values[np.argmax(counts)])


def outside_enclosure(view: ViewInk, block: TextBlock, region: int, boxes: list) -> int:
    """The region around a label's enclosure: an item number drawn in a circle or a small box
    (no larger than ENCLOSURE_CHARS character heights beyond the text) labels the region the
    circle sits in, not the inside of the circle. Returns ``region`` for any other label."""
    if not region or boxes[region - 1] is None:
        return region
    rows, cols = boxes[region - 1]
    reach = ENCLOSURE_CHARS * block.char_height_px
    text_height, text_width = block.box[2] - block.box[0], block.box[3] - block.box[1]
    if rows.stop - rows.start > text_height + reach or cols.stop - cols.start > text_width + reach:
        return region
    step = int(2 * view.line_width_px) + 3  # across the enclosing line
    r0, c0 = max(0, rows.start - step), max(0, cols.start - step)
    r1, c1 = min(view.regions.shape[0] - 1, rows.stop + step), min(view.regions.shape[1] - 1, cols.stop + step)
    ring = np.concatenate([view.regions[r0, c0:c1 + 1], view.regions[r1, c0:c1 + 1],
                           view.regions[r0:r1 + 1, c0], view.regions[r0:r1 + 1, c1]])
    ring = ring[(ring > 0) & (ring != region)]
    if not len(ring):
        return region
    values, counts = np.unique(ring, return_counts=True)
    return int(values[np.argmax(counts)])


def border_regions(regions: np.ndarray) -> set[int]:
    return set(np.unique(np.concatenate([regions[0], regions[-1], regions[:, 0], regions[:, -1]]))) - {0}


@dataclass
class RegionLabel:
    region: int
    side: int | None  # +1 port half, -1 starboard half, None the whole region
    blocks: list[TextBlock]
    text: str = ''  # as read by the model


def label_groups(view: ViewInk, blocks: list[TextBlock], centre_row: float | None
                 ) -> tuple[list[RegionLabel], list[TextBlock]]:
    """Text blocks grouped by the closed region under them (and, in a plan, by the side of the
    centre line), and the blocks outside any closed region. Regions open to the view edge or
    larger than MAX_REGION_SHARE of the view are not closed (the linework leaks into a room)."""
    from scipy import ndimage

    border = border_regions(view.regions)
    sizes = np.bincount(view.regions.ravel())
    limit = MAX_REGION_SHARE * view.regions.size
    boxes = ndimage.find_objects(view.regions)
    grouped: dict[tuple[int, int | None], list[TextBlock]] = {}
    free = []
    for block in blocks:
        region = outside_enclosure(view, block, region_at(view, block), boxes)
        if region and region not in border and sizes[region] <= limit:
            side = None if centre_row is None else (1 if block.centre[0] < centre_row else -1)
            grouped.setdefault((region, side), []).append(block)
        else:
            free.append(block)
    return [RegionLabel(region, side, members) for (region, side), members in grouped.items()], free


def resolve_sides(groups: list[RegionLabel]) -> list[RegionLabel]:
    """A plan region with a whole tank label on each side of the centre line (a tank number, or
    a content word other than a dry space) holds a port and a starboard tank; otherwise its two
    sides are one label, port text first ("CARGO" over "TANK NO. 9" is one tank)."""
    by_region: dict[int, list[RegionLabel]] = {}
    for group in groups:
        by_region.setdefault(group.region, []).append(group)
    resolved = []
    for region, parts in by_region.items():
        parts.sort(key=lambda g: -(g.side or 0))
        if len(parts) == 2 and all(_names_a_tank(p.text) for p in parts):
            resolved.extend(parts)
            continue
        # Notes on a side ("GIRDER OVER") are not part of the tank's name.
        named = [p for p in parts if p.text and not _is_note(p.text)] or parts
        text = ' '.join(p.text for p in named if p.text)
        resolved.append(RegionLabel(region, None, [b for p in parts for b in p.blocks], text))
    return resolved


def _is_note(text: str) -> bool:
    """A structural note ("GIRDER OVER", "WEB"): a feature word with no tank word, no tank
    number and no schedule item."""
    lower = text.lower()
    return bool(FEATURE_WORDS.search(lower)) and not TANK_WORDS.search(lower) and not tank_key(text) \
        and '#' not in text


def _names_a_tank(text: str) -> bool:
    return bool(tank_key(text)) or content_of(text) not in (None, 'dry')


def _several_tanks(text: str) -> bool:
    """A label with two different tank numbers belongs to a room that holds several tanks (or a
    region that leaks into them), not to one tank."""
    numbers = {re.sub(r'\s+', '', m.group(1)) for m in re.finditer(r'\bno\.?\s*(\d{1,2})', text.lower())}
    return len(numbers) > 1


def plan_tanks(view: ReadView, labels: list[RegionLabel], schedule: list[dict] = ()) -> list[PlanTank]:
    """Tank regions of a plan: labelled regions whose label names a tank, or whose tank number
    has a schedule row that names a tank (of the same kind). A label for both sides ("NO.2 P/S")
    on a region across the centre line gives a port and a starboard tank."""
    found: list[PlanTank] = []
    for label in labels:
        if _several_tanks(label.text) or not names_tank(label.text, schedule):
            continue
        for side, text in split_both_sides(label.text, label.side, view.centre_row is not None):
            tank = PlanTank(view.record_name, text, tank_key(text), label.region, {}, (0.0, 0.0), side,
                            view.ink.spec.role)
            _restrict(view, tank)
            if tank.columns:
                found.append(tank)
    return found


def names_tank(text: str, schedule: list[dict]) -> bool:
    """A label names a tank by its own words, or by a tank number whose schedule row (same
    number and kind) names a tank."""
    if is_tank_label(text):
        return True
    if FEATURE_WORDS.search((text or '').lower()) or not tank_key(text):
        return False
    row = schedule_row_for(text, list(schedule))
    return row is not None and is_tank_label(f"{row.get('name', '')} {row.get('content', '')}")


def split_both_sides(text: str, side: int | None, has_centre_line: bool) -> list[tuple[int | None, str]]:
    """(side, label) of the tanks a label names: a label for both sides ("NO.2 P/S") on a whole
    region gives a port tank ("NO.2 P") and a starboard tank ("NO.2 S"); else the label itself."""
    if side is not None or not has_centre_line or not BOTH_SIDES.search(text):
        return [(side, text)]
    return [(1, BOTH_SIDES.sub('P', text)), (-1, BOTH_SIDES.sub('S', text))]


def _restrict(view: ReadView, tank: PlanTank) -> None:
    """Columns of the tank's region (one side of the centre line when ``side`` is set)."""
    mask = view.ink.regions == tank.region
    if tank.side is not None and view.centre_row is not None:
        rows = np.arange(mask.shape[0])[:, None]
        mask = mask & ((rows < view.centre_row) if tank.side > 0 else (rows >= view.centre_row))
    rows, cols = np.nonzero(mask)
    if not len(cols):
        tank.columns = {}
        return
    # One column range per column of pixels; y up = port (bow to the right).
    order = np.argsort(cols)
    cols, rows = cols[order], rows[order]
    unique, starts = np.unique(cols, return_index=True)
    ends = np.append(starts[1:], len(cols))
    xs = view.axis.x_m(unique + 0.5)
    scale = view.px_per_m
    centre = view.centre_row
    spans = {}
    for x, a, b in zip(xs, starts, ends):
        top, bottom = rows[a:b].min(), rows[a:b].max() + 1
        spans[float(x)] = ((centre - bottom) / scale, (centre - top) / scale)
    tank.columns = spans
    pixel = 1 / scale
    tank.x_range = (float(xs.min()) - pixel / 2, float(xs.max()) + pixel / 2)


@dataclass
class ProfileRegion:
    region: int
    label: str
    x_range: tuple[float, float]
    columns: dict[float, tuple[float, float]]  # ship x -> (z low, z high) m


def profile_regions(view: ReadView, labels: list[RegionLabel]) -> list[ProfileRegion]:
    """Labelled profile regions with their height (m above the baseline) per ship x."""
    found = []
    for label in labels:
        if not label.text:
            continue
        rows, cols = np.nonzero(view.ink.regions == label.region)
        unique, inverse = np.unique(cols, return_inverse=True)
        low = np.full(len(unique), -1)
        high = np.full(len(unique), 10 ** 9)
        np.maximum.at(low, inverse, rows)
        np.minimum.at(high, inverse, rows)
        xs = view.axis.x_m(unique + 0.5)
        z_low = (view.baseline_row - (low + 1)) / view.px_per_m
        z_high = (view.baseline_row - high) / view.px_per_m
        columns = {float(x): (float(a), float(b)) for x, a, b in zip(xs, z_low, z_high)}
        found.append(ProfileRegion(label.region, label.text, (float(xs.min()), float(xs.max())), columns))
    return found


def find_baseline(view: ReadView, blocks: list[TextBlock]) -> tuple[float, str]:
    """Baseline row: the horizontal line next to a "BL"/"base line" label (within
    BASELINE_REACH character heights of it; a line at or below the label first), else the
    lowest long horizontal line (a fifth of the view wide) above the frame axis."""
    parsed = view.ink
    # A baseline is often drawn dashed: dash gaps are closed here.
    horizontal, _ = axis_line_masks(parsed.ink & ~parsed.text, parsed.px_per_mm, close_dashes=True)
    # Only a frame axis with read numbers lies below the hull; ticks without numbers (frame marks
    # on a tank-top line) or a scale-bar sheet give no such row: then the lowest long line counts.
    has_frame_axis = view.axis is not None and view.axis.source == 'read'
    axis_row = view.axis.row if has_frame_axis else float(horizontal.shape[0])
    for block in blocks:
        text = block.text.lower().replace('.', ' ')
        if not re.search(r'\bb\s*l\b|base\s*line|baseline', text):
            continue
        reach = int(BASELINE_REACH * block.char_height_px)
        r0, c0, r1, c1 = _label_line_box(block, blocks)
        # The frame axis itself may be the baseline: rows down to just below the axis line.
        top, bottom = max(0, r0 - reach), min(int(axis_row + 2 * parsed.line_width_px) + 1, r1 + reach)
        window = horizontal[top:bottom, max(0, c0 - 3 * reach):c1 + 3 * reach]
        rows = np.flatnonzero(window.any(axis=1)) + top
        if len(rows):
            bands = [float(b.mean()) for b in np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)]
            # A line that ends at the label, on the label's rows, is the labelled line; else a
            # label is written above its line: a line at or below the label's top wins.
            ending = [r for r in bands if r0 <= r <= r1 + 2 * parsed.line_width_px
                      and _line_ends_at(horizontal[int(round(r))], c0, c1, block.char_height_px)]
            below = [r for r in bands if r >= r0]
            row = min(ending or below or bands, key=lambda r: abs(r - block.centre[0]))
            return row, f'horizontal line at the label "{block.text}"'
    cover = horizontal.sum(axis=1)
    long_rows = np.flatnonzero(cover >= 0.2 * horizontal.shape[1])
    bands = np.split(long_rows, np.flatnonzero(np.diff(long_rows) > 1) + 1) if len(long_rows) else []
    lines = [float(b.mean()) for b in bands if len(b) and b.mean() < axis_row - 2]
    if lines:
        where = 'above the frame axis' if has_frame_axis else 'of the view'
        return max(lines), f'lowest long horizontal line {where} (no baseline label read)'
    return float(parsed.ink.shape[0]), 'view bottom (no baseline found)'


def _label_line_box(block: TextBlock, blocks: list[TextBlock]) -> tuple[int, int, int, int]:
    """Box of a block and the words beside it on its text line ("Ny" before "BL."): blocks
    whose rows overlap and that follow each other with gaps under two character heights."""
    r0, c0, r1, c1 = block.box
    gap = 2 * block.char_height_px
    grown = True
    while grown:
        grown = False
        for other in blocks:
            b0, d0, b1, d1 = other.box
            if min(r1, b1) - max(r0, b0) <= 0 or (d0 >= c0 and d1 <= c1):
                continue
            if c0 - gap <= d1 <= c0 or c1 <= d0 <= c1 + gap:
                r0, c0, r1, c1 = min(r0, b0), min(c0, d0), max(r1, b1), max(c1, d1)
                grown = True
    return r0, c0, r1, c1


def _line_ends_at(row: np.ndarray, c0: int, c1: int, char_height: float) -> bool:
    """Whether a run of ``row`` ends within 1.5 character heights left of column ``c0`` or
    starts within that distance right of ``c1`` (a label placed at the end of its line)."""
    gap = int(1.5 * char_height)
    left = row[max(0, c0 - gap):c0]
    right = row[c1:c1 + gap]
    return bool(left.any() and not row[c0:c1].any()) or bool(right.any() and not row[c0:c1].any())


def floor_above_base(view: ReadView, x_m: float) -> float | None:
    """Height (m) of the lowest horizontal line at least MIN_DOUBLE_BOTTOM_M above the baseline,
    in the profile column at ship x."""
    columns = np.arange(view.ink.ink.shape[1]) + 0.5
    xs = view.axis.x_m(columns)
    column = int(np.argmin(np.abs(xs - x_m)))
    rows = np.flatnonzero(view.ink.horizontal[:, column])
    heights = (view.baseline_row - rows) / view.px_per_m
    heights = heights[heights >= MIN_DOUBLE_BOTTOM_M]
    return float(heights.min()) if len(heights) else None


def deck_above(profile: ReadView, xs: np.ndarray, low_m: float) -> float | None:
    """Height (m) of the first deck line above ``low_m`` over a tank: a horizontal profile line
    at least DECK_MIN_COVER of the view wide, at least MIN_TANK_HEIGHT_M above ``low_m``, at the
    tank's middle."""
    from scipy import ndimage

    horizontal = profile.ink.horizontal
    # A deck line with sheer steps from row to row: its connected pieces span the width.
    pieces, _ = ndimage.label(horizontal, structure=np.ones((3, 3)))
    spans = [0] + [box[1].stop - box[1].start for box in ndimage.find_objects(pieces)]
    columns = np.arange(horizontal.shape[1]) + 0.5
    column = int(np.argmin(np.abs(profile.axis.x_m(columns) - float(np.median(xs)))))
    rows = np.flatnonzero(horizontal[:, column])
    rows = rows[[spans[pieces[row, column]] >= DECK_MIN_COVER * horizontal.shape[1] for row in rows]] \
        if len(rows) else rows
    heights = (profile.baseline_row - rows) / profile.px_per_m
    heights = heights[heights >= low_m + MIN_TANK_HEIGHT_M]
    return float(heights.min()) if len(heights) else None


# ---------------------------------------------------------------------------------------------
# Tanks


@dataclass
class RasterTank:
    plan: PlanTank
    content: str
    name: str
    schedule_key: str | None
    z_source: str
    z_basis: str
    profile_label: str | None
    triangles: np.ndarray | None
    volume_m3: float
    notes: list[str] = field(default_factory=list)


def match_profile(tank: PlanTank, regions: list[ProfileRegion], on_bottom: bool = False) -> ProfileRegion | None:
    """The profile region of a plan tank: the two x extents overlap over at least
    MIN_PROFILE_COVER of the longer one (a piece of the tank, or a room over several tanks, is
    not the tank), and the labels share a word (content words, not numbers or sides); the
    largest overlap wins. With ``on_bottom`` (a tank of a double-bottom plan) only regions on the
    bottom shell count."""
    best, best_overlap = None, 0.0
    plan_words = words(tank.label)
    for region in regions:
        overlap = min(tank.x_range[1], region.x_range[1]) - max(tank.x_range[0], region.x_range[0])
        longer = max(tank.x_range[1] - tank.x_range[0], region.x_range[1] - region.x_range[0])
        if longer <= 0 or overlap < MIN_PROFILE_COVER * longer:
            continue
        if on_bottom and min(low for low, _ in region.columns.values()) > ON_BOTTOM_M:
            continue  # a double-bottom tank's profile region sits on the bottom shell
        shared = plan_words & words(region.label)
        # A tank number names the same tank only on a tank label ("HOLD NO.2" is not tank No. 2).
        same_number = (_number(tank.key) is not None and _number(tank.key) == _number(tank_key(region.label))
                       and content_of(region.label) not in (None, 'dry'))
        # A shortened word counts ("FRESH W." names "Fresh water").
        prefixed = any(a.startswith(b) or b.startswith(a) for a in plan_words for b in words(region.label)
                       if min(len(a), len(b)) >= 3)
        if not (shared or same_number or prefixed):
            continue
        if overlap > best_overlap:
            best, best_overlap = region, overlap
    return best


def _number(key: str | None) -> str | None:
    match = re.match(r'no (\d+)', key or '')
    return match.group(1) if match else None


def align_to_profile(plan: ReadView, profile: ReadView, search_m: float = None) -> tuple[float, str, bool]:
    """Shift (m) of a plan's x that puts its transverse bulkheads on the profile's: the shift
    within ``search_m`` (default ALIGN_SEARCH_M) that best correlates the long vertical lines of both views (0.1 m
    bins). Used when x comes from a scale bar, with no frame numbers to tie the views.
    Returns the shift, the evidence and whether at least ALIGN_MIN_AGREEING bins agree; a weak
    alignment shifts nothing (shift 0)."""
    def presence(view: ReadView) -> tuple[np.ndarray, float]:
        vertical = view.ink.vertical
        long_columns = vertical.sum(axis=0) >= ALIGN_MIN_LINE * vertical.shape[0]
        xs = view.axis.x_m(np.flatnonzero(long_columns) + 0.5)
        return xs, float(view.axis.x_m([0.0])[0])

    search_m = ALIGN_SEARCH_M if search_m is None else search_m
    plan_xs, _ = presence(plan)
    profile_xs, _ = presence(profile)
    if not len(plan_xs) or not len(profile_xs):
        return 0.0, 'no long vertical lines to align on; views taken as drawn one above the other', False
    low = min(plan_xs.min(), profile_xs.min()) - search_m
    bins = np.arange(low, max(plan_xs.max(), profile_xs.max()) + search_m, ALIGN_BIN_M)
    a = np.histogram(plan_xs, bins)[0] > 0
    b = np.histogram(profile_xs, bins)[0] > 0
    steps = int(search_m / ALIGN_BIN_M)
    scores = {shift: float(np.sum(np.roll(a, shift) & b)) for shift in range(-steps, steps + 1)}
    best = max(scores, key=lambda k: (scores[k], -abs(k)))
    agreeing = scores[best] >= ALIGN_MIN_AGREEING
    shift_m = best * ALIGN_BIN_M if agreeing else 0.0
    return shift_m, (f'plan shifted {shift_m:+.1f} m: best {best * ALIGN_BIN_M:+.1f} m has {scores[best]:.0f} '
                     f'vertical-line bins agree with the profile (at no shift: {scores[0]:.0f})'), agreeing


def double_bottom_level(profile: ReadView, xs: np.ndarray) -> float | None:
    """Tank top of a double bottom over a tank's length: the median of the lowest horizontal
    profile line above the baseline at nine stations (a station without one is skipped)."""
    levels = [floor_above_base(profile, x) for x in np.linspace(xs.min(), xs.max(), 9)]
    levels = [level for level in levels if level is not None]
    return float(np.median(levels)) if levels else None


def build_tank(tank: PlanTank, plan_role: str, profile: ReadView | None, regions: list[ProfileRegion],
               slicer: tanks.HullSlicer | None, region: ProfileRegion | None = None
               ) -> tuple[np.ndarray | None, str, str, str | None]:
    """Solid of a plan tank: (triangles, z source, z basis, matched profile label). ``region``
    gives the profile region directly (a tank named in the profile only)."""
    xs = np.array(sorted(tank.columns))
    step = abs(xs[1] - xs[0]) if len(xs) > 1 else 0.05

    def y_of_x(x):
        nearest = xs[np.argmin(np.abs(xs - x))]
        return tank.columns[float(nearest)] if abs(nearest - x) <= 1.5 * step else None

    if plan_role == 'double_bottom' and label_kind(tank.label) in ('deep tank', 'settling', 'peak'):
        plan_role = 'above'  # drawn in the inner-bottom plan, but standing on the tank top
    matched = region or (match_profile(tank, regions, plan_role == 'double_bottom') if profile is not None else None)
    bottom = -1.0 if slicer is not None else 0.0
    tank_top = double_bottom_level(profile, xs) if plan_role == 'double_bottom' and profile is not None else None
    if matched is not None:
        zx = np.array(sorted(matched.columns))
        # A profile region whose floor lies inside the double bottom (below its tank top, or
        # within ON_BOTTOM_M of the baseline) sits on the bottom shell: lines below the tank top
        # in a profile are old keel or shaft lines, not tank floors.
        floor_limit = max(ON_BOTTOM_M, tank_top or 0.0)

        def z_of_x(x):
            nearest = zx[np.argmin(np.abs(zx - x))]
            low, high = matched.columns[float(nearest)]
            return (bottom if low <= floor_limit else low, high)
        source, basis = 'traced', f'profile region at the label "{matched.label}"'
    elif tank_top is not None:
        def z_of_x(x):
            return (bottom, tank_top)
        source, basis = 'traced', (f'from the bottom to the tank-top line of the profile at {tank_top:.2f} m '
                                   '(median of the lowest horizontal line above the baseline over the tank)')
    elif profile is not None:
        # A tank in a plan above the double bottom that the profile does not show (a wing tank
        # off the centre line): from the tank top to the deck above it (gap fill).
        low = double_bottom_level(profile, xs)
        high = deck_above(profile, xs, low if low is not None else 0.0)
        if high is None:
            return None, 'guessed', 'no profile region matched and no deck line found above the tank', None

        def z_of_x(x):
            return (bottom if low is None else low, high)
        source, basis = 'guessed', (f'not in the profile: from the tank top ({low if low is not None else "bottom"}) '
                                    f'to the deck line above it at {high:.2f} m; the tank height is not drawn')
    else:
        return None, 'guessed', 'no profile to give the tank height', None
    if slicer is not None:
        loft = tanks.tank_loft_in_hull(slicer, tank.x_range, y_of_x, z_of_x, TANK_SLAB_M, TANK_ROW_DZ_M)
        return loft.triangles(), source, basis, matched.label if matched else None
    slabs = []
    edges = list(np.arange(tank.x_range[0], tank.x_range[1], TANK_SLAB_M)) + [tank.x_range[1]]
    for xa, xb in zip(edges, edges[1:]):
        middle = (xa + xb) / 2
        y_range, z_range = y_of_x(middle), z_of_x(middle)
        if y_range and z_range and z_range[1] > z_range[0] and y_range[1] > y_range[0]:
            (ya, yb), (za, zb) = y_range, z_range
            slabs.append((float(xa), float(xb), [[ya, za], [yb, za], [yb, zb], [ya, zb]]))
    basis += '; no hull given: prism of the plan region (bilge not cut, guessed)'
    triangles = tanks.slabs_triangles(slabs) if slabs else None
    return triangles, 'guessed', basis, matched.label if matched else None


def half_breadths(view: ReadView, x_m: float) -> tuple[float, float] | None:
    """Port and starboard half-breadths (m) of a plan's outline at ship x: the outermost
    boundary ink above and below the centre line in that pixel column; None outside the plan."""
    if view.centre_row is None:
        return None
    boundary = view.ink.boundary
    xs = view.axis.x_m(np.arange(boundary.shape[1]) + 0.5)
    if not min(xs[0], xs[-1]) <= x_m <= max(xs[0], xs[-1]):
        return None
    column = int(np.argmin(np.abs(xs - x_m)))
    rows = np.flatnonzero(boundary[:, column])
    clear = 2 * view.ink.line_width_px  # the centre line itself
    port = rows[rows < view.centre_row - clear]
    starboard = rows[rows > view.centre_row + clear]
    if not len(port) or not len(starboard):
        return None
    return (view.centre_row - port.min()) / view.px_per_m, (starboard.max() - view.centre_row) / view.px_per_m


def profile_tanks(profile: ReadView, labels: list[RegionLabel], regions: list[ProfileRegion],
                  plans: list[ReadView], plan_tanks_found: list[PlanTank]) -> list[tuple[PlanTank, ProfileRegion]]:
    """Tanks that the profile names but no plan draws (deep tanks, peaks, a fresh water tank
    over the shaft): a labelled profile region that names a liquid tank, with no plan tank of
    the same number or name words over the same frames. Its breadth at each x is the median of
    the plan outlines there (port half, starboard half, or both for a centre tank); its height
    is the profile region. A label for both sides ("NO.2 P/S") gives two tanks."""
    by_region = {region.region: region for region in regions}
    found = []
    for label in labels:
        region = by_region.get(label.region)
        if region is None or not is_tank_label(label.text) or content_of(label.text) in (None, 'dry'):
            continue
        if ROOM_WORDS.search(label.text.lower()):
            continue  # a room's label run together with a tank's: the region is the room
        if _several_tanks(label.text) or any(_same_tank(label.text, region, tank) for tank in plan_tanks_found):
            continue
        both = bool(BOTH_SIDES.search(label.text))
        # A tank on the bottom shell no higher than a double bottom takes the double-bottom
        # plan's breadth; any other tank the plans above it (all plans when none has that role).
        in_double_bottom = (min(low for low, _ in region.columns.values()) <= ON_BOTTOM_M
                            and max(high for _, high in region.columns.values()) <= MAX_DOUBLE_BOTTOM_M)
        role = 'double_bottom' if in_double_bottom else 'above'
        breadth_plans = [plan for plan in plans if plan.ink.spec.role == role] or plans
        for side, text in ([(1, BOTH_SIDES.sub('P', label.text)), (-1, BOTH_SIDES.sub('S', label.text))]
                           if both else [(None, label.text)]):
            columns = {}
            for x in np.arange(region.x_range[0], region.x_range[1], TANK_SLAB_M / 2):
                widths = [w for w in (half_breadths(plan, float(x)) for plan in breadth_plans) if w is not None]
                if not widths:
                    continue
                # The hull is symmetric: the smaller side leaves out ink drawn outside the hull.
                half = float(np.median([min(w) for w in widths]))
                columns[float(x)] = (0.0 if side == 1 else -half, 0.0 if side == -1 else half)
            if len(columns) < 2:
                continue
            xs = sorted(columns)
            tank = PlanTank(profile.record_name, text, tank_key(text), -1, columns, (xs[0], xs[-1]), side)
            found.append((tank, region))
    return found


def _same_tank(text: str, region: ProfileRegion, tank: PlanTank) -> bool:
    """A plan tank is the tank of a profile label when their x extents overlap over half the
    shorter one, their kinds do not differ (a deep tank over double-bottom tank No. 1 is another
    tank) and they share the tank number or a name word."""
    profile_kind = label_kind(text)
    if profile_kind and tank.kind and profile_kind != tank.kind:
        return False
    overlap = min(tank.x_range[1], region.x_range[1]) - max(tank.x_range[0], region.x_range[0])
    shorter = min(tank.x_range[1] - tank.x_range[0], region.x_range[1] - region.x_range[0])
    if shorter <= 0 or overlap < 0.5 * shorter:
        return False
    number = _number(tank_key(text))
    return (number is not None and number == _number(tank.key)) or bool(words(text) & words(tank.label))


def read_schedule(ink: np.ndarray, window, ask: Asker) -> list[dict]:
    """Rows (key, name, content) of a printed tank schedule; volumes are never asked."""
    import cv2

    height, width = ink.shape
    x0, y0, x1, y1 = window
    crop = ink[int(y0 * height):int(y1 * height), int(x0 * width):int(x1 * width)]
    scale = min(1.0, 2400 / max(crop.shape))
    image = np.where(crop, 0, 255).astype(np.uint8)
    if scale < 1:
        image = cv2.resize(image, (int(crop.shape[1] * scale), int(crop.shape[0] * scale)),
                           interpolation=cv2.INTER_AREA)
    reply = ask(image, SCHEDULE_PROMPT)
    rows = reply.get('rows') or []
    return [r for r in rows if isinstance(r, dict) and (r.get('key') or r.get('name'))]


def schedule_row_for(label: str, rows: list[dict], sheet: int | None = None) -> dict | None:
    """The schedule row of a label: the same tank number and a kind that does not differ (a
    "NO.1 HATCH" is not fuel oil tank No. 1; a deep tank No. 3 is not double-bottom tank No. 3),
    rows of the label's own sheet first; else the row that shares the most name words (two or
    more)."""
    key = tank_key(label)
    kind = label_kind(label)
    if key:
        same_sheet = sorted(rows, key=lambda row: row.get('sheet') != sheet)
        for row in same_sheet:
            if tank_key(row.get('key', '')) != key and tank_key(row.get('name', '')) != key:
                continue
            row_kind = label_kind(row.get('name', ''))
            if kind is None or row_kind is None or kind == row_kind:
                return row
    label_words = words(label)
    best, best_score = None, 0
    for row in rows:
        score = len(label_words & words(row.get('name', '')))
        if score > best_score:
            best, best_score = row, score
    return best if best_score >= 2 else None


def read_sheet(ink: np.ndarray, dpi: float, sheet: SheetSpec, ask: Asker,
               slicer: tanks.HullSlicer | None = None) -> tuple[list[RasterTank], dict]:
    """Read one sheet: tanks (with solids) and a reading record (no image data)."""
    return read_sheets([(ink, dpi, sheet)], ask, slicer)


@dataclass
class _SheetViews:
    views: dict[str, ReadView]
    labels: dict[str, list[RegionLabel]]
    free: dict[str, list[TextBlock]]
    schedule: list[dict]


def _read_views(ink: np.ndarray, dpi: float, sheet: SheetSpec, ask: Asker, prefix: str,
                reading: dict, number: int = 0) -> _SheetViews:
    """All views of one sheet with their axes and labels, and its tank schedule (rows tagged
    with the sheet ``number``: item numbers refer to the schedule of their own sheet)."""
    px_per_mm = dpi / MM_PER_INCH
    ink, angle = deskew(ink, px_per_mm)
    reading.setdefault('sheets', []).append({'dpi': dpi, 'skew_removed_deg': round(angle, 3)})
    bar_axis = None
    if sheet.scale_bar is not None:
        bar_axis = read_scale_bar(ink, sheet.scale_bar, px_per_mm, sheet.scale_bar_unit_m, ask)
        reading['sheets'][-1]['scale_bar'] = None if bar_axis is None else {
            'px_per_m': bar_axis.px_per_m, 'evidence': bar_axis.evidence}
    schedule = read_schedule(ink, sheet.schedule, ask) if sheet.schedule else []
    found = _SheetViews({}, {}, {}, [{**row, 'sheet': number} for row in schedule])
    for spec in sheet.views:
        name = prefix + spec.name
        view = read_view(ink, spec, px_per_mm, sheet, ask, bar_axis)
        view.name = name
        if view.axis is None:
            reading['views'][name] = {'error': 'no axis or scale', 'notes': view.notes}
            continue
        found.labels[name], found.free[name] = read_labels(view, ask, found.schedule)
        found.views[name] = view
        reading['views'][name] = {
            'kind': spec.kind, 'px_per_m': round(view.px_per_m, 3), 'axis': view.axis.evidence,
            'axis_source': view.axis.source, 'ticks': len(view.axis.ticks),
            'labels': [label.text for label in found.labels[name]],
            'label_places': [{'text': label.text, 'region': label.region, 'side': label.side,
                              'box': list(_box_of(label.blocks)), 'x_m': [round(float(v), 2) for v in view.axis.x_m(
                                  [_box_of(label.blocks)[1], _box_of(label.blocks)[3]])]}
                             for label in found.labels[name] if label.blocks],
            'free_text': [b.text for b in found.free[name]],
            'cross_marks': len(view.ink.crosses), 'notes': view.notes}
    return found


def read_sheets(sheets: list[tuple[np.ndarray, float, SheetSpec]], ask: Asker,
                slicer: tanks.HullSlicer | None = None) -> tuple[list[RasterTank], dict]:
    """Read the views of one or more sheets (a profile on one sheet, plans on others) and build
    the tanks. The first profile is the profile of every plan. Views without frame numbers are
    aligned to it by their bulkheads (``align_to_profile``): within ALIGN_SEARCH_M on the same
    sheet, within half the profile's length on another sheet."""
    reading: dict = {'views': {}, 'engineering_approved': False}
    views: dict[str, ReadView] = {}
    labels: dict[str, list[RegionLabel]] = {}
    free: dict[str, list[TextBlock]] = {}
    schedule: list[dict] = []
    sheet_of: dict[str, int] = {}
    for number, (ink, dpi, sheet) in enumerate(sheets):
        prefix = f'sheet{number + 1}_' if len(sheets) > 1 else ''
        found = _read_views(ink, dpi, sheet, ask, prefix, reading, number)
        views.update(found.views)
        labels.update(found.labels)
        free.update(found.free)
        schedule.extend(found.schedule)
        sheet_of.update({name: number for name in found.views})
    profile_name = next((name for name, v in views.items() if v.ink.spec.kind == 'profile'), None)
    profile = views.get(profile_name)
    regions: list[ProfileRegion] = []
    if profile is not None:
        profile_length = profile.ink.ink.shape[1] / profile.px_per_m
        for name, view in views.items():
            if view.ink.spec.kind == 'plan' and view.axis.source == 'guessed':
                search = ALIGN_SEARCH_M if sheet_of[name] == sheet_of[profile_name] else profile_length / 2
                shift, evidence, agreeing = align_to_profile(view, profile, search)
                shift_px = shift * view.px_per_m  # before the ticks move (the scale reads them)
                for tick in view.axis.ticks:
                    tick.column -= shift_px
                if agreeing:
                    view.axis.source = 'aligned'
                    view.axis.evidence += '; x aligned to the profile by its bulkheads'
                reading['views'][name].update(alignment=evidence, axis_source=view.axis.source,
                                              axis=view.axis.evidence)
        profile.baseline_row, basis = find_baseline(profile, free[profile_name] + [
            TextBlock(_box_of(label.blocks), label.blocks[0].char_height_px, label.text)
            for label in labels[profile_name]])
        reading['views'][profile_name]['baseline'] = basis
        regions = profile_regions(profile, labels[profile_name])
    reading['schedule_rows'] = len(schedule)
    results: list[RasterTank] = []
    for name, view in views.items():
        if view.ink.spec.kind != 'plan':
            continue
        for tank in plan_tanks(view, labels[name], schedule):
            row = schedule_row_for(tank.label, schedule, sheet_of[name]) if schedule else None
            content = content_of(row.get('content', '') if row else '', row.get('name', '') if row else '',
                                 tank.label) or 'misc'
            tank_name = row.get('name') if row else tank.label
            triangles, z_source, z_basis, profile_label = build_tank(tank, view.ink.spec.role, profile, regions, slicer)
            volume = tanks.fill_state(tanks.outward(triangles), float(triangles[:, :, 2].max())).volume_m3 \
                if triangles is not None else 0.0
            results.append(RasterTank(tank, content, tank_name or tank.label, row.get('key') if row else None,
                                      z_source, z_basis, profile_label, triangles, volume))
    if profile is not None:
        plans = [view for view in views.values() if view.ink.spec.kind == 'plan']
        for tank, region in profile_tanks(profile, labels[profile_name], regions, plans,
                                          [t.plan for t in results]):
            row = schedule_row_for(tank.label, schedule, sheet_of[profile_name]) if schedule else None
            content = content_of(row.get('content', '') if row else '', tank.label) or 'misc'
            triangles, z_source, z_basis, profile_label = build_tank(tank, 'above', profile, regions, slicer, region)
            volume = tanks.fill_state(tanks.outward(triangles), float(triangles[:, :, 2].max())).volume_m3 \
                if triangles is not None else 0.0
            z_basis += '; breadth from the plan outlines at each x (guessed)'
            results.append(RasterTank(tank, content, tank.label, row.get('key') if row else None, 'guessed',
                                      z_basis, profile_label, triangles, volume))
    reading['tanks'] = [tank_record(t) for t in results]
    return results, reading


def _box_of(blocks: list[TextBlock]) -> tuple[int, int, int, int]:
    return (min(b.box[0] for b in blocks), min(b.box[1] for b in blocks), max(b.box[2] for b in blocks),
            max(b.box[3] for b in blocks))


def read_scale_bar(ink: np.ndarray, window, px_per_mm: float, unit_m: float, ask: Asker) -> Axis | None:
    height, width = ink.shape
    x0, y0, x1, y1 = window
    spec = ViewSpec('scale_bar', 'bar', window)
    crop = ink[int(y0 * height):int(y1 * height), int(x0 * width):int(x1 * width)]
    parsed = parse_view(crop, spec, (int(y0 * height), int(x0 * width)), px_per_mm)
    best = None
    for row in axis_rows(parsed):
        ticks, spacing = regular_ticks(find_ticks(crop, row, parsed.line_width_px, px_per_mm))
        if len(ticks) >= 4 and (best is None or len(ticks) > len(best[0])):
            best = (ticks, spacing, row)
    if best is None:
        return None
    ticks, spacing, row = best
    crops, _ = axis_label_crops(parsed, row, ticks, spacing, px_per_mm)
    has_text = [i for i, c in enumerate(crops) if c.any()]
    for i, text in zip(has_text, read_crops([crops[i] for i in has_text], _char_px(parsed), AXIS_PROMPT, ask)):
        ticks[i].label = text
    return fit_scale_bar(row, ticks, unit_m)


def tank_record(tank: RasterTank) -> dict:
    return {'label': tank.plan.label, 'key': tank.plan.key, 'view': tank.plan.view, 'name': tank.name,
            'schedule_key': tank.schedule_key, 'content': tank.content,
            'x_m': [round(v, 3) for v in tank.plan.x_range], 'volume_m3': round(tank.volume_m3, 4),
            'built': tank.triangles is not None, 'profile_label': tank.profile_label,
            'z_m': None if tank.triangles is None else [round(float(tank.triangles[:, :, 2].min()), 3),
                                                       round(float(tank.triangles[:, :, 2].max()), 3)],
            'y_m': None if tank.triangles is None else [round(float(tank.triangles[:, :, 1].min()), 3),
                                                       round(float(tank.triangles[:, :, 1].max()), 3)],
            'source_labels': {'outline': 'traced', 'height': tank.z_source, 'name': 'read',
                              'content': 'read' if tank.schedule_key or content_of(tank.plan.label) else 'guessed'},
            'height_basis': tank.z_basis, 'engineering_approved': False}


def tank_model(results: list[RasterTank]) -> list[tanks.Tank]:
    """The v1 tank model (capacity plan, sounding tables, exports)."""
    model = []
    used = set()
    for number, tank in enumerate(results):
        identity = re.sub(r'\W+', '_', (tank.plan.key or tank.plan.label).lower()).strip('_') or f'tank_{number}'
        while identity in used:
            identity += '_2'
        used.add(identity)
        record = tank_record(tank)
        labels = {'name': 'read', 'content': record['source_labels']['content'], 'density': 'guessed',
                  'geometry': 'traced' if tank.z_source == 'traced' else 'guessed', 'sounding_origin': 'guessed'}
        model.append(tanks.Tank(identity, tank.name, tank.content, tank.triangles, None, None, labels, None,
                                [tank.z_basis]))
    return model
