"""Generate a declared synthetic source-only harness example (no answer keys)."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw


def make_example(out, *, ambiguous=False):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    image=Image.new('RGB',(600,230),'white');draw=ImageDraw.Draw(image);sections=[]
    for i in range(3):
        left,centre,bottom=i*200,i*200+20,210
        for x in range(centre,centre+151,30):draw.line((x,30,x,bottom),fill=(210,)*3,width=1)
        for y in range(30,bottom+1,30):draw.line((centre,y,centre+170,y),fill=(210,)*3,width=1)
        draw.line([(centre+30+.25*(bottom-y),y) for y in range(30,bottom+1)],fill=(15,)*3,width=3)
        if ambiguous:draw.line((centre+137,30,centre+137,bottom),fill=(207,)*3,width=3)
        sections.append({'id':f's{i}','x_m':i*2.,'roi_px':[left+10,20,left+195,220],
            'calibration':{'centerline_px':centre,'baseline_px':bottom,'pixels_per_metre':60},
            'z_min_m':0.,'z_max_m':3.,'evidence':'Declared calibration for a generated development drawing.'})
    image.save(out/'drawing.png')
    spec={'schema_version':'1.0','vessel_id':'synthetic-agent-example','units':'m',
        'symmetry':'port_starboard','symmetry_evidence':'Explicit generated fixture assumption.',
        'end_closure':'flat_at_terminal_stations','source':{'file':'drawing.png'},'sections':sections}
    (out/'spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    return out/'spec.json'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--ambiguous',action='store_true')
    a=p.parse_args();print(make_example(a.out,ambiguous=a.ambiguous))
