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
