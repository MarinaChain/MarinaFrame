"""Whole-vessel A/B: DeepSeek writes ship-cad JSON (arm A) or CadQuery code (arm B).

Protocol (fixed before running): docs/plans/2026-11-09-whole-vessel-scope.md, section 3.5.
Both arms get the same evidence pack (three GA renders with calibration, the title block
and the deterministic step 1 reading), the same model, limits and scorer.

Load the keys in the same shell first (never print them)::

    source scripts/load_opencode_keys.sh
    PYTHONPATH=src python -m benchmarks.gunnerus.whole_vessel_ab \\
        --sources work/sources/gunnerus --out work/whole-vessel/ab-001 \\
        --truth-mesh <truth dir>/truth_mesh.npz

Outputs are drawing derivatives and provider receipts: keep them in a git-ignored folder.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

GO_MODEL = 'deepseek-v4.1-flash'
GO_ENDPOINT = 'https://opencode.ai/inference/go/openai/v1/chat/completions'
MAX_TURNS = 3
TEMPERATURE = 0.2
# Request settings per protocol round (plan sections 3.5 and 3.5.1). Round 1 left thinking at
# the provider default; every arm B reply spent its budget on hidden reasoning.
ROUNDS = {
    '1': {'max_tokens': 16_000, 'thinking': None},
    '2': {'max_tokens': 32_000, 'thinking': 'disabled'},
}
REPEATS = 3
REQUEST_TIMEOUT_S = 600
BUILD_TIMEOUT_S = 120
# Environment variables that arm B code may see (CadQuery and OCP need none beyond these).
BUILD_ENV_ALLOW = ('PATH', 'LANG', 'LC_ALL', 'LC_CTYPE')
COMPONENTS = {
    'aft_deck': 'aft working deck plate (open deck aft of the superstructure, on the aft deck level)',
    'main_deck': '1-deck plate under the superstructure',
    'house_t1': 'first superstructure tier: solid from 1-deck up to A-deck (its roof is the A-deck)',
    'aft_bulwark': 'bulwark wall along the aft working deck edge',
    'house_t2': 'second tier deckhouse standing on the A-deck',
    'wheelhouse': 'wheelhouse on top of the second tier',
    'fwd_rail': 'rail or bulwark around the forward part of the A-deck',
}
SCORED = ('aft_deck', 'house_t1', 'aft_bulwark')
RENDER_VIEWS = ('profile', 'plan_1deck', 'plan_adeck')


# ---------------------------------------------------------------- evidence pack

def render_pack(sources: Path, out: Path) -> dict:
    """Render the GA views (all layers and labels) and write each pixel-to-metre calibration."""
    from benchmarks.gunnerus.whole_vessel import GA_FILE, VIEWS
    from benchmarks.ship_cad.run import render_view

    images = []
    for name in RENDER_VIEWS:
        view = VIEWS[name]
        spec = {'name': name, 'file': str(sources / GA_FILE), 'bounds': view.bounds}
        meta = render_view(spec, out / f'{name}.png')
        x0, y0, x1, y1 = view.bounds
        mpu = view.metres_per_unit
        # render_view maps drawing x linearly to [0, width] and drawing y to [height, 0].
        sx = (x1 - x0) / meta['width'] * mpu
        sy = (y1 - y0) / meta['height'] * mpu
        vertical = 'z' if view.kind == 'profile' else 'y'
        meta['calibration'] = {
            'x_m': f'{(x0 - view.origin[0]) * mpu:.4f} + {sx:.6f} * px',
            f'{vertical}_m': f'{(y1 - view.origin[1]) * mpu:.4f} - {sy:.6f} * py',
        }
        images.append(meta)
    return {'images': images}


def reading_text(inputs: dict) -> str:
    """The deterministic step 1 reading, as compact text for the prompt."""
    lines = ['Profile levels read by code (z m; x extents m):']
    for name, level in inputs['levels'].items():
        lines.append(f'- {name}: z={level["z"]} extent={level.get("x_range") or level["extent"]} '
                     f'({level["source"]}, {level["basis"]})')
    lines.append('Plan footprints read by code (closed outline, [x, y] m):')
    for key, record in inputs['measurements'].items():
        if record['kind'] == 'outline' and not key.startswith('aft_bulwark'):
            points = [[round(x, 2), round(y, 2)] for x, y in record['value']]
            lines.append(f'- {key} from {record.get("plan_view")}: {json.dumps(points)}')
    for key, guess in inputs['guesses'].items():
        lines.append(f'- {key}: code GUESS {json.dumps(guess["value"])} ({guess["basis"]})')
    return '\n'.join(lines)


COMMON = """You draft a 3D CAD model of the research vessel Gunnerus from its General Arrangement (GA).
Coordinates are metres: x from frame 0, positive forward; y positive to port, 0 on the centreline;
z up from the baseline. Title block: LOA 36.25, LPP 33.90, breadth moulded 9.60, depth to 1-deck
4.287, depth to A-deck 6.687, draught 2.50, frame distance 0.500.

