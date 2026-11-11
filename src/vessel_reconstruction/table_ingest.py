"""Conservative OCR of source-drawing offset tables, with cell-level evidence.

Uses the installed pretrained Tesseract LSTM recognizer.  No model is trained on
this project, no numeric target geometry is supplied, and no digit is repaired
using neighboring cells or a hull prior.  Two OCR passes must agree on a valid
feet-inches-eighths token and both exceed a fixed heuristic confidence threshold.
"""
from __future__ import annotations

import csv
import hashlib
from io import BytesIO, StringIO
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import numpy as np
from PIL import Image, ImageOps

MIN_OCR_CONFIDENCE = 70.0


def _gap(kind: str, message: str, section_id: str | None = None, cell_index: int | None = None) -> dict:
    suffix=f'{section_id or "source"}' + (f'-cell-{cell_index}' if cell_index is not None else '')
    return {'id':f'{suffix}-{kind}','kind':kind,'severity':'blocking',
            'section_id':section_id,'cell_index':cell_index,'message':message}


def _finite(value: Any) -> bool:
    try:
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    except OverflowError:
        return False


def parse_feet_inches_eighths(text: str) -> tuple[float,str]:
    """Parse an explicit F-I-E token; whitespace removal is not digit repair."""
    normalized=re.sub(r'\s+','',text.strip())
    match=re.fullmatch(r'(\d{1,3})-(\d{1,2})-([0-7])',normalized)
    if not match:
        raise ValueError('Expected unambiguous feet-inches-eighths notation, such as 18-7-4.')
    feet,inches,eighths=map(int,match.groups())
    if not 0<=inches<=11:
        raise ValueError('Inches must be in 0..11; no carry or digit correction is inferred.')
    return (feet+inches/12+eighths/96)*0.3048, normalized


def _threshold(image: Image.Image) -> Image.Image:
    values=np.asarray(image)
    hist=np.bincount(values.ravel(),minlength=256).astype(float)
    p=hist/max(1,hist.sum());w=np.cumsum(p);m=np.cumsum(p*np.arange(256))
    variance=(m[-1]*w-m)**2/np.maximum(w*(1-w),1e-12)
    threshold=int(np.argmax(variance))
    return image.point(lambda value: 255 if value>threshold else 0)


def _ocr_pass(image:Image.Image,psm:int,threshold:bool=False) -> dict:
    if threshold:
        image=_threshold(image)
    image=ImageOps.expand(image,border=18,fill=255)
    buffer=BytesIO();image.save(buffer,format='PNG')
    command=['tesseract','stdin','stdout','--oem','1','--psm',str(psm),'-l','eng',
             '-c','tessedit_char_whitelist=0123456789-','tsv']
    env=os.environ.copy();env['OMP_THREAD_LIMIT']='1'
    process=subprocess.run(command,input=buffer.getvalue(),stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,timeout=20,env=env,check=False)
    if process.returncode:
        return {'psm':psm,'thresholded':threshold,'raw_text':'','confidence':0.0,
                'error':process.stderr.decode(errors='replace').strip()[:500]}
    words=[];confidence=[]
    for record in csv.DictReader(StringIO(process.stdout.decode(errors='replace')),delimiter='\t'):
        value=record.get('text','').strip()
        if value:
            words.append(value)
            try:
                confidence.append(float(record['conf']))
            except (TypeError,ValueError):
                confidence.append(0.0)
    return {'psm':psm,'thresholded':threshold,'raw_text':' '.join(words),
            'confidence':min(confidence) if confidence else 0.0,
            'confidence_definition':'Minimum Tesseract token confidence in this crop; not a probability of correct engineering geometry.'}


