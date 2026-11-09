"""Balclutha sheet 7 model-value test with Claude subagents (round 7, protocol section 3.5.7).

Claude Sonnet 5.5 and Opus 5.5 run as Claude Code subagents on the Claude subscription, started by
a person (never through the router or OpenCode Go). A subagent reads image files with its file Read
tool and writes one answer JSON file. This module has two commands:

    pack   cut the tile pack (tiles, 1/4-scale context images, per-tile text, TASK.md)
    score  score answer files with the round-4 scorer and the fixed decision rule

Usage (outputs stay out of the repository; the truth file is never in the pack)::

    PYTHONPATH=src python -m benchmarks.balclutha.claude_value pack \\
        --sheet work/sources/balclutha_ca54_s7.tif --out <pack folder>
    PYTHONPATH=src python -m benchmarks.balclutha.claude_value score --answers <folder of answer files>

Answer files are named ``<model>-<repeat>.json`` (for example ``sonnet-5.5-1.json``); files with
the same ``<model>`` form one set of repeats.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from benchmarks.balclutha import model_value as round4
from benchmarks.balclutha import router_value as round6
from benchmarks.balclutha import tiled_value as round5

# Claude downsamples an image whose long edge is over 1568 px; the tiles keep the sheet's own pixels.
CLAUDE_MAX_EDGE = 1568
# Three tiles per side and waterline, each 1568 x 784 px, covering 48 px across the centreline to
# 4,080 px out (the round-6 span ends at 4,048 px); neighbours overlap by 288 px.
CLAUDE_LAYOUT = {'width': CLAUDE_MAX_EDGE, 'height': CLAUDE_MAX_EDGE // 2,
                 'spans': {'near': (-48, 1520), 'mid': (1232, 2800), 'far': (2512, 4080)}}
# The fixed truth file of rounds 4 to 6 (outside the repository; the pack command never reads it).
DEFAULT_TRUTH = Path('/private/tmp/claude-501/-Users-jonathanjie-Documents-workspace/'
                     '31a3f286-f3b9-4116-93bc-756e11ead9ee/scratchpad/wv-agent/balclutha/truth_s7.json')

TILE_TEXT = """TILE {tile_id}
Read these two image files (use your file Read tool):
  Image 1: context/{tile_id}.png - the whole {side_name} of the body plan at 1/4 scale, each curve
           labelled with its station number ({first} to {last}). The red box is the area of image 2.
  Image 2: tiles/{tile_id}.png - a tile at FULL resolution ({width} x {height} px) of that red box.

Find every station curve ({first} to {last}) that crosses the {waterline} ft waterline INSIDE image 2.
The {waterline} ft waterline is the horizontal grid line at y = {row} px in image 2.
Calibration of image 2: the centreline is at x = {cx} px (it can lie outside the tile);
{ppm} px per metre; half-breadth (m) = |x - ({cx})| / {ppm}.
Grid lines inside image 2: waterlines {waterlines}; vertical buttock lines {buttocks}.
In this half the station curves are nested: {order}.
Ignore: half stations (11 1/2, 12 1/2), the straight diagonals (DIAGONAL A, B, C), the dashed sheer line,
rub rail and deck-edge lines, grid lines and lettering. Leave out a station that does not cross the
{waterline} ft waterline inside image 2.
Result for this tile: a list of (station, x pixel in image 2); then the half-breadth in metres.
"""

TASK_TEMPLATE = """# Task: read station half-breadths from the Balclutha body plan

You read a scanned drawing: the BODY PLAN of the sailing ship Balclutha (HAER CA-54, sheet 7).
Stations 0 to 10 (aftbody) are drawn LEFT of the centreline, stations 11 to 20 (forebody) RIGHT of it.
Waterlines are drawn every 4 ft (4, 8, ..., 32 ft above the base line). Dimensions are to the inner
surface of the hull. You read the curves in the images; you do not look up or recall any table.

This pack has {count} tiles. Each tile is a piece of the sheet at its own resolution (no resampling),
one waterline per tile, with three tiles per side and waterline that overlap each other.

## Files (read in this order)

1. This file (TASK.md).
2. For each side and waterline below, in this order: read `text/<tile id>.txt` of each tile of
   the group, then its two images: `context/<tile id>.png` (1/4-scale side with a red box) and
   `tiles/<tile id>.png` (the tile). The text file gives the tile's calibration and grid positions.

{groups}

## Method

For each tile, follow its text file: find where each station curve crosses the target waterline
inside the tile, note the x pixel, and convert it with the calibration in the text file:
half-breadth (m) = |x - centreline x| / 491.48 (the text file gives the centreline x in tile pixels,
which can be outside the tile). Use the grid lines (buttock lines, waterline) to check your x values.
Station numbers come from the context image; the stations are nested, so the order at a waterline
is fixed (see the text file). A station that does not reach a waterline (the low stations do not reach
the low waterlines on the aft side, the high stations on the fore side) gets null.
If a curve crosses in two overlapping tiles, take the mean of the two half-breadths.
Read the curves; do not invent values. If you cannot see a crossing, give null.
Use only the files in this pack. Do not look for other files on the computer (for example the
sheet, a table or earlier answers).

## Answer

