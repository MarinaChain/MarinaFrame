"""Balclutha sheet 7 model-value test (round 4, option B).

Protocol (fixed before running): docs/plans/2026-11-09-whole-vessel-scope.md, section 3.5.3.
The model reads half-breadths of stations 0 to 20 at the 4 to 32 ft waterlines from the scanned
body plan; the printed offset table (not in the image) is the truth. R0, the existing
deterministic raster tracer, abstained on this sheet and is not run again.

Usage (load the keys in the same shell first; outputs stay out of the repository)::

    source scripts/load_opencode_keys.sh
    PYTHONPATH=src python -m benchmarks.balclutha.model_value --sheet work/sources/balclutha_ca54_s7.tif \\
        --truth <truth_s7.json> --out work/balclutha/round4-001
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

import numpy as np

from benchmarks.gunnerus import whole_vessel_ab as ab

FEET_M = 0.3048
WATERLINES_FT = (4, 8, 12, 16, 20, 24, 28, 32)
STATIONS = tuple(range(21))
# Host calibration at 1/4 scale (docs/GEOMETRY_ACCURACY_V05.md section 8.2).
QUARTER_SCALE = 4
CENTRE_COLUMN = 1206.0
BASE_ROW = 1714.4
PIXELS_PER_M = 122.87
# Body-plan crop at 1/4 scale (rows above the table; the table starts near row 2040).
CROP_ROWS = (150, 1800)
IMAGE_WIDTH = 1600
REPEATS = 3
# Decision rule (section 3.5.3).
MIN_COVERAGE = 0.60
MAX_MEDIAN_RMS_M = 0.15


def feet_inches_eighths(text: str | None) -> float | None:
    if text is None:
        return None
    feet, inches, eighths = (int(part) for part in text.split('-'))
    return (feet + (inches + eighths / 8) / 12) * FEET_M


def load_truth(path: Path) -> dict:
    """{(station, waterline_ft): half-breadth m} for the printed, non-crossed cells."""
    rows = json.loads(path.read_text())['rows']
    return {(station, waterline): feet_inches_eighths(value)
            for waterline in WATERLINES_FT for station, value in enumerate(rows[str(waterline)])
            if value is not None}


def render_crop(sheet: Path, out: Path) -> dict:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None  # a known HAER sheet, 139 Mpx
    with Image.open(sheet) as image:
        quarter = image.convert('L').resize((image.width // QUARTER_SCALE, image.height // QUARTER_SCALE),
                                             Image.LANCZOS)
    crop = quarter.crop((0, CROP_ROWS[0], quarter.width, CROP_ROWS[1]))
    factor = IMAGE_WIDTH / crop.width
    crop = crop.resize((IMAGE_WIDTH, round(crop.height * factor)), Image.LANCZOS)
    path = out / 'body_plan.png'
    crop.save(path)
    metres_per_px = 1 / (PIXELS_PER_M * factor)
    return {'path': str(path), 'width': crop.width, 'height': crop.height,
            'calibration': {'centreline_px': round(CENTRE_COLUMN * factor, 2),
                            'baseline_py': round((BASE_ROW - CROP_ROWS[0]) * factor, 2),
                            'metres_per_px': round(metres_per_px, 6)}}


PROMPT = """This image is the BODY PLAN of the sailing ship Balclutha (HAER CA-54, sheet 7), a scanned
drawing. Stations 0 to 10 (aftbody) are drawn LEFT of the centreline, stations 11 to 20 (forebody)
RIGHT of it; each curve is labelled with its station number. Waterlines are drawn every 4 ft and
labelled at the left (BASE 0 ft to 32 ft). Dimensions are to the inner surface of the hull.

Calibration of this image ({width} x {height} px): centreline at x = {cx} px; baseline at y = {by} px;
{mpp} metres per pixel in both directions. half-breadth (m) = |x - {cx}| * {mpp};
height above base (m) = ({by} - y) * {mpp}. 1 ft = 0.3048 m.

For every station 0 to 20, give the half-breadth in metres where the station curve crosses each
waterline 4, 8, 12, 16, 20, 24, 28 and 32 ft (the crossing nearest the side shell). Use null where
the station does not reach that waterline. Read the curves; do not invent a table.
Reply with ONE JSON object only:
{{"source": "ai_inferred", "waterlines_ft": [4, 8, 12, 16, 20, 24, 28, 32],
  "stations": {{"0": [v4, v8, ..., v32], "1": [...], ..., "20": [...]}}}}
