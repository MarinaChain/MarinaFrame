"""Round 9: the round-8 body-plan reader, unchanged, on a holdout sheet (C.A. Thayer, HAER CA-61 sheet 4).

Protocol (fixed before running): docs/plans/2026-11-09-whole-vessel-scope.md, section 3.5.9.
This module only adds the sheet's host calibration, its truth loader and scorer, and the Claude
call (Claude Code CLI in print mode, on the Claude subscription). Measuring, questions, identity
and the decision rule are the round-8 code (`benchmarks.balclutha.crossing_value`).

Usage (outputs and the truth file stay out of the repository; for the Crouton arm load the keys
in the same shell first)::

    source scripts/load_opencode_keys.sh
    PYTHONPATH=src python -m benchmarks.thayer.holdout_value --arm crouton \\
        --sheet work/sources/haer/ca_thayer/loc_ca1506_sheet_04.tif --truth <truth_s4.json> --out <folder>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from benchmarks.balclutha import crossing_value as round8
from benchmarks.balclutha import model_value as round4
from benchmarks.balclutha import router_value as round6
from benchmarks.frozen_readers.v1 import body_plan_crossings as bpc
from benchmarks.frozen_readers.v1 import body_plan_reader as bpr

PROTOCOL = 'docs/plans/2026-11-09-whole-vessel-scope.md 3.5.9'
FEET_M = 0.3048
# Host calibration of sheet 4 (section 3.5.9), from the drawn grid: 600 px per 4 ft.
CENTRE_COLUMN = 8857.5
BASE_ROW = 6081.5
PIXELS_PER_FT = 150.0
PIXELS_PER_M = PIXELS_PER_FT / FEET_M
# Waterline label (feet-inches above base, as printed) -> image row (whole pixels; the drawn line
# is 4 px wide, centred half a pixel lower).
WATERLINE_ROWS = {'3-7': 5543, '5-7': 5243, '7-7': 4943, '9-7': 4643, '11-7': 4343,
                  '13-7': 4043, '15-7': 3743, '17-7': 3443}
WATERLINES = tuple(WATERLINE_ROWS)
# Vertical grid lines: buttocks at 4, 8 and 12 ft and the 20 ft frame of the body-plan grid.
GRID_OFFSETS_FT = (4, 8, 12, 20)
STATIONS = tuple(range(1, 23))
AFT_STATIONS_OUTER_FIRST = tuple(range(12, 23))
FORE_STATIONS_OUTER_FIRST = tuple(range(11, 0, -1))
ARMS = ('code', 'crouton', 'sonnet')
SONNET = 'claude-sonnet-5-5'
CLAUDE_SYSTEM_PROMPT = 'You answer questions about images of ship drawings. Reply with the JSON object only.'
CLAUDE_TIMEOUT_S = 600
# The Claude call must use the subscription login, never an API key.
API_KEY_VARIABLES = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')


def grid_columns(sign: int) -> tuple[float, ...]:
    return tuple(CENTRE_COLUMN + sign * feet * PIXELS_PER_FT for feet in GRID_OFFSETS_FT)


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration of sheet 4: aftbody left of the centreline, forebody right."""
    sides = (bpr.SideLayout('aft', -1, AFT_STATIONS_OUTER_FIRST, grid_columns(-1)),
             bpr.SideLayout('fore', 1, FORE_STATIONS_OUTER_FIRST, grid_columns(1)))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), round8.MAX_OFFSET_PX, sides)


def load_truth(path: Path) -> dict:
    """{(station, waterline label): half-breadth m} for the printed, non-crossed cells."""
    data = json.loads(path.read_text())
    return {(station, waterline): round4.feet_inches_eighths(value)
            for waterline in WATERLINES
            for station, value in zip(data['stations'], data['rows'][waterline]) if value is not None}


def score(table: dict, truth: dict) -> dict:
    return round4.score(table, truth, STATIONS, WATERLINES)


# ---------------------------------------------------------------- Claude (subscription, print mode)

