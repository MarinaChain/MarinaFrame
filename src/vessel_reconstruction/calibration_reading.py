"""Label questions for the automatic body-plan calibration (`sheet_calibration`).

A model only reads printed labels and numbers here; code finds and measures every line, and
the images carry code-drawn tags (H1, V1, T1) so that the model names a tag, not a position.
The one coarse position a model gives is the box of each view on a whole-sheet overview; code
then measures inside it.

Transport: the Claude Code CLI in print mode on the Claude subscription (`claude -p`, no tools,
API key variables removed), as in the holdout harnesses. Answers are cached by question digest in
a folder outside the repository, so a repeated run makes no new call.

Two side checks are independent questions: `numbering_direction` reads printed text on the whole
sheet (station marks next to the stem or stern, table headers such as "Transom", deck names);
`fore_half_by_shape` sees only the body plan with all lettering removed by code and judges the
drawn shapes (transom, counter, deadwood, shaft, stem).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import subprocess
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

from vessel_reconstruction.sheet_calibration import Line, parse_feet

MODEL = 'claude-sonnet-5-5'
SYSTEM_PROMPT = 'You read printed labels and numbers on images of ship drawings. Reply with the JSON object only.'
TIMEOUT_S = 600
API_KEY_VARIABLES = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')
# Longest image side sent to the model (px).
IMAGE_SIDE = 1568
# A coarse box from the overview is grown by this share of the sheet on each side.
BOX_MARGIN_SHARE = 0.035
# The scale-bar and notes boxes are small and close to other ink: a smaller margin.
SMALL_BOX_MARGIN_SHARE = 0.005
# Lettering removed for the shape check: ink components smaller than this share of the image side.
LETTER_MAX_SHARE = 0.03
# Tag drawing.
TAG_MARGIN_PX = 70
TAG_COLOUR = (220, 0, 0)
CENTRE_COLOUR = (0, 90, 220)
# A scale bar's ticks: vertical strokes covering this share of the bar band.
TICK_MIN_FILL = 0.6
MIN_TICKS = 3
# A scale bar's horizontal strokes: ink runs at least this share of the crop width.
BAR_MIN_RUN_SHARE = 0.08
UNIT_FT = {'ft': 1.0, 'feet': 1.0, 'foot': 1.0, 'in': 1 / 12, 'inches': 1 / 12, 'm': 1 / 0.3048,
           'metres': 1 / 0.3048, 'meters': 1 / 0.3048, 'cm': 0.01 / 0.3048, 'centimeters': 0.01 / 0.3048,
           'centimetres': 0.01 / 0.3048}


# ---------------------------------------------------------------- transport

def claude_command(model: str) -> list[str]:
    return ['claude', '-p', '--model', model, '--tools', '', '--input-format', 'stream-json',
            '--output-format', 'stream-json', '--verbose', '--no-session-persistence', '--strict-mcp-config',
            '--system-prompt', SYSTEM_PROMPT]


def claude_ask(model: str = MODEL, runner=subprocess.run, receipts: Path | None = None):
    """An `ask(prompt, pngs) -> text` through the Claude Code CLI on the subscription."""
    environment = {key: value for key, value in os.environ.items() if key not in API_KEY_VARIABLES}

    def ask(prompt: str, pngs: list[bytes]) -> str:
        content = [{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                                 'data': base64.b64encode(png).decode()}} for png in pngs]
        content.append({'type': 'text', 'text': prompt})
        message = {'type': 'user', 'message': {'role': 'user', 'content': content}}
        started = time.time()
        try:
            done = runner(claude_command(model), input=json.dumps(message) + '\n', capture_output=True, text=True,
                          env=environment, timeout=TIMEOUT_S)
            result = next((json.loads(line) for line in done.stdout.splitlines()
                           if line.startswith('{') and json.loads(line).get('type') == 'result'), None)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            result = None
        if receipts is not None:
            receipts.mkdir(parents=True, exist_ok=True)
            usage = (result or {}).get('usage') or {}
            with (receipts / 'claude.jsonl').open('a') as log:
                log.write(json.dumps({'model': model, 'seconds': round(time.time() - started, 1),
                                      'state': 'completed' if result and not result.get('is_error') else 'failed',
                                      'input_tokens': sum(usage.get(k) or 0 for k in (
                                          'input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')),
                                      'output_tokens': usage.get('output_tokens')}) + '\n')
        if not result or result.get('is_error'):
            raise RuntimeError('the claude CLI gave no answer')
        return result.get('result') or ''

    return ask


def parse_json(text: str) -> dict:
    """The first JSON object in a reply (a fenced block is accepted)."""
    start = text.find('{')
    if start < 0:
        raise ValueError('no JSON object in the reply')
    depth = 0
    for index in range(start, len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0:
                return json.loads(text[start:index + 1])
    raise ValueError('unterminated JSON object')


# ---------------------------------------------------------------- images

def reduce(ink: np.ndarray, side: int = IMAGE_SIDE) -> tuple[np.ndarray, int]:
    """Ink reduced by block max (thin lines stay visible) to at most `side` px; returns (mask, step)."""
    step = max(1, int(np.ceil(max(ink.shape) / side)))
    height, width = (ink.shape[0] // step) * step, (ink.shape[1] // step) * step
    if step == 1:
        return ink.copy(), 1
    blocks = ink[:height, :width].reshape(height // step, step, width // step, step)
    return blocks.any(axis=(1, 3)), step


def to_png(mask: np.ndarray, marks=None) -> bytes:
    from PIL import Image, ImageDraw
    image = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert('RGB')
    if marks:
        marks(ImageDraw.Draw(image), image)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def _clip_box(box: list, shape: tuple) -> list[int]:
    return [max(0, int(box[0])), max(0, int(box[1])), min(shape[1], int(box[2])), min(shape[0], int(box[3]))]


def _strip_stack(crop: np.ndarray, side: int = IMAGE_SIDE) -> np.ndarray:
    """A wide, low crop cut into strips stacked top to bottom, so the text stays large."""
    height, width = crop.shape
    strips = max(1, min(4, int(np.ceil(width / side))))
    if strips == 1 or height * strips > width:
        return crop
    cut = int(np.ceil(width / strips))
    gap = np.zeros((20, cut), dtype=bool)
    parts = []
    for index in range(strips):
        part = crop[:, index * cut:(index + 1) * cut]
        part = np.pad(part, ((0, 0), (0, cut - part.shape[1])))
        parts += [part, gap]
    return np.vstack(parts[:-1])


def without_lettering(mask: np.ndarray) -> np.ndarray:
    """Remove small ink components (letters, digits) from a reduced drawing."""
    labels, count = ndimage.label(mask, structure=np.ones((3, 3)))
    if count == 0:
        return mask
    limit = LETTER_MAX_SHARE * max(mask.shape)
    keep = np.zeros(count + 1, dtype=bool)
    for index, found in enumerate(ndimage.find_objects(labels), start=1):
        rows, cols = found
        keep[index] = max(rows.stop - rows.start, cols.stop - cols.start) >= limit
    return keep[labels]


# ---------------------------------------------------------------- prompts

LOCATE_PROMPT = """This image is a whole scanned sheet of ship lines drawings ({width} x {height} px as shown).
Find these and give each box as [left, top, right, bottom] in the pixel coordinates of THIS image:
- body_plan_box: the BODY PLAN (cross-section curves of the hull drawn about one vertical centreline,
  usually with a waterline/buttock grid). Include its grid lines and their printed labels, nothing else.
