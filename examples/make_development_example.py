"""Development fixture, explicitly excluded from held-out benchmark scores."""
from pathlib import Path
import json, math
import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction.fonts import dejavu_sans

root = Path(__file__).resolve().parents[1]
out = root / 'data/examples/development'
out.mkdir(parents=True, exist_ok=True)
panel_w, panel_h, cols, rows = 360, 330, 7, 3
ppm, depth = 56.0, 4.5
im = Image.new('RGB', (cols*panel_w, rows*panel_h), 'white')
draw = ImageDraw.Draw(im)
font = dejavu_sans(14)
spec = {'schema_version':'1.0','vessel_id':'Development hull — calibrated section sheet','source':{'file':'drawing.png','license':'Generated development fixture; not held-out evaluation'},'units':'m','symmetry':'port_starboard','symmetry_evidence':'Explicit symmetric example design; mirroring requires review','end_closure':'flat_at_terminal_stations','sections':[],'components':[]}
for i,x in enumerate(np.linspace(0,60,21)):
 col,row=i%cols,i//cols
 left,top=col*panel_w,row*panel_h
 cx,by=left+40,top+300
 half_width=(0.3+4.2*math.sin(math.pi*(i+1)/22))
 z=np.linspace(0,depth,1001)
 y=half_width*np.sqrt(z/depth)*(1-.13*(z/depth)**4)
 draw.text((left+20,top+9),f'SECTION {i:02d}  |  X = {x:.1f} m',fill=(35,45,60),font=font)
 for zz in range(5):
  yy=by-zz*ppm
  draw.line((cx,yy,left+335,yy),fill=(220,224,230),width=1)
 draw.line((cx,top+40,cx,by+4),fill=(190,196,204),width=1)
 draw.line([(cx+float(a)*ppm,by-float(b)*ppm) for a,b in zip(y,z)],fill=(20,40,65),width=3)
 spec['sections'].append({'id':f'section-{i:02d}','x_m':float(x),'roi_px':[left+20,top+35,left+340,top+310],'calibration':{'centerline_px':cx,'baseline_px':by,'pixels_per_metre':ppm},'z_min_m':0.0,'z_max_m':depth,'evidence':'Explicit view box, labelled station and known drawing scale; geometry must come from image pixels'})
im.save(out/'drawing.png')
(out/'spec.json').write_text(json.dumps(spec,indent=2))
print(out/'spec.json')
