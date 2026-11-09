"""Balclutha sheet 7, round 7: code measures every crossing, a low-cost model only identifies.

Protocol (fixed before running): docs/plans/2026-11-09-whole-vessel-scope.md, section 3.5.8.
Code traces every ink crossing of each waterline at full resolution and links them into one
chain per drawn curve (`vessel_reconstruction.body_plan_reader`). R0 numbers the chains by
nesting order alone. R1 asks a model one question per chain on a crop with the curve traced in
red: which station number labels it (`vessel_reconstruction.body_plan_identity`). Values are
always the code-measured columns. Same truth, metrics and decision rule as rounds 4 to 6.

Usage (outputs stay out of the repository; for R1 load the keys in the same shell first)::

    source scripts/load_opencode_keys.sh
    PYTHONPATH=src python -m benchmarks.balclutha.crossing_value --arm crouton \\
        --sheet work/sources/balclutha_ca54_s7.tif --truth <truth_s7.json> --out <folder outside the repo>
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from benchmarks.balclutha import model_value as round4
from benchmarks.balclutha import router_value as round6
from benchmarks.balclutha import tiled_value as round5
from benchmarks.gunnerus import whole_vessel_ab as ab
from vessel_reconstruction import body_plan_identity as bpi
from vessel_reconstruction import body_plan_reader as bpr

PROTOCOL = 'docs/plans/2026-11-09-whole-vessel-scope.md 3.5.8'
# Stations are drawn out to the 20 ft buttock (2,990 px from the centreline); 3,150 px leaves room.
MAX_OFFSET_PX = 3150
# A crop keeps to its own half: at most this many px across the centreline.
CROP_ACROSS_CENTRE_PX = 40
WORKERS = 4
# The truth cell that rounds 5 and 6 found doubtful (24 ft, station 18); reported, not removed.
DOUBTFUL_CELL = (18, 24)
ARMS = ('code', 'crouton', 'astra')
CROUTON = 'crouton-alpha-free'
ASTRA = 'gpt-6-astra'


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration of sheet 7 (section 3.5.4), both halves."""
    sides = (bpr.SideLayout('aft', -1, tuple(range(10, -1, -1)), round5.BUTTOCK_COLUMNS['aft']),
             bpr.SideLayout('fore', 1, tuple(range(11, 21)), round5.BUTTOCK_COLUMNS['fore']))
    return bpr.SheetLayout(round5.CENTRE_COLUMN, round5.PIXELS_PER_M,
                           {w: round5.WATERLINE_ROWS[w] for w in round4.WATERLINES_FT}, MAX_OFFSET_PX, sides)


SIDE_NAMES = {'aft': 'aftbody (stern half, left of the centreline)',
              'fore': 'forebody (bow half, right of the centreline)'}


def measure(sheet_pixels: np.ndarray, layout: bpr.SheetLayout) -> dict[str, bpr.SideReading]:
    ink = sheet_pixels < 128
    return {side.name: bpr.measure_side(ink, layout, side) for side in layout.sides}


def table_and_flags(readings: dict, identities: dict, layout: bpr.SheetLayout) -> tuple[dict, list]:
    table, flags = {}, []
    for name, reading in readings.items():
        side_table = bpr.table_from_identities(reading, identities[name], layout.pixels_per_metre,
                                               layout.centre_column)
        flags += [dict(flag, side=name) for flag in bpr.fairness_flags(
            side_table, reading.layout.stations_outer_first, layout.waterlines_low_to_high())]
        table.update(side_table)
    return table, flags


def score(table: dict, truth: dict) -> dict:
    result = round4.score(table, truth)
    without = {key: value for key, value in truth.items() if key != DOUBTFUL_CELL}
    secondary = round4.score(table, without)
    result['rms_without_doubtful_cell_m'] = secondary.get('rms_m')
    return result


def measurement_summary(readings: dict) -> dict:
    return {name: {'chains': len(r.chains), 'one_waterline_chains': sum(1 for c in r.chains if len(c.nodes) == 1),
                   'inferred_links': sum(c.inferred_links for c in r.chains),
                   'crossings_by_kind': _kinds(r)} for name, r in readings.items()}


