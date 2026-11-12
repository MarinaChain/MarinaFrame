"""Both GA reading passes share one label vocabulary (ga_vocabulary), with no copies."""
from vessel_reconstruction import ga_counts, ga_labels, ga_vocabulary


def test_fine_pass_vocabulary_exports_are_shared():
    for name in ("KIND_WORDS", "PROMOTIONS", "CUT_REASONS"):
        assert getattr(ga_labels, name) is getattr(ga_vocabulary, name)


def test_coarse_pass_vocabulary_is_shared():
    for name in ("FITTING_WORDS", "ROOM_NOUNS", "SYSTEM_WORDS", "DECK_NAME_WORDS", "NOTE_WORDS"):
        assert getattr(ga_counts, name) is getattr(ga_vocabulary, name)
