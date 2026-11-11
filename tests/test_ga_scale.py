"""Measuring a GA with its printed frame scale. All inputs are synthetic; no model is called."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from vessel_reconstruction import ga_commercial as ga
from vessel_reconstruction import ga_scale as gs
from vessel_reconstruction import source_record

# A synthetic ship: frames 0..200; 700 mm up to frame 20, 800 mm to frame 180, then 700 mm.
SPANS = [(0, 20, 700.0), (20, 180, 800.0), (180, 200, 700.0)]
PX_PER_M = 12.0
AP_PX = 300.0


def _x_m(frame: float) -> float:
    total = 0.0
    for low, high, mm in SPANS:
        total += (min(max(frame, low), high) - low) * mm / 1000.0
    if frame < 0:
        total += frame * SPANS[0][2] / 1000.0
    if frame > 200:
        total += (frame - 200) * SPANS[-1][2] / 1000.0
    return total


def _px(frame: float) -> float:
    return AP_PX + PX_PER_M * _x_m(frame)


def _ticks(step=10):
    return [(frame, _px(frame)) for frame in range(0, 201, step)]


def _table():
    labels = [(700.0, _px(8)), (800.0, _px(100)), (700.0, _px(192))]
    table, reason = gs.spacing_table(_ticks(), labels, [_px(20), _px(180)])
    assert table is not None, reason
    return table


@pytest.mark.parametrize("label,expected", [
    ("35", ("frame", 35)), ("-5", ("frame", -5)), ("A.P.", ("ap", None)), ("AP", ("ap", None)),
    ("F.P.", ("fp", None)), ("FR.120", ("frame", 120)), ("B.L.", None), ("25200", None)])
def test_scale_marks_are_frame_numbers_or_perpendiculars(label, expected):
    assert gs.parse_tick(label) == expected


@pytest.mark.parametrize("printed,expected", [
    ("800 MM", 800.0), ("700mm", 700.0), ("FR. SP. = 910 MM", 910.0), ("0.80 M", 800.0),
    ("F.S. 0.70", 700.0), ("F.S. 3.64", 3640.0), ("FRAME SPACE 600mm", 600.0), ("FR. SP. 800", 800.0),
    ("FS ~720", 720.0), ("3,200 mm", 3200.0), ("0,80 M", 800.0),
    ("25200", None), ("12 mm", None), ("frame space", None), ("52", None)])
def test_a_frame_spacing_is_parsed_only_in_its_range(printed, expected):
    assert gs.parse_spacing_mm(printed) == expected


def test_the_frame_table_follows_the_printed_spacings_and_changes():
    table = _table()
    assert [(s["from_frame"], s["to_frame"], s["spacing_mm"]) for s in table.spans] == [
        (0, 20, 700.0), (20, 180, 800.0), (180, 200, 700.0)]
    for frame in (-4, 0, 7.5, 20, 99, 180, 195, 204):
        assert table.x_m(frame) == pytest.approx(_x_m(frame))
        assert table.frame_at(table.x_m(frame)) == pytest.approx(frame)


def test_a_drawing_with_the_bow_to_the_left_gives_the_same_table():
    mirror = lambda px: 5000.0 - px
    ticks = [(frame, mirror(px)) for frame, px in _ticks()]
    labels = [(700.0, mirror(_px(8))), (800.0, mirror(_px(100))), (700.0, mirror(_px(192)))]
    table, _ = gs.spacing_table(ticks, labels, [mirror(_px(20)), mirror(_px(180))])
    assert [(s["from_frame"], s["to_frame"], s["spacing_mm"]) for s in table.spans] == [
        (0, 20, 700.0), (20, 180, 800.0), (180, 200, 700.0)]
    axis, _ = gs.fit_axis(ticks, table)
    assert axis.px_per_m == pytest.approx(-PX_PER_M)


def test_one_spacing_needs_no_change_and_no_spacing_is_an_abstention():
    ticks = [(frame, 100.0 + 8.0 * frame) for frame in range(0, 101, 10)]
    table, _ = gs.spacing_table(ticks, [(800.0, 500.0)], [])
    assert len(table.spans) == 1 and table.x_m(50) == pytest.approx(40.0)
    assert gs.spacing_table(ticks, [], [])[0] is None
    # Two spacings with no change drawn between them, and a range with numbers but no spacing.
    assert gs.spacing_table(ticks, [(800.0, 200.0), (700.0, 700.0)], [])[0] is None
    assert gs.spacing_table(ticks, [(800.0, 200.0)], [500.0])[0] is None
    # One frame number is no scale.
    assert gs.spacing_table(ticks[:1], [(800.0, 500.0)], [])[0] is None


def test_the_fit_leaves_out_a_misread_number_and_refuses_numbers_that_do_not_fit():
    table = _table()
    ticks = _ticks()
    ticks[7] = (ticks[7][0], ticks[7][1] + 90.0)  # a number pointed in the wrong place
    axis, _ = gs.fit_axis(ticks, table)
    assert axis.px_per_m == pytest.approx(PX_PER_M, rel=1e-3) and axis.offset == pytest.approx(AP_PX, abs=1.0)
    assert axis.ticks_used == len(ticks) - 1
    assert gs.fit_axis(ticks[:3], table)[0] is None
    scattered = [(frame, px + (37.0 if index % 2 else -37.0)) for index, (frame, px) in enumerate(_ticks())]
    assert gs.fit_axis(scattered, table)[0] is None


# ------------------------------------------------------------------ a whole reading

SHEET = (3000, 1600)
BASE_Y, DECK_Y = 500.0, 320.0        # depth 15 m at 12 px/m
CENTRE_Y, HALF_BREADTH_PX = 1100.0, 180.0   # breadth 30 m
FP_FRAME = 190


def _result(tmp_path: Path) -> dict:
    image = Image.new("L", SHEET, 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle([_px(-6), DECK_Y, _px(198), BASE_Y], outline=0, width=3)
    draw.rectangle([_px(-6), CENTRE_Y - HALF_BREADTH_PX, _px(198), CENTRE_Y + HALF_BREADTH_PX], outline=0, width=3)
    image.save(tmp_path / "S-1_GA.png")
    result = {"schema": ga.SCHEMA, "engineering_approved": False, "checks": [], "particulars": {},
              "sources": {"ga": {"file": "S-1_GA.png", "size_px": list(SHEET)}},
              "views": [{"view_id": "v1", "kind": "profile", "title": "", "sheet": "S-1_GA.png",
                         "box_px": [150.0, 250.0, 2900.0, 520.0]},
                        {"view_id": "v2", "kind": "tank_top_plan", "title": "TANK TOP", "sheet": "S-1_GA.png",
                         "box_px": [150.0, 900.0, 2900.0, 1300.0]}],
              "spaces": []}

    def space(space_id, kind, label, number, view, box):
        region = source_record.region("S-1_GA.png", view="profile" if view == "v1" else "plan", box_px=box,
                                      page_px=list(SHEET))
        result["spaces"].append({"id": space_id, "kind": kind, "label": label, "number": number, "status": "read",
                                 "view_id": view, "found_by": "coarse", "source_record": source_record.read([region])})

    space("cargo_hold-001", "cargo_hold", "NO.2 CARGO HOLD", "2", "v1", [1200, 400, 1400, 420])
    space("cargo_hold-002", "cargo_hold", "NO.2 CARGO HOLD", "2", "v2", [1200, 1090, 1400, 1110])
    space("ballast_tank-003", "ballast_tank", "NO.2 W.B.T. (P&S)", "2", "v1", [1200, 480, 1400, 495])
    space("ballast_tank-004", "ballast_tank", "NO.2 W.B.T. (P)", "2P", "v2", [1200, 960, 1400, 975])
    space("ballast_tank-005", "ballast_tank", "NO.2 W.B.T. (S)", "2S", "v2", [1200, 1230, 1400, 1245])
    space("other_space-006", "other_space", "STORE", None, "v2", [400, 1000, 450, 1010])
    return result


def _image_xy(request_dir: Path, image_id: str, x: float, y: float) -> tuple[float, float]:
    tile = gs._tiles(request_dir)[image_id]
    left, top, right, bottom = tile["crop_box_px"]
    return (x - left) * tile["width"] / (right - left), (y - top) * tile["height"] / (bottom - top)


def _holding(request_dir: Path, view: str, x: float, y: float) -> str:
    """The first image of ``view`` that shows sheet point (x, y)."""
    for image_id, tile in gs._tiles(request_dir).items():
        left, top, right, bottom = tile["crop_box_px"]
        if tile["view"].split(":")[1] == view and left <= x <= right and top <= y <= bottom:
            return image_id
    raise AssertionError((view, x, y))


def _scale_reply(request_dir: Path, *, fp=True, spacings=True) -> dict:
    def mark(view, x, y, **more):
        image_id = _holding(request_dir, view, x, y)
        ix, iy = _image_xy(request_dir, image_id, x, y)
        return {"image_id": image_id, "x": ix, "y": iy, **more}

    ticks = [mark("v1", _px(f), BASE_Y + 15, label=str(f)) for f in range(0, 191, 10)]
    ticks += [mark("v2", _px(f), CENTRE_Y, label=str(f)) for f in range(10, 181, 10)]
    ticks.append(mark("v1", _px(0), BASE_Y + 30, label="A.P."))
    if fp:
        ticks.append(mark("v1", _px(FP_FRAME), BASE_Y + 30, label="F.P."))
    labels = [mark("v1", _px(f), BASE_Y + 45, printed=text)
              for f, text in ((8, "700 MM"), (100, "800 MM"), (190, "700 MM"))] if spacings else []
    cuts = [mark("v1", _px(f), BASE_Y + 45) for f in (20, 180)] if spacings else []
    points = [mark("v1", _px(-6), 400, name="hull_aft_end"), mark("v1", _px(198), 400, name="hull_fore_end"),
              mark("v1", _px(100), BASE_Y, name="base_line"), mark("v1", _px(100), DECK_Y, name="upper_deck_at_side"),
              mark("v2", _px(100), CENTRE_Y, name="centre_line"),
              mark("v2", _px(100), CENTRE_Y - HALF_BREADTH_PX, name="shell_side_a"),
              mark("v2", _px(100), CENTRE_Y + HALF_BREADTH_PX, name="shell_side_b")]
    return {"reply": {"ga_scale": {"ticks": ticks, "spacing_labels": labels, "spacing_boundaries": cuts,
                                   "points": points, "extents": [], "note": "", "refused": 0}}}


def _extent_reply(request_dir: Path) -> dict:
    def box(space_id, view, left, top, right, bottom, basis="outline"):
        x0, y0 = _image_xy(request_dir, view, left, top)
        x1, y1 = _image_xy(request_dir, view, right, bottom)
        return {"space_id": space_id, "image_id": view, "box": [x0, y0, x1, y1], "basis": basis}

    aft, fore = _px(80), _px(120)
    return {"reply": {"ga_scale": {"ticks": [], "spacing_labels": [], "spacing_boundaries": [], "points": [], "note": "",
                                   "extents": [
        box("cargo_hold-001", "v1", aft, DECK_Y, fore, BASE_Y - 24),
        box("cargo_hold-002", "v2", aft + 3, CENTRE_Y - 150, fore - 2, CENTRE_Y + 150),
        box("ballast_tank-003", "v1", aft, BASE_Y - 24, fore, BASE_Y),
        box("ballast_tank-004", "v2", aft, CENTRE_Y - HALF_BREADTH_PX, fore, CENTRE_Y),
        box("ballast_tank-005", "v2", aft, CENTRE_Y, fore, CENTRE_Y + HALF_BREADTH_PX),
        box("other_space-006", "v2", _px(10), CENTRE_Y - 60, _px(16), CENTRE_Y - 20, "uncertain"),
        box("no_such_space", "v2", aft, CENTRE_Y, fore, CENTRE_Y + 10)]}}}


def _run(tmp_path, **scale_options):
    result = _result(tmp_path)
    replies = []

    def call(request_dir, provider_dir):
        is_extents = request_dir.name == "extents"
        reply = _extent_reply(request_dir) if is_extents else _scale_reply(request_dir, **scale_options)
        replies.append(reply)
        return reply

    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    return result, stats


def test_principal_dimensions_are_measured_and_kept_apart_from_printed_particulars(tmp_path):
    result, stats = _run(tmp_path)
    assert stats["requests"] == 2 and result["frames"]["status"] == "read"
    # The table reaches from the aft end to the fore end of the hull.
    assert [(s["from_frame"], s["to_frame"], s["spacing_mm"]) for s in result["frames"]["spacings"]] == [
        (-6, 20, 700.0), (20, 180, 800.0), (180, 198, 700.0)]
    measured = result["measured"]
    expected = {"lbp_m": _x_m(FP_FRAME), "loa_m": _x_m(198) - _x_m(-6), "depth_m": 15.0, "breadth_m": 30.0}
    for field, value in expected.items():
        entry = measured[field]
        assert entry["status"] == "measured_from_scale" and entry["value"] == pytest.approx(value, abs=0.15)
        assert entry["uncertainty_m"] > 0 and source_record.validate(entry["source_record"])["kind"] == "read"
    # The exam reads ``particulars``: a measured value never goes there.
    assert result["particulars"] == {}
    request = json.loads((tmp_path / "scale" / "scale" / "request.json").read_text())
    assert request["purpose"] == "ga_scale" and len(request["images"]) <= gs.MAX_IMAGES
    assert "S-1_GA" not in json.dumps(request["context"])


def test_space_extents_come_in_frames_and_metres_with_a_status_per_axis(tmp_path):
    result, stats = _run(tmp_path)
    spaces = {s["id"]: s for s in result["spaces"]}
    hold = spaces["cargo_hold-001"]["extent"]
    assert hold["frames"] == [80, 120] and hold["x_m"] == [pytest.approx(_x_m(80)), pytest.approx(_x_m(120))]
    assert hold["z_m"] == [pytest.approx(2.0, abs=0.1), pytest.approx(15.0, abs=0.1)]
    assert hold["status"] == {"x": "measured_from_scale", "z": "measured_from_scale"}
    port = spaces["ballast_tank-004"]["extent"]
    # Bow to the right: port is up the sheet, so y is 0..15 m to port.
    assert port["side"] == "port" and port["y_m"] == [pytest.approx(0.0, abs=0.1), pytest.approx(15.0, abs=0.1)]
    assert spaces["ballast_tank-005"]["extent"]["y_m"][0] == pytest.approx(-15.0, abs=0.1)
    assert spaces["other_space-006"]["extent"]["status"] == {"x": "guessed", "y": "guessed"}
    assert stats["extents"] == {"asked": 6, "boxed": 6, "with_extent": 6, "requests": 1}
    assert any(c["code"] == "extent_of_unknown_space" for c in result["checks"])


def test_the_arrangement_input_joins_the_views_of_one_space(tmp_path):
    result, _ = _run(tmp_path)
    result["particulars"] = {"breadth_m": {"value": 30.2, "status": "read", "source_record": source_record.read(
        [source_record.region("S-1_GA.png", view="table")])}}
    data = gs.arrangement_input(result, "S-1")
    assert data["schema"] == "marinaframe.ga_reading.v1" and data["engineering_approved"] is False
    # Printed wins; the rest is measured and says so.
    assert data["particulars"]["breadth_m"]["status"] == "read" and data["particulars"]["breadth_m"]["value"] == 30.2
    assert data["particulars"]["lbp_m"]["status"] == "measured_from_scale"
    by_label = {}
    for space in data["spaces"]:
        by_label.setdefault(space["label"], []).append(space)
    holds = [s for s in data["spaces"] if s["kind"] == "cargo_hold"]
    assert len(holds) == 1 and set(holds[0]["extent"]) >= {"frames", "x_m", "y_m", "z_m"}
    assert holds[0]["extent"]["status"] == {"x": "measured_from_scale", "y": "measured_from_scale",
                                            "z": "measured_from_scale"}
    assert len(holds[0]["source_record"]["regions"]) == 2
    tanks = [s for s in data["spaces"] if s["kind"] == "ballast_tank"]
    assert sorted(t["extent"]["side"] for t in tanks) == ["port", "starboard"]
    assert all(t["extent"]["z_m"][1] == pytest.approx(2.0, abs=0.1) for t in tanks)


def test_without_a_printed_spacing_or_an_fp_mark_the_values_are_null(tmp_path):
    result, stats = _run(tmp_path, spacings=False)
    # The scale request is sent again before the ship is given up.
    assert result["frames"]["status"] == "unknown"
    assert stats["requests"] == stats["scale_attempts"] == gs.SCALE_ATTEMPTS
    assert all(v["value"] is None and v["reason"] for v in result["measured"].values())
    assert all("extent" not in s for s in result["spaces"])
    data = gs.arrangement_input(result, "S-1")
    assert data["particulars"]["lbp_m"]["value"] is None
    (tmp_path / "second").mkdir()
    result, _ = _run(tmp_path / "second", fp=False)
    assert result["measured"]["lbp_m"]["value"] is None and "F.P." in result["measured"]["lbp_m"]["reason"]
    assert result["measured"]["loa_m"]["status"] == "measured_from_scale"


def test_measured_values_that_do_not_fit_each_other_are_refused(tmp_path):
    result = _result(tmp_path)
    gs.prepare_scale(result, tmp_path / "S-1_GA.png", tmp_path / "scale")
    reading = _scale_reply(tmp_path / "scale")
    points = {p["name"]: p for p in reading["reply"]["ga_scale"]["points"] if p["image_id"].startswith("v2")}
    # Both shell sides pointed on the same side of the centreline: a breadth far too small for the length.
    points["shell_side_a"]["y"] = points["shell_side_b"]["y"] - 40
    gs.read_scale(result, reading, tmp_path / "scale")
    assert result["measured"]["breadth_m"]["value"] is None and result["measured"]["lbp_m"]["value"] is not None
    assert any(c["code"].startswith("measured_") for c in result["checks"])


def test_a_failed_request_is_an_abstention(tmp_path):
    result = _result(tmp_path)
    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale",
                          lambda request, out: {"reply": None, "stop_reason": "vision_request_failed: timeout"})
    assert stats["requests"] == gs.SCALE_ATTEMPTS and result["frames"]["status"] == "unknown"
    assert "timeout" in result["measured"]["lbp_m"]["reason"]


def test_the_exam_run_does_not_measure_by_default(tmp_path):
    """``read`` and ``batch`` send the scale requests only with --measure."""
    calls = []

    def fake_call(binary, request, out, basis, model=ga.MODEL):
        calls.append(json.loads((Path(request) / "request.json").read_text())["purpose"])
        return {"reply": None, "stop_reason": "test", "usage": {}, "receipts": []}

    image = Image.new("L", (400, 300), 255)
    ImageDraw.Draw(image).rectangle([20, 20, 380, 280], outline=0)
    image.save(tmp_path / "S-2_GA.png")
    original, ga.call_model = ga.call_model, fake_call
    try:
        result = ga.read_one(tmp_path / "S-2_GA.png", None, tmp_path / "out", tmp_path / "bin", "test")
    finally:
        ga.call_model = original
    assert calls == ["ga_reading"] and "measured" not in result


def test_a_space_listed_twice_in_one_view_is_one_space_and_shared_label_crops_are_not_asked(tmp_path):
    result = _result(tmp_path)
    twin = json.loads(json.dumps(next(s for s in result["spaces"] if s["id"] == "cargo_hold-001")))
    twin["id"], twin["found_by"] = "cargo_hold-c01-1", "fine"
    result["spaces"].append(twin)
    # Two labels read from one fine crop: their places are not known.
    for name in ("GALLEY", "MESS"):
        room = json.loads(json.dumps(next(s for s in result["spaces"] if s["id"] == "other_space-006")))
        room.update(id=f"other_space-c02-{name}", label=name)
        room["source_record"]["regions"][0]["box_px"] = [500.0, 1000.0, 600.0, 1050.0]
        result["spaces"].append(room)
    gs.prepare_extents(result, tmp_path / "S-1_GA.png", tmp_path / "extents")
    asked = json.loads((tmp_path / "extents" / "request.json").read_text())["context"]["spaces"]
    assert not any(s["label"] in ("GALLEY", "MESS") for s in asked)
    for space in result["spaces"]:
        if space["kind"] == "cargo_hold" and space["view_id"] == "v1":
            space["extent"] = {"frames": [80, 120], "x_m": [62.0, 94.0], "z_m": [2.0, 15.0], "view_id": "v1",
                               "status": {"x": "measured_from_scale", "z": "measured_from_scale"},
                               "basis": "outline"}
    assert len([s for s in gs.merged_spaces(result) if s["kind"] == "cargo_hold" and "extent" in s]) == 1


def _depth_run(tmp_path, deck_shift_px=0.0, deck_frame=100, tier=True, tall_ballast=False, ballast_at_deck=False):
    """A run with three cargo holds; the deck point is moved by ``deck_shift_px`` (up is negative)
    or pointed at ``deck_frame``."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    result = _result(tmp_path)
    for index, aft in enumerate((40, 120)):
        hold = json.loads(json.dumps(result["spaces"][0]))
        hold.update(id=f"cargo_hold-10{index}", label=f"NO.{index + 3} CARGO HOLD", number=str(index + 3))
        hold["source_record"]["regions"][0]["box_px"] = [_px(aft) + 100.0, 400.0, _px(aft) + 300.0, 420.0]
        result["spaces"].append(hold)
    if tier:
        deck = json.loads(json.dumps(result["spaces"][0]))
        deck.update(id="accommodation_deck-200", kind="accommodation_deck", label="A DECK", number=None, view_id=None)
        deck["source_record"]["regions"][0]["box_px"] = [100.0, 1400.0, 200.0, 1420.0]
        result["spaces"].append(deck)
    replies = []

    def call(request_dir, provider_dir):
        if not replies:
            reply = _scale_reply(request_dir)
            for point in reply["reply"]["ga_scale"]["points"]:
                if point["name"] == "upper_deck_at_side":
                    image_id = _holding(request_dir, "v1", _px(deck_frame), DECK_Y + deck_shift_px)
                    point["image_id"] = image_id
                    point["x"], point["y"] = _image_xy(request_dir, image_id, _px(deck_frame), DECK_Y + deck_shift_px)
        else:
            reply = _extent_reply(request_dir)
            extents = reply["reply"]["ga_scale"]["extents"]
            if tall_ballast:  # the profile ballast tank boxed up past the deck
                tank = next(e for e in extents if e["space_id"] == "ballast_tank-003")
                tank["box"][1] = _image_xy(request_dir, "v1", _px(80), DECK_Y - 60)[1]
            if ballast_at_deck:  # the profile ballast tank ends at the pointed deck line
                tank = next(e for e in extents if e["space_id"] == "ballast_tank-003")
                tank["box"][1] = _image_xy(request_dir, "v1", _px(80), DECK_Y + deck_shift_px)[1]
            first = extents[0]
            width = first["box"][2] - first["box"][0]
            for index, shift in enumerate((-1.0, 1.0)):
                twin = dict(first, space_id=f"cargo_hold-10{index}")
                twin["box"] = [first["box"][0] + shift * width, first["box"][1], first["box"][2] + shift * width,
                               first["box"][3]]
                extents.append(twin)
            if tier:  # the lowest deckhouse tier stands on the upper deck
                x0, y0 = _image_xy(request_dir, "v1", _px(10), DECK_Y - 36)
                x1, y1 = _image_xy(request_dir, "v1", _px(30), DECK_Y)
                extents.append({"space_id": "accommodation_deck-200", "image_id": "v1", "box": [x0, y0, x1, y1],
                                "basis": "uncertain"})
        replies.append(reply)
        return reply

    result["passes_scale"] = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    return result


