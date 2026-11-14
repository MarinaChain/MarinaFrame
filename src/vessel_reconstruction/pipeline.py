"""Transactional drawing -> observed sections -> CAD -> immutable evidence."""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import stat
import time
from pathlib import Path

from .draft import DRAFT_EXPORT_NAMES, check_draft
from .artifacts import GEOMETRY_NAMES
from .errors import GeometryError
from .provenance import digest_file, digest_object, snapshot_implementation, environment_record, write_json
from .resources import DEFAULT_POLICY, ResourceLimitError, source_extension, validate_sources
from .run_record import SCHEMA_VERSION, TABLE_READING_FILE, observed_geometry, seal_run, verify_run
from .schema import MAX_SPEC_BYTES, TABLE_VISION_MODE, gap, load_bounded_json, loads_bounded_json, validate_spec
from .transaction import RunPublicationError, RunTransaction, quarantine_interrupted

# Byte budget of the read-table record captured into a table run.
MAX_TABLE_READING_BYTES = 8 * 1024 * 1024


# Lazy wrappers keep verification and invalid-input rejection free of native CAD
# imports. They remain public module seams for embedding and fault-injection tests.
def build_hull(*args, **kwargs):
    from .geometry import build_hull as build
    return build(*args, **kwargs)


def _complexity_fit_warnings(normalized: list[dict]) -> list[dict]:
    """One warning per section that a draft simplified beyond the requested CAD bound."""
    warnings = []
    for section in normalized:
        record = section["cad_approximation"]
        fit = record.get("complexity_fit")
        if fit is None or record["maximum_half_breadth_deviation_m"] <= fit["requested_maximum_deviation_m"]:
            continue
        warnings.append(gap(
            "draft_simplified_curve",
            f"Curve simplified for the CAD knot limit: maximum half-breadth deviation "
            f"{record['maximum_half_breadth_deviation_m'] * 1000:.1f} mm from the traced curve "
            f"(requested bound {fit['requested_maximum_deviation_m'] * 1000:g} mm).",
            section["id"], severity="warning"))
    return warnings


def hull_fairing_enabled() -> bool:
    from .fairing import enabled
    return enabled()


def _faired_sections(sections: list[dict], result: dict) -> list[dict]:
    """Sections from the faired hull surface, or the sections as given when the fit fails.

    The fairing report (without the input points) goes to the run diagnostics; its check
    items (points moved beyond their tolerance, with the distance) become warnings.
    """
    from .fairing import METHOD, fair_sections
    try:
        faired, report = fair_sections(sections)
    except Exception as exc:  # happy path: a fit failure keeps the current hull
        faired, report = sections, {"method": METHOD, "applied": False, "reason": f"fit failed ({type(exc).__name__})",
                                    "check_items": [gap("fairing_fallback", f"Hull fairing failed ({type(exc).__name__}); "
                                                        "the hull goes through the sections as observed.", severity="warning")]}
    result.setdefault("diagnostics", {})["hull_fairing"] = {key: value for key, value in report.items()
                                                          if key != "check_items"}
    result["gaps"].extend(report["check_items"])
    return faired


def build_region_hull(*args, **kwargs):
    from .geometry import build_region_hull as build
    return build(*args, **kwargs)


def metrics_for(*args, **kwargs):
    from .geometry import metrics_for as metrics
    return metrics(*args, **kwargs)


def export_geometry(*args, **kwargs):
    from .geometry import export_geometry as export
    return export(*args, **kwargs)


def _make_source_preview(source: dict, out: Path, spec: dict) -> None:
    """Display derivative of a metadata-preflighted immutable source snapshot."""
    source_path = out / source["file"]
    try:
        from PIL import Image
        settings = spec["source" if source["id"] == "source-1" else "station_reference"]
        if source_path.suffix.lower() == ".pdf":
            import fitz
            with fitz.open(source_path) as document:
                page = document[settings.get("page_index", 0)]
                dpi = settings.get("render_dpi", 144)
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        else:
            with Image.open(source_path) as opened:
                if source_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and max(opened.size) <= 3000:
                    return
                image = opened.convert("RGB")
        original = list(image.size)
        image.thumbnail((3000, 3000))
        name = source_path.stem + "_preview.png"
        image.save(out / name)
        source.update(preview_file=name, preview_scale_x=image.width / original[0],
                      preview_scale_y=image.height / original[1], original_pixel_size=original,
                      preview_note="Display-only derivative; geometry uses the preflighted original snapshot.")
    except Exception:
        # A preview is optional. Its presence, bytes and source binding are
        # nevertheless included in the immutable manifest when it exists.
        (out / (source_path.stem + "_preview.png")).unlink(missing_ok=True)
        source["preview_note"] = "No display preview available; original source retained."


