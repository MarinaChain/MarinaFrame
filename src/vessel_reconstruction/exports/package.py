"""Write every export of one draft revision and pack them in a zip with a manifest.

Files (``<stem>`` is ``<vessel>_<revision>_DRAFT``):
  <stem>_offsets.csv        half-breadths, stations x waterlines, with source labels
  <stem>_hydrostatics.json  hydrostatics summary (machine-readable)
  <stem>_hydrostatics.csv   the same summary, one quantity per row
  <stem>_report.pdf         review report with station overlays
  <stem>_model.step         the build's STEP, header stamped as a draft
  <stem>_model.iges         the build's draft IGES trimmed surfaces, millimetres
  <stem>_model.3dm          the build's draft Rhino layers and faces, millimetres
  <stem>_model.stl          the build's STL, binary header stamped as a draft
  <stem>_capacity_plan.csv  capacity plan, when a tank model is given (``tanks``)
  <stem>_sounding_<id>.csv  sounding table of each built tank, when a tank model is given
  <stem>_<name>             steel tables (*_steel_members.csv, *_steel_totals.csv) and OCX
                            files (*.3docx) of a structure folder, when one is given
                            (``structure_dir``); copied, they carry their own draft stamp. With a tank
                            model, the tanks are added as OCX compartments to the one OCX file of the
                            structure folder (role ocx_structure_tanks)
  <stem>_tanks.3docx        tanks only, as OCX compartments: written when there is a tank model and no
                            single structure OCX file to hold them (role ocx_tanks)
  glb/*.glb                existing display meshes, copied with metre-scale scene transforms
  assets.json              stable asset ids linked to GLB files and part nodes
  spaces.json              built tanks, with bounds in model metres and source labels
  frames.json              stored frame spacing, zero and table; unknown when not supplied
  <stem>_manifest.json      file list with SHA-256 hashes and the source build identity
  <stem>_package.zip        all of the above

Legacy tasks gain a vessel identity sidecar; existing task evidence is only read.
Hashes of the original STEP and STL bytes are
kept in the manifest, because the copies differ from them in the header only.
"""
from __future__ import annotations

import csv
import ctypes
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

from .. import __version__
# The module, not its names: ``structure.ocx`` imports ``tanks``, which imports this package.
from ..structure import ocx
from ..provenance import digest_file
from ..resources import ResourceLimitError
from ..booklet_check import Booklet, compare_booklet, load_booklet, write_comparison_csv
from .csv_safety import safe_text_cell
from .hydrostatics import Hydrostatics, design_draft, mesh_hydrostatics, read_stl, table_hydrostatics
from .offsets import DEFAULT_WATERLINE_INTERVALS, offsets_table, write_offsets_csv
from ..accuracy_summary import facts_from_build as accuracy_facts_from_build
from .report import FOOTER, VIEWER_CAPTURE_FILE, ReportFacts, write_report
from .source import DraftBuild, ExportError, load_build
from .tank_tables import write_tank_tables
from .identity import manifest_identity, known_particulars
from .spatial import write_spatial

STAMP = "Draft hull model from MarinaFrame. Not approved for construction."
DATUM = "Units metres (STEP, IGES, Rhino 3dm and STL in millimetres); x along the length as drawn; z up from the baseline (z = 0)."
# Fixed timestamp for zip entries, so the same files give the same zip bytes.
ZIP_DATE_TIME = (2026, 1, 1, 0, 0, 0)
STEP_DESCRIPTION = re.compile(r"FILE_DESCRIPTION\(\(.*?\),'2;1'\);", re.DOTALL)
STEP_HEADER_BYTES = 4096
STL_HEADER_BYTES = 80
# Files of a structure folder (``structure.steel.write_steel_tables`` and ``structure.ocx.export_ocx``)
# that go into the package, by name suffix, with their manifest role.
STRUCTURE_FILE_ROLES = (("_steel_members.csv", "steel_members"), ("_steel_totals.csv", "steel_totals"),
                        (".3docx", "ocx_structure"))


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
        from .source import domain_root, read_json
        domain = domain_root(build.task_dir)
        known = known_particulars(build, domain, read_json(domain / "state.json"))
        spec = dict(build.spec)
        if any(item.get("field") == "draft_m" for item in known.get("check_items", [])) and "draft_m" not in known:
            spec.pop("design_draft_m", None)
            spec.pop("design_draft_source", None)
        if known.get("draft_m") is not None:
            spec["design_draft_m"] = known["draft_m"]
            spec["design_draft_source"] = (known.get("sources") or {}).get("draft_m", {"status": "typed"})
        level, basis = design_draft(spec, float(metrics.get("depth_m") or 0), keel, draft_m)
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
            writer.writerow(["not_computed_reason", safe_text_cell(error)])
            return
        for key, value in hydrostatics.as_dict().items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True)
            if isinstance(value, str):
                value = safe_text_cell(value)
            writer.writerow([key, "" if value is None else value])


