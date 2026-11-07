"""Hull sources for the benchmark factory.

Every hull is converted once to one canonical frame and cached as a triangle mesh:

- units: metres; the whole hull is scaled uniformly so that its length is ``CANONICAL_LENGTH_M``;
- x: from the aft extreme (0) to the forward extreme (length); y: athwartships, symmetric
  about 0 (half-hull sources keep y >= 0); z: up from the lowest point of the hull (0).

Two kinds of source are supported:

- ``brep``: exact CAD surfaces (IGES from SIMMAN and DSYHS, FreeCAD BRep for Series 60 and
  Wigley). The cut that is drawn on a body plan is an exact OpenCascade plane section of the
  native shape (``exact_section``). Truth is the fine tessellation of the same shape.
- ``shipd``: Ship-D parametric hulls. The dataset's own published generator
  (``HullParameterization.gen_stl``) makes a water-line mesh; that mesh is the geometry
  (no exact surface exists in the dataset code), and drawings and truth both come from it.

Truth and drawings of one hull always come from the same geometry. The factory does not
measure how well a hull source matches the real ship; it measures how well the pipeline
recovers the geometry that was drawn.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CANONICAL_LENGTH_M = 100.0
# Chord deviation of truth meshes, in canonical metres.
TRUTH_DEFLECTION_M = 0.0005
ROOT = Path(__file__).resolve().parents[2]


def sources_root() -> Path:
    return ROOT / "work" / "sources"


# --- named hulls -----------------------------------------------------------------------------
# axes: native index of (length, beam, vertical); signs: +1 when the native axis points
# forward / starboard-positive / up. unit_m: metres per native unit.
@dataclass(frozen=True)
class NamedHull:
    hull_id: str
    family: str
    kind: str  # "iges_zip" | "fcstd"
    archive: str  # path under work/sources
    member: str
    manifest: str  # manifest.tsv under work/sources that records provenance
    unit_m: float
    length_axis: int
    forward_sign: int
    vertical_axis: int
    up_sign: int
    licence: str
    description: str


NAMED_HULLS = [
    NamedHull("kcs", "kcs", "iges_zip", "simman/simman2008/KCS_hull_SVA.zip", "KCS_hull_SVA.igs",
              "simman/simman2008/manifest.tsv", 0.001, 0, 1, 2, 1,
              "SIMMAN 2008 workshop data; research and commercial use recorded by the project (docs/DATA_ACQUISITION.md)",
              "KRISO Container Ship, SVA Potsdam IGES hull, half hull"),
    NamedHull("kvlcc1", "kvlcc1", "iges_zip", "simman/simman2008/kvlcc1_hull.zip", "kvlcc1.igs",
              "simman/simman2008/manifest.tsv", 1.0, 0, -1, 2, 1,
              "SIMMAN 2008 workshop data; research and commercial use recorded by the project",
              "KVLCC1 tanker hull IGES"),
    NamedHull("kvlcc2", "kvlcc2", "iges_zip", "simman/simman2008/kvlcc2_hull.zip", "kvlcc2.igs",
              "simman/simman2008/manifest.tsv", 1.0, 0, -1, 2, 1,
              "SIMMAN 2008 workshop data; research and commercial use recorded by the project",
              "KVLCC2 tanker hull IGES"),
    NamedHull("dtmb5415", "dtmb5415", "iges_zip", "simman/simman2008/5415_hull_FORCE2004_IIHR2005_INSEAN2005.zip",
              "5415.igs", "simman/simman2008/manifest.tsv", 0.001, 0, -1, 2, 1,
              "SIMMAN 2008 workshop data; research and commercial use recorded by the project",
              "DTMB 5415 model (FORCE/IIHR/INSEAN IGES), half hull, x aft from the bow"),
    NamedHull("series60", "series60", "fcstd", "series60_freecad/src/Mod/Ship/resources/examples/s60.fcstd",
              "PartShape.brp", "series60_freecad/manifest.tsv", 0.001, 0, 1, 2, 1,
              "FreeCAD repo LGPL v2 with in-file CC-BY 3.0 field; research and commercial use recorded",
              "Series 60 (CB 0.60) digital copy from the FreeCAD Ship workbench examples"),
    NamedHull("wigley", "wigley", "fcstd", "series60_freecad/src/Mod/Ship/resources/examples/wigley.fcstd",
              "PartShape.brp", "series60_freecad/manifest.tsv", 0.001, 0, 1, 2, 1,
              "FreeCAD repo LGPL v2 with in-file CC-BY 3.0 field; analytic form",
              "Wigley hull from the FreeCAD Ship workbench examples"),
]
DSYHS_ARCHIVE = "dsyhs/geometriesIGSmodelscale.zip"
DSYHS_MANIFEST = "dsyhs/manifest.tsv"


def dsyhs_members() -> list[str]:
    with zipfile.ZipFile(sources_root() / DSYHS_ARCHIVE) as archive:
        return sorted(n for n in archive.namelist() if n.startswith("IGS/SYSSER") and n.endswith(".igs"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_row(manifest: Path, file_name: str) -> dict:
    lines = manifest.read_text().splitlines()
    header = lines[0].split("\t")
    for line in lines[1:]:
        cells = line.split("\t")
        if cells[0] == file_name or cells[0].endswith("/" + file_name):
            return dict(zip(header, cells))
    return {}


# --- OpenCascade helpers ---------------------------------------------------------------------
def read_native_shape(data: bytes, kind: str, scratch: Path):
    """Read an IGES or BRep byte string into an OpenCascade shape (native units)."""
    scratch.mkdir(parents=True, exist_ok=True)
    if kind == "iges":
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.IGESControl import IGESControl_Reader

        path = scratch / "hull.igs"
        path.write_bytes(data)
        reader = IGESControl_Reader()
        if reader.ReadFile(str(path)) != IFSelect_RetDone:
            raise RuntimeError("IGES read failed")
        reader.TransferRoots()
        return reader.OneShape()
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    path = scratch / "hull.brp"
    path.write_bytes(data)
    shape = TopoDS_Shape()
    BRepTools.Read_s(shape, str(path), BRep_Builder())
    return shape


def tessellate(shape, deflection: float, angular_rad: float = 0.2) -> np.ndarray:
    """Triangles (T, 3, 3) of a shape, in the shape's own units."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, deflection, False, angular_rad, True)
    blocks = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None:
            transform = location.Transformation()
            nodes = np.array([[p.X(), p.Y(), p.Z()] for p in
                              (triangulation.Node(i).Transformed(transform)
                               for i in range(1, triangulation.NbNodes() + 1))])
            triangles = np.array([triangulation.Triangle(i).Get()
                                  for i in range(1, triangulation.NbTriangles() + 1)]) - 1
            blocks.append(nodes[triangles])
        explorer.Next()
    return np.vstack(blocks)


