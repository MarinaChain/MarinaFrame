"""No check rows enter tuning; missing trials cannot make a candidate pass."""

import pytest


from benchmarks.hull_fairing import replay_three_view as module


def test_tuning_rejects_check_rows_and_uses_fixed_candidate_order():
    candidates = [{"plan_weight": w, "minimum_fidelity": fidelity, "worst_follow_share": follow}
                  for w, fidelity, follow in [(8., .96, .2), (2., .96, .2), (.5, .90, .1)]]
    assert module.select_candidate(candidates)["plan_weight"] == 2.
    with pytest.raises(ValueError, match="fit"):
        module.require_fit_rows([{"split": "check", "case": "x"}])
    module.require_fit_rows([{"split": "fit", "case": "x"}])


def test_trial_summary_keeps_missing_trials_and_uses_absolute_share():
    trials = [{"kind": "cell_0.1m", "share": -.3, "available": True},
              {"kind": "cell_0.1m", "share": None, "available": False}]
    summary = module.trial_summary(trials)["cell_0.1m"]
    assert summary["planned"] == 2 and summary["available"] == 1
    assert summary["max_absolute_share"] == .3
    assert summary["target_met"] is False


def test_paired_trials_use_same_vertex_and_do_not_modify_independent_evidence():
    import numpy as np
    sections = [{"id": f"s{i}", "x_m": float(i), "source_label": "traced",
                 "points_yz_m": [[1., float(z)] for z in np.linspace(0, 2, 10)]} for i in range(5)]
    seen = []
    def fit(rows):
        seen.append(rows)
        return rows, {}
    trials = module.injection_trials(sections, 1., fit)
    assert len(trials) == 6
    assert all(t["share"] == pytest.approx(1.) for t in trials)
    assert all(len(a[1]["points_yz_m"]) == len(b[1]["points_yz_m"]) for a, b in zip(seen[::2], seen[1::2]))
