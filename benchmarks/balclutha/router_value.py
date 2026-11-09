"""Balclutha sheet 7 model-value test with stronger vision models through codex-router (round 6).

Protocol (fixed before running): docs/plans/2026-11-09-whole-vessel-scope.md, section 3.5.5.
Same task, prompt, merge, metrics and decision rule as round 5 (`tiled_value`); only the model,
the tile size (4096 x 2048 px, one tile per side and waterline) and the request settings change.

The models are called through the local codex-router (OpenAI Responses API). The router's caller
secret is read into this process's environment only; it is never printed, logged or stored.

Usage (outputs stay out of the repository)::

    PYTHONPATH=src python -m benchmarks.balclutha.router_value --model gpt-6.1-sol \\
        --sheet work/sources/balclutha_ca54_s7.tif --truth <truth_s7.json> --out <folder outside the repo>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np

from benchmarks.balclutha import model_value as round4
from benchmarks.balclutha import tiled_value as round5

ROUTER_PORT = 4202
CALLER_SECRET_FILE = Path.home() / '.codex' / 'codex-router' / 'caller-secret'
SECRET_ENV = 'CODEX_ROUTER_CALLER_SECRET'
MODELS = ('gpt-6.1-sol', 'gpt-6-astra')
REASONING_EFFORT = 'high'
MAX_OUTPUT_TOKENS = 32_000
REQUEST_TIMEOUT_S = 1800
# Effective resolution with detail "original" is 5,120 px per side for both models (protocol
# 3.5.5); one 4096 px tile spans the whole half-breadth, from 48 px across the centreline to
# 4,048 px out (past the 20 ft buttock at 2,990 px).
ROUND6_LAYOUT = {'width': 4096, 'height': 2048, 'spans': {'whole': (-48, 4048)}}


def load_caller_secret() -> None:
    """Put the router caller secret into this process's environment (never printed)."""
    if not os.environ.get(SECRET_ENV):
        os.environ[SECRET_ENV] = CALLER_SECRET_FILE.read_text().strip()


def router_url() -> str:
    return f'http://127.0.0.1:{ROUTER_PORT}/_codex-router/{os.environ[SECRET_ENV]}/v1/responses'


def responses_input(messages: list) -> list:
    """Chat-completions messages (as `tiled_value.first_prompt` builds them) to Responses input items.

    Images are sent with detail "original" so the provider does not resample them.
    """
    items = []
    for message in messages:
        if message['role'] == 'assistant':
            items.append({'role': 'assistant', 'content': [{'type': 'output_text', 'text': message['content']}]})
            continue
        content = message['content']
        if isinstance(content, str):
            content = [{'type': 'text', 'text': content}]
        parts = []
        for part in content:
            if part['type'] == 'text':
                parts.append({'type': 'input_text', 'text': part['text']})
            elif part['type'] == 'image_url':
                parts.append({'type': 'input_image', 'image_url': part['image_url']['url'], 'detail': 'original'})
            else:
                raise ValueError(f'unknown content part {part["type"]!r}')
        items.append({'role': message['role'], 'content': parts})
    return items


def request_body(model: str, messages: list) -> dict:
    return {'model': model, 'input': responses_input(messages), 'reasoning': {'effort': REASONING_EFFORT},
            'max_output_tokens': MAX_OUTPUT_TOKENS, 'stream': False, 'store': False}


