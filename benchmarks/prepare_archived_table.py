"""Prepare an explicitly calibrated real-table input, preserving source provenance.

No half-breadth values are encoded here. Numeric y values can only come from
OCR of the archived sheet7 scan. Station spacing is transcribed calibration
from the dimension chain on original sheet3, with source crops retained.
"""
from __future__ import annotations
import json
from pathlib import Path
import warnings

from PIL import Image
from .archived_table_experiment import cell_layout, COL_EDGES
from vessel_reconstruction.provenance import digest_file,write_json

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/public_scan'


def main():
    original=ROOT/'data/external/balclutha/body_plan_sheet_7.tif'
    reference=ROOT/'data/external/balclutha/lines_sheet_3.png'
    if digest_file(original)!='32f09c60a39d5a7f91148eb26148ebb58feea3d0a510e5a9a9da7767c60326a8':
        raise ValueError('Original table source hash changed.')
    if digest_file(reference)!='02a14d8d6ec4f6a57d123f02a0ccf2ed5b87ed98dedc5d014b795b20af666163':
        raise ValueError('Station reference source hash changed.')
    DATA.mkdir(parents=True,exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',Image.DecompressionBombWarning)
        with Image.open(original) as image:
            if image.size!=(9632,14442):
                raise ValueError('Unexpected table source dimensions.')
            image=image.convert('L').resize((4816,7221),Image.Resampling.LANCZOS)
            image.save(DATA/'balclutha_bodyplan_halfscale.png')
    source=json.loads(original.with_name('source_manifest.json').read_text())
    refmanifest=json.loads(reference.with_name('lines_sheet_3_manifest.json').read_text())
    # These are explicit station-location dimensions from sheet3, not hull
    # ordinates. Last interval is6ft0.5in, one inch shorter than other quarters.
    interval_feet=[6+1.5/12]*4+[12+3/12]*4+[24+6/12]*4+[12+3/12]*4+[6+1.5/12]*3+[6+.5/12]
    positions=[0.0]
    for interval in interval_feet:
        positions.append(positions[-1]+interval*.3048)
    layout=cell_layout()
    sections=[]
    for station in range(1,20):
        cells=[{'z_m':cell['z_m'],'roi_px':cell['roi_px']} for cell in layout if cell['station_label']==station]
        sections.append({'id':f'station-{station:02d}','x_m':positions[station],
            'roi_px':[COL_EDGES[station],5886,COL_EDGES[station+1],6414],
            'evidence':f'Sheet7 table column labelled station{station}; half-breadth waterlines4,8,12,16,20,24ft. Cell regions/row identities were visually calibrated. Longitudinal x is the cumulative explicit dimension chain on sheet3, referenced from station0. No half-breadth values were transcribed into this input.',
            'cells':cells})
    spec={'schema_version':'1.0','vessel_id':'balclutha-archived-inner-hull-table',
          'input_mode':'offset_table_ocr','units':'m','table_value_units':'feet_inches_eighths',
          'table_surface':'inner_hull_surface',
          'source':{'file':'balclutha_bodyplan_halfscale.png','sha256':digest_file(DATA/'balclutha_bodyplan_halfscale.png'),
                    'url':source['landing_page'],'license':source['license'],
                    'original_scan_sha256':digest_file(original),
                    'transformation':'Uniform half-size LANCZOS resampling of original sheet7; no edited/traced numeric values.'},
          'station_reference':{'file':'../external/balclutha/lines_sheet_3.png','sha256':digest_file(reference),
                    'url':refmanifest.get('landing_page',refmanifest.get('source_url','https://www.loc.gov/resource/hhh.ca1493.sheet/?sp=3')),
                    'license':refmanifest.get('license',source['license']),
                    'roi_px':[2400,5880,12050,6150],
                    'description':'Actual sheet3 dimension chain: stations0–4 in6ft1.5in increments;4–8 in12ft3in;8–12 in24ft6in;12–16 in12ft3in;16–19 in6ft1.5in;19–20 in6ft0.5in. Note6 explains initial24ft6in spacing and added half/quarter stations. These dimensions are human-provided calibration, not automatically detected.'},
          'symmetry':'port_starboard','symmetry_evidence':'Sheet3 note1 states only starboard was measured and HAER assumed bilateral symmetry. Retained as a source assumption requiring review, not independently verified.',
          'end_closure':'flat_at_terminal_stations','sections':sections,'components':[],
          'scope_note':'Candidate cropped inner-hull envelope only: stations1–19, waterlines4–24ft. No full hull, steel thickness, displacement, current vessel condition, or engineering approval. Any ambiguous required cell blocks the run.',
          'historical_date':'Measurements1988; drawing1990. Source note11 discusses limited drawing/measurement accuracy; this implementation does not validate those tolerances.'}
    write_json(DATA/'table_spec.json',spec)
    calibration={'source_file':'../external/balclutha/lines_sheet_3.png','source_sha256':digest_file(reference),
        'method':'Human reading of explicit dimension chain; numeric feet-to-metres conversion',
        'station_positions_m':{str(i):x for i,x in enumerate(positions)},
        'interval_feet':interval_feet,'total_ft':sum(interval_feet),'total_m':positions[-1],
        'review_required':True,'source_crops':['station_reference_left.png','station_reference_middle.png','station_reference_right.png'],
        'shape_values_supplied':False}
    write_json(DATA/'station_calibration.json',calibration)
    print(json.dumps({'spec':str(DATA/'table_spec.json'),'stations':len(sections),'cells':len(layout),'source_total_station_span_m':positions[-1]},indent=2))

if __name__=='__main__':main()
