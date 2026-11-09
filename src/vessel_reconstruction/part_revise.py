"""Re-run one whole-vessel part from a person's mark (docs/APP_SPEC.md "Whole-vessel parts").

A person marks a part in the app and writes what to change. This worker gives the model
(DeepSeek through OpenCode Go, ship-cad JSON form, thinking disabled) crops of the run's
drawings around the part, the part's current values and the note. It rebuilds only that part
in the ship-cad worker and rewrites the part's entry in ``<task>/whole_vessel/execution.json``
with a new revision. The other parts do not change. The previous STEP stays as
``<id>.r<previous revision>.step`` and the previous entry stays in ``revision_history``, so the
person can keep the new part or undo it.

The crops come from ``<task>/whole_vessel/views.json`` (the run's drawing views and their
calibration; schema below). Every value the model gives is labelled ``ai_inferred``; nothing is
approved (``engineering_approved`` stays false).

Command line (the app runs it; the key comes from the environment, never from an argument)::

    python -m vessel_reconstruction.part_revise --task DIR --part ID --note=TEXT
    python -m vessel_reconstruction.part_revise --task DIR --part ID --keep
    python -m vessel_reconstruction.part_revise --task DIR --part ID --undo

``views.json``::

    {"schema": "whole-vessel-views/v1",
     "views": {"profile": {"kind": "profile", "file": "<DXF, PNG or JPEG; absolute or task-relative>",
                           "sha256": "<optional>", "bounds": [u0, v0, u1, v1],
                           "origin": [u, v], "metres_per_unit": 0.001, "y_down": false,
                           "layers": ["S0CO1"] or null}, ...}}

``bounds`` and ``origin`` are in the file's units (drawing units for a DXF, pixels for an image).
A point (u, v) is at ship x = (u - origin_u) * metres_per_unit and z (profile) or y (plan) =
(v - origin_v) * metres_per_unit, with the sign of v reversed when ``y_down`` (image rows).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.request
import uuid
from pathlib import Path

EXECUTION_FILE = Path('whole_vessel') / 'execution.json'
VIEWS_FILE = Path('whole_vessel') / 'views.json'
# Host detail of the parts above the hull (hull side, end contours, windows): with it a rebuilt
# deck, bulwark or deckhouse follows the hull as the first build did (ship_cad.execute).
DETAIL_FILE = Path('whole_vessel') / 'detail.json'
VIEWS_SCHEMA = 'whole-vessel-views/v1'
REVISIONS_FOLDER = Path('whole_vessel') / 'revisions'
EXECUTION_MAX_BYTES = 8 * 1024 * 1024  # the same limit as the app reader (app/core/src/parts.rs)

# Ops whose values the model can give as ship-cad inline values (the hull is a loft of stations).
REVISABLE_OPS = ('deck', 'deckhouse', 'bulwark', 'appendage')
MAX_NOTE_CHARS = 500  # docs/APP_SPEC.md: a mark note has 1 to 500 characters
PART_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')  # part ids become file names

# Model request (the same model and endpoint as rust-control/src/types.rs GO_MODEL, GO_ENDPOINT).
GO_MODEL = 'deepseek-v4.1-flash'
GO_ENDPOINT = 'https://opencode.ai/inference/go/openai/v1/chat/completions'
KEY_VARIABLES = ('OPENCODE_API_KEY', 'OPENCODE_API_KEY_2', 'OPENCODE_API_KEY_3')
SETTINGS = {'max_tokens': 32_000, 'thinking': 'disabled', 'temperature': 0.2}
REQUEST_TIMEOUT_S = 300
MAX_TURNS = 3  # a reply that does not build goes back to the model with the reason

# Crops. The provider accepts at most 1,048,576 pixels and 1 MiB per image.
MAX_IMAGES = 3
MAX_IMAGE_PIXELS = 1_000_000
MAX_IMAGE_SIDE = 2048
MAX_IMAGE_BYTES = 1_048_576
MAX_UPSCALE = 4.0  # a small raster crop is enlarged at most this much
CONTEXT_M = 3.0  # drawing shown around the part on each side, plus a quarter of its size
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg')


class PartReviseError(ValueError):
    """A request the worker refuses; the message is shown to the person."""


# ---------------------------------------------------------------- run files

def _read_json(path: Path, max_bytes: int) -> dict:
    with path.open('rb') as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PartReviseError(f'{path.name} is too large.')
    return json.loads(data)


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temporary, path)


def load_detail(task: Path) -> dict | None:
    """The run's host detail, or None (an older run: parts are rebuilt straight)."""
    path = task / DETAIL_FILE
    try:
        return json.loads(path.read_text()) if path.is_file() else None
    except (OSError, ValueError):
        return None


