"""Tests for the cited rule data and its executable checks.

Expected values are worked by hand from the ABS Rules for Building and Classing
Marine Vessels, Part 3, July 2023. The paragraph is named beside each case.
"""
import copy
import os
import re
from pathlib import Path

import pytest

from vessel_reconstruction.rules import (MissingInputError, Quantity, RuleDataError, UnitError,
                                         convert, load_rule_set, validate)
from vessel_reconstruction.rules import agreement, formulas, midship

RULE_SET = load_rule_set()

MIDSHIP_COLUMNS = [
    "Double_Bottom_Height", "Bottom_Floor_Thickness", "Bottom_Girder_Thickness",
    "Bottom_Floor_Spacing", "Inner_Bottom_Deck_Thickness", "Hopper_Plate_Thickness",
    "Bottom_Stiffener_SM", "Bottom_Transverse_Stiffener_SM", "Hopper_Stiffener_SM",
    "Side_Frame_SM", "Webframe_SM", "Webframe_Depth", "Webframe_Thickness",
    "Side_Stringer_SM", "Side_Stringer_Depth", "Bulkhead_Thickness",
    "Trans_Bulkhead_Horizontal_Stiffener_SM", "Trans_Bulkhead_Vertical_Stiffener_SM",
    "Deck_Trans_Stiff_SM", "Deck_Thickness", "Deck_Beam_SM", "Deck_Beam_Depth",
    "Deck_Beam_Thickness", "Side_Shell_Thickness", "Bottom_Shell_Thickness",
]


def required(column, ship_type="bulk_carrier", provided=1.0e9, strict=False, **geometry):
    """Run one rule and return the required value."""
    rule = RULE_SET.by_column(column)
    inputs = dict(geometry)
    inputs[rule.data["criterion"]["provided_input"]] = provided
    return rule.evaluate(inputs, ship_type, strict=strict).required


# --- rule data ---------------------------------------------------------------

def test_rule_file_covers_the_25_midship_constraints_once():
    assert [r.midship_column for r in RULE_SET.rules] == MIDSHIP_COLUMNS
    assert len({r.id for r in RULE_SET.rules}) == 25


def test_every_rule_is_cited_with_edition_and_page():
    for rule in RULE_SET.rules:
        for cite in rule.data["citations"]:
            source = RULE_SET.data["sources"][cite["source"]]
            assert source["edition"]
            assert re.match(r"^\d-\d-\d+/\d", cite["ref"])
            assert 1 <= cite["page"] <= 400


def test_status_counts_are_recorded():
    statuses = [r.status for r in RULE_SET.rules]
    assert set(statuses) <= {"encoded", "partial", "not_encoded"}
    assert statuses.count("encoded") + statuses.count("partial") == 25
    for rule in RULE_SET.rules:
        if rule.status == "partial":
            assert rule.data["status_reason"]


def test_validation_rejects_broken_rule_data():
    base = copy.deepcopy(RULE_SET.data)
    broken = copy.deepcopy(base)
    broken["rules"][0]["citations"] = []
    with pytest.raises(RuleDataError):
        validate(broken)
    broken = copy.deepcopy(base)
    broken["rules"][0]["status"] = "done"
    with pytest.raises(RuleDataError):
        validate(broken)
    broken = copy.deepcopy(base)
    broken["rules"][0]["citations"][0]["source"] = "nowhere"
    with pytest.raises(RuleDataError):
        validate(broken)
    broken = copy.deepcopy(base)
    broken["rules"][1]["id"] = broken["rules"][0]["id"]
    with pytest.raises(RuleDataError):
        validate(broken)
    broken = copy.deepcopy(base)
    broken["rules"][0]["check"] = "no_such_check"
    with pytest.raises(RuleDataError):
        validate(broken)


def test_checks_do_not_import_network_modules():
    package = Path(formulas.__file__).parent
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(socket|urllib|http|requests|ssl)\b", text, re.M)


# --- units -------------------------------------------------------------------

def test_unit_conversion():
    assert convert(1500.0, "mm", "m") == pytest.approx(1.5)
    assert convert(2.0, "m", "mm") == pytest.approx(2000.0)
    assert convert(1.0e6, "mm", "mm") == 1.0e6


