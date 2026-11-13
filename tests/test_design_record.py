"""Design record contract and lossless result transport."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_design_record_api_exists():
    assert importlib.util.find_spec("vessel_reconstruction.design_record") is not None


def test_schema_is_valid():
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(json.loads((ROOT / "schemas/design-record-v1.schema.json").read_text()))


def test_fixture_roundtrip(tmp_path):
    from vessel_reconstruction.design_record import DesignRecord
    data = json.loads((ROOT / "tests/fixtures/design_record/kvlcc2.json").read_text())
    record = DesignRecord.from_dict(data)
    path = tmp_path / "record.json"
    record.save(path)
    assert DesignRecord.load(path).to_dict() == data
    detached = record.to_dict()
    detached["name"] = "changed"
    assert record.to_dict() == data


def test_shared_invalid_records():
    from vessel_reconstruction.design_record import DesignRecord
    fixture = json.loads((ROOT / "tests/fixtures/design_record/kvlcc2.json").read_text())
    cases = json.loads((ROOT / "tests/fixtures/design_record/invalid.json").read_text())
    for case in cases:
        data = copy.deepcopy(fixture)
        parent = data
        for part in case["path"][:-1]:
            parent = parent[part]
        if case.get("delete"):
            del parent[case["path"][-1]]
        else:
            parent[case["path"][-1]] = case["value"]
        with pytest.raises(ValueError, match=".+"):
            DesignRecord.from_dict(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_rejected(value):
    from vessel_reconstruction.design_record import DesignRecord
    data = json.loads((ROOT / "tests/fixtures/design_record/kvlcc2.json").read_text())
    data["main_dimensions"]["length"]["value"] = value
    with pytest.raises(ValueError):
        DesignRecord.from_dict(data)


def test_result_evidence_is_lossless():
    from vessel_reconstruction.design_record import capture_result, restore_result
    source = {"value": 1.2345678901234567, "nested": [None, True, "draft", -2, {"x_m": 1.0}], "engineering_approved": False}
    evidence = capture_result(source, units={"value": "1", "x_m": "m", "nested": "1"}, method="test", method_version="1", sources=["synthetic"])
    assert restore_result(evidence) == source
    assert evidence["value"]["value"]["value"]["unit"] == "1"
    with pytest.raises(ValueError, match="unit"):
        capture_result({"unknown": 3}, units={}, method="test", method_version="1", sources=[])