def load_execution(task: Path) -> dict:
    path = task / EXECUTION_FILE
    if not path.is_file():
        raise PartReviseError('This run has no whole-vessel parts.')
    return _read_json(path, EXECUTION_MAX_BYTES)


def find_part(record: dict, part_id: str) -> int:
    if not PART_ID.match(part_id):
        raise PartReviseError('This run has no such part.')
    components = (record.get('result') or {}).get('components') or []
    for index, component in enumerate(components):
        if component.get('id') == part_id:
            return index
    raise PartReviseError('This run has no such part.')


def save_execution(task: Path, record: dict) -> None:
    record.setdefault('result', {})['engineering_approved'] = False
    _write_json_atomic(task / EXECUTION_FILE, record)


def check_note(note: str) -> str:
    note = note.strip()
    if not 1 <= len(note) <= MAX_NOTE_CHARS or any(ord(c) < 32 or ord(c) == 127 for c in note):
        raise PartReviseError(f'A mark note has 1 to {MAX_NOTE_CHARS} characters.')
    return note


# ---------------------------------------------------------------- crops of the run's drawings

def load_views(task: Path) -> dict:
    """The run's drawing views (``whole_vessel/views.json``), each with its file resolved."""
    path = task / VIEWS_FILE
    if not path.is_file():
        raise PartReviseError('This run does not say which drawings it read (whole_vessel/views.json).')
    manifest = _read_json(path, 1024 * 1024)
    if manifest.get('schema') != VIEWS_SCHEMA or not isinstance(manifest.get('views'), dict):
        raise PartReviseError('whole_vessel/views.json has an unknown form.')
    views = {}
    for name, view in manifest['views'].items():
        numbers = [*view.get('bounds', []), *view.get('origin', []), view.get('metres_per_unit')]
        if (view.get('kind') not in ('profile', 'plan') or len(view.get('bounds', [])) != 4
                or len(view.get('origin', [])) != 2
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in numbers)
                or view['metres_per_unit'] <= 0 or not isinstance(view.get('file'), str)):
            raise PartReviseError(f'whole_vessel/views.json: view {name!r} is not complete.')
        file = Path(view['file'])
        views[name] = dict(view, file=file if file.is_absolute() else task / file)
    return views


def part_box(entry: dict) -> dict | None:
    """The part's extent in metres: {'x': [low, high], 'y': [...], 'z': [...]} (axes it has)."""
    box = entry.get('bbox_m') or {}
    if isinstance(box.get('min'), list) and isinstance(box.get('max'), list):
        return {axis: [box['min'][i], box['max'][i]] for i, axis in enumerate('xyz')}
    geometry = entry.get('geometry') or {}
    outline = geometry.get('outline')
    if not isinstance(outline, list) or not outline:
        return None
    second = 'z' if entry.get('op') == 'appendage' else 'y'
    extent = {'x': [min(p[0] for p in outline), max(p[0] for p in outline)],
              second: [min(p[1] for p in outline), max(p[1] for p in outline)]}
    for argument, axis in (('height', 'z'), ('span', 'y')):
        if isinstance(geometry.get(argument), list) and len(geometry[argument]) == 2:
            extent[axis] = sorted(geometry[argument])
    return extent