def _kinds(reading: bpr.SideReading) -> dict:
    counts: dict = {}
    for found in reading.crossings.values():
        for crossing in found:
            counts[crossing.kind] = counts.get(crossing.kind, 0) + 1
    return counts


# ---------------------------------------------------------------- R0 (code only)

def run_code(readings: dict, layout: bpr.SheetLayout, truth: dict, scorer=None) -> dict:
    identities = {name: bpr.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in readings.items()}
    table, flags = table_and_flags(readings, identities, layout)
    result = (scorer or score)(table, truth)
    result.update(fairness_flags=len(flags), calls=0)
    return result


# ---------------------------------------------------------------- R1 (model)

def question_messages(prompt: str, png: bytes) -> list:
    url = 'data:image/png;base64,' + base64.b64encode(png).decode()
    return [{'role': 'user', 'content': [{'type': 'text', 'text': prompt},
                                         {'type': 'image_url', 'image_url': {'url': url}}]}]


def crouton_with_fallback(crouton=None, deepseek=None):
    """Crouton Alpha Free; on a failed request one retry, then DeepSeek V4.1 Flash (thinking off)."""
    crouton = crouton or round6.make_go_call(CROUTON)
    deepseek = deepseek or (lambda messages, receipts: ab.call_model(messages, receipts, ab.ROUNDS['2']))

    def call(messages: list, receipts: Path) -> tuple[str, dict]:
        for _ in range(2):
            text, receipt = crouton(messages, receipts, {})
            if receipt.get('state') == 'completed':
                return text, dict(receipt, answered_by=CROUTON)
            time.sleep(5)
        text, receipt = deepseek(messages, receipts)
        return text, dict(receipt, answered_by=ab.GO_MODEL)

    return call


def router_call(model: str):
    inner = round6.make_call(model)

    def call(messages: list, receipts: Path) -> tuple[str, dict]:
        text, receipt = inner(messages, receipts, {})
        return text, dict(receipt, answered_by=model)

    return call


def ask_label(question: dict, folder: Path, call) -> dict:
    """One label question, at most ab.MAX_TURNS turns (later turns only after an invalid reply)."""
    messages, turns, label, invalid, valid = question['messages'], [], None, 0, False
    for turn in range(1, ab.MAX_TURNS + 1):
        text, receipt = call(messages, folder / 'receipts')
        (folder / f'{question["id"]}-reply-{turn}.txt').write_text(text)
        turns.append({key: receipt.get(key) for key in ('state', 'usage', 'seconds', 'answered_by')})
        try:
            label, valid = bpi.parse_label(text, question['stations']), True
            break
        except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            invalid += 1
            messages = messages + [{'role': 'assistant', 'content': text},
                                   {'role': 'user', 'content': f'Invalid reply: {exc}. Reply again with the '
                                                               'JSON object only.'}]
    return {'id': question['id'], 'label': label, 'valid': valid, 'turns': turns, 'invalid_replies': invalid}


def build_questions(sheet_pixels: np.ndarray, readings: dict, layout: bpr.SheetLayout) -> list[dict]:
    questions = []
    for name, reading in readings.items():
        side = reading.layout
        limits = sorted((int(layout.centre_column - side.sign * CROP_ACROSS_CENTRE_PX),
                         int(layout.centre_column + side.sign * layout.max_offset_px * 1.2)))
        prompt = bpi.label_prompt(SIDE_NAMES[name], side.stations_outer_first)
        for index, chain in enumerate(reading.chains):
            png, geometry = bpi.question_image(sheet_pixels, chain, (limits[0], limits[1]))
            questions.append({'id': f'{name}-chain{index:02d}', 'side': name, 'chain': index, 'geometry': geometry,
                              'stations': side.stations_outer_first, 'messages': question_messages(prompt, png)})
    return questions


