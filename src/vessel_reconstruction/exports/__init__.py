"""Exports of a built draft for a naval architect (docs/APP_SPEC.md, section "Exports").

``export_draft(task_dir, "r3", out_dir)`` writes the offsets table CSV, the
hydrostatics summary, the PDF review report, stamped STEP and STL copies, a
manifest with SHA-256 hashes and a zip of all of them. Every file name has the
vessel, the revision and "DRAFT"; every file carries the draft stamp.
Command line: ``python -m vessel_reconstruction.exports --task DIR --revision rN --out DIR``.
"""
from .package import export_draft
from .source import ExportError

__all__ = ["ExportError", "export_draft"]