def _to_source(view: dict, x_m: float, w_m: float) -> tuple[float, float]:
    origin_u, origin_v = view['origin']
    scale = view['metres_per_unit']
    v = origin_v - w_m / scale if view.get('y_down') else origin_v + w_m / scale
    return origin_u + x_m / scale, v


def crop_window(view: dict, box: dict | None) -> list[float] | None:
    """The part's window in the view's units (with context), inside the view; None when outside."""
    u0, v0, u1, v1 = view['bounds']
    vertical = 'z' if view['kind'] == 'profile' else 'y'
    if box is None or 'x' not in box or vertical not in box:
        return [u0, v0, u1, v1]
    x_low, x_high = box['x']
    w_low, w_high = box[vertical]
    margin_x = CONTEXT_M + (x_high - x_low) / 4
    margin_w = CONTEXT_M + (w_high - w_low) / 4
    corners = [_to_source(view, x_low - margin_x, w_low - margin_w),
               _to_source(view, x_high + margin_x, w_high + margin_w)]
    window = [max(u0, min(c[0] for c in corners)), max(v0, min(c[1] for c in corners)),
              min(u1, max(c[0] for c in corners)), min(v1, max(c[1] for c in corners))]
    if window[0] >= window[2] or window[1] >= window[3]:
        return None
    return window


def _image_scale(width: float, height: float, max_scale: float) -> float:
    return min(max_scale, MAX_IMAGE_SIDE / width, MAX_IMAGE_SIDE / height,
               math.sqrt(MAX_IMAGE_PIXELS / (width * height)))


def _render_dxf(view: dict, window: list[float]):
    """Line work and printed text of a DXF inside the window; (image, pixels per unit, window)."""
    import ezdxf
    from PIL import Image, ImageDraw

    from .ship_measure import read_dxf

    u0, v0, u1, v1 = window
    scale = _image_scale(u1 - u0, v1 - v0, math.inf)
    # Rounded down, so that the pixel limit holds; the calibration uses the scale, not the size.
    width, height = max(1, int((u1 - u0) * scale)), max(1, int((v1 - v0) * scale))
    image = Image.new('L', (width, height), 255)
    draw = ImageDraw.Draw(image)

    def pixel(point):
        return (point[0] - u0) * scale, (v1 - point[1]) * scale

    for entity in read_dxf(view['file'], layers=view.get('layers')):
        if any(u0 <= p[0] <= u1 and v0 <= p[1] <= v1 for p in entity['points']):
            draw.line([pixel(p) for p in entity['points']], fill=0, width=1)
    for entity in ezdxf.readfile(view['file']).modelspace().query('TEXT MTEXT'):
        insert = entity.dxf.insert
        if u0 <= insert.x <= u1 and v0 <= insert.y <= v1:
            text = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.plain_text()
            draw.text(pixel((insert.x, insert.y)), text, fill=0)
    return image, scale, window


def _render_raster(view: dict, window: list[float]):
    from PIL import Image

    u0, v0, u1, v1 = (math.floor(window[0]), math.floor(window[1]), math.ceil(window[2]), math.ceil(window[3]))
    with Image.open(view['file']) as source:
        part = source.convert('L').crop((u0, v0, u1, v1))
    scale = _image_scale(part.width, part.height, MAX_UPSCALE)
    size = (max(1, int(part.width * scale)), max(1, int(part.height * scale)))
    # The window in whole pixels: the calibration of the crop starts there.
    return part.resize(size, Image.LANCZOS), scale, [u0, v0, u1, v1]


