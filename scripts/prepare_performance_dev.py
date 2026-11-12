"""Prepare only already exposed KCS/JBC public development cases.

Requires the existing public model-test download directory. xlrd is a preparation
only dependency (use `uv run --no-project --with xlrd --python <main-python>`).
No blind ship discovery, downloading, scoring or constant tuning occurs here.
Outputs remain under ignored work/. Source geometry must be extracted by name.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import hashlib
import json
import math
import numpy as np

from vessel_reconstruction.performance_geometry import surface_particulars


def read_iges_mesh(path: Path, deflection_mm: float = 2.0) -> np.ndarray:
    from OCP.IGESControl import IGESControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    reader = IGESControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError(f"cannot read IGES {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    BRepMesh_IncrementalMesh(shape, deflection_mm, False, 0.2, False)
    blocks = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, location)
        if tri is not None:
            transform = location.Transformation()
            nodes = np.array([[p.X(),p.Y(),p.Z()] for p in
                              (tri.Node(i).Transformed(transform) for i in range(1,tri.NbNodes()+1))])
            faces = np.array([tri.Triangle(i).Get() for i in range(1,tri.NbTriangles()+1)])-1
            if face.Orientation() == TopAbs_REVERSED:
                faces = faces[:,::-1]
            blocks.append(nodes[faces]/1000)
        explorer.Next()
    if not blocks:
        raise ValueError("IGES has no triangulated faces")
    return np.concatenate(blocks)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",type=Path,required=True)
    parser.add_argument("--kcs-iges",type=Path,required=True)
    parser.add_argument("--jbc-iges",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise ValueError("output must not already exist")
    import xlrd
    cases=[]
    metadata={}
    for ship,path,factor,draft,lpp,aft,half in [
        ("KCS",args.kcs_iges,230/7.2786,10.8,230,0,True),
        ("JBC",args.jbc_iges,1,.4125,7,-3.5,False)]:
        mesh=read_iges_mesh(path)/factor
        geometry=surface_particulars(mesh,waterline_z_m=draft/factor,lpp_m=lpp/factor,
            aft_perpendicular_x_m=aft/factor,forward_x_sign=1,half_hull=half)
        metadata[ship]=dict(geometry=geometry,geometry_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        hull={k:v for k,v in geometry.items() if k in
              {"lwl_m","beam_m","draft_m","volume_m3","cm","cwp",
               "lcb_percent_lwl_forward","wetted_surface_m2","transom_area_m2"}}
        # Bulb section at FP, in the supplied coordinates; centre height is its
        # immersed transverse-area centroid, not a fitted performance parameter.
        from vessel_reconstruction.performance_geometry import _half_widths
        fp=aft/factor+lpp/factor
        z=np.linspace(float(mesh[:,:,2].min()),draft/factor,801)
        widths=2*_half_widths(mesh,fp,z)
        area=float(np.trapezoid(widths,z))
        hull["bulb_area_m2"]=area
        hull["bulb_center_height_m"]=float(np.trapezoid(widths*(z-z[0]),z)/area) if area>0 else 0
        if ship=="KCS":
            book=xlrd.open_workbook(args.data_dir/"KCS_vary_Fr_2-1.xls")
            sheet=book.sheet_by_index(0)
            speeds=[.915,1.281,1.647,1.922,2.196,2.379]
            measurements=[dict(speed_ms=speed,ct=sheet.cell_value(row,3)/1000,
                reference_surface_m2=9.4379,
                source=f"KCS_vary_Fr_2-1.xls Sheet1 D{row+1}; speed Case_2-1.html; S0 kcs_gc.html model1")
                for row,speed in zip(range(4,10),speeds)]
            water=dict(density_kg_m3=999.5,kinematic_viscosity_m2_s=1.27e-6)
            # Case 2.1 includes a rudder; coefficient reference is bare-hull S0.
            hull.update(appendage_area_m2=.1152,appendage_form_factor=1.5)
            notes=["Rudder (1+k2)=1.5 stated assumption; hull S0 is coefficient reference.",
                   "Geometry envelope measured from public starboard-half IGES; no force-based tuning."]
        else:
            sheet=xlrd.open_workbook(args.data_dir/"JBC_VOV_1-1a_template.xls").sheet_by_index(0)
            speed=.142*math.sqrt(9.81*7)
            measurements=[dict(speed_ms=speed,ct=sheet.cell_value(3,2)/1000,
                reference_surface_m2=.2494*7**2,
                source="JBC_VOV_1-1a_template.xls Sheet1 C4, A1, A14; model Lpp7m, Fr.142")]
            water=dict(density_kg_m3=999,kinematic_viscosity_m2_s=speed*7/7.46e6)
            notes=["Model Lpp7m, Fr.142; viscosity derived from published Re7.46e6.",
                   "Public jbc.igs bare hull; separate boss/spacer omitted and marked approximation."]
        for method in ("holtrop_mennen_1982","holtrop_1984"):
            case=dict(schema_version=1,ship=ship,scale="model",method=method,
                particulars_source=f"{path.name} sha256={metadata[ship]['geometry_sha256']}; envelope 401x401, chord2mm; workshop conditions",
                hull=hull,water=water,measurements=measurements,notes=notes)
            if ship=="JBC":
                case.update(propeller=dict(diameter_m=.203,blade_count=5,pitch_diameter_ratio=.75,
                    expanded_area_ratio=.50,shaft_efficiency=.98),sfoc_g_per_kwh=180)
                case["notes"]=notes+["B-series surrogate for AU MP687, not exact propeller; SFOC180 and etaS.98 assumptions."]
            cases.append(case)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as stream:
        json.dump({"cases":cases},stream,indent=2,allow_nan=False)
    with args.output.with_suffix(".geometry.json").open("x") as stream:
        json.dump(metadata,stream,indent=2,allow_nan=False)


if __name__=="__main__":
    main()
