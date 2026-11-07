"""Receipt-bound calibration through the Rust worker; never calls HTTP in Python."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from vessel_reconstruction.llm_setup import digest, write_json


SIZES = [(512, 512), (1024, 768), (2048, 480), (4096, 240), (640, 1280)]
MODES = {
    'implicit_pixels': 'Return pixel coordinates, origin at the top-left, x right and y down.',
    'explicit_pixels': 'Return pixel coordinates of the attached image, origin top-left, x right and y down. Use the stated width and height.',
    'normalized_1000': 'Return normalized coordinates: x=1000*column/image_width, y=1000*row/image_height. Origin top-left, x right and y down.',
    'normalized_1': 'Return normalized coordinates in 0..1: x=column/image_width, y=row/image_height. Origin top-left, x right and y down.',
}


def calibration_image(width, height):
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(12, min(24, height // 18)))
    # Grid labels are fractions, not pixel answers to the named marks.
    for fraction in [0.1, 0.3, 0.5, 0.7, 0.9]:
        x, y = round(width * fraction), round(height * fraction)
        draw.line((x, 0, x, height), fill=(215, 215, 215))
        draw.line((0, y, width, y), fill=(215, 215, 215))
        draw.text((x + 2, 1), f'{fraction:.1f}', font=font, fill='gray')
    marks = {name: [round(width * x), round(height * y)] for name, x, y in [
        ('A', .17, .23), ('B', .72, .18), ('C', .39, .61),
        ('D', .83, .77), ('E', .21, .83), ('F', .62, .43)]}
    for index, (name, (x, y)) in enumerate(marks.items()):
        if index % 3 == 0:
            draw.ellipse((x-5, y-5, x+5, y+5), fill='black')
        elif index % 3 == 1:
            draw.line((x-9, y, x+9, y), fill='black', width=3)
            draw.line((x, y-9, x, y+9), fill='black', width=3)
        else:
            draw.line((x-28, y+13, x, y), fill='black', width=3)
            draw.ellipse((x-3, y-3, x+3, y+3), fill='black')
        draw.text((x+12, y-18), name, fill='black', font=font)
    return image, marks


def fit_frame(answers, truth):
    answers, truth = np.asarray(answers, float), np.asarray(truth, float)
    fits = []
    for order, values in [('xy', answers), ('yx', answers[:, ::-1])]:
        scales, offsets, fitted = [], [], []
        for axis in range(2):
            matrix = np.column_stack([values[:, axis], np.ones(len(values))])
            scale, offset = np.linalg.lstsq(matrix, truth[:, axis], rcond=None)[0]
            scales.append(float(scale))
            offsets.append(float(offset))
            fitted.append(matrix @ [scale, offset])
        residual = np.column_stack(fitted) - truth
        fits.append({'axis_order': order, 'scale': scales, 'offset': offsets,
                     'rms_px': float(np.sqrt(np.mean(np.sum(residual ** 2, axis=1))))})
    return min(fits, key=lambda fit: fit['rms_px'])


def request(image, out, context, binary, source_hash=None, crop=None, hide_size=False):
    out.mkdir(parents=True, exist_ok=False)
    prepared = out / 'request'
    prepared.mkdir()
    path = prepared / 'image.png'
    image.quantize(colors=64).save(path, optimize=True)
    manifest = {'schema_version': 'marinaframe.vision_request.v1', 'purpose': 'localisation',
                'source_sha256': source_hash or digest(path), 'engineering_approved': False,
                'context': context, 'images': [{'image_id': 'localisation', 'file': 'image.png',
                    'sha256': digest(path), 'bytes': path.stat().st_size, 'width': image.width,
                    'height': image.height, 'view': 'localisation',
                    'crop_box_px': crop or [0, 0, image.width, image.height]}]}
    if hide_size:
        # Rust still validates and receipts the real dimensions. This flag only
        # suppresses their prompt listing for the implicit-size control arm.
        manifest['context']['omit_image_size_from_prompt'] = True
    write_json(prepared / 'request.json', manifest)
    completed = subprocess.run([str(binary.resolve()), 'vision-request', '--request', str(prepared.resolve()),
        '--out', str((out / 'reading').resolve()), '--provider-transfer-basis',
        'Authorized synthetic development drawing localisation experiment W14'],
        capture_output=True, text=True, timeout=240)
    if completed.returncode:
        write_json(out / 'driver_error.json', {'returncode': completed.returncode, 'stderr': completed.stderr[:1000]})
        return None
    reading = json.loads((out / 'reading' / 'vision_reading.json').read_text())
    return (reading.get('reply') or {}).get('localisation')


def run(out, binary):
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    # Two independent repetitions, not a retry selected for a better answer.
    for width, height in SIZES:
        image, marks = calibration_image(width, height)
        jobs = [(mode, repeat) for mode in MODES for repeat in range(2)]
        def one(job):
            mode, repeat = job
            context = {'coordinate_frame': MODES[mode], 'questions': [
                {'id': name, 'question': f'Locate the centre of mark {name} (dot or cross), or the upper-right endpoint of the short line labelled {name}.'}
                for name in marks]}
            if mode != 'implicit_pixels':
                context['image_size_px'] = [width, height]
            directory = out / f'{width}x{height}-{mode}-{repeat}'
            reply = request(image, directory, context, binary, hide_size=mode == 'implicit_pixels')
            points, targets, errors = [], [], []
            for answer in (reply or {}).get('answers', []):
                if answer['id'] not in marks or answer['x'] is None or answer['y'] is None:
                    continue
                point = [answer['x'], answer['y']]
                factor = [width / 1000, height / 1000] if mode == 'normalized_1000' else [width, height] if mode == 'normalized_1' else [1, 1]
                mapped = np.array(point) * factor
                target = marks[answer['id']]
                points.append(point)
                targets.append(target)
                errors.append(float(np.linalg.norm(mapped - target)))
            row = {'size': [width, height], 'mode': mode, 'repeat': repeat, 'marks_returned': len(points),
                   'errors_px': errors, 'fit': fit_frame(points, targets) if len(points) >= 3 else None,
                   'raw_reply': reply, 'truth': marks}
            write_json(directory / 'score.json', row)
            return row
        with ThreadPoolExecutor(max_workers=2) as pool:
            batch = list(pool.map(one, jobs))
        rows.extend(batch)
        write_json(out / 'results.json', rows)
        if all(row['marks_returned'] == 0 for row in batch):
            write_json(out / 'stop.json', {'reason': 'no_progress_all_modes_failed', 'size': [width, height]})
            break
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    run(args.out, args.binary)


if __name__ == '__main__':
    main()
