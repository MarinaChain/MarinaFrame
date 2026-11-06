"""Package the complete reproducible project, excluding transient/browser QA files."""
from __future__ import annotations
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXCLUDE_PARTS={'.git','.venv','__pycache__','.pytest_cache','node_modules','workbench-qa','build','dist'}

def files():
    for path in sorted(ROOT.rglob('*')):
        relative=path.relative_to(ROOT)
        if not path.is_file() or path.is_symlink(): continue
        if any(p in EXCLUDE_PARTS or p.endswith('.egg-info') for p in relative.parts): continue
        if path.suffix in {'.pyc','.pyo','.zip'}: continue
        # Screenshots from browser QA remain internal, not a requested deliverable.
        if 'browser' in path.name.lower() and path.suffix in {'.png','.jpg','.jpeg'}: continue
        yield path,relative

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    a.out.parent.mkdir(parents=True,exist_ok=True)
    inventory=[]
    with zipfile.ZipFile(a.out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path,relative in files():
            raw=path.read_bytes()
            inventory.append({'path':str(relative),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
            z.writestr('vessel-reconstruction/'+relative.as_posix(),raw)
        manifest={'files':inventory,'file_count':len(inventory),'purpose':'Complete source, datasets, measured evidence and CAD outputs; excludes temporary caches and browser QA screenshots.'}
        z.writestr('vessel-reconstruction/RELEASE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(a.out) as z:
        bad=z.testzip()
        if bad: raise ValueError('Archive integrity failure: '+bad)
    receipt={'path':str(a.out.resolve()),'bytes':a.out.stat().st_size,'file_count':len(inventory),'sha256':hashlib.sha256(a.out.read_bytes()).hexdigest(),'archive_crc_verified':True}
    a.out.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
