"""Compare the export hydrostatics engine with the supplied DSYHS upright tables.

No network, images, source-data edits or customer-hull reconstruction. XLSX values
are read from the stored XML cells; this script does not evaluate Excel formulas.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import numpy as np

from vessel_reconstruction.exports.hydrostatics import mesh_hydrostatics

SHEET_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
# Chord error in the source IGES unit (mm), and angular deflection in radians.
MESH_DEFLECTION_MM = 0.05
MESH_ANGLE_RAD = 0.05
GEOMETRY_TIMEOUT_SECONDS = 60
# The IGES global section gives 0.001 mm precision. Ignore roundoff at y=0.
CENTRELINE_TOLERANCE_M = 1e-6
# Each side's sampled breadth can differ from the surface by one chord tolerance.
FULL_HULL_SYMMETRY_TOLERANCE_M = 2 * MESH_DEFLECTION_MM / 1000
PRINTED_COLUMNS = {"volume_m3": "volc0", "lcb_m": "lcb0", "waterplane_area_m2": "aw0", "lcf_m": "lcf0"}
UNITS = {"volume_m3": "m3", "lcb_m": "m", "waterplane_area_m2": "m2", "lcf_m": "m"}
NOT_PRINTED = ["displacement_t", "vcb_m", "kmt_m", "tpc_t_per_cm", "mct_t_m_per_cm"]


def read_table(path: Path) -> list[dict]:
    """Read the canoe-body worksheet's cached numeric values, keeping absent cells absent."""
    with ZipFile(path) as archive:
        strings = ["".join(node.itertext()) for node in
                   ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", SHEET_NS)]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall("s:sheetData/s:row", SHEET_NS):
        values = {}
        for cell in row:
            value = cell.find("s:v", SHEET_NS)
            if value is not None and value.text is not None:
                column = re.sub(r"\d", "", cell.attrib["r"])
                values[column] = strings[int(value.text)] if cell.get("t") == "s" else float(value.text)
        rows.append(values)
    header = rows[0]
    return [{header[column]: value for column, value in row.items() if column in header} for row in rows[1:]]


def geometry_name(sysser: int, overhang: float) -> str:
    suffix = {1: "", 0.5: "_05", 0: "_0"}
    if overhang not in suffix:
        raise ValueError(f"Unsupported overhang {overhang}")
    return f"IGS/SYSSER{sysser:02d}{suffix[overhang]}_surface.igs"


def error_statistics(rows: list[dict]) -> dict:
    pairs = [(r["computed"], r["printed"]) for r in rows
             if r.get("computed") is not None and r.get("printed") is not None]
    errors = np.array([a - b for a, b in pairs])
    relative = np.array([abs(a - b) / abs(b) * 100 for a, b in pairs if b != 0])
    return {"n": len(pairs),
            "mean_error": float(errors.mean()) if len(errors) else None,
            "mean_absolute_error": float(np.abs(errors).mean()) if len(errors) else None,
            "max_absolute_error": float(np.abs(errors).max()) if len(errors) else None,
            "rms_error": float(np.sqrt(np.mean(errors ** 2))) if len(errors) else None,
            "relative_n": len(relative),
            "mean_absolute_error_percent": float(relative.mean()) if len(relative) else None,
            "max_absolute_error_percent": float(relative.max()) if len(relative) else None}


def complete_hull(triangles: np.ndarray) -> np.ndarray:
    """Reflect a half hull; keep a supplied full hull (SYSSER43) once only."""
    y = triangles[:, :, 1]
    port, starboard = -float(y.min()), float(y.max())
    # Small spline overshoots at the keel/stem are not a second hull side.
    # DSYHS canoe bodies are symmetric, so a full body must reach the same
    # breadth on both sides within the mesh's absolute chord tolerance.
    if (min(port, starboard) > CENTRELINE_TOLERANCE_M
            and math.isclose(port, starboard, rel_tol=0, abs_tol=FULL_HULL_SYMMETRY_TOLERANCE_M)):
        return triangles
    mirrored = triangles[:, ::-1].copy()
    mirrored[:, :, 1] *= -1
    return np.concatenate([triangles, mirrored])


def read_geometry(path: Path) -> np.ndarray:
    """Tessellate the IGES canoe body, then complete it if only one side is supplied."""
    import cadquery as cq
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.IGESControl import IGESControl_Reader
    from OCP.TopAbs import TopAbs_Orientation
    from OCP.TopLoc import TopLoc_Location

    reader = IGESControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError(f"Cannot read {path.name}")
    reader.TransferRoots()
    shape = cq.Shape.cast(reader.OneShape())
    # CadQuery.Shape.tessellate uses relative edge deflection. Request absolute
    # deflection here so tiny IGES edges do not force unbounded refinement.
    BRepMesh_IncrementalMesh(shape.wrapped, MESH_DEFLECTION_MM, False, MESH_ANGLE_RAD, False)
    pieces = []
    for face in shape.Faces():
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face.wrapped, location)
        if mesh is None:
            raise ValueError("An IGES face has no triangulation")
        transform = location.Transformation()
        vertices = [mesh.Node(i).Transformed(transform) for i in range(1, mesh.NbNodes() + 1)]
        points = np.array([[p.X(), p.Y(), p.Z()] for p in vertices]) / 1000
        indices = np.array([[t.Value(1) - 1, t.Value(2) - 1, t.Value(3) - 1] for t in mesh.Triangles()])
        if face.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
            indices = indices[:, ::-1]
        pieces.append(points[indices])
    return complete_hull(np.concatenate(pieces))