def test_the_depth_is_taken_amidships_and_checked_against_the_spaces_below_the_deck(tmp_path):
    codes = lambda result: {c["code"] for c in result["checks"]}
    agreed = _depth_run(tmp_path / "a")
    assert agreed["measured"]["depth_m"]["value"] == pytest.approx(15.0, abs=0.15)
    assert "agrees" in agreed["measured"]["depth_m"]["cross_check"]["result"]
    # A deck line above the tops of the boxed spaces (topside tanks above the holds, or another
    # deck): kept, and marked as not confirmed.
    above = _depth_run(tmp_path / "b", deck_shift_px=-60.0)
    assert above["measured"]["depth_m"]["value"] == pytest.approx(20.0, abs=0.2)
    assert "depth_not_confirmed_by_space_tops" in codes(above)
    # A deck line a rail height above holds that agree: the deck at the centreline or a rail.
    # The moulded depth is to the deck at side, where the holds end.
    rail = _depth_run(tmp_path / "r", deck_shift_px=-14.0)
    depth = rail["measured"]["depth_m"]
    assert depth["value"] == pytest.approx(15.0, abs=0.15) and "depth_taken_from_cargo_space_tops" in codes(rail)
    # A substituted value is an estimate: its own status, with the pointed value and the reason kept.
    assert depth["status"] == "derived_from_space_tops" and depth["pointed_depth_m"] == pytest.approx(16.2, abs=0.2)
    assert "rail" in depth["reason"]
    assert rail["passes_scale"]["derived"] == ["depth_m"] and "depth_m" not in rail["passes_scale"]["measured"]
    assert gs.arrangement_input(rail, "S-1")["particulars"]["depth_m"]["status"] == "derived_from_space_tops"
    # A deck line below the top of a hold: the line or the boxes are wrong, so it is never a
    # measured depth. The holds agree on one top, which becomes the (derived) depth.
    below = _depth_run(tmp_path / "c", deck_shift_px=60.0)
    depth = below["measured"]["depth_m"]
    assert "depth_below_a_space_top" in codes(below)
    assert depth["status"] == "derived_from_space_tops" and depth["value"] == pytest.approx(15.0, abs=0.15)
    assert depth["pointed_depth_m"] == pytest.approx(10.0, abs=0.2) and "below the top" in depth["reason"]
    # Pointed near the stern (a poop deck): not used; the holds and the lowest tier give the depth.
    aft = _depth_run(tmp_path / "d", deck_shift_px=-36.0, deck_frame=13)
    assert "deck_point_not_amidships" in codes(aft)
    assert aft["measured"]["depth_m"]["value"] == pytest.approx(15.0, abs=0.15)
    assert aft["measured"]["depth_m"]["status"] == "derived_from_space_tops"
    assert aft["measured"]["depth_m"]["pointed_depth_m"] is None
    # The same without anything else that ends at the hold tops: null.
    alone = _depth_run(tmp_path / "e", deck_shift_px=-36.0, deck_frame=13, tier=False)
    assert alone["measured"]["depth_m"]["value"] is None