def copy_structure_files(structure_dir: Path, out_dir: Path, stem: str,
                         tanks: list | None = None) -> tuple[list[tuple[Path, str, dict]], list[str]]:
    """Copy the steel tables and OCX files of ``structure_dir`` as ``<stem>_<name>``; return their entries.

    When ``tanks`` hold built tanks and the folder has exactly one OCX file, that file gets the tanks as
    compartments (one OCX file with steel and tanks).
    """
    sources = []
    for source in sorted(Path(structure_dir).iterdir()):
        role = next((role for suffix, role in STRUCTURE_FILE_ROLES if source.name.endswith(suffix)), None)
        if role is not None and source.is_file() and not source.is_symlink():
            sources.append((source, role))
    ocx_sources = [source for source, role in sources if role == "ocx_structure"]
    entries, failures = [], []
    for source, role in sources:
        target = out_dir / f"{stem}_{source.name}"
        extra = {"source_file": source.name}
        try:
            if ocx_sources == [source] and ocx.add_compartments(source, target, tanks):
                role, extra["compartments"] = "ocx_structure_tanks", len(ocx.writable_tanks(tanks))
            else:
                target.write_bytes(source.read_bytes())
        except ResourceLimitError:
            raise
        except Exception as error:
            if role != "ocx_structure":
                raise
            target.unlink(missing_ok=True)
            failures.append(str(error).strip() or type(error).__name__)
            continue
        entries.append((target, role, extra))
    return entries, failures


def write_tanks_ocx(tanks: list, out_dir: Path, stem: str, vessel: str) -> tuple[Path, str, dict]:
    """Write the tanks as an OCX file of compartments only."""
    path = out_dir / f"{stem}_tanks.3docx"
    count = ocx.export_ocx(None, path, name=f"{vessel} tanks", tanks=tanks)
    return path, "ocx_tanks", {"compartments": count}


def file_entry(path: Path, role: str, *, root: Path | None = None, **extra) -> dict:
    name = path.relative_to(root).as_posix() if root is not None else path.name
    return {"file": name, "role": role, "bytes": path.stat().st_size, "sha256": digest_file(path), **extra}