def test_unit_mismatch_and_unknown_unit_are_errors():
    with pytest.raises(UnitError):
        convert(1.0, "cm3", "m")
    with pytest.raises(UnitError):
        convert(1.0, "furlong", "m")


def test_quantity_input_is_converted_to_the_declared_unit():
    # A depth of 500 mm is read as 0.5 m: 5.0 + 3.5 = 8.5 mm.
    rule = RULE_SET.by_column("Webframe_Thickness")
    result = rule.evaluate({"webframe_depth": Quantity(500.0, "mm"), "web_t_mm": 9.0}, "tanker")
    assert result.required == pytest.approx(8.5)  # 5.0 + 3.5, 3-2-6/3.5.2
    with pytest.raises(UnitError):
        rule.evaluate({"webframe_depth": Quantity(1.0, "cm3"), "web_t_mm": 9.0}, "tanker")


def test_missing_input_is_reported():
    with pytest.raises(MissingInputError):
        RULE_SET.by_column("Webframe_Depth").evaluate({"depth_mm": 1000.0}, "tanker")


# --- hand-computed rule cases ---------------------------------------------------

def test_double_bottom_height_3_2_4_3_1_1c():
    # 32 B + 190 sqrt(d) = 32*20 + 190*sqrt(8) = 640 + 537.401 mm
    assert required("Double_Bottom_Height", "tanker", beam=20.0, draft=8.0) == pytest.approx(1177.401, abs=1e-3)


def test_double_bottom_height_floor_of_0_76_m_3_2_4_1_1i():
    # B = 10 m, d = 4 m: 320 + 380 = 700 mm. 1.1.i raises it to 760 mm for MiDShip non-tankers.
    assert required("Double_Bottom_Height", "tanker", beam=10.0, draft=4.0) == pytest.approx(700.0)
    assert required("Double_Bottom_Height", "bulk_carrier", beam=10.0, draft=4.0) == pytest.approx(760.0)
    assert required("Double_Bottom_Height", "tanker", strict=True, beam=10.0, draft=4.0) == pytest.approx(760.0)


def test_double_bottom_height_cap_of_2_m_in_1_1i():
    # B = 60 m: B/20 = 3 m, capped at 2000 mm. 32*60 + 190*sqrt(9) = 2490 mm governs.
    assert required("Double_Bottom_Height", "bulk_carrier", beam=60.0, draft=9.0) == pytest.approx(2490.0)


def test_floor_and_girder_thickness_3_2_4_5_1():
    # 0.036*250 + 4.7 + 1.5 = 15.2 mm
    assert required("Bottom_Floor_Thickness") == pytest.approx(15.2)
    assert required("Bottom_Girder_Thickness") == pytest.approx(15.2)
    # Center girder, 3-2-4/3.1.1(a): 0.056*250 + 5.5 = 19.5 mm
    assert required("Bottom_Girder_Thickness", strict=True) == pytest.approx(19.5)


def test_floor_spacing_limit_3_2_4_5_1():
    rule = RULE_SET.by_column("Bottom_Floor_Spacing")
    assert rule.evaluate({"floor_spacing_m": 3.66}, "tanker").passed is True
    assert rule.evaluate({"floor_spacing_m": 3.67}, "tanker").passed is False
    assert rule.evaluate({"floor_spacing_m": 3.0}, "tanker").required == pytest.approx(3.66)


def test_plate_thickness_equation_3_2_3_5_1():
    # t = s sqrt(h)/254 + 1.5 with s = 800 mm, h = 3.66 m
    assert formulas.plate_thickness_mm(0.8, 3.66, 254.0, 1.5, 1.0, 1.0) == pytest.approx(7.5256, abs=1e-3)


def test_wheel_loading_3_2_3_5_17():
    assumptions = RULE_SET.by_column("Deck_Thickness").assumptions()
    inputs = {"sp_webframe": 2.0, "sp_bottom_girder": 2.0}
    # Aspect ratio 1: n = 0.85. W = 13800*9.81/1000 = 135.378 kN.
    # t = 1.1*8.05*0.2*0.85*sqrt(1.5*135.378) = 21.452 mm
    assert formulas.wheel_load_thickness_mm(inputs, assumptions) == pytest.approx(21.452, abs=1e-2)
    # Aspect ratio 2 or more: n = 1.0, t = 25.236 mm
    inputs = {"sp_webframe": 4.0, "sp_bottom_girder": 2.0}
    assert formulas.wheel_load_thickness_mm(inputs, assumptions) == pytest.approx(25.236, abs=1e-2)