def test_many_spaces_go_out_in_short_requests_holds_and_tanks_first(tmp_path):
    """Asked for 71 spaces at once the model boxed 20 (round u1): short lists, most useful first."""
    result = _result(tmp_path)
    template = next(s for s in result["spaces"] if s["id"] == "other_space-006")
    for index in range(50):
        room = json.loads(json.dumps(template))
        room.update(id=f"other_space-r{index:02d}", label=f"ROOM {index}")
        room["source_record"]["regions"][0]["box_px"] = [100.0 + 10 * index, 1000.0, 105.0 + 10 * index, 1010.0]
        result["spaces"].append(room)
    directories = gs.prepare_extents(result, tmp_path / "S-1_GA.png", tmp_path / "extents")
    contexts = [json.loads((d / "request.json").read_text())["context"] for d in directories]
    assert [d.name for d in directories] == ["extents", "extents-2", "extents-3"]
    assert all(len(c["spaces"]) <= gs.EXTENT_SPACES_PER_REQUEST for c in contexts)
    assert contexts[0]["want"] == ["extents", "points"] and contexts[1]["want"] == ["extents"]
    first = [s["kind"] for s in contexts[0]["spaces"]]
    assert first[0] == "cargo_hold" and first.index("ballast_tank") < first.index("other_space")