def _new_record(vessel_id: str, export_cad: bool) -> dict:
    return {"schema_version": SCHEMA_VERSION, "record_kind": "immutable_inference_record", "run_id": "",
            "vessel_id": vessel_id[:256] or "unnamed", "status": "blocked",
            "method": "raster_curve_tracking+section_loft", "input_mode": None,
            "review": {"state": "unreviewed", "engineering_approved": False},
            "sources": [], "parts": [], "sections": [], "normalized_sections": [], "gaps": [],
            "assumptions": [], "metrics": {}, "exports": {}, "requested_exports": export_cad,
            "timing_seconds": 0.0, "provenance": {"input_spec_sha256": digest_object(None),
                "replay_spec_sha256": digest_object(None), "submitted_spec_sha256": None,
                "implementation_sha256": None,
                "implementation_snapshot": {"status": "unavailable", "files_sha256": {}}}}


def has_regions(sections: list[dict]) -> bool:
    """True when any observed section is a multi-piece (region) station."""
    return any("regions" in section for section in sections)


def region_summary(report: dict) -> dict:
    """Run-level record of a region loft: runs, solids, volumes and bounds, without stations."""
    return {key: value for key, value in report.items() if key != "stations"}


def _has_block(result):
    return any(item.get("severity", "blocking") == "blocking" for item in result["gaps"])


