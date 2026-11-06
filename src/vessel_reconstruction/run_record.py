"""Version 2 immutable run records and non-circular local integrity manifests.

The manifest hashes every immutable file, including the entire result record.
The result never hashes the manifest. Review events may reference the manifest
hash, but remain separate mutable records. This is local integrity checking,
not authenticity against an actor able to rewrite the complete run.
"""
from __future__ import annotations

import math
import os
import re
from bisect import bisect_right
from pathlib import Path

from .provenance import digest_file, digest_object, safe_relative_file, snapshot_hash, sync_file, write_json
from .schema import finite, load_bounded_json, SHA256

SCHEMA_VERSION = "2.0"
TERMINAL_STATES = {"review_required", "blocked", "failed", "interrupted", "cancelled"}
MUTABLE_FILES = {"review_history.json", "review_state.json", ".review.lock"}
MAX_RECORD_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_RUN_BYTES = 1024 * 1024 * 1024
REQUIRED_FILES = {"result.json", "input_spec.json", "replay_spec.json"}
LIMITATION = ("Content hashes and derived checks detect changes against this local manifest. "
              "An actor who can rewrite all evidence and the manifest can replace the record; "
              "this is not a digital signature, engineering approval, or independent source authentication.")


def _read(root, name):
    return load_bounded_json(safe_relative_file(root, name), max_bytes=MAX_RECORD_BYTES,
                             max_depth=40, max_nodes=3_000_000)


def _inventory(root: Path) -> set[str]:
    files, size = set(), 0
    for directory, subdirs, names in os.walk(root, followlinks=False):
        for name in subdirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError("Symbolic-link directory in run.")
        for name in names:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            path = safe_relative_file(root, relative)
            size += path.stat().st_size
            if path.stat().st_size > MAX_ARTIFACT_BYTES or size > MAX_RUN_BYTES or len(files) >= 4096:
                raise ValueError("Run exceeds bounded verification limits.")
            files.add(relative)
    return files


def identity_for(result: dict) -> dict:
    provenance = result["provenance"]
    return {"scheme": "input-sources-implementation-request-v2",
            "input_spec_sha256": provenance["input_spec_sha256"],
            "submitted_spec_sha256": provenance.get("submitted_spec_sha256"),
            "sources": [{"id": source["id"], "sha256": source["sha256"]} for source in result["sources"]],
            "implementation_sha256": provenance.get("implementation_sha256"),
            "requested_exports": result["requested_exports"],
            "recovery_identity": provenance.get("recovery_identity")}


def seal_run(root: Path, result: dict, *, writer=write_json) -> dict:
    """Write the final result, then the full manifest. Called only in staging."""
    result["identity"] = identity_for(result)
    result["run_id"] = digest_object(result["identity"])[:20]
    result["terminal"] = {"state": result["status"], "complete": True,
                          "publication": "exclusive_staging_atomic_directory_v1"}
    writer(root / "result.json", result)
    files = {}
    for name in sorted(_inventory(root) - MUTABLE_FILES - {"manifest.json", "transaction.json"}):
        path = safe_relative_file(root, name)
        sync_file(path)
        files[name] = {"sha256": digest_file(path), "size_bytes": path.stat().st_size}
    manifest = {"schema_version": SCHEMA_VERSION, "kind": "marinaframe_run_manifest",
                "hash_algorithm": "sha256", "canonicalization": "json-sortkeys-utf8-v1",
                "run_id": result["run_id"], "record": {"file": "result.json",
                "sha256": files["result.json"]["sha256"], "canonical_sha256": digest_object(result)},
                "files": files, "mutable_files": sorted(MUTABLE_FILES), "local_integrity_only": True}
    writer(root / "manifest.json", manifest)
    return manifest


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _points(points, minimum=2):
    _require(isinstance(points, list) and minimum <= len(points) <= 1025, "Invalid section point count.")
    previous = None
    for point in points:
        _require(isinstance(point, list) and len(point) == 2 and all(finite(v) and abs(v) <= 1e7 for v in point), "Invalid section coordinate.")
        _require(point[0] >= 0 and (previous is None or point[1] > previous), "Half-section ordinates must be nonnegative with increasing elevations.")
        previous = point[1]


def _area(points):
    return sum((a[0] + b[0]) * (b[1] - a[1]) for a, b in zip(points, points[1:]))


def _close(observed, expected, *, relative=2e-6, absolute=1e-8):
    return finite(observed) and abs(observed - expected) <= max(absolute, abs(expected) * relative)


