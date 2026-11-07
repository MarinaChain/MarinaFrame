"""Offset-table reading by the vision model: deterministic checks only.

Model responses are injected as read-table records; nothing here contacts a
provider. The records use the receipt shape that rust-control writes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from vessel_reconstruction import table_vision
from vessel_reconstruction.pipeline import reconstruct
from vessel_reconstruction.run_record import verify_run
from vessel_reconstruction.schema import validate_spec
from vessel_reconstruction.table_vision import (GO_MODEL, extract_table_sections, parse_feet_inches_eighths,
                                               prepare)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from make_table_example import make_example  # noqa: E402


@pytest.fixture(scope="module")
def table(tmp_path_factory):
    root = tmp_path_factory.mktemp("table")
    spec_path = make_example(root / "input")
    manifest = prepare(spec_path, root / "crops")
    truth = json.loads((root / "input" / "truth" / "printed_tokens.json").read_text())
    return {"root": root, "spec_path": spec_path, "manifest": manifest, "truth": truth}


def receipt(cells, transcription, *, state="completed", model=GO_MODEL, request_id="table-r1"):
    """A receipt as rust-control writes it, for a batch of manifest cells."""
    images = [{"artifact_id": c["cell_id"], "path": c["crop_file"], "sha256": c["sha256"], "bytes": c["bytes"],
               "mime_type": "image/png", "evidence_kind": "table_cell_crop", "view": None, "generation_id": None,
               "revision_id": None, "step_sha256": None, "pixels_attached": True} for c in cells]
    value = {"protocol": "marinaframe.provider.v1", "request_id": request_id, "state": state,
             "endpoint": "https://opencode.ai/inference/go/openai/v1/chat/completions",
             "requested_model": GO_MODEL, "returned_model": model if state == "completed" else None,
             "completion_id": "cmpl-" + request_id, "http_status": 200, "images": images,
             "usage": {"prompt_tokens": 800, "completion_tokens": 60, "total_tokens": 860},
             "purpose": "table_transcription", "evidence_mode": "live", "error_code": None}
    if state == "completed":
        value["transcription"] = {"cells": transcription}
    return value


def record(table, override=None, *, receipts=None, **fields):
    """A read-table record where every cell reads its printed token, then overrides."""
    cells = table["manifest"]["cells"]
    tokens = dict(table["truth"])
    tokens.update(override or {})
    if receipts is None:
        receipts = []
        for start in range(0, len(cells), 4):
            batch = cells[start:start + 4]
            entries = []
            for c in batch:
                value = tokens[c["cell_id"]]
                entries.append({"cell_id": c["cell_id"], **({"abstain_reason": value[1]} if isinstance(value, tuple) else {"token": value})})
            receipts.append(receipt(batch, entries, request_id=f"table-r{start}"))
    value = {"schema_version": "marinaframe.table_reading.v1", "evidence_mode": "live", "engineering_approved": False,
             "crops_manifest_sha256": "0" * 64, "source_sha256": table["manifest"]["source_sha256"],
             "table_value_units": "feet_inches_eighths", "requested_model": GO_MODEL, "receipts": receipts,
             "counts": {"cells_requested": len(cells)}}
    value.update(fields)
    return value


def extract(table, reading, tmp_path, spec_changes=None):
    spec = json.loads(table["spec_path"].read_text())
    spec.update(spec_changes or {})
    (tmp_path / "table_reading.json").write_text(json.dumps(reading))
    spec["table_reading"] = {"file": "table_reading.json"}
    (tmp_path / "table.png").write_bytes((table["root"] / "input" / "table.png").read_bytes())
    return extract_table_sections(spec, tmp_path)


def kinds(output):
    return [g["kind"] for g in output["gaps"] if g["severity"] == "blocking"]


@pytest.mark.parametrize("text, metres", [("18-7-4", (18 + 7 / 12 + 4 / 96) * .3048), (" 0 - 0 - 0 ", 0.0), ("6-11-7", (6 + 11 / 12 + 7 / 96) * .3048)])
def test_parser_accepts_only_strict_feet_inches_eighths(text, metres):
    assert parse_feet_inches_eighths(text)[0] == pytest.approx(metres)


@pytest.mark.parametrize("text", ["18'-7\"-4", "18-7", "18-7-8", "18-12-0", "5.6", "18-7-4m", "1O-2-3", "18/7/4", "-1-2-3", ""])
def test_parser_rejects_ambiguous_out_of_range_and_unit_marked_tokens(text):
    with pytest.raises(ValueError):
        parse_feet_inches_eighths(text)


def test_prepare_writes_deterministic_hash_bound_crops(table, tmp_path):
    manifest = table["manifest"]
    assert manifest["engineering_approved"] is False and len(manifest["cells"]) == 20
    for cell in manifest["cells"]:
        data = (table["root"] / "crops" / cell["crop_file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == cell["sha256"] and len(data) == cell["bytes"]
        assert data.startswith(b"\x89PNG") and cell["height"] >= table_vision.MIN_CROP_HEIGHT_PX
    again = prepare(table["spec_path"], tmp_path / "again")
    assert again == manifest
    with pytest.raises(FileExistsError):
        prepare(table["spec_path"], tmp_path / "again")


def test_valid_transcriptions_give_sections_with_cell_evidence(table, tmp_path):
    output = extract(table, record(table), tmp_path)
    assert kinds(output) == []
    assert [s["id"] for s in output["sections"]] == ["st-0", "st-1", "st-2", "st-3"]
    station = output["sections"][1]
    assert station["points_yz_m"][0] == [pytest.approx(parse_feet_inches_eighths("4-10-6")[0]), 0.5]
    evidence = station["evidence"]["cell_evidence"][0]
    assert evidence["source_token"] == "4-10-6" and evidence["readings"][0]["request_id"] == "table-r4"
    assert output["diagnostics"]["cells_accepted"] == 20


def test_abstention_blocks_the_station_and_is_not_guessed(table, tmp_path):
    output = extract(table, record(table, {"c002-003": ("abstain", "digit cut off")}), tmp_path)
    assert kinds(output) == ["table_cell_abstained"]
    assert output["gaps"][0]["cell_id"] == "c002-003" and "digit cut off" in output["gaps"][0]["message"]
    assert [s["id"] for s in output["sections"]] == ["st-0", "st-1", "st-3"]


@pytest.mark.parametrize("token", ["6'-4\"-4", "6-4", "6.4.4", "6-4-4 1/2"])
def test_ambiguous_notation_blocks_the_cell(table, tmp_path, token):
    output = extract(table, record(table, {"c002-003": token}), tmp_path)
    assert kinds(output) == ["ambiguous_table_cell"]


def test_out_of_range_notation_and_beam_bound_block(table, tmp_path):
    assert kinds(extract(table, record(table, {"c000-000": "1-12-4"}), tmp_path)) == ["ambiguous_table_cell"]
    # 2 x 6-6-1 is about 3.96 m; a declared 3.5 m beam makes the widest cells out of range.
    output = extract(table, record(table), tmp_path, {"constraints": {"beam_m": 3.5}})
    assert set(kinds(output)) == {"table_value_out_of_range"}
    assert {g["section_id"] for g in output["gaps"]} == {"st-1", "st-2"}


def test_transcription_not_tied_to_a_requested_cell_rejects_the_record(table, tmp_path):
    reading = record(table)
    reading["receipts"][0]["transcription"]["cells"].append({"cell_id": "c003-004", "token": "9-9-1"})
    output = extract(table, reading, tmp_path)
    assert kinds(output) == ["table_reading_unrequested_cell"] and output["sections"] == []


def test_pixels_that_differ_from_the_captured_source_block(table, tmp_path):
    reading = record(table)
    reading["receipts"][1]["images"][0]["sha256"] = "f" * 64
    output = extract(table, reading, tmp_path)
    assert kinds(output) == ["table_cell_pixels_mismatch"]


def test_failed_requests_leave_cells_unread_and_disagreement_is_not_resolved(table, tmp_path):
    reading = record(table)
    cells = table["manifest"]["cells"][:4]
    reading["receipts"][0] = receipt(cells, None, state="failed")
    assert kinds(extract(table, reading, tmp_path)) == ["table_cell_unread"] * 4
    reading = record(table)
    second = copy.deepcopy(reading["receipts"][0])
    second["request_id"] = "table-second"
    second["transcription"]["cells"][0]["token"] = "1-10-6"
    reading["receipts"].append(second)
    assert kinds(extract(table, reading, tmp_path)) == ["conflicting_table_readings"]


def test_record_level_contract(table, tmp_path):
    for fields in ({"engineering_approved": True}, {"requested_model": "other-model"},
                   {"source_sha256": "a" * 64}, {"table_value_units": "metres"}):
        assert kinds(extract(table, record(table, **fields), tmp_path)) == ["table_reading_invalid"], fields
    reading = record(table)
    reading["receipts"][0]["returned_model"] = "other-model"
    assert kinds(extract(table, reading, tmp_path)) == ["table_cell_unread"] * 4


def test_units_and_input_answers_are_explicit(table):
    spec = json.loads(table["spec_path"].read_text())
    base = table["spec_path"].parent
    assert validate_spec(spec, base) == []
    for change, kind in (({"table_value_units": "metres"}, "table_units_unresolved"),
                         ({"input_mode": "offset_table_ocr"}, "unsupported_input_mode")):
        assert kind in [g["kind"] for g in validate_spec({**spec, **change}, base)]
    answered = copy.deepcopy(spec)
    answered["sections"][0]["cells"][0]["token"] = "1-10-4"
    assert "geometry_in_input" in [g["kind"] for g in validate_spec(answered, base)]
    outside = copy.deepcopy(spec)
    outside["sections"][0]["cells"][0]["roi_px"] = [0, 0, 20, 20]
    assert "invalid_cell_region" in [g["kind"] for g in validate_spec(outside, base)]
    curves = {k: v for k, v in spec.items() if k not in ("input_mode", "table_value_units")}
    curves["table_reading"] = {"file": "spec.json"}
    assert "unexpected_field" in [g["kind"] for g in validate_spec(curves, base)]


def test_pipeline_run_binds_the_reading_record_and_verifies(table, tmp_path):
    work = tmp_path / "input"
    work.mkdir()
    spec = json.loads(table["spec_path"].read_text())
    (work / "table.png").write_bytes((table["root"] / "input" / "table.png").read_bytes())
    (work / "reading.json").write_text(json.dumps(record(table)))
    spec["table_reading"] = {"file": "reading.json"}
    (work / "spec.json").write_text(json.dumps(spec))
    result = reconstruct(work / "spec.json", tmp_path / "run", export_cad=False)
    assert result["status"] == "review_required", result["gaps"]
    assert result["input_mode"] == "offset_table_vision" and result["review"]["engineering_approved"] is False
    reading_hash = hashlib.sha256((work / "reading.json").read_bytes()).hexdigest()
    assert result["provenance"]["table_reading"] == {"file": "table_reading.json", "sha256": reading_hash}
    assert result["identity"]["table_reading_sha256"] == reading_hash
    assert verify_run(tmp_path / "run")["valid"] is True
    (tmp_path / "run" / "table_reading.json").write_text(json.dumps(record(table, {"c000-000": "9-9-1"})))
    assert verify_run(tmp_path / "run")["valid"] is False


def test_pipeline_without_a_reading_is_blocked_not_guessed(table, tmp_path):
    result = reconstruct(table["spec_path"], tmp_path / "run", export_cad=False)
    assert result["status"] == "blocked"
    assert "table_reading_missing" in [g["kind"] for g in result["gaps"]]
    assert result["sections"] == [] and verify_run(tmp_path / "run")["valid"] is True
