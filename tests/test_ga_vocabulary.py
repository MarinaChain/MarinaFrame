"""Both GA reading passes share one label vocabulary (ga_vocabulary), with no copies."""
import pytest

from vessel_reconstruction import ga_counts, ga_labels, ga_vocabulary, source_record
from vessel_reconstruction.ga_commercial_settings import DEFINITIONS


@pytest.mark.parametrize("label", ["CR.1", "CR. 2", "CR 3", "NO.4 CR.", "CARGO CR.1", "CRANE 1"])
def test_cargo_crane_abbreviations_keep_their_kind_and_source_box(label):
    kind = ga_labels.label_kind("cargo_crane", label, DEFINITIONS)
    assert kind == "cargo_crane"
    record = source_record.read([source_record.region("synthetic.png", view="v1", box_px=[10, 20, 40, 50])])
    crane = {"label": label, "kind": kind, "number": "1", "source_record": record}
    other = {"label": "CRANE 1", "kind": "cargo_crane", "number": "1", "source_record": record}
    result = {"spaces": [crane, other], "checks": []}
    assert ga_counts.drop_fragments(result) == 0
    assert result["spaces"][0]["source_record"] == record


@pytest.mark.parametrize("label", ["HOSE CR.1", "PROVISION CR.2", "ENGINE CR.3", "DAVIT CR.4", "CROSS 1"])
def test_non_cargo_cranes_and_unrelated_prefixes_are_not_cargo_cranes(label):
    assert ga_labels.label_kind("cargo_crane", label, DEFINITIONS) == "other_space"


def test_access_hatch_is_not_promoted_to_cargo_hatch():
    assert ga_labels.label_kind("other_space", "ACCESS HATCH", DEFINITIONS) == "other_space"


def test_fine_pass_vocabulary_exports_are_shared():
    for name in ("KIND_WORDS", "PROMOTIONS", "CUT_REASONS"):
        assert getattr(ga_labels, name) is getattr(ga_vocabulary, name)


def test_coarse_pass_vocabulary_is_shared():
    for name in ("FITTING_WORDS", "ROOM_NOUNS", "SYSTEM_WORDS", "DECK_NAME_WORDS", "NOTE_WORDS"):
        assert getattr(ga_counts, name) is getattr(ga_vocabulary, name)