def _language_model_info() -> dict:
    """Fingerprint the actual pretrained language weights used by Tesseract."""
    listing=subprocess.run(['tesseract','--list-langs'],capture_output=True,text=True,check=False,timeout=5).stdout
    match=re.search(r'"([^"]+)"',listing)
    directory=Path(os.environ['TESSDATA_PREFIX']) if os.environ.get('TESSDATA_PREFIX') else (Path(match.group(1)) if match else None)
    model=directory/'eng.traineddata' if directory else None
    if model is not None and model.is_file():
        return {'language':'eng','file':str(model.resolve()),'sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'bytes':model.stat().st_size}
    return {'language':'eng','file':None,'sha256':None,'status':'Language-model file location not resolved; replay requires the same Tesseract installation.'}


def _read_cell(image:Image.Image,roi:list[int]) -> dict:
    cell=image.crop(tuple(roi)).convert('L')
    # Source pixels are enlarged to aid a generic OCR recognizer, not replaced.
    if cell.height<120:
        factor=max(1,math.ceil(120/cell.height))
        cell=cell.resize((cell.width*factor,cell.height*factor),Image.Resampling.LANCZOS)
    passes=[_ocr_pass(cell,7),_ocr_pass(cell,6,threshold=True)]
    parsed=[]
    for attempt in passes:
        try:
            value,token=parse_feet_inches_eighths(attempt['raw_text'])
            attempt['parsed_m']=value;attempt['normalized_token']=token
            parsed.append((value,token))
        except ValueError as exc:
            attempt['parse_error']=str(exc)
    result={'roi_px':roi,'ocr_runs':passes,'raw_ocr':[p['raw_text'] for p in passes],
            'ocr_confidence':min(p['confidence'] for p in passes),
            'confidence_threshold':MIN_OCR_CONFIDENCE,'parsed_value_m':None,
            'corrections_applied':[],'status':'ambiguous'}
    if len(parsed)!=2:
        result['reason']='At least one OCR pass did not produce valid feet-inches-eighths notation.'
    elif parsed[0][1]!=parsed[1][1]:
        result['reason']='OCR passes disagree; no digit is repaired from neighboring values.'
    elif result['ocr_confidence']<MIN_OCR_CONFIDENCE:
        result['reason']='OCR confidence is below the fixed acceptance threshold.'
    else:
        result.update(status='observed_review_required',parsed_value_m=parsed[0][0],source_token=parsed[0][1])
    return result


def _roi(value:Any,width:int,height:int) -> list[int] | None:
    if not isinstance(value,(list,tuple)) or len(value)!=4 or not all(_finite(v) and int(v)==v for v in value):
        return None
    left,top,right,bottom=map(int,value)
    if not 0<=left<right<=width or not 0<=top<bottom<=height:
        return None
    return [left,top,right,bottom]


def extract_table_sections(spec:dict,base_dir:Path) -> dict:
    """Read measured half-breadths from explicitly identified source table cells.

    Station x_m, waterline z_m, cell regions, and unit notation are human
    calibration. Values of y are obtained exclusively from source image OCR.
    A missing or uncertain required cell blocks that section and the run.
    """
    output={'sections':[],'gaps':[],'cell_evidence':[],'diagnostics':{},'method':'archived_table_ocr'}
    if not isinstance(spec,dict) or spec.get('units')!='m':
        output['gaps'].append(_gap('invalid_table_spec','Output units must be explicitly metres.'))
        return output
    if spec.get('input_mode')!='offset_table_ocr' or spec.get('table_value_units')!='feet_inches_eighths':
        output['gaps'].append(_gap('unresolved_table_units','Declare input_mode=offset_table_ocr and table_value_units=feet_inches_eighths; units are not guessed.'))
        return output
    if shutil.which('tesseract') is None:
        output['gaps'].append(_gap('ocr_unavailable','The pretrained Tesseract OCR executable is not installed.'))
        return output
    source=spec.get('source')
    if not isinstance(source,dict) or not isinstance(source.get('file'),str):
        output['gaps'].append(_gap('missing_source','source.file must identify the scanned table.'))
        return output
    source_path=Path(base_dir)/source['file']
    from .resources import ResourceLimitError, validate_sources
    try:
        validate_sources(spec, base_dir)
    except ResourceLimitError as exc:
        output['gaps'].append(_gap(exc.kind, str(exc)))
        return output
    try:
        image=Image.open(source_path)
        width,height=image.size
    except (OSError,ValueError,Image.DecompressionBombError) as exc:
        output['gaps'].append(_gap('unreadable_source',f'Table image cannot be opened: {type(exc).__name__}.'))
        return output
    version=subprocess.run(['tesseract','--version'],capture_output=True,text=True,check=False,timeout=5).stdout.splitlines()
    output['diagnostics']={'ocr_engine':version[0] if version else 'Tesseract','recognizer':'Pretrained English LSTM (--oem 1); not trained or fine-tuned on this project',
                           'ocr_passes':[{'psm':7,'preprocessing':'grayscale, deterministic enlargement, white padding'},
                                         {'psm':6,'preprocessing':'Otsu binarization, deterministic enlargement, white padding'}],
                           'passes_are_statistically_independent':False,
                           'confidence_threshold':MIN_OCR_CONFIDENCE,'correction_policy':'No digit repairs or hull-shape prior',
                           'image_width_px':width,'image_height_px':height,'language_model':_language_model_info(),'sections':{}}
    sections=spec.get('sections')
    if not isinstance(sections,list) or not sections:
        output['gaps'].append(_gap('missing_table_cells','At least one station with explicit table cell regions is required.'))
        image.close();return output
    forbidden={'points','points_yz_m','offsets','ground_truth','reference_mesh','hull_parameters'}
    if forbidden.intersection(spec):
        output['gaps'].append(_gap('geometry_in_input','Target geometry must not be supplied to table inference.'))
        image.close();return output
    seen=set()
    try:
        for index,section in enumerate(sections):
            if not isinstance(section,dict):
                output['gaps'].append(_gap('invalid_table_section',f'Section {index} must be an object.'))
                continue
            sid=str(section.get('id',f'section-{index}'))
            if sid in seen or not section.get('id'):
                output['gaps'].append(_gap('invalid_table_section','Each station requires a unique nonempty identity.',sid));continue
            seen.add(sid)
            if forbidden.intersection(section):
                output['gaps'].append(_gap('geometry_in_input','Table station contains target geometry.',sid));continue
            if not _finite(section.get('x_m')):
                output['gaps'].append(_gap('missing_station','A source-supported longitudinal station coordinate is required.',sid));continue
            column_roi=_roi(section.get('roi_px'),width,height)
            if column_roi is None:
                output['gaps'].append(_gap('invalid_table_region','Declare a valid table station column region.',sid));continue
            cells=section.get('cells')
            if not isinstance(cells,list) or len(cells)<5:
                output['gaps'].append(_gap('insufficient_table_cells','At least five measured elevations per station are required by this CAD adapter.',sid));continue
            points=[];evidence=[];failed=False;zs=set()
            for ci,cell in enumerate(cells):
                if not isinstance(cell,dict) or not _finite(cell.get('z_m')) or float(cell.get('z_m',0)) in zs:
                    output['gaps'].append(_gap('invalid_table_cell','Each cell requires a finite, unique source-supported waterline z_m.',sid,ci));failed=True;continue
                zs.add(float(cell['z_m']))
                roi=_roi(cell.get('roi_px'),width,height)
                if roi is None:
                    output['gaps'].append(_gap('invalid_table_cell','A cell region is outside the source image.',sid,ci));failed=True;continue
                if not (column_roi[0]<=roi[0]<roi[2]<=column_roi[2] and column_roi[1]<=roi[1]<roi[3]<=column_roi[3]):
                    output['gaps'].append(_gap('invalid_table_cell','Cell region falls outside its declared station column.',sid,ci));failed=True;continue
                if forbidden.intersection(cell) or any(k in cell for k in ('value','value_m','y_m','parsed_value_m','text','expected_text')):
                    output['gaps'].append(_gap('geometry_in_input','Numeric table answers or transcriptions may not be supplied as input.',sid,ci));failed=True;continue
                try:
                    observed=_read_cell(image,roi)
                except subprocess.TimeoutExpired:
                    observed={'roi_px':roi,'raw_ocr':[],'ocr_runs':[],'parsed_value_m':None,'status':'ambiguous','reason':'OCR timed out.','corrections_applied':[]}
                observed.update(section_id=sid,cell_index=ci,z_m=float(cell['z_m']),source_file=source['file'])
                evidence.append(observed);output['cell_evidence'].append(observed)
                if observed['status']!='observed_review_required':
                    output['gaps'].append(_gap('ambiguous_table_cell',observed.get('reason','Unresolved OCR'),sid,ci));failed=True
                else:
                    points.append([float(observed['parsed_value_m']),float(cell['z_m'])])
            coverage=len(points)/len(cells)
            output['diagnostics']['sections'][sid]={'observed_cells':len(points),'required_cells':len(cells),'coverage':coverage,'status':'blocked' if failed else 'review_required'}
            if failed:
                continue
            points.sort(key=lambda point:point[1])
            confidence=min(item['ocr_confidence'] for item in evidence)/100
            output['sections'].append({'id':sid,'x_m':float(section['x_m']),'points_yz_m':points,
                'confidence':confidence,'coverage':coverage,
                'evidence':{'roi_px':list(section['roi_px']),'source_file':source['file'],'input_form':'archival_offset_table_ocr',
                    'human_assistance':section.get('evidence','Human-provided cell positions, station coordinate, waterline heights, and table units'),
                    'table_value_units':'feet_inches_eighths','cell_evidence':evidence,
                    'source_surface':spec.get('table_surface','Unresolved; reviewer must identify the measured surface'),
                    'interpolation':'Only listed waterline points were observed; geometry between them is interpolation.'},
                'warnings':['OCR scores are recognizer heuristics, not probabilities of correct hull dimensions.',
                            'Two OCR passes use the same pretrained model and can share errors; human source verification remains required.',
                            'Station locations, waterline labels, cell boundaries, and unit notation are explicitly human-assisted.',
                            'Only the listed waterline points were observed; no missing lower hull, upper hull, bow, or stern is inferred.']})
    finally:
        image.close()
    return output