def test_a_scale_reply_without_hull_ends_is_measured_without_them(tmp_path):
    """No hull end pointed (development round u1: a crash): the table keeps the drawn scale ends."""
    result = _result(tmp_path)

    def call(request_dir, provider_dir):
        if request_dir.name == "extents":
            return _extent_reply(request_dir)
        reply = _scale_reply(request_dir)
        points = reply["reply"]["ga_scale"]["points"]
        points[:] = [p for p in points if p["name"] not in ("hull_aft_end", "hull_fore_end")]
        return reply

    gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    assert result["frames"]["status"] == "read"
    assert result["measured"]["loa_m"]["value"] is None and result["measured"]["lbp_m"]["value"] is not None


def test_places_the_scale_request_left_out_are_asked_for_and_used(tmp_path):
    """No F.P. in the scale reply: the first extents request names it and its reply gives it
    (development round u3: an LBP lost to a missing F.P. mark)."""
    result = _result(tmp_path)

    def call(request_dir, provider_dir):
        if request_dir.name.startswith("extents"):
            reply = _extent_reply(request_dir)
            if request_dir.name == "extents":
                x, y = _image_xy(request_dir, "v1", _px(FP_FRAME), BASE_Y + 30)
                reply["reply"]["ga_scale"]["ticks"] = [{"image_id": "v1", "label": "F.P.", "x": x, "y": y}]
            return reply
        return _scale_reply(request_dir, fp=False)

    gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    context = json.loads((tmp_path / "scale" / "extents" / "request.json").read_text())["context"]
    assert context["missing"]["places"] == ["F.P."]
    assert result["measured"]["lbp_m"]["value"] == pytest.approx(_x_m(FP_FRAME), abs=0.15)