def native_bounds(shape) -> np.ndarray:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    lo, hi = box.CornerMin(), box.CornerMax()
    return np.array([[lo.X(), lo.Y(), lo.Z()], [hi.X(), hi.Y(), hi.Z()]])


@dataclass(frozen=True)
class Frame:
    """Affine map native -> canonical: canonical = (native - origin)[axes] * signs * scale."""

    axes: tuple[int, int, int]  # native indices for canonical x, y, z
    signs: tuple[float, float, float]
    origin: tuple[float, float, float]  # native point that maps to canonical (0, *, 0)
    scale: float  # canonical metres per native unit
    fold_y: bool  # half hull on the negative side: y -> -y so that y >= 0

    def apply(self, points: np.ndarray) -> np.ndarray:
        native = points - np.asarray(self.origin)
        out = np.stack([native[:, self.axes[i]] * self.signs[i] for i in range(3)], axis=1) * self.scale
        return out

    def to_dict(self) -> dict:
        return {"axes": list(self.axes), "signs": list(self.signs), "origin": list(self.origin),
                "scale": self.scale, "fold_y": self.fold_y}

    @staticmethod
    def from_dict(d: dict) -> "Frame":
        return Frame(tuple(d["axes"]), tuple(d["signs"]), tuple(d["origin"]), d["scale"], d["fold_y"])


def _handedness(frame: Frame) -> float:
    matrix = np.zeros((3, 3))
    for row, axis in enumerate(frame.axes):
        matrix[row, axis] = frame.signs[row]
    return float(np.sign(np.linalg.det(matrix)))


def make_frame(bounds: np.ndarray, hull: NamedHull) -> Frame:
    lo, hi = bounds
    length_axis, vertical_axis = hull.length_axis, hull.vertical_axis
    beam_axis = ({0, 1, 2} - {length_axis, vertical_axis}).pop()
    extent = (hi - lo)[length_axis]
    scale = CANONICAL_LENGTH_M / extent
    ox = lo[length_axis] if hull.forward_sign > 0 else hi[length_axis]
    oz = lo[vertical_axis] if hull.up_sign > 0 else hi[vertical_axis]
    origin = [0.0, 0.0, 0.0]
    origin[length_axis], origin[vertical_axis] = ox, oz
    low_y, high_y = lo[beam_axis], hi[beam_axis]
    half_negative = bool(high_y <= 1e-6 * extent and low_y < 0)
    return Frame((length_axis, beam_axis, vertical_axis), (float(hull.forward_sign), -1.0 if half_negative else 1.0,
                                                           float(hull.up_sign)), tuple(origin), scale, half_negative)