def _ordinate(points, elevations, z):
    index = min(max(bisect_right(elevations, z) - 1, 0), len(points) - 2)
    left, right = points[index], points[index + 1]
    return left[0] + (right[0] - left[0]) * (z - left[1]) / (right[1] - left[1])


def _check_approximation(normalized, metrics):
    """Recompute whole-polyline approximation diagnostics using scalar math."""
    derived = []
    for section in normalized:
        source, cad = section["points_yz_m"], section["cad_points_yz_m"]
        _require(_close(source[0][1], cad[0][1]) and _close(source[-1][1], cad[-1][1]),
                 "CAD approximation changed the observed vertical domain.")
        source_z, cad_z = [point[1] for point in source], [point[1] for point in cad]
        knots = sorted(set(source_z + cad_z))
        errors = [_ordinate(cad, cad_z, z) - _ordinate(source, source_z, z) for z in knots]
        maximum = max(abs(error) for error in errors)
        rms = math.sqrt(max(0.0, sum((b - a) * (e * e + e * f + f * f) / 3
                                    for a, b, e, f in zip(knots, knots[1:], errors, errors[1:]))
                                   / (knots[-1] - knots[0])))
        record = section.get("cad_approximation")
        _require(isinstance(record, dict) and record.get("method") == "vertical_error_bounded_source_knots_v1"
                 and record.get("correspondence") == "shared_normalized_height_source_knot_union", "Unsupported or missing CAD approximation record.")
        allowed = record.get("maximum_allowed_half_breadth_deviation_m")
        _require(finite(allowed) and 0 <= allowed <= .01 and maximum <= allowed + 1e-10,
                 "CAD approximation exceeds its declared ordinate-error bound.")
        expected = {"maximum_half_breadth_deviation_m": maximum,
                    "height_weighted_rms_deviation_m": rms, "source_section_area_m2": _area(source),
                    "cad_section_area_m2": _area(cad), "section_area_error_m2": _area(cad) - _area(source),
                    "section_beam_error_m": 2 * (max(p[0] for p in cad) - max(p[0] for p in source))}
        _require(all(_close(record.get(key), value, absolute=1e-9) for key, value in expected.items()), "CAD approximation diagnostics disagree with source and normalized ordinates.")
        _require(record.get("source_point_count") == len(source) and record.get("common_knot_count") == len(cad)
                 and type(record.get("retained_source_knots")) is int and 2 <= record["retained_source_knots"] <= len(source),
                 "CAD approximation point counts are inconsistent.")
        expected_faces = 2 * (len(normalized) - 1) * len(cad) + 2
        _require(len(cad) <= 513 and expected_faces <= 20_000 and record.get("estimated_face_count") == expected_faces,
                 "CAD complexity declaration is inconsistent or exceeds bounds.")
        derived.append(record)
    summary = metrics.get("geometry_approximation")
    _require(isinstance(summary, dict), "Missing geometry approximation summary.")
    values = {"maximum_allowed_half_breadth_deviation_m": max(r["maximum_allowed_half_breadth_deviation_m"] for r in derived),
              "maximum_half_breadth_deviation_m": max(r["maximum_half_breadth_deviation_m"] for r in derived),
              "maximum_height_weighted_rms_deviation_m": max(r["height_weighted_rms_deviation_m"] for r in derived),
              "maximum_section_area_error_m2": max(abs(r["section_area_error_m2"]) for r in derived),
              "maximum_section_beam_error_m": max(abs(r["section_beam_error_m"]) for r in derived)}
    _require(all(_close(summary.get(key), value, absolute=1e-9) for key, value in values.items()), "CAD approximation summary disagrees with individual sections.")
    _require(summary.get("common_knot_count") == len(normalized[0]["cad_points_yz_m"])
             and summary.get("estimated_face_count") == derived[0]["estimated_face_count"], "CAD summary counts are inconsistent.")