- scale_bar_box: a graphic scale bar in feet (or metres) with numbered ticks, or null.
- spacing_text_box: the printed notes or table row labels that state the buttock-line spacing or
  offsets and the waterline spacing (for example "Buttock lines spaced 1'-0\\"", or row labels
  "Buttock 1-0-0"), or null. Do not read the offset values of a table.
Also read scale_text: the printed drawing scale exactly as printed (for example 3/8" = 1'-0"), or null.
Reply with JSON only: {{"body_plan_box": [..], "scale_bar_box": [..] or null, "spacing_text_box": [..] or null,
"scale_text": "..." or null}}"""

LINES_PROMPT = """This image is the BODY PLAN of a ship drawing. Code found straight grid lines and tagged them in red in the margins: horizontal lines H1..H{h} (tags at
the left and right edges), vertical lines V1..V{v} (tags at the top and bottom edges).
Read only PRINTED text; never guess a value that is not printed.
1. For each horizontal tag whose line carries a printed label (a waterline height such as 32'-0" W.L.,
   17'-7" WL, or a name such as Base, BASELINE, W0), give the label text as printed.
2. For each vertical tag whose line carries a printed label (a buttock offset such as 4 Ft., 12, B2),
   give the label text as printed.
3. centreline: the V tag of the body plan's centreline (the vertical line about which the two halves are
   drawn; often labelled CL), or null.