"""


def first_prompt(crop: dict) -> list:
    cal = crop['calibration']
    text = PROMPT.format(width=crop['width'], height=crop['height'], cx=cal['centreline_px'],
                         by=cal['baseline_py'], mpp=cal['metres_per_px'])
    data = base64.b64encode(Path(crop['path']).read_bytes()).decode()
    return [{'role': 'user', 'content': [{'type': 'text', 'text': text},
                                         {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{data}'}}]}]


def parse_reading(text: str) -> dict:
    """{(station, waterline_ft): metres} from the model reply; raises on an invalid reply."""
    reply = ab.extract_json(text)
    stations = reply['stations']
    reading = {}
    for station in STATIONS:
        values = stations.get(str(station))
        if values is None:
            continue
        if not isinstance(values, list) or len(values) != len(WATERLINES_FT):
            raise ValueError(f'station {station}: need {len(WATERLINES_FT)} values')
        for waterline, value in zip(WATERLINES_FT, values):
            if value is None:
                continue
            if not isinstance(value, (int, float)) or not 0 <= value <= 10:
                raise ValueError(f'station {station}: half-breadth {value!r} is not 0 to 10 m')
            reading[(station, waterline)] = float(value)
    return reading


def score(reading: dict, truth: dict) -> dict:
    common = [key for key in truth if key in reading]
    errors = np.array([reading[key] - truth[key] for key in common])
    result = {'truth_cells': len(truth), 'cells_given': len(common), 'coverage': len(common) / len(truth),
              'extra_cells': len([key for key in reading if key not in truth])}
    if len(common):
        result.update(rms_m=float(np.sqrt(np.mean(errors ** 2))), max_abs_m=float(np.max(np.abs(errors))),
                      within_0_05=float(np.mean(np.abs(errors) <= 0.05)),
                      within_0_15=float(np.mean(np.abs(errors) <= 0.15)))
    identity_errors = []
    for station in STATIONS:
        own = [(w, reading[(station, w)]) for w in WATERLINES_FT if (station, w) in reading]

        def station_rms(other):
            pairs = [(v, truth[(other, w)]) for w, v in own if (other, w) in truth]
            return float(np.sqrt(np.mean([(v - t) ** 2 for v, t in pairs]))) if len(pairs) >= 3 else None

        mine = station_rms(station)
        if mine is None:
            continue
        better = [other for other in (station - 1, station + 1)
                  if other in STATIONS and (rms := station_rms(other)) is not None and rms < mine]
        if better:
            identity_errors.append(station)
    result['identity_errors'] = identity_errors
    return result


def run(sheet: Path, truth_path: Path, out: Path, call=None) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    truth = load_truth(truth_path)
    crop = render_crop(sheet, out)
    call = call or ab.call_model
    repeats = []
    for repeat in range(1, REPEATS + 1):
        folder = out / f'R1-{repeat}'
        folder.mkdir()
        messages, started, turns, reading = first_prompt(crop), time.time(), [], None
        for turn in range(1, ab.MAX_TURNS + 1):
            text, receipt = call(messages, folder / 'receipts', ab.ROUNDS['2'])
            (folder / f'reply-{turn}.txt').write_text(text)
            turns.append({k: receipt.get(k) for k in ('state', 'usage', 'seconds', 'finish_reason')})
            try:
                reading = parse_reading(text)
                break
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                messages = messages + [{'role': 'assistant', 'content': text},
                                       {'role': 'user', 'content': f'Invalid reply: {exc}. Reply again with the '
                                                                   'complete JSON object only.'}]
        result = score(reading, truth) if reading is not None else {'truth_cells': len(truth), 'cells_given': 0,
                                                                     'coverage': 0.0}
        result.update(turns=len(turns), seconds=round(time.time() - started, 1),
                      prompt_tokens=sum((t['usage'] or {}).get('prompt_tokens') or 0 for t in turns),
                      completion_tokens=sum((t['usage'] or {}).get('completion_tokens') or 0 for t in turns))
        (folder / 'score.json').write_text(json.dumps(result, indent=2) + '\n')
        repeats.append(result)
        print(json.dumps(result), flush=True)
    rms = [r['rms_m'] for r in repeats if 'rms_m' in r]
    adds_value = (all(r['coverage'] >= MIN_COVERAGE for r in repeats) and len(rms) == REPEATS
                  and float(np.median(rms)) <= MAX_MEDIAN_RMS_M)
    summary = {'protocol': 'docs/plans/2026-11-09-whole-vessel-scope.md 3.5.3', 'r0_cells_read': 0,
               'repeats': repeats, 'median_rms_m': float(np.median(rms)) if rms else None,
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
    print(json.dumps({k: v for k, v in summary.items() if k != 'repeats'}, indent=2))


if __name__ == '__main__':
    main()
