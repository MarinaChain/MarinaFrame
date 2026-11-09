"""Measured error bands of the three outputs (hull, tanks, steel): one table, one source.

Every band is a result that a committed document reports. The band says what was measured, on
how many cases, whether the cases were development data (the code was tuned on them) or a
holdout (read once, after the protocol was fixed), and where the document states it. A band
that was never measured says "not measured"; no number is filled in.

The run summary (``accuracy_summary``), the PDF report and the app read this table. The app's
copy is generated into ``app/ui/js/accuracy_bands.js`` by ``scripts/export_accuracy_bands.py``,
and a test fails when that file is out of date.

All of these are measurements on other ships and sheets. None of them is a measurement of the run
at hand, and none of them approves a result.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

OUTPUTS = ("hull", "tanks", "steel")
DATASETS = ("development", "holdout", "none")
OUTCOMES = ("met", "missed", "mixed", "not measured", "invalid")


@dataclass(frozen=True)
class Band:
    """One measured error band."""

    id: str
    output: str  # "hull", "tanks" or "steel"
    scope: str  # what was measured, in plain words
    short: str  # the band as one phrase for a summary line
    chip: str  # the band as a few characters for a compact indicator
    dataset: str  # "development", "holdout" or "none" (not measured)
    n: str  # how many sheets, ships or items
    source: str  # repository document
    section: str  # heading of the document section that reports it
    outcome: str  # "met", "missed", "mixed", "not measured" or "invalid"
    caveat: str  # the main limit of the number

    @property
    def measured(self) -> bool:
        return self.outcome != "not measured"


BANDS: tuple[Band, ...] = (
    # ------------------------------------------------------------------ hull
    Band(
        id="hull.model_reading_clean", output="hull",
        scope="Hull read from a three-view lines sheet by the model and the code (first-hull path)",
        short="measured on clean synthetic sheets only: RMS 0.8 to 14 % of half-beam, 4 of 10 within the 2 % gate",
        chip="0.8-14 %", dataset="development", n="10 cases (5 L0, 5 L1)",
        source="docs/HULL_SELECTION.md", section="7", outcome="mixed",
        caveat="Clean synthetic sheets and one pass of one model; not scans. The code was tuned on these "
               "cases. Half-beam RMS only; the 5 % volume gate is reported in section 6 of the same document."),
    Band(
        id="hull.scanned_bue_girl", output="hull",
        scope="Hull from a scanned body plan with a printed table (code-only station names)",
        short="1.4 mm RMS on BUE GIRL (holdout, round bilge)",
        chip="1.4 mm", dataset="holdout", n="1 sheet, 37 of 39 cells",
        source="docs/WHOLE_VESSEL_GUNNERUS.md", section="5.9", outcome="met",
        caveat="One sheet. Two cells were not read; seven extra cells at the fore sheer are not in the score."),
    Band(
        id="hull.scanned_bumble_bee", output="hull",
        scope="Hull from a scanned body plan with a printed table (code-only station names)",
        short="0.11 m RMS on BUMBLE BEE 47 (holdout, round bilge; some station numbers wrong)",
        chip="0.11 m", dataset="holdout", n="1 sheet, 50 of 54 cells",
        source="docs/holdouts/round13-bumble-bee.md", section="Measured decision and model value",
        outcome="invalid",
        caveat="Invalid: the sheet calibration swapped bow and stern; not a measure of the reader."),
    Band(
        id="hull.scanned_thayer", output="hull",
        scope="Hull from a scanned body plan with a printed table",
        short="0.09 m RMS on C.A. Thayer with model station labels, 0.68 m without (holdout)",
        chip="0.09-0.68 m", dataset="holdout", n="1 sheet, 150 of 151 cells",
        source="docs/WHOLE_VESSEL_GUNNERUS.md", section="5.5", outcome="mixed",
        caveat="Code alone failed; with model labels the RMS passes but three stations keep wrong names "
               "(errors up to 0.52 m). The sheet is no longer a holdout."),
    Band(
        id="hull.scanned_pardon_me", output="hull",
        scope="Hull from a scanned body plan with a printed table",
        short="missed on PARDON ME (holdout, hard chine): 34 of 57 cells read",
        chip="missed", dataset="holdout", n="1 sheet, 34 of 57 cells",
        source="docs/holdouts/round14-pardon-me.md", section="11.1", outcome="missed",
        caveat="Hard-chine hull: station pieces are not joined across the chine. RMS 0.13 m is only on the "
               "cells that were read, and the largest error is 0.64 m."),
    Band(
        id="hull.vector_gunnerus", output="hull",
        scope="Hull from vector (CAD) drawings",
        short="13.5 mm median against a printed section (Gunnerus, development)",
        chip="13.5 mm", dataset="development", n="1 ship, 44 points",
        source="docs/STRUCTURE_V2.md", section="9.2", outcome="met",
        caveat="One ship and one section; 95th percentile 36.5 mm, largest 39.1 mm. The deck level at "
               "the stern differs from the drawn section by 172.5 mm."),
    # ------------------------------------------------------------------ tanks
    Band(
        id="tanks.vector_gunnerus", output="tanks",
        scope="Tank volumes from a vector (DXF) capacity plan, against the printed net volumes",
        short="median 10 % off the printed volume on a vector plan (21 tanks, development)",
        chip="10 %", dataset="development", n="1 ship, 21 tanks",
        source="docs/TANKS_V1.md", section="5.2.1", outcome="met",
        caveat="9 of 21 tanks within 10 %, 1 within 3 %. Group totals: miscellaneous tanks +57.8 %, "
               "grand total of four groups +4.3 %. Printed net volumes exclude structure."),
    Band(
        id="tanks.raster_dev", output="tanks",
        scope="Tank volumes from a scanned (raster) capacity plan, against the printed volumes",
        short="scanned plans, development: median 9 % on one plan and 40 % on another (datum differs)",
        chip="9-40 %", dataset="development", n="2 plans (20 and 17 matched tanks)",
        source="docs/TANKS_V2.md", section="7.1", outcome="mixed",
        caveat="The two Gunnerus drawings disagree on the tank-top datum, so double-bottom tanks are "
               "about 40 % high on the second plan. The code was tuned on both plans."),
    Band(
        id="tanks.raster_holdout", output="tanks",
        scope="Tank volumes from a scanned (raster) capacity plan of a ship the code had not seen",
        short="scanned plan holdout missed (Huddell: 0 of 22 tanks matched)",
        chip="missed", dataset="holdout", n="1 ship, 22 tank rows",
        source="docs/TANKS_V2.md", section="6", outcome="missed",
        caveat="The frame axis was not found on any view. Huddell is spent as a holdout; a fresh holdout "
               "ship is still needed."),
    Band(
        id="tanks.raster_after_fix", output="tanks",
        scope="The same Huddell plans after fixes (not a holdout any more)",
        short="after fixes 14 of 22 tanks matched, median 29 %, total -43 % (development)",
        chip="29 %", dataset="development", n="1 ship, 14 of 22 tank rows",
        source="docs/TANKS_V2.md", section="7.1", outcome="missed",
        caveat="Misses the round 2 targets (median 25 %, total within 25 %). Deep tanks 3 P/S "
               "(24 % of the truth total) are not built."),
    # ------------------------------------------------------------------ steel
    Band(
        id="steel.positions", output="steel",
        scope="Member positions of the Gunnerus parallel-body steel, against the printed drawing",
        short="positions match the printed drawing: median 0.0 mm on 35 pairs (development)",
        chip="pos 0 mm", dataset="development", n="1 ship, 35 pairs",
        source="docs/STRUCTURE_V2.md", section="9.2", outcome="mixed",
        caveat="Printed against printed, on CAD drawings. Of 7 level checks, 3 differ by 88.5 to 172.5 mm "
               "(tank top and deck levels)."),
    Band(
        id="steel.members_midship", output="steel",
        scope="Member detection and steel volume on 12 midship-block designs, against their 3D truth",
        short="12 designs: member F1 0.48, transverse recall 0.35, steel volume 4.1 % low (development)",
        chip="vol 4 %", dataset="development", n="12 designs, 18,244 members",
        source="docs/STRUCTURE_V2.md", section="7.2", outcome="mixed",
        caveat="Misses the detection targets (F1 0.80, transverse recall 0.60). Volume is steel volume "
               "against truth, not a printed weight."),
    Band(
        id="steel.weight", output="steel",
        scope="Steel weight against a printed lightweight or steel weight",
        short="weight not measured against a printed weight",
        chip="wt n/m", dataset="none", n="not measured",
        source="docs/STRUCTURE_V2.md", section="9.2", outcome="not measured",
        caveat="No printed weight was found on the Gunnerus sheets. Weight is area x thickness x 7.85 t/m3, "
               "with the density and any unprinted thickness labelled guessed."),
)

_BY_ID = {band.id: band for band in BANDS}


def band(band_id: str) -> Band:
    """The band with this id; ``KeyError`` for an unknown id."""
    return _BY_ID[band_id]


def bands_for(output: str) -> tuple[Band, ...]:
    return tuple(b for b in BANDS if b.output == output)


def bands_as_dicts() -> list[dict]:
    """The table as plain dicts, in order (for the app's generated copy)."""
    return [{**asdict(b), "measured": b.measured} for b in BANDS]
