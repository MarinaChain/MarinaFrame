"""Gunnerus whole-vessel detail: the hull side and the drawn shape of the parts above the hull.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, section 3.8 (development case).
"""
from __future__ import annotations

from pathlib import Path

LINES_FILE = 'polarkonsult/Lines Plan Rev0.dxf'


def hull_sections(sources: Path) -> list[dict]:
    """The lines-plan station sections that the hull loft uses (read only, no CAD).

    The stations are not cut at the deck: above the deck they are the drawn shell of the
    bulwark and the forecastle, which the parts above the hull must follow.
    """
    from benchmarks.gunnerus import make_gunnerus_configs, vector_path

    config, _ = make_gunnerus_configs.vector_config(sources / LINES_FILE)
    return vector_path.read_sections(config, sources / LINES_FILE)['sections']


MIDSHIP_FILE = 'polarkonsult/Midship Section Rev0.dxf'
BREADTH_M = 9.60  # title block
# Standard deck camber when no section drawing gives one: B/50 at the centreline.
STANDARD_CAMBER_FRACTION = 1 / 50
DECK_PARTS = ('aft_deck', 'main_deck')


def labelled(value, source: str, basis: str) -> dict:
    return {'value': value, 'source': source, 'basis': basis}


def deck_camber(sources: Path) -> dict:
    """Camber read from the midship-section deck lines, else the standard B/50 (guessed)."""
    from vessel_reconstruction.ga_reader import section_deck_camber

    path = sources / MIDSHIP_FILE
    read = section_deck_camber(path) if path.is_file() else None
    if read is not None:
        shape = 'straight level lines: no camber' if read['camber_m'] == 0 else 'median rise'
        return labelled(read['camber_m'], 'traced', f'midship section: {read["sections"]} labelled 1-DECK '
                        f'moulded lines, rise {read["rises_m"]} m ({shape})')
    camber = round(BREADTH_M * STANDARD_CAMBER_FRACTION, 3)
    return labelled(camber, 'guessed', 'no deck line read in a section drawing; standard camber B/50')


def add_detail(inputs: dict, sources: Path) -> dict:
    """Add ``inputs['detail']``: the hull side and the labelled detail values of each part."""
    from vessel_reconstruction.superstructure import HullSide

    sections = hull_sections(sources)
    hull = HullSide.from_sections(sections)
    camber = deck_camber(sources)
    parts = {part: {'camber_m': camber} for part in DECK_PARTS}
    inputs['detail'] = {
        'hull_side': labelled(hull.to_dict(), 'traced',
                              f'lines plan: {len(sections)} station sections, not cut at the deck; above a '
                              'drawn top the flare of the top rows continues for at most 1.5 m'),
        'parts': parts}
    return inputs['detail']