def test_a_tank_boxed_above_the_deck_that_the_holds_confirm_is_the_wrong_box(tmp_path):
    """The holds agree on one top and the pointed deck line lies there: a ballast tank boxed
    above it is a wrong box (development round u3), not a wrong deck line."""
    result = _depth_run(tmp_path, tall_ballast=True)
    depth = result["measured"]["depth_m"]
    assert depth["status"] == "measured_from_scale" and depth["value"] == pytest.approx(15.0, abs=0.15)
    assert "agrees with the tops of the cargo spaces" in depth["cross_check"]["result"]
    tank = next(s for s in result["spaces"] if s["id"] == "ballast_tank-003")
    assert tank["extent"]["status"]["z"] == "guessed" and "z_note" in tank["extent"]
    assert "extent_above_the_deck" in {c["code"] for c in result["checks"]}
    # Without holds that confirm the deck line, a box above it still refuses the line.
    below = _depth_run(tmp_path / "b", deck_shift_px=60.0, tall_ballast=True)
    assert below["measured"]["depth_m"]["status"] != "measured_from_scale"
    # Holds boxed above a deck line that a ballast tank ends at (cargo boxes up to the rail,
    # round u4): the boxes disagree, so the hold tops do not replace the line; no depth.
    mixed = _depth_run(tmp_path / "m", deck_shift_px=60.0, ballast_at_deck=True)
    depth = mixed["measured"]["depth_m"]
    assert depth["value"] is None and "boxes disagree" in depth["reason"]


