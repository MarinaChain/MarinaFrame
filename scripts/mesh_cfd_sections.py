"""Build a public CFD mesh from an explicitly supplied saved station file."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from vessel_reconstruction.cfd.section_mesh import build_section_mesh, mesh_particulars
from vessel_reconstruction.cfd.surface import write_stl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sections', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mesh-only', action='store_true', help='Defer G6 measurements until distance and surfaceCheck')
    args = parser.parse_args()
    args.out.mkdir(exist_ok=False)
    source = json.loads(args.sections.read_text())
    triangles, metadata = build_section_mesh(source['sections'])
    print(f'closed mesh: {len(triangles)} triangles', flush=True)
    labels = metadata.pop('triangle_labels')
    np.savez_compressed(args.out / 'mesh.npz', triangles=triangles, labels=labels)
    write_stl(args.out / 'hull.stl', triangles)
    print('STL written', flush=True)
    if args.mesh_only:
        (args.out / 'topology.json').write_text(json.dumps(metadata, indent=2)+'\n')
        return
    metadata.update(mesh_particulars(triangles, source['draft_m']))
    metadata.update(triangles=len(triangles), source_sha256=source['source_sha256'],
                    sections_sha256=hashlib.sha256(args.sections.read_bytes()).hexdigest(),
                    draft_m=source['draft_m'], deck_m=source['deck_m'],
                    area_error_percent=100*(metadata['wetted_area_m2']/9.4379-1),
                    volume_error_percent=100*(metadata['volume_m3']/1.6490-1),
                    engineering_approved=False)
    metadata['g6_particulars_pass'] = (abs(metadata['area_error_percent']) <= .5 and
                                        abs(metadata['volume_error_percent']) <= .5)
    (args.out / 'geometry.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(metadata), flush=True)


if __name__ == '__main__':
    main()
