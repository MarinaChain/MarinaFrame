"""Tessellate one explicitly supplied public KCS IGES; no other data discovery."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh

from prepare_performance_dev import read_iges_mesh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kcs-iges', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(exist_ok=False)
    # SIMMAN KCS is a starboard half, full-scale metres; SVA Lpp=7.2786m.
    scale = 230 / 7.2786
    triangles = read_iges_mesh(args.kcs_iges, deflection_mm=10) / scale
    reflected = triangles[:, ::-1].copy()
    reflected[:, :, 1] *= -1
    mesh = trimesh.Trimesh(vertices=np.concatenate([triangles, reflected]).reshape(-1, 3),
                           faces=np.arange(len(triangles)*6).reshape(-1, 3), process=True)
    mesh.merge_vertices(digits_vertex=7)
    mesh.fix_normals(multibody=True)
    mesh.export(args.out / 'kcs-full.stl')
    metadata = dict(source='SIMMAN2008 KCS_hull_SVA.igs',
                    source_sha256=hashlib.sha256(args.kcs_iges.read_bytes()).hexdigest(),
                    scale_divisor=scale, lpp_m=7.2786, draft_m=0.3418,
                    bounds_m=mesh.bounds.tolist(), triangles=len(mesh.faces),
                    watertight=bool(mesh.is_watertight), winding_consistent=bool(mesh.is_winding_consistent),
                    note='Port reflection only. Above-water deck/end closures not repaired; do not run unless watertight.')
    (args.out / 'geometry.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(metadata))


if __name__ == '__main__':
    main()