def calibration(view: dict, window: list[float], scale: float) -> dict:
    """Pixel to metre formulas of one crop, as text for the model."""
    u0, v0, u1, v1 = window
    origin_u, origin_v = view['origin']
    metres = view['metres_per_unit']
    step = metres / scale
    top = (origin_v - v0) * metres if view.get('y_down') else (v1 - origin_v) * metres
    vertical = 'z_m' if view['kind'] == 'profile' else 'y_m'
    return {'x_m': f'{(u0 - origin_u) * metres:.4f} + {step:.6f} * px',
            vertical: f'{top:.4f} - {step:.6f} * py'}


def choose_views(entry: dict, views: dict) -> list[str]:
    """Views named in the part's evidence first; at least one profile and one plan when there are."""
    named = []
    for record in (entry.get('provenance') or {}).values():
        if isinstance(record, dict):
            for key in ('plan_view', 'view'):
                name = record.get(key)
                if name in views and name not in named:
                    named.append(name)
    ordered = named + [name for name in views if name not in named]
    chosen = []
    for kind in ('profile', 'plan'):
        first = next((name for name in ordered if views[name]['kind'] == kind), None)
        if first:
            chosen.append(first)
    chosen += [name for name in ordered if name not in chosen]
    return chosen


def build_pack(task: Path, entry: dict, out: Path) -> dict:
    """PNG crops of the run's drawings around the part, with their calibration."""
    views = load_views(task)
    box = part_box(entry)
    out.mkdir(parents=True, exist_ok=True)
    images = []
    for name in choose_views(entry, views):
        if len(images) == MAX_IMAGES:
            break
        view = views[name]
        if not view['file'].is_file():
            raise PartReviseError(f'The drawing of the {name} view is not where the run read it.')
        if view.get('sha256') and _sha256(view['file']) != view['sha256']:
            raise PartReviseError(f'The drawing of the {name} view changed after the run read it.')
        window = crop_window(view, box)
        if window is None:
            continue
        raster = view['file'].suffix.lower() in IMAGE_SUFFIXES
        image, scale, window = _render_raster(view, window) if raster else _render_dxf(view, window)
        path = out / f'{len(images) + 1}-{_safe(name)}.png'
        image.save(path, optimize=True)
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise PartReviseError(f'The crop of the {name} view is larger than the model accepts.')
        images.append({'view': name, 'kind': view['kind'], 'file': path.name, 'path': str(path),
                       'width': image.width, 'height': image.height,
                       'calibration': calibration(view, window, scale), 'sha256': _sha256(path)})
    if not images:
        raise PartReviseError('No drawing view of this run shows the part.')
    return {'images': images}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _safe(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9_-]', '_', name)[:64]


# ---------------------------------------------------------------- prompt

PROMPT = """You revise ONE part of a draft 3D CAD model of a ship, read from its drawings. A person
marked the part and wrote what to change. Coordinates are metres: x along the ship, positive
forward; y positive to port, 0 on the centreline; z up from the baseline.

Images (crops of the drawings; the calibration converts pixels to metres):
{images}

Part: {part_id} ({label}), operation {op}.
Current values (source labels: traced = read from the drawing, guessed = code gap fill,
ai_inferred = model value):
{values}

The person's mark (what to change): "{note}"

Follow the mark. Check it against the images; keep every value the mark does not concern.
Reply with ONE JSON object only (no prose), a ship-cad/v1 program with exactly this one component:
{{"schema":"ship-cad/v1","components":[{{"id":"{part_id}","op":"{op}",
  "source":{{"view":"{view}","region":"{part_id}","method":"closed_outline"}},
  "args":{{ARGUMENT:{{"value":VALUE,"source":"ai_inferred","basis":"short reason"}}, ...}}}}]}}
Arguments for {op} (every argument is required):
{arguments}
"""

ARGUMENT_HELP = {
    'outline': 'plan polygon [[x, y], ...] (3 or more points, not closed, not self-intersecting)',
    'height': '[z_low, z_high] with z_low < z_high',
    'thickness': 'wall thickness in metres (the wall is inside the outline)',
    'span': '[y_low, y_high]: the transverse extent of the part',
}
APPENDAGE_OUTLINE = 'profile polygon [[x, z], ...] (3 or more points, not closed, not self-intersecting)'