def claude_message(messages: list) -> dict:
    """One stream-json user message from the round-8 chat messages.

    The first message carries the prompt and the image. A later turn (only after an invalid
    reply) is folded into the same user message as text, since print mode takes user turns only.
    """
    first = messages[0]['content']
    text = next(part['text'] for part in first if part['type'] == 'text')
    data_url = next(part['image_url']['url'] for part in first if part['type'] == 'image_url')
    for earlier in messages[1:]:
        speaker = 'Your earlier reply' if earlier['role'] == 'assistant' else 'Note'
        text += f'\n\n{speaker}: {earlier["content"]}'
    image = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                         'data': data_url.split(',', 1)[1]}}
    return {'type': 'user', 'message': {'role': 'user', 'content': [image, {'type': 'text', 'text': text}]}}


def claude_command(model: str) -> list[str]:
    return ['claude', '-p', '--model', model, '--tools', '', '--input-format', 'stream-json',
            '--output-format', 'stream-json', '--verbose', '--no-session-persistence', '--strict-mcp-config',
            '--system-prompt', CLAUDE_SYSTEM_PROMPT]


def claude_call(model: str = SONNET, runner=subprocess.run):
    """A `call(messages, receipts)` through the Claude Code CLI; no tools, no API key."""
    environment = {key: value for key, value in os.environ.items() if key not in API_KEY_VARIABLES}

    def call(messages: list, receipts: Path) -> tuple[str, dict]:
        started = time.time()
        receipt = {'model': model, 'access': 'claude -p (subscription)'}
        try:
            done = runner(claude_command(model), input=json.dumps(claude_message(messages)) + '\n',
                          capture_output=True, text=True, env=environment, timeout=CLAUDE_TIMEOUT_S)
            result = next((json.loads(line) for line in done.stdout.splitlines()
                           if line.startswith('{') and json.loads(line).get('type') == 'result'), None)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            result, receipt['error'] = None, type(exc).__name__
        text = (result or {}).get('result') or ''
        usage = (result or {}).get('usage') or {}
        completed = result is not None and result.get('subtype') == 'success' and not result.get('is_error')
        receipt.update(state='completed' if completed else 'failed', seconds=round(time.time() - started, 1),
                       answered_by=model,
                       usage={'prompt_tokens': sum(usage.get(key) or 0 for key in (
                           'input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')),
                              'completion_tokens': usage.get('output_tokens')})
        receipts.mkdir(parents=True, exist_ok=True)
        with (receipts / 'claude.jsonl').open('a') as log:
            log.write(json.dumps(receipt) + '\n')
        return text, receipt

    return call


# ---------------------------------------------------------------- run

def run(arm: str, sheet_path: Path, truth_path: Path, out: Path, call=None) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    truth = load_truth(truth_path)
    sheet_pixels = bpc.load_ink(sheet_path)
    layout = sheet_layout()
    started = time.time()
    readings = round8.measure(sheet_pixels, layout)
    measured = {'seconds': round(time.time() - started, 1), 'sides': round8.measurement_summary(readings)}
    print(json.dumps({'measurement': measured}), flush=True)
    results = []
    repeats = 1 if arm == 'code' else round4.REPEATS
    if arm == 'code':
        results.append(round8.run_code(readings, layout, truth, scorer=score))
        print(json.dumps(results[-1]), flush=True)
    else:
        questions = round8.build_questions(sheet_pixels, readings, layout)
        if call is None:
            call = round8.crouton_with_fallback() if arm == 'crouton' else claude_call(SONNET)
        for repeat in range(1, repeats + 1):
            results.append(round8.run_repeat(readings, questions, layout, truth, out / f'R1-{repeat}', call,
                                             scorer=score))
            print(json.dumps(results[-1]), flush=True)
    median, passes = round6.decide(results, repeats)
    summary = {'protocol': PROTOCOL, 'arm': arm, 'measurement': measured, 'repeats': results,
               'median_rms_m': median, 'passes_rule': passes, 'engineering_approved': False}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm', choices=ARMS, required=True)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.arm == 'crouton':
        round6.load_go_key1()
    summary = run(args.arm, args.sheet, args.truth, args.out.resolve())
    print(json.dumps({key: value for key, value in summary.items() if key != 'repeats'}, indent=2))


if __name__ == '__main__':
    main()