def _copy_source(source_path: Path, stage: Path, role: str) -> tuple[str, str]:
    """Bound bytes while copying; hash and later inspect only the copied bytes."""
    from .platform_files import require_windows_disk_path
    require_windows_disk_path(source_path)
    limit = DEFAULT_POLICY.source_bytes if role == "source" else DEFAULT_POLICY.reference_bytes
    descriptor = os.open(source_path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ResourceLimitError("resource_limit", f"{role} exceeds the configured ordinary-file byte budget.")
        extension = source_extension(stream.read(16))
        stream.seek(0)
        name = role + extension
        destination = stage / name
        written = 0
        try:
            with destination.open("xb") as target:
                while block := stream.read(min(1024 * 1024, limit + 1 - written)):
                    written += len(block)
                    if written > limit:
                        raise ResourceLimitError("resource_limit", f"{role} changed or exceeded its byte budget during capture.")
                    target.write(block)
                target.flush()
                os.fsync(target.fileno())
            if written != info.st_size:
                raise ResourceLimitError("source_changed", "Source size changed during evidence capture; retry with a stable input file.")
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return name, digest_file(destination)


def _capture_table_reading(input_spec: dict, replay_spec: dict, base_dir: Path, stage: Path, result: dict):
    """Copy the read-table record into the run and bind it by hash.

    The record holds every provider receipt; the run identity includes its
    hash, so a different reading is a different run.
    """
    settings = input_spec.get("table_reading")
    if not isinstance(settings, dict) or not isinstance(settings.get("file"), str):
        result["gaps"].append(gap("table_reading_missing", "Run table_vision prepare and marinaframe read-table, then declare table_reading.file."))
        return
    try:
        descriptor = os.open(base_dir / settings["file"], os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("The table reading record must be an ordinary file.")
            raw = stream.read(MAX_TABLE_READING_BYTES + 1)
        if len(raw) > MAX_TABLE_READING_BYTES:
            raise ValueError("The table reading record exceeds its byte budget.")
        with (stage / TABLE_READING_FILE).open("xb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
    except (OSError, ValueError):
        result["gaps"].append(gap("table_reading_missing", "The table reading record could not be captured."))
        return
    digest = hashlib.sha256(raw).hexdigest()
    if settings.get("sha256") is not None and settings["sha256"] != digest:
        result["gaps"].append(gap("table_reading_hash_mismatch", "Captured table reading bytes differ from their declared hash."))
    replay_spec["table_reading"] = {**settings, "file": TABLE_READING_FILE, "sha256": digest}
    result["provenance"]["table_reading"] = {"file": TABLE_READING_FILE, "sha256": digest}


def _discard_geometry(stage: Path, result: dict):
    result.update(exports={}, parts=[], metrics={}, normalized_sections=[])
    result.pop("export_results", None)
    for name in GEOMETRY_NAMES:
        (stage / name).unlink(missing_ok=True)
    # Observations are evidence, but cannot be asserted when their required
    # artifact was not successfully written.
    if not (stage / "extracted_sections.json").is_file():
        result["sections"] = []
        result["provenance"].pop("extracted_geometry_sha256", None)
        result["provenance"].pop("extraction_complete", None)


def _tag_draft_exports(stage: Path, exports: dict):
    """Rename the CAD exports of a draft, so each file name says "draft"."""
    for key, name in DRAFT_EXPORT_NAMES.items():
        if key in exports:
            os.replace(stage / exports[key], stage / name)
            exports[key] = name


def _externalize_section_diagnostics(stage: Path, result: dict):
    """Keep section diagnostics in the already retained extraction artifact."""
    diagnostics = result.get("diagnostics")
    path = stage / "extracted_sections.json"
    if not isinstance(diagnostics, dict) or "sections" not in diagnostics or not path.is_file():
        return
    extraction = load_bounded_json(path, max_bytes=64 * 1024**2, max_depth=40, max_nodes=3_000_000)
    if extraction.get("diagnostics", {}).get("sections") != diagnostics["sections"]:
        raise ValueError("Section diagnostics disagree with the extraction artifact.")
    diagnostics.pop("sections")
    diagnostics["sections_artifact"] = {"file": path.name, "sha256": digest_file(path)}


def _publish(transaction, result, input_spec, replay_spec, started):
    stage = transaction.stage
    if result["status"] != "review_required" or _has_block(result):
        if result["status"] == "review_required":
            result["status"] = "failed"
        _discard_geometry(stage, result)
    write_json(stage / "input_spec.json", input_spec)
    write_json(stage / "replay_spec.json", replay_spec)
    result["provenance"]["input_spec_sha256"] = digest_object(input_spec)
    result["provenance"]["replay_spec_sha256"] = digest_object(replay_spec)
    result["timing_seconds"] = time.perf_counter() - started
    transaction.checkpoint("sealing")
    # The reservation keeps recovery discoverable after removing the private
    # checkpoint. Only committed files appear in the manifest inventory.
    (stage / "transaction.json").unlink()
    _externalize_section_diagnostics(stage, result)
    seal_run(stage, result, writer=write_json)
    verification = verify_run(stage)
    if not verification["valid"]:
        message = next((check.get("message", check.get("kind")) for check in verification["checks"] if not check["valid"]), "Unknown verification failure")
        raise RunPublicationError(f"Required evidence did not verify before publication: {message}")
    transaction.publish()
    return result


def _capture_spec(spec_path, transaction, stage, result, phase):
    input_spec = None
    try:
        transaction.checkpoint(phase[0])
        from .platform_files import require_windows_disk_path
        require_windows_disk_path(Path(spec_path))
        descriptor = os.open(spec_path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Specification must be an ordinary file.")
            raw = stream.read(MAX_SPEC_BYTES + 1)
        if len(raw) > MAX_SPEC_BYTES:
            raise ValueError("Specification byte budget exceeded.")
        (stage / "submitted_spec.json").write_bytes(raw)
        result["provenance"]["submitted_spec_sha256"] = hashlib.sha256(raw).hexdigest()
        input_spec = loads_bounded_json(raw)
    except (OSError, ValueError) as exc:
        result["gaps"].append(gap("invalid_spec", f"Drawing specification is unreadable, malformed, or exceeds limits ({type(exc).__name__})."))
        if result["provenance"]["submitted_spec_sha256"] is None:
            result["provenance"]["recovery_identity"] = {"kind": "uncaptured_input", "transaction_id": transaction.token}
    return input_spec


def _validate_input(input_spec, spec_path, transaction, result, phase, replay):
    replay_spec = None
    phase[0] = "schema_validation"
    transaction.checkpoint(phase[0])
    if input_spec is not None:
        result["gaps"].extend(validate_spec(input_spec, spec_path.parent))
    if isinstance(input_spec, dict):
        replay_spec = copy.deepcopy(input_spec)
        replay[0] = replay_spec
        if isinstance(input_spec.get("vessel_id"), str) and input_spec["vessel_id"].strip():
            result["vessel_id"] = input_spec["vessel_id"][:256]
        if check_draft(input_spec.get("draft")):
            # A best-effort draft: the record lists its open guesses and
            # its CAD exports carry the draft tag in their file names.
            result["draft"] = copy.deepcopy(input_spec["draft"])
        mode = input_spec.get("input_mode", "calibrated_section_curves")
        result["input_mode"] = mode if isinstance(mode, str) and mode in ("calibrated_section_curves", TABLE_VISION_MODE) else None
    else:
        if not result["gaps"]:
            result["gaps"].append(gap("invalid_spec", "The drawing specification must be a JSON object."))
    return replay_spec


def _capture_implementation(transaction, stage, result, phase):
    phase[0] = "implementation_capture"
    transaction.checkpoint(phase[0])
    try:
        snapshot = snapshot_implementation(stage)
    except Exception:
        shutil.rmtree(stage / "implementation_source", ignore_errors=False)
        raise
    snapshot["status"] = "complete"
    result["provenance"].update(implementation_snapshot=snapshot,
                                implementation_sha256=snapshot["implementation_sha256"],
                                environment=environment_record(),
                                input_geometry_access="Drawing pixels plus disclosed view/table regions, stations, and calibration only.")


def _capture_sources(input_spec, replay_spec, spec_path, transaction, stage, result, phase):
    phase[0] = "source_capture"
    transaction.checkpoint(phase[0])
    if isinstance(input_spec, dict):
        for role, identifier in (("source", "source-1"), ("station_reference", "source-2")):
            settings = input_spec.get(role)
            if not isinstance(settings, dict) or not isinstance(settings.get("file"), str) or not settings["file"] or "\x00" in settings["file"]:
                continue
            source_path = spec_path.parent / settings["file"]
            try:
                name, source_hash = _copy_source(source_path, stage, role)
            except ResourceLimitError as exc:
                result["gaps"].append(gap(exc.kind, str(exc)))
                continue
            except (OSError, ValueError):
                result["gaps"].append(gap("source_missing", f"The {role} evidence could not be captured."))
                continue
            supplied_hash = settings.get("sha256")
            if supplied_hash is not None and supplied_hash != source_hash:
                result["gaps"].append(gap("source_hash_mismatch" if role == "source" else "station_reference_hash_mismatch", "Captured source bytes differ from their declared hash."))
            source = {"id": identifier, "file": name, "original_file": source_path.name, "sha256": source_hash,
                      "url": settings.get("url"), "license": settings.get("license"),
                      "role": "drawing_evidence" if role == "source" else "station_coordinate_reference"}
            if role == "station_reference":
                source.update(roi_px=settings.get("roi_px"), description=settings.get("description"))
            result["sources"].append(source)
            replay_spec[role]["file"], replay_spec[role]["sha256"] = name, source_hash
        if result["input_mode"] == TABLE_VISION_MODE:
            _capture_table_reading(input_spec, replay_spec, spec_path.parent, stage, result)
        result["assumptions"] = [
            {"id": "symmetry", "status": "review_required", "description": input_spec.get("symmetry_evidence") if isinstance(input_spec.get("symmetry_evidence"), str) else "Symmetry unresolved."},
            {"id": "station_interpolation", "status": "review_required", "description": "Ruled interpolation between observed sections; intervening geometry is a modeling assumption."},
            {"id": "end_caps", "status": "review_required", "description": "Flat mathematical terminal caps; no unsupported bow or stern extension."},
            {"id": "upper_closure", "status": "review_required", "description": "The top measurement closes the envelope; no steel deck is asserted."},
            {"id": "lower_closure", "status": "review_required", "description": "A nonzero lowest breadth closes with a flat segment; geometry below a cropped view is unknown."},
            {"id": "condition", "status": "unverified", "description": "Supplied drawing evidence, not independently verified present-day vessel condition."},
        ]
        declared = input_spec.get("sections") if isinstance(input_spec.get("sections"), list) else []
        if any(isinstance(section, dict) and "pieces" in section for section in declared):
            result["assumptions"].append({"id": "region_matching", "status": "review_required", "description":
                "Regions of multi-piece stations are lofted only to the best-overlapping region of the same kind on the neighbouring station; an unmatched region ends with a flat closure."})


def _preflight_sources(replay_spec, transaction, stage, result, phase):
    phase[0] = "resource_preflight"
    transaction.checkpoint(phase[0])
    # Inspect captured bytes, so original file mutation cannot bypass
    # the budgets or change inference after this check.
    result["provenance"]["resource_preflight"] = validate_sources(replay_spec, stage)
    for source in result["sources"]:
        _make_source_preview(source, stage, replay_spec)


def _bind_section_evidence(sections, result, assistance):
    for section in sections:
        section.setdefault("evidence", {}).update(source_id="source-1", source_sha256=result["sources"][0]["sha256"],
            assistance=assistance)
        if len(result["sources"]) > 1:
            section["evidence"]["station_source_id"] = "source-2"


def _record_extraction(stage, extracted, result):
    extracted["sections"] = result["sections"]
    write_json(stage / "extracted_sections.json", extracted)
    result["provenance"].update(extraction_complete=True, extracted_geometry_sha256=digest_object([
        observed_geometry(section) for section in result["sections"]]))


def _extract_sections(input_spec, replay_spec, transaction, stage, result, phase):
    phase[0] = "section_extraction"
    transaction.checkpoint(phase[0])
    if result["input_mode"] == TABLE_VISION_MODE:
        from .table_vision import extract_table_sections
        extracted = extract_table_sections(replay_spec, stage)
        assistance = ("Explicit station, waterline and cell regions; half-breadths are vision-model "
                      "transcriptions of the cell crops, parsed by a strict notation parser.")
    else:
        from .ingest import extract_sections
        extracted = extract_sections(replay_spec, stage)
        assistance = "Explicit station/pixel regions and dimensional calibration; half-breadths measured from the source pixels."
    result["sections"] = extracted.get("sections", [])
    result["gaps"].extend(extracted.get("gaps", []))
    result["diagnostics"] = extracted.get("diagnostics", {})
    result["method"] = extracted.get("method", "raster_curve_tracking") + "+section_loft"
    found = {section["id"] for section in result["sections"]}
    for required in input_spec["sections"]:
        if required["id"] not in found:
            result["gaps"].append(gap("unresolved_required_section", "A required drawing view did not yield a supported contour; missing evidence is not interpolated.", required["id"]))
    if "draft" in result:
        from .draft import prepare_draft_sections
        result["sections"], repairs = prepare_draft_sections(result["sections"], input_spec["sections"])
        result["gaps"] = [{**item, "severity": "warning"} for item in result["gaps"]]
        result["gaps"].extend(repairs)
        for section in result["sections"]:
            if any("Draft uses unreliable" in warning for warning in section.get("warnings", [])):
                result["gaps"].append(gap("draft_unreliable_curve", "Using fragmented curve; re-trace this section, pick another candidate, or accept draft.", section["id"], severity="warning"))
        # Cross-station fairness: name the section that breaks the hull
        # (warnings only). Interpolated sections come from their
        # neighbours, so they are not evidence for or against them.
        from .fairness import check_fairness, fairness_warnings
        fairness = check_fairness([s for s in result["sections"] if s.get("source_label") != "interpolated"])
        result.setdefault("diagnostics", {})["fairness"] = fairness
        result["gaps"].extend(fairness_warnings(fairness))
    # Hull fairing (setting, off by default): sections taken from one fair surface
    # fitted to all stations at once. The sections as observed are kept for the
    # fallback below.
    observed_sections = None
    if hull_fairing_enabled() and result["sections"] and not has_regions(result["sections"]):
        observed_sections = result["sections"]
        result["sections"] = _faired_sections(observed_sections, result)

    from .source_record import finish_sections
    finish_sections(result["sections"], faired=observed_sections is not None and result["sections"] is not observed_sections)
    _bind_section_evidence(result["sections"], result, assistance)
    _record_extraction(stage, extracted, result)
    return extracted, assistance, observed_sections


def _construct_hull(input_spec, transaction, stage, result, phase, extracted, assistance, observed_sections):
    phase[0] = "cad_construction"
    transaction.checkpoint(phase[0])
    region_report = None
    regions = has_regions(result["sections"])
    if regions:
        # Multi-piece stations: one closed solid per matched region
        # run; the compound's solids meet on shared faces.
        shape, region_report = build_region_hull(result["sections"])
        stations = {station["id"]: station for station in region_report["stations"]}
        normalized = [{**section, "cad_station": stations[section["id"]]}
                      for section in sorted(result["sections"], key=lambda s: s["x_m"])]
    else:
        # A draft simplifies over-complex curves to fit the CAD
        # limits; a strict run still rejects them.
        try:
            shape, normalized = build_hull(result["sections"], fit_complexity="draft" in result)
        except GeometryError as exc:
            if observed_sections is None:
                raise
            # Happy path: a faired hull that cannot be built falls back to the
            # hull through the sections as observed, with a check item.
            result["sections"] = observed_sections
            from .source_record import finish_sections
            finish_sections(result["sections"])
            _bind_section_evidence(result["sections"], result, assistance)
            result["gaps"].append(gap("fairing_fallback", f"The faired hull could not be built ({exc}); "
                                      "the hull goes through the sections as observed.", severity="warning"))
            result["diagnostics"]["hull_fairing"]["applied"] = False
            _record_extraction(stage, extracted, result)
            shape, normalized = build_hull(result["sections"], fit_complexity="draft" in result)
        result["gaps"].extend(_complexity_fit_warnings(normalized))
    provisional = metrics_for(shape)
    constraints = input_spec.get("constraints", {})
    tolerance = constraints.get("relative_tolerance", .03)
    for key in ("length_m", "beam_m", "depth_m"):
        if key in constraints and abs(provisional[key] - constraints[key]) / constraints[key] > tolerance:
            result["gaps"].append(gap("dimension_conflict", f"Reconstructed {key} conflicts with the independently declared dimension.", severity="warning" if "draft" in result else "blocking"))
    return shape, normalized, regions, region_report


def _export_hull(input_spec, transaction, stage, result, phase, shape, normalized, regions, region_report, export_cad):
    phase[0] = "geometry_export_and_reload"
    transaction.checkpoint(phase[0])
    # A single-solid run calls the export seam exactly as before.
    region_export = {"expected_solids": region_report["solid_count"]} if regions else {}
    exports, metrics = export_geometry(shape, stage, export_cad=export_cad, **region_export)
    export_results = metrics.pop("export_results", None)
    if export_results is not None:
        result["export_results"] = export_results
        for format_name, outcome in export_results.items():
            if outcome["status"] == "failed":
                result["gaps"].append(gap("export_failed", f"{format_name.upper()} export failed: {outcome['reason']}", severity="warning"))
    if "draft" in result:
        _tag_draft_exports(stage, exports)
    from .geometry import approximation_summary
    metrics.update(section_count=len(normalized), minimum_observation_coverage=min(s.get("coverage", 0) for s in result["sections"]))
    if regions:
        metrics["region_loft"] = region_summary(region_report)
    else:
        metrics["geometry_approximation"] = approximation_summary(normalized)
    phase[0] = "required_cad_evidence"
    transaction.checkpoint(phase[0])
    write_json(stage / "cad_sections.json", normalized)
    result["normalized_sections"] = normalized
    result["exports"], result["metrics"] = exports, metrics
    result["parts"] = [{"id": "hull", "name": "Reconstructed hull envelope", "kind": "hull_envelope",
        "source_ids": [s["id"] for s in result["sources"]], "section_ids": [s["id"] for s in result["sections"]],
        "status": "review_required", "mesh_file": "mesh.json",
        "unresolved_properties": ["shell_thickness", "material", "internal_structure", "current_as_built_condition"]}]
    # This status is private until full record validation,
    # required artifact hashing, and atomic publication finish.
    result["status"] = "review_required"

def _publish_terminal_run(transaction, result, input_spec, replay_spec, started):
    try:
        try:
            return _publish(transaction, result, input_spec, replay_spec, started)
        except Exception as exc:
            if transaction.published:
                raise RunPublicationError("Atomic publication occurred, but directory durability could not be confirmed; inspect the terminal run before retrying.") from exc
            result["status"] = "failed"
            result["provenance"]["failure_stage"] = "evidence_commit"
            result["gaps"].append(gap("evidence_commit_failed", f"Required evidence could not be committed ({type(exc).__name__}); geometry was withdrawn."))
            try:
                return _publish(transaction, result, input_spec, replay_spec, started)
            except Exception as final_exc:
                raise RunPublicationError("The run could not publish a complete terminal record. Private staging is retained for interruption recovery; no result is reported as successful.") from final_exc
    finally:
        transaction.close()



def reconstruct(spec_path: str | Path, output_dir: str | Path, *, export_cad: bool = True) -> dict:
    """Build in exclusive private staging; publish one complete terminal run.

    The destination must not already exist, even when empty. A storage failure
    that prevents writing a complete failure record raises RunPublicationError;
    unpublished staging remains discoverable to recovery and is never served.
    """
    if type(export_cad) is not bool:
        raise ValueError("export_cad must be a boolean.")
    started, spec_path = time.perf_counter(), Path(spec_path).absolute()
    transaction = RunTransaction(output_dir)
    stage = transaction.stage
    result = _new_record(spec_path.parent.name, export_cad)
    input_spec = replay_spec = None
    # Keep the current phase and replay available if a stage raises.
    phase, replay = ["input_capture"], [None]
    try:
        input_spec = _capture_spec(spec_path, transaction, stage, result, phase)
        replay_spec = _validate_input(input_spec, spec_path, transaction, result, phase, replay)
        _capture_implementation(transaction, stage, result, phase)
        _capture_sources(input_spec, replay_spec, spec_path, transaction, stage, result, phase)
        if not _has_block(result):
            _preflight_sources(replay_spec, transaction, stage, result, phase)
            extracted, assistance, observed_sections = _extract_sections(
                input_spec, replay_spec, transaction, stage, result, phase)
            if not _has_block(result):
                shape, normalized, regions, region_report = _construct_hull(
                    input_spec, transaction, stage, result, phase, extracted, assistance, observed_sections)
                if not _has_block(result):
                    _export_hull(input_spec, transaction, stage, result, phase, shape, normalized,
                                 regions, region_report, export_cad)
    except ResourceLimitError as exc:
        result["status"] = "blocked"
        result["gaps"].append(gap(exc.kind, str(exc)))
    except GeometryError as exc:
        result["status"] = "blocked"
        result["gaps"].append(gap("invalid_geometry", str(exc)))
    except (KeyboardInterrupt, SystemExit):
        result["status"] = "cancelled"
        result["gaps"].append(gap("cancelled", "Processing was cancelled before publication."))
    except Exception as exc:
        result["status"] = "failed"
        result["provenance"]["failure_stage"] = phase[0]
        result["gaps"].append(gap("processing_error", f"Processing stopped at {phase[0]} ({type(exc).__name__}); no geometry was published."))
    replay_spec = replay[0]
    return _publish_terminal_run(transaction, result, input_spec, replay_spec, started)


def recover_interrupted_run(output_dir: str | Path, *, status="interrupted", reason=None) -> dict:
    """Recover only an orphaned transaction and publish export-free evidence."""
    if status not in ("interrupted", "cancelled", "failed"):
        raise ValueError("Recovery requires interrupted, cancelled, or failed terminal status.")
    recovered = quarantine_interrupted(output_dir)
    if not recovered["recovered"]:
        return recovered
    started = time.perf_counter()
    transaction = RunTransaction(output_dir)
    result = _new_record(Path(output_dir).name, False)
    result["status"] = status
    result["gaps"] = [gap(status, reason if isinstance(reason, str) and len(reason) <= 1024 else "The worker stopped before atomic publication; unpublished geometry was removed.")]
    result["provenance"]["recovery_identity"] = {"kind": "interrupted_transaction", "transaction_id": transaction.token,
                                                  "last_phase": recovered.get("last_phase", "unknown")}
    try:
        _publish(transaction, result, None, None, started)
    finally:
        transaction.close()
    return {**recovered, "status": status, "run_id": result["run_id"], "published": True}