def write_zip(files: list[Path], path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            info = zipfile.ZipInfo(file.relative_to(path.parent).as_posix(), date_time=ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, file.read_bytes())


def _exchange_directories(first: Path, second: Path) -> None:
    """Swap two existing directories in one filesystem operation."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        operation = libc.renameatx_np
        current_directory = -2  # macOS AT_FDCWD
    elif sys.platform.startswith("linux"):
        operation = libc.renameat2
        current_directory = -100  # Linux AT_FDCWD
    else:
        raise ExportError("Atomic replacement of an existing package is not supported on this platform.")
    operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    operation.restype = ctypes.c_int
    # Both systems use 2 for an atomic exchange of the two paths.
    if operation(current_directory, os.fsencode(first), current_directory, os.fsencode(second), 2) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


@contextmanager
def _package_stage(target: Path):
    """Keep the target intact until the complete sibling directory is ready."""
    # A relative "." otherwise puts the stage inside the directory being copied.
    target = Path(os.path.abspath(target))
    if Path.cwd().is_relative_to(target):
        raise ExportError("The package destination must not replace the current directory.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ExportError("The package target must be a directory, not a symbolic link.")
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        if target.exists():
            if any(path.is_symlink() for path in target.rglob("*")):
                raise ExportError("The package target must not contain symbolic links.")
            shutil.copytree(target, stage, dirs_exist_ok=True)
        yield stage
        if target.exists():
            _exchange_directories(stage, target)
        else:
            os.rename(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _check_package(stage: Path, manifest: dict) -> None:
    """Check the staged file hashes and archive contents before publication."""
    entries = manifest["files"]
    expected = {entry["file"] for entry in entries} | {manifest["manifest_file"]}
    for entry in entries:
        path = stage / entry["file"]
        if path.stat().st_size != entry["bytes"] or digest_file(path) != entry["sha256"]:
            raise ExportError(f"Staged package file changed: {entry['file']}.")
    with zipfile.ZipFile(stage / manifest["package"]["file"]) as archive:
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise ExportError("Staged package archive has an incorrect file list.")
        for entry in entries:
            if hashlib.sha256(archive.read(entry["file"])).hexdigest() != entry["sha256"]:
                raise ExportError(f"Staged package archive differs: {entry['file']}.")
        if archive.read(manifest["manifest_file"]) != (stage / manifest["manifest_file"]).read_bytes():
            raise ExportError("Staged package archive has a different manifest.")


def _report_progress(stage: str) -> None:
    """Tell the app's progress watchdog that the export moved on (no-op outside a supervised run)."""
    from .. import progress

    try:
        progress.report(stage)
    except (OSError, ValueError, KeyError):
        pass  # Telemetry failures must not fail an export.


def export_draft(task_dir: Path, revision: str, out_dir: Path, *, draft_m: float | None = None,
                 waterline_intervals: int = DEFAULT_WATERLINE_INTERVALS, vessel: str | None = None,
                 tanks: list | None = None, structure_dir: Path | None = None,
                 booklet: Booklet | Path | str | None = None) -> dict:
    """Write all exports of one revision into ``out_dir``; return the manifest.

    ``tanks`` (``vessel_reconstruction.tanks.Tank`` list) adds the capacity plan, the sounding tables and
    the tanks as OCX compartments; ``structure_dir`` adds the steel tables and OCX files found in that
    folder. ``booklet`` adds printed hydrostatic comparisons to the CSV, PDF and accuracy line.
    """
    build = load_build(Path(task_dir), revision, vessel)
    destination = Path(out_dir).resolve()
    task_root = build.task_dir.resolve()
    domain = task_root / "domain"
    if task_root.is_relative_to(destination) or destination.is_relative_to(domain):
        raise ExportError("The package destination must not replace task or build evidence.")
    if structure_dir is not None and Path(structure_dir).resolve().is_relative_to(destination):
        raise ExportError("The package destination must not replace its structure source.")
    identity = manifest_identity(build, tanks, structure_dir)
    booklet_check = None
    if booklet is not None:
        try:
            if isinstance(booklet, (Path, str)):
                booklet = load_booklet(Path(booklet))
            if not isinstance(booklet, Booklet):
                raise ValueError("Supply a parsed Booklet or JSON file path")
            geometry = ({"triangles": read_stl(build.stl_path, build.stl_units)} if build.stl_path is not None
                        else {"sections": build.sections})
            booklet_check = compare_booklet(booklet, **geometry)
        except (ValueError, OSError) as error:
            raise ExportError(f"Cannot check booklet: {error}") from error
    with _package_stage(Path(out_dir)) as out_dir:
        stem = build.file_stem
        _report_progress("Writing the 3D files")
        entries, units_axes, glb_result, display_omissions = write_spatial(build, identity, tanks, structure_dir, out_dir)
        format_results = dict(build.result.get("export_results") or {})
        if glb_result is not None:
            format_results["glb"] = glb_result

        _report_progress("Writing the offsets")
        offsets = out_dir / f"{stem}_offsets.csv"
        table = offsets_table(build.sections, build.spec, waterline_intervals)
        write_offsets_csv(table, offsets, stamp_lines(build))
        entries.append((offsets, "offsets_table", {}))

        _report_progress("Computing the hydrostatics")
        hydrostatics, error = compute_hydrostatics(build, draft_m)
        hydro_json, hydro_csv = out_dir / f"{stem}_hydrostatics.json", out_dir / f"{stem}_hydrostatics.csv"
        write_hydrostatics(hydrostatics, error, build, hydro_json, hydro_csv)
        entries += [(hydro_json, "hydrostatics", {}), (hydro_csv, "hydrostatics_table", {})]

        if booklet_check is not None:
            booklet_csv = out_dir / f"{stem}_booklet_check.csv"
            write_comparison_csv(booklet_check, booklet_csv, stamp_lines(build))
            entries.append((booklet_csv, "booklet_check", {}))

        capacity_rows = None
        _report_progress("Writing the tank and structure tables")
        if tanks:
            capacity_rows, tank_entries = write_tank_tables(tanks, out_dir, stem, stamp_lines(build))
            entries += tank_entries
        structure_entries, ocx_failures = (copy_structure_files(Path(structure_dir), out_dir, stem, tanks)
                                           if structure_dir else ([], []))
        entries += structure_entries
        if ocx.writable_tanks(tanks) and not any(role == "ocx_structure_tanks" for _, role, _ in structure_entries):
            try:
                entries.append(write_tanks_ocx(tanks, out_dir, stem, build.vessel))
            except ResourceLimitError:
                raise
            except Exception as export_error:
                (out_dir / f"{stem}_tanks.3docx").unlink(missing_ok=True)
                ocx_failures.append(str(export_error).strip() or type(export_error).__name__)
        if ocx_failures:
            format_results["ocx"] = {"status": "failed", "reason": "; ".join(ocx_failures)[:1000]}
        elif any(role.startswith("ocx_") for _, role, _ in entries):
            format_results["ocx"] = {"status": "ok", "reason": None}

        _report_progress("Writing the report")
        report = out_dir / f"{stem}_report.pdf"
        # The app writes a picture of its 3D view here before the export; without it the report is unchanged.
        viewer_image = out_dir / VIEWER_CAPTURE_FILE
        booklet_summary = booklet_check.summary if booklet_check is not None else None
        write_report(ReportFacts(build, hydrostatics, error, f"MarinaFrame {__version__}", capacity_rows,
                                 accuracy_facts_from_build(build, capacity_rows, structure_dir, booklet_summary),
                                 booklet_check, viewer_image if viewer_image.is_file() else None), report)
        entries.append((report, "review_report", {}))

        _report_progress("Copying the CAD models")
        missing = []
        for source, suffix, role, stamp in ((build.step_path, "step", "step_model", stamped_step),
                                            (build.iges_path, "iges", "iges_model", None),
                                            (build.rhino_path, "3dm", "rhino_model", None),
                                            (build.stl_path, "stl", "stl_mesh", stamped_stl)):
            target = out_dir / f"{stem}_model.{suffix}"
            if source is None:
                target.unlink(missing_ok=True)
                missing.append(role)
                continue
            try:
                extra = {"source_sha256": digest_file(source)}
                if stamp is not None:
                    extra["header_stamped"] = stamp(source, target, build)
                else:
                    # IGES and 3dm already carry draft notes. Preserve their bytes and metadata.
                    target.write_bytes(source.read_bytes())
                    extra["units"] = "mm"
            except ResourceLimitError:
                raise
            except Exception as export_error:
                target.unlink(missing_ok=True)
                missing.append(role)
                format_results[suffix] = {"status": "failed", "reason": (str(export_error).strip() or type(export_error).__name__)[:1000]}
                continue
            format_results[suffix] = {"status": "ok", "reason": None}
            entries.append((target, role, extra))

        manifest = {**identity, "stamp": STAMP, "footer": FOOTER, "datum": DATUM, "engineering_approved": False,
                    "tool": f"MarinaFrame {__version__}", "vessel": build.vessel, "revision": build.revision_id,
                    "run_id": build.result.get("run_id"), "build": build.build_dir.name,
                    "result_sha256": digest_file(build.build_dir / "result.json"),
                    "review_state": (build.result.get("review") or {}).get("state", "unreviewed"),
                    "draft_status": (build.result.get("draft") or {}).get("status"),
                    "open_guesses": sum(1 for g in build.guesses if g.get("status") == "open"),
                    "not_built": missing, "format_results": format_results, "display_omissions": display_omissions,
                    "units_axes": units_axes,
                    "files": [file_entry(path, role, root=out_dir, **extra) for path, role, extra in entries]}
        if booklet_summary is not None:
            manifest["booklet_check"] = booklet_summary
        manifest_path = out_dir / f"{stem}_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        package = out_dir / f"{stem}_package.zip"
        write_zip([path for path, _, _ in entries] + [manifest_path], package)
        manifest["package"] = file_entry(package, "package")
        manifest["manifest_file"] = manifest_path.name
        _check_package(out_dir, manifest)
    return manifest
