"""Sample direct-mesh distances to one explicitly supplied public IGES."""
import argparse
import json
from pathlib import Path

import cadquery as cq
import numpy as np
from OCP.IGESControl import IGESControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static

from vessel_reconstruction.cfd.reconstruction import sample_distances


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iges', required=True, type=Path)
    parser.add_argument('--mesh', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    Interface_Static.SetCVal_s('xstep.cascade.unit', 'MM')
    reader = IGESControl_Reader()
    if reader.ReadFile(str(args.iges)) != IFSelect_RetDone:
        raise ValueError('Cannot read public IGES')
    reader.TransferRoots()
    source = cq.Shape.cast(reader.OneShape()).scale(1 / (1000 * 230 / 7.2786))
    data = np.load(args.mesh, allow_pickle=False)
    triangles, labels = data['triangles'], data['labels']
    result = dict(method='uniform triangle-index centroid samples, starboard only; exact OCCT point-to-trimmed-shape distance',
                  global_bound=False, engineering_approved=False)
    for label in ('skin', 'keel', 'end', 'deck'):
        candidates = triangles[(labels == label) & (triangles.mean(axis=1)[:,1] >= 0)]
        indices = np.unique(np.linspace(0, len(candidates)-1, min(1000, len(candidates)), dtype=int))
        points = candidates[indices].mean(axis=1)
        distances = sample_distances(source, points)
        result[label] = dict(samples=len(points), max_distance_m=max(distances, default=0),
                             mean_distance_m=float(np.mean(distances)) if distances else None)
        print(label, result[label], flush=True)
        args.out.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
