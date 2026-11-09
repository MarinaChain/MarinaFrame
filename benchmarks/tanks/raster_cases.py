"""Host calibration of the raster tank-plan cases (docs/TANKS_V2.md section 2).

A person read these from the sheets without the truth: the window of each view (shares of the
sheet width and height), whether it is a profile or a plan and the plan's role, the frame spacing
printed on the sheet or the window of the graphic scale bar, and the window of the tank schedule.
No geometry is given here: scale, frame positions, boundaries and heights are read by code.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from vessel_reconstruction.tank_plan_raster import FEET_M, INK_THRESHOLD, SheetSpec, ViewSpec


def _share(x0, y0, x1, y1, width, height):
    """A window measured on a reduced preview image of the sheet, as shares of the sheet."""
    return (x0 / width, y0 / height, x1 / width, y1 / height)


# Windows were measured on 40 dpi previews (1873 x 1325 px) of the A0 sheets.
PREVIEW = (1873, 1325)

GUNNERUS_TANK_PLAN = SheetSpec(
    views=[ViewSpec('profile', 'profile', _share(60, 655, 1250, 875, *PREVIEW)),
           ViewSpec('tank_top', 'plan', _share(60, 940, 1215, 1262, *PREVIEW), role='double_bottom')],
    frame_spacing_m=0.500,  # main dimensions table: "FRAME DISTANCE 500 MM"
    schedule=_share(1160, 52, 1850, 565, *PREVIEW))

GUNNERUS_TANK_ARRANGEMENT = SheetSpec(
    views=[ViewSpec('profile', 'profile', _share(40, 460, 1000, 606, *PREVIEW)),
           ViewSpec('below_1_deck', 'plan', _share(40, 648, 1000, 897, *PREVIEW), role='above'),
           ViewSpec('below_tank_top', 'plan', _share(40, 915, 1000, 1172, *PREVIEW), role='double_bottom')],
    frame_spacing_m=0.500,  # main particulars: "FRAME DISTANCE 500 (mm)"
    schedule=_share(1070, 385, 1392, 870, *PREVIEW))

# HAER sheets (400 dpi bilevel TIFF). Windows measured on 1/8 previews.
SAUGATUCK_SHEET4 = SheetSpec(
    views=[ViewSpec('profile', 'profile', _share(240, 270, 1950, 520, 2200, 1700)),
           ViewSpec('second_deck_and_hold', 'plan', _share(240, 1095, 1880, 1320, 2200, 1700), role='above')],
    scale_bar=_share(395, 1478, 1795, 1530, 2200, 1700), scale_bar_unit_m=FEET_M)

CASES = {
    'gunnerus_tank_plan': ('gunnerus/polarkonsult/Tank Plan Rev1.pdf', GUNNERUS_TANK_PLAN),
    'gunnerus_tank_arrangement': ('gunnerus/extended/CJOB/Tank Arrangement Rev0.pdf', GUNNERUS_TANK_ARRANGEMENT),
    'saugatuck': ('tanks-public/saugatuck_haer_va128/Capacity_Plan_Profile,_Upper_Deck_Capacity_Plan,_Second_Deck_and_'
                  'Hold_Capacity_Plan_-_Saugatuck,_James_River_Reserve_Fleet,_Newport_News,_Newport_News,_VA_HAER_'
                  'VA-128_(sheet_4_of_6).tif', SAUGATUCK_SHEET4),
}

# Scan variant (docs/TANKS_V2.md section 2): skew, blur, grey noise, 1-bit threshold, flips.
SCAN_SKEW_DEG = 0.2
SCAN_BLUR_SIGMA_PX = 0.8
SCAN_NOISE_SIGMA = 12.0
SCAN_FLIP_SHARE = 0.001


def render_pdf(path: Path, dpi: int) -> np.ndarray:
    """Grey page (uint8) of a one-page PDF."""
    import fitz

    with fitz.open(path) as document:
        pixmap = document[0].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
        return np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width).copy()


def scan_variant(grey: np.ndarray, seed: int = 0) -> np.ndarray:
    """Ink mask of a simulated bilevel scan of a grey page."""
    import cv2

    rng = np.random.default_rng(seed)
    height, width = grey.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), SCAN_SKEW_DEG, 1.0)
    turned = cv2.warpAffine(grey, matrix, (width, height), flags=cv2.INTER_LINEAR, borderValue=255)
    blurred = cv2.GaussianBlur(turned, (0, 0), SCAN_BLUR_SIGMA_PX).astype(np.float32)
    blurred += rng.normal(0, SCAN_NOISE_SIGMA, blurred.shape).astype(np.float32)
    ink = blurred < INK_THRESHOLD
    flips = rng.random(ink.shape) < SCAN_FLIP_SHARE
    return ink ^ flips


def load_case(sources: Path, case: str, dpi: int | None, scan: bool) -> tuple[np.ndarray, float, SheetSpec]:
    """Ink mask, its dpi and the sheet description of a case."""
    from vessel_reconstruction.body_plan_crossings import load_ink

    relative, spec = CASES[case]
    path = sources / relative
    if path.suffix.lower() == '.pdf':
        grey = render_pdf(path, dpi or 300)
        ink = scan_variant(grey) if scan else grey < INK_THRESHOLD
        return ink, float(dpi or 300), spec
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(path) as image:
        sheet_dpi = float((image.info.get('dpi') or (400, 400))[0])
    return load_ink(path), sheet_dpi, spec