def test_bottom_section_modulus_tanker_3_2_4_7_3_and_3_2_10_3_3():
    # Tanker: h = max(0.667*10, 10 - 2 + 1.3) = 9.3 m. s = 0.6 m, l = 3.0 m, c = 1.0.
    # SM = 7.8*1.0*9.3*0.6*3.0^2 = 391.716 cm3
    sm = required("Bottom_Stiffener_SM", "tanker", sp_frame=0.6, sp_bottom_stringer=0.5,
                  sp_webframe=3.0, sp_bottom_girder=2.0, depth=10.0, db_height=2.0)
    assert sm == pytest.approx(391.716, abs=1e-3)


def test_bottom_section_modulus_non_tanker_uses_two_thirds_depth():
    # Non-tanker: h = 0.667*10 = 6.67 m. SM = 7.8*6.67*0.6*9 = 280.9 cm3
    sm = required("Bottom_Stiffener_SM", "bulk_carrier", sp_frame=0.6, sp_bottom_stringer=0.5,
                  sp_webframe=3.0, sp_bottom_girder=2.0, depth=10.0, db_height=2.0)
    assert sm == pytest.approx(280.9, abs=0.1)


def test_web_frame_depth_and_thickness_3_2_6_3_5_2():
    assert required("Webframe_Depth", h_cargo=9.0) == pytest.approx(1125.0)  # 0.125 * 9 m
    assert required("Webframe_Thickness", webframe_depth=1.125) == pytest.approx(14.0)  # 14.75 capped
    assert required("Webframe_Thickness", webframe_depth=0.5) == pytest.approx(8.5)


def test_side_stringer_depth_3_2_6_5_3():
    assert required("Side_Stringer_Depth", sp_webframe=3.0) == pytest.approx(375.0)


def test_deck_beam_rules_3_2_8():
    # SM = 4.74*1.5*3.66*l^2*b with l = 2.0 m girder spacing and b = 3.0 m
    sm = required("Deck_Beam_SM", sp_deck_girder=2.0, sp_webframe=3.0)
    assert sm == pytest.approx(312.2712, abs=1e-3)
    assert required("Deck_Beam_Depth", sp_deck_girder=2.0) == pytest.approx(166.6)  # 0.0833*2000
    # Thickness: depth 0.9 m gives 9 + 4 = 13 mm, raised to 15 mm by the face-area option.
    assert required("Deck_Beam_Thickness", deck_beam_depth=0.9) == pytest.approx(15.0)
    # No deck girder in the design: no requirement.
    assert required("Deck_Beam_SM", sp_deck_girder=0.0, sp_webframe=3.0) == 0.0


def test_side_shell_thickness_3_2_2_3_9_3():
    # L = 250 m, s = 700 mm, D = 10 m, d = 6.667 m. d/D = max(0.6667, 0.0433*250/10) = 1.0825.
    # (700/645) sqrt((250 - 15.2)*1.0825) + 2.5 = 19.802 mm
    t = required("Side_Shell_Thickness", sp_frame=0.7, sp_side_stringer=0.5, depth=10.0, draft=6.667)
    assert t == pytest.approx(19.802, abs=1e-2)


def test_bottom_shell_thickness_3_2_2_3_15_1():
    # Same case. (700/508) sqrt((250 - 62.5)*1.0825) + 2.5 = 22.13 mm; the minimum equation gives
    # 700*(250 - 18.3)/(42*250 + 1070) = 14.0 mm.
    t = required("Bottom_Shell_Thickness", sp_frame=0.7, sp_side_stringer=0.5, sp_bottom_stringer=0.4,
                 depth=10.0, draft=6.667)
    assert t == pytest.approx(1000 * 0.7 / 508 * (187.5 * 1.0825) ** 0.5 + 2.5, abs=1e-6)
    assert t == pytest.approx(22.13, abs=0.01)