def run_repeat(readings: dict, questions: list[dict], layout: bpr.SheetLayout, truth: dict, folder: Path,
               call, scorer=None) -> dict:
    folder.mkdir()
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = list(pool.map(lambda q: ask_label(q, folder, call), questions))
    labels = {name: {} for name in readings}
    for question, answer in zip(questions, answers):
        labels[question['side']][question['chain']] = answer['label']
    identities, summaries, reasked = {}, {}, []
    for name, reading in readings.items():
        _, summary = bpi.identities_from_labels(reading, labels[name])
        # Ask again where a label disagrees with the best numbering (a fresh request each).
        again = [q for q in questions if q['side'] == name and q['chain'] in summary['disagreeing_chains']]
        for question in again:
            second = ask_label(dict(question, id=question['id'] + '-again'), folder, call)
            reasked.append(second)
            labels[name][question['chain']] = second['label']
        identities[name], summaries[name] = bpi.identities_from_labels(reading, labels[name])
    table, flags = table_and_flags(readings, identities, layout)
    result = (scorer or score)(table, truth)
    rank = {name: bpr.identities_by_rank(r.chains, r.layout.stations_outer_first) for name, r in readings.items()}
    every = answers + reasked
    turns = [turn for answer in every for turn in answer['turns']]
    result.update(
        fairness_flags=len(flags), questions=len(questions), reasked=len(reasked), calls=len(turns),
        invalid_replies=sum(a['invalid_replies'] for a in every),
        unanswered=sum(1 for a in every if not a['valid']),
        failed_requests=sum(1 for t in turns if t['state'] != 'completed'),
        answered_by={model: sum(1 for t in turns if t.get('answered_by') == model)
                     for model in {t.get('answered_by') for t in turns}},
        labels_equal_to_code_rank=sum(1 for name in labels for chain, label in labels[name].items()
                                      if label is not None and rank[name].get(chain) == label),
        labels_null=sum(1 for name in labels for label in labels[name].values() if label is None),
        identity_summaries=summaries, identities_differ_from_code=sum(
            1 for name in identities for chain, station in identities[name].items()
            if rank[name].get(chain) != station),
        seconds=round(time.time() - started, 1),
        prompt_tokens=sum((t['usage'] or {}).get('prompt_tokens') or 0 for t in turns),
        completion_tokens=sum((t['usage'] or {}).get('completion_tokens') or 0 for t in turns))
    (folder / 'labels.json').write_text(json.dumps({name: {str(k): v for k, v in found.items()}
                                                    for name, found in labels.items()}, indent=2) + '\n')
    (folder / 'score.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


# ---------------------------------------------------------------- run

def run(arm: str, sheet_path: Path, truth_path: Path, out: Path, call=None, repeats: int = round4.REPEATS) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    truth = round4.load_truth(truth_path)
    sheet_pixels = round5.load_sheet(sheet_path)
    layout = sheet_layout()
    started = time.time()
    readings = measure(sheet_pixels, layout)
    measured = {'seconds': round(time.time() - started, 1), 'sides': measurement_summary(readings)}
    print(json.dumps({'measurement': measured}), flush=True)
    results = []
    if arm == 'code':
        for repeat in range(1, repeats + 1):
            results.append(run_code(readings, layout, truth))
            print(json.dumps(results[-1]), flush=True)
    else:
        questions = build_questions(sheet_pixels, readings, layout)
        if call is None:
            call = crouton_with_fallback() if arm == 'crouton' else router_call(ASTRA)
        for repeat in range(1, repeats + 1):
            results.append(run_repeat(readings, questions, layout, truth, out / f'R1-{repeat}', call))
            print(json.dumps(results[-1]), flush=True)
    median, adds_value = round6.decide(results, repeats)
    summary = {'protocol': PROTOCOL, 'arm': arm, 'measurement': measured, 'repeats': results,
               'median_rms_m': median, 'passes_rule': adds_value, 'engineering_approved': False}
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
    elif args.arm == 'astra':
        round6.load_caller_secret()
    summary = run(args.arm, args.sheet, args.truth, args.out.resolve())
    print(json.dumps({key: value for key, value in summary.items() if key != 'repeats'}, indent=2))


if __name__ == '__main__':
    main()