def final_response(raw: bytes) -> dict:
    """The response object; the router may answer with server-sent events even when not asked to."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        final = {}
        for line in raw.decode(errors='replace').splitlines():
            if not line.startswith('data:'):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if event.get('type') in ('response.completed', 'response.incomplete', 'response.failed'):
                final = event.get('response', {})
        return final


def output_text(response: dict) -> str:
    return ''.join(part.get('text', '') for item in response.get('output', []) if item.get('type') == 'message'
                   for part in item.get('content', []) if part.get('type') == 'output_text')


def usage_counts(usage: dict | None) -> dict:
    """Responses usage in the round-5 receipt keys (prompt / completion tokens) plus reasoning tokens."""
    usage = usage or {}
    return {'prompt_tokens': usage.get('input_tokens'), 'completion_tokens': usage.get('output_tokens'),
            'reasoning_tokens': (usage.get('output_tokens_details') or {}).get('reasoning_tokens')}


def make_call(model: str, opener=urllib.request.urlopen):
    """A `call(messages, receipts, settings)` for `tiled_value.run_repeat`; settings are fixed here."""

    def call(messages: list, receipts: Path, _settings: dict) -> tuple[str, dict]:
        body = json.dumps(request_body(model, messages)).encode()
        request_id = uuid.uuid4().hex
        receipt = {'request_id': request_id, 'model': model, 'reasoning_effort': REASONING_EFFORT,
                   'request_sha256': hashlib.sha256(body).hexdigest(), 'request_bytes': len(body)}
        started = time.time()
        try:
            request = urllib.request.Request(router_url(), data=body, method='POST',
                                             headers={'Content-Type': 'application/json'})
            with opener(request, timeout=REQUEST_TIMEOUT_S) as response:
                reply = final_response(response.read())
            text = output_text(reply)
            receipt.update(state='completed', returned_model=reply.get('model'), finish_reason=reply.get('status'),
                           usage=usage_counts(reply.get('usage')),
                           reply_sha256=hashlib.sha256(text.encode()).hexdigest())
        except Exception as exc:  # noqa: BLE001 - a failed request is recorded, not hidden
            message = f'{type(exc).__name__}: {exc}'.replace(os.environ.get(SECRET_ENV) or '\0', '<secret>')
            text, receipt['state'], receipt['error'] = '', 'failed', message[:500]
        receipt['seconds'] = time.time() - started
        receipts.mkdir(parents=True, exist_ok=True)
        (receipts / f'{request_id}.json').write_text(json.dumps(receipt, indent=2) + '\n')
        return text, receipt

    return call


def decide(results: list[dict], repeats: int = round4.REPEATS) -> tuple[float | None, bool]:
    """Median RMS and the fixed decision rule (section 3.5.3, unchanged)."""
    rms = [r['rms_m'] for r in results if 'rms_m' in r]
    median = float(np.median(rms)) if rms else None
    adds_value = (len(results) == repeats and all(r['coverage'] >= round4.MIN_COVERAGE for r in results)
                  and len(rms) == repeats and median <= round4.MAX_MEDIAN_RMS_M)
    return median, adds_value


def run(model: str, sheet_path: Path, truth_path: Path, out: Path, call=None, repeats: int = round4.REPEATS) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    truth = round4.load_truth(truth_path)
    sheet = round5.load_sheet(sheet_path)
    tiles = round5.tile_boxes(ROUND6_LAYOUT)
    images = {tile['id']: (round5.context_image(sheet, tile), round5.png_bytes(round5.tile_pixels(sheet, tile)))
              for tile in tiles}
    call = call or make_call(model)
    results = []
    for repeat in range(1, repeats + 1):
        result = round5.run_repeat(tiles, images, truth, out / f'R1-{repeat}', call)
        result['reasoning_tokens'] = sum(
            (json.loads(path.read_text()).get('usage') or {}).get('reasoning_tokens') or 0
            for path in (out / f'R1-{repeat}' / 'receipts').glob('*.json'))
        results.append(result)
        print(json.dumps(result), flush=True)
    median, adds_value = decide(results, repeats)
    summary = {'protocol': 'docs/plans/2026-11-09-whole-vessel-scope.md 3.5.5', 'model': model,
               'reasoning_effort': REASONING_EFFORT, 'layout': ROUND6_LAYOUT, 'repeats': results,
               'median_rms_m': median, 'model_adds_value': adds_value, 'engineering_approved': False}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=MODELS, required=True)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    load_caller_secret()
    summary = run(args.model, args.sheet, args.truth, args.out.resolve())
    print(json.dumps({key: value for key, value in summary.items() if key != 'repeats'}, indent=2))


if __name__ == '__main__':
    main()