def test_a_depth_that_no_space_can_check_is_not_given(tmp_path):
    result = _result(tmp_path)

    def call(request_dir, provider_dir):
        if request_dir.name == "extents":  # the extents reply boxes nothing
            return {"reply": {"ga_scale": {"ticks": [], "spacing_labels": [], "spacing_boundaries": [],
                                           "points": [], "extents": [], "note": "", "refused": 0}}}
        return _scale_reply(request_dir)

    gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    depth = result["measured"]["depth_m"]
    assert depth["value"] is None and depth["status"] == "unknown"
    assert depth["pointed_depth_m"] == pytest.approx(15.0, abs=0.15)
    assert "depth_not_checked" in {c["code"] for c in result["checks"]}
    assert result["measured"]["lbp_m"]["status"] == "measured_from_scale"  # the other values stay


def test_label_places_follow_the_image_actually_sent(tmp_path, monkeypatch):
    """Images can be sent smaller than planned (request size); a label place sent to the model
    must be in the pixels of the image it gets (development round 3: places 11 % off)."""
    result = _result(tmp_path)
    monkeypatch.setattr(ga, "MAX_TOTAL_IMAGE_BYTES", 40_000)  # forces smaller images
    gs.prepare_extents(result, tmp_path / "S-1_GA.png", tmp_path / "extents")
    request = json.loads((tmp_path / "extents" / "request.json").read_text())
    images = {image["image_id"]: image for image in request["images"]}
    checked = 0
    for asked in request["context"]["spaces"]:
        if asked["at"] is None:
            continue
        image = images[asked["image_id"]]
        left, top, right, bottom = image["crop_box_px"]
        region = next(s for s in result["spaces"] if s["id"] == asked["space_id"])["source_record"]["regions"][0]
        centre = ((region["box_px"][0] + region["box_px"][2]) / 2, (region["box_px"][1] + region["box_px"][3]) / 2)
        assert asked["at"][0] == pytest.approx((centre[0] - left) * image["width"] / (right - left), abs=1)
        assert asked["at"][1] == pytest.approx((centre[1] - top) * image["height"] / (bottom - top), abs=1)
        checked += 1
    assert checked >= 3