Images (rendered from the GA vector file; calibration converts pixels to metres):
{images}

Code read the drawing first. Its reading can be incomplete or wrong; values marked GUESS are code
gap fills. Use it, check it against the images, and correct it where the images show otherwise.
{reading}

Build exactly these components (use these ids). Never leave one out: when the drawing does not
show a value, give your best estimate and say so in the basis.
{components}
Decks are plates whose top is the deck level. Deckhouse tiers are solid blocks from their base
deck to their roof, with the plan outline of their outer walls. Bulwarks and rails are thin walls
along the deck edge. Do not model the hull.
"""

FORMAT_A = """Reply with ONE JSON object only (no prose), in the ship-cad/v1 language:
{"schema":"ship-cad/v1","components":[
  {"id":"house_t1","op":"deckhouse",
   "source":{"view":"plan","region":"house_t1","method":"closed_outline"},
   "args":{"outline":{"value":[[x,y],...],"source":"ai_inferred","basis":"short reason"},
           "height":{"value":[z_low,z_high],"source":"ai_inferred","basis":"short reason"}}}]}
Operations and their args: deck {outline, height}; deckhouse {outline, height};
bulwark {outline, height, thickness}. outline: plan polygon [[x,y],...] (3 to 4096 points, not
closed, not self-intersecting); height: [z_low, z_high] with z_low < z_high; thickness: metres
(a bulwark is the band between the outline and the outline offset inwards by the thickness).
Every arg value is an object with exactly "value", "source" ("ai_inferred" or "guessed") and "basis".
"""

FORMAT_B = """Reply with ONE Python code block only (```python ... ```). The module must define
    def build() -> dict:   # returns {component id: cadquery.Shape (a solid), in metres}