def check_sources(source: Path) -> dict:
    """Verify the three supplied inputs against the local manifest before using them."""
    # The supplied .tsv contains literal backslash-t separators.
    content = (source / "manifest.tsv").read_text().replace("\\t", "\t")
    records = list(csv.DictReader(content.splitlines(), delimiter="\t"))
    inputs = {}
    for record in records:
        path = source / record["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"Source hash mismatch: {path.name}")
        inputs[path.name] = digest
    required = {"geometriesIGSmodelscale.zip", "DSYHS_hydrostatics_modelscale.xlsx",
                "DSYHS_hydrostatics_fullscale.xlsx"}
    if not required <= inputs.keys():
        raise ValueError("The DSYHS manifest is missing a required input")
    return inputs


def run(source: Path, scratch: Path, out: Path) -> dict:
    hashes = check_sources(source)
    tables = {scale: read_table(source / f"DSYHS_hydrostatics_{scale}scale.xlsx") for scale in ("model", "full")}
    full_by_key = {(int(r["Sysser"]), r["Overhang"]): r for r in tables["full"]}
    comparisons, failures = [], []
    scratch.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    with ZipFile(source / "geometriesIGSmodelscale.zip") as archive, tempfile.TemporaryDirectory(dir=scratch) as tmp:
        for model_row in tables["model"]:
            key = int(model_row["Sysser"]), model_row["Overhang"]
            name = geometry_name(*key)
            try:
                local = Path(tmp) / "canoe.igs"
                local.write_bytes(archive.read(name))
                mesh_path = Path(tmp) / "canoe.npy"
                # Isolate each CAD import/mesh. A bad face must not block every
                # later printed row. Failures remain in the final denominator.
                subprocess.run([sys.executable, str(Path(__file__).resolve()), "--geometry", str(local),
                                "--mesh-out", str(mesh_path)], check=True, capture_output=True, text=True,
                               timeout=GEOMETRY_TIMEOUT_SECONDS)
                triangles = np.load(mesh_path)
                for scale, row in (("model", model_row), ("full", full_by_key[key])):
                    factor = row["lwl0"] / model_row["lwl0"]
                    # IGES z=0 is the nominal upright keel. Do not shift it to a
                    # tessellation vertex: small spline undershoots are geometry error.
                    h = mesh_hydrostatics(triangles * factor, row["tc0"], "DSYHS upright printed draft")
                    for quantity, column in PRINTED_COLUMNS.items():
                        computed = getattr(h, quantity)
                        if quantity in ("lcb_m", "lcf_m"):
                            computed -= row["lwl0"] / 2  # printed datum is mid Lwl; +x is forward
                        printed = row.get(column)
                        error = computed - printed if printed is not None else None
                        comparisons.append({"scale": scale, "sysser": key[0], "overhang": key[1],
                                            "geometry": name, "geometry_scale_factor": factor,
                                            "triangles": len(triangles), "draft_m": row["tc0"],
                                            "quantity": quantity, "unit": UNITS[quantity],
                                            "printed": printed, "computed": computed, "error": error,
                                            "absolute_error": abs(error) if error is not None else None,
                                            "absolute_error_percent": abs(error / printed) * 100 if printed else None,
                                            "absolute_error_percent_lwl": abs(error) / row["lwl0"] * 100
                                            if error is not None and quantity in ("lcb_m", "lcf_m") else None})
                print(f"checked {name}", flush=True)
            except (ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
                failures.append({"sysser": key[0], "overhang": key[1], "geometry": name, "reason": str(error)})
                print(f"not compared {name}: {error}", flush=True)
    statistics = {scale: {quantity: {"unit": UNITS[quantity], **error_statistics(
        [r for r in comparisons if r["scale"] == scale and r["quantity"] == quantity])}
        for quantity in PRINTED_COLUMNS} for scale in tables}
    result = {"source_sha256": hashes, "mesh_deflection_mm": MESH_DEFLECTION_MM,
              "mesh_deflection_is_relative": False, "geometry_timeout_seconds": GEOMETRY_TIMEOUT_SECONDS,
              "mesh_angle_rad": MESH_ANGLE_RAD, "printed_rows_per_scale": {k: len(v) for k, v in tables.items()},
              "full_scale_geometry": "model IGES scaled by full/model printed upright Lwl",
              "hull_completion": "reflect single-sided canoe bodies only; keep full hulls once",
              "not_printed_quantities": NOT_PRINTED, "failures": failures, "statistics": statistics}
    (out / "dsyhs_engine_check.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if comparisons:
        with (out / "dsyhs_engine_check.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(comparisons[0]))
            writer.writeheader()
            writer.writerows(comparisons)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", type=Path)
    mode.add_argument("--geometry", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--mesh-out", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--scratch", type=Path, default=Path("work/booklet-check"))
    parser.add_argument("--out", type=Path, default=Path("work/booklet-check"))
    args = parser.parse_args()
    if args.geometry is not None:
        if args.mesh_out is None:
            parser.error("--geometry needs --mesh-out")
        np.save(args.mesh_out, read_geometry(args.geometry))
        return 0
    result = run(args.source, args.scratch, args.out)
    print(json.dumps(result, indent=2))
    return int(bool(result["failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