def test_web_frame_spacings_with_several_changes_between_two_numbers():
    """A tanker scale: numbers every 5 frames, two changes of spacing between two of them, and
    one number misread in a way that keeps the order."""
    spans = [(-5, 11, 700.0), (11, 40, 900.0), (40, 42, 2940.0), (42, 44, 3530.0), (44, 95, 3640.0), (95, 115, 700.0)]

    def x_m(frame):
        return sum((min(max(frame, low), high) - low) * mm / 1000.0 for low, high, mm in spans)

    px = lambda frame: 100.0 + 9.0 * x_m(frame)
    ticks = [(frame, px(frame)) for frame in range(-5, 116, 5)]
    ticks = [(43, place) if frame == 45 else (frame, place) for frame, place in ticks]  # "45" read as "43"
    labels = [(mm, px((low + high) / 2)) for low, high, mm in spans]
    table, reason = gs.spacing_table(ticks, labels, [px(high) + 1.5 for _, high, _ in spans[:-1]])
    assert table is not None, reason
    assert [(s["from_frame"], s["to_frame"], s["spacing_mm"]) for s in table.spans] == spans
    axis, _ = gs.fit_axis(ticks, table)
    assert axis.px_per_m == pytest.approx(9.0, rel=2e-3) and axis.ticks_used == len(ticks) - 1


def test_the_text_of_a_one_frame_range_printed_beside_it_belongs_to_it():
    """A web-frame range of one frame is too short for its text, which is printed in the next
    range (development round u2: the scale was refused three times)."""
    def x_m(frame):
        return 0.7 * min(frame, 30) + 0.9 * min(max(frame - 30, 0), 1) + 0.7 * max(frame - 31, 0)

    def px(frame):
        return 300.0 + 12.0 * x_m(frame)

    ticks = [(frame, px(frame)) for frame in range(0, 61, 5)]
    labels = [(700.0, px(15)), (900.0, px(33)), (700.0, px(50))]
    table, reason = gs.spacing_table(ticks, labels, [px(30), px(31)])
    assert table is not None, reason
    assert [(s["from_frame"], s["to_frame"], s["spacing_mm"]) for s in table.spans] == [
        (0, 30, 700.0), (30, 31, 900.0), (31, 60, 700.0)]
    # Without the short range drawn, the two texts in one range are still refused.
    table, reason = gs.spacing_table(ticks, labels, [px(30)])
    assert table is None


def test_a_number_out_of_order_is_left_out():
    ticks = _ticks()
    ticks[5] = (155, ticks[5][1])  # "50" read as "155"
    kept = gs.consistent_ticks(ticks)
    assert len(kept) == len(ticks) - 1 and (155, ticks[5][1]) not in kept


