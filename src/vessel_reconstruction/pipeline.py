"""Transactional drawing -> observed sections -> CAD -> immutable evidence."""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import stat
import time
from pathlib import Path

from .errors import GeometryError
from .provenance import digest_file, digest_object, snapshot_implementation, environment_record, write_json
from .resources import DEFAULT_POLICY, ResourceLimitError, source_extension, validate_sources
from .run_record import SCHEMA_VERSION, seal_run, verify_run
from .schema import MAX_SPEC_BYTES, gap, loads_bounded_json, validate_spec
from .transaction import RunPublicationError, RunTransaction, quarantine_interrupted


# Lazy wrappers keep verification and invalid-input rejection free of native CAD
# imports. They remain public module seams for embedding and fault-injection tests.
def build_hull(*args, **kwargs):
    from .geometry import build_hull as build
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


def _has_block(result):
    return any(item.get("severity", "blocking") == "blocking" for item in result["gaps"])


def _copy_source(source_path: Path, stage: Path, role: str) -> tuple[str, str]:
    """Bound bytes while copying; hash and later inspect only the copied bytes."""
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


def _discard_geometry(stage: Path, result: dict):
    result.update(exports={}, parts=[], metrics={}, normalized_sections=[])
    for name in ("mesh.json", "model.step", "model.stl", "cad_sections.json"):
        (stage / name).unlink(missing_ok=True)
    # Observations are evidence, but cannot be asserted when their required
    # artifact was not successfully written.
    if not (stage / "extracted_sections.json").is_file():
        result["sections"] = []
        result["provenance"].pop("extracted_geometry_sha256", None)
        result["provenance"].pop("extraction_complete", None)


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
    seal_run(stage, result, writer=write_json)
    verification = verify_run(stage)
    if not verification["valid"]:
        message = next((check.get("message", check.get("kind")) for check in verification["checks"] if not check["valid"]), "Unknown verification failure")
        raise RunPublicationError(f"Required evidence did not verify before publication: {message}")
    transaction.publish()
    return result


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
    phase = "input_capture"
    try:
        try:
            transaction.checkpoint(phase)
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
        phase = "schema_validation"
        transaction.checkpoint(phase)
        if input_spec is not None:
            result["gaps"].extend(validate_spec(input_spec, spec_path.parent))
        if isinstance(input_spec, dict):
            replay_spec = copy.deepcopy(input_spec)
            if isinstance(input_spec.get("vessel_id"), str) and input_spec["vessel_id"].strip():
                result["vessel_id"] = input_spec["vessel_id"][:256]
            mode = input_spec.get("input_mode", "calibrated_section_curves")
            result["input_mode"] = mode if isinstance(mode, str) and mode in ("calibrated_section_curves", "offset_table_ocr") else None
        else:
            if not result["gaps"]:
                result["gaps"].append(gap("invalid_spec", "The drawing specification must be a JSON object."))
        phase = "implementation_capture"
        transaction.checkpoint(phase)
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
        phase = "source_capture"
        transaction.checkpoint(phase)
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
            result["assumptions"] = [
                {"id": "symmetry", "status": "review_required", "description": input_spec.get("symmetry_evidence") if isinstance(input_spec.get("symmetry_evidence"), str) else "Symmetry unresolved."},
                {"id": "station_interpolation", "status": "review_required", "description": "Ruled interpolation between observed sections; intervening geometry is a modeling assumption."},
                {"id": "end_caps", "status": "review_required", "description": "Flat mathematical terminal caps; no unsupported bow or stern extension."},
                {"id": "upper_closure", "status": "review_required", "description": "The top measurement closes the envelope; no steel deck is asserted."},
                {"id": "lower_closure", "status": "review_required", "description": "A nonzero lowest breadth closes with a flat segment; geometry below a cropped view is unknown."},
                {"id": "condition", "status": "unverified", "description": "Supplied drawing evidence, not independently verified present-day vessel condition."},
            ]
        if not _has_block(result):
            phase = "resource_preflight"
            transaction.checkpoint(phase)
            # Inspect captured bytes, so original file mutation cannot bypass
            # the budgets or change inference after this check.
            result["provenance"]["resource_preflight"] = validate_sources(replay_spec, stage)
            for source in result["sources"]:
                _make_source_preview(source, stage, replay_spec)
            phase = "section_extraction"
            transaction.checkpoint(phase)
            if result["input_mode"] == "offset_table_ocr":
                from .table_ingest import extract_table_sections
                extracted = extract_table_sections(replay_spec, stage)
            else:
                from .ingest import extract_sections
                extracted = extract_sections(replay_spec, stage)
            result["sections"] = extracted.get("sections", [])
            result["gaps"].extend(extracted.get("gaps", []))
            result["diagnostics"] = extracted.get("diagnostics", {})
            result["method"] = extracted.get("method", "raster_curve_tracking") + "+section_loft"
            found = {section["id"] for section in result["sections"]}
            for required in input_spec["sections"]:
                if required["id"] not in found:
                    result["gaps"].append(gap("unresolved_required_section", "A required drawing view did not yield a supported contour; missing evidence is not interpolated.", required["id"]))
            for section in result["sections"]:
                section.setdefault("evidence", {}).update(source_id="source-1", source_sha256=result["sources"][0]["sha256"],
                    assistance="Explicit station/pixel regions and dimensional calibration; half-breadths measured from the source pixels.")
                if len(result["sources"]) > 1:
                    section["evidence"]["station_source_id"] = "source-2"
            extracted["sections"] = result["sections"]
            write_json(stage / "extracted_sections.json", extracted)
            result["provenance"].update(extraction_complete=True, extracted_geometry_sha256=digest_object([
                {key: section[key] for key in ("id", "x_m", "points_yz_m")} for section in result["sections"]]))
            if not _has_block(result):
                phase = "cad_construction"
                transaction.checkpoint(phase)
                shape, normalized = build_hull(result["sections"])
                provisional = metrics_for(shape)
                constraints = input_spec.get("constraints", {})
                tolerance = constraints.get("relative_tolerance", .03)
                for key in ("length_m", "beam_m", "depth_m"):
                    if key in constraints and abs(provisional[key] - constraints[key]) / constraints[key] > tolerance:
                        result["gaps"].append(gap("dimension_conflict", f"Reconstructed {key} conflicts with the independently declared dimension."))
                if not _has_block(result):
                    phase = "geometry_export_and_reload"
                    transaction.checkpoint(phase)
                    exports, metrics = export_geometry(shape, stage, export_cad=export_cad)
                    from .geometry import approximation_summary
                    metrics.update(section_count=len(normalized), minimum_observation_coverage=min(s.get("coverage", 0) for s in result["sections"]),
                                   geometry_approximation=approximation_summary(normalized))
                    phase = "required_cad_evidence"
                    transaction.checkpoint(phase)
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
        result["provenance"]["failure_stage"] = phase
        result["gaps"].append(gap("processing_error", f"Processing stopped at {phase} ({type(exc).__name__}); no geometry was published."))
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
