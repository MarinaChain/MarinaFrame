"""Pure scantling formulas for the MiDShip rule set.

Every function takes three arguments and returns the required value in the
unit named by the rule's ``criterion.required_unit``:

* ``x``      -- input values, already converted to the rule's declared units
* ``a``      -- assumption values (option choices and design-basis constants)
* ``strict`` -- when true, apply text-based requirements that the MiDShip
  evaluator leaves out (see each function). The default reproduces the scope
  chosen by the dataset authors, so agreement can be measured first and the
  differences reported second.

Rule-text constants (for example 7.8 and 254) live here with a citation in
the function docstring. Option choices that the text leaves to the designer
(for example the coefficient ``c``) live in the rule JSON as assumptions.
Citations use the ABS Rules for Building and Classing Marine Vessels, Part 3,
July 2023 edition, which is the edition obtained for this study.
"""
from __future__ import annotations

from math import sqrt
from typing import Callable, Dict, Mapping

Inputs = Mapping[str, float]
Assumptions = Mapping[str, float]


# --- shared helpers --------------------------------------------------------

def deep_tank_head(x: Inputs, a: Assumptions) -> float:
    """Design head h in m for deep-tank type requirements.

    3-2-10/3.1 lists the heads to compare; the two used here are two-thirds
    of the depth to the bulkhead deck and, for tankers, the tank height plus
    the 3-2-7/3.1 Table 2 column (e) head (1.30 m for L of 122 m and above).
    """
    head = a["deep_tank_depth_fraction"] * x["depth"]
    if x["is_tanker"]:
        tank_top_head = x["depth"] - x["db_height"] + a["overflow_margin_m"]
        head = max(head, tank_top_head)
    return head


def plate_thickness_mm(spacing_m: float, head_m: float, c1: float, c2: float,
                       k: float, q: float) -> float:
    """t = s k sqrt(q h) / C1 + C2, with s in mm (3-2-10/3.1, 3-2-9/5.1, 3-2-3/5.1)."""
    return 1000.0 * spacing_m * k * sqrt(q * head_m) / c1 + c2


def wheel_load_thickness_mm(x: Inputs, a: Assumptions) -> float:
    """Wheel-loading thickness of a strength deck, 3-2-3/5.17.

    t = 1.1 k K n sqrt(C W). The text gives K as a polynomial of the wheel
    imprint ratios a/s and b/s. The imprint is not part of the design data,
    so K is an assumption (``wheel_K``) taken from the upper range of the
    3-2-3/5 Figure 2 curves, as the dataset authors state.
    """
    aspect = (max(x["sp_webframe"], x["sp_bottom_girder"])
              / min(x["sp_webframe"], x["sp_bottom_girder"]))
    n = min(1.0, 0.85 + 0.15 * (aspect - 1.0))
    wheel_kn = a["wheel_mass_kg"] * 9.81 / 1000.0
    return 1.1 * a["wheel_k"] * a["wheel_K"] * n * sqrt(a["wheel_C"] * wheel_kn)


def _panel_spacing_inner_bottom(x: Inputs) -> float:
    return max(x["sp_frame"], x["sp_bottom_stringer"])


def _inner_bottom_required_mm(x: Inputs, a: Assumptions, strict: bool) -> float:
    """Governing inner-bottom plate thickness: max of four ABS options."""
    s = _panel_spacing_inner_bottom(x)
    length = a["scantling_length_m"]
    # 3-2-3/5.1: plating of a deck or inner bottom carrying cargo.
    cargo = plate_thickness_mm(s, x["h_cargo"], 254.0, 1.5, 1.0, 1.0)
    # 3-2-4/9.5: inner bottom plating for vessels using grabs (non-tankers).
    grab = 0.0
    if not x["is_tanker"]:
        grab = (0.037 * length + 0.009 * s * 1000.0) * sqrt(a["Q"]) + 5.5
    # 3-2-10/3.1: deep tank plating.
    deep = plate_thickness_mm(s, deep_tank_head(x, a), 254.0, 2.5, a["k_panel"], a["q"])
    if strict:
        # 3-2-10/3.1: not less than 6.5 mm or s/150 + C2.
        deep = max(deep, 6.5, 1000.0 * s / 150.0 + 2.5)
    return max(cargo, grab, deep, wheel_load_thickness_mm(x, a))