def part_values(entry: dict) -> str:
    from .ship_cad import OPERATIONS

    labels = entry.get('source_labels') or {}
    provenance = entry.get('provenance') or {}
    lines = []
    for argument in OPERATIONS[entry['op']]:
        value = (entry.get('geometry') or {}).get(argument)
        record = provenance.get(argument) if isinstance(provenance.get(argument), dict) else {}
        basis = record.get('basis')
        line = f'- {argument} ({labels.get(argument, "unknown")}): {json.dumps(value)}'
        lines.append(line + (f'; basis: {basis}' if basis else ''))
    return '\n'.join(lines)


def revision_prompt(entry: dict, note: str, pack: dict) -> list:
    from .ship_cad import OPERATIONS

    op = entry['op']
    images = '\n'.join(f'{i + 1}. {m["view"]} ({m["width"]}x{m["height"]} px): '
                       + '; '.join(f'{k} = {v}' for k, v in m['calibration'].items())
                       for i, m in enumerate(pack['images']))
    arguments = '\n'.join(
        f'- {name}: {APPENDAGE_OUTLINE if (op, name) == ("appendage", "outline") else ARGUMENT_HELP[name]}'
        for name in OPERATIONS[op])
    text = PROMPT.format(images=images, part_id=entry['id'], label=entry.get('label', entry['id']), op=op,
                         values=part_values(entry), note=note, arguments=arguments,
                         view='profile' if op == 'appendage' else 'plan')
    content = [{'type': 'text', 'text': text}]
    for meta in pack['images']:
        data = base64.b64encode(Path(meta['path']).read_bytes()).decode()
        content.append({'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{data}'}})
    return [{'role': 'user', 'content': content}]


# ---------------------------------------------------------------- model client

def model_key() -> str:
    """The first key in the environment. The app sets it from its key lookup; it is never printed."""
    for variable in KEY_VARIABLES:
        if os.environ.get(variable):
            return os.environ[variable]
    raise PartReviseError('No model key was found.')


def call_model(messages: list, receipts: Path, settings: dict) -> tuple[str, dict]:
    """One chat completion with a receipt (no key in the receipt)."""
    body = json.dumps({'model': GO_MODEL, 'messages': messages, 'max_tokens': settings['max_tokens'],
                       'temperature': settings['temperature'], 'stream': False,
                       'thinking': {'type': settings['thinking']}}).encode()
    request_id = uuid.uuid4().hex
    request = urllib.request.Request(GO_ENDPOINT, data=body, method='POST', headers={
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'Authorization': f'Bearer {model_key()}', 'User-Agent': 'MarinaFrame part revise',
        'x-opencode-session': f'mf-{request_id}'})
    started = time.time()
    receipt = {'request_id': request_id, 'model': GO_MODEL, 'endpoint': GO_ENDPOINT,
               'request_sha256': hashlib.sha256(body).hexdigest(), 'request_bytes': len(body)}
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            reply = json.loads(response.read())
        text = reply['choices'][0]['message'].get('content') or ''
        usage = reply.get('usage') or {}
        receipt.update(state='completed', returned_model=reply.get('model'),
                       finish_reason=reply['choices'][0].get('finish_reason'),
                       usage={k: usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens',
                                                        'cost')},
                       reply_sha256=hashlib.sha256(text.encode()).hexdigest())
    except Exception as exc:  # noqa: BLE001 - a failed request is recorded, not hidden
        text, receipt['state'] = '', 'failed'
        receipt['error'] = type(exc).__name__ + (f' {exc.code}' if hasattr(exc, 'code') else '')
    receipt['seconds'] = round(time.time() - started, 2)
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / f'{request_id}.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return text, receipt


