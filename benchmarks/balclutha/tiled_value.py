"""Balclutha sheet 7 model-value test on full-resolution tiles (round 5).

Protocol (fixed before running): docs/plans/2026-11-09-whole-vessel-scope.md, section 3.5.4.
The model reads, one waterline at a time, where the station curves cross that waterline in a
2048 x 1024 px tile of the full-resolution sheet; the host merges the tiles into the round-4
reading form and scores it with the round-4 scorer and decision rule. R0 runs the existing
tracer on the same tiles where it can run (the tiles that contain the centreline).

Usage (load the keys in the same shell first; outputs stay out of the repository)::

    source scripts/load_opencode_keys.sh
    PYTHONPATH=src python -m benchmarks.balclutha.tiled_value --sheet work/sources/balclutha_ca54_s7.tif \\
        --truth <truth_s7.json> --out work/balclutha/round5-001
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from benchmarks.balclutha import model_value as round4
from benchmarks.gunnerus import whole_vessel_ab as ab

# Host calibration at full resolution (section 3.5.3 values times 4; grid measured on the sheet).
CENTRE_COLUMN = 4824
BASE_ROW = 6857.6
PIXELS_PER_M = 491.48
WATERLINE_ROWS = {0: 6860, 4: 6261, 8: 5659, 12: 5059, 16: 4459, 20: 3858, 24: 3258, 28: 2662, 32: 2066}
BUTTOCK_OFFSETS_FT = (2, 4, 8, 12, 16, 18, 20)
BUTTOCK_COLUMNS = {'fore': (5124, 5421, 6020, 6618, 7216, 7517, 7814),
                   'aft': (4526, 4225, 3627, 3027, 2429, 2130, 1825)}
SIDE_STATIONS = {'aft': tuple(range(0, 11)), 'fore': tuple(range(11, 21))}
# Tile layout: distance out from the centreline (px) of each tile's near and far edge.
TILE_WIDTH = 2048
TILE_HEIGHT = 1024
TILE_SPANS = {'inner': (-48, 2000), 'outer': (1002, 3050)}
# Round 5 layout; a later round may pass another (same fields) to tile_boxes.
ROUND5_LAYOUT = {'width': TILE_WIDTH, 'height': TILE_HEIGHT, 'spans': TILE_SPANS}
# Context image: one side of the body plan at 1/4 scale (columns from the centreline, rows).
QUARTER = 4
CONTEXT_OUT_PX = 800
CONTEXT_ROWS = (350, 1740)
WORKERS = 4
DISAGREEMENT_M = 0.15


def tile_boxes(layout: dict = ROUND5_LAYOUT) -> list[dict]:
    """Tiles per (side, waterline, position) with their full-sheet box (left, top, right, bottom).

    The round-5 layout gives 32 tiles; each span (near, far) must be layout['width'] px wide.
    """
    tiles = []
    for side, sign in (('aft', -1), ('fore', 1)):
        for waterline in round4.WATERLINES_FT:
            row = WATERLINE_ROWS[waterline]
            top = row - layout['height'] // 2
            for position, (near, far) in layout['spans'].items():
                columns = sorted((CENTRE_COLUMN + sign * near, CENTRE_COLUMN + sign * far))
                tiles.append({'id': f'{side}-wl{waterline:02d}-{position}', 'side': side, 'waterline': waterline,
                              'position': position, 'box': (columns[0], top, columns[1], top + layout['height'])})
    return tiles


def tile_size(tile: dict) -> tuple[int, int]:
    left, top, right, bottom = tile['box']
    return right - left, bottom - top


def tile_grid(tile: dict) -> dict:
    """Calibration and grid lines in tile pixels (only the lines inside the tile)."""
    left, top, right, bottom = tile['box']
    waterlines = {ft: row - top for ft, row in WATERLINE_ROWS.items() if top <= row < bottom}
    buttocks = {ft: column - left for ft, column in zip(BUTTOCK_OFFSETS_FT, BUTTOCK_COLUMNS[tile['side']])
                if left <= column < right}
    return {'centreline_x': CENTRE_COLUMN - left, 'target_row': WATERLINE_ROWS[tile['waterline']] - top,
            'waterlines': waterlines, 'buttocks': buttocks}


PROMPT = """These images are from the BODY PLAN of the sailing ship Balclutha (HAER CA-54, sheet 7), a scanned
drawing. Image 1 is the whole {side_name} half at 1/4 scale: stations {first} to {last}, each curve labelled
with its station number. The red box in image 1 is the area of image 2.
Image 2 is a tile at FULL resolution ({width} x {height} px) of that red box.