# --- the 25 checks, in MiDShip column order ---------------------------------

def db_height(x, a, strict):
    """3-2-4/3.1.1(c): dDB = 32 B + 190 sqrt(d) mm.

    3-2-4/1.1.i: not less than B/20 and 0.76 m, need not exceed 2 m. MiDShip
    applies 1.1.i to non-tankers only; ``strict`` applies it to all types.
    """
    required = 32.0 * x["beam"] + 190.0 * sqrt(x["draft"])
    if strict or not x["is_tanker"]:
        required = max(required, min(x["beam"] / 20.0 * 1000.0, 2000.0), 760.0)
    return required


def floor_thickness(x, a, strict):
    """3-2-4/5.1: t = 0.036 L + 4.7 + c mm, with c = 1.5 for longitudinal framing."""
    return 0.036 * a["scantling_length_m"] + 4.7 + a["floor_c_mm"]


def girder_thickness(x, a, strict):
    """3-2-4/5.1 with c = 1.5 (MiDShip); 3-2-4/3.1.1(a) center girder: 0.056 L + 5.5."""
    required = 0.036 * a["scantling_length_m"] + 4.7 + a["floor_c_mm"]
    if strict:
        required = max(required, 0.056 * a["scantling_length_m"] + 5.5)
    return required


def floor_spacing(x, a, strict):
    """3-2-4/5.1: maximum floor spacing 3.66 m with open floors or longitudinal framing."""
    return 3.66


def inner_bottom_thickness(x, a, strict):
    return _inner_bottom_required_mm(x, a, strict)


def hopper_plate_thickness(x, a, strict):
    """Hopper plating takes the inner-bottom requirement; zero when no hopper is fitted."""
    if x["provided"] <= 0.0:
        return 0.0
    return _inner_bottom_required_mm(x, a, strict)


def _bottom_sm(x, a):
    """3-2-4/7.3 and 3-2-10/3.3: SM = 7.8 c h s l^2 cm3."""
    s = _panel_spacing_inner_bottom(x)
    span = max(x["sp_webframe"], x["sp_bottom_girder"])
    return 7.8 * a["c_bottom"] * deep_tank_head(x, a) * s * span ** 2


def bottom_stiffener_sm(x, a, strict):
    return _bottom_sm(x, a)


def bottom_transverse_sm(x, a, strict):
    return _bottom_sm(x, a)


def hopper_stiffener_sm(x, a, strict):
    if x["is_tanker"]:
        return 0.0
    return _bottom_sm(x, a)


def side_frame_sm(x, a, strict):
    """3-2-5/3.1.1: SM = s l^2 (h + b h1 / C1)(C2 + C3 / l^3) cm3, l >= 2.1 m."""
    span = max(x["l_frame"], 2.1)
    h = max(x["draft"] - span / 2.0, 0.4 * span)
    return (x["sp_frame"] * span ** 2
            * (h + x["h_cargo"] * x["sp_bottom_girder"] / 30.0)
            * (7.0 + 45.0 / span ** 3) * a["Q"])


def webframe_sm(x, a, strict):
    """3-2-6/3.1.2: SM = 4.74 c s l^2 (h + b h1 / 45K) cm3."""
    span = x["h_cargo"]
    h = max(0.5 * span, abs(span / 2.0 + x["db_height"] - x["draft"]))
    return (4.74 * a["c_webframe"] * x["sp_webframe"] * span ** 2
            * (h + x["webframe_depth"] * a["h_deck_m"] / (45.0 * a["K_deck_support"]))
            * a["Q"])


def webframe_depth(x, a, strict):
    """3-2-6/3.5.2: depth not less than 0.125 l, l = web frame span. Result in mm."""
    return 1000.0 * 0.125 * x["h_cargo"]


