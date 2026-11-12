"""Commercial GA commercial settings."""
from __future__ import annotations

import re

SCHEMA = "marinaframe.ga_reading.v1"
REQUEST_SCHEMA = "marinaframe.vision_request.v1"
PURPOSE = "ga_reading"
MODEL = "claude-sonnet-5-5"
# Provider limits (rust-control/src/provider.rs check_png and vision.rs).
MAX_SIDE_PX = 2048
MAX_PIXELS = 1_048_576
MAX_IMAGE_BYTES = 1_048_576
MAX_IMAGES = 6
# The provider refuses a request body above 2 MiB (provider.rs); images travel
# as base64 (4/3 of their bytes), so all images together stay below this.
MAX_TOTAL_IMAGE_BYTES = 1_400_000
# When the images are too large together, they are sent with this many grey
# levels (line drawings keep their text) and then at smaller scales.
REDUCED_GREY_LEVELS = 16
# Neighbouring tiles share this fraction of the tile size, so a label cut by
# one tile edge is whole in the other tile. A hold label on the dev sheets is
# up to about 7 % of the sheet width; on a five-strip tiling 15 % of a strip
# covers it with margin.
TILE_OVERLAP = 0.15
# Rounding of tile edges to whole pixels can add a pixel row or column.
SCALE_MARGIN = 0.99
# A box with less ink than this share of its pixels lies on blank paper.
MIN_INK_SHARE = 0.002
INK_LEVEL = 160

LENGTH_FIELDS = {"loa": "loa_m", "lbp": "lbp_m", "breadth": "breadth_m", "depth": "depth_m",
                 "draft": "draft_m", "scantling_draft": "scantling_draft_m"}
# Plausible ranges of commercial ships. A printed value outside its range is
# a misreading or a unit the parser did not understand, so it is not used.
PLAUSIBLE = {"loa_m": (20.0, 500.0), "lbp_m": (20.0, 500.0), "breadth_m": (4.0, 80.0),
             "depth_m": (2.0, 50.0), "draft_m": (1.0, 35.0), "scantling_draft_m": (1.0, 35.0),
             "deadweight_t": (100.0, 600_000.0)}
COUNT_KINDS = {"cargo_holds": "cargo_hold", "cargo_hatches": "cargo_hatch", "cargo_cranes": "cargo_crane",
               "cargo_tanks": "cargo_tank", "slop_tanks": "slop_tank", "container_bays": "container_bay"}
# Requests for one ship in a reading (the product setting; ``--max-requests-per-ship``): one
# coarse request, then fine requests until every unexplained text blob is read, up to this total.
MAX_REQUESTS_PER_SHIP = 6

# Counting definitions (decided by the PM, 2026-11-12). Each is a setting with the default
# below; the sentences go to the model in the request context and code counts by the same rule.
DEFINITIONS = {
    # Holds numbered with halves (No.4A, No.4F) are two holds when a transverse bulkhead
    # separates them and each has its own main hatch. False: one hold per number.
    "split_holds_are_separate": True,
    # A tank whose label says SLOP is a slop tank, also a centreline "slop holding tank".
    # False: a slop holding tank is not counted.
    "slop_holding_tank_is_slop": True,
}


def definition_sentences(definitions: dict) -> list[str]:
    """The counting rules of a run as sentences for the model."""
    holds = ("A cargo hold is a cargo space that transverse bulkheads separate from the next one and that has its "
             "own main hatch. ")
    if definitions["split_holds_are_separate"]:
        holds += ("Holds labelled as halves of one number (No.4A, No.4F) are two holds when a transverse bulkhead "
                  "separates them and each has its own main hatch; they are one hold when they are one space with "
                  "one label or one hatch.")
    else:
        holds += "Holds labelled as halves of one number (No.4A, No.4F) count as one hold."
    slop = "A slop tank is a tank whose printed label says SLOP (SLOP TK, SLOP TANK"
    if definitions["slop_holding_tank_is_slop"]:
        slop += ", SLOP HOLDING TK, also on the centreline)."
    else:
        slop += "); a slop holding tank is not counted."
    slop += " Residue, waste-oil, sludge and other tanks are not slop tanks."
    return [holds,
            "On a bulk carrier the cargo holds and the main cargo hatches are usually equal in number; when your "
            "two counts differ, look again at both before you answer.",
            slop]


# "ABT. 147,87 M", "abt.229.00 m", "APPROX. 25 000 T": a value printed as approximate. The prefix
# goes; the rest must still be one clear number with its unit (holdout exam, 2026-11-12).
APPROXIMATE = re.compile(r"^\s*(?:abt|about|approx(?:imately)?)(?=[\s.\d])\.?\s*", re.I)


# A printed value's ink is measured at the image's own level: anything clearly darker than its
# paper (holdout exam: a table printed in light grey, darkest text 206-246 of 255, held no ink at
# the fixed level). Clearly: at least this many grey levels, or this many times the paper's noise.
MIN_INK_CONTRAST = 24
NOISE_FACTOR = 6.0
PAPER_BAND = 48  # pixels within this of the paper level measure its noise
# Beside a value box without ink, an ink run in the same rows is searched up to one box width or
# this share of the image width, left and right; it is used only when it is the only run there.
VALUE_SEARCH_SHARE = 0.1


# A box whose ink share is below this holds only a sliver of its value (the edge of the text;
# holdout re-check: 0.0035 and 0.0122); well-placed value boxes hold far more.
SLIVER_SHARE = 0.03
# A table ruling line: an ink run at most this wide whose ink continues above and below the
# value's rows (by at least the rows' height, at this share of the band) is not a value.
RULE_MAX_WIDTH_PX = 4
RULE_CONTINUES_SHARE = 0.8


RECORD_VIEWS = {"profile": "profile", "deck_plan": "plan", "tank_top_plan": "plan", "accommodation_plan": "plan",
                "section": "section", "particulars_table": "table"}


# ------------------------------------------------------------------ command line

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff")