def test_hopper_rules_do_not_apply_to_tankers():
    rule = RULE_SET.by_column("Hopper_Plate_Thickness")
    assert rule.evaluate({}, "tanker").applicable is False
    assert RULE_SET.by_column("Hopper_Stiffener_SM").evaluate({}, "tanker").passed is None


def test_pass_fail_follows_value_at_least_required():
    rule = RULE_SET.by_column("Bottom_Floor_Thickness")
    assert rule.evaluate({"floor_t_mm": 15.2}, "tanker").passed is True
    assert rule.evaluate({"floor_t_mm": 15.1}, "tanker").passed is False


def test_section_modulus_of_plate_and_web():
    # Plate 100 x 10 mm, web 100 x 10 mm, no flange.
    # Area 2000 mm2, centroid 25 mm, I = 2,091,666.7 mm4, z = 75 mm, SM = 27.889 cm3
    assert midship.section_modulus_cm3(10.0, 100.0, 100.0, 10.0, 0.0) == pytest.approx(27.889, abs=1e-3)


# --- MiDShip adapter -------------------------------------------------------------

def test_parameter_layout_splits_spans_into_equal_gaps():
    row = {"L_3h": 40.0, "B": 20.0, "D": 10.0, "Db": 2000.0, "l_overhang": 0.05,
           "web frames per hold": 8.0, "num intermediate trans frames": 3.0,
           "num bottom girders": 6.0, "num top girders": 6.0,
           "num intermediate bottom stiffeners": 4.0, "num intermediate deck stiffeners": 4.0,
           "num side shell stiffeners": 19.0, "num transverse bulkhead stiffeners": 19.0,
           "num vertical bulkhead stiffeners": 6.0, "web frame h": 2000.0,
           "floor web bracket L2": 1000.0, "deck web bracket  L2": 1000.0,
           "trans deck beam h": 900.0, "cont step height": 0.0}
    geometry = midship.inputs_from_parameters(row, "tanker").geometry
    assert geometry["sp_webframe"] == pytest.approx((40.0 - 4.0) / 3.0 / 9.0)  # 1.3333 m
    assert geometry["sp_frame"] == pytest.approx(1.3333 / 4.0, abs=1e-4)
    assert geometry["sp_bottom_girder"] == pytest.approx((10.0 - 2.0) / 5.0)  # 1.6 m
    assert geometry["sp_side_stringer"] == pytest.approx(10.0 / 20.0)
    container = midship.inputs_from_parameters({**row, "cont step height": 4000.0}, "container_ship").geometry
    assert container["sp_deck_girder"] == 0.0 and container["deck_beam_depth"] == 0.0


def test_noisy_duplicate_positions_are_merged_unless_legacy():
    positions = [0.0, 1.0e-15, 0.5, 1.0]
    assert midship._gaps(positions, True, False) == pytest.approx(0.5)
    assert midship._gaps(positions, True, True) == pytest.approx(1.0e-15)


def test_stored_sign_of_spacing_column():
    assert agreement.stored_sign("Bottom_Floor_Spacing") == -1.0
    assert agreement.stored_sign("Side_Shell_Thickness") == 1.0


# --- data-backed check (skipped when the git-ignored MiDShip sample is absent) ----

MIDSHIP_ROOT = Path(os.environ.get(
    "MIDSHIP_ROOT", "/Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources/midship"))


@pytest.mark.skipif(not (MIDSHIP_ROOT / "SGLD_Gen_Structures").is_dir(),
                    reason="MiDShip sample is not available")
def test_sgld_bom_designs_agree_with_the_dataset_when_evaluator_spacing_is_replicated():
    tables = agreement.load_tables(MIDSHIP_ROOT, "SGLD")
    base = MIDSHIP_ROOT / "SGLD_Gen_Structures"
    checked = 0
    for path in sorted(base.glob("sgld_design_*_Structural_Elements.csv")):
        index = int(path.name.split("_")[2])
        for item in agreement.compare_bom(RULE_SET, tables, index, path, legacy_unique=True):
            assert item.threshold_match, (index, item.column)
            assert item.mine_pass == item.ms_pass, (index, item.column)
            checked += 1
    assert checked >= 12 * 20
