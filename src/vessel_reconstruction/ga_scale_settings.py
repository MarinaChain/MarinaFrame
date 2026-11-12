"""Commercial GA settings; rules and constants unchanged."""
from __future__ import annotations

import re

PURPOSE = "ga_scale"
REQUEST_SCHEMA = "marinaframe.vision_request.v1"
INPUT_SCHEMA = "marinaframe.ga_reading.v1"
MEASURED = "measured_from_scale"
# A depth that was not measured at the deck line: the median top of the read cargo spaces took
# the place of a pointed line that was the deck at the centreline, a rail, or missing. It is an
# estimate; downstream must not treat it as measured (and must not check it against those tops).
DERIVED = "derived_from_space_tops"
# A pointed depth that only boxes with an uncertain boundary agree with: shown, never measured.
UNCONFIRMED = "unconfirmed_from_uncertain_boxes"

# Frame spacings of commercial ships (mm): ordinary frames from about 500 mm, numbered web frames
# of large tankers up to a few metres. A printed spacing outside this range is a misreading.
SPACING_RANGE_MM = (300.0, 5000.0)
# A spacing printed without a unit is metres below this value ("F.S. 0.70") and millimetres
# above it ("FR. SP. 800"); only one of the two lies in the range above.
UNITLESS_METRES_BELOW = 10.0
# A frame scale needs this many frame numbers that fit the spacings.
MIN_TICKS = 4
# A tick whose place is further from the fitted scale than this is a misread number or a place
# pointed wrongly; it is left out of the fit (pixels of the sheet, and frame widths).
MIN_OUTLIER_PX = 4.0
OUTLIER_FRAMES = 1.5
# A range with this many frame numbers is checked against its printed spacing: the pixels per
# frame of the numbers must give the printed spacing within the tolerance (a range with fewer
# numbers is too short for this: three numbers at a ship's end were 17 % off on a good table).
MIN_RANGE_TICKS = 5
RANGE_SLOPE_TOLERANCE = 0.15
# Two readings of one printed spacing text (from two requests) lie this close (sheet pixels).
SAME_LABEL_PX = 40.0
# This many neighbouring frame numbers off the fitted scale are not misreadings: the table is wrong.
MAX_OUTLIER_RUN = 2
# At most this share of the ticks may be left out; with more, the scale is not established.
MAX_OUTLIER_SHARE = 0.34
# The fitted scale must place its own ticks within one frame width (root mean square).
MAX_RMS_FRAMES = 1.0
# Two marks of the same thing on overlapping images are one mark when this close (sheet pixels).
SAME_MARK_PX = 10.0
# Scale requests for one ship: another is sent only while the scale is not established. The
# marks of all attempts are read together (a change of spacing that one reply leaves out is in
# the next; the frame numbers decide between two readings of a printed spacing).
SCALE_ATTEMPTS = 3
# A plan without frame numbers takes the scale of the profile only when its hull is drawn as
# long as the profile's hull, within this share (one sheet, one drawing scale; four pointed hull
# ends of about 1 % each).
SAME_SCALE_TOLERANCE = 0.04
# A place pointed by the model is taken to be this exact (pixels of the attached image).
POINT_SIGMA_IMAGE_PX = 2.0
# Room around a view's box in its images: the frame scale and the spacing line lie below the
# profile, outside a tight view box.
VIEW_PAD_X = 0.04
VIEW_PAD_Y = 0.30
MAX_IMAGES = 6
MAX_SPACES = 150
# Spaces asked in one extents request. Asked for 71 spaces at once the model boxed 20 (round u1;
# 43 of 43 when asked for 43), so the spaces go out in requests of this size, most useful first.
EXTENT_SPACES_PER_REQUEST = 20
DECK_EQUIPMENT = ("cargo_crane", "cargo_hatch")
MAX_EXTENT_REQUESTS = 4
# The order in which spaces are asked: holds and cargo tanks, then the tanks beside them (a wing
# ballast tank makes a cargo tank narrower than the hull), then the rest.
EXTENT_PRIORITY = ("cargo_hold", "cargo_tank", "slop_tank", "ballast_tank", "fuel_tank", "engine_room",
                   "cargo_hatch", "accommodation_deck", "other_tank", "cargo_crane", "container_bay", "other_space")
