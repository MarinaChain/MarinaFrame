"""Reconstruct only the explicitly named public KCS IGES; outputs stay in work/."""
import argparse
import hashlib
import json
from pathlib import Path

import cadquery as cq
import numpy as np
from OCP.IGESControl import IGESControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static

from vessel_reconstruction.cfd.reconstruction import station_positions, slice_half_breadths, loft_sections, submerged_particulars


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kcs-iges', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(exist_ok=False)
    Interface_Static.SetCVal_s('xstep.cascade.unit', 'MM')
    reader = IGESControl_Reader()
    if reader.ReadFile(str(args.kcs_iges)) != IFSelect_RetDone:
        raise ValueError('Cannot read KCS IGES')
    reader.TransferRoots()
    divisor = 1000 * (230 / 7.2786)
    source = cq.Shape.cast(reader.OneShape()).scale(1 / divisor)
    deck = 17.19999 / (230 / 7.2786)
    # At this deck the aft transom is x=-6m and the stem is x=233.952291m.
    # Both are source boundary coordinates, not dimensions fitted to G6.
    # Inset 0.01 mm full-scale avoids plane/coincident end-face ambiguity.
    positions = station_positions((-6 + 0.00001) / (230 / 7.2786),
                                  (233.952291 - 0.00001) / (230 / 7.2786))
    records = []
    profiles = []
    for index, x in enumerate(positions):
        try:
            profile, evidence = slice_half_breadths(source, float(x), deck)
        except ValueError as error:
            (args.out / 'failed-station.json').write_text(json.dumps(dict(index=index, x_m=float(x), error=str(error)), indent=2))
            raise
        profiles.append(profile)
        records.append(dict(x_m=float(x), points_yz_m=profile.tolist(), **evidence))
        print(f'section {index + 1}/{len(positions)} x={x:.9f}', flush=True)
    metadata = dict(source_sha256=hashlib.sha256(args.kcs_iges.read_bytes()).hexdigest(),
                    scale_divisor=230 / 7.2786, deck_m=deck, draft_m=0.3418,
                    station_count=len(positions), spacing_min_m=float(np.diff(positions).min()),
                    spacing_max_m=float(np.diff(positions).max()), sections=records)
    (args.out / 'sections.json').write_text(json.dumps(metadata, indent=2))
    solid = loft_sections(positions, profiles)
    cq.exporters.export(solid, str(args.out / 'hull.step'))
    metadata.pop('sections')
    metadata.update(submerged_particulars(solid, 0.3418))
    (args.out / 'geometry.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata), flush=True)


if __name__ == '__main__':
    main()
