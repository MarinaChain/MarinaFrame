"""Locate DejaVu Sans, the label font for review images on every platform.

Linux hosts provide it as a system font. macOS does not, so the copy shipped
inside the locked matplotlib dependency is used. matplotlib is located without
being imported, because importing it is slow.
"""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

from PIL import ImageFont

LINUX_DEJAVU_SANS = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
MATPLOTLIB_FONT_PATH = Path("mpl-data/fonts/ttf/DejaVuSans.ttf")


def dejavu_sans_path() -> Path | None:
    if LINUX_DEJAVU_SANS.is_file():
        return LINUX_DEJAVU_SANS
    spec = find_spec("matplotlib")
    for location in (spec.submodule_search_locations or []) if spec else []:
        candidate = Path(location) / MATPLOTLIB_FONT_PATH
        if candidate.is_file():
            return candidate
    return None


def dejavu_sans(size: int) -> ImageFont.FreeTypeFont:
    """Return DejaVu Sans at size; raise OSError when no copy is available."""
    path = dejavu_sans_path()
    if path is None:
        raise OSError("DejaVu Sans font is not available")
    return ImageFont.truetype(str(path), size)
