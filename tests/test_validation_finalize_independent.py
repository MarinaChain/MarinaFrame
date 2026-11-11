"""Author-separated regression expectations from actual finalization findings.

Native execution is doubled by the explicitly controlled existing fixture. The
finalization interleavings (selection race, cancellation after the predicate)
are guarded in Rust: rust-control/tests/finalization_guards.rs.
"""
import json

import pytest

from validation_fixture import ControlledValidationDomain


@pytest.mark.parametrize('bad_revision',[False,True,0.0,-1,10**12,None])
def test_malformed_persisted_revision_is_rejected_without_recovery_promotion(tmp_path,bad_revision):
    domain=ControlledValidationDomain(tmp_path/'task',maximum=.0005)
    assert domain.execute('validate_candidate',{})['ok'] is True
    state=json.loads(domain.state_path.read_text());state['revision']=bad_revision
    domain.state_path.write_text(json.dumps(state))
    # A live object must reject cleanly instead of formatting invalid state again
    # in its error-observation path. A newly opened object must refuse admission.
    result=domain.execute('validate_candidate',{})
    assert result['ok'] is False
    with pytest.raises((ValueError,TypeError)):
        ControlledValidationDomain(domain.task_dir,maximum=.0005)
