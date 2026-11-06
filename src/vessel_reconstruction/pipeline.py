"""Complete drawing -> observed sections -> CAD -> evidence workflow."""
from __future__ import annotations

import json
import math
import shutil
import time
from pathlib import Path

from .geometry import GeometryError, build_hull, export_geometry, metrics_for
from .provenance import digest_file, digest_object, implementation_hash, snapshot_implementation, environment_record, write_json
from .schema import gap, validate_spec


def _make_source_preview(source: dict, out: Path, spec: dict) -> None:
    """A display-only derivative. Geometry always uses the original snapshot."""
    source_path = out / source["file"]
    try:
        from PIL import Image
        if source_path.suffix.lower() == ".pdf":
            import fitz
            with fitz.open(source_path) as doc:
                settings = spec.get("source", {})
                page = doc[int(settings.get("page_index", 0))]
                dpi = float(settings.get("render_dpi", 144))
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                im = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        elif source_path.suffix.lower() in {".tif", ".tiff", ".bmp", ".png", ".jpg", ".jpeg", ".webp"}:
            with Image.open(source_path) as opened:
                if source_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and max(opened.size) <= 3000:
                    return
                im = opened.convert("RGB")
        else:
            return
        original = list(im.size)
        im.thumbnail((3000, 3000))
        preview_name = source_path.stem + "_preview.png"
        im.save(out / preview_name)
        source["preview_file"] = preview_name
        source["preview_scale_x"] = im.width / original[0]
        source["preview_scale_y"] = im.height / original[1]
        source["original_pixel_size"] = original
        source["preview_note"] = "Display-only resized derivative; all observations and hashes refer to original source bytes."
    except Exception:
        # Display failure never changes engineering evidence or inferred geometry.
        source["preview_note"] = "No display preview available; original source retained."


