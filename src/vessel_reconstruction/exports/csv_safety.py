"""Keep spreadsheet apps from running text cells of exported CSV files as formulas.

Station ids, labels and notes can come from a drawing spec that a person or the model
wrote. A text cell that starts with =, +, -, @, a tab or a carriage return is prefixed
with a single quote. Numbers are written by the caller as formatted numbers and are not
passed through here, so negative values stay numeric.
"""

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text
