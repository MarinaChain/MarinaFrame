"""Independent reference extraction from the published DTMB5415 IGES surface.

This is a DATA-PRODUCTION utility, not an inference adapter. Its source CAD and
numeric answers never enter parser input. OpenCascade's IGES reader converts
source metre units to internal millimetres; coordinates below divide by 1000.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

SOURCE_SHA256 = "a3d1e9d82ff5aec16525f39e1708af4bd71960c56e9584d494554633e60dc8ad"
X_MIN, X_MAX = -2.5, 2.9
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "data/external/dtmb5415"


def extract_dtmb_sections(*, stations: int = 41, samples: int = 257, dense_stations: int = 241) -> dict:
    from OCP.IGESControl import IGESControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS
    from .generate import section_volume
    source = SOURCE_ROOT / "goteborg_original.iges"
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Published reference file hash mismatch")
    reader = IGESControl_Reader()
    if reader.ReadFile(str(source)) != IFSelect_RetDone:
        raise ValueError("Cannot import published IGES source")
    reader.TransferRoots()
    shape = reader.OneShape()
    def cut(x_m):
        cut = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(x_m*1000, 0, 0), gp_Dir(1, 0, 0)), False)
        cut.Build()
        if not cut.IsDone():
            raise ValueError(f"IGES section operation failed at x={x_m}")
        explorer = TopExp_Explorer(cut.Shape(), TopAbs_EDGE)
        curves = []
        while explorer.More():
            curve = BRepAdaptor_Curve(TopoDS.Edge_s(explorer.Current()))
            params = np.linspace(curve.FirstParameter(), curve.LastParameter(), 4097)
            points = np.array([[curve.Value(float(t)).Y(), curve.Value(float(t)).Z()] for t in params])/1000
            curves.append(points)
            explorer.Next()
        if len(curves) != 1:
            raise ValueError(f"Only unambiguous single section supported: {len(curves)} curves at {x_m}")
        p = curves[0]
        if np.all(np.diff(p[:,1]) < 0):
            p = p[::-1]
        if np.any(np.diff(p[:,1]) <= 0):
            raise ValueError(f"Source section is not single-valued in elevation at {x_m}")
        z = np.linspace(p[0,1], p[-1,1], samples)
        y = np.interp(z, p[:,1], p[:,0])
        if y.min() < -1e-7:
            raise ValueError("Source half-hull crosses the symmetry plane unexpectedly")
        return {"x_m":float(x_m-X_MIN),"points_yz_m":np.column_stack((np.maximum(y,0),z)).tolist()}
    # Ends are explicitly cropped: exclude degenerate tips and close at these
    # terminal planes. The source shell is not claimed to be a pre-existing solid.
    xs = np.linspace(X_MIN, X_MAX, dense_stations)
    dense = [cut(float(x)) for x in xs]
    selected = []
    for i, x in enumerate(np.linspace(X_MIN,X_MAX,stations)):
        idx = int(round((x-X_MIN)/(X_MAX-X_MIN)*(dense_stations-1)))
        section = dense[idx].copy() if abs(xs[idx]-x)<1e-9 else cut(float(x))
        section["id"] = f"frame-{i:02d}"
        selected.append(section)
    return {"sections":selected,"reference_volume_m3":section_volume(dense),
            "provenance":{"source_name":"Published DTMB5415 half-hull IGES, mathLab WaveBEMapp",
                "source_sha256":SOURCE_SHA256,
                "source_url":"https://github.com/mathLab/WaveBEMapp-DTMB-5415/blob/afad0f04a2ce5ee03f37dcefbe697a5281bc0168/goteborg_original.iges",
                "license":"MIT", "attribution":"Copyright (c) 2017 Marco Tezzele",
                "source_kind":"externally authored CAD surface, rasterized for this benchmark",
                "coordinate_transform":"OCP output mm / 1000; x shifted +2.5m; y,z unchanged",
                "crop":"original x in [-2.5, 2.9] metres; bow/bulb region excluded because some planes contain disconnected contours unsupported by this foundation; full source section elevations; mirrored half-hull; flat end caps",
                "dense_integration_stations":dense_stations,"section_ordinate_samples":samples,
                "source_curve_samples_per_section":4097,
                "source_is_solid":False,"source_face_count":3,
                "inference_never_receives":["IGES source","section ordinates","reference volume"]}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=SOURCE_ROOT/"reference_sections.json")
    args=parser.parse_args()
    data=extract_dtmb_sections()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(data,indent=2)+"\n")
    print(json.dumps({"path":str(args.out),"sections":len(data['sections']),"volume_m3":data['reference_volume_m3'],"sha256":hashlib.sha256(args.out.read_bytes()).hexdigest()},indent=2))

if __name__=="__main__": main()
