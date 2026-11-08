"""Re-run one whole-vessel part from a person's mark (Mark and revise, CLI first).

The app keeps a person's mark of a part (review "marked" plus a note of what to change; see
docs/APP_SPEC.md "Whole-vessel parts"). This entry point takes the part id and the note, gives
DeepSeek the part's drawing crops, its current values and the note (ship-cad JSON form, thinking
disabled), rebuilds only that part in the ship-cad worker, and rewrites the part's entry in
``<folder>/whole_vessel/execution.json`` with a new revision. The other parts do not change.
The previous STEP stays as ``<id>.r<revision>.step``.

Load the keys in the same shell first (never print them)::

    source scripts/load_opencode_keys.sh
    PYTHONPATH=src python -m benchmarks.gunnerus.whole_vessel_revise --folder <run folder> \\
        --pack <A/B run>/pack.json --part wheelhouse --note "What to change"
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import time
from pathlib import Path

from benchmarks.gunnerus import whole_vessel_ab as ab

# Ops whose values the model can revise as ship-cad inline values (the hull is a loft).
REVISABLE_OPS = ('deck', 'deckhouse', 'bulwark', 'appendage')
MAX_NOTE_CHARS = 500  # docs/APP_SPEC.md: a mark note has 1 to 500 characters

PROMPT = """You revise ONE part of a draft 3D CAD model of the research vessel Gunnerus, from its General
Arrangement. A person marked the part and wrote what to change. Coordinates are metres: x from
frame 0, positive forward; y positive to port; z up from the baseline.

Images (rendered from the GA; calibration converts pixels to metres):
{images}

Part: {part_id} ({label}), operation {op}.
Current values (source labels: traced = read from the drawing, guessed = code gap fill,
ai_inferred = model value):
{values}

The person's mark (what to change): "{note}"

Follow the mark. Check it against the images; keep every value the mark does not concern.
Reply with ONE JSON object only (no prose), a ship-cad/v1 program with exactly this one component:
{{"schema":"ship-cad/v1","components":[{{"id":"{part_id}","op":"{op}",
  "source":{{"view":"plan","region":"{part_id}","method":"closed_outline"}},
  "args":{{ARGUMENT:{{"value":VALUE,"source":"ai_inferred","basis":"short reason"}}, ...}}}}]}}
Arguments for {op}: {arguments}. outline: plan polygon [[x,y],...] (not closed, not
self-intersecting); height: [z_low, z_high]; thickness: metres. Every argument is required.
"""


def load_parts(folder: Path) -> dict:
    return json.loads((folder / 'whole_vessel' / 'execution.json').read_text())


def part_values(entry: dict) -> str:
    lines = []
    for argument, label in entry.get('source_labels', {}).items():
        value = (entry.get('geometry') or {}).get(argument)
        basis = (entry.get('provenance', {}).get(argument) or {}).get('basis')
        lines.append(f'- {argument} ({label}): {json.dumps(value)}' + (f'; basis: {basis}' if basis else ''))
    return '\n'.join(lines)


def revision_prompt(entry: dict, note: str, pack: dict) -> list:
    from vessel_reconstruction.ship_cad import OPERATIONS

    images = '\n'.join(f'{i + 1}. {m["view"]} ({m["width"]}x{m["height"]} px): '
                       + '; '.join(f'{k} = {v}' for k, v in m['calibration'].items())
                       for i, m in enumerate(pack['images']))
    text = PROMPT.format(images=images, part_id=entry['id'], label=entry.get('label', entry['id']),
                         op=entry['op'], values=part_values(entry), note=note,
                         arguments=', '.join(OPERATIONS[entry['op']]))
    content = [{'type': 'text', 'text': text}]
    for meta in pack['images']:
        data = base64.b64encode(Path(meta['path']).read_bytes()).decode()
        content.append({'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{data}'}})
    return [{'role': 'user', 'content': content}]


def updated_entry(old: dict, built: dict, note: str, revision: int, receipts: list) -> dict:
    """The new entry: the rebuilt part's values, with the mark and the revision history."""
    entry = dict(built, label=old.get('label', built['id']), revision=revision, revision_note=note)
    entry['revision_history'] = old.get('revision_history', []) + [{
        'revision': old.get('revision', 0), 'status': old.get('status'), 'geometry': old.get('geometry'),
        'source_labels': old.get('source_labels'), 'volume_m3': old.get('volume_m3')}]
    entry['revision_receipts'] = receipts
    return entry


def revise(folder: Path, pack: dict, part_id: str, note: str, call=None, settings=None) -> dict:
    """Rebuild one part from a mark; return the new entry. ``call`` is the model client."""
    from vessel_reconstruction.ship_cad import triage_program
    from vessel_reconstruction.ship_cad_worker import run as run_worker

    if not 1 <= len(note.strip()) <= MAX_NOTE_CHARS:
        raise ValueError(f'A mark note has 1 to {MAX_NOTE_CHARS} characters.')
    record = load_parts(folder)
    components = record['result']['components']
    index = next((i for i, c in enumerate(components) if c['id'] == part_id), None)
    if index is None:
        raise ValueError(f'No part {part_id!r} in this run.')
    old = components[index]
    if old['op'] not in REVISABLE_OPS:
        raise ValueError(f'Part {part_id!r} ({old["op"]}) cannot be revised from a mark yet.')
    revision = old.get('revision', 0) + 1
    work = folder / 'revisions' / f'{part_id}-r{revision}'
    work.mkdir(parents=True, exist_ok=False)
    call = call or ab.call_model
    settings = settings or ab.ROUNDS['2']
    messages = revision_prompt(old, note, pack)
    receipts, built = [], None
    for turn in range(1, ab.MAX_TURNS + 1):
        text, receipt = call(messages, work / 'receipts', settings)
        receipts.append({k: receipt.get(k) for k in ('request_id', 'state', 'usage', 'seconds')})
        (work / f'reply-{turn}.txt').write_text(text)
        try:
            program = ab.extract_json(text)
            program['components'] = [c for c in program.get('components', []) if c.get('id') == part_id][:1]
            triage_program(program)
            execution = run_worker(program, {}, work / f'task-{turn}')
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
        raise RuntimeError(f'Part {part_id!r} was not rebuilt in {ab.MAX_TURNS} turns; the old part stays.')
    parts = folder / 'whole_vessel'
    if (parts / f'{part_id}.step').is_file():
        shutil.copy2(parts / f'{part_id}.step', parts / f'{part_id}.r{revision - 1}.step')
    shutil.copy2(source, parts / f'{part_id}.step')
    entry = updated_entry(old, built, note, revision, receipts)
    components[index] = entry
    (parts / 'execution.json').write_text(json.dumps(record, indent=2) + '\n')
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True, help='Run folder that holds whole_vessel/')
    parser.add_argument('--pack', type=Path, required=True, help='pack.json with the drawing crops')
    parser.add_argument('--part', required=True)
    parser.add_argument('--note', required=True)
    args = parser.parse_args()
    pack = json.loads(args.pack.read_text())['pack']
    for meta in pack['images']:
        meta['path'] = str(args.pack.parent / meta['file'])
    started = time.time()
    entry = revise(args.folder.resolve(), pack, args.part, args.note)
    print(json.dumps({'part': entry['id'], 'revision': entry['revision'], 'status': entry['status'],
                      'geometry': entry['geometry'], 'volume_m3': entry.get('volume_m3'),
                      'seconds': round(time.time() - started, 1)}, indent=2))


if __name__ == '__main__':
    main()
