"""Explicit version selection and lossless migration of draft records."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from vessel_reconstruction import design_record as contract

ROOT = Path(__file__).resolve().parents[1]
NEW_UNITS = ("g CO2/(t nm)", "nm")


def fixture():
    return json.loads((ROOT / "tests/fixtures/design_record/kvlcc2.json").read_text())


def test_v1_1_schema_only_extends_version_and_units():
    old = json.loads((ROOT / "schemas/design-record-v1.schema.json").read_text())
    new = json.loads((ROOT / "schemas/design-record-v1.1.schema.json").read_text())
    Draft202012Validator.check_schema(new)
    expected = copy.deepcopy(old)
    expected["$id"] = "urn:marinaframe:design-record:1.1.0"
    expected["title"] = "MarinaFrame design record v1.1"
    expected["properties"]["schema_version"]["const"] = "1.1.0"
    expected["$defs"]["quantity"]["properties"]["unit"]["enum"].extend(NEW_UNITS)
    assert new == expected
    assert contract.SCHEMA_VERSION == "1.0.0"  # Existing builders stay on v1.


def test_migration_preserves_data_and_detaches_input():
    source = fixture()
    original = copy.deepcopy(source)
    migrated = contract.migrate_v1_0_0_to_v1_1_0(source)
    assert source == original
    expected = copy.deepcopy(original)
    expected["schema_version"] = "1.1.0"
    assert migrated == expected
    assert contract.DesignRecord.from_dict(migrated).to_dict() == expected
    migrated["main_dimensions"]["length"]["value"] = 9
    assert source == original


@pytest.mark.parametrize("unit", NEW_UNITS)
def test_efficiency_units_require_explicit_v1_1(unit, tmp_path):
    source = fixture()
    source["main_dimensions"]["length"]["unit"] = unit
    with pytest.raises(ValueError):
        contract.DesignRecord.from_dict(source)
    source["schema_version"] = "1.1.0"
    record = contract.DesignRecord.from_dict(source)
    path = tmp_path / "record.json"
    record.save(path)
    assert contract.DesignRecord.load(path).to_dict() == source


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0", "2.0.0", None])
def test_migration_requires_v1_0_source(version):
    source = fixture()
    source["schema_version"] = version
    with pytest.raises(ValueError):
        contract.migrate_v1_0_0_to_v1_1_0(source)


@pytest.mark.parametrize("mutation", ["unknown", "speed", "unit", "approval"])
def test_migration_validates_source_without_dropping_fields(mutation):
    source = fixture()
    if mutation == "unknown":
        source["unknown"] = {"preserve_me": 12}
    elif mutation == "speed":
        source["requirements"]["service_speed"]["kn"]["value"] = 500
    elif mutation == "unit":
        source["main_dimensions"]["length"]["unit"] = "nm"
    else:
        source["engineering_approved"] = True
    original = copy.deepcopy(source)
    with pytest.raises(ValueError):
        contract.migrate_v1_0_0_to_v1_1_0(source)
    assert source == original


def test_v1_1_keeps_strict_validation():
    source = fixture()
    source["schema_version"] = "1.1.0"
    source["main_dimensions"]["length"]["unit"] = "invented"
    with pytest.raises(ValueError):
        contract.DesignRecord.from_dict(source)
    source["main_dimensions"]["length"]["unit"] = "nm"
    source["extra"] = 1
    with pytest.raises(ValueError):
        contract.DesignRecord.from_dict(source)