def _check_record(root: Path, result: dict, manifest: dict):
    required = {"schema_version", "record_kind", "run_id", "identity", "vessel_id", "status", "method",
                "input_mode", "review", "sources", "parts", "sections", "normalized_sections", "gaps",
                "assumptions", "metrics", "exports", "provenance", "timing_seconds", "terminal", "requested_exports"}
    _require(isinstance(result, dict) and required <= set(result) <= required | {"diagnostics"}, "Incomplete or unsupported inference record schema.")
    _require(result["schema_version"] == SCHEMA_VERSION and result["record_kind"] == "immutable_inference_record", "Unsupported inference record.")
    status = result["status"]
    _require(isinstance(status, str) and status in TERMINAL_STATES, "Nonterminal or unknown run state.")
    _require(result["terminal"] == {"state": status, "complete": True, "publication": "exclusive_staging_atomic_directory_v1"}, "Terminal state declaration is inconsistent.")
    _require(result["review"] == {"state": "unreviewed", "engineering_approved": False}, "The immutable record cannot contain a mutable review decision or approval.")
    _require(type(result["requested_exports"]) is bool and finite(result["timing_seconds"]) and result["timing_seconds"] >= 0, "Invalid request or timing metadata.")
    for field in ("vessel_id", "method"):
        _require(isinstance(result[field], str) and 0 < len(result[field]) <= 8192, "Invalid record text metadata.")
    _require(result["input_mode"] in (None, "calibrated_section_curves", "offset_table_ocr"), "Invalid input mode metadata.")
    for field in ("sources", "parts", "sections", "normalized_sections", "gaps", "assumptions"):
        _require(isinstance(result[field], list), f"Invalid {field} record.")
    for field in ("metrics", "exports", "provenance"):
        _require(isinstance(result[field], dict), f"Invalid {field} record.")
    for entry in result["gaps"]:
        _require(isinstance(entry, dict) and isinstance(entry.get("kind"), str) and isinstance(entry.get("message"), str)
                 and entry.get("severity") in ("blocking", "warning", "info"), "Invalid gap record.")
    blocking = any(entry["severity"] == "blocking" for entry in result["gaps"])
    _require((status == "review_required" and not blocking) or (status != "review_required" and blocking), "Run status contradicts its blocking gaps.")
    declared = set(manifest["files"])
    _require(REQUIRED_FILES <= declared, "Required evidence declarations are missing.")
    input_spec, replay = _read(root, "input_spec.json"), _read(root, "replay_spec.json")
    provenance = result["provenance"]
    _require(provenance.get("input_spec_sha256") == digest_object(input_spec), "Canonical input-specification digest mismatch.")
    _require(provenance.get("replay_spec_sha256") == digest_object(replay), "Canonical replay-specification digest mismatch.")
    submitted = provenance.get("submitted_spec_sha256")
    if submitted is not None:
        _require(isinstance(submitted, str) and SHA256.fullmatch(submitted) is not None and "submitted_spec.json" in declared,
                 "Submitted specification evidence is missing.")
        _require(digest_file(safe_relative_file(root, "submitted_spec.json")) == submitted, "Submitted specification digest mismatch.")
    snapshot = provenance.get("implementation_snapshot")
    _require(isinstance(snapshot, dict) and isinstance(snapshot.get("files_sha256"), dict), "Implementation declaration is missing.")
    implementation_files = snapshot["files_sha256"]
    if snapshot.get("status") == "complete":
        _require(bool(implementation_files), "Implementation manifest is empty.")
        _require({"pipeline.py", "schema.py", "provenance.py", "run_record.py", "geometry.py", "ingest.py"}
                 <= {Path(name).name for name in implementation_files}, "Required implementation source is missing.")
        _require({name for name in declared if name.startswith("implementation_source/")} == set(implementation_files),
                 "Implementation declaration does not cover its complete file inventory.")
        for name, expected in implementation_files.items():
            _require(name.startswith("implementation_source/vessel_reconstruction/") and name.endswith(".py") and name in declared,
                     "Invalid implementation evidence path.")
            _require(expected == manifest["files"][name]["sha256"], "Implementation digest declaration mismatch.")
        _require(snapshot_hash(root, implementation_files) == provenance.get("implementation_sha256") == snapshot.get("implementation_sha256"),
                 "Combined implementation identity mismatch.")
    else:
        _require(snapshot.get("status") == "unavailable" and not implementation_files
                 and provenance.get("implementation_sha256") is None and status != "review_required", "Incomplete implementation cannot support an export.")
        _require(not any(name.startswith("implementation_source/") for name in declared), "Untracked partial implementation evidence.")
    _require(result["identity"] == identity_for(result), "Identity payload is inconsistent with the record.")
    _require(result["run_id"] == digest_object(result["identity"])[:20] == manifest["run_id"], "Run identity cannot be recomputed.")
    _require(len(result["sources"]) <= 2, "Too many evidence sources.")
    source_ids = set()
    for source in result["sources"]:
        _require(isinstance(source, dict) and source.get("id") in ("source-1", "source-2") and source["id"] not in source_ids, "Invalid source identity.")
        source_ids.add(source["id"])
        name = source.get("file")
        _require(isinstance(name, str) and name in declared and source.get("sha256") == manifest["files"][name]["sha256"], "Source evidence declaration mismatch.")
        field = "source" if source["id"] == "source-1" else "station_reference"
        _require(isinstance(replay, dict) and isinstance(replay.get(field), dict)
                 and replay[field].get("file") == name and replay[field].get("sha256") == source["sha256"], "Replay source binding is inconsistent.")
        if "preview_file" in source:
            _require(source["preview_file"] in declared, "Source preview evidence is missing.")
    expected_files = set(REQUIRED_FILES) | set(implementation_files)
    if submitted is not None:
        expected_files.add("submitted_spec.json")
    for source in result["sources"]:
        expected_files.add(source["file"])
        if "preview_file" in source:
            expected_files.add(source["preview_file"])
    if result["sections"] or provenance.get("extraction_complete"):
        expected_files.add("extracted_sections.json")
    if status == "review_required":
        expected_files.update(("mesh.json", "cad_sections.json", "extracted_sections.json"))
        if result["requested_exports"]:
            expected_files.update(("model.step", "model.stl"))
    _require(declared == expected_files, "Immutable artifacts are not fully explained by the record's evidence and terminal state.")
    if isinstance(input_spec, dict) and isinstance(replay, dict):
        expected_replay = dict(input_spec)
        for source in result["sources"]:
            field = "source" if source["id"] == "source-1" else "station_reference"
            _require(isinstance(input_spec.get(field), dict), "Input source is not an object.")
            expected_replay[field] = {**input_spec[field], "file": source["file"], "sha256": source["sha256"]}
        _require(expected_replay == replay, "Replay metadata differs from the submitted inference specification.")
    else:
        _require(replay is None and not result["sources"], "Rejected input cannot contain unexplained replay evidence.")
    sections = result["sections"]
    _require(len(sections) <= 300 and len(result["normalized_sections"]) <= 300, "Section record exceeds bounds.")
    ids = set()
    input_sections = {s["id"]: s for s in input_spec.get("sections", []) if isinstance(s, dict) and isinstance(s.get("id"), str)} if isinstance(input_spec, dict) and isinstance(input_spec.get("sections"), list) else {}
    for section in sections:
        _require(isinstance(section, dict) and isinstance(section.get("id"), str) and section["id"] not in ids, "Invalid observed section identity.")
        ids.add(section["id"])
        _require(finite(section.get("x_m")) and abs(section["x_m"]) <= 1e7, "Invalid observed station coordinate.")
        _require(section["id"] in input_sections and section["x_m"] == input_sections[section["id"]].get("x_m"), "Observed station contradicts its input calibration.")
        _points(section.get("points_yz_m"), minimum=5)
        _require(finite(section.get("coverage")) and 0 <= section["coverage"] <= 1, "Invalid observation coverage.")
        evidence = section.get("evidence")
        _require(isinstance(evidence, dict) and evidence.get("source_id") == "source-1" and "source-1" in source_ids
                 and evidence.get("source_sha256") == result["sources"][0]["sha256"], "Observed section has no bound source evidence.")
    if sections or provenance.get("extraction_complete"):
        _require("extracted_sections.json" in declared, "Observed sections artifact is missing.")
        extracted = _read(root, "extracted_sections.json")
        _require(isinstance(extracted, dict) and extracted.get("sections") == sections, "Observed sections disagree with the immutable record.")
        expected_digest = digest_object([{key: section[key] for key in ("id", "x_m", "points_yz_m")} for section in sections])
        _require(provenance.get("extracted_geometry_sha256") == expected_digest, "Observed-geometry digest mismatch.")
    exports = result["exports"]
    if status != "review_required":
        _require(not exports and not result["parts"] and not result["metrics"] and not result["normalized_sections"], "A non-success state exposes geometry or authoritative geometry metrics.")
        _require(not {"mesh.json", "model.step", "model.stl", "cad_sections.json"}.intersection(declared), "A non-success run retains published geometry.")
        return
    _require(isinstance(input_spec, dict) and isinstance(replay, dict) and "source-1" in source_ids, "Successful run lacks input evidence.")
    _require(set(input_sections) == ids and len(ids) >= 3, "Required stations are missing from a successful run.")
    expected_exports = {"mesh": "mesh.json", "mesh_units": "m"}
    if result["requested_exports"]:
        expected_exports.update(step="model.step", step_units="mm", stl="model.stl", stl_units="mm")
    _require(exports == expected_exports, "Export status, request, filenames or units are inconsistent.")
    _require({"mesh.json", "cad_sections.json", "extracted_sections.json"} <= declared, "Required successful geometry evidence is missing.")
    if result["requested_exports"]:
        _require({"model.step", "model.stl"} <= declared, "Requested CAD exports are missing.")
    else:
        _require(not {"model.step", "model.stl"}.intersection(declared), "Unrequested CAD exports present.")
    normalized = result["normalized_sections"]
    _require(_read(root, "cad_sections.json") == normalized and len(normalized) == len(sections), "Normalized CAD sections disagree with the record.")
    original = {section["id"]: section for section in sections}
    for section in normalized:
        _require(isinstance(section, dict) and section.get("id") in original, "Unknown CAD section identity.")
        _require({key: value for key, value in section.items() if key not in ("cad_points_yz_m", "cad_approximation")} == original[section["id"]], "CAD section altered its recorded observations.")
        _points(section.get("cad_points_yz_m"))
    _require(len({section["id"] for section in normalized}) == len(sections), "Duplicate CAD section identity.")
    xs = [section["x_m"] for section in normalized]
    _require(all(b > a for a, b in zip(xs, xs[1:])), "CAD station ordering is invalid.")
    n = len(normalized[0]["cad_points_yz_m"])
    _require(all(len(section["cad_points_yz_m"]) == n for section in normalized), "CAD correspondence is inconsistent.")
    volume = 0.0
    for left, right in zip(normalized, normalized[1:]):
        a, b = left["cad_points_yz_m"], right["cad_points_yz_m"]
        midpoint = [[(p[0] + q[0]) / 2, (p[1] + q[1]) / 2] for p, q in zip(a, b)]
        volume += (right["x_m"] - left["x_m"]) * (_area(a) + 4 * _area(midpoint) + _area(b)) / 6
    metrics = result["metrics"]
    _check_approximation(normalized, metrics)
    for name in ("volume_m3", "surface_area_m2", "length_m", "beam_m", "depth_m"):
        _require(finite(metrics.get(name)) and metrics[name] > 0, "Invalid authoritative geometry metric.")
    _require(_close(metrics["volume_m3"], volume), "Volume disagrees with independently integrated normalized sections.")
    beam = 2 * max(point[0] for section in normalized for point in section["cad_points_yz_m"])
    zmin = min(point[1] for section in normalized for point in section["cad_points_yz_m"])
    zmax = max(point[1] for section in normalized for point in section["cad_points_yz_m"])
    _require(_close(metrics["length_m"], xs[-1] - xs[0]) and _close(metrics["beam_m"], beam) and _close(metrics["depth_m"], zmax - zmin), "Dimensions disagree with normalized CAD bounds.")
    _require(metrics.get("cad_valid") is True and type(metrics.get("solid_count")) is int and metrics["solid_count"] == 1,
             "Successful CAD validity record is missing.")
    _require(metrics.get("section_count") == len(normalized) and _close(metrics.get("minimum_observation_coverage"), min(s["coverage"] for s in sections)), "Observation summary disagrees with section evidence.")
    mesh = _read(root, "mesh.json")
    _require(isinstance(mesh, dict) and mesh.get("units") == "m", "Invalid mesh units/schema.")
    vertices, faces = mesh.get("vertices"), mesh.get("faces")
    _require(isinstance(vertices, list) and 4 <= len(vertices) <= 1_000_000 and isinstance(faces, list) and 4 <= len(faces) <= 2_000_000, "Invalid or excessive mesh topology.")
    _require(all(isinstance(v, list) and len(v) == 3 and all(finite(x) and abs(x) <= 1e7 for x in v) for v in vertices), "Invalid mesh vertex.")
    _require(all(isinstance(f, list) and len(f) == 3 and len(set(f)) == 3 and all(type(i) is int and 0 <= i < len(vertices) for i in f) for f in faces), "Invalid mesh face.")
    _require(metrics.get("mesh_vertices") == len(vertices) and metrics.get("mesh_faces") == len(faces), "Mesh counts disagree with metrics.")
    bounds = {"min": [min(v[k] for v in vertices) for k in range(3)], "max": [max(v[k] for v in vertices) for k in range(3)]}
    bbox = metrics.get("bbox_m")
    _require(isinstance(bbox, dict) and all(isinstance(bbox.get(key), list) and len(bbox[key]) == 3
             and all(_close(a, b) for a, b in zip(bbox[key], bounds[key])) for key in ("min", "max")), "Mesh bounds disagree with geometry metrics.")
    _require(len(result["parts"]) == 1 and isinstance(result["parts"][0], dict)
             and result["parts"][0].get("mesh_file") == "mesh.json"
             and set(result["parts"][0].get("section_ids", [])) == ids, "Part record is inconsistent with geometry evidence.")


