"""Exercise every section, uncertainty branch and customer/decision fields."""
import json
from pathlib import Path

import pytest

from vessel_reconstruction.design_record import DesignRecord

FIXTURE = Path(__file__).parent / "fixtures/design_record/kvlcc2.json"


def test_populated_record_and_isolated_scope():
    data = json.loads(FIXTURE.read_text())
    q = data["main_dimensions"]["length"].copy()
    q.update(uncertainty={"kind": "absolute", "lower": 1, "upper": 2, "basis": "synthetic example"}, uncertainty_reason=None)
    component = dict(id="synthetic-component", kind="synthetic", quantities={"length": q}, labels={"purpose": "contract test"}, files=[], notes=[])
    for name in ["compartments", "tanks", "weights", "loading_conditions", "midship_section_inputs", "appendages"]:
        data[name] = [component]
    data["requirements"]["constraints"] = [component]
    data["data_scope"] = dict(kind="customer", customer_id="synthetic-tenant", permitted_uses=["development"])
    data["designer_decisions"] = [dict(id="choice-1", candidate_id=data["design_id"], action="deferred", reason="Synthetic test only", designer_id="synthetic-designer", recorded_at="2026-11-13T00:00:00Z", status="review_required")]
    assert DesignRecord.from_dict(data).to_dict() == data


def test_duplicate_json_field_fails():
    with pytest.raises(ValueError, match="Duplicate JSON field"):
        DesignRecord.loads('{"name":"one","name":"two"}')


def test_save_rechecks_private_mutation():
    record = DesignRecord.load(FIXTURE)
    record._data["engineering_approved"] = True
    with pytest.raises(ValueError):
        record.to_json()


def test_unknown_future_fields_never_migrate():
    data = json.loads(FIXTURE.read_text())
    data["future_section"] = {}
    with pytest.raises(ValueError):
        DesignRecord.from_dict(data)
