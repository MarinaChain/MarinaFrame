"""The measured error bands: one table, every band with a source, the app's copy up to date."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

from vessel_reconstruction.accuracy_bands import BANDS, DATASETS, OUTCOMES, OUTPUTS, band, bands_for

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def heading_titles(doc: Path) -> list[str]:
    return [line.lstrip("#").strip() for line in doc.read_text(encoding="utf-8").splitlines() if line.startswith("#")]


def test_ids_are_unique_and_every_output_has_bands():
    ids = [b.id for b in BANDS]
    assert len(ids) == len(set(ids))
    for output in OUTPUTS:
        assert bands_for(output), output
        assert all(b.id.startswith(f"{output}.") for b in bands_for(output))


@pytest.mark.parametrize("item", BANDS, ids=lambda b: b.id)
def test_every_band_cites_a_source_section_that_exists(item):
    assert item.source and item.section and item.n and item.short and item.chip and item.caveat
    doc = ROOT / item.source
    assert doc.is_file(), f"{item.id}: {item.source} is not in the repository"
    assert any(title.startswith(item.section) for title in heading_titles(doc)), (
        f"{item.id}: no heading of {item.source} starts with {item.section!r}")


@pytest.mark.parametrize("item", BANDS, ids=lambda b: b.id)
def test_dataset_and_outcome_are_known_and_unmeasured_bands_say_so(item):
    assert item.dataset in DATASETS and item.outcome in OUTCOMES
    if item.outcome == "not measured":
        assert item.dataset == "none" and item.n == "not measured"
    else:
        assert item.dataset in ("development", "holdout") and item.measured


def test_the_unmeasured_band_is_steel_weight():
    assert [b.id for b in BANDS if not b.measured] == ["steel.weight"]


def test_wording_makes_no_approval_claim():
    for item in BANDS:
        text = " ".join((item.scope, item.short, item.caveat)).lower()
        assert "approved" not in text and "verified" not in text, item.id


def test_known_holdout_results_are_in_the_table():
    assert band("hull.scanned_bue_girl").dataset == "holdout" and "1.4 mm" in band("hull.scanned_bue_girl").short
    assert band("hull.scanned_pardon_me").outcome == "missed"
    assert band("tanks.raster_holdout").outcome == "missed"


def test_the_apps_copy_is_up_to_date():
    from export_accuracy_bands import TARGET, render

    assert TARGET.read_text(encoding="utf-8") == render(), (
        "run: PYTHONPATH=src python scripts/export_accuracy_bands.py")
