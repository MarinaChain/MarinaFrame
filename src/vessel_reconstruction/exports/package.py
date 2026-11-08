"""Write every export of one draft revision and pack them in a zip with a manifest.

Files (``<stem>`` is ``<vessel>_<revision>_DRAFT``):
  <stem>_offsets.csv        half-breadths, stations x waterlines, with source labels
  <stem>_hydrostatics.json  hydrostatics summary (machine-readable)
  <stem>_hydrostatics.csv   the same summary, one quantity per row
  <stem>_report.pdf         review report with station overlays
  <stem>_model.step         the build's STEP, header stamped as a draft
  <stem>_model.stl          the build's STL, binary header stamped as a draft
  <stem>_manifest.json      file list with SHA-256 hashes and the source build identity
  <stem>_package.zip        all of the above

The task folder is only read. Hashes of the original STEP and STL bytes are
kept in the manifest, because the copies differ from them in the header only.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import zipfile

from .. import __version__
from ..provenance import digest_file
from .hydrostatics import Hydrostatics, design_draft, mesh_hydrostatics, read_stl, table_hydrostatics
from .offsets import DEFAULT_WATERLINE_INTERVALS, offsets_table, write_offsets_csv
from .report import FOOTER, ReportFacts, write_report
from .source import DraftBuild, load_build

STAMP = "Draft hull model from MarinaFrame. Not approved for construction."
DATUM = "Units metres (STEP and STL in millimetres); x along the length as drawn; z up from the baseline (z = 0)."
# Fixed timestamp for zip entries, so the same files give the same zip bytes.
ZIP_DATE_TIME = (2026, 1, 1, 0, 0, 0)
STEP_DESCRIPTION = re.compile(r"FILE_DESCRIPTION\(\(.*?\),'2;1'\);", re.DOTALL)
STEP_HEADER_BYTES = 4096
STL_HEADER_BYTES = 80


def stamp_lines(build: DraftBuild) -> list[str]:
    return [STAMP, f"Vessel {build.vessel}; revision {build.revision_id}; run {build.result.get('run_id', '-')}; "
            f"MarinaFrame {__version__}; review state "
            f"{(build.result.get('review') or {}).get('state', 'unreviewed')}.", DATUM, FOOTER]


def step_text(value: str) -> str:
    """A STEP string literal: apostrophes doubled, ASCII only."""
    return "'" + value.encode("ascii", "replace").decode().replace("'", "''") + "'"


def stamped_step(source: Path, target: Path, build: DraftBuild) -> bool:
    """Copy the STEP file with the draft stamp in FILE_DESCRIPTION; return False when no header matched."""
    data = source.read_bytes()
    # One character per byte, so character positions in ``head`` are byte positions in ``data``.
    head = data[:STEP_HEADER_BYTES].decode("latin-1")
    match = STEP_DESCRIPTION.search(head)
    header_end = head.find("ENDSEC;")
    if match is None or header_end < 0 or match.end() > header_end:
        target.write_bytes(data)
        return False
    lines = [STAMP, f"Vessel {build.vessel} revision {build.revision_id} run {build.result.get('run_id', '-')}",
             "Units mm; x along the length as drawn; z up from the baseline"]
    replacement = "FILE_DESCRIPTION((" + ",".join(step_text(v) for v in lines) + "),'2;1');"
    target.write_bytes(data[:match.start()] + replacement.encode("ascii") + data[match.end():])
    return True


def stamped_stl(source: Path, target: Path, build: DraftBuild) -> bool:
    """Copy the STL file; a binary STL gets the draft stamp in its 80-byte header."""
    data = source.read_bytes()
    if data[:5].lower() == b"solid" or len(data) < 84:  # ASCII STL: keep unchanged.
        target.write_bytes(data)
        return False
    header = f"MarinaFrame DRAFT {build.revision_id} not for construction".encode("ascii", "replace")
    target.write_bytes(header[:STL_HEADER_BYTES].ljust(STL_HEADER_BYTES, b" ") + data[STL_HEADER_BYTES:])
    return True


def compute_hydrostatics(build: DraftBuild, draft_m: float | None) -> tuple[Hydrostatics | None, str | None]:
    metrics = build.result.get("metrics") or {}
    bbox_min_z = ((metrics.get("bbox_m") or {}).get("min") or [0, 0, 0])[2]
    keel = float(bbox_min_z)
    try:
        level, basis = design_draft(build.spec, float(metrics.get("depth_m") or 0), keel, draft_m)
        if level <= keel:
            return None, f"the waterline z = {level:.3f} m is not above the keel z = {keel:.3f} m"
        if build.stl_path is not None:
            triangles = read_stl(build.stl_path, build.stl_units)
            return mesh_hydrostatics(triangles, level, basis, reference_volume_m3=metrics.get("volume_m3")), None
        return table_hydrostatics(build.sections, level, basis), None
    except (ValueError, OSError) as error:
        return None, str(error)


def write_hydrostatics(hydrostatics: Hydrostatics | None, error: str | None, build: DraftBuild,
                       json_path: Path, csv_path: Path) -> None:
    record = {"stamp": STAMP, "vessel": build.vessel, "revision": build.revision_id, "datum": DATUM,
              "engineering_approved": False, "hydrostatics": hydrostatics.as_dict() if hydrostatics else None,
              "not_computed_reason": error}
    json_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        for line in stamp_lines(build):
            writer.writerow([f"# {line}"])
        writer.writerow(["quantity", "value"])
        if hydrostatics is None:
            writer.writerow(["not_computed_reason", error])
            return
        for key, value in hydrostatics.as_dict().items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True)
            writer.writerow([key, "" if value is None else value])


def file_entry(path: Path, role: str, **extra) -> dict:
    return {"file": path.name, "role": role, "bytes": path.stat().st_size, "sha256": digest_file(path), **extra}


def write_zip(files: list[Path], path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            info = zipfile.ZipInfo(file.name, date_time=ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, file.read_bytes())


def export_draft(task_dir: Path, revision: str, out_dir: Path, *, draft_m: float | None = None,
                 waterline_intervals: int = DEFAULT_WATERLINE_INTERVALS, vessel: str | None = None) -> dict:
    """Write all exports of one revision into ``out_dir``; return the manifest."""
    build = load_build(Path(task_dir), revision, vessel)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = build.file_stem
    entries = []

    offsets = out_dir / f"{stem}_offsets.csv"
    table = offsets_table(build.sections, build.spec, waterline_intervals)
    write_offsets_csv(table, offsets, stamp_lines(build))
    entries.append((offsets, "offsets_table", {}))

    hydrostatics, error = compute_hydrostatics(build, draft_m)
    hydro_json, hydro_csv = out_dir / f"{stem}_hydrostatics.json", out_dir / f"{stem}_hydrostatics.csv"
    write_hydrostatics(hydrostatics, error, build, hydro_json, hydro_csv)
    entries += [(hydro_json, "hydrostatics", {}), (hydro_csv, "hydrostatics_table", {})]

    report = out_dir / f"{stem}_report.pdf"
    write_report(ReportFacts(build, hydrostatics, error, f"MarinaFrame {__version__}"), report)
    entries.append((report, "review_report", {}))

    missing = []
    for source, suffix, role, stamp in ((build.step_path, "step", "step_model", stamped_step),
                                        (build.stl_path, "stl", "stl_mesh", stamped_stl)):
        if source is None:
            missing.append(role)
            continue
        target = out_dir / f"{stem}_model.{suffix}"
        stamped = stamp(source, target, build)
        entries.append((target, role, {"source_sha256": digest_file(source), "header_stamped": stamped}))

    manifest = {"stamp": STAMP, "footer": FOOTER, "datum": DATUM, "engineering_approved": False,
                "tool": f"MarinaFrame {__version__}", "vessel": build.vessel, "revision": build.revision_id,
                "run_id": build.result.get("run_id"), "build": build.build_dir.name,
                "result_sha256": digest_file(build.build_dir / "result.json"),
                "review_state": (build.result.get("review") or {}).get("state", "unreviewed"),
                "draft_status": (build.result.get("draft") or {}).get("status"),
                "open_guesses": sum(1 for g in build.guesses if g.get("status") == "open"),
                "not_built": missing,
                "files": [file_entry(path, role, **extra) for path, role, extra in entries]}
    manifest_path = out_dir / f"{stem}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    package = out_dir / f"{stem}_package.zip"
    write_zip([path for path, _, _ in entries] + [manifest_path], package)
    manifest["package"] = file_entry(package, "package")
    manifest["manifest_file"] = manifest_path.name
    return manifest
