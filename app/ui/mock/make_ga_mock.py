"""Generate mock/files/ga-1.png: a synthetic general arrangement of the mock survey launch.

A made-up 24 m vessel (not a real drawing): a profile above a deck plan, with the deckhouse,
wheelhouse, bulwark and tanks of mock/backend.js. The source records of the mock parts point at
regions of this sheet (MOCK_GA_REGIONS in mock/backend.js uses the same pixel formulas).

Run from the repository root:  .venv/bin/python app/ui/mock/make_ga_mock.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FILES = Path(__file__).resolve().parent / "files"
WIDTH, HEIGHT = 1600, 1000
PX_PER_M = 50
X0 = 200  # ship x = 0 (aft perpendicular)
PROFILE_BASE = 480  # profile: z = 0 (baseline)
PLAN_CENTRE = 770  # plan: y = 0 (centre line); port is up
INK = (32, 36, 42)
FAINT = (150, 156, 164)
PAPER = (247, 245, 239)


def px(x: float) -> float:
    return X0 + PX_PER_M * x


def pz(z: float) -> float:
    return PROFILE_BASE - PX_PER_M * z


def py(y: float) -> float:
    return PLAN_CENTRE - PX_PER_M * y


def font(size: int):
    try:
        return ImageFont.truetype("Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default()


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, WIDTH - 40, HEIGHT - 40), outline=INK, width=3)
    draw.text((80, 64), "GENERAL ARRANGEMENT  (synthetic test drawing)", fill=INK, font=font(24))
    draw.text((80, 96), "Scale 1:50   Dimensions in metres", fill=INK, font=font(14))

    # Profile: hull, main deck, bulwark, deckhouse, wheelhouse, tanks (dashed boxes).
    hull = [(px(0), pz(3.4)), (px(0), pz(1.2)), (px(2), pz(0.2)), (px(20), pz(0)), (px(23), pz(1.0)),
            (px(24), pz(3.6))]
    draw.line(hull, fill=INK, width=3)
    draw.line((px(0), pz(3.4), px(24), pz(3.6)), fill=INK, width=2)
    draw.text((px(18), pz(3.4) - 22), "MAIN DECK", fill=INK, font=font(14))
    draw.rectangle((px(0), pz(4.4), px(9), pz(3.4)), outline=INK, width=2)
    draw.rectangle((px(9), pz(5.8), px(17), pz(3.4)), outline=INK, width=2)
    draw.text((px(9.3), pz(5.8) + 6), "A DECK", fill=INK, font=font(14))
    draw.rectangle((px(11), pz(8.2), px(15.5), pz(5.8)), outline=INK, width=2)
    draw.text((px(11.3), pz(8.2) + 6), "WHEELHOUSE", fill=INK, font=font(14))
    for x0, x1, z0, z1, label in ((4, 7, 0.2, 1.4, "FW 1"), (13, 16, 0.2, 1.3, "WB 1"), (17, 19.5, 0.2, 1.2, "DO")):
        draw.rectangle((px(x0), pz(z1), px(x1), pz(z0)), outline=FAINT, width=1)
        draw.text((px(x0) + 6, pz(z1) + 4), label, fill=INK, font=font(13))

    # Plan: deck edge, deckhouse, tanks with labels.
    edge = [(px(0), py(3.4)), (px(18), py(3.6)), (px(24), py(0)), (px(18), py(-3.6)), (px(0), py(-3.4))]
    draw.line(edge + [edge[0]], fill=INK, width=3)
    draw.line((px(0), py(0), px(24), py(0)), fill=FAINT, width=1)
    draw.rectangle((px(9), py(2.6), px(17), py(-2.6)), outline=INK, width=2)
    draw.text((px(9.3), py(2.6) + 6), "DECKHOUSE", fill=INK, font=font(14))
    for x0, x1, y0, y1, label in ((4, 7, -1.5, 1.5, "FW 1"), (13, 16, 0.2, 2.4, "WB 1 P"),
                                  (13, 16, -2.4, -0.2, "WB 1 S"), (17, 19.5, -2.0, 2.0, "DO")):
        draw.rectangle((px(x0), py(y1), px(x1), py(y0)), outline=FAINT, width=1)
        draw.text((px(x0) + 6, py(y1) + 4), label, fill=INK, font=font(13))
    draw.text((80, PLAN_CENTRE - 210), "DECK PLAN", fill=INK, font=font(16))
    draw.text((80, 140), "PROFILE", fill=INK, font=font(16))

    draw.rectangle((1180, 880, WIDTH - 40, HEIGHT - 40), outline=INK, width=2)
    draw.text((1200, 892), "MOCK HULL A", fill=INK, font=font(20))
    draw.text((1200, 922), "Not a real vessel", fill=INK, font=font(13))
    image.save(FILES / "ga-1.png", optimize=True)
    print("wrote", FILES / "ga-1.png")


if __name__ == "__main__":
    main()