def webframe_thickness(x, a, strict):
    """3-2-6/3.5.2: 1 mm per 100 mm of depth plus 3.5 mm, need not exceed 14 mm."""
    return min(1000.0 * 0.01 * x["webframe_depth"] + 3.5, 14.0)


def side_stringer_sm(x, a, strict):
    """3-2-6/5.1 (SM = 4.74 c h s l^2) and 3-2-10/3.3 (SM = 7.8 c h s l^2)."""
    head = max(a["deep_tank_depth_fraction"] * x["depth"], 1.8)
    hold = 4.74 * a["c_stringer"] * head * x["sp_side_stringer"] * x["sp_webframe"] ** 2 * a["Q"]
    s = max(x["sp_frame"], x["sp_side_stringer"])
    tank = 7.8 * a["c_bottom"] * deep_tank_head(x, a) * s * x["sp_webframe"] ** 2
    return max(hold, tank)


def side_stringer_depth(x, a, strict):
    """3-2-6/5.3.i: depth not less than 0.125 l, l = span between web frames. mm."""
    return 1000.0 * 0.125 * x["sp_webframe"]


def bulkhead_thickness(x, a, strict):
    """3-2-9/5.1 (c = 254 collision bulkhead) and 3-2-10/3.1 deep-tank plating."""
    s = max(x["sp_bhd_horizontal"], x["sp_bhd_vertical"])
    watertight = plate_thickness_mm(s, x["depth"], a["bhd_c"], 1.5, a["k_panel"], a["q"])
    watertight = max(watertight, 6.0, 1000.0 * s / 200.0 + 2.5)
    deep = plate_thickness_mm(s, deep_tank_head(x, a), 254.0, 2.5, a["k_panel"], a["q"])
    if strict:
        deep = max(deep, 6.5, 1000.0 * s / 150.0 + 2.5)
    return max(watertight, deep)


def _bulkhead_stiffener_sm(x, a):
    """3-2-9/5.3 (SM = 7.8 k c h s l^2) and 3-2-10/3.3, c = 0.6 as MiDShip."""
    s = max(x["sp_bhd_horizontal"], x["sp_bhd_vertical"])
    c = a["c_bulkhead"]
    watertight = 7.8 * a["k_collision"] * c * s * x["depth"] * x["sp_bhd_horizontal"] ** 2
    span = max(x["sp_bhd_horizontal"], x["sp_bhd_vertical"])
    deep = 7.8 * 1.0 * c * s * deep_tank_head(x, a) * span ** 2
    return max(watertight, deep)


def bulkhead_horizontal_sm(x, a, strict):
    return _bulkhead_stiffener_sm(x, a)


def bulkhead_vertical_sm(x, a, strict):
    return _bulkhead_stiffener_sm(x, a)


def deck_trans_stiffener_sm(x, a, strict):
    """3-2-7/3.1: SM = 7.8 c h s l^2 with c = 0.585 between longitudinal deck girders."""
    if x["sp_deck_girder"] <= 0.0:
        return 0.0
    return 7.8 * a["c_deck_beam"] * a["h_deck_m"] * x["sp_webframe"] * x["sp_deck_girder"] ** 2


def deck_thickness(x, a, strict):
    """3-2-3/5.1 cargo equation, 3-2-4/9.5 grab equation, 3-2-3/5.17 wheel loading, 5.0 mm floor."""
    s = x["sp_frame"]
    if x["sp_deck_stringer"] > 0.0:
        s = max(s, x["sp_deck_stringer"])
    cargo = plate_thickness_mm(s, a["h_deck_m"], 254.0, 1.5, 1.0, 1.0)
    grab = 0.0
    if not x["is_tanker"]:
        grab = (0.037 * a["scantling_length_m"] + 0.009 * s * 1000.0) * sqrt(a["Q"]) + 5.5
    return max(cargo, grab, wheel_load_thickness_mm(x, a), 5.0)


def deck_beam_sm(x, a, strict):
    """3-2-8/5.3 with c = 1.5 for tank decks (3-2-8/5.13): SM = 4.74 c b h l^2 cm3."""
    if x["sp_deck_girder"] <= 0.0:
        return 0.0
    return (4.74 * a["c_deck_girder"] * a["h_deck_m"] * x["sp_deck_girder"] ** 2
            * x["sp_webframe"])