# Sanity bounds of commercial hull proportions; a measured set outside them is not used.
LBP_OVER_LOA = (0.85, 1.001)
LENGTH_OVER_BREADTH = (3.0, 12.0)
BREADTH_OVER_DEPTH = (1.0, 4.5)
# The moulded depth is taken amidships: the pointed deck line must lie in this part of the hull
# length (clear of the poop, the forecastle and, on most ships, the deckhouse).
MIDSHIP_SHARE = (0.25, 0.75)
# Spaces that lie below the upper deck: the deck is not lower than the top of any of them.
BELOW_DECK_KINDS = ("cargo_hold", "cargo_tank", "slop_tank", "ballast_tank", "fuel_tank", "engine_room")
# Without a pointed deck line, the depth is taken from the tops of the cargo spaces only when
# this many of them agree and another kind of space (or the lowest deckhouse tier) ends there too.
MIN_DECK_TOPS = 3
# A deck line pointed this little above the tops of the cargo spaces is the deck at the
# centreline (camber) or the top of the rail or bulwark, not the deck at side: bulwarks are
# about 1.0 to 1.4 m high and camber is below 1 m. Higher than this, the cargo spaces end
# below the deck (topside tanks).
RAIL_OR_CAMBER_M = 1.5
# The A.P. mark and frame 0 are the same place; they may be pointed this many frame widths apart.
AP_MARK_FRAMES = 2.0
# A space whose box ends this close to the centreline (metres) ends on it.
CENTRE_TOLERANCE_M = 0.6

PLAN_KINDS = ("deck_plan", "tank_top_plan")


# When the frame numbers of a range contradict its printed spacing in every reply (round u9n2:
# a printed "800" read as "600" three times), the spacing the numbers fit is taken, if it is one
# of these (or another value printed on the scale) and fits clearly better than the rest. Its
# span is marked as chosen by the fit, not read.
STANDARD_SPACINGS_MM = (500.0, 550.0, 600.0, 650.0, 700.0, 750.0, 800.0, 850.0, 900.0, 950.0, 1000.0)
CHOSEN_BY_FIT = "chosen_by_frame_number_fit"
FIT_CHOICE_ERROR = 0.03     # the chosen spacing is within 3 % of what the numbers show
FIT_CHOICE_MARGIN = 0.05    # and every other spacing is off by at least 5 % (and twice as much)
# The two halves of the range must show one spacing: a range that holds two spacings (a change
# not drawn) fits neither, and its mean would fit a wrong one (600 and 800 average to 750).
STRAIGHT_RUN_TOLERANCE = 0.06


# A local spacing printed for one frame inside a range of another spacing ("1200" under two
# close bulkheads in a range of 800; review round 4) lengthens the scale after it by
# (local / main - 1) frames. One such frame is a few pixels, about the scatter of the frame
# numbers (round u8: 5 px against +-3 px), so the frame numbers of the whole range decide: a
# line through them must fit with the local frames at most this share of the residual it has
# without them.
LOCAL_FIT_GAIN = 0.8
# A short range's drawn length may differ from its frames at its spacing by this share of one
# frame (the places of its two changes are each pointed to about a quarter frame).
SHORT_RANGE_TOLERANCE = 0.5


PROFILE_PLACES = ("hull_aft_end", "hull_fore_end", "base_line", "upper_deck_at_side")
PLAN_PLACES = ("centre_line", "shell_side_a", "shell_side_b")


# Checks that ``_measure`` writes; it runs again when the extents request adds named places.
MEASURE_CHECKS = ("frame_scale_not_fitted", "ap_mark_not_at_frame_0", "deck_point_not_amidships",
                  "measured_value_implausible", "measured_lengths_disagree", "measured_breadth_disagrees",
                  "measured_depth_disagrees")
# Every check code the frame-scale pass writes (a replay of the pass removes these first).
SCALE_PASS_CHECKS = MEASURE_CHECKS + (
    "depth_below_a_space_top", "depth_not_checked", "depth_not_confirmed_by_space_tops",
    "depth_taken_from_cargo_space_tops", "depth_unconfirmed_from_uncertain_boxes", "extent_above_the_deck",
    "extent_covers_a_labelled_neighbour", "extent_ends_below_spaces_above", "extent_of_unknown_space",
    "extent_withheld", "frame_spacing_not_understood", "outline_dropped", "plan_boxes_hold_each_others_labels",
    "printed_hatch_size_ignored", "scale_mark_not_understood")
MEASURED_FIELDS = ("lbp_m", "loa_m", "breadth_m", "depth_m")


SIDE_WORDS = [(r"\(?\bP\s?[&/]\s?S\b\)?|\(P,\s?S\)", "both"), (r"\(P\)|\bPORT\b", "port"),
              (r"\(S\)|\bSTBD\b|\bSTARBOARD\b", "starboard"), (r"\(C\)|\bCENT(?:RE|ER)\b", "centre")]


# An outline is a trace of the drawn boundary by the model: its points are placed with the
# frame scale but the trace itself is not measured, so it has its own status and changes no
# axis status (PM decision, 2026-11-12).
OUTLINE_STATUS = "traced"
# Points of an outline may lie this far outside its box (pixels of the sheet) for the line width.
OUTLINE_BOX_TOLERANCE_PX = 3.0


