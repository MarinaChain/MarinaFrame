"""Read grid scale without supplying the answer in the same request."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
from pathlib import Path

from PIL import Image

from benchmarks.localisation.calibrate import request
from benchmarks.localisation.drawings import fit_image
from benchmarks.llm_setup_review.sample import SETUP_SAMPLE_HULLS
from vessel_reconstruction.llm_setup import digest, write_json


def one(job):
    case, root, out, binary = job
    source = root / 'inputs' / case / 'drawing.png'
    spec = json.loads(source.with_name('spec.json').read_text())
    params = json.loads((root / 'params' / f'{case}.json').read_text())
    if params['split'] != 'development':
        raise ValueError('Development only')
    image = Image.open(source).convert('RGB')
    section = spec['sections'][2]
    roi = section['roi_px']
    box = [max(0, roi[0]-55), max(0, roi[1]-40), min(image.width, roi[2]+30), min(image.height, roi[3]+45)]
    attached = fit_image(image, box)
    context = {'image_size_px': list(attached.size), 'coordinate_frame': 'attachment pixels',
               'questions': [{'id': 'S', 'question': 'Read the horizontal scale from the printed buttock grid numbers and their line spacing. Return value as attachment pixels per printed drawing unit. If units are not stated, report that in evidence; do not invent metres. x=y=null.'}]}
    reply = request(attached, out/case, context, binary, digest(source), box)
    answer = next((a for a in (reply or {}).get('answers', []) if a['id']=='S'), {})
    truth = params['geometry']['ppm'] * attached.width / (box[2]-box[0])
    value = answer.get('value')
    row = {'case_id': case, 'level': params['level'], 'layout': params['layout'], 'answer': answer,
           'truth_attachment_px_per_unit': truth, 'relative_error': abs(value/truth-1) if value is not None else None}
    write_json(out/case/'score.json', row)
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(one,[(f'{h}-L{l}',args.root,args.out,args.binary) for h in SETUP_SAMPLE_HULLS for l in range(4)]))
    write_json(args.out/'results.json',rows)


if __name__=='__main__':
    main()
