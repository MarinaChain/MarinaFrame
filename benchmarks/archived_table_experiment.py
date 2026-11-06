"""Cell-level archived table OCR experiment; no station x is invented.

Preserves every attempted cell before any optional spatial station reference
is attached. This module does not construct CAD from a guessed column spacing.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time

from PIL import Image, ImageDraw, ImageFont
from vessel_reconstruction.table_ingest import _read_cell, MIN_OCR_CONFIDENCE
from vessel_reconstruction.provenance import digest_file, write_json, environment_record

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/public_scan'
# Human cell-layout calibration from the original table, not the numeric text.
COL_EDGES=[859,1021,1183,1346,1510,1674,1837,1999,2159,2324,2488,2651,2812,2976,3139,3302,3465,3630,3797,3962,4127,4292]
ROW_BOUNDS={4:(6328,6414),8:(6240,6324),12:(6154,6236),16:(6064,6150),20:(5978,6060),24:(5886,5974)}


def cell_layout() -> list[dict]:
    return [{'section_id':f'station-{station:02d}','station_label':station,'waterline_ft':height,
             'z_m':height*.3048,'roi_px':[COL_EDGES[station]+4,ROW_BOUNDS[height][0]+4,COL_EDGES[station+1]-4,ROW_BOUNDS[height][1]-4]}
            for station in range(1,20) for height in (4,8,12,16,20,24)]


def make_contact_sheets(source:Path,results:list[dict],out:Path) -> list[str]:
    """Display every attempted source cell, including failures, for review."""
    font=ImageFont.truetype('DejaVuSans.ttf',16)
    small=ImageFont.truetype('DejaVuSans.ttf',13)
    files=[]
    with Image.open(source) as image:
        for page,stations in enumerate((range(1,7),range(7,13),range(13,19),range(19,20)),1):
            stations=list(stations)
            board=Image.new('RGB',(330*len(stations),6*225),(250,250,250))
            draw=ImageDraw.Draw(board)
            for column,station in enumerate(stations):
                for row,height in enumerate((4,8,12,16,20,24)):
                    cell=next(c for c in results if c['station_label']==station and c['waterline_ft']==height)
                    x,y=column*330,row*225
                    crop=image.crop(cell['roi_px']).convert('RGB')
                    factor=min(310/crop.width,160/crop.height)
                    crop=crop.resize((round(crop.width*factor),round(crop.height*factor)),Image.Resampling.LANCZOS)
                    board.paste(crop,(x+10,y+28))
                    color=(20,130,65) if cell['status']=='observed_review_required' else (190,55,40)
                    draw.rectangle((x+1,y+1,x+328,y+223),outline=color,width=2)
                    draw.text((x+8,y+6),f"Station {station} | WL {height} ft",fill=(15,15,15),font=font)
                    draw.text((x+8,y+181),f"OCR: {' / '.join(cell['raw_ocr'])}",fill=color,font=small)
                    scores=' / '.join(str(round(t['confidence'],1)) for t in cell['ocr_runs'])
                    draw.text((x+8,y+203),f"Confidence: {scores}",fill=color,font=small)
            name=f'cells_contact_{page}.png';board.save(out/name);files.append(name)
    return files


def run(out:Path, experiment_id:str='balclutha-sheet7-table-ocr-v1') -> dict:
    if (out/'cell_results.json').exists():
        raise FileExistsError('Use a new directory; retain all previous attempts.')
    out.mkdir(parents=True,exist_ok=True)
    source=DATA/'balclutha_bodyplan_halfscale.png'
    original=ROOT/'data/external/balclutha/body_plan_sheet_7.tif'
    layout=cell_layout()
    contract={
        'experiment_id':experiment_id,'source_image_sha256':digest_file(source),
        'original_scan_sha256':digest_file(original),'original_provenance_file':'data/external/balclutha/source_manifest.json',
        'image_derivation':'Original sheet7 TIFF uniformly resampled by0.5 with LANCZOS; no traced or edited numeric values.',
        'table_caption':'Dimensions are to the inner hull surface; source notation is feet, inches, and eighths of an inch.',
        'candidate_stations':list(range(1,20)),'candidate_waterlines_ft':[4,8,12,16,20,24],
        'input_geometry':'Cell rectangles and row identities only; no transcribed answers, hull ordinates, or reference geometry.',
        'station_longitudinal_positions':'Not inferred in this experiment; separate source evidence required before CAD.',
        'all_attempts_retained':True,'ocr_confidence_threshold':MIN_OCR_CONFIDENCE,
        'adapter_sha256':digest_file(ROOT/'src/vessel_reconstruction/table_ingest.py'),
        'environment':environment_record(),'ocr_model_directory':os.environ.get('TESSDATA_PREFIX','/usr/share/tesseract-ocr/5/tessdata'),
        'ocr_weights_sha256':digest_file(Path(os.environ.get('TESSDATA_PREFIX','/usr/share/tesseract-ocr/5/tessdata'))/'eng.traineddata'),'cells':layout,
    }
    write_json(out/'experiment_contract.json',contract)
    with Image.open(source) as im:
        image=im.convert('L');image.load()
    def inspect(cell):
        observed=_read_cell(image,cell['roi_px'])
        return {**cell,**observed}
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(inspect,layout))
    elapsed=time.perf_counter()-started
    image.close()
    observed=[cell for cell in results if cell['status']=='observed_review_required']
    complete=[]
    for station in range(1,20):
        group=[cell for cell in results if cell['station_label']==station]
        if all(cell['status']=='observed_review_required' for cell in group):
            complete.append(station)
    report={'experiment_id':contract['experiment_id'],'elapsed_seconds':elapsed,
            'attempted_cells':len(results),'observed_cells':len(observed),'ambiguous_cells':len(results)-len(observed),
            'complete_station_labels':complete,'cad_constructed':False,'station_positions_verified':False,
            'numeric_accuracy':'Not independently established. Dual OCR agreement does not exclude shared recognition errors; source review required.',
            'all_cell_results':results}
    write_json(out/'cell_results.json',report)
    make_contact_sheets(source,results,out)
    summary='\n'.join(f"| {station} | {sum(cell['status']=='observed_review_required' for cell in results if cell['station_label']==station)}/6 |" for station in range(1,20))
    text=f'''# Original Balclutha table OCR: {experiment_id}\n\n**{len(observed)} of {len(results)} source cells passed the frozen OCR agreement/confidence checks; {len(results)-len(observed)} were blocked as ambiguous.** This is an OCR observation count, not a measured accuracy rate. Every cell and both raw OCR passes are retained in `cell_results.json`.\n\nThe source is the independently authored HAER CA-54 sheet7 archive scan. It was uniformly resampled by0.5 and was not redrawn, traced, or altered. The printed table states inner-hull-surface dimensions in feet, inches, and eighths of an inch. Cell regions and row identities were human calibrated; no numeric y values were input.\n\nThe fixed experiment attempts stations1–19 and waterlines4–24ft in4ft steps. Tesseract's pretrained English LSTM is used twice with disclosed preprocessing, exact notation agreement, and minimum confidence70. No digit corrections or hull-prior substitutions are applied. The two passes share a model and are not statistically independent.\n\n| Station label | Cells passing the fixed checks |\n|---:|---:|\n{summary}\n\nNo CAD is constructed here: longitudinal station positions require independent evidence from the dimensioned lines drawing. A later attempt must preserve these ambiguous cells, state its selected scope, and must not turn omitted cells into inferred geometry. No quantitative reconstruction accuracy is claimed.\n'''
    (out/'REPORT.md').write_text(text)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--id',default='balclutha-sheet7-table-ocr-v1');a=p.parse_args()
    r=run(a.out,a.id)
    print(json.dumps({k:v for k,v in r.items() if k!='all_cell_results'},indent=2))
if __name__=='__main__':main()
