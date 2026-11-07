"""Read the printed scale and the plate and stiffener tables from sheet words.

Only exact printed patterns are accepted. A cell that does not parse gives
``None`` for that value; nothing is repaired or guessed.
"""
from __future__ import annotations

import re

from .model import PlateRow, StiffenerRow, Word

# Words whose centres differ in height by less than this are on one text line.
LINE_TOLERANCE_MM = 1.0
# A table row starts within this distance of its first column's header word.
COLUMN_TOLERANCE_MM = 3.0
# Rows of a table are separated by about 12 mm; a larger gap ends the table.
MAX_ROW_GAP_MM = 20.0
# The last (material) column ends about 30 mm after its header word; the
# sheet margin labels lie more than 50 mm further right.
LAST_COLUMN_WIDTH_MM = 45.0

SCALE_PATTERN = re.compile(r"\b1\s*m\s*=\s*(\d+(?:\.\d+)?)\s*mm\b")
THICKNESS_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*mm$")
DIMS_PATTERN = re.compile(
    r"^([TLI])-\s*(\d+(?:\.\d+)?)\s*m\s*x\s*(\d+(?:\.\d+)?)\s*m\s*x\s*(\d+(?:\.\d+)?)\s*mm$")
COUNT_PATTERN = re.compile(r"^\d+$")

PLATE_HEADER = ("Plate", "Thickness", "Material")
STIFFENER_HEADER = ("Stiffener", "Num.", "Spacing", "Dims:", "Material")


def text_lines(words: tuple[Word, ...] | list[Word]) -> list[list[Word]]:
    """Group words into lines, top line first, words left to right."""
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: -w.centre[1]):
        if lines and abs(lines[-1][0].centre[1] - word.centre[1]) <= LINE_TOLERANCE_MM:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def read_scale(words) -> float | None:
    """Return the printed scale in drawing millimetres per ship metre."""
    found = set()
    for line in text_lines(words):
        match = SCALE_PATTERN.search(" ".join(w.text for w in line))
        if match:
            found.add(float(match.group(1)))
    return found.pop() if len(found) == 1 else None


def _find_header(lines, header: tuple[str, ...]):
    for index, line in enumerate(lines):
        texts = [w.text for w in line]
        if all(token in texts for token in header):
            starts = []
            for token in header:
                starts.append(next(w.x0 for w in line if w.text == token))
            if starts == sorted(starts):
                return index, starts
    return None, None


def _table_rows(lines, header: tuple[str, ...]) -> list[list[str]]:
    header_index, starts = _find_header(lines, header)
    if header_index is None:
        return []
    rows: list[list[str]] = []
    previous_z = lines[header_index][0].centre[1]
    x_end = starts[-1] + LAST_COLUMN_WIDTH_MM
    for line in lines[header_index + 1:]:
        cells_words = [w for w in line if starts[0] - COLUMN_TOLERANCE_MM <= w.x0 <= x_end]
        if not cells_words:
            continue
        z = cells_words[0].centre[1]
        if previous_z - z > MAX_ROW_GAP_MM:
            break
        if abs(cells_words[0].x0 - starts[0]) > COLUMN_TOLERANCE_MM:
            continue  # not a table row (for example a sheet margin label)
        if any(w.text == "Material" for w in cells_words):
            break  # the header of the next table
        cells = [[] for _ in starts]
        for word in cells_words:
            column = max(i for i, s in enumerate(starts) if word.x0 >= s - COLUMN_TOLERANCE_MM)
            cells[column].append(word.text)
        rows.append([" ".join(c) for c in cells])
        previous_z = z
    return rows


def read_plate_table(words) -> list[PlateRow]:
    rows = []
    for name, thickness, *_ in _table_rows(text_lines(words), PLATE_HEADER):
        match = THICKNESS_PATTERN.match(thickness.strip())
        rows.append(PlateRow(name.strip(), float(match.group(1)) if match else None))
    return rows


def read_stiffener_table(words) -> list[StiffenerRow]:
    rows = []
    for name, count, _spacing, dims, *_ in _table_rows(text_lines(words), STIFFENER_HEADER):
        count_value = int(count) if COUNT_PATTERN.match(count.strip()) else None
        match = DIMS_PATTERN.match(dims.strip())
        if match:
            shape = match.group(1)
            height, width, thickness = (float(match.group(i)) for i in (2, 3, 4))
            rows.append(StiffenerRow(name.strip(), count_value, shape, round(height * 1000, 3),
                                     round(width * 1000, 3), thickness))
        else:
            rows.append(StiffenerRow(name.strip(), count_value, None, None, None, None))
    return rows
