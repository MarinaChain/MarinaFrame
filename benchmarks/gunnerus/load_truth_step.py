"""Load the Gunnerus STEP truth model once and cache it as an OpenCascade BRep.

DATA-PRODUCTION utility for the sealed Gunnerus benchmark. The STEP file and
everything derived from it are truth data: they never enter inference input.
The source is git-ignored and must never be committed or sent to a provider.

The 763 MB STEP has one product with one MANIFOLD_SOLID_BREP. Reading it takes
minutes and several GB of memory, so this script runs once and writes:

- ``<out>/truth_hull.brep``: binary BRep of the single solid (millimetres).
- ``<out>/truth_load.json``: source hash, entity summary, bounding box, volume.

Usage::

    PYTHONPATH=src python -m benchmarks.gunnerus.load_truth_step --step <file> --out work/gunnerus/truth
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_step(step_path: Path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != IFSelect_RetDone:
        raise ValueError("Cannot read the STEP truth model.")
    reader.TransferRoots()
    return reader.OneShape()


def describe(shape) -> dict:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    def count(kind) -> int:
        explorer, total = TopExp_Explorer(shape, kind), 0
        while explorer.More():
            total += 1
            explorer.Next()
        return total

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return {"solids": count(TopAbs_SOLID), "shells": count(TopAbs_SHELL), "faces": count(TopAbs_FACE),
            "bbox_mm": {"min": [xmin, ymin, zmin], "max": [xmax, ymax, zmax]},
            "volume_mm3": props.Mass()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from OCP.BinTools import BinTools

    args.out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    source_sha = sha256_file(args.step)
    shape = load_step(args.step)
    loaded = time.perf_counter()
    summary = describe(shape)
    BinTools.Write_s(shape, str(args.out / "truth_hull.brep"))
    record = {"source_file": args.step.name, "source_sha256": source_sha, "source_bytes": args.step.stat().st_size,
              "load_seconds": loaded - started, "units": "mm", **summary}
    (args.out / "truth_load.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