It runs with the repo Python environment (cadquery, OCP, numpy, math are available) in an empty
work folder. Do not use the network, subprocesses or files. Do not export: the runner exports
each returned solid to STEP. Each solid must be valid and have positive volume.
"""


def components_text() -> str:
    return '\n'.join(f'- {cid}: {meaning}' for cid, meaning in COMPONENTS.items())


def first_prompt(arm: str, pack: dict, inputs: dict) -> list:
    images = '\n'.join(f'{i + 1}. {m["view"]} ({m["width"]}x{m["height"]} px): '
                       + '; '.join(f'{k} = {v}' for k, v in m['calibration'].items())
                       for i, m in enumerate(pack['images']))
    text = COMMON.format(images=images, reading=reading_text(inputs), components=components_text())
    text += FORMAT_A if arm == 'A' else FORMAT_B
    content = [{'type': 'text', 'text': text}]
    for meta in pack['images']:
        data = base64.b64encode(Path(meta['path']).read_bytes()).decode()
        content.append({'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{data}'}})
    return [{'role': 'user', 'content': content}]


# ---------------------------------------------------------------- provider client

def request_body(messages: list, settings: dict) -> dict:
    """Chat request; thinking is set as the Rust provider sets it for vision reading."""
    body = {'model': GO_MODEL, 'messages': messages, 'max_tokens': settings['max_tokens'],
            'temperature': TEMPERATURE}
    if settings['thinking'] is not None:
        body.update(stream=False, thinking={'type': settings['thinking']})
    return body


def call_model(messages: list, receipts: Path, settings: dict) -> tuple[str, dict]:
    """One chat completion with a receipt. The key comes from the environment only."""
    key = os.environ.get('OPENCODE_API_KEY')
    if not key:
        raise RuntimeError('Load the keys first: source scripts/load_opencode_keys.sh')
    body = json.dumps(request_body(messages, settings)).encode()
    request_id = uuid.uuid4().hex
    request = urllib.request.Request(GO_ENDPOINT, data=body, method='POST', headers={
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'Authorization': f'Bearer {key}', 'User-Agent': 'MarinaFrame/0.5 whole-vessel A/B',
        'x-opencode-session': f'mf-{request_id}'})
    started = time.time()
    receipt = {'request_id': request_id, 'model': GO_MODEL, 'request_sha256': hashlib.sha256(body).hexdigest(),
               'request_bytes': len(body), 'started': started}
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            reply = json.loads(response.read())
        text = reply['choices'][0]['message'].get('content') or ''
        usage = reply.get('usage', {})
        receipt.update(state='completed', returned_model=reply.get('model'),
                       finish_reason=reply['choices'][0].get('finish_reason'),
                       usage={k: usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cost')},
                       billing=usage.get('opencode'), reply_sha256=hashlib.sha256(text.encode()).hexdigest())
    except Exception as exc:  # noqa: BLE001 - a failed request is recorded, not hidden
        text, receipt['state'], receipt['error'] = '', 'failed', f'{type(exc).__name__}: {exc}'[:500]
    receipt['seconds'] = time.time() - started
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / f'{request_id}.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return text, receipt


# ---------------------------------------------------------------- arms

def extract_json(text: str) -> dict:
    match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    body = match.group(1) if match else text[text.find('{'):text.rfind('}') + 1]
    return json.loads(body)


def extract_code(text: str) -> str:
    match = re.search(r'```python\s*(.*?)```', text, re.DOTALL)
    if not match:
        raise ValueError('reply has no ```python block')
    return match.group(1)


def build_arm_a(text: str, folder: Path) -> dict:
    from vessel_reconstruction.ship_cad import validate_program
    from vessel_reconstruction.ship_cad_worker import run

    program = validate_program(extract_json(text))
    (folder / 'program.json').write_text(json.dumps(program, indent=2) + '\n')
    return run(program, {}, folder / 'task')


RUNNER = '''
import json, sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
out = Path('task/work/output'); out.mkdir(parents=True, exist_ok=True)
components = []
try:
    import model_program, cadquery as cq
    shapes = model_program.build()
    if not isinstance(shapes, dict):
        raise TypeError('build() must return a dict')
except Exception:
    print(traceback.format_exc()[-3000:], file=sys.stderr)
    raise SystemExit(2)
material = []
for cid, shape in shapes.items():
    item = {'id': str(cid), 'op': 'python', 'status': 'draft_guess', 'source_labels': {'geometry': 'ai_inferred'}}
    try:
        if isinstance(shape, cq.Workplane):
            shape = shape.val()
        if not shape.isValid() or not shape.Solids() or shape.Volume() <= 0:
            raise ValueError('invalid or empty CAD solid')
        box = shape.BoundingBox()
        item.update(built=True, volume_m3=shape.Volume(),
                    bbox_m={'min': [box.xmin, box.ymin, box.zmin], 'max': [box.xmax, box.ymax, box.zmax]})
        cq.exporters.export(shape.scale(1000), str(out / f'{cid}.step'))
        material.append(shape)
    except Exception as exc:
        item.update(built=False, reason=f'{type(exc).__name__}: {exc}'[:500])
    components.append(item)
if material:
    cq.exporters.export(cq.Compound.makeCompound(material).scale(1000), str(out / 'model-draft.step'))
Path('execution.json').write_text(json.dumps({'exit_code': 0, 'result': {
    'schema': 'ship-cad-result/v1', 'status': 'draft_only', 'engineering_approved': False,
    'components': components}}, indent=2))
'''


def build_arm_b(text: str, folder: Path) -> dict:
    (folder / 'model_program.py').write_text(extract_code(text))
    (folder / 'runner.py').write_text(RUNNER)
    # Model-written code gets no credentials: an empty environment plus an allow-list.
    env = {key: os.environ[key] for key in BUILD_ENV_ALLOW if key in os.environ}
    env.update(HOME=str(folder), TMPDIR=str(folder), PYTHONDONTWRITEBYTECODE='1')
    try:
        done = subprocess.run([sys.executable, '-I', 'runner.py'], cwd=folder, env=env, capture_output=True,
                              text=True, timeout=BUILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {'exit_code': None, 'error': f'build timed out after {BUILD_TIMEOUT_S} s'}
    if done.returncode != 0 or not (folder / 'execution.json').is_file():
        return {'exit_code': done.returncode, 'error': (done.stderr or done.stdout)[-3000:]}
    return json.loads((folder / 'execution.json').read_text())


def feedback(execution: dict) -> tuple[str, int]:
    components = (execution.get('result') or {}).get('components', [])
    built = {c['id'] for c in components if c.get('built')}
    lines = [f'Build result: {len(built & set(COMPONENTS))} of {len(COMPONENTS)} required components built.']
    if execution.get('error'):
        lines.append(f'Error: {execution["error"]}')
    for c in components:
        if c.get('built'):
            lines.append(f'- {c["id"]}: built, volume {c["volume_m3"]:.2f} m3, bbox {c["bbox_m"]}')
        else:
            lines.append(f'- {c["id"]}: NOT built: {c.get("reason", "")[:300]}')
    missing = set(COMPONENTS) - {c['id'] for c in components}
    if missing:
        lines.append(f'Missing ids: {sorted(missing)}')
    lines.append('Fix the problems and reply with the complete output again, in the same format.')
    return '\n'.join(lines), len(built & set(COMPONENTS))


def run_repeat(arm: str, pack: dict, inputs: dict, folder: Path, settings: dict) -> dict:
    messages = first_prompt(arm, pack, inputs)
    record = {'arm': arm, 'settings': settings, 'turns': [], 'started': time.time()}
    execution = {}
    for turn in range(1, MAX_TURNS + 1):
        turn_dir = folder / f'turn-{turn}'
        turn_dir.mkdir(parents=True)
        text, receipt = call_model(messages, folder / 'receipts', settings)
        (turn_dir / 'reply.txt').write_text(text)
        try:
            execution = build_arm_a(text, turn_dir) if arm == 'A' else build_arm_b(text, turn_dir)
        except Exception as exc:  # noqa: BLE001 - a rejected reply is feedback, not a crash
            execution = {'exit_code': None, 'error': f'{type(exc).__name__}: {exc}'[:1500]}
        (turn_dir / 'execution.json').write_text(json.dumps(execution, indent=2, default=str) + '\n')
        message, built = feedback(execution)
        record['turns'].append({'turn': turn, 'receipt': receipt, 'built': built,
                                'error': execution.get('error')})
        record['final_turn'] = turn
        if built == len(COMPONENTS) or receipt['state'] != 'completed':
            break
        messages = messages + [{'role': 'assistant', 'content': text}, {'role': 'user', 'content': message}]
    record['seconds'] = time.time() - record['started']
    return record


def summarise(folder: Path, record: dict, truth_mesh: Path) -> dict:
    from benchmarks.gunnerus.whole_vessel_metrics import score_run

    final = folder / f'turn-{record["final_turn"]}'
    score = score_run(final, truth_mesh) if (final / 'execution.json').is_file() else {}
    usage = [t['receipt'].get('usage') or {} for t in record['turns']]
    built = {cid for cid, item in score.get('M7_components', {}).items() if item['built']}
    return {'arm': record['arm'], 'turns': len(record['turns']), 'seconds': round(record['seconds'], 1),
            'prompt_tokens': sum(u.get('prompt_tokens') or 0 for u in usage),
            'completion_tokens': sum(u.get('completion_tokens') or 0 for u in usage),
            'cost': sum(u.get('cost') or 0 for u in usage),
            'built': len(built & set(COMPONENTS)), 'success': set(SCORED) <= built,
            'metrics': score.get('metrics', {})}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--truth-mesh', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=REPEATS)
    parser.add_argument('--round', choices=sorted(ROUNDS), default='2', help='Protocol round (request settings).')
    args = parser.parse_args()
    settings = ROUNDS[args.round]
    from benchmarks.gunnerus.whole_vessel import build_inputs

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = build_inputs(args.sources)
    pack = render_pack(args.sources, out)
    for meta in pack['images']:
        meta['path'] = str(out / meta['file'])
    (out / 'pack.json').write_text(json.dumps({'pack': pack, 'reading': reading_text(inputs)}, indent=2) + '\n')
    results = []
    for repeat in range(1, args.repeats + 1):
        for arm in ('A', 'B'):
            folder = out / f'{arm}{repeat}'
            record = run_repeat(arm, pack, inputs, folder, settings)
            (folder / 'record.json').write_text(json.dumps(record, indent=2, default=str) + '\n')
            summary = summarise(folder, record, args.truth_mesh)
            (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
            results.append(summary)
            print(json.dumps(summary), flush=True)
    (out / 'ab_summary.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
