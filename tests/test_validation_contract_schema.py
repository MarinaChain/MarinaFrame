"""Validate the published protocol schema with the full optional validator."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema", reason="Install pinned requirements-data-linux-py312.lock for full Draft 2020-12 validation")

from vessel_reconstruction.validation_contract import ValidationContractError, validate_contract_shape

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/candidate-validation-v1.schema.json").read_text())
jsonschema.Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
PASSED = json.loads((ROOT / "tests/fixtures/validation_contract/passed.json").read_text())


@pytest.mark.parametrize("name", ["passed.json", "failed.json", "failed-native.json"])
def test_complete_protocol_fixture_passes_full_draft202012_and_runtime_shape(name):
    fixture = json.loads((ROOT / "tests/fixtures/validation_contract" / name).read_text())
    VALIDATOR.validate(fixture)
    validate_contract_shape(fixture)


@pytest.mark.parametrize("field", SCHEMA["required"])
def test_required_contract_field_cannot_be_omitted(field):
    fixture = deepcopy(PASSED)
    del fixture[field]
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(fixture)
    with pytest.raises(ValidationContractError):
        validate_contract_shape(fixture)


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "marinaframe.validation.v999"),
    (("engineering_approved",), 0),
    (("engineering_approved",), True),
    (("engineering_approved",), None),
    (("extra",), "unknown"),
    (("checks", "worker_execution"), "cancelled"),
    (("checks", "trace_fidelity"), "failed"),
    (("checks", "cad_validity"), True),
    (("outcome",), "failed"),
    (("units", "reported"), "mm"),
    (("tolerances", "max_section_distance_m"), 0.01),
    (("binding", "revision_id"), "previous"),
    (("binding", "step_sha256"), "missing"),
    (("sampling", "section_ids"), ["s0", "s0", "s0"]),
])
def test_schema_and_runtime_reject_malformed_or_contradictory_fields(path, value):
    fixture = deepcopy(PASSED)
    target = fixture
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(fixture)
    with pytest.raises(ValidationContractError):
        validate_contract_shape(fixture)
