"""Shared label vocabulary for both commercial GA reading passes."""

# Words a label must contain before a fine-pass reading of it counts as a counted kind. A cell
# read without context can name a cut label wrongly (review round 1: a cut hold label typed as a
# cargo tank on a bulk carrier); a label that does not say what it is goes to the other kinds.
KIND_WORDS = {
    "cargo_hold": r"\bHOLD\b",
    "cargo_hatch": r"\bHATCH\b|\bH\.?\s?C\b",
    # A hose-handling, provision or engine-room crane is a crane but not a cargo crane.
    "cargo_crane": r"^(?!.*\b(?:HOSE|PROV|PROVISION|STORE|STORES|ENGINE|E/R|DAVIT|MISC|HOIST)\b).*\bCRANE\b",
    "cargo_tank": r"C\.?\s?O\.?\s?T|C\.?\s?T\b|CARGO\s+(?:OIL\s+)?T(?:AN)?K|\bCOT\b",
    "slop_tank": r"\bSLOP\b",
}



# A label whose text names its kind gets that kind when the model gave a general one (review
# round 2: "NO.4 C.T.(P)" came back as other_tank, "NO.9 H O L D" as other_space). A numbered
# hold or cargo tank needs its number in the label; a hatch is never promoted (an access hatch
# is not a cargo hatch).
PROMOTIONS = [
    ("slop_tank", ("other_tank",), r"\bSLOP\b"),
    ("cargo_tank", ("other_tank",), r"^(?:NO\.?\s*)?\d+\s*(?:C\.\s?O\.\s?T|C\.\s?T|COT|CARGO\s+(?:OIL\s+)?T(?:AN)?K)\b"),
    ("cargo_hold", ("other_space",), r"^(?:NO\.?\s*)?\d+\s*[A-Z]?\s*(?:CARGO\s+)?HOLD\b"),
    ("ballast_tank", ("other_tank", "other_space"),
     r"W\.?\s?B\.?\s?T|B\.?\s?W\.?\s?T|\bBALLAST\b|\b[AF]\.\s?P\.\s?T\b|\bPEAK\s+T(?:AN)?K"),
    ("fuel_tank", ("other_tank",), r"\bF\.\s?O\.\s?T|\bH\.?\s?F\.?\s?O\b|\bD\.\s?O\.\s?T|\bM\.?\s?[DG]\.?\s?O\b|\bFUEL\s+OIL\b"),
]



# A dropped label whose reason says it was cut may be read whole from a wider crop.
CUT_REASONS = ("the label is cut", "unclosed parenthesis", "start of a longer word", "single letter",
               "the end of the label", "a part of the label")

# Words that name a fitting or an opening, not a space (lane W, round u6r: accommodation ladders
# outboard of the ship side ended with no volume).
FITTING_WORDS = {"LADDER", "GANGWAY", "DAVIT", "OPENING", "OPEN", "MANIFOLD", "WINCH", "WINDLASS", "MOORING",
                 "BOLLARD", "FAIRLEAD", "RAFT", "LIFEBOAT", "BOAT", "CAPSTAN", "CHOCK", "HATCH"}
# The last word of a room or store: a label that ends with one is a space even when it names a
# fitting ("HATCH COVER STORE", "BOAT DECK STORE").
ROOM_NOUNS = {"STORE", "STR", "ROOM", "RM", "SPACE", "LOCKER", "SHOP", "WORKSHOP", "TRUNK", "TANK", "TK"}
# Words that name a system and need a room noun to be a space ("FOAM" for "FOAM ROOM").
SYSTEM_WORDS = {"FOAM", "CO", "FIRE", "FAN", "HYD", "PAINT", "LAMP", "ROPE", "CHAIN", "BATT", "ELEC", "EMERG",
                "EMG", "PUMP"}
# The last word of a deck name; a space on a deck ends with its own noun ("DECK STORE").
DECK_NAME_WORDS = {"DECK", "DK"}
# Words of a note printed beside a fitting ("FOLDING TYPE"), never of a space.
NOTE_WORDS = {"TYPE"}