def scripted_model(replies: list[str]):
    """A model that gives these replies in order (tests; no request is made)."""
    remaining = list(replies)

    def call(messages, receipts, settings):
        text = remaining.pop(0) if remaining else ''
        return text, {'request_id': f'scripted-{len(replies) - len(remaining)}', 'state': 'completed',
                      'usage': {}, 'seconds': 0.0}
    return call


def extract_json(text: str) -> dict:
    match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    body = match.group(1) if match else text[text.find('{'):text.rfind('}') + 1]
    return json.loads(body)


# ---------------------------------------------------------------- revise, keep, undo

def keep_unchanged_labels(old: dict, built: dict) -> dict:
    """A value the model gave back unchanged keeps its old source label and evidence: a traced
    value stays traced. Only values that changed are labelled ``ai_inferred``."""
    labels = dict(built.get('source_labels') or {})
    provenance = dict(built.get('provenance') or {})
    old_geometry, new_geometry = old.get('geometry') or {}, built.get('geometry') or {}
    for argument in labels:
        old_label = (old.get('source_labels') or {}).get(argument)
        if old_label and argument in old_geometry and old_geometry[argument] == new_geometry.get(argument):
            labels[argument] = old_label
            if argument in (old.get('provenance') or {}):
                provenance[argument] = old['provenance'][argument]
    return dict(built, source_labels=labels, provenance=provenance)


def updated_entry(old: dict, built: dict, note: str, revision: int, receipts: list) -> dict:
    """The new entry: the rebuilt part's values, the mark, and the whole previous entry."""
    previous = {key: value for key, value in old.items() if key != 'revision_history'}
    entry = dict(keep_unchanged_labels(old, built), label=old.get('label', built['id']), revision=revision,
                 revision_note=note, revision_kept=False)
    entry['revision_history'] = old.get('revision_history', []) + [previous]
    entry['revision_receipts'] = receipts
    return entry


def revise_part(task: Path, part_id: str, note: str, *, call=None, pack: dict | None = None) -> dict:
    """Rebuild one part from a mark; return the new entry. ``call`` is the model client."""
    from .ship_cad import triage_program
    from .ship_cad_worker import run as run_worker

    note = check_note(note)
    task = Path(task).resolve()
    record = load_execution(task)
    index = find_part(record, part_id)
    components = record['result']['components']
    old = components[index]
    if old.get('op') not in REVISABLE_OPS:
        raise PartReviseError(f'A {old.get("op")} part cannot be re-run from a mark yet.')
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise PartReviseError('Parts are rebuilt only on macOS (the CAD worker needs its sandbox).')
    revision = int(old.get('revision', 0)) + 1
    # One folder per attempt (an undone revision number can be used again).
    attempt = f'{time.strftime("%Y%m%dT%H%M%S")}-{uuid.uuid4().hex[:6]}'
    work = task / REVISIONS_FOLDER / f'{part_id}-r{revision}-{attempt}'
    work.mkdir(parents=True, exist_ok=False)
    pack = pack or build_pack(task, old, work / 'pack')
    call = call or call_model
    messages = revision_prompt(old, note, pack)
    receipts, built, problem = [], None, None
    for turn in range(1, MAX_TURNS + 1):
        text, receipt = call(messages, work / 'receipts', SETTINGS)
        receipts.append({k: receipt.get(k) for k in ('request_id', 'state', 'usage', 'seconds')})
        (work / f'reply-{turn}.txt').write_text(text)
        if receipt.get('state') != 'completed':
            problem = 'the model request failed'
            break
        try:
            program = extract_json(text)
            program['components'] = [c for c in program.get('components', []) if c.get('id') == part_id][:1]
            triage_program(program)
            (work / f'program-{turn}.json').write_text(json.dumps(program, indent=2) + '\n')
            execution = run_worker(program, {}, work / f'task-{turn}', detail=load_detail(task))
            result = (execution.get('result') or {}).get('components', [])
            built = next((c for c in result if c['id'] == part_id and c.get('built')), None)
            problem = None if built else (result[0].get('reason') if result else execution.get('error'))
        except Exception as exc:  # noqa: BLE001 - the error goes back to the model
            problem = f'{type(exc).__name__}: {exc}'[:1500]
        if built:
            source = work / f'task-{turn}' / 'work' / 'output' / f'{part_id}.step'
            break
        messages = messages + [{'role': 'assistant', 'content': text},
                               {'role': 'user', 'content': f'Not built: {problem}. Reply with the complete '
                                                           'program again, in the same format.'}]
    if not built:
        raise PartReviseError(f'The part was not rebuilt ({str(problem)[:200]}); the old part stays.')
    parts = task / 'whole_vessel'
    if (parts / f'{part_id}.step').is_file():
        shutil.copy2(parts / f'{part_id}.step', parts / f'{part_id}.r{revision - 1}.step')
    shutil.copy2(source, parts / f'{part_id}.step')
    entry = updated_entry(old, built, note, revision, receipts)
    components[index] = entry
    save_execution(task, record)
    return entry


