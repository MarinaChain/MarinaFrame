"""Bounded label-reading images and geometry-only station attachment.

No model transport lives here. The Rust controller reads every reply.
Limits and ambiguity rules: protocol amendment 52cecb4.
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
from pathlib import Path
import hashlib
import json
import math
import re

import numpy as np
from PIL import Image

from .body_plan_position_names import _distance_to_side

MAX_SIDE = 2048
MAX_PIXELS = 1_048_576
MAX_BYTES = 1_048_576
MAX_TOTAL_BYTES = 1_400_000
DISTANCE_M = 0.05


def _scale(width, height):
    return min(1., MAX_SIDE / max(width, height), math.sqrt(MAX_PIXELS / (width * height)))


def _encode(image, scale):
    while True:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        resized = image.resize(size, Image.Resampling.LANCZOS)
        stream = BytesIO()
        resized.save(stream, format='PNG', optimize=True)
        data = stream.getvalue()
        if len(data) <= MAX_BYTES and size[0] * size[1] <= MAX_PIXELS and max(size) <= MAX_SIDE:
            return data, size
        scale *= 0.9


def prepare(path: Path, out: Path, body_box: tuple) -> dict:
    """Whole-sheet overview plus four overlapping body-plan tiles (GA limits)."""
    out.mkdir(parents=True, exist_ok=False)
    guard = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as opened:
            image = opened.convert('L')
    finally:
        Image.MAX_IMAGE_PIXELS = guard
    left, top, right, bottom = map(int, body_box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(image.width, right), min(image.height, bottom)
    if right <= left or bottom <= top:
        raise ValueError('empty body-plan region')
    boxes = [(0, 0, image.width, image.height)]
    for row in range(2):
        for column in range(2):
            width, height = right - left, bottom - top
            boxes.append((max(left, math.floor(left + width * (column / 2 - .04))),
                          max(top, math.floor(top + height * (row / 2 - .04))),
                          min(right, math.ceil(left + width * ((column + 1) / 2 + .04))),
                          min(bottom, math.ceil(top + height * ((row + 1) / 2 + .04)))))
    crops = [image.crop(box) for box in boxes]
    for attempt in range(30):
        encoded = [_encode(crop, _scale(*crop.size) * .9 ** attempt) for crop in crops]
        if sum(len(data) for data, _ in encoded) <= MAX_TOTAL_BYTES:
            break
    else:
        raise ValueError('images exceed total byte limit')
    entries = []
    for index, (box, (data, size)) in enumerate(zip(boxes, encoded)):
        image_id = f'image{index}'
        (out / f'{image_id}.png').write_bytes(data)
        entries.append({'image_id': image_id, 'file': f'{image_id}.png',
                        'view': 'sheet_overview' if index == 0 else f'tile:{index}',
                        'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                        'width': size[0], 'height': size[1], 'crop_box_px': list(box)})
    manifest = {'schema_version': 'marinaframe.vision_request.v1', 'purpose': 'station_numbers',
                'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'engineering_approved': False,
                'context': {'coordinate_frame': 'attachment_pixels', 'sheet_size_px': list(image.size),
                            'note': 'Read only printed station numbers beside body-plan section curves; '
                                    'tiles overlap, list each printed label once on its clearest tile. '
                                    'Never use an offsets table to supply station labels.'}, 'images': entries}
    (out / 'request.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def map_item(item: dict, manifest: dict) -> dict:
    attachment = next(image for image in manifest['images'] if image['image_id'] == item['image_id'])
    left, top, right, bottom = attachment['crop_box_px']
    x0, y0, x1, y1 = item['box']
    sx = (right - left) / attachment['width']
    sy = (bottom - top) / attachment['height']
    return {'printed': item['printed'], 'box': [left + x0 * sx, top + y0 * sy, left + x1 * sx, top + y1 * sy]}


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def deduplicate(items: list[dict]) -> list[dict]:
    kept = []
    for item in sorted(items, key=lambda item: (_area(item['box']), item['printed'], item['box'])):
        a = item['box']
        duplicate = False
        for other in kept:
            if other['printed'] != item['printed']:
                continue
            b = other['box']
            intersection = max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))
            union = _area(a) + _area(b) - intersection
            if union > 0 and intersection / union >= .5:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def name_half(half, side, items: list[dict], layout):
    """Experimental label route: retain geometry but never retain rank identity."""
    from copy import deepcopy
    from . import body_plan_polyline as polyline

    result = deepcopy(half)
    sections = list({id(section): section for section in
                     result.stations + result.engaged + result.unnamed}.values())
    fragments = polyline._fragments(sections)
    eligible = [section for section in sections if not section.shared_knuckle
                and not any(section is fragment for fragment in fragments)]
    assigned = attach_numbers(eligible, items, set(side.stations_outer_first), layout)
    for section in sections:
        section.station = None
    result.stations, result.engaged = [], []
    result.unnamed = [section for section in sections if not any(section is item for item in eligible)]
    for index, section in enumerate(eligible):
        if index not in assigned or (not half.read and not polyline.is_clear_knuckle(section, layout)):
            result.unnamed.append(section)
            continue
        section.station = assigned[index]
        section.notes.append('named by printed station number and unique geometric attachment')
        if section.bottom_alternatives:
            polyline.side_and_knuckle_only(section)
        result.stations.append(section)
    # A half with traced sections cannot restore crossing rank curves when labels fail.
    # Truly round-bilge halves without eligible knuckles keep the existing fallback.
    result.read = half.read or bool(eligible)
    return result, {'unnamed_sections': len(result.unnamed),
                    'named': [section.station for section in result.stations],
                    'label_items': items, 'rank_fallback': False}


def attach_numbers(sections: list, items: list[dict], permitted: set[int], layout) -> dict[int, int]:
    claims = []
    for item in items:
        printed = item['printed'].strip()
        if re.fullmatch(r'[0-9]+', printed) is None or int(printed) not in permitted:
            continue
        x0, y0, x1, y1 = item['box']
        row, column = (y0 + y1) / 2, (x0 + x1) / 2
        nearby = [index for index, section in enumerate(sections)
                  if _distance_to_side(section.side_points(), row, column) <= DISTANCE_M * layout.pixels_per_metre]
        if len(nearby) == 1:
            claims.append((nearby[0], int(printed)))
    section_counts = Counter(index for index, _ in claims)
    name_counts = Counter(name for _, name in claims)
    return {index: name for index, name in claims if section_counts[index] == name_counts[name] == 1}
