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

from vessel_reconstruction.body_plan_reader import (
    Chain,
    SideReading,
    station_candidates,
)

# Crop: the curve's path plus this margin (px of the sheet), scaled so that its longer side is at
# most QUESTION_MAX_SIDE_PX. Low-cost models read 16 px text at 2,048 px images (plan 3.5.5);
# station numbers on a 400 dpi sheet are about 70 px tall, so about 20 px at 1/3.5 scale.
QUESTION_MARGIN_PX = 300
QUESTION_MAX_SIDE_PX = 1536
TRACE_COLOUR = (230, 0, 0, 170)  # semi-transparent red, so the digits under it stay readable
TRACE_WIDTH_PX = 4
# Station assignment: a chain given the station its label names gains MATCH_SCORE; a chain that
# crosses two or more waterlines left without a station, and a station skipped between numbered
# chains (or before the first), each cost GAP_COST. Moving the numbering away from the code's
# nesting count needs more labels that agree with the move than gaps it opens (ties keep the
# count), so one misread label in a crowded area never moves it.
MATCH_SCORE = 1
GAP_COST = 1

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
    only add confusion). sheet is the grey sheet, or the ink mask of a bilevel scan
    (`body_plan_crossings.load_ink`), which gives the same black-and-white crop.
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
    pixels = sheet[top:bottom, left:right]
    if pixels.dtype == bool:
        pixels = np.where(pixels, np.uint8(0), np.uint8(255))  # ink black, paper white; 1 byte per pixel
    crop = Image.fromarray(np.ascontiguousarray(pixels)).convert('L')
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


def assign_stations(labels: dict[int, int | None], candidates: list[int], multi_waterline: set[int],
                    stations_outer_first: tuple[int, ...]) -> dict[int, int]:
    """Chain index -> station: the numbering in nesting order that agrees best with the labels.

    Code proposes the chains (candidates, outermost first) and their order; the model's labels
    name them. The assignment keeps the nesting order (a chain further in gets a station further
    in), and it may leave out a chain (not a station curve: a leader line, a merged curve, an
    outline) or a station (not drawn as its own curve). Each departure from the plain nesting count
    costs GAP_COST, each label followed gains MATCH_SCORE; ties keep the nesting count. A
    one-waterline chain is numbered only with the station its label names.
    """
    count = len(stations_outer_first)
    multi_in_order = [chain for chain in candidates if chain in multi_waterline]
    rank_position = {chain: position for position, chain in enumerate(multi_in_order)}
    memo: dict = {}

    def solve(i: int, p: int) -> tuple:
        """Best ((score, agreement with the nesting count), choices) for candidates[i:], positions p.."""
        if i == len(candidates):
            return (0, 0), ()
        if (i, p) not in memo:
            chain = candidates[i]
            (score, agree), rest = solve(i + 1, p)
            options = [((score - (GAP_COST if chain in multi_waterline else 0), agree), rest)]
            for q in range(p, count):
                matches = labels.get(chain) == stations_outer_first[q]
                if chain not in multi_waterline and not matches:
                    continue
                (score, agree), rest = solve(i + 1, q + 1)
                gained = MATCH_SCORE * matches - GAP_COST * (q - p)
                options.append(((score + gained, agree + (rank_position.get(chain) == q)), ((chain, q),) + rest))
            memo[(i, p)] = max(options, key=lambda option: option[0])
        return memo[(i, p)]

    _, choices = solve(0, 0)
    return {chain: stations_outer_first[position] for chain, position in choices}


def identities_from_labels(reading: SideReading, labels: dict[int, int | None]) -> tuple[dict[int, int], dict]:
    """Chain index -> station from the model's labels, checked against the nesting order.

    Candidates are the code's station candidates (`station_candidates`); a one-waterline chain
    also needs a label. Returns the identities and a summary: labels followed, chains whose label
    disagrees (to ask again), chains left out, and stations left without a chain between numbered
    ones (a person or a second question should confirm these).
    """
    stations = reading.layout.stations_outer_first
    candidates = [k for k in station_candidates(reading)
                  if len(reading.chains[k].nodes) >= 2 or labels.get(k) is not None]
    multi = {k for k in candidates if len(reading.chains[k].nodes) >= 2}
    identities = assign_stations(labels, candidates, multi, stations)
    disagree = [k for k, station in identities.items() if labels.get(k) is not None and labels[k] != station]
    used = {stations.index(station) for station in identities.values()}
    missing = [stations[q] for q in range(min(used), max(used)) if q not in used] if used else []
    return identities, {'labels_agreeing': sum(1 for k, station in identities.items() if labels.get(k) == station),
                        'labels_given': sum(1 for k in candidates if labels.get(k) is not None),
                        'chains_kept': len(identities), 'chains_left_out': [k for k in candidates if k not in identities],
                        'stations_without_chain': missing, 'disagreeing_chains': disagree}