Write ONE JSON object to the answer path you were given, and write nothing else to disk:

    {{"source": "ai_inferred", "waterlines_ft": [4, 8, 12, 16, 20, 24, 28, 32],
      "stations": {{"0": [v4, v8, v12, v16, v20, v24, v28, v32], "1": [...], ..., "20": [...]}}}}

- Keys "0" to "20": all 21 stations.
- Each list has 8 values in the order of `waterlines_ft`: the half-breadth in metres (0 to 10) where the
  station curve crosses that waterline, or null where it does not (or you cannot see it).
- Every value is ai_inferred (the `source` field says so).
- Valid JSON only: no comments and no trailing commas.
When the file is written, reply with only the path of the file.
"""


def tile_text(tile: dict) -> str:
    """The round-6 prompt for one tile, adapted to files (the same numbers as `tiled_value.tile_prompt`)."""
    grid = round5.tile_grid(tile)
    side_name, order = round5.SIDE_TEXT[tile['side']]
    stations = round5.SIDE_STATIONS[tile['side']]
    waterlines = ', '.join(f'{ft} ft at y = {row}' for ft, row in grid['waterlines'].items()) or 'none'
    buttocks = ', '.join(f'{ft} ft ({ft * round4.FEET_M:.3f} m) at x = {column}'
                         for ft, column in grid['buttocks'].items()) or 'none'
    width, height = round5.tile_size(tile)
    return TILE_TEXT.format(tile_id=tile['id'], side_name=side_name, first=stations[0], last=stations[-1],
                            width=width, height=height, waterline=tile['waterline'], row=grid['target_row'],
                            cx=grid['centreline_x'], ppm=round5.PIXELS_PER_M, waterlines=waterlines,
                            buttocks=buttocks, order=order)


def task_text(tiles: list[dict]) -> str:
    groups = []
    for side in ('aft', 'fore'):
        stations = round5.SIDE_STATIONS[side]
        for waterline in round4.WATERLINES_FT:
            ids = [t['id'] for t in tiles if t['side'] == side and t['waterline'] == waterline]
            groups.append(f'- {side} half, {waterline} ft waterline (stations {stations[0]} to {stations[-1]}): '
                          + ', '.join(ids))
    return TASK_TEMPLATE.format(count=len(tiles), groups='\n'.join(groups))


def build_pack(sheet_path: Path, out: Path) -> list[dict]:
    """Cut the pack into `out` (a new folder): tiles, context images, per-tile text, TASK.md."""
    out.mkdir(parents=True, exist_ok=False)
    for name in ('tiles', 'context', 'text'):
        (out / name).mkdir()
    sheet = round5.load_sheet(sheet_path)
    tiles = round5.tile_boxes(CLAUDE_LAYOUT)
    for tile in tiles:
        width, height = round5.tile_size(tile)
        if max(width, height) > CLAUDE_MAX_EDGE:
            raise ValueError(f'tile {tile["id"]} is {width} x {height} px, over {CLAUDE_MAX_EDGE}')
        (out / 'tiles' / f'{tile["id"]}.png').write_bytes(round5.png_bytes(round5.tile_pixels(sheet, tile)))
        (out / 'context' / f'{tile["id"]}.png').write_bytes(round5.context_image(sheet, tile))
        (out / 'text' / f'{tile["id"]}.txt').write_text(tile_text(tile))
    (out / 'TASK.md').write_text(task_text(tiles))
    return tiles


# ---------------------------------------------------------------- scoring

ANSWER_NAME = re.compile(r'^(?P<model>.+)-(?P<repeat>\d+)\.json$')


def score_answer(path: Path, truth: dict) -> dict:
    """Round-4 score of one answer file; an unreadable or invalid file scores zero cells (as round 4)."""
    try:
        reading = round4.parse_reading(path.read_text())
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        return {'truth_cells': len(truth), 'cells_given': 0, 'coverage': 0.0, 'invalid': str(exc)[:200]}
    return round4.score(reading, truth)


def score_folder(answers: Path, truth: dict, repeats: int = round4.REPEATS) -> dict:
    """Score every `<model>-<n>.json` in `answers`; the fixed decision rule per model."""
    results: dict[str, list[dict]] = {}
    for path in sorted(answers.glob('*.json')):
        match = ANSWER_NAME.match(path.name)
        if match:
            results.setdefault(match['model'], []).append({'file': path.name, **score_answer(path, truth)})
    models = {}
    for model, scored in results.items():
        median, adds_value = round6.decide(scored, repeats)
        models[model] = {'repeats': scored, 'median_rms_m': median, 'model_adds_value': adds_value,
                         'engineering_approved': False}
    return {'protocol': 'docs/plans/2026-11-09-whole-vessel-scope.md 3.5.7', 'models': models}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('pack')
    pack.add_argument('--sheet', type=Path, required=True)
    pack.add_argument('--out', type=Path, required=True)
    score = commands.add_parser('score')
    score.add_argument('--answers', type=Path, required=True)
    score.add_argument('--truth', type=Path, default=DEFAULT_TRUTH)
    args = parser.parse_args()
    if args.command == 'pack':
        print(f'{len(build_pack(args.sheet, args.out.resolve()))} tiles in {args.out}')
    else:
        print(json.dumps(score_folder(args.answers, round4.load_truth(args.truth)), indent=2))


if __name__ == '__main__':
    main()
