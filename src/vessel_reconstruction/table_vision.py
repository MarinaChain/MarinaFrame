"""Offset-table reading with the vision model: crops and deterministic checks.

This module never contacts a model provider. ``prepare`` writes one PNG crop
per human-declared table cell and a manifest. The Rust controller command
``marinaframe read-table`` sends the crops and records receipts. Then
``extract_table_sections`` binds each receipt to a crop recomputed from the
captured source and accepts only strict feet-inches-eighths tokens. Every
doubt is a blocking gap; no digit is repaired and no value is guessed.
See docs/VISION_TABLE_READING.md.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import sys

from PIL import Image

from .provenance import digest_file, write_json
from .schema import TABLE_VISION_MODE, gap, load_bounded_json

INPUT_MODE = TABLE_VISION_MODE
TABLE_UNITS = "feet_inches_eighths"
CROPS_VERSION = "marinaframe.table_crops.v1"
READING_VERSION = "marinaframe.table_reading.v1"
TABLE_PURPOSE = "table_transcription"
CELL_EVIDENCE_KIND = "table_cell_crop"
GO_MODEL = "deepseek-v4.1-flash"
METRES_PER_FOOT = 0.3048
# Small crops are enlarged by an integer factor (nearest neighbour) so that a
# printed token is at least this many pixels high. No pixel values change.
MIN_CROP_HEIGHT_PX = 48
# The Rust provider worker accepts PNGs up to these limits (provider.rs).
MAX_CROP_SIDE_PX = 2048
MAX_CROP_PIXELS = 1_048_576
MAX_CROP_BYTES = 196_608
MAX_READING_BYTES = 8 * 1024 * 1024


def parse_feet_inches_eighths(text: str) -> tuple[float, str]:
    """Parse an explicit F-I-E token to metres; whitespace removal is not digit repair."""
    normalized = re.sub(r"\s+", "", text.strip())
    match = re.fullmatch(r"(\d{1,3})-(\d{1,2})-([0-7])", normalized)
    if not match:
        raise ValueError("Expected unambiguous feet-inches-eighths notation, such as 18-7-4.")
    feet, inches, eighths = map(int, match.groups())
    if not 0 <= inches <= 11:
        raise ValueError("Inches must be in 0..11; no carry or digit correction is inferred.")
    return (feet + inches / 12 + eighths / 96) * METRES_PER_FOOT, normalized


def cell_id(section_index: int, cell_index: int) -> str:
    """Stable, provider-safe identity of one declared cell (spec order)."""
    return f"c{section_index:03d}-{cell_index:03d}"


def declared_cells(spec: dict) -> list[dict]:
    """List declared cells in spec order with their identities."""
    cells = []
    for section_index, section in enumerate(spec.get("sections", [])):
        for index, cell in enumerate(section.get("cells", [])):
            cells.append({"cell_id": cell_id(section_index, index), "section_id": section["id"],
                          "cell_index": index, "z_m": float(cell["z_m"]), "roi_px": [int(v) for v in cell["roi_px"]]})
    return cells


def crop_png(image, roi: list[int]) -> tuple[bytes, int, int]:
    """Deterministic grayscale PNG of one cell region of an RGB source array."""
    left, top, right, bottom = roi
    height, width = image.shape[:2]
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
        raise ValueError("Cell region lies outside the source image.")
    cell = Image.fromarray(image[top:bottom, left:right]).convert("L")
    if cell.height < MIN_CROP_HEIGHT_PX:
        factor = math.ceil(MIN_CROP_HEIGHT_PX / cell.height)
        cell = cell.resize((cell.width * factor, cell.height * factor), Image.Resampling.NEAREST)
    if max(cell.size) > MAX_CROP_SIDE_PX or cell.width * cell.height > MAX_CROP_PIXELS:
        raise ValueError("Cell crop exceeds the provider image dimension limit.")
    buffer = BytesIO()
    cell.save(buffer, format="PNG")
    data = buffer.getvalue()
    if len(data) > MAX_CROP_BYTES:
        raise ValueError("Cell crop exceeds the provider image byte limit.")
    return data, cell.width, cell.height


def _source_image(spec: dict, base_dir: Path):
    from .ingest import _read_image
    return _read_image(spec["source"], Path(base_dir))[0]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(spec_path: Path, out_dir: Path) -> dict:
    """Write cell crops and their manifest for ``marinaframe read-table``."""
    from .resources import validate_sources
    from .schema import validate_spec
    spec_path, out_dir = Path(spec_path), Path(out_dir)
    spec = load_bounded_json(spec_path)
    errors = validate_spec(spec, spec_path.parent)
    if spec.get("input_mode") != INPUT_MODE:
        errors.append(gap("unsupported_input_mode", f"prepare requires input_mode={INPUT_MODE}."))
    if errors:
        raise ValueError("; ".join(f"{e['kind']}: {e['message']}" for e in errors[:8]))
    validate_sources(spec, spec_path.parent)
    image = _source_image(spec, spec_path.parent)
    out_dir.mkdir(parents=True, exist_ok=False)
    entries = []
    for cell in declared_cells(spec):
        data, width, height = crop_png(image, cell["roi_px"])
        name = f"{cell['cell_id']}.png"
        with (out_dir / name).open("xb") as handle:
            handle.write(data)
        entries.append({"cell_id": cell["cell_id"], "section_id": cell["section_id"], "cell_index": cell["cell_index"],
                        "crop_file": name, "sha256": _sha256(data), "bytes": len(data), "width": width, "height": height})
    manifest = {"schema_version": CROPS_VERSION, "source_sha256": digest_file(spec_path.parent / spec["source"]["file"]),
                "table_value_units": TABLE_UNITS, "engineering_approved": False, "cells": entries}
    write_json(out_dir / "manifest.json", manifest)
    return manifest


def _cell_gap(kind: str, message: str, cell: dict) -> dict:
    entry = gap(kind, message, cell["section_id"])
    entry.update(id=f"{kind}:{cell['cell_id']}", cell_id=cell["cell_id"], cell_index=cell["cell_index"])
    return entry


def _record_problem(record, source_sha256: str) -> str | None:
    """Return why a reading record cannot be used, or None."""
    if not isinstance(record, dict) or record.get("schema_version") != READING_VERSION:
        return "Unsupported table reading record."
    if record.get("engineering_approved") is not False:
        return "A table reading record cannot claim engineering approval."
    if record.get("evidence_mode") != "live" or record.get("requested_model") != GO_MODEL:
        return "The reading record does not name the provisioned model."
    if record.get("source_sha256") != source_sha256:
        return "The reading record belongs to different source bytes."
    if record.get("table_value_units") != TABLE_UNITS:
        return "The reading record declares other table units."
    if not isinstance(record.get("receipts"), list):
        return "The reading record has no receipt list."
    return None


def collect_readings(record: dict) -> tuple[dict[str, list[dict]], list[str]]:
    """Map cell id to readings from completed receipts.

    A transcription entry counts only when the same receipt sent an image of
    that cell. Other entries are returned as unrequested cell ids.
    """
    readings: dict[str, list[dict]] = {}
    unrequested = []
    for receipt in record["receipts"]:
        if not isinstance(receipt, dict) or receipt.get("purpose") != TABLE_PURPOSE:
            unrequested.append("<receipt without table purpose>")
            continue
        if (receipt.get("state") != "completed" or receipt.get("returned_model") != GO_MODEL
                or not isinstance(receipt.get("transcription"), dict)):
            continue
        images = {image.get("artifact_id"): image for image in receipt.get("images", [])
                  if isinstance(image, dict) and image.get("evidence_kind") == CELL_EVIDENCE_KIND
                  and image.get("pixels_attached") is True}
        for entry in receipt["transcription"].get("cells", []):
            identity = entry.get("cell_id") if isinstance(entry, dict) else None
            if identity not in images:
                unrequested.append(str(identity)[:64])
                continue
            readings.setdefault(identity, []).append({
                "token": entry.get("token"), "abstain_reason": entry.get("abstain_reason"),
                "request_id": receipt.get("request_id"), "completion_id": receipt.get("completion_id"),
                "crop_sha256": images[identity].get("sha256")})
    return readings, unrequested


def _judge_cell(cell: dict, crop_sha256: str, readings: list[dict], half_beam_limit: float | None):
    """Return (value_m, evidence, gap) for one cell; exactly one of value or gap is set."""
    evidence = {"cell_id": cell["cell_id"], "section_id": cell["section_id"], "cell_index": cell["cell_index"],
                "z_m": cell["z_m"], "roi_px": cell["roi_px"], "crop_sha256": crop_sha256,
                "readings": readings, "parsed_value_m": None, "status": "blocked"}
    if not readings:
        return None, evidence, _cell_gap("table_cell_unread", "No completed model transcription covers this cell.", cell)
    if any(r["crop_sha256"] != crop_sha256 for r in readings):
        return None, evidence, _cell_gap("table_cell_pixels_mismatch",
                                         "The pixels sent for this cell differ from the crop of the captured source.", cell)
    outcomes = {r["token"] for r in readings}
    if len(outcomes) > 1:
        return None, evidence, _cell_gap("conflicting_table_readings", "Model readings of this cell disagree; none is chosen.", cell)
    token = readings[0]["token"]
    if not isinstance(token, str):
        reason = readings[0].get("abstain_reason")
        return None, evidence, _cell_gap("table_cell_abstained",
                                         f"The model abstained: {str(reason)[:200]}", cell)
    try:
        value, normalized = parse_feet_inches_eighths(token)
    except ValueError as exc:
        return None, evidence, _cell_gap("ambiguous_table_cell", f"Token {token[:32]!r}: {exc}", cell)
    if half_beam_limit is not None and value > half_beam_limit:
        return None, evidence, _cell_gap("table_value_out_of_range",
                                         "The half-breadth exceeds half of the declared beam and its tolerance.", cell)
    evidence.update(source_token=normalized, parsed_value_m=value, status="observed_review_required")
    return value, evidence, None


def extract_table_sections(spec: dict, base_dir: Path) -> dict:
    """Turn bound model transcriptions into half-breadth sections or blocking gaps.

    Station x_m, waterline z_m, cell regions and unit notation are human
    calibration. Half-breadths come only from model transcriptions of the
    declared cell crops, parsed by the strict notation parser.
    """
    output = {"sections": [], "gaps": [], "cell_evidence": [], "diagnostics": {}, "method": "offset_table_vision"}
    base_dir = Path(base_dir)
    if spec.get("input_mode") != INPUT_MODE or spec.get("table_value_units") != TABLE_UNITS:
        output["gaps"].append(gap("table_units_unresolved", f"Declare input_mode={INPUT_MODE} and table_value_units={TABLE_UNITS}."))
        return output
    reading = spec.get("table_reading")
    if not isinstance(reading, dict) or not isinstance(reading.get("file"), str):
        output["gaps"].append(gap("table_reading_missing", "Run table_vision prepare and marinaframe read-table, then declare table_reading.file."))
        return output
    source_sha256 = digest_file(base_dir / spec["source"]["file"])
    try:
        record = load_bounded_json(base_dir / reading["file"], max_bytes=MAX_READING_BYTES, max_depth=24, max_nodes=500_000)
    except (OSError, ValueError):
        output["gaps"].append(gap("table_reading_unreadable", "The table reading record is unreadable or exceeds limits."))
        return output
    problem = _record_problem(record, source_sha256)
    if problem:
        output["gaps"].append(gap("table_reading_invalid", problem))
        return output
    readings, unrequested = collect_readings(record)
    if unrequested:
        output["gaps"].append(gap("table_reading_unrequested_cell",
                                  f"Transcriptions not tied to a crop sent in the same request: {', '.join(sorted(set(unrequested))[:8])}."))
        return output
    try:
        image = _source_image(spec, base_dir)
    except ValueError as exc:
        output["gaps"].append(gap(getattr(exc, "kind", "unreadable_source"), str(exc)))
        return output
    constraints = spec.get("constraints", {})
    half_beam_limit = None
    if "beam_m" in constraints:
        half_beam_limit = constraints["beam_m"] / 2 * (1 + constraints.get("relative_tolerance", .03))
    cells = declared_cells(spec)
    known = {cell["cell_id"] for cell in cells}
    stray = sorted(set(readings) - known)
    if stray:
        output["gaps"].append(gap("table_reading_unrequested_cell", f"Readings for undeclared cells: {', '.join(stray[:8])}."))
        return output
    by_section: dict[str, list] = {}
    for cell in cells:
        try:
            crop_sha256 = _sha256(crop_png(image, cell["roi_px"])[0])
        except ValueError as exc:
            output["gaps"].append(_cell_gap("invalid_table_cell", str(exc), cell))
            by_section.setdefault(cell["section_id"], []).append((cell, None, None))
            continue
        value, evidence, problem = _judge_cell(cell, crop_sha256, readings.get(cell["cell_id"], []), half_beam_limit)
        output["cell_evidence"].append(evidence)
        if problem:
            output["gaps"].append(problem)
        by_section.setdefault(cell["section_id"], []).append((cell, value, evidence))
    statistics = {"cells_declared": len(cells), "cells_accepted": 0, "sections": {}}
    for section in spec["sections"]:
        entries = by_section.get(section["id"], [])
        accepted = [entry for entry in entries if entry[1] is not None]
        statistics["cells_accepted"] += len(accepted)
        blocked = len(accepted) != len(entries)
        statistics["sections"][section["id"]] = {"declared_cells": len(entries), "accepted_cells": len(accepted),
                                                 "status": "blocked" if blocked else "review_required"}
        if blocked:
            continue
        points = sorted([[value, cell["z_m"]] for cell, value, _ in accepted], key=lambda point: point[1])
        warnings = ["Model transcriptions are untrusted readings, not labels; every cell requires human source review.",
                    "Station locations, waterline heights, cell regions and unit notation are human-declared.",
                    "Only the listed waterline points were observed; geometry between them is interpolation."]
        if any(b[0] < a[0] for a, b in zip(points, points[1:])):
            output["gaps"].append(gap("non_monotonic_station", "Half-breadth decreases with height; tumblehome is possible, but confirm the readings.",
                                      section["id"], severity="warning"))
        output["sections"].append({
            "id": section["id"], "x_m": float(section["x_m"]), "points_yz_m": points, "coverage": 1.0,
            "evidence": {"roi_px": list(section["roi_px"]), "input_form": "offset_table_vision_transcription",
                         "human_assistance": section.get("evidence"), "table_value_units": TABLE_UNITS,
                         "cell_evidence": [evidence for _, _, evidence in accepted],
                         "source_surface": spec.get("table_surface", "Unresolved; reviewer must identify the measured surface")},
            "warnings": warnings})
    statistics.update(model=GO_MODEL, reading_counts=record.get("counts"),
                      notation_parser="strict feet-inches-eighths; no digit repair, no unit conversion of tokens",
                      crop_policy=f"grayscale, nearest-neighbour integer enlargement to >= {MIN_CROP_HEIGHT_PX} px height")
    output["diagnostics"] = statistics
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m vessel_reconstruction.table_vision")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_command = commands.add_parser("prepare", help="Write cell crops and their manifest.")
    prepare_command.add_argument("--spec", required=True, type=Path)
    prepare_command.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = prepare(args.spec, args.out)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:1000], "engineering_approved": False}), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "cells": len(manifest["cells"]), "manifest": str(args.out / "manifest.json"),
                      "engineering_approved": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
