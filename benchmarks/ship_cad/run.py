"""Development driver: drawing-only proposals, deterministic tools, isolated CAD.

All drawing derivatives and provider receipts belong under ignored work/.
Truth is deliberately not accepted by this inference command.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from vessel_reconstruction.ship_cad import validate_program
from vessel_reconstruction.ship_measure import investigate, read_dxf, source_hash
from vessel_reconstruction.ship_cad_worker import run as run_worker


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def region_bounds(box, bounds):
    if (len(box) != 4 or not all(isinstance(v, (int, float)) and 0 <= v <= 1000 for v in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        raise ValueError('Invalid normalized attachment region')
    x0, y0, x1, y1 = bounds
    # Attachment y points down; DXF y points up.
    return [x0+(x1-x0)*box[0]/1000, y0+(y1-y0)*(1-box[3]/1000),
            x0+(x1-x0)*box[2]/1000, y0+(y1-y0)*(1-box[1]/1000)]


def progress_key(measurements):
    values = [r['value'] for r in measurements.values() if r.get('status') == 'measured']
    return hashlib.sha256(json.dumps(sorted(json.dumps(v, sort_keys=True) for v in values)).encode()).hexdigest()


def render_view(view, out):
    """Render source vectors and printed labels, recording the exact transform."""
    import ezdxf
    from PIL import Image, ImageDraw

    bounds = view['bounds']
    x0, y0, x1, y1 = bounds
    scale = min(1400/(x1-x0), 700/(y1-y0))
    width, height = round((x1-x0)*scale), round((y1-y0)*scale)
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    def point(p):
        return ((p[0]-x0)/(x1-x0)*width, (y1-p[1])/(y1-y0)*height)
    entities = read_dxf(Path(view['file']), layers=view.get('layers'))
    for entity in entities:
        p = entity['points']
        if any(x0 <= q[0] <= x1 and y0 <= q[1] <= y1 for q in p):
            draw.line([point(q) for q in p], fill='black', width=1)
    document = ezdxf.readfile(view['file'])
    for entity in document.modelspace().query('TEXT MTEXT'):
        p = entity.dxf.insert
        if x0 <= p.x <= x1 and y0 <= p.y <= y1:
            text = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.plain_text()
            draw.text(point((p.x,p.y)), text, fill='black')
    image.save(out)
    return {'image_id': view['name'], 'file': out.name, 'sha256': source_hash(out),
            'bytes': out.stat().st_size, 'width': width, 'height': height, 'view': view['name'],
            'crop_box_px': [0,0,width,height]}


def hull_measurement(dxf, out):
    from benchmarks.gunnerus.make_gunnerus_configs import vector_config
    from vessel_reconstruction.lines_dxf import BodyPlanView, StationRequest, SideLine, read_stations

    config, ledger = vector_config(dxf)
    view = BodyPlanView(**config['view'])
    requests = [StationRequest(**s) for s in config['stations']]
    read = read_stations(dxf, view, requests, pick_tolerance=config['pick_tolerance'],
                         side_line=SideLine(**config['side_line']), regions=True,
                         centreline_closure_m=config['centreline_closure_m'])
    write(out/'hull-config.json', config)
    write(out/'hull-identity.json', ledger)
    write(out/'hull-read.json', read)
    return {'status': 'measured' if len(read['sections']) >= 3 else 'failed',
            'kind': 'sections', 'value': read['sections'], 'view':'body', 'region':'hull',
            'method':'body_plan_regions', 'source_sha256':source_hash(dxf),
            'entity_ids': [s['id'] for s in read['sections']],
            'reason':'Existing drawing-only station identity rules are provisional; no truth input',
            'abstentions':read['abstentions']}


def drawing_audit(lines):
    """Independent drawing traces; missing identities remain blocking gaps."""
    import ezdxf
    from benchmarks.gunnerus.make_gunnerus_configs import profile_outline, PROFILE_FRAME0_X, BASELINE_Y
    doc = ezdxf.readfile(lines)
    outline = profile_outline(doc)
    profile = [[float((p[0]-PROFILE_FRAME0_X)/1000),float((p[1]-BASELINE_Y)/1000)] for p in outline]
    # Plan waterlines require semantic identity. Do not use the entire plan ink
    # cloud as if all its lines described the selected horizontal cut.
    return {'planes':{'profile':0.0, 'plan':2.5, 'body':17.0}, 'drawings':{'profile':profile},
            'provenance':{'profile':{'source_sha256':source_hash(lines),'method':'closed centreline buttock'},
                          'plan':{'missing':'Waterline contour identity not resolved'},
                          'body':{'missing':'Independent station correspondence not resolved'}}}


def run(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Freeze bytes before any later test build. Python edits must also stop during this run.
    binary = out/'marinaframe'
    shutil.copy2(args.controller, binary)
    ga = args.sources/'polarkonsult/GA Gunnerus Rev1.dxf'
    lines = args.sources/'polarkonsult/Lines Plan Rev0.dxf'
    views = {
        'plan': {'file':str(ga), 'bounds':[3000,22000,41000,33500], 'origin':[4973.089172,27719.422877]},
        'profile': {'file':str(ga), 'bounds':[3000,46000,41000,64000], 'origin':[4973.089172,47493.95]},
        'body': {'file':str(lines), 'bounds':[53500,24400,63400,32800], 'origin':[58433.8,25121.5]},
    }
    for name, view in views.items():
        view.update(name=name, metres_per_unit=0.001, regions={})
    # These drawing calibrations are caller-reviewed, not LLM-discovered.
    write(out/'view-calibration.json', views)
    if args.reuse_drawings:
        # Reuse only host-generated drawing artifacts, with their source hashes checked.
        old = json.loads((args.reuse_drawings/'hull-config.json').read_text())
        if source_hash(Path(old['dxf'])) != source_hash(lines):
            raise ValueError('Drawing cache source changed')
        for name in ('plan.png','profile.png','body.png','hull-config.json','hull-identity.json','hull-read.json'):
            shutil.copy2(args.reuse_drawings/name,out/name)
        from PIL import Image
        images = []
        for name in views:
            path = out/f'{name}.png'
            with Image.open(path) as image:
                width,height = image.size
            images.append({'image_id':name,'file':path.name,'sha256':source_hash(path),
                           'bytes':path.stat().st_size,'width':width,'height':height,
                           'view':name,'crop_box_px':[0,0,width,height]})
        read = json.loads((out/'hull-read.json').read_text())
        base = {'hull_sections':{'status':'measured','kind':'sections','value':read['sections'],
                'view':'body','region':'hull','method':'body_plan_regions','source_sha256':source_hash(lines),
                'entity_ids':[s['id'] for s in read['sections']], 'abstentions':read['abstentions'],
                'reason':'Provisional drawing-only station rules'}}
    else:
        images = [render_view(v, out/f'{name}.png') for name,v in views.items()]
        base = {'hull_sections':hull_measurement(lines, out)}
    audit = drawing_audit(lines)
    write(out/'drawing-audit.json', audit)
    best_resolved = 0
    stale = 0
    round_number = 0
    feedback = {}
    cache = {}
    while True:
        round_dir = out/f'round-{round_number:03d}'
        prepared = round_dir/'prepared'
        prepared.mkdir(parents=True)
        for meta in images:
            shutil.copy2(out/meta['file'], prepared/meta['file'])
        manifest = {'schema_version':'marinaframe.vision_request.v1','purpose':'ship_cad',
                    'source_sha256':source_hash(ga), 'engineering_approved':False, 'images':images,
                    'context':{'coordinate_frame':'normalized_attachment_1000',
                               'available_measurements':{'hull_sections':{'kind':'sections', 'view':'body',
                                  'region':'hull','method':'body_plan_regions',
                                  'status':base['hull_sections']['status']}},
                               'required_hull_component':{'id':'hull','op':'hull',
                                   'source':{'view':'body','region':'hull','method':'body_plan_regions'},
                                   'args':{'sections':'hull_sections'}},
                               'hull_note':'Copy required_hull_component exactly. hull_body is NOT a valid source '
                                   'region for hull_sections. Do not substitute it or add a hull measurement request.',
                               'drawing_note':'plan is A-deck; profile shows upperworks; body is lines-plan hull. '
                                  'Host calibration is provisional. Include visible missing parts as components.',
                               'operation_args': {'hull':['sections'], 'deck':['outline','height'],
                                   'deckhouse':['outline','height'], 'bulwark':['outline','height','thickness'],
                                   'appendage':['outline','span'], 'opening':['outline','height','target']},
                               'required_note':'Every listed argument is REQUIRED. Use a missing named reference '
                                   'when no measurement exists. Do not request body_plan_regions: reference the '
                                   'existing hull_sections directly, with source body/hull/body_plan_regions. '
                                   'Measurement tools are ONLY closed_outline and parallel_lines. '
                                   'All measurement identifiers must be new; never redefine hull_sections.',
                               'previous_tool_results':feedback}}
        write(prepared/'request.json', manifest)
        call = subprocess.run([str(binary),'vision-request','--request',str(prepared), '--out',str(round_dir/'provider'),
                               '--provider-transfer-basis','Authorized Gunnerus development drawing test W13'],
                              capture_output=True,text=True,timeout=240)
        (round_dir/'stdout.txt').write_text(call.stdout)
        (round_dir/'stderr.txt').write_text(call.stderr)
        reading_path = round_dir/'provider/vision_reading.json'
        if not reading_path.exists():
            write(out/'stop.json', {'reason':'provider_driver_failed','exit_code':call.returncode})
            break
        reading = json.loads(reading_path.read_text())
        reply = (reading.get('reply') or {}).get('ship_cad')
        if not reply:
            # Invalid schema is no progress. Feed back only the typed guard reason;
            # never reinterpret or execute rejected model content.
            errors = [json.loads(p.read_text()).get('error_code') for p in (round_dir/'provider/receipts').glob('*.json')]
            stale += 1
            feedback = {'schema_rejection':str(errors), 'instruction':'Each measurement must name a region '
                        'with the SAME view. Define separate profile and plan regions. Do not reuse a plan region '
                        'for a profile measurement. Retain all required component arguments.'}
            if stale >= 2:
                write(out/'stop.json', {'reason':'no_valid_program_progress','rounds':round_number+1})
                break
            round_number += 1
            continue
        program = validate_program({'schema':reply['schema'],'components':reply['components']})
        local_views = deepcopy(views)
        for region in reply['regions']:
            view = local_views[region['view']]
            view['regions'][region['id']] = region_bounds(region['box_normalized'], view['bounds'])
        measurements = deepcopy(base)
        for tool in reply['measurements']:
            measurements[tool['id']] = investigate({k:tool[k] for k in ('tool','view','region')}, local_views, cache)
        write(round_dir/'program.json', program)
        write(round_dir/'measurements.json', measurements)
        execution = run_worker(program, measurements, round_dir/'task', audit=audit)
        write(round_dir/'execution.json', execution)
        feedback = {k:{field:r[field] for field in ('status','kind','reason','value') if field in r and field != 'value'}
                    for k,r in measurements.items()}
        feedback['component_failures'] = {c['id']:c['reason'] for c in
            (execution.get('result') or {}).get('components', []) if not c.get('built')}
        feedback['host_hull_source'] = {'view':'body','region':'hull','method':'body_plan_regions'}
        # Only a greater number of resolved components counts. Changing failed
        # regions or alternating measured level pairs cannot extend the run.
        resolved = sum(c.get('built', False) for c in (execution.get('result') or {}).get('components', []))
        stale = 0 if resolved > best_resolved else stale+1
        best_resolved = max(best_resolved, resolved)
        write(out/'latest.json', {'round':round_number, 'task':str(round_dir/'task'),
                                 'program':str(round_dir/'program.json'),'stale_rounds':stale})
        if execution['exit_code'] != 0:
            write(out/'stop.json', {'reason':'sandbox_worker_failed','execution':execution})
            break
        if stale >= 2:
            write(out/'stop.json', {'reason':'no_measurement_progress','rounds':round_number+1})
            break
        round_number += 1
    from benchmarks.localisation.summarize import receipts, usage
    write(out/'usage.json', usage(receipts(out)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--controller',type=Path,required=True)
    parser.add_argument('--reuse-drawings',type=Path,help='Prior drawing-only preparation, never truth')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