Task: find every station curve ({first} to {last}) that crosses the {waterline} ft waterline INSIDE image 2.
The {waterline} ft waterline is the horizontal grid line at y = {row} px in image 2.
Calibration of image 2: the centreline is at x = {cx} px (it can lie outside the tile);
{ppm} px per metre; half-breadth (m) = |x - {cx}| / {ppm}.
Grid lines inside image 2: waterlines {waterlines}; vertical buttock lines {buttocks}.
In this half the station curves are nested: {order}.
Ignore: half stations (11 1/2, 12 1/2), the straight diagonals (DIAGONAL A, B, C), the dashed sheer line,
rub rail and deck-edge lines, grid lines and lettering. Leave out a station that does not cross the
{waterline} ft waterline inside image 2.
Reply with ONE JSON object only:
{{"source": "ai_inferred", "waterline_ft": {waterline}, "crossings": [{{"station": <int>, "x_px": <number>}}, ...]}}
"""

SIDE_TEXT = {
    'aft': ('aftbody (left of the centreline)', 'at a waterline, station 10 is farthest from the centreline '
            'and station 0 is nearest; the low stations do not reach the low waterlines'),
    'fore': ('forebody (right of the centreline)', 'at a waterline, station 11 is farthest from the centreline '
             'and station 20 is nearest; the high stations do not reach the low waterlines'),
}


def tile_prompt(tile: dict) -> str:
    grid = tile_grid(tile)
    side_name, order = SIDE_TEXT[tile['side']]
    stations = SIDE_STATIONS[tile['side']]
    waterlines = ', '.join(f'{ft} ft at y = {row}' for ft, row in grid['waterlines'].items()) or 'none'
    buttocks = ', '.join(f'{ft} ft ({ft * round4.FEET_M:.3f} m) at x = {column}'
                         for ft, column in grid['buttocks'].items()) or 'none'
    width, height = tile_size(tile)
    return PROMPT.format(side_name=side_name, first=stations[0], last=stations[-1], width=width,
                         height=height, waterline=tile['waterline'], row=grid['target_row'],
                         cx=grid['centreline_x'], ppm=PIXELS_PER_M, waterlines=waterlines, buttocks=buttocks,
                         order=order)


def parse_crossings(text: str, tile: dict) -> dict:
    """{station: x_px in the tile} from the model reply; raises ValueError on an invalid reply."""
    reply = ab.extract_json(text)
    crossings = reply.get('crossings')
    if not isinstance(crossings, list):
        raise ValueError('need a "crossings" list')
    reading = {}
    for item in crossings:
        if not isinstance(item, dict):
            raise ValueError('each crossing must be an object')
        station, x_px = item.get('station'), item.get('x_px')
        if isinstance(station, bool) or not isinstance(station, int) or station not in SIDE_STATIONS[tile['side']]:
            raise ValueError(f'station {station!r} is not in this half')
        if station in reading:
            raise ValueError(f'station {station} is given twice')
        if isinstance(x_px, bool) or not isinstance(x_px, (int, float)) or not 0 <= x_px <= tile_size(tile)[0]:
            raise ValueError(f'station {station}: x_px {x_px!r} is outside the tile')
        reading[station] = float(x_px)
    return reading


def half_breadth_m(tile: dict, x_px: float) -> float:
    return abs(x_px + tile['box'][0] - CENTRE_COLUMN) / PIXELS_PER_M


def merge(tile_readings: list[tuple[dict, dict]]) -> tuple[dict, int]:
    """Round-4 reading {(station, waterline_ft): m}: mean over the tiles that give a cell.

    Also returns how many cells two tiles give with values more than DISAGREEMENT_M apart.
    """
    values: dict[tuple[int, int], list[float]] = {}
    for tile, crossings in tile_readings:
        for station, x_px in crossings.items():
            values.setdefault((station, tile['waterline']), []).append(half_breadth_m(tile, x_px))
    reading = {key: float(np.mean(found)) for key, found in values.items()}
    disagreements = sum(1 for found in values.values() if max(found) - min(found) > DISAGREEMENT_M)
    return reading, disagreements


# ---------------------------------------------------------------- images

def load_sheet(sheet: Path) -> np.ndarray:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None  # a known HAER sheet, 139 Mpx
    with Image.open(sheet) as image:
        return np.asarray(image.convert('L'))


def png_bytes(array: np.ndarray) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format='PNG')
    return buffer.getvalue()


def context_image(sheet: np.ndarray, tile: dict) -> bytes:
    """One side of the body plan at 1/4 scale, the tile drawn as a red box."""
    from PIL import Image, ImageDraw

    centre = CENTRE_COLUMN // QUARTER
    columns = (centre - CONTEXT_OUT_PX, centre + 12) if tile['side'] == 'aft' else (centre - 12, centre + CONTEXT_OUT_PX)
    rows = CONTEXT_ROWS
    full = sheet[rows[0] * QUARTER:rows[1] * QUARTER, columns[0] * QUARTER:columns[1] * QUARTER]
    image = Image.fromarray(full).resize(((columns[1] - columns[0]), rows[1] - rows[0]), Image.LANCZOS).convert('RGB')
    left, top, right, bottom = tile['box']
    ImageDraw.Draw(image).rectangle((left / QUARTER - columns[0], top / QUARTER - rows[0],
                                     right / QUARTER - columns[0], bottom / QUARTER - rows[0]),
                                    outline=(220, 0, 0), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def tile_pixels(sheet: np.ndarray, tile: dict) -> np.ndarray:
    left, top, right, bottom = tile['box']
    return sheet[top:bottom, left:right]


def first_prompt(tile: dict, context_png: bytes, tile_png: bytes) -> list:
    def image(data: bytes) -> dict:
        return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(data).decode()}}

    return [{'role': 'user', 'content': [{'type': 'text', 'text': tile_prompt(tile)},
                                         image(context_png), image(tile_png)]}]


# ---------------------------------------------------------------- R1 (model)

def read_tile(tile: dict, images: tuple[bytes, bytes], folder: Path, call) -> dict:
    messages, turns, crossings, invalid = first_prompt(tile, *images), [], None, 0
    for turn in range(1, ab.MAX_TURNS + 1):
        text, receipt = call(messages, folder / 'receipts', ab.ROUNDS['2'])
        (folder / f'{tile["id"]}-reply-{turn}.txt').write_text(text)
        turns.append({key: receipt.get(key) for key in ('state', 'usage', 'seconds', 'finish_reason')})
        try:
            crossings = parse_crossings(text, tile)
            break
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            invalid += 1
            messages = messages + [{'role': 'assistant', 'content': text},
                                   {'role': 'user', 'content': f'Invalid reply: {exc}. Reply again with the '
                                                               'complete JSON object only.'}]
    return {'tile': tile, 'crossings': crossings or {}, 'turns': turns, 'invalid_replies': invalid}


def run_repeat(tiles: list[dict], images: dict, truth: dict, folder: Path, call) -> dict:
    folder.mkdir()
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda tile: read_tile(tile, images[tile['id']], folder, call), tiles))
    reading, disagreements = merge([(r['tile'], r['crossings']) for r in results])
    turns = [turn for r in results for turn in r['turns']]
    result = round4.score(reading, truth)
    result.update(tile_disagreements=disagreements, calls=len(turns),
                  invalid_replies=sum(r['invalid_replies'] for r in results),
                  failed_requests=sum(1 for turn in turns if turn['state'] != 'completed'),
                  seconds=round(time.time() - started, 1),
                  prompt_tokens=sum((turn['usage'] or {}).get('prompt_tokens') or 0 for turn in turns),
                  completion_tokens=sum((turn['usage'] or {}).get('completion_tokens') or 0 for turn in turns))
    (folder / 'tiles.json').write_text(json.dumps(
        [{'id': r['tile']['id'], 'crossings': r['crossings'], 'invalid_replies': r['invalid_replies']}
         for r in results], indent=2) + '\n')
    (folder / 'score.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


# ---------------------------------------------------------------- R0 (code only)

def r0_spec(tile: dict) -> dict:
    left, top, _, _ = tile['box']
    width, height = tile_size(tile)
    baseline = BASE_ROW - top
    return {'units': 'm', 'source': {'file': 'tile.png'},
            'sections': [{'id': tile['id'], 'x_m': 0.0, 'roi_px': [0, 0, width, height],
                          'calibration': {'pixels_per_metre': PIXELS_PER_M,
                                          'centerline_px': CENTRE_COLUMN - left, 'baseline_px': baseline},
                          'z_min_m': (baseline - (height - 1)) / PIXELS_PER_M,
                          'z_max_m': baseline / PIXELS_PER_M}]}


def value_at_waterline(points_yz_m: list, waterline_ft: int) -> float | None:
    z_target = waterline_ft * round4.FEET_M
    ordered = sorted((z, abs(y)) for y, z in points_yz_m)
    zs, ys = [z for z, _ in ordered], [y for _, y in ordered]
    if not zs or not zs[0] <= z_target <= zs[-1]:
        return None
    return float(np.interp(z_target, zs, ys))


def nearest_station(value: float, tile: dict, truth: dict) -> int | None:
    candidates = [(abs(truth[(s, tile['waterline'])] - value), s) for s in SIDE_STATIONS[tile['side']]
                  if (s, tile['waterline']) in truth]
    return min(candidates)[1] if candidates else None


def run_r0(tiles: list[dict], sheet: np.ndarray, truth: dict, folder: Path) -> dict:
    from PIL import Image

    from vessel_reconstruction.ingest import extract_sections

    outcomes, reading = [], {}
    for tile in tiles:
        tile_folder = folder / tile['id']
        tile_folder.mkdir(parents=True)
        Image.fromarray(tile_pixels(sheet, tile)).save(tile_folder / 'tile.png')
        output = extract_sections(r0_spec(tile), tile_folder)
        outcome = {'id': tile['id'], 'gaps': [gap.get('kind') for gap in output['gaps']], 'value_m': None,
                   'assigned_station': None}
        if output['sections']:
            value = value_at_waterline(output['sections'][0]['points_yz_m'], tile['waterline'])
            station = nearest_station(value, tile, truth) if value is not None else None
            outcome.update(value_m=value, assigned_station=station)
            if station is not None:
                reading.setdefault((station, tile['waterline']), value)
        outcomes.append(outcome)
    result = round4.score(reading, truth)
    result['tiles'] = outcomes
    (folder / 'score.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


# ---------------------------------------------------------------- run

def run(sheet_path: Path, truth_path: Path, out: Path, call=None, repeats: int = round4.REPEATS) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    truth = round4.load_truth(truth_path)
    sheet = load_sheet(sheet_path)
    tiles = tile_boxes()
    r0 = run_r0(tiles, sheet, truth, out / 'R0')
    print(json.dumps({key: value for key, value in r0.items() if key != 'tiles'}), flush=True)
    images = {tile['id']: (context_image(sheet, tile), png_bytes(tile_pixels(sheet, tile))) for tile in tiles}
    results = []
    for repeat in range(1, repeats + 1):
        result = run_repeat(tiles, images, truth, out / f'R1-{repeat}', call or ab.call_model)
        results.append(result)
        print(json.dumps(result), flush=True)
    rms = [r['rms_m'] for r in results if 'rms_m' in r]
    adds_value = (all(r['coverage'] >= round4.MIN_COVERAGE for r in results) and len(rms) == repeats
                  and float(np.median(rms)) <= round4.MAX_MEDIAN_RMS_M)
    summary = {'protocol': 'docs/plans/2026-11-09-whole-vessel-scope.md 3.5.4',
               'r0': {key: value for key, value in r0.items() if key != 'tiles'},
               'repeats': results, 'median_rms_m': float(np.median(rms)) if rms else None,
               'model_adds_value': adds_value, 'engineering_approved': False}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.sheet, args.truth, args.out.resolve())
    print(json.dumps({key: value for key, value in summary.items() if key != 'repeats'}, indent=2))


if __name__ == '__main__':
    main()
