"""Structural members from midship section drawings (workstream W3, v1).

Entry point: :func:`read_section_pdf`. See docs/STRUCTURE_V1.md for the task,
the metrics and the measured results. Every output has
``engineering_approved=false``.
"""
from __future__ import annotations

from pathlib import Path

from .model import SectionResult
from .section import read_section
from .vector import read_pdf_words, read_vector_sheet, vector_path_count

RASTER_DPI = 200


def read_section_pdf(pdf_path: Path, mode: str = "auto", dpi: float = RASTER_DPI,
                     scale_mm_per_m: float | None = None) -> SectionResult:
    """Read one section sheet.

    ``mode`` is ``vector``, ``raster`` or ``auto`` (vector when the page has
    drawn paths, otherwise raster). The raster path takes words from the PDF
    text layer when there is one; it does no OCR.
    """
    pdf_path = Path(pdf_path)
    if mode == "auto":
        mode = "vector" if vector_path_count(pdf_path) > 0 else "raster"
    if mode == "vector":
        return read_section(read_vector_sheet(pdf_path), scale_mm_per_m)
    if mode == "raster":
        from .raster import render_pdf_page, sheet_from_pixels
        words = read_pdf_words(pdf_path)
        sheet = sheet_from_pixels(render_pdf_page(pdf_path, dpi), dpi, words)
        return read_section(sheet, scale_mm_per_m)
    raise ValueError(f"unknown mode {mode!r}")


__all__ = ["read_section_pdf", "read_section", "SectionResult"]