# --- exact sections --------------------------------------------------------------------------
def exact_section(shape, frame: Frame, x_canonical_m: float, deflection_native: float) -> list[np.ndarray]:
    """Exact plane section of a native shape at canonical x; polylines in canonical (y, z) metres."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    axis = frame.axes[0]
    sign = frame.signs[0]
    native_position = frame.origin[axis] + x_canonical_m / frame.scale * sign
    origin = [0.0, 0.0, 0.0]
    origin[axis] = native_position
    normal = [0.0, 0.0, 0.0]
    normal[axis] = 1.0
    section = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(*origin), gp_Dir(*normal)), False)
    section.Build()
    if not section.IsDone():
        raise RuntimeError(f"section failed at x={x_canonical_m}")
    polylines = []
    explorer = TopExp_Explorer(section.Shape(), TopAbs_EDGE)
    while explorer.More():
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(explorer.Current()))
        sampler = GCPnts_QuasiUniformDeflection(curve, deflection_native)
        if sampler.IsDone() and sampler.NbPoints() >= 2:
            pts = [sampler.Value(i) for i in range(1, sampler.NbPoints() + 1)]
        else:
            pts = [curve.Value(float(t)) for t in np.linspace(curve.FirstParameter(), curve.LastParameter(), 65)]
        native = np.array([[p.X(), p.Y(), p.Z()] for p in pts])
        canonical = frame.apply(native)
        polylines.append(canonical[:, 1:])
        explorer.Next()
    return polylines


# --- chains and clipping ---------------------------------------------------------------------
def chain_polylines(pieces: list[np.ndarray], tol: float = 2.0e-5) -> list[np.ndarray]:
    """Join polylines/segments that touch end to end (within ``tol``) into longer chains."""
    pieces = [np.asarray(p, float) for p in pieces if len(p) >= 2]
    if not pieces:
        return []
    key = lambda p: (int(round(p[0] / tol)), int(round(p[1] / tol)))  # noqa: E731
    ends: dict = {}
    for index, piece in enumerate(pieces):
        for which in (0, -1):
            k = key(piece[which])
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    ends.setdefault((k[0] + dy, k[1] + dz), []).append((index, which))
    used = [False] * len(pieces)
    chains = []
    for start in range(len(pieces)):
        if used[start]:
            continue
        used[start] = True
        chain = list(pieces[start])
        for direction in (1, -1):
            while True:
                tip = chain[-1] if direction == 1 else chain[0]
                options = [(i, w) for (i, w) in ends.get(key(tip), []) if not used[i]]
                if not options:
                    break
                i, w = options[0]
                used[i] = True
                nxt = list(pieces[i])
                if (w == 0) != (direction == 1):
                    nxt = nxt[::-1]
                if direction == 1:
                    chain.extend(nxt[1:])
                else:
                    chain = nxt[:-1] + chain
        chains.append(np.array(chain))
    return chains


def clip_half(polylines: list[np.ndarray]) -> list[np.ndarray]:
    """Keep the part with y >= 0 (starboard half) of each polyline; interpolate at y = 0."""
    result = []
    for line in polylines:
        run: list = []
        for a, b in zip(line[:-1], line[1:]):
            ina, inb = a[0] >= 0, b[0] >= 0
            if ina and not run:
                run.append(a)
            if ina and inb:
                run.append(b)
            elif ina and not inb:
                t = a[0] / (a[0] - b[0])
                run.append(a + t * (b - a))
                result.append(np.array(run))
                run = []
            elif not ina and inb:
                t = a[0] / (a[0] - b[0])
                run = [a + t * (b - a), b]
        if len(run) >= 2:
            result.append(np.array(run))
    return [r for r in result if len(r) >= 2]


# --- hull container --------------------------------------------------------------------------
@dataclass
class Hull:
    hull_id: str
    family: str
    triangles: np.ndarray  # (T, 3, 3) canonical metres
    length_m: float
    depth_m: float
    max_half_breadth_m: float
    half_hull: bool
    provenance: dict
    shape: object = None  # native OpenCascade shape (brep hulls) or None
    frame: Frame | None = None

    def drawn_section(self, x_m: float) -> list[np.ndarray]:
        """Starboard half of the true section at x, as polylines in (y, z) metres."""
        if self.shape is not None:
            deflection_native = TRUTH_DEFLECTION_M / self.frame.scale
            # A plane exactly on a face boundary (midships of the Wigley hull) gives duplicate edges;
            # cut 0.1 mm inside, the same offset the scorer uses for terminal cuts.
            pieces = exact_section(self.shape, self.frame, x_m + 1.0e-4, deflection_native)
        else:
            from benchmarks.gunnerus.hull_metrics import cut_mesh

            pieces = cut_mesh(self.triangles, x_m)
        chains = chain_polylines(pieces)
        return clip_half(chains)


def _finish(hull_id, family, triangles, shape, frame, provenance) -> Hull:
    lo, hi = triangles.reshape(-1, 3).min(axis=0), triangles.reshape(-1, 3).max(axis=0)
    half = bool(lo[1] >= -1e-6 * CANONICAL_LENGTH_M)
    return Hull(hull_id, family, triangles, float(hi[0] - lo[0]), float(hi[2] - lo[2]),
                float(max(abs(lo[1]), abs(hi[1]))), half, provenance, shape, frame)


def load_named(hull: NamedHull, scratch: Path) -> Hull:
    with zipfile.ZipFile(sources_root() / hull.archive) as archive:
        data = archive.read(hull.member)
    return _load_brep(hull.hull_id, hull.family, data, "iges" if hull.kind == "iges_zip" else "brep", hull, scratch,
                      archive_path=sources_root() / hull.archive, manifest=sources_root() / hull.manifest,
                      member=hull.member)


def _load_brep(hull_id, family, data, kind, recipe, scratch, *, archive_path, manifest, member) -> Hull:
    shape = read_native_shape(data, kind, scratch)
    bounds = native_bounds(shape)
    frame = make_frame(bounds, recipe)
    native_deflection = TRUTH_DEFLECTION_M / frame.scale
    native = tessellate(shape, native_deflection)
    triangles = frame.apply(native.reshape(-1, 3)).reshape(-1, 3, 3)
    if _handedness(frame) < 0:  # a reflection reverses the triangle orientation
        triangles = triangles[:, ::-1]
    lo_y, hi_y = triangles[:, :, 1].min(), triangles[:, :, 1].max()
    if lo_y > -0.01 * hi_y:  # half hull: remove sub-percent overshoot across the centreplane
        triangles = triangles.copy()
        triangles[:, :, 1] = np.maximum(triangles[:, :, 1], 0.0)
    row = manifest_row(manifest, archive_path.name)
    provenance = {"source": "brep", "member": member, "member_sha256": _sha256(data),
                  "archive": str(archive_path.relative_to(sources_root())),
                  "archive_sha256": row.get("sha256"), "source_url": row.get("source_url") or row.get("url"),
                  "licence_terms": getattr(recipe, "licence", None) or row.get("licence_terms"),
                  "description": getattr(recipe, "description", None),
                  "native_bounds": bounds.tolist(), "frame": frame.to_dict(),
                  "mesh_deflection_m": TRUTH_DEFLECTION_M}
    return _finish(hull_id, family, triangles, shape, frame, provenance)


def load_dsyhs(member: str, scratch: Path) -> Hull:
    with zipfile.ZipFile(sources_root() / DSYHS_ARCHIVE) as archive:
        data = archive.read(member)
    number = Path(member).name.replace("_surface.igs", "").lower()
    recipe = NamedHull(number, "dsyhs", "iges_zip", DSYHS_ARCHIVE, member, DSYHS_MANIFEST, 0.001, 0, 1, 2, 1,
                       "CC0 1.0 (4TU.ResearchData)", f"Delft Systematic Yacht Hull Series {number.upper()}, bare hull")
    return _load_brep(number, "dsyhs", data, "iges", recipe, scratch, archive_path=sources_root() / DSYHS_ARCHIVE,
                      manifest=sources_root() / DSYHS_MANIFEST, member=member)


# --- Ship-D ----------------------------------------------------------------------------------
SHIPD_SETS = ("Constrained_Randomized_Set_1", "Constrained_Randomized_Set_2", "Constrained_Randomized_Set_3")


def shipd_root() -> Path:
    return sources_root() / "shipd"


def shipd_vectors() -> tuple[np.ndarray, list[tuple[str, int]]]:
    """All feasible Ship-D parameter vectors (the three constrained random sets) and their keys."""
    blocks, keys = [], []
    for name in SHIPD_SETS:
        path = shipd_root() / "data" / "Ship_D_Dataset" / name / "Input_Vectors.csv"
        block = np.loadtxt(path, delimiter=",", skiprows=1)
        blocks.append(block)
        keys += [(name, i) for i in range(len(block))]
    return np.vstack(blocks), keys


def _load_shipd_module():
    """Import the dataset's published generator from its file path.

    Its only third-party need beyond numpy/matplotlib is ``numpy-stl`` for writing STL files.
    We never write STL files, so a minimal stand-in provides the array container.
    """
    if "stl" not in sys.modules:
        stl, mesh = types.ModuleType("stl"), types.ModuleType("stl.mesh")

        class Mesh:
            dtype = np.dtype([("normals", "f4", (3,)), ("vectors", "f4", (3, 3)), ("attr", "u2")])

            def __init__(self, data):
                self.data, self.vectors = data, data["vectors"]

            def save(self, _path):
                pass

        mesh.Mesh = Mesh
        stl.mesh = mesh
        sys.modules["stl"], sys.modules["stl.mesh"] = stl, mesh
    if "HullParameterization" in sys.modules:
        return sys.modules["HullParameterization"]
    path = shipd_root() / "code" / "HullParameterization.py"
    spec = importlib.util.spec_from_file_location("HullParameterization", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["HullParameterization"] = module
    spec.loader.exec_module(module)
    return module


SHIPD_NUM_WL = 160
SHIPD_POINTS_PER_WL = 800


def load_shipd(key: tuple[str, int], vector: np.ndarray, family: str) -> Hull:
    module = _load_shipd_module()
    parameterization = module.Hull_Parameterization(vector)
    mesh = parameterization.gen_stl(NUM_WL=SHIPD_NUM_WL, PointsPerWL=SHIPD_POINTS_PER_WL, bit_AddTransom=1,
                                    bit_AddDeckLid=0, namepath="/dev/null")
    raw = np.array(mesh.vectors, dtype=float)
    if not np.isfinite(raw).all():
        raise ValueError("non-finite Ship-D mesh")
    # Generator frame: x from the bow aft, y athwartships, z up from the keel line.
    x_max = raw[:, :, 0].max()
    scale = CANONICAL_LENGTH_M / float(vector[0])
    flipped = raw.copy()
    flipped[:, :, 0] = (x_max - raw[:, :, 0])
    triangles = flipped * scale
    triangles = triangles[:, ::-1]  # x was reflected
    lo = triangles.reshape(-1, 3).min(axis=0)
    triangles = triangles - np.array([lo[0], 0.0, lo[2]])
    hull_id = f"shipd-{key[0].split('_')[-1]}-{key[1]:05d}"
    provenance = {"source": "shipd", "set": key[0], "row": int(key[1]), "family_cluster": family,
                  "licence_terms": "Ship-D (Harvard Dataverse DOI 10.7910/DVN/MMGAUS); research and commercial use recorded by the project",
                  "parameters_sha256": _sha256(np.asarray(vector, dtype="<f8").tobytes()),
                  "generator": "HullParameterization.gen_stl", "num_wl": SHIPD_NUM_WL,
                  "points_per_wl": SHIPD_POINTS_PER_WL, "scale_to_canonical": scale}
    return _finish(hull_id, family, triangles, None, None, provenance)


# --- cache -----------------------------------------------------------------------------------
def cache_hull(hull: Hull, directory: Path) -> Path:
    """Write the canonical mesh (and the native shape of exact hulls) under ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{hull.hull_id}.npz"
    meta = {"hull_id": hull.hull_id, "family": hull.family, "length_m": hull.length_m, "depth_m": hull.depth_m,
            "max_half_breadth_m": hull.max_half_breadth_m, "half_hull": hull.half_hull,
            "provenance": hull.provenance, "has_shape": hull.shape is not None}
    np.savez_compressed(path, triangles=hull.triangles, meta=json.dumps(meta))
    if hull.shape is not None:
        from OCP.BinTools import BinTools

        BinTools.Write_s(hull.shape, str(directory / f"{hull.hull_id}.brep"))
    return path


def load_cached(directory: Path, hull_id: str) -> Hull:
    data = np.load(directory / f"{hull_id}.npz", allow_pickle=False)
    meta = json.loads(str(data["meta"]))
    shape, frame = None, None
    if meta["has_shape"]:
        from OCP.BinTools import BinTools
        from OCP.TopoDS import TopoDS_Shape

        shape = TopoDS_Shape()
        BinTools.Read_s(shape, str(directory / f"{hull_id}.brep"))
        frame = Frame.from_dict(meta["provenance"]["frame"])
    return Hull(meta["hull_id"], meta["family"], data["triangles"], meta["length_m"], meta["depth_m"],
                meta["max_half_breadth_m"], meta["half_hull"], meta["provenance"], shape, frame)
