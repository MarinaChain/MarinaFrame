"""Frozen stress test on the original HAER Balclutha frame-108 scan.

Run: PYTHONPATH=src python -m benchmarks.independent_real_scan --out artifacts/real-scan-v1
The only preprocessing is a documented border crop and uniform resampling.
There is no tracing, masking, redrawing, or CAD projection in the source image.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request
import warnings

from PIL import Image, ImageDraw

from vessel_reconstruction.ingest import extract_sections
from vessel_reconstruction.provenance import digest_file, implementation_hash, write_json, environment_record

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'public_scan'
ORIGINAL_NAME='balclutha_frame108_original.tif'
INPUT_NAME='balclutha_frame108_input.png'
ORIGINAL_SHA256='4e6344f077c9337cf3a1a1e735879e719449852ca6cf1200cd80d51692243fa6'
ORIGINAL_URL='https://upload.wikimedia.org/wikipedia/commons/8/83/Section_at_Frame_108_-_Ship_BALCLUTHA%2C_2905_Hyde_Street_Pier%2C_San_Francisco%2C_San_Francisco_County%2C_CA_HAER_CAL%2C38-SANFRA%2C200-_%28sheet_48_of_69%29.tif'
COMMONS_URL='https://commons.wikimedia.org/wiki/File:Section_at_Frame_108_-_Ship_BALCLUTHA,_2905_Hyde_Street_Pier,_San_Francisco,_San_Francisco_County,_CA_HAER_CAL,38-SANFRA,200-_(sheet_48_of_69).tif'
LOC_URL='https://www.loc.gov/resource/hhh.ca1493.sheet/?sp=48'


def prepare_source() -> dict:
    DATA.mkdir(parents=True,exist_ok=True)
    original=DATA/ORIGINAL_NAME
    if not original.exists():
        request=urllib.request.Request(ORIGINAL_URL,headers={'User-Agent':'VesselReconstructionResearch/0.1 (public-domain source reproducibility study)'})
        with urllib.request.urlopen(request,timeout=60) as response:
            original.write_bytes(response.read())
    if digest_file(original)!=ORIGINAL_SHA256:
        raise ValueError('Original scan hash mismatch; do not substitute or silently update the source.')
    # The scanned sheet is 139 MP. Keep the original untouched, and use an
    # exactly isotropic quarter-size derivative to bound inference memory.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',Image.DecompressionBombWarning)
        with Image.open(original) as image:
            if image.size!=(9632,14434):
                raise ValueError('Unexpected original dimensions.')
            image=image.crop((0,0,9632,14432)).convert('L')
            image=image.resize((2408,3608),Image.Resampling.LANCZOS)
            image.save(DATA/INPUT_NAME)
    manifest={
        'title':'Section at Frame 108 — Ship BALCLUTHA, HAER CA-54, sheet 48 of 69',
        'creator':'Mark T. Bittle / Historic American Engineering Record, National Park Service',
        'drawing_date':'1988', 'retrieved_utc':datetime.now(timezone.utc).isoformat(),
        'source_kind':'Original independently authored archival measured drawing scan',
        'catalog_url':LOC_URL,'commons_description_url':COMMONS_URL,'download_url':ORIGINAL_URL,
        'rights':'Public domain in the United States: work of a National Park Service employee in official duties (PD-US-NPS).',
        'rights_basis':'Commons original-file description expressly applies PD-US-NPS, with LoC source identification; not inferred merely from HABS/HAER membership.',
        'original':{'file':ORIGINAL_NAME,'sha256':ORIGINAL_SHA256,'bytes':original.stat().st_size,'width_px':9632,'height_px':14434},
        'inference_derivative':{'file':INPUT_NAME,'sha256':digest_file(DATA/INPUT_NAME),'width_px':2408,'height_px':3608,
            'transforms':[{'operation':'crop','box_original_px':[0,0,9632,14432],'reason':'Remove two bottom border pixels so both dimensions divide by four.'},
                          {'operation':'uniform_resize','scale':0.25,'filter':'Pillow LANCZOS'}],
            'prohibited_operations_performed':[]},
        'evaluation_note':'Original source, not a drawing generated from external CAD. No checked numerical reference geometry is available; no reconstruction accuracy metric is claimed.'
    }
    write_json(DATA/'source_manifest.json',manifest)
    return manifest


def calibration_spec(manifest: dict) -> dict:
    # These are panel/datum/ruler observations, NOT traced hull ordinates.
    # The printed metric scale spans x=389..2020 over 10 m in the derivative.
    return {
        'schema_version':'1.0','vessel_id':'balclutha-real-frame108','units':'m',
        'source':{'file':INPUT_NAME,'sha256':manifest['inference_derivative']['sha256'],
                  'url':LOC_URL,'license':manifest['rights']},
        'symmetry':'port_starboard','symmetry_evidence':'Symmetry is an explicit, unapproved assumption; only the right half of one scanned frame is examined.',
        'end_closure':'flat_at_terminal_stations',
        'sections':[{
            'id':'frame-108','x_m':0.0,'roi_px':[1180,840,2070,2585],
            'calibration':{'centerline_px':1205,'baseline_px':2565,'pixels_per_metre':163.1},
            'z_min_m':0.0,'z_max_m':10.45,
            'evidence':'Manually selected starboard half-panel. Printed 0–10 metre scale endpoints x=389 and x=2020 give 163.1 px/m. Local centreline is x=1205; baseline y=2565 is near the shell/keel intersection. These datum picks require review. x_m=0 is only a local label for this isolated station, not a claimed longitudinal location in the vessel.'
        }],
        'components':[],
        'test_scope':'Single-section extraction stress test only; no 3D hull construction or invented station spacing.',
        'manual_assistance':{'roi_px':[1180,840,2070,2585], 'centreline_px':1205,'baseline_px':2565,
            'scale_bar':{'endpoints_px':[[389,3300],[2020,3300]],'label':'0 to 10 metres','pixels_per_metre':163.1},
            'vertical_crop':'Local z=0..10.45 m, stopping below top rail/upper equipment.',
            'geometry_points_supplied':False},
    }


def annotated_preview(spec:dict,output:Path) -> None:
    with Image.open(DATA/INPUT_NAME) as im:
        im=im.convert('RGB')
        draw=ImageDraw.Draw(im)
        section=spec['sections'][0]
        draw.rectangle(section['roi_px'],outline=(220,40,40),width=5)
        draw.line((1205,840,1205,2585),fill=(30,120,220),width=3)
        draw.line((1180,2565,2070,2565),fill=(30,120,220),width=3)
        draw.line((389,3300,2020,3300),fill=(20,150,50),width=5)
        im.thumbnail((1200,1800),Image.Resampling.LANCZOS)
        im.save(output)


def run(output:Path) -> dict:
    output=Path(output)
    if (output/'stress_report.json').exists():
        raise FileExistsError('Use a new output directory; previous attempts must remain reviewable.')
    manifest=prepare_source()
    spec=calibration_spec(manifest)
    write_json(DATA/'frame108_spec.json',spec)
    output.mkdir(parents=True,exist_ok=True)
    # Only this image and explicitly disclosed calibration enter inference.
    shutil.copyfile(DATA/INPUT_NAME,output/INPUT_NAME)
    write_json(output/'input_spec.json',spec)
    implementation=implementation_hash()
    started=time.perf_counter()
    observations=extract_sections(spec,output)
    elapsed=time.perf_counter()-started
    write_json(output/'extracted_sections.json',observations)
    blocked=bool(observations['gaps']) or not observations['sections']
    report={
        'case_id':'original-balclutha-frame108-v1','status':'blocked' if blocked else 'unverified_section_observation',
        'source_manifest':manifest,'implementation_sha256':implementation,
        'ingest_sha256':digest_file(ROOT/'src/vessel_reconstruction/ingest.py'),
        'environment':environment_record(),'inference_seconds':elapsed,
        'inputs':['untouched archival pixels after disclosed uniform resampling','human ROI/datum/printed-ruler calibration'],
        'geometry_labels_available_to_inference':False,
        'outcome':{'extracted_section_count':len(observations['sections']),'gaps':observations['gaps']},
        'accuracy_evaluation':'Not available: no independently checked numeric reference for this frame. Source visibility and CAD validity would not establish accuracy.',
        'cad_exported':False,
        'scope_limit':'One isolated section; no verified longitudinal position/spacing. Do not duplicate it into invented stations or claim full-ship reconstruction.',
        'attempt_selection':'First calibrated full half-panel attempt retained. No parser tuning or contour masking was performed on this source.',
        'interpretation':'The detailed archival panel contains internal framing, decks, hatching, leaders, and adjacent shell/frame contours. A one-contour raster parser must distinguish these or abstain.',
        'diagnostics':observations['diagnostics'],
    }
    write_json(output/'stress_report.json',report)
    annotated_preview(spec,output/'calibration_preview.png')
    gaps='\n'.join(f"- **{g['kind']}**: {g['message']}" for g in observations['gaps']) or '- No parser blocking gap; observation still requires manual source review.'
    text=f'''# Real archival drawing stress test: Balclutha frame 108\n\n## Outcome\n\n**{report['status']}**. The parser returned {len(observations['sections'])} section(s) in {elapsed:.3f} seconds. No CAD was exported and no geometric accuracy score is claimed.\n\n{gaps}\n\n## Actual source\n\nThis is Mark T. Bittle's 1988 HAER CA-54 sheet 48, obtained as the original 9,632 × 14,434 TIFF from the verified Commons mirror of the Library of Congress record. It is an independently authored archival section, not a view projected from a CAD model. The exact downloaded bytes are retained.\n\n- [Library of Congress sheet 48]({LOC_URL})\n- [Original-file provenance and public-domain notice]({COMMONS_URL})\n- Original SHA-256: `{ORIGINAL_SHA256}`\n\nThe description applies the US public-domain status of an official National Park Service work. Source metadata and retrieval details are preserved in `source_manifest.json`.\n\n## Permitted assistance and transformations\n\nThe original file was left intact. The inference derivative removes two blank bottom-border pixels and uniformly resamples the remaining sheet by 0.25 with LANCZOS. It contains all original contours, hatching, equipment, dimensions, and annotations. No contour was traced, masked, painted, or recreated.\n\nThe human-assisted ROI is `[1180,840,2070,2585]`; centerline x=1205 and baseline y=2565 define a local coordinate system. The printed 0–10 metre ruler spans x=389 to x=2020, yielding 163.1 pixels/metre. The vertical interval is local z=0–10.45 m. These picks are reviewable in `calibration_preview.png` and the complete specification. The isolated station's x=0 is only a local label, not a physical longitudinal placement.\n\n## What this result establishes\n\nThis test exposes the parser to real archived scan content under the same tracing algorithm used for synthetic drawings. The detailed panel contains several physically meaningful close contours and many internal lines. A blocking result is evidence of an unsupported input, not a successfully reconstructed ship. The raw body plan and the OCR measurement-table route are separate experiments.\n\nEven a successful single-section trace would require independent dimensional checks and verified station spacing before hull construction. No existing scan was silently excluded or relabeled as generated training data.\n'''
    (output/'REPORT.md').write_text(text)
    (DATA/'STRESS_REPORT.md').write_text(text+'\nReproduction: `PYTHONPATH=src python -m benchmarks.independent_real_scan --out artifacts/another-real-scan-run`\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    report=run(args.out)
    print(json.dumps({'status':report['status'],'outcome':report['outcome'],'inference_seconds':report['inference_seconds']},indent=2))

if __name__=='__main__':
    main()