def _pending(record: dict, part_id: str) -> tuple[int, dict]:
    index = find_part(record, part_id)
    entry = record['result']['components'][index]
    if not entry.get('revision') or entry.get('revision_kept') or not entry.get('revision_history'):
        raise PartReviseError('This part has no new revision to keep or undo.')
    return index, entry


def keep_revision(task: Path, part_id: str) -> dict:
    """Keep the new revision: the Keep and Undo choice ends; the history stays."""
    task = Path(task).resolve()
    record = load_execution(task)
    index, entry = _pending(record, part_id)
    entry['revision_kept'] = True
    record['result']['components'][index] = entry
    save_execution(task, record)
    return entry


def undo_revision(task: Path, part_id: str) -> dict:
    """Put back the previous entry and its STEP (``<id>.r<previous>.step``)."""
    task = Path(task).resolve()
    record = load_execution(task)
    index, entry = _pending(record, part_id)
    history = entry['revision_history']
    previous = dict(history[-1])
    if history[:-1]:
        previous['revision_history'] = history[:-1]
    parts = task / 'whole_vessel'
    backup = parts / f'{part_id}.r{entry["revision"] - 1}.step'
    if backup.is_file():
        os.replace(backup, parts / f'{part_id}.step')
    elif not previous.get('built'):
        (parts / f'{part_id}.step').unlink(missing_ok=True)
    else:
        raise PartReviseError('The previous STEP of this part is missing; nothing was changed.')
    record['result']['components'][index] = previous
    save_execution(task, record)
    return previous


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m vessel_reconstruction.part_revise',
                                     description='Re-run one whole-vessel part from a mark, or keep or undo '
                                                 'its new revision.')
    parser.add_argument('--task', type=Path, required=True, help='task folder (holds whole_vessel/)')
    parser.add_argument('--part', required=True, help='part id')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--note', help='what to change (the mark note); pass it as --note=TEXT')
    action.add_argument('--keep', action='store_true', help='keep the new revision')
    action.add_argument('--undo', action='store_true', help='put back the previous revision')
    parser.add_argument('--replies', type=Path,
                        help='JSON list of scripted model replies (tests only; no model request is made)')
    args = parser.parse_args(argv)
    try:
        if args.keep:
            entry = keep_revision(args.task, args.part)
        elif args.undo:
            entry = undo_revision(args.task, args.part)
        else:
            call = scripted_model(json.loads(args.replies.read_text())) if args.replies else None
            entry = revise_part(args.task, args.part, args.note, call=call)
    except PartReviseError as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({'part': entry['id'], 'revision': entry.get('revision', 0), 'built': entry.get('built'),
                      'status': entry.get('status')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