def reconstruct(spec_path: str | Path, output_dir: str | Path, *, export_cad: bool = True) -> dict:
    started = time.perf_counter()
    spec_path, out = Path(spec_path).resolve(), Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "result.json").exists():
        raise FileExistsError(f"Run already exists at {out}; choose a new output directory to preserve evidence.")
    result = {
        "schema_version": "1.0", "run_id": "", "vessel_id": spec_path.parent.name,
        "status": "blocked", "method": "raster_curve_tracking+section_loft",
        "review": {"state": "unreviewed", "engineering_approved": False},
        "sources": [], "parts": [], "sections": [], "gaps": [], "assumptions": [],
        "metrics": {}, "exports": {}, "provenance": {},
    }
    try:
        def reject_nonfinite(value):
            raise ValueError(f"Non-finite JSON number {value} is not permitted.")
        def finite_float(token):
            value = float(token)
            if not math.isfinite(value):
                raise ValueError("JSON numeric overflow is not permitted.")
            return value
        spec = json.loads(spec_path.read_text(encoding="utf-8"), parse_constant=reject_nonfinite, parse_float=finite_float)
        if not isinstance(spec, dict):
            raise ValueError("The drawing specification must be a JSON object.")
    except (OSError, ValueError) as exc:
        result["gaps"] = [gap("invalid_spec", f"The drawing specification could not be read: {type(exc).__name__}.")]
        result["timing_seconds"] = time.perf_counter() - started
        write_json(out / "result.json", result)
        return result
    result["vessel_id"] = str(spec.get("vessel_id", spec_path.parent.name))
    result["gaps"] = validate_spec(spec, spec_path.parent)
    spec_hash = digest_object(spec)
    write_json(out / "input_spec.json", spec)
    result["provenance"] = {
        "input_spec_sha256": spec_hash, "implementation_sha256": implementation_hash(),
        "implementation_snapshot": snapshot_implementation(out),
        "environment": environment_record(), "input_geometry_access": "Drawing pixels plus disclosed view or table-cell regions, station coordinates, and dimensional calibration only.",
    }
    result["input_mode"] = spec.get("input_mode", "calibrated_section_curves")
    source = spec.get("source", {})
    if isinstance(source, dict) and isinstance(source.get("file"), str):
        source_path = (spec_path.parent / source["file"]).resolve()
        if source_path.is_file():
            source_hash = digest_file(source_path)
            supplied_hash = source.get("sha256")
            if supplied_hash and supplied_hash != source_hash:
                result["gaps"].append(gap("source_hash_mismatch", "Input bytes differ from the declared source hash."))
            name = "source" + source_path.suffix.lower()
            target = out / name
            if source_path != target:
                shutil.copyfile(source_path, target)
            result["sources"] = [{"id": "source-1", "file": name, "original_file": source_path.name, "sha256": source_hash, "url": source.get("url"), "license": source.get("license"), "role": "drawing_evidence"}]
            replay = json.loads(json.dumps(spec))
            replay["source"]["file"] = name
            replay["source"]["sha256"] = source_hash
            reference = spec.get("station_reference")
            if isinstance(reference, dict) and isinstance(reference.get("file"), str):
                ref_path = (spec_path.parent / reference["file"]).resolve()
                if ref_path.is_file():
                    ref_name = "station_reference" + ref_path.suffix.lower()
                    ref_hash = digest_file(ref_path)
                    if reference.get("sha256") and reference["sha256"] != ref_hash:
                        result["gaps"].append(gap("station_reference_hash_mismatch", "Station reference bytes differ from their declared hash."))
                    if ref_path != out / ref_name:
                        shutil.copyfile(ref_path, out / ref_name)
                    result["sources"].append({"id": "source-2", "file": ref_name, "original_file": ref_path.name, "sha256": ref_hash, "url": reference.get("url"), "license": reference.get("license"), "role": "station_coordinate_reference", "roi_px": reference.get("roi_px"), "description": reference.get("description")})
                    replay["station_reference"]["file"] = ref_name
                    replay["station_reference"]["sha256"] = ref_hash
            write_json(out / "replay_spec.json", replay)
    for record in result["sources"]:
        _make_source_preview(record, out, spec)
    result["run_id"] = digest_object({"spec": spec_hash, "sources": [s["sha256"] for s in result["sources"]], "implementation": result["provenance"]["implementation_sha256"]})[:20]
    result["assumptions"] = [
        {"id": "symmetry", "status": "review_required", "description": str(spec.get("symmetry_evidence", "Symmetry unresolved."))},
        {"id": "station_interpolation", "status": "review_required", "description": "Ruled interpolation between observed transverse sections. Geometry between stations is a modeling assumption, not directly measured."},
        {"id": "end_caps", "status": "review_required", "description": "Flat mathematical caps at the first and last supplied station; no bow/stern is inferred beyond them."},
        {"id": "upper_closure", "status": "review_required", "description": "Each section is closed across its top measurement. This is an envelope closure, not a claim that a steel deck exists there."},
        {"id": "lower_closure", "status": "review_required", "description": "If a section has nonzero breadth at its lowest measurement, its two sides are closed with a flat lower segment. A cropped section does not establish the hull below that segment."},
        {"id": "condition", "status": "unverified", "description": "The result describes the supplied drawing evidence, not independently verified present-day vessel condition."},
    ]
    if not result["gaps"]:
        try:
            # Inference operates on the exact snapshotted evidence. No reference
            # geometry or benchmark answer files are copied into this directory.
            inference_spec = json.loads((out / "replay_spec.json").read_text())
            if result["input_mode"] == "offset_table_ocr":
                from .table_ingest import extract_table_sections
                extracted = extract_table_sections(inference_spec, out)
            else:
                from .ingest import extract_sections
                extracted = extract_sections(inference_spec, out)
            result["sections"] = extracted.get("sections", [])
            result["gaps"].extend(extracted.get("gaps", []))
            result["diagnostics"] = extracted.get("diagnostics", {})
            result["method"] = extracted.get("method", "raster_curve_tracking") + "+section_loft"
            write_json(out / "extracted_sections.json", extracted)
            found = {s["id"] for s in result["sections"]}
            for sec in spec["sections"]:
                if sec["id"] not in found:
                    result["gaps"].append(gap("unresolved_required_section", "A required drawing view did not yield a supported contour. Interpolation over missing evidence is disabled.", sec["id"]))
            for sec in result["sections"]:
                sec.setdefault("evidence", {})["source_id"] = "source-1"
                sec["evidence"]["source_sha256"] = result["sources"][0]["sha256"]
                sec["evidence"]["assistance"] = ("Table cell regions, row elevations and station positions supplied explicitly; half-breadths recognized from source image text." if result["input_mode"] == "offset_table_ocr" else "Section region, station coordinate and scale supplied explicitly; curve points measured from image.")
                if len(result["sources"]) > 1:
                    sec["evidence"]["station_source_id"] = "source-2"
            if not any(g.get("severity", "blocking") == "blocking" for g in result["gaps"]):
                shape, normalized = build_hull(result["sections"])
                provisional = metrics_for(shape)
                constraints = spec.get("constraints", {})
                tolerance = float(constraints.get("relative_tolerance", 0.03))
                if tolerance <= 0 or tolerance > 0.2:
                    result["gaps"].append(gap("invalid_constraint_tolerance", "Constraint tolerance must be in (0, 0.2]."))
                for key in ("length_m", "beam_m", "depth_m"):
                    if key in constraints:
                        observed, expected = provisional[key], float(constraints[key])
                        error = abs(observed - expected) / expected
                        if error > tolerance:
                            result["gaps"].append(gap("dimension_conflict", f"Reconstruction {key}={observed:.6g} disagrees with independent dimension {expected:.6g} (relative difference {error:.2%})."))
                if not any(g.get("severity", "blocking") == "blocking" for g in result["gaps"]):
                    result["exports"], result["metrics"] = export_geometry(shape, out, export_cad=export_cad)
                    result["status"] = "review_required"
                    result["parts"] = [{
                        "id": "hull", "name": "Reconstructed hull envelope", "kind": "hull_envelope",
                        "source_ids": [s["id"] for s in result["sources"]], "section_ids": [s["id"] for s in result["sections"]],
                        "status": "review_required", "mesh_file": "mesh.json",
                        "unresolved_properties": ["shell_thickness", "material", "internal_structure", "current_as_built_condition"],
                    }]
                    result["metrics"]["section_count"] = len(normalized)
                    result["metrics"]["minimum_observation_coverage"] = min(s.get("coverage", 0) for s in result["sections"])
                    write_json(out / "cad_sections.json", normalized)
                    result["provenance"]["extracted_geometry_sha256"] = digest_object([{ "id": s["id"], "x_m": s["x_m"], "points_yz_m": s["points_yz_m"]} for s in result["sections"]])
        except GeometryError as exc:
            result["gaps"].append(gap("invalid_geometry", str(exc)))
        except Exception as exc:
            # No partial geometry is published as accepted after an unexpected error.
            result["gaps"].append(gap("processing_error", f"Processing stopped: {type(exc).__name__}: {exc}"))
    if result["status"] == "blocked":
        result["exports"] = {}
        result["parts"] = []
        for name in ("model.step", "model.stl", "mesh.json"):
            (out / name).unlink(missing_ok=True)
    result["timing_seconds"] = time.perf_counter() - started
    result["provenance"]["output_sha256"] = {name: digest_file(out / name) for name in ("model.step", "model.stl", "mesh.json", "extracted_sections.json") if (out / name).exists()}
    write_json(out / "result.json", result)
    return result


def verify_run(run_dir: str | Path) -> dict:
    path = Path(run_dir)
    result = json.loads((path / "result.json").read_text())
    checks = []
    for source in result["sources"]:
        candidate = path / source["file"]
        checks.append({"file": source["file"], "valid": candidate.is_file() and digest_file(candidate) == source["sha256"], "role": "source"})
    for name, expected in result["provenance"].get("output_sha256", {}).items():
        candidate = path / name
        checks.append({"file": name, "valid": candidate.is_file() and digest_file(candidate) == expected, "role": "output"})
    for name, expected in result["provenance"].get("implementation_snapshot", {}).get("files_sha256", {}).items():
        candidate = path / name
        checks.append({"file": name, "valid": candidate.is_file() and digest_file(candidate) == expected, "role": "implementation"})
    spec_path = path / "input_spec.json"
    checks.append({"file": "input_spec.json", "valid": spec_path.is_file() and digest_object(json.loads(spec_path.read_text())) == result["provenance"].get("input_spec_sha256"), "role": "specification"})
    return {"valid": all(c["valid"] for c in checks), "checks": checks, "limitation": "Content hashes detect changes against this local manifest. This is not an externally signed certification."}

