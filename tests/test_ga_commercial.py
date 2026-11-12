"""Commercial GA reading: tiling, parsing, interpretation and the exam scorer.

All inputs are synthetic. No model is called and no partner drawing is used.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from vessel_reconstruction import ga_commercial as ga
from vessel_reconstruction import source_record

ROOT = Path(__file__).resolve().parents[1]


def _scorer():
    spec = importlib.util.spec_from_file_location("score_ga_exam", ROOT / "scripts" / "score_ga_exam.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sheet(path: Path, size=(3000, 1500)) -> Path:
    """A synthetic GA: four hold boxes with ink, blank paper elsewhere."""
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    step = (size[0] - 100) // 4
    for index in range(4):
        left = 50 + index * step
        draw.rectangle([left, 100, left + step - 40, 600], outline=0, width=4)
        draw.text((left + 20, 200), f"NO.{4 - index} CARGO HOLD", fill=0)
    image.save(path)
    return path


# ------------------------------------------------------------------ images

@pytest.mark.parametrize("size", [(3000, 1500), (2809, 2325), (1968, 273), (6000, 600), (900, 700)])
def test_tiles_cover_the_sheet_within_provider_limits(size):
    columns, rows, scale = ga.tile_grid(*size, max_tiles=5)
    boxes = ga.tile_boxes(*size, columns, rows)
    assert columns * rows <= 5
    assert min(b[0] for b in boxes) == 0 and max(b[2] for b in boxes) == size[0]
    assert min(b[1] for b in boxes) == 0 and max(b[3] for b in boxes) == size[1]
    for left, top, right, bottom in boxes:
        width, height = round((right - left) * scale), round((bottom - top) * scale)
        assert max(width, height) <= ga.MAX_SIDE_PX and width * height <= ga.MAX_PIXELS


def test_prepare_writes_bounded_images_and_keeps_the_source_map_host_side(tmp_path):
    sheet = _sheet(tmp_path / "S-1_GA.png")
    manifest = ga.prepare(sheet, tmp_path / "request")
    assert manifest["purpose"] == "ga_reading" and manifest["engineering_approved"] is False
    assert len(manifest["images"]) <= ga.MAX_IMAGES
    assert sum(i["bytes"] for i in manifest["images"]) <= ga.MAX_TOTAL_IMAGE_BYTES
    assert "S-1_GA.png" not in json.dumps(manifest["context"])
    sources = json.loads((tmp_path / "request" / "sources.json").read_text())
    assert sources["sources"]["ga"]["file"] == "S-1_GA.png"


def test_a_particulars_table_alone_is_a_request(tmp_path):
    table = Image.new("L", (800, 400), 255)
    ImageDraw.Draw(table).text((20, 20), "L.O.A. 189.99 m", fill=0)
    table.save(tmp_path / "S-2_table.png")
    manifest = ga.prepare(None, tmp_path / "request", tmp_path / "S-2_table.png")
    assert [i["view"] for i in manifest["images"]] == ["particulars_table"]


def test_case_files_find_the_ga_and_one_table(tmp_path):
    for name in ("C-1_GA.png", "C-1_particulars.png", "C-2_GA.png", "C-10_GA.png"):
        Image.new("L", (10, 10), 255).save(tmp_path / name)
    assert ga.case_files(tmp_path, "C-1") == (tmp_path / "C-1_GA.png", tmp_path / "C-1_particulars.png")
    assert ga.case_files(tmp_path, "C-2") == (tmp_path / "C-2_GA.png", None)
    with pytest.raises(ValueError):
        ga.case_files(tmp_path, "C-3")


# ------------------------------------------------------------------ parsing

@pytest.mark.parametrize("printed, unit, field, expected", [
    ("189.99 m", None, "loa_m", 189.99),
    ("189.99", "(m)", "loa_m", 189.99),
    ("32.26M", None, "breadth_m", 32.26),
    ("18,500 mm", None, "depth_m", 18.5),
    ("32,26 m", None, "breadth_m", 32.26),
    ("600' 0\"", None, "loa_m", 182.88),
])
def test_printed_lengths_parse_to_metres(printed, unit, field, expected):
    value, _ = ga.parse_length(printed, unit, field)
    assert value == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("printed, unit, field", [
    ("189.99", None, "loa_m"),          # no unit anywhere: never assumed
    ("18.5 mm", None, "depth_m"),       # implausible after the unit
    ("abc m", None, "loa_m"),
    ("1,850 m", None, "breadth_m"),     # 1850 m or 1.85 m: neither plausible
])
def test_unclear_lengths_abstain(printed, unit, field):
    assert ga.parse_length(printed, unit, field)[0] is None


def test_a_comma_with_two_plausible_readings_abstains():
    # 32,260 m: 32.26 m (decimal comma) is a plausible depth; 32260 m is not.
    assert ga.parse_length("32,260 m", None, "depth_m")[0] == pytest.approx(32.26)
    # 20,500 mm: 20.5 m or 0.0205 m; only one plausible.
    assert ga.parse_length("20,500 mm", None, "depth_m")[0] == pytest.approx(20.5)


def test_deadweight_needs_a_tonne_unit():
    assert ga.parse_mass("57,000 t", None)[0] == 57000
    assert ga.parse_mass("57000", "MT")[0] == 57000
    assert ga.parse_mass("57000", None)[0] is None
    assert ga.parse_mass("57,000 long tons", None)[0] is None


# ------------------------------------------------------------------ interpretation

def _reading(reply: dict | None) -> dict:
    usage = {"requests_intended": 1, "requests_completed": 1, "prompt_tokens": 9000, "completion_tokens": 2000,
             "observed_cost_usd": 0.0}
    return {"requested_model": "claude-sonnet-5-5", "endpoint": "claude-cli:print:subscription",
            "usage": usage, "receipts": [{"usage": {"list_cost": 0.1}}],
            "reply": None if reply is None else {"ga_reading": reply}, "stop_reason": None}


def _hold(number: str, left: float, image: str = "sheet", basis: str = "read") -> dict:
    return {"kind": "cargo_hold", "label": f"NO.{number} CARGO HOLD" if basis == "read" else "",
            "number": number if basis == "read" else None, "basis": basis, "image_id": image,
            "box": [left, 150, left + 120, 300]}


def _counts(**overrides) -> dict:
    counts = {name: {"missing": "not shown"} for name in ga.COUNT_KINDS}
    counts.update(overrides)
    return counts


@pytest.fixture()
def prepared(tmp_path):
    sheet = _sheet(tmp_path / "S-1_GA.png", size=(1000, 1000))
    ga.prepare(sheet, tmp_path / "request")
    request = json.loads((tmp_path / "request" / "request.json").read_text())
    assert [i["image_id"] for i in request["images"]] == ["sheet"]  # one native image
    return tmp_path


def test_counts_spaces_and_records(prepared):
    reply = {"ship_type": {"value": "bulk_carrier", "evidence": "holds"},
             "particulars": [{"field": "loa", "printed": "189.99 m", "unit_context": None, "image_id": "sheet",
                              "box": [60, 100, 400, 600], "evidence": "L.O.A."}],
             "items": [_hold("1", 60), _hold("2", 285), _hold("3", 510), _hold("4", 735, basis="guessed"),
                       # a box on blank paper is dropped
                       {"kind": "engine_room", "label": "ENGINE ROOM", "number": None, "basis": "read",
                        "image_id": "sheet", "box": [5, 850, 60, 890]}],
             "counts": _counts(cargo_holds={"value": 4, "evidence": "four holds"},
                               cargo_cranes={"value": 0, "evidence": "gearless"}),
             "refused": [{"entry": {"label": "NO.5 W.B.T."}, "error_code": "ga_item_contract"}]}
    result = ga.interpret(_reading(reply), prepared / "request", prepared)
    assert result["engineering_approved"] is False
    assert result["particulars"]["loa_m"]["value"] == pytest.approx(189.99)
    assert result["particulars"]["loa_m"]["source_record"]["kind"] == "read"
    assert result["particulars"]["lbp_m"] == {"value": None, "status": "unknown", "reason": "not found printed"}
    holds = result["counts"]["cargo_holds"]
    assert (holds["value"], holds["status"], holds["labelled_items"]) == (4, "read", 3)
    assert result["counts"]["cargo_cranes"]["value"] == 0  # zero is a count, not an abstention
    assert result["counts"]["cargo_hatches"]["value"] is None
    statuses = sorted(s["status"] for s in result["spaces"])
    assert statuses == ["guessed", "read", "read", "read"]
    for space in result["spaces"]:
        source_record.validate(space["source_record"])
        region = (space["source_record"].get("regions") or space["source_record"]["inputs"])[0]
        assert region["sheet"] == "S-1_GA.png" and region["page_px"] == [1000, 1000]
    codes = [c["code"] for c in result["checks"]]
    assert "item_box_without_ink" in codes and "ga_item_contract" in codes


def test_a_count_below_the_labelled_items_abstains(prepared):
    reply = {"ship_type": {"missing": "unclear"}, "particulars": [],
             "items": [_hold("1", 60), _hold("2", 285), _hold("3", 510)],
             "counts": _counts(cargo_holds={"value": 2, "evidence": "two holds"})}
    result = ga.interpret(_reading(reply), prepared / "request", prepared)
    assert result["counts"]["cargo_holds"]["value"] is None
    assert result["counts"]["cargo_holds"]["source_record"]["kind"] == "unknown"


def _count_result(spaces, **counts):
    region = source_record.region("S_GA.png", view=None, box_px=[1, 1, 9, 9], page_px=[100, 100])
    return {"sources": {"ga": {"file": "S_GA.png"}}, "checks": [], "counts": {},
            "model_counts": _counts(**counts),
            "spaces": [{"id": f"s{i}", "kind": kind, "number": number, "status": "read", "view_id": view,
                        "source_record": source_record.read([region])}
                       for i, (kind, number, view) in enumerate(spaces)]}


def test_tanks_are_counted_within_one_view_not_across_notations():
    profile = [("cargo_tank", str(n), "v1") for n in range(1, 7)]
    tank_top = [("cargo_tank", f"{n}{side}", "v2") for n in range(1, 7) for side in "PS"]
    result = _count_result(profile + tank_top, cargo_tanks={"value": 12, "evidence": "6 x (P&S)"})
    ga.finish_counts(result)
    assert result["counts"]["cargo_tanks"]["value"] == 12
    assert result["counts"]["cargo_tanks"]["labelled_items"] == 12


def test_a_view_missing_a_label_is_not_a_contradiction_but_a_shorter_view_is():
    profile = [("cargo_hold", str(n), "v1") for n in range(1, 6)]
    gaps = [("cargo_hold", n, "v2") for n in ("1", "2", "5")]
    result = _count_result(profile + gaps, cargo_holds={"value": 5, "evidence": "five"})
    ga.finish_counts(result)
    assert result["counts"]["cargo_holds"]["value"] == 5
    shorter = [("cargo_hold", str(n), "v2") for n in range(1, 5)]
    result = _count_result(profile + shorter, cargo_holds={"value": 5, "evidence": "five"})
    ga.finish_counts(result)
    assert result["counts"]["cargo_holds"]["value"] is None
    assert "up to No.4" in result["counts"]["cargo_holds"]["reason"]


def test_fine_pass_numbers_do_not_end_a_view():
    profile = [("cargo_tank", str(n), "v1") for n in range(1, 8)]
    deck = [("cargo_tank", n, "v2") for n in ("2", "5")]
    result = _count_result(profile + deck, cargo_tanks={"value": 14, "evidence": "7 x (P&S)"})
    for space in result["spaces"][len(profile):]:
        space["found_by"] = "fine"
    ga.finish_counts(result)
    assert result["counts"]["cargo_tanks"]["value"] == 14
    assert result["counts"]["cargo_tanks"]["views_compared"] == 1


def test_a_cut_label_without_its_side_is_not_another_tank():
    """Review of the adaptive fine pass: "NO.6 C.O.T.K" (cut) beside NO.6 (P) and (S) is no 13th tank."""
    sided = [("cargo_tank", f"{n}{side}", "v2") for n in range(1, 7) for side in "PS"]
    result = _count_result(sided + [("cargo_tank", "6", "v2")], cargo_tanks={"value": 12, "evidence": "6 x (P&S)"})
    ga.finish_counts(result)
    assert (result["counts"]["cargo_tanks"]["value"], result["counts"]["cargo_tanks"]["labelled_items"]) == (12, 12)
    assert ga._number_with_side("3", "NO.3 C.O.TK(P)") == "3P" and ga._number_with_side("3", "NO.3 C.O.TK(P&S)") == "3"
    assert ga._number_with_side("4A", "NO.4A HOLD") == "4A" and ga._number_with_side(None, "ENGINE ROOM") is None


def test_hold_halves_are_two_holds_by_default_and_one_by_setting():
    """Definition (PM, 2026-11-12): No.4A and No.4F are two holds; the other rule is a setting."""
    halves = [("cargo_hold", f"{n}{half}", "v1") for n in range(1, 5) for half in "AF"]
    result = _count_result(halves, cargo_holds={"value": 8, "evidence": "eight holds, each with a hatch"})
    ga.finish_counts(result)
    assert (result["counts"]["cargo_holds"]["value"], result["counts"]["cargo_holds"]["labelled_items"]) == (8, 8)
    # A model count of 4 is below the eight labelled holds: abstain, never answer 4.
    result = _count_result(halves, cargo_holds={"value": 4, "evidence": "four numbers"})
    ga.finish_counts(result)
    assert result["counts"]["cargo_holds"]["value"] is None
    result = _count_result(halves, cargo_holds={"value": 4, "evidence": "four numbers"})
    result["definitions"] = {**ga.DEFINITIONS, "split_holds_are_separate": False}
    ga.finish_counts(result)
    assert (result["counts"]["cargo_holds"]["value"], result["counts"]["cargo_holds"]["labelled_items"]) == (4, 4)


def test_the_definitions_go_to_the_model_and_follow_the_settings(tmp_path):
    sheet = _sheet(tmp_path / "S-1_GA.png", size=(1000, 1000))
    manifest = ga.prepare(sheet, tmp_path / "default")
    text = " ".join(manifest["context"]["definitions"])
    assert "two holds" in text and "SLOP HOLDING TK" in text and "usually equal" in text
    other = ga.prepare(sheet, tmp_path / "other", definitions={"split_holds_are_separate": False,
                                                               "slop_holding_tank_is_slop": False})
    text = " ".join(other["context"]["definitions"])
    assert "count as one hold" in text and "slop holding tank is not counted" in text
    assert json.loads((tmp_path / "other" / "sources.json").read_text())["definitions"] == {
        "split_holds_are_separate": False, "slop_holding_tank_is_slop": False}


def test_holds_and_hatches_that_differ_on_a_bulk_carrier_are_listed():
    spaces = [("cargo_hold", str(n), "v1") for n in range(1, 6)]
    result = _count_result(spaces, cargo_holds={"value": 5, "evidence": "five"},
                           cargo_hatches={"value": 4, "evidence": "four"})
    result["ship_type"] = {"value": "bulk_carrier"}
    ga.finish_counts(result)
    ga.finish_counts(result)  # the fine pass counts again: the check is listed once
    assert [c["code"] for c in result["checks"]].count("holds_and_hatches_differ") == 1
    assert result["counts"]["cargo_holds"]["value"] == 5  # listed, not refused


def test_a_fine_label_completes_a_view_that_the_coarse_pass_listed():
    """Development batch 3: the coarse pass missed the last hold label of the tank top plan."""
    profile = [("cargo_hold", str(n), "v1") for n in range(1, 5)]
    tank_top = [("cargo_hold", str(n), "v2") for n in range(1, 4)]
    result = _count_result(profile + tank_top, cargo_holds={"value": 4, "evidence": "four"})
    ga.finish_counts(result)
    assert result["counts"]["cargo_holds"]["value"] is None      # v2 ends at No.3
    result = _count_result(profile + tank_top + [("cargo_hold", "4", "v2")], cargo_holds={"value": 4, "evidence": "four"})
    result["spaces"][-1]["found_by"] = "fine"
    ga.finish_counts(result)
    assert result["counts"]["cargo_holds"]["value"] == 4


def test_lbp_longer_than_loa_is_not_used(prepared):
    def particular(field, printed):
        return {"field": field, "printed": printed, "unit_context": None, "image_id": "sheet",
                "box": [60, 100, 400, 600], "evidence": "row"}
    reply = {"ship_type": {"missing": "unclear"}, "items": [], "counts": _counts(),
             "particulars": [particular("loa", "180.00 m"), particular("lbp", "185.00 m")]}
    result = ga.interpret(_reading(reply), prepared / "request", prepared)
    assert result["particulars"]["loa_m"]["value"] is None and result["particulars"]["lbp_m"]["value"] is None


def test_no_reply_means_every_value_is_unknown(prepared):
    result = ga.interpret(_reading(None), prepared / "request", prepared)
    assert all(v["value"] is None for v in result["particulars"].values())
    assert all(v["value"] is None for v in result["counts"].values())


def test_a_request_without_a_reading_still_counts_and_abstains(prepared, tmp_path):
    receipts = tmp_path / "provider" / "receipts"
    receipts.mkdir(parents=True)
    receipts.joinpath("vision-1.json").write_text(json.dumps(
        {"state": "completed", "usage": {"prompt_tokens": 9000, "completion_tokens": 3000, "list_cost": 0.15},
         "observed_cost_usd": 0.0}))
    stderr = '{"engineering_approved":false,"error_code":"typed_contract_rejected","ok":false}\n'
    reading = ga.failed_reading(tmp_path / "provider", "claude-sonnet-5-5", stderr)
    result = ga.interpret(reading, prepared / "request", prepared)
    assert result["usage"]["requests"] == 1 and result["usage"]["list_cost_usd"] == 0.15
    assert result["counts"]["cargo_holds"]["reason"] == "vision_request_failed: typed_contract_rejected"
    assert all(v["value"] is None for v in result["particulars"].values())


def test_the_app_run_folder(prepared, tmp_path):
    reply = {"ship_type": {"value": "tanker", "evidence": "C.O.T."}, "particulars": [],
             "items": [_hold("1", 60)], "counts": _counts()}
    result = ga.interpret(_reading(reply), prepared / "request", prepared)
    task = ga.write_app_run(result, prepared, tmp_path / "task", "demo")
    state = json.loads((task / "domain" / "state.json").read_text())
    assert state["inspection_artifacts"][0]["path"] == "ga_reading/S-1_GA.png"
    assert (task / "ga_reading" / "S-1_GA.png").is_file()
    assert json.loads((task / "state.json").read_text())["state"]["engineering_approved"] is False


# ------------------------------------------------------------------ scorer

def test_scorer_separates_wrong_answers_from_abstentions(tmp_path):
    scorer = _scorer()
    answers = {"H-1": {"LOA": 189.99, "LBP": 182.0, "B": 32.26, "D": None, "holds": 5, "hatches": 5, "cranes": 0},
               "H-2": {"holds": 7, "cranes": 4}}
    predictions = {"H-1": {"loa_m": 189.994, "lbp_m": 182.1, "breadth_m": None, "depth_m": None,
                           "cargo_holds": 5, "cargo_hatches": 4, "cargo_cranes": 0},
                   "H-2": {"cargo_holds": None, "cargo_cranes": 3}}
    (tmp_path / "answers.json").write_text(json.dumps(answers))
    result = scorer.score(predictions, scorer.load_answers(tmp_path / "answers.json"))
    particulars, counts = result["groups"]["particulars"], result["groups"]["counts"]
    # LOA within 5 mm; LBP 10 cm off; B abstained; D expected null and abstained.
    assert (particulars["correct"], particulars["wrong"], particulars["abstained"],
            particulars["correct_abstention"]) == (1, 1, 1, 1)
    # holds 5 ok, hatches wrong, cranes 0 ok; H-2: holds abstained, cranes wrong.
    assert (counts["correct"], counts["wrong"], counts["abstained"]) == (2, 2, 1)
    assert counts["accuracy_when_answered"] == 0.5
    assert result["fields"]["cargo_cranes"]["correct"] == 1


def test_scorer_reads_csv_answers_and_reading_folders(tmp_path):
    scorer = _scorer()
    (tmp_path / "answers.csv").write_text("case,LOA,LBP,holds,cranes\nH-1,100.5,unreadable,4,\n")
    answers = scorer.load_answers(tmp_path / "answers.csv")
    assert answers == {"H-1": {"loa_m": 100.5, "lbp_m": None, "cargo_holds": 4.0}}
    folder = tmp_path / "outputs" / "H-1"
    folder.mkdir(parents=True)
    folder.joinpath("ga_reading.json").write_text(json.dumps({
        "particulars": {"loa_m": {"value": 100.5}, "lbp_m": {"value": 99.0}},
        "counts": {"cargo_holds": {"value": 4}}}))
    result = scorer.score(scorer.load_predictions(tmp_path / "outputs"), answers)
    assert result["per_case"]["H-1"]["fields"] == {"loa_m": "correct", "lbp_m": "wrong", "cargo_holds": "correct"}
    assert scorer.load_predictions(tmp_path / "outputs")["H-1"]["cargo_cranes"] is None


def test_a_missing_prediction_is_an_abstention_and_listed():
    scorer = _scorer()
    result = scorer.score({}, {"H-9": {"cargo_holds": 3.0}})
    assert result["groups"]["counts"]["abstained"] == 1
    assert result["cases_without_prediction"] == ["H-9"]


def test_a_measured_value_is_never_an_exam_answer(tmp_path):
    """The arrangement input carries measured particulars; the scorer takes printed ones only."""
    scorer = _scorer()
    reading = {"particulars": {"lbp_m": {"value": 133.0, "status": "measured_from_scale"},
                               "loa_m": {"value": 139.9, "status": "read"}},
               "measured": {"breadth_m": {"value": 24.8, "status": "measured_from_scale"}},
               "counts": {"cargo_holds": {"value": 4}}}
    (tmp_path / "S-1").mkdir()
    (tmp_path / "S-1" / "ga_reading.json").write_text(json.dumps(reading))
    row = scorer.load_predictions(tmp_path)["S-1"]
    assert row["lbp_m"] is None and row["breadth_m"] is None and row["loa_m"] == 139.9 and row["cargo_holds"] == 4


@pytest.mark.parametrize("label, others, cut", [
    ("NO. 4", [], True),                                     # only a number
    ("T. S. W. B. T. (", [], True),                          # unclosed parenthesis
    ("NO. 2 F", [], True),                                   # a cut letter after the number
    ("NO. 5 W.", [], True),
    ("NO. 2 CARG", ["NO.2 CARGO HOLD"], True),               # the start of a longer word
    ("GEAR", ["STEERING GEAR ROOM"], True),                  # a word printed only inside longer labels
    ("STORE", ["STORE", "BOSUN STORE"], False),              # printed alone elsewhere: a room name
    ("SLOP O.T.", ["SLOP TK(P) O.T.H."], False),             # a dotted abbreviation is not a cut word
    ("NO.3 C.O.T. (P)", ["NO.3 C.O.T. (S)"], False),
])
def test_a_cut_or_untyped_label_is_not_a_space(label, others, cut):
    """Lane W round u6: "NO. 4", "NO. 2 CARG", "GEAR", "T. S. W. B. T. (" became spaces."""
    space = {"label": label, "kind": "other_space", "number": None,
             "source_record": {"kind": "read", "regions": [{"box_px": [0, 0, 10, 10]}]}}
    other_spaces = [{"label": o, "kind": "other_space", "number": None,
                     "source_record": {"kind": "read", "regions": [{"box_px": [500, 500, 510, 510]}]}}
                    for o in others]
    vocabulary = {w for o in others for w in ga._words(o)}
    wholes = {"".join(ga._words(o)) for o in others}
    assert (ga.fragment_reason(space, other_spaces, vocabulary, wholes) is not None) is cut


def test_a_piece_read_where_a_longer_label_is_printed_is_dropped_with_its_reason():
    def space(label, box, kind="other_space"):
        return {"id": label, "label": label, "kind": kind, "number": None, "status": "read", "view_id": None,
                "source_record": {"kind": "read", "regions": [{"box_px": box}]}}
    result = {"spaces": [space("COOL. W. T. (C)", [0, 0, 100, 20]), space("W. T. (C)", [40, 0, 100, 20]),
                         space("SLOP TK(P)", [200, 0, 260, 20], "slop_tank"),
                         space("SLOP TK(P) O.T.H.", [200, 0, 300, 20], "slop_tank")], "checks": []}
    assert ga.drop_fragments(result) == 1
    assert [s["label"] for s in result["spaces"]] == ["COOL. W. T. (C)", "SLOP TK(P)", "SLOP TK(P) O.T.H."]
    assert result["checks"][0]["code"] == "fragment_label_dropped" and "COOL" in result["checks"][0]["reason"]


@pytest.mark.parametrize("label, number, others, dropped", [
    ("PILOT LADDER", None, [], True),                        # a fitting, not a space (lane W, round u6r)
    ("HATCH OPEN.", None, [], True),                         # an opening
    ("HATCH OPENI", None, [], True),                         # an opening label cut inside its word
    ("BOATSWAIN STORE", None, [], False),
    ("RESCUE BOAT", None, [], True),
    ("FOAM", None, [], True),                                # a system word without its room noun
    ("FOAM ROOM", None, [], False),
    ("UPPER DECK", None, [], True),                          # a deck name (review round 4)
    ("NO.I T.", "I", [], True),                              # a capital I for 1, then one letter (round u10)
    ("DECK STORE", None, [], False),
    ("CHANGING ROOM (DECK)", None, [], False),
    ("FOLDING TYPE", None, [], True),                        # a note beside a hatch cover
    ("A/H TO NO.5 HOLD", None, [], True),                    # an access hatch (review round 4)
    ("ACCESS HATCH TO DUCT KEEL", None, [], True),
    ("HATCH COVER STORE", None, [], False),                  # a store for a fitting is a space
    ("X.Y.Z.K(P)", None, [("NO.1 X.Y.ZK(P&S)", "1")], True),   # a numbered tank read without its number
    ("X.Y.Z.K(P)", None, [("X.Y.ZK STORE", None)], False),
    ("NO. 2 F.O.", "2", [("2 F. O. T. (P/S)", "2")], True),  # cut dotted abbreviation of the same tank
    ("NO.4 C.O.T(P&S)", "4", [("NO.4 C.O.T(P&S) X", "4")], False),
    ("C02 RM", None, [("S/G RM", None)], False),             # "C" of CO2 is not a side mark
])
def test_fittings_systems_and_cut_abbreviations_are_not_spaces(label, number, others, dropped):
    space = {"label": label, "kind": "other_space", "number": number,
             "source_record": {"kind": "read", "regions": [{"box_px": [0, 0, 10, 10]}]}}
    other_spaces = [{"label": o, "kind": "fuel_tank", "number": n,
                     "source_record": {"kind": "read", "regions": [{"box_px": [500, 500, 510, 510]}]}}
                    for o, n in others]
    vocabulary = {w for o, _ in others for w in ga._words(o)}
    wholes = {"".join(ga._words(o)) for o, _ in others}
    assert (ga.fragment_reason(space, other_spaces, vocabulary, wholes) is not None) is dropped



# ------------------------------------------------------------------ holdout exam fixes (2026-11-12)

@pytest.mark.parametrize("printed, expected", [
    ("ABT. 147,87 M", 147.87), ("abt.229.00 m", 229.0), ("About 120.5 m", 120.5),
    ("APPROX. 99.0 M", 99.0), ("approximately 99 m", 99.0),
])
def test_a_value_printed_as_approximate_is_read(printed, expected):
    assert ga.parse_length(printed, None, "loa_m")[0] == pytest.approx(expected)


@pytest.mark.parametrize("printed", ["ABT 147,87 - 148 M", "ABT. 147.87", "about", "ABT. 147 / 150 M"])
def test_an_approximate_value_with_a_range_or_no_unit_still_abstains(printed):
    assert ga.parse_length(printed, None, "loa_m")[0] is None


def _table_case(tmp_path, ga_name="S-3.png", table_name="S-3.png"):
    """A GA and a particulars table in two folders; the table prints its LOA at (100, 60)."""
    (tmp_path / "ga").mkdir()
    (tmp_path / "table").mkdir()
    sheet = _sheet(tmp_path / "ga" / ga_name, size=(1000, 1000))
    table = Image.new("L", (800, 400), 255)
    ImageDraw.Draw(table).text((100, 60), "L.O.A. 189.99 m", fill=0, font=ImageFont.load_default(size=28))
    table.save(tmp_path / "table" / table_name)
    ga.prepare(sheet, tmp_path / "request", tmp_path / "table" / table_name)
    request = json.loads((tmp_path / "request" / "request.json").read_text())
    image = next(i for i in request["images"] if i["view"].startswith("particulars_table"))
    scale = image["width"] / 800
    box = [round(v * scale) for v in (90, 50, 420, 100)]
    reply = {"ship_type": {"missing": "x"}, "items": [], "counts": _counts(),
             "particulars": [{"field": "loa", "printed": "189.99 m", "unit_context": None,
                              "image_id": image["image_id"], "box": box, "evidence": "L.O.A. row"}]}
    return _reading(reply), tmp_path / "ga"


def test_a_table_value_is_checked_for_ink_on_the_table_even_with_the_name_of_the_ga(tmp_path):
    """Holdout exam: all values of one table were refused as boxes without ink."""
    reading, ga_folder = _table_case(tmp_path)
    result = ga.interpret(reading, tmp_path / "request", ga_folder)
    assert result["particulars"]["loa_m"]["value"] == pytest.approx(189.99)


def test_a_16_bit_or_transparent_image_keeps_its_ink(tmp_path):
    text = Image.new("L", (200, 60), 255)
    ImageDraw.Draw(text).text((10, 10), "189.99 m", fill=0, font=ImageFont.load_default(size=28))
    wide = Image.fromarray(np.asarray(text, dtype=np.uint16) * 257)  # a 16-bit grey image
    assert wide.mode.startswith("I;16")
    wide.save(tmp_path / "wide.png")
    rgba = Image.new("RGBA", (200, 60), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).text((10, 10), "189.99 m", fill=(0, 0, 0, 255), font=ImageFont.load_default(size=28))
    rgba.save(tmp_path / "clear.png")
    for name in ("wide.png", "clear.png"):
        grey = np.asarray(ga.load_grey(tmp_path / name))
        assert grey.max() == 255 and 0.01 < (grey < ga.INK_LEVEL).mean() < 0.5, name
    plain = np.asarray(ga.load_grey(tmp_path / "wide.png"))
    text.save(tmp_path / "plain.png")
    assert (np.asarray(ga.load_grey(tmp_path / "plain.png")) == np.asarray(text)).all()  # 8-bit: unchanged
    assert plain.shape == (60, 200)


def test_a_stored_run_is_reinterpreted_without_a_model_call(tmp_path):
    reading, ga_folder = _table_case(tmp_path, ga_name="S-3_GA.png", table_name="S-3_table.png")
    case = tmp_path / "run" / "S-3"
    case.mkdir(parents=True)
    (tmp_path / "request").rename(case / "request")
    (case / "provider").mkdir()
    (case / "provider" / "vision_reading.json").write_text(json.dumps(reading))
    stored = {"particulars": {"loa_m": {"value": None, "status": "unknown", "reason": "the value's box holds no ink"}},
              "counts": {"cargo_holds": {"value": 4}}, "spaces": [{"id": "x"}], "checks": [], "passes": {}}
    (case / "ga_reading.json").write_text(json.dumps(stored))
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for folder in ("ga", "table"):
        for file in (tmp_path / folder).iterdir():
            file.rename(inputs / file.name)
    assert ga.main(["reinterpret-particulars", "--run", str(tmp_path / "run"), "--inputs", str(inputs),
                    "--out", str(tmp_path / "again")]) == 0
    again = json.loads((tmp_path / "again" / "S-3" / "ga_reading.json").read_text())
    assert again["particulars"]["loa_m"]["value"] == pytest.approx(189.99)
    assert again["counts"] == stored["counts"] and again["spaces"] == stored["spaces"]
    assert again["passes"]["particulars_reinterpreted"] == {"changed": ["loa_m", "lbp_m", "breadth_m", "depth_m",
                                                                        "draft_m", "scantling_draft_m",
                                                                        "deadweight_t"][:1], "model_calls": 0}