def verify_run(run_dir: str | Path) -> dict:
    """Fail closed on malformed, unsealed, incomplete, or inconsistent records."""
    root, checks, version, status = Path(run_dir), [], None, None
    try:
        _require(not root.is_symlink() and root.is_dir(), "Run path must be an ordinary directory.")
        _require(not os.path.lexists(root.parent / f".{root.name}.run-lock"), "Run publication is pending or its durability is unconfirmed; recover the interrupted transaction.")
        result = _read(root, "result.json")
        _require(isinstance(result, dict), "Result must be an object.")
        version, status = result.get("schema_version"), result.get("status")
        if version == "1.0":
            # Legacy hash declarations can be inspected, but the old contract
            # omitted result/replay/CAD sections. Never confer v2 assurance.
            checks.append({"kind": "legacy_unsealed", "valid": False,
                           "message": "Recognized legacy v1 evidence: incomplete immutable boundary; rerun to obtain v2 assurance."})
            return {"valid": False, "schema_version": version, "assurance": "legacy_unsealed", "status": status,
                    "exports_allowed": False, "checks": checks, "limitation": LIMITATION}
        _require(version == SCHEMA_VERSION, "Unsupported result schema version.")
        manifest = _read(root, "manifest.json")
        _require(isinstance(manifest, dict) and set(manifest) == {"schema_version", "kind", "hash_algorithm", "canonicalization", "run_id", "record", "files", "mutable_files", "local_integrity_only"}, "Invalid or incomplete manifest schema.")
        _require(manifest["schema_version"] == SCHEMA_VERSION and manifest["kind"] == "marinaframe_run_manifest"
                 and manifest["hash_algorithm"] == "sha256" and manifest["canonicalization"] == "json-sortkeys-utf8-v1"
                 and manifest["local_integrity_only"] is True and manifest["mutable_files"] == sorted(MUTABLE_FILES), "Unsupported integrity manifest contract.")
        entries = manifest["files"]
        _require(isinstance(entries, dict) and bool(entries) and REQUIRED_FILES <= set(entries), "Manifest lacks nonempty required evidence.")
        actual = _inventory(root) - MUTABLE_FILES - {"manifest.json"}
        _require(set(entries) == actual, "Manifest does not cover the complete immutable file inventory.")
        for name, entry in entries.items():
            _require(isinstance(entry, dict) and set(entry) == {"sha256", "size_bytes"}
                     and isinstance(entry["sha256"], str) and SHA256.fullmatch(entry["sha256"]) is not None
                     and type(entry["size_bytes"]) is int and 0 <= entry["size_bytes"] <= MAX_ARTIFACT_BYTES, "Malformed file declaration.")
            path = safe_relative_file(root, name)
            valid = path.stat().st_size == entry["size_bytes"] and digest_file(path) == entry["sha256"]
            checks.append({"file": name, "kind": "content_hash", "valid": valid})
        _require(all(check["valid"] for check in checks), "One or more immutable evidence files changed.")
        _require(manifest["record"] == {"file": "result.json", "sha256": entries["result.json"]["sha256"], "canonical_sha256": digest_object(result)}, "Entire-record canonical integrity check failed.")
        _check_record(root, result, manifest)
        checks.append({"kind": "schema_identity_and_derived_consistency", "valid": True})
    except Exception as exc:
        checks.append({"kind": "integrity_failure", "valid": False, "message": str(exc)[:500]})
    valid = bool(checks) and all(check["valid"] for check in checks)
    return {"valid": valid, "schema_version": version, "assurance": "local_manifest" if valid else "invalid",
            "status": status, "exports_allowed": valid and status == "review_required", "checks": checks, "limitation": LIMITATION}
