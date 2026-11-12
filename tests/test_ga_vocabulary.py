"""Both GA reading passes share vocabulary without breaking old imports."""
from vessel_reconstruction import ga_commercial, ga_labels, ga_vocabulary


def test_fine_pass_vocabulary_exports_are_shared():
    for name in ("KIND_WORDS", "PROMOTIONS", "CUT_REASONS"):
        assert getattr(ga_labels, name) is getattr(ga_vocabulary, name)


def test_coarse_pass_vocabulary_exports_are_shared():
    for name in ("FITTING_WORDS", "ROOM_NOUNS", "SYSTEM_WORDS", "DECK_NAME_WORDS", "NOTE_WORDS"):
        assert getattr(ga_commercial, name) is getattr(ga_vocabulary, name)
