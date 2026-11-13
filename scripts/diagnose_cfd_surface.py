"""Report topology of one public IGES without changing or scoring its geometry."""
import argparse
import hashlib
import json
from pathlib import Path

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
from OCP.BRepGProp import BRepGProp
from OCP.BRep import BRep_Tool
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.IGESControl import IGESControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer


def shapes(shape, kind):
    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def diagnose(path):
    Interface_Static.SetCVal_s('xstep.cascade.unit', 'MM')
    reader = IGESControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError('Cannot read public IGES')
    reader.TransferRoots()
    result = diagnose_shape(reader.OneShape())
    result['source_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def diagnose_shape(shape):
    """Measure an OCCT shape in full-scale millimetres; do not repair it."""
    # IGES transfer uses millimetres: 0.1 mm full-scale sewing, not model scale.
    sewing = BRepBuilderAPI_Sewing(0.1)
    sewing.Add(shape)
    sewing.Perform()
    faces = []
    for index, face in enumerate(shapes(shape, TopAbs_FACE), 1):
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(face, box)
        properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, properties)
        faces.append(dict(index=index, bounds_full_scale_m=[x / 1000 for x in box.Get()],
                          area_full_scale_m2=properties.Mass() / 1e6,
                          valid=bool(BRepCheck_Analyzer(face).IsValid()),
                          surface_type=str(BRepAdaptor_Surface(TopoDS.Face_s(face)).GetType())))
    return dict(sewing_tolerance_full_scale_mm=0.1, faces=faces,
                shells_after_sewing=sum(1 for _ in shapes(sewing.SewedShape(), TopAbs_SHELL)),
                free_edges=sewing.NbFreeEdges(), multiple_edges=sewing.NbMultipleEdges(),
                degenerated_shapes=sewing.NbDegeneratedShapes(),
                free_edge_bounds_full_scale_m=[edge_bounds(sewing.FreeEdge(i))
                                               for i in range(1, sewing.NbFreeEdges() + 1)])


def edge_bounds(edge):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(edge, box)
    edge = TopoDS.Edge_s(edge)
    vertices = [TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)]
    endpoints = []
    for vertex in vertices:
        point = BRep_Tool.Pnt_s(vertex)
        endpoints.append([point.X() / 1000, point.Y() / 1000, point.Z() / 1000])
    return dict(bounds=[x / 1000 for x in box.Get()], endpoints=endpoints,
                degenerate=BRep_Tool.Degenerated_s(edge))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iges', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = diagnose(args.iges)
    with args.out.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k not in
                      ('faces', 'free_edge_bounds_full_scale_m')}))


if __name__ == '__main__':
    main()
