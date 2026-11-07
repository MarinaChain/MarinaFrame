"""Reproduce loss of a narrow observed chine before CAD approximation.

Run with PYTHONPATH pointing at the exact published or updated source. The
comparator measures centres of untouched raster rows independently; no target
coordinates are passed to ingestion. This is a development fixture, not holdout.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from PIL import Image, ImageDraw
from vessel_reconstruction import ingest


def run(out):
    if out.exists(): raise FileExistsError('Retain previous evidence; choose a fresh directory')
    out.mkdir(parents=True)
    image = Image.new('L', (140, 550), 255)
    ImageDraw.Draw(image).line([(70, 20), (70, 268), (79, 270), (70, 272), (70, 532)], fill=15, width=1)
    image.save(out / 'source.png')
    spec = {'units':'m','source':{'file':'source.png'},'sections':[{'id':'narrow_source_chine',
        'x_m':0.,'roi_px':[20,10,130,540],
        'calibration':{'centerline_px':25.,'baseline_px':532.,'pixels_per_metre':100.},
        'z_min_m':0.,'z_max_m':5.12}]}
    result = ingest.extract_sections(spec, out)
    if result['gaps']: raise ValueError(result['gaps'])
    points = np.asarray(result['sections'][0]['points_yz_m'])
    rows = np.arange(20,533); raster=np.asarray(image)
    observed=np.asarray([np.flatnonzero(raster[row]<100).mean() for row in rows])
    z=(532.-rows)/100.
    recovered=np.interp(z,points[:,1],points[:,0])*100.+25.
    summary={'known_development_only':True,'engineering_approved':False,
        'source_sha256':hashlib.sha256((out/'source.png').read_bytes()).hexdigest(),
        'ingest_source_sha256':hashlib.sha256(Path(ingest.__file__).read_bytes()).hexdigest(),
        'reference':'Independently enumerated centres of original raster dark runs; no reference is passed to extraction.',
        'point_count':len(points),'maximum_lost_source_ordinate_px':float(np.max(np.abs(recovered-observed))),
        'rms_lost_source_ordinate_px':float(np.sqrt(np.mean((recovered-observed)**2))),
        'source_sampling':result['diagnostics']['sections']['narrow_source_chine'].get('source_sampling'),
        'row_comparison':np.column_stack((rows,observed,recovered,recovered-observed)).tolist()}
    for name,value in [('spec.json',spec),('extraction.json',result),('report.json',summary)]:
        (out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    result=run(parser.parse_args().out)
    print(json.dumps({k:v for k,v in result.items() if k!='row_comparison'},indent=2))
