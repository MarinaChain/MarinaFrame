"""Station identity of measured body-plan curves from small visual questions to a model.

Plan section 3.5.8. The model is never asked where a line is. For each chain that code traced
(`body_plan_reader`), it sees one crop of the drawing around that curve, at a scale where the
station numbers are readable, with the curve traced over in red, and answers one discrete
question: which station number labels the red curve (or none). Code then picks the station
numbering that agrees with the most answers while keeping the nesting order, asks again where an
answer disagrees, and keeps the code-measured columns as the values.
"""
from __future__ import annotations

import io
import json
import re

import numpy as np

from vessel_reconstruction.body_plan_reader import Chain, SideReading

# Crop: the curve's path plus this margin (px of the sheet), scaled so that its longer side is at
# most QUESTION_MAX_SIDE_PX. Low-cost models read 16 px text at 2,048 px images (plan 3.5.5);
# station numbers on a 400 dpi sheet are about 70 px tall, so about 20 px at 1/3.5 scale.
QUESTION_MARGIN_PX = 300
QUESTION_MAX_SIDE_PX = 1536
TRACE_COLOUR = (230, 0, 0, 170)  # semi-transparent red, so the digits under it stay readable
TRACE_WIDTH_PX = 4

LABEL_PROMPT = """This image is part of the BODY PLAN of a ship: a scanned line drawing of the {side_name}.
Each station curve is labelled with its station number, written on or right next to the curve,
sometimes with a small arrow pointing to the curve. Straight diagonal lines, the sheer line, deck
edges and grid lines are not station curves.

One curve is traced over in semi-transparent RED. Which station number labels the red curve?
The station numbers in this half are {first} to {last}. If no number in the image belongs to the
red curve, or the red line is not a station curve, answer null.
Reply with ONE JSON object only: {{"station": <integer or null>, "reason": "<a few words>"}}
"""


def question_image(sheet: np.ndarray, chain: Chain,
                   column_limits: tuple[int, int] | None = None) -> tuple[bytes, dict]:
    """PNG crop around one chain's curve with the curve traced in red, and the crop geometry.

    column_limits keeps the crop inside one half of the body plan (the other half's labels would
    only add confusion).
    """
    from PIL import Image, ImageDraw

    rows = [p[0] for p in chain.path]
    columns = [p[1] for p in chain.path]
    height, width = sheet.shape
    top = max(0, int(min(rows)) - QUESTION_MARGIN_PX)
    bottom = min(height, int(max(rows)) + QUESTION_MARGIN_PX)
    left = max(0, int(min(columns)) - QUESTION_MARGIN_PX)
    right = min(width, int(max(columns)) + QUESTION_MARGIN_PX)
    if column_limits is not None:
        left, right = max(left, column_limits[0]), min(right, column_limits[1])
    scale = min(1.0, QUESTION_MAX_SIDE_PX / max(bottom - top, right - left))
    size = (max(1, round((right - left) * scale)), max(1, round((bottom - top) * scale)))
    crop = Image.fromarray(np.ascontiguousarray(sheet[top:bottom, left:right])).convert('L')
    image = crop.resize(size, Image.LANCZOS).convert('RGBA')
    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    points = [((column - left) * scale, (row - top) * scale) for row, column in chain.path]
    ImageDraw.Draw(overlay).line(points, fill=TRACE_COLOUR, width=TRACE_WIDTH_PX)
    image = Image.alpha_composite(image, overlay).convert('RGB')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue(), {'box': [left, top, right, bottom], 'scale': scale, 'size': list(size)}


def label_prompt(side_name: str, stations: tuple[int, ...]) -> str:
    return LABEL_PROMPT.format(side_name=side_name, first=min(stations), last=max(stations))


def parse_label(text: str, stations: tuple[int, ...]) -> int | None:
    """The station number in a reply, or None for a null answer; raises ValueError if invalid."""
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    body = match.group(1) if match else text[text.find('{'):text.rfind('}') + 1]
    reply = json.loads(body)
    if not isinstance(reply, dict) or 'station' not in reply:
        raise ValueError('need an object with "station"')
    station = reply['station']
    if station is None:
        return None
    if isinstance(station, str) and station.strip().lstrip('-').isdigit():
        station = int(station)
    if isinstance(station, bool) or not isinstance(station, int) or station not in stations:
        raise ValueError(f'station {station!r} is not one of {min(stations)} to {max(stations)}')
    return station


def best_offset(labels: dict[int, int | None], kept: list[int], stations_outer_first: tuple[int, ...]) -> tuple[int, int]:
    """Numbering offset that agrees with the most labels, and how many agree.

    Chain kept[r] gets station stations_outer_first[r + offset]. Ties prefer the smallest |offset|
    (the code's own nesting count).
    """
    best = (0, -1)
    for offset in sorted(range(-len(kept) + 1, len(stations_outer_first)), key=abs):
        agree = sum(1 for r, chain in enumerate(kept) if 0 <= r + offset < len(stations_outer_first)
                    and labels.get(chain) == stations_outer_first[r + offset])
        if agree > best[1]:
            best = (offset, agree)
    return best


def identities_from_labels(reading: SideReading, labels: dict[int, int | None]) -> tuple[dict[int, int], dict]:
    """Chain index -> station from the model's labels and the nesting order.

    Kept chains: every chain that crosses two or more waterlines, and a one-waterline chain only
    when the model gave it a station number. The numbering is the nesting order shifted by the
    offset that agrees with the most labels. Returns the identities and a summary (offset,
    agreeing labels, chains whose label disagrees).
    """
    stations = reading.layout.stations_outer_first
    kept = [k for k, chain in enumerate(reading.chains) if len(chain.nodes) >= 2 or labels.get(k) is not None]
    offset, agree = best_offset(labels, kept, stations)
    identities = {chain: stations[r + offset] for r, chain in enumerate(kept) if 0 <= r + offset < len(stations)}
    disagree = [k for k, station in identities.items() if labels.get(k) is not None and labels[k] != station]
    labelled = sum(1 for k in kept if labels.get(k) is not None)
    return identities, {'offset': offset, 'labels_agreeing': agree, 'labels_given': labelled,
                        'chains_kept': len(kept), 'disagreeing_chains': disagree}