# Overlap rules: a box that takes in a labelled neighbour (lane W, round u4r: holds lost 80-92 % of
# their volume to tank boxes drawn over them).
STRIP_COVER = 0.8  # a neighbour that spans this share of a box along one axis is a strip of it
EDGE_TOLERANCE_M = 0.5


# A short untyped label ("X. T. (P)": two letters) names a small tank or room. A box guessed for
# it on every axis may be at most this many times its label box in each direction (lane W, round
# u6r3: such a label got a guessed box along a whole hold).
SMALL_LABEL_LETTERS = 4
SMALL_LABEL_BOX_FACTOR = 2.0


# A tank in the profile ends below the spaces boxed in its upper part (Astra round 6: peak tanks
# boxed up through a bosun store, a void, a fresh-water tank or the steering gear room above
# them). A space counts when this share of its length lies inside the tank's length and it
# starts above this share of the tank's height.
TANKS_ENDING_BELOW = ("ballast_tank", "fuel_tank", "other_tank")
INSIDE_LENGTH_SHARE = 0.9
UPPER_PART_SHARE = 0.4
NOT_A_SPACE_ABOVE = ("accommodation_deck", *DECK_EQUIPMENT)


# A size printed inside a hatch ("18.200 x 15.000", "15,480 X 20,600"): two numbers and an x.
HATCH_SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[xX×*]\s*(\d+(?:[.,]\d+)?)\s*(mm|m)?\.?")
HATCH_SIZE_RANGE_M = (2.0, 60.0)
PRINTED = "printed"


# A redrawn box keeps at least this share of the first box's area. A larger cut is more often a
# box that avoids a label printed over the space (a side tank's label over a hold) than a
# boundary found (rounds u6r5 and u6r6: holds and cargo tanks cut to strips of 28-51 %; the
# redrawn boxes that ended at a neighbour kept 65-84 %).
REDRAW_MIN_AREA_SHARE = 0.6


# The arrangement step's gate (lane W): no space left without volume, no fragment labels, and no
# cargo space losing more of its volume to smaller spaces than in round s3b (worst: 56 % of a
# hold, 58 % of a cargo tank).
GATE_MAX_CARGO_LOSS = 0.58
# Kinds whose missing extents the gate reports as a coverage warning, not a failure.
COVERAGE_KINDS = ("fuel_tank", "ballast_tank")
GATE_GRID = 20
GATE_KINDS = ("cargo_hold", "cargo_tank", "slop_tank", "ballast_tank", "fuel_tank", "other_tank", "engine_room",
              "other_space")


# A box guessed on every axis that shares more than this share of its volume with a cargo
# space covers it (touching faces and rounding stay below it).
GUESSED_OVER_CARGO_SHARE = 0.02
CARGO_KINDS = ("cargo_hold", "cargo_tank")
# A box whose outer side reaches this share of the half breadth lies against the shell: a wing,
# topside or side tank beside the cargo space (often inside a cargo box drawn to the shell). It
# is not a small space guessed over the cargo space.
AT_SHELL_SHARE = 0.85
# Such a box against the shell may still take at most this share of a cargo space's volume (lane
# W, round u6r7; development ships: side, topside and bottom tanks took up to 12 %, boxes drawn
# from the shell to near the centreline 34-80 %).
SHELL_BOX_MAX_CARGO_SHARE = 0.15


# A hold or a space on the centreline whose y range is off the centreline by more than this share
# of the breadth (|y_min + y_max| / B) is not a measured breadth (lane W, round u6r7: a hold
# boxed from -7 to +12 m).
OFF_CENTRE_SHARE = 0.10
# A tank against the shell guessed on every axis, with no height drawn in a profile, is placed in
# this upper share of the depth: top-side, upper wing and gravity wing tanks lie under the deck
# (lane W, round u6r7: such tanks filled to full height became wing columns in a hold).
UPPER_BAND_SHARE = 0.3
# A tank in the lower part of the hull ("D.B.", "BTM", "HOPPER"): it gets no upper band.
LOWER_TANK = re.compile(r"\bD\s*\.?\s*B\b|\bD/B\b|BTM|BOTTOM|HOPPER|LOWER|DOUBLE")


# A crane or hatch box whose bottom is more than this above the deck is the crane house or a
# part of the hatch cover, not the whole (lane W, round u6r8: crane posts started 8 m above the
# deck); a hatch coaming or a crane pedestal stands on the deck.
DECK_EQUIPMENT_GAP_M = 1.0


# Two cargo spaces of different numbers that share this share of the smaller box are one place
# read with two numbers.
CARGO_CONFLICT_SHARE = 0.5


# Two entries whose boxes share this share of each other's volume are one space read twice.
SAME_BOX_SHARE = 0.85
