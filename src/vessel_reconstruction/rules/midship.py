"""Adapters from MiDShip tables to rule inputs, and the agreement comparison.

Two input sources exist:

* ``inputs_from_structural_elements`` reads the per-design bill of materials
  (``*_Structural_Elements.csv``). It is exact, but the sample holds 36 BOMs.
* ``inputs_from_parameters`` rebuilds the same inputs from the 120-column
  parameter row, for every design in the sample tables.

Both return a ``DesignInputs``. Only ``csv`` and ``math`` are used.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from math import hypot
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

DRAFT_FRACTION = 0.6667  # MiDShip takes draft = 0.6667 of the molded depth.
MERGE_TOLERANCE_M = 1.0e-6  # positions closer than 1 micrometre are the same position

# Sign convention of the stored tables: value >= threshold is a pass.
# The one maximum-spacing constraint is stored with both numbers negated.
SPACING_COLUMN = "Bottom_Floor_Spacing"

SHIP_TYPE_COLUMNS = (("cat tanker", "tanker"), ("cat container", "container_ship"),
                     ("cat bulkcarrier", "bulk_carrier"))


class GeometryError(ValueError):
    """A member needed for an input is missing from the design."""


@dataclass
class DesignInputs:
    ship_type: str
    geometry: Dict[str, float]
    provided: Dict[str, float]  # MiDShip column -> actual member value
    notes: List[str] = field(default_factory=list)

    def rule_inputs(self, rule) -> Dict[str, float]:
        """Geometry plus the provided value that belongs to ``rule``."""
        values = dict(self.geometry)
        provided_name = rule.data["criterion"]["provided_input"]
        values[provided_name] = self.provided[rule.midship_column]
        return values


# --- section properties -----------------------------------------------------

def section_modulus_cm3(plate_t_mm: float, spacing_mm: float, h_mm: float,
                        t_mm: float, w_mm: float) -> float:
    """Section modulus of a stiffener with its plate, in cm3.

    Convention of the dataset: the plate has the full stiffener spacing as
    effective breadth, the web has thickness ``t`` and height ``h``, and the
    flange has width ``w`` and the same thickness ``t``. The plate mid-plane
    is the datum. This is a design-side convention, not an ABS rule; the ABS
    effective breadth of 3-2-1 is not applied.
    """
    area = t_mm * w_mm + h_mm * t_mm + plate_t_mm * spacing_mm
    centroid = (t_mm * w_mm * h_mm + h_mm * t_mm * (h_mm / 2.0)) / area
    inertia = (spacing_mm * plate_t_mm ** 3 / 12.0 + spacing_mm * plate_t_mm * centroid ** 2
               + w_mm * t_mm ** 3 / 12.0 + w_mm * t_mm * (centroid - h_mm) ** 2
               + t_mm * h_mm ** 3 / 12.0 + h_mm * t_mm * (h_mm / 2.0 - centroid) ** 2)
    return inertia / max(centroid, h_mm - centroid) / 1000.0


# --- bill of materials adapter ----------------------------------------------

_BOM_NUMERIC = ("x_loc", "y_loc", "z_loc", "L1", "L2", "Thickness")


def read_structural_elements(path) -> List[Dict[str, object]]:
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row: Dict[str, object] = {"Object_ID": raw["Object_ID"], "Class": raw["Class"],
                                      "Type": raw["Type"], "Lightening_Holes": raw["Lightening_Holes"]}
            for key in _BOM_NUMERIC:
                row[key] = float(raw[key]) if raw[key] != "" else float("nan")
            rows.append(row)
    return rows


def _distinct(values: Sequence[float], legacy_unique: bool) -> List[float]:
    """Sorted distinct positions.

    Positions that differ by less than ``MERGE_TOLERANCE_M`` are one position:
    the CAD export writes the same position with float noise (for example 0.0
    and -1.8e-15). ``legacy_unique`` keeps every float apart, which reproduces
    the dataset evaluator and is used only to diagnose its artifacts.
    """
    ordered = sorted(values)
    if legacy_unique:
        return sorted(set(ordered))
    merged: List[float] = []
    for value in ordered:
        if not merged or value - merged[-1] > MERGE_TOLERANCE_M:
            merged.append(value)
    return merged


def _gaps(values: Sequence[float], evaluator_unique: bool, legacy_unique: bool) -> float:
    """Gap between the two lowest member positions.

    The default merges noisy duplicates. In legacy mode the call follows the
    dataset evaluator: exact-float unique when it used unique, else the raw
    sorted list.
    """
    if legacy_unique:
        ordered = sorted(set(values)) if evaluator_unique else sorted(values)
    else:
        ordered = _distinct(values, False)
    if len(ordered) < 2:
        raise GeometryError("fewer than two members to measure a spacing")
    return ordered[1] - ordered[0]


def inputs_from_structural_elements(rows: Sequence[Mapping[str, object]],
                                    ship_type: str,
                                    legacy_unique: bool = False) -> DesignInputs:
    by_class: Dict[str, List[Mapping[str, object]]] = {}
    by_id: Dict[str, Mapping[str, object]] = {}
    for row in rows:
        by_class.setdefault(row["Class"], []).append(row)
        by_id[row["Object_ID"]] = row

    def first(cls: str) -> Mapping[str, object]:
        if cls not in by_class:
            raise GeometryError(f"class {cls} missing")
        return by_class[cls][0]

    def coords(cls: str, key: str) -> List[float]:
        if cls not in by_class:
            raise GeometryError(f"class {cls} missing")
        return [r[key] for r in by_class[cls]]

    def flange_m(row) -> float:
        flange = by_id.get(f"{row['Object_ID']}_Flange")
        return flange["L2"] if flange else 0.0

    def mm(value_m: float) -> float:
        return value_m * 1000.0

    notes: List[str] = []
    side_shell = first("Side_Shell")
    beam = 2.0 * side_shell["y_loc"]
    decks = sorted(by_class.get("Deck", []), key=lambda r: r["z_loc"])
    if len(decks) < 2:
        raise GeometryError("need an inner bottom and a top deck")
    inner_bottom, top_deck = decks[0], decks[1]
    db_height = inner_bottom["z_loc"]
    depth = top_deck["z_loc"]
    draft = DRAFT_FRACTION * depth
    h_cargo = depth - db_height

    sp = {
        "sp_webframe": _gaps(coords("Vertical_Web_Frame", "x_loc"), False, legacy_unique),
        "sp_frame": _gaps(coords("Vertical_Side_Frame", "x_loc"), False, legacy_unique),
        "sp_bottom_girder": _gaps(coords("Bottom_Longitudinal_Girder", "y_loc"), False, legacy_unique),
        "sp_bottom_stringer": _gaps(coords("Bottom_Longitudinal_Stiffener", "y_loc"), False, legacy_unique),
        "sp_side_stringer": _gaps(coords("Side_Shell_Longitudinal_Stiffener", "z_loc"), False, legacy_unique),
        "sp_bhd_horizontal": _gaps(coords("Transverse_Bulkhead_Transverse_Stiffener", "z_loc"), True, legacy_unique),
        "sp_bhd_vertical": _gaps(coords("Transverse_Bulkhead_Vertical_Stiffener", "y_loc"), True, legacy_unique),
    }
    has_deck_girder = "Deck_Longitudinal_Girder" in by_class
    sp["sp_deck_girder"] = _gaps(coords("Deck_Longitudinal_Girder", "y_loc"), True, legacy_unique) if has_deck_girder else 0.0
    sp["sp_deck_stringer"] = (_gaps(coords("Deck_Longitudinal_Stiffener", "y_loc"), True, legacy_unique)
                              if has_deck_girder else 0.0)

    floor_bracket = first("Bracket_Floor_Web")["L2"]
    deck_bracket = first("Bracket_Deck_Web")["L2"] if "Bracket_Deck_Web" in by_class else 0.0
    l_frame = depth - db_height - floor_bracket - deck_bracket

    web = first("Vertical_Web_Frame")
    has_deck_beam = "Deck_Transvere_Beam" in by_class  # sic: the spelling in the data
    deck_beam = first("Deck_Transvere_Beam") if has_deck_beam else None
    geometry = {"beam": beam, "depth": depth, "draft": draft, "db_height": db_height,
                "h_cargo": h_cargo, "l_frame": l_frame, "webframe_depth": web["L2"],
                "deck_beam_depth": deck_beam["L2"] if deck_beam else 0.0, **sp}

    def stiffener_sm(plate_t_mm, spacing_m, member) -> float:
        return section_modulus_cm3(plate_t_mm, mm(spacing_m), mm(member["L2"]),
                                   mm(member["Thickness"]), mm(flange_m(member)))

    bottom_shell_t = mm(first("Bottom_Shell")["Thickness"])
    side_shell_t = mm(side_shell["Thickness"])
    top_deck_t = mm(top_deck["Thickness"])
    inner_bottom_t = mm(inner_bottom["Thickness"])
    bhd_t = mm(first("Transverse_Bulkhead")["Thickness"])

    has_hopper = ship_type != "tanker" and "Hopper Pannel" in by_class  # sic
    hopper_t = mm(first("Hopper Pannel")["Thickness"]) if has_hopper else 0.0
    hopper_sm = 0.0
    if has_hopper:
        stiff = first("Hopper_Pannel_Longitudinal_Stiffener")
        stiff_rows = by_class["Hopper_Pannel_Longitudinal_Stiffener"]
        if ship_type == "bulk_carrier":
            spacing = hypot(stiff_rows[1]["y_loc"] - stiff_rows[0]["y_loc"],
                            stiff_rows[1]["z_loc"] - stiff_rows[0]["z_loc"])
        else:
            spacing = min(_diff_min(coords("Hopper_Pannel_Longitudinal_Stiffener", "y_loc"), legacy_unique),
                          _diff_min(coords("Hopper_Pannel_Longitudinal_Stiffener", "z_loc"), legacy_unique))
        hopper_sm = stiffener_sm(hopper_t, spacing, stiff)

    bhd_h = first("Transverse_Bulkhead_Transverse_Stiffener")
    bhd_v = first("Transverse_Bulkhead_Vertical_Stiffener")
    provided = {
        "Double_Bottom_Height": mm(db_height),
        "Bottom_Floor_Thickness": mm(first("Transverse_Floor")["Thickness"]),
        "Bottom_Girder_Thickness": mm(first("Bottom_Longitudinal_Girder")["Thickness"]),
        "Bottom_Floor_Spacing": sp["sp_webframe"],
        "Inner_Bottom_Deck_Thickness": inner_bottom_t,
        "Hopper_Plate_Thickness": hopper_t,
        "Bottom_Stiffener_SM": stiffener_sm(bottom_shell_t, sp["sp_bottom_stringer"],
                                            first("Bottom_Longitudinal_Stiffener")),
        "Bottom_Transverse_Stiffener_SM": stiffener_sm(bottom_shell_t, sp["sp_frame"],
                                                       first("Transverse_Bottom_Frame")),
        "Hopper_Stiffener_SM": hopper_sm,
        "Side_Frame_SM": stiffener_sm(side_shell_t, sp["sp_frame"], first("Vertical_Side_Frame")),
        "Webframe_SM": stiffener_sm(side_shell_t, sp["sp_webframe"], web),
        "Webframe_Depth": mm(web["L2"]),
        "Webframe_Thickness": mm(web["Thickness"]),
        "Side_Stringer_SM": stiffener_sm(side_shell_t, sp["sp_side_stringer"],
                                         first("Side_Shell_Longitudinal_Stiffener")),
        "Side_Stringer_Depth": mm(first("Side_Shell_Longitudinal_Stiffener")["L2"]),
        "Bulkhead_Thickness": bhd_t,
        "Trans_Bulkhead_Horizontal_Stiffener_SM": stiffener_sm(bhd_t, sp["sp_bhd_horizontal"], bhd_h),
        "Trans_Bulkhead_Vertical_Stiffener_SM": stiffener_sm(bhd_t, sp["sp_bhd_vertical"], bhd_v),
        "Deck_Trans_Stiff_SM": 0.0,
        "Deck_Thickness": top_deck_t,
        "Deck_Beam_SM": 0.0,
        "Deck_Beam_Depth": mm(deck_beam["L2"]) if deck_beam else 0.0,
        "Deck_Beam_Thickness": mm(deck_beam["Thickness"]) if deck_beam else 0.0,
        "Side_Shell_Thickness": side_shell_t,
        "Bottom_Shell_Thickness": bottom_shell_t,
    }
    if has_deck_girder and deck_beam:
        # The data spells this class with a trailing comma.
        provided["Deck_Trans_Stiff_SM"] = stiffener_sm(top_deck_t, sp["sp_frame"],
                                                       first("Deck_Transverse_Stiffener,"))
        provided["Deck_Beam_SM"] = stiffener_sm(top_deck_t, sp["sp_webframe"], deck_beam)
    return DesignInputs(ship_type, geometry, provided, notes)


def _diff_min(values: Sequence[float], legacy_unique: bool = False) -> float:
    ordered = _distinct(values, legacy_unique)
    if len(ordered) < 2:
        return float("inf")
    return min(b - a for a, b in zip(ordered, ordered[1:]))


# --- parameter row adapter ----------------------------------------------------

def inputs_from_parameters(row: Mapping[str, float], ship_type: str) -> DesignInputs:
    """Rebuild the rule geometry inputs from one 120-column parameter row.

    Spacings follow the generator layout: ``n`` members split a span into
    ``n + 1`` equal gaps. The layout was checked against the 36 bills of
    materials in the sample (see docs/RULES_V1.md). Member values that the
    rules compare against (``provided``) are not rebuilt here; the agreement
    runner reads them from the MiDShip value table.
    """
    length = row["L_3h"]
    beam = row["B"]
    depth = row["D"]
    db_height = row["Db"] / 1000.0
    hold = (length - 2.0 * row["l_overhang"] * length) / 3.0
    sp_webframe = hold / (row["web frames per hold"] + 1.0)
    # Longitudinals are laid out across the bottom between the centre line and
    # the wing tank: half beam minus the web frame depth, in (n - 1) gaps.
    flat = beam / 2.0 - row["web frame h"] / 1000.0
    sp_bottom_girder = flat / (row["num bottom girders"] - 1.0)
    container = ship_type == "container_ship"
    # Container holds have no deck girders, deck beams or deck brackets, and the
    # floor bracket height is the container step height.
    sp_deck_girder = 0.0 if container else flat / (row["num top girders"] - 1.0)
    floor_bracket = (row["cont step height"] if container else row["floor web bracket L2"]) / 1000.0
    deck_bracket = 0.0 if container else row["deck web bracket  L2"] / 1000.0
    geometry = {
        "beam": beam,
        "depth": depth,
        "draft": DRAFT_FRACTION * depth,
        "db_height": db_height,
        "h_cargo": depth - db_height,
        "l_frame": depth - db_height - floor_bracket - deck_bracket,
        "webframe_depth": row["web frame h"] / 1000.0,
        "deck_beam_depth": 0.0 if container else row["trans deck beam h"] / 1000.0,
        "sp_webframe": sp_webframe,
        "sp_frame": sp_webframe / (row["num intermediate trans frames"] + 1.0),
        "sp_bottom_girder": sp_bottom_girder,
        "sp_bottom_stringer": sp_bottom_girder / (row["num intermediate bottom stiffeners"] + 1.0),
        "sp_side_stringer": depth / (row["num side shell stiffeners"] + 1.0),
        "sp_bhd_horizontal": depth / (row["num transverse bulkhead stiffeners"] + 1.0),
        "sp_bhd_vertical": flat / (row["num vertical bulkhead stiffeners"] - 1.0),
        "sp_deck_girder": sp_deck_girder,
        "sp_deck_stringer": (0.0 if container else
                             sp_deck_girder / (row["num intermediate deck stiffeners"] + 1.0)),
    }
    return DesignInputs(ship_type, geometry, {})


# --- table readers ------------------------------------------------------------

def read_float_table(path) -> List[Dict[str, float]]:
    """Read a CSV into rows of floats; an empty or unreadable cell becomes NaN."""
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row = {}
            for key, text in raw.items():
                try:
                    row[key.strip()] = float(text)
                except (TypeError, ValueError):
                    row[key.strip()] = float("nan")
            rows.append(row)
    return rows


def ship_type_of(parameter_row: Mapping[str, float]) -> Optional[str]:
    for column, name in SHIP_TYPE_COLUMNS:
        if parameter_row.get(column, 0.0) == 1.0:
            return name
    return None


def midship_pass(value: float, threshold: float) -> bool:
    """The dataset rule: a constraint passes when value >= threshold."""
    return value >= threshold
