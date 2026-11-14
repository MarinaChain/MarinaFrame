"""Aggregate export must not disclose condition identifiers or values."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from investigate_thin_ship_bulbs import export_summary


def test_export_removes_identifiers_and_raw_values(tmp_path):
    row = {"id": "synthetic-private-id", "section_error_m": 0,
           "variants": {"baseline": {"cw": 1, "reference_error_percent": 2}}}
    (tmp_path / "experiments.jsonl").write_text(json.dumps(row) + "\n")
    (tmp_path / "reference-refinement.json").write_text(json.dumps([
        {"id": "synthetic-private-id", "error_percent": 2,
         "cw": 1, "reference_cw": 1.02}]))
    (tmp_path / "splits.json").write_text("{}")
    output = tmp_path / "public.json"
    export_summary(tmp_path, output)
    data = output.read_text()
    assert "synthetic-private-id" not in data
    assert '"reference_cw"' not in data
    assert json.loads(data)["original_gate"] == "FAIL; unchanged"