def deck_beam_depth(x, a, strict):
    """3-2-8/5.13: minimum girder depth 0.0833 l (tanks); 0.0583 l in 3-2-8/5.7. mm."""
    if x["sp_deck_girder"] <= 0.0:
        return 0.0
    return 1000.0 * 0.0833 * x["sp_deck_girder"]


def deck_beam_thickness(x, a, strict):
    """3-2-8/5.7: 1 mm per 100 mm of depth plus 4 mm; 15 mm face-area option (assumption)."""
    if x["deck_beam_depth"] <= 0.0:
        return 0.0
    return max(1000.0 * 0.01 * x["deck_beam_depth"] + 4.0, a["deck_beam_min_mm"])


def _spacing_for_shell(x, strict, for_bottom):
    if strict and for_bottom:
        return x["sp_bottom_stringer"]
    return max(x["sp_frame"], x["sp_side_stringer"])


def _draft_ratio(x, a):
    """Actual d/D, not less than 0.0433 L/D (3-2-2/3.9.3, 3-2-2/3.15.1)."""
    length = a["scantling_length_m"]
    return max(x["draft"] / x["depth"], 0.0433 * length / x["depth"])


def side_shell_thickness(x, a, strict):
    """3-2-2/3.9.3: t = (s/645) sqrt((L - 15.2) d/D) + 2.5; 3-2-2/5.1 floor with s = 610 mm."""
    length = a["scantling_length_m"]
    s = _spacing_for_shell(x, strict, False)
    main = 1000.0 * s / 645.0 * sqrt((length - 15.2) * _draft_ratio(x, a)) + 2.5
    minimum = 0.035 * (length + 29.0) + 0.009 * 1000.0 * s
    at_610 = 0.035 * (length + 29.0) + 0.009 * 610.0
    return max(main, minimum, at_610)


def bottom_shell_thickness(x, a, strict):
    """3-2-2/3.15.1 (longitudinal, 122 m <= L <= 305 m) and 3-2-2/3.15.2.

    MiDShip uses the side-shell spacing here. ``strict`` uses the bottom
    longitudinal spacing, which the text defines as ``s``.
    """
    length = a["scantling_length_m"]
    s = _spacing_for_shell(x, strict, True)
    t_main = 1000.0 * s / 508.0 * sqrt((length - 62.5) * _draft_ratio(x, a)) + 2.5
    t_min = 1000.0 * s * (length - 18.3) / (42.0 * length + 1070.0)
    return max(t_main, t_min, a["bottom_shell_floor_mm"])


CHECKS: Dict[str, Callable[[Inputs, Assumptions, bool], float]] = {
    "db_height": db_height,
    "floor_thickness": floor_thickness,
    "girder_thickness": girder_thickness,
    "floor_spacing": floor_spacing,
    "inner_bottom_thickness": inner_bottom_thickness,
    "hopper_plate_thickness": hopper_plate_thickness,
    "bottom_stiffener_sm": bottom_stiffener_sm,
    "bottom_transverse_sm": bottom_transverse_sm,
    "hopper_stiffener_sm": hopper_stiffener_sm,
    "side_frame_sm": side_frame_sm,
    "webframe_sm": webframe_sm,
    "webframe_depth": webframe_depth,
    "webframe_thickness": webframe_thickness,
    "side_stringer_sm": side_stringer_sm,
    "side_stringer_depth": side_stringer_depth,
    "bulkhead_thickness": bulkhead_thickness,
    "bulkhead_horizontal_sm": bulkhead_horizontal_sm,
    "bulkhead_vertical_sm": bulkhead_vertical_sm,
    "deck_trans_stiffener_sm": deck_trans_stiffener_sm,
    "deck_thickness": deck_thickness,
    "deck_beam_sm": deck_beam_sm,
    "deck_beam_depth": deck_beam_depth,
    "deck_beam_thickness": deck_beam_thickness,
    "side_shell_thickness": side_shell_thickness,
    "bottom_shell_thickness": bottom_shell_thickness,
}