def test_places_that_the_scale_request_left_out_come_from_the_whole_view_images(tmp_path):
    """A reply sometimes does not look at the plan images; the extents request asks again."""
    result = _result(tmp_path)
    replies = []

    def call(request_dir, provider_dir):
        if not replies:
            reply = _scale_reply(request_dir)
            marks = reply["reply"]["ga_scale"]
            marks["points"] = [p for p in marks["points"] if p["image_id"].startswith("v1")]
        else:
            assert json.loads((request_dir / "request.json").read_text())["context"]["want"] == ["extents", "points"]
            reply = _extent_reply(request_dir)
            for name, y in (("centre_line", CENTRE_Y), ("shell_side_a", CENTRE_Y - HALF_BREADTH_PX),
                            ("shell_side_b", CENTRE_Y + HALF_BREADTH_PX), ("base_line", BASE_Y + 40)):
                view = "v1" if name == "base_line" else "v2"
                x, iy = _image_xy(request_dir, view, _px(100), y)
                reply["reply"]["ga_scale"]["points"].append({"image_id": view, "name": name, "x": x, "y": iy})
        replies.append(reply)
        return reply

    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    assert stats["extents"]["points_added"] == 3    # the base line was pointed before and is kept
    assert result["measured"]["breadth_m"]["value"] == pytest.approx(30.0, abs=0.3)
    assert result["measured"]["depth_m"]["value"] == pytest.approx(15.0, abs=0.15)
    port = next(s for s in result["spaces"] if s["id"] == "ballast_tank-004")["extent"]
    assert port["y_m"] == [pytest.approx(0.0, abs=0.2), pytest.approx(15.0, abs=0.2)]


def test_a_second_scale_request_can_establish_the_scale(tmp_path):
    result = _result(tmp_path)
    replies = []

    def call(request_dir, provider_dir):
        if len(replies) == 0:
            reply = _scale_reply(request_dir, spacings=False)   # the spacing texts were not read
        elif len(replies) == 1:
            reply = _scale_reply(request_dir)
        else:
            reply = _extent_reply(request_dir)
        replies.append(reply)
        return reply

    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    assert stats["requests"] == 3 and stats["scale_attempts"] == 2 and result["frames"]["status"] == "read"
    assert result["measured"]["lbp_m"]["value"] == pytest.approx(_x_m(FP_FRAME), abs=0.15)
    # The second request says why the first reading was refused; the first says nothing of the kind.
    first = json.loads((tmp_path / "scale" / "scale" / "request.json").read_text())["context"]
    second = json.loads((tmp_path / "scale" / "scale-2" / "request.json").read_text())["context"]
    assert "previous_attempt" not in first
    assert "spacing" in second["previous_attempt"] and "refused" in second["previous_attempt"]


def test_the_frame_numbers_check_the_printed_spacing_of_a_range():
    """A printed value read wrongly ("600" for "800"), or a change of spacing that was not marked."""
    cuts = [_px(20), _px(180)]
    good = [(700.0, _px(8)), (800.0, _px(100)), (700.0, _px(192))]
    assert gs.spacing_table(_ticks(), good, cuts)[0] is not None
    misread = [(700.0, _px(8)), (600.0, _px(100)), (700.0, _px(192))]
    table, reason = gs.spacing_table(_ticks(step=5), misread, cuts)
    # The middle range has the most numbers and gives the scale; then the end ranges (five
    # numbers each) do not fit their printed 700 mm.
    assert table is None and "do not fit" in reason
    # With too few numbers in the end ranges, the fit of the whole scale refuses the table.
    table, _ = gs.spacing_table(_ticks(), misread, cuts)
    assert gs.fit_axis(_ticks(), table)[0] is None
    # The same place read as 600 and as 800 in two requests: the frame numbers decide.
    both = good + [(600.0, _px(101))]
    table, _ = gs.spacing_table(_ticks(), both, cuts)
    assert [s["spacing_mm"] for s in table.spans] == [700.0, 800.0, 700.0]
    # A change of spacing that no request marked: two printed values at two places in one range.
    # The frame numbers do not choose one of them (a short range would be left out without notice).
    table, reason = gs.spacing_table(_ticks(), good, cuts[:1])
    assert table is None and "no change drawn" in reason


def test_a_run_of_frame_numbers_off_the_scale_refuses_the_table():
    table = _table()
    ticks = _ticks()
    shifted = [(frame, px + (40.0 if 60 <= frame <= 90 else 0.0)) for frame, px in ticks]  # four neighbours
    assert gs.fit_axis(shifted, table)[0] is None
    two = [(frame, px + (40.0 if frame in (60, 130) else 0.0)) for frame, px in ticks]      # two misreadings
    assert gs.fit_axis(two, table)[0] is not None


def test_the_marks_of_two_scale_requests_are_read_together(tmp_path):
    """One reply leaves out a change of spacing; the next has it (and leaves out another)."""
    result = _result(tmp_path)
    replies = []

    def call(request_dir, provider_dir):
        if request_dir.name == "extents":
            reply = _extent_reply(request_dir)
        else:
            reply = _scale_reply(request_dir)
            marks = reply["reply"]["ga_scale"]
            keep = 0 if not replies else 1
            marks["spacing_boundaries"] = marks["spacing_boundaries"][keep:keep + 1]
        replies.append(reply)
        return reply

    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    assert stats["scale_attempts"] == 2 and result["frames"]["status"] == "read"
    assert [s["spacing_mm"] for s in result["frames"]["spacings"]] == [700.0, 800.0, 700.0]
    assert result["measured"]["lbp_m"]["value"] == pytest.approx(_x_m(FP_FRAME), abs=0.2)