4. The station numbers printed on or next to the station curves LEFT of the centreline, and RIGHT of
   it (numbers only, for example "STA 6" -> 6; leave out words such as Transom).
Reply with JSON only: {{"horizontal": {{"H1": "label" ...}}, "vertical": {{"V1": "label" ...}},
"centreline": "V..", "stations_left": [..], "stations_right": [..]}}. Leave a tag out when its line has no printed label."""

NOTES_PROMPT = """This image shows printed notes or table row labels from a ship lines drawing (a long line of
text may be cut into strips shown one below the other). Read only what is printed:
- buttock_spacing: the stated spacing between buttock lines (for example 1'-0" or 8-1/16"), or, when only
  buttock row labels are printed (Buttock 1-0-0, Buttock 2-0-0, ...), the step between them; else null.
- waterline_spacing: the stated spacing between waterlines, or null.
- scale_text: a printed drawing scale (for example 3/4"=1'-0"), or null.
Do not read offset values from a table. Reply with JSON only:
{"buttock_spacing": "..." or null, "waterline_spacing": "..." or null, "scale_text": "..." or null}"""

BAR_PROMPT = """This image is a graphic scale bar from a ship drawing. Code tagged vertical strokes in the bar
in red: T1..T{t} (tags under the bar). For each tag that sits exactly at a NUMBERED tick, give the printed
number, and give the unit printed on the bar (feet, inches, metres or centimeters). If the image has two
bars, use the bar in feet. Reply with JSON only: {{"ticks": {{"T1": 0, ...}}, "unit": "feet"}}"""

DIRECTION_PROMPT = """This image is a whole scanned sheet of ship lines drawings. Use PRINTED TEXT to decide how the
stations are numbered: station marks in the profile or plan view next to the stem (bow) or the stern,
table headers (for example a "Transom" column next to one end of the station numbers), deck names
(forecastle is forward, poop is aft), or notes. Is the LOWEST station number at the bow or at the stern?
Reply with JSON only: {"lowest_at": "bow" | "stern" | "unsure", "evidence": "short reason"}"""

SHAPE_PROMPT = """This image is the BODY PLAN of a ship: cross sections of one half of the hull, the forebody
sections drawn on one side of the blue centreline and the afterbody sections on the other. All lettering
was removed on purpose. Judge from the drawn SHAPES only which side is the FOREBODY (bow half): the
afterbody often shows a transom, a counter, deadwood, a skeg, a propeller shaft or rudder structure, and
sections that end on a flat or raised stern; the forebody shows sections running down to the stem and keel.
Reply with JSON only: {"fore_half": "left" | "right" | "unsure", "evidence": "short reason"}"""


# ---------------------------------------------------------------- reading

class ClaudeReading:
    """The label questions of one sheet, answered by `ask(prompt, pngs) -> text` and cached."""

    def __init__(self, ask, cache: Path | None = None, sheet_id: str = '', images: Path | None = None):
        self.ask = ask
        self.images = images  # when set, every question image is saved here (outside the repository)
        self.cache = cache
        self.sheet_id = sheet_id
        self.calls = 0
        self.log: list[dict] = []
        self._overview = None

    # -- cached question
    def question(self, name: str, prompt: str, pngs: list[bytes]) -> dict:
        digest = hashlib.sha256((self.sheet_id + name + prompt).encode() + b''.join(pngs)).hexdigest()[:24]
        if self.images is not None:
            self.images.mkdir(parents=True, exist_ok=True)
            for index, png in enumerate(pngs):
                (self.images / f'{name}-{index}.png').write_bytes(png)
        path = self.cache / f'{name}-{digest}.json' if self.cache else None
        if path and path.exists():
            answer = json.loads(path.read_text())
            self.log.append({'question': name, 'cached': True})
            return answer
        answer = {}
        for attempt in range(2):
            try:
                self.calls += 1
                text = self.ask(prompt, pngs)
                answer = parse_json(text)
                break
            except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
                self.log.append({'question': name, 'attempt': attempt + 1, 'error': str(exc)[:200]})
        if path and answer:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(answer, indent=2) + '\n')
        self.log.append({'question': name, 'cached': False, 'answered': bool(answer)})
        return answer

    def overview(self, ink: np.ndarray):
        if self._overview is None:
            mask, step = reduce(ink)
            self._overview = (to_png(mask), step, mask.shape)
        return self._overview

    # -- questions used by sheet_calibration.calibrate
    def locate(self, ink: np.ndarray) -> dict:
        png, step, shape = self.overview(ink)
        answer = self.question('locate', LOCATE_PROMPT.format(width=shape[1], height=shape[0]), [png])
        margins = {'body_plan_box': BOX_MARGIN_SHARE * max(ink.shape),
                   'scale_bar_box': SMALL_BOX_MARGIN_SHARE * max(ink.shape),
                   'spacing_text_box': SMALL_BOX_MARGIN_SHARE * max(ink.shape)}
        result = {'raw': answer, 'scale_text': answer.get('scale_text'),
                  'source': 'model:coarse box on the overview, grown by code'}
        for key in ('body_plan_box', 'scale_bar_box', 'spacing_text_box'):
            box = answer.get(key)
            if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                margin = margins[key]
                grown = [box[0] * step - margin, box[1] * step - margin, box[2] * step + margin,
                         box[3] * step + margin]
                result[key + '_px'] = _clip_box(grown, ink.shape)
        self._spacing_box = result.get('spacing_text_box_px')
        return result

    def label_lines(self, ink, box, horizontals: list[Line], verticals: list[Line]) -> dict:
        crop = ink[box[1]:box[3], box[0]:box[2]]
        mask, step = reduce(crop, IMAGE_SIDE - 2 * TAG_MARGIN_PX)
        mask = np.pad(mask, TAG_MARGIN_PX)
        h_tags = {f'H{i + 1}': line for i, line in enumerate(sorted(horizontals, key=lambda l: l.position))}
        v_tags = {f'V{i + 1}': line for i, line in enumerate(sorted(verticals, key=lambda l: l.position))}

        def marks(draw, image):
            for tag, line in h_tags.items():
                y = TAG_MARGIN_PX + (line.position - box[1]) / step
                draw.line([(TAG_MARGIN_PX - 12, y), (TAG_MARGIN_PX - 2, y)], fill=TAG_COLOUR, width=2)
                draw.line([(image.width - TAG_MARGIN_PX + 2, y), (image.width - TAG_MARGIN_PX + 12, y)],
                          fill=TAG_COLOUR, width=2)
                draw.text((4, y - 6), tag, fill=TAG_COLOUR)
                draw.text((image.width - TAG_MARGIN_PX + 16, y - 6), tag, fill=TAG_COLOUR)
            for index, (tag, line) in enumerate(v_tags.items()):
                x = TAG_MARGIN_PX + (line.position - box[0]) / step
                offset = 14 * (index % 3)
                draw.line([(x, TAG_MARGIN_PX - 10), (x, TAG_MARGIN_PX - 2)], fill=TAG_COLOUR, width=2)
                draw.text((x - 8, 6 + offset), tag, fill=TAG_COLOUR)
                draw.text((x - 8, image.height - TAG_MARGIN_PX + 8 + offset), tag, fill=TAG_COLOUR)

        png = to_png(mask, marks)
        answer = self.question('lines', LINES_PROMPT.format(h=len(h_tags), v=len(v_tags)), [png])
        result = {'raw': answer, 'horizontal_ft': [], 'base_lines': [], 'vertical_ft': [],
                  'centreline': v_tags.get(str(answer.get('centreline') or '').strip())}
        for tag, text in (answer.get('horizontal') or {}).items():
            line = h_tags.get(tag)
            if line is None or not text:
                continue
            label = str(text)
            if re.search(r'\bbase', label, flags=re.IGNORECASE) or re.fullmatch(r'\s*W\s*0\b.*', label):
                result['base_lines'].append(line)
                if not re.search(r"\d\s*['-]", label):
                    continue
            feet = parse_feet(re.sub(r'(?i)(water ?line|w\.?\s?l\.?|wl|base|baseline)', '', label))
            if feet is not None and not re.match(r'(?i)\s*W\s*-?\d+\s*$', label):
                result['horizontal_ft'].append((line, feet))
        for tag, text in (answer.get('vertical') or {}).items():
            line = v_tags.get(tag)
            feet = parse_feet(re.sub(r'(?i)(buttock|but\.?|b(?=\d))', '', str(text))) if line and text else None
            if feet:
                result['vertical_ft'].append((line, feet))
        for key in ('stations_left', 'stations_right'):  # left and right of the image
            numbers = []
            for value in answer.get(key) or []:
                match = re.search(r'-?\d+', str(value))
                if match:
                    numbers.append(int(match[0]))
            result[key] = sorted(set(numbers))
        return result

    def read_notes(self, ink) -> dict:
        box = getattr(self, '_spacing_box', None)
        if not box:
            return {}
        crop = _strip_stack(ink[box[1]:box[3], box[0]:box[2]])
        mask, _ = reduce(crop)
        answer = self.question('notes', NOTES_PROMPT, [to_png(mask)])
        return {'raw': answer, 'buttock_spacing_ft': parse_feet(answer.get('buttock_spacing')),
                'waterline_spacing_ft': parse_feet(answer.get('waterline_spacing')),
                'scale_text': answer.get('scale_text')}

    def read_scale_bar(self, ink, box) -> dict:
        crop = ink[box[1]:box[3], box[0]:box[2]]
        ticks = scale_bar_ticks(crop)
        if len(ticks) < 2:
            return {}
        mask, step = reduce(crop, IMAGE_SIDE)
        mask = np.pad(mask, ((0, TAG_MARGIN_PX), (0, 0)))
        tags = {f'T{i + 1}': column for i, column in enumerate(ticks)}

        def marks(draw, image):
            for index, (tag, column) in enumerate(tags.items()):
                x = column / step
                draw.line([(x, image.height - TAG_MARGIN_PX), (x, image.height - TAG_MARGIN_PX + 12)],
                          fill=TAG_COLOUR, width=2)
                draw.text((x - 8, image.height - TAG_MARGIN_PX + 16 + 16 * (index % 3)), tag, fill=TAG_COLOUR)

        answer = self.question('scale_bar', BAR_PROMPT.format(t=len(tags)), [to_png(mask, marks)])
        unit = UNIT_FT.get(str(answer.get('unit') or '').strip().lower())
        found = []
        for tag, value in (answer.get('ticks') or {}).items():
            if tag in tags and isinstance(value, (int, float)) and not isinstance(value, bool):
                found.append((box[0] + tags[tag], float(value)))
        return {'raw': answer, 'ticks': found if unit else [], 'unit_ft': unit}

    def numbering_direction(self, ink) -> dict:
        png, _, _ = self.overview(ink)
        answer = self.question('direction', DIRECTION_PROMPT, [png])
        lowest = str(answer.get('lowest_at') or 'unsure').lower()
        return {'lowest_at': lowest if lowest in ('bow', 'stern') else 'unsure', 'evidence': answer.get('evidence')}

    def fore_half_by_shape(self, ink, box, centre) -> dict:
        crop = ink[box[1]:box[3], box[0]:box[2]]
        mask, step = reduce(crop)
        mask = without_lettering(mask)

        def marks(draw, image):
            x = (centre - box[0]) / step
            draw.line([(x, 0), (x, image.height)], fill=CENTRE_COLOUR, width=2)

        answer = self.question('shape', SHAPE_PROMPT, [to_png(mask, marks)])
        half = str(answer.get('fore_half') or 'unsure').lower()
        return {'fore_half': half if half in ('left', 'right') else None, 'evidence': answer.get('evidence')}


def scale_bar_ticks(crop: np.ndarray) -> list[float]:
    """Columns (crop px) of the vertical strokes inside a scale bar's band of horizontal strokes."""
    if crop.size == 0:
        return []
    runs = []
    for row in range(crop.shape[0]):
        line = crop[row]
        if not line.any():
            runs.append(0)
            continue
        padded = np.concatenate(([0], line.astype(np.int8), [0]))
        edges = np.flatnonzero(np.diff(padded))
        runs.append(int(np.max(edges[1::2] - edges[::2])))
    runs = np.array(runs)
    bar_rows = np.flatnonzero(runs >= BAR_MIN_RUN_SHARE * crop.shape[1])
    if bar_rows.size == 0:
        return []
    # The first bar from the top with at least three ticks (a sheet may draw a feet bar above a
    # metric bar, and the coarse box may hold other ink).
    for group in np.split(bar_rows, np.flatnonzero(np.diff(bar_rows) > 60) + 1):
        top, bottom = int(group[0]), int(group[-1])
        band = crop[max(0, top - 2):bottom + 3]
        found = np.flatnonzero(band.mean(axis=0) >= TICK_MIN_FILL)
        if found.size == 0:
            continue
        ticks = [float(part.mean()) for part in np.split(found, np.flatnonzero(np.diff(found) > 2) + 1)]
        if len(ticks) >= MIN_TICKS:
            return ticks
    return []


# ---------------------------------------------------------------- person check

OVERLAY_COLOURS = {'centre': (220, 0, 0), 'base': (0, 150, 0), 'waterline': (0, 90, 220), 'grid': (160, 160, 160),
                   'fore': (200, 90, 0), 'aft': (120, 0, 160), 'flag': (220, 0, 0)}


def overlay_png(ink: np.ndarray, calibration) -> bytes:
    """The calibration drawn over the body plan, for a person to confirm in one look.

    Red: centreline. Green: baseline. Blue: waterlines with their heights (ft-in-eighths).
    Grey: buttock grid columns. The two halves are named FORE and AFT with their stations,
    outermost first. Open flags are listed under the drawing.
    """
    from PIL import Image, ImageDraw, ImageFont
    box = calibration.box
    crop = ink[box[1]:box[3], box[0]:box[2]]
    mask, step = reduce(crop)
    flags = [f'{f.field}: {f.message}' for f in calibration.flags]
    footer = 24 * (len(flags) + 1) + 10
    image = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert('RGB')
    canvas = Image.new('RGB', (image.width, image.height + 40 + footer), 'white')
    canvas.paste(image, (0, 40))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:  # Pillow before 10.1
        font = ImageFont.load_default()

    def x_of(column):
        return (column - box[0]) / step

    def y_of(row):
        return 40 + (row - box[1]) / step

    for side in calibration.sides:
        for column in side['grid_columns']:
            draw.line([(x_of(column), 40), (x_of(column), 40 + image.height)], fill=OVERLAY_COLOURS['grid'])
    for waterline in calibration.waterlines:
        y = y_of(waterline['row'])
        draw.line([(0, y), (image.width, y)], fill=OVERLAY_COLOURS['waterline'], width=2)
        draw.text((4, y - 20), f"WL {waterline['label']}", fill=OVERLAY_COLOURS['waterline'], font=font)
    if calibration.baseline_row is not None:
        y = y_of(calibration.baseline_row)
        draw.line([(0, y), (image.width, y)], fill=OVERLAY_COLOURS['base'], width=3)
        draw.text((4, y + 2), 'BASELINE', fill=OVERLAY_COLOURS['base'], font=font)
    if calibration.centre_column is not None:
        x = x_of(calibration.centre_column)
        draw.line([(x, 40), (x, 40 + image.height)], fill=OVERLAY_COLOURS['centre'], width=3)
        for side in calibration.sides:
            text = f"{side['name'].upper()}: {' '.join(str(s) for s in side['stations_outer_first'])}"
            width = draw.textlength(text, font=font)
            left = x + 12 if side['sign'] > 0 else x - 12 - width
            draw.text((left, 10), text, fill=OVERLAY_COLOURS[side['name']], font=font)
    scale = f'{calibration.pixels_per_ft:.2f} px/ft' if calibration.pixels_per_ft else 'scale not found'
    lines = [f'Scale {scale}. Confirm the centreline, baseline, waterlines and which half is FORE.'] + flags
    for index, text in enumerate(lines):
        draw.text((6, 40 + image.height + 6 + 24 * index), text[:200],
                  fill=OVERLAY_COLOURS['flag'] if index else (0, 0, 0), font=font)
    buffer = io.BytesIO()
    canvas.save(buffer, format='PNG')
    return buffer.getvalue()
