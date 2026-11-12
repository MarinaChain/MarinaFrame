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
    # The plan box of the hold ends at the port tank drawn over half the breadth: one-sided, so
    # its y is centred and guessed (lane W, round u6r7).
    assert holds[0]["extent"]["status"] == {"x": "measured_from_scale", "y": "guessed", "z": "measured_from_scale"}
    assert holds[0]["extent"]["y_m"] == [-6.25, 6.25] and "off the centreline" in holds[0]["extent"]["y_note"]
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


def test_a_space_listed_twice_in_one_view_is_one_space_and_shared_label_crops_are_asked_near(tmp_path):
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
    directories = gs.prepare_extents(result, tmp_path / "S-1_GA.png", tmp_path / "extents")
    asked = [s for d in directories for s in json.loads((d / "request.json").read_text())["context"]["spaces"]]
    # Asked with the crop as "near" and no label place (round u8: such spaces were never asked).
    shared = [s for s in asked if s["label"] in ("GALLEY", "MESS")]
    assert len(shared) == 2 and all(s["at"] is None and len(s["near"]) == 4 for s in shared)
    assert asked.index(shared[0]) > asked.index(next(s for s in asked if s["label"] == "STORE"))


def test_labels_with_a_known_place_and_labels_near_a_crop_go_in_separate_requests(tmp_path):
    """Round u9n: mixed in one request, the model marked most boxes uncertain."""
    result = _result(tmp_path)
    for index in range(gs.EXTENT_SPACES_PER_REQUEST + 3):
        room = json.loads(json.dumps(next(s for s in result["spaces"] if s["id"] == "other_space-006")))
        room.update(id=f"other_space-c02-{index}", label=f"ROOM {index}")
        room["source_record"]["regions"][0]["box_px"] = [500.0, 1000.0, 600.0, 1050.0]
        result["spaces"].append(room)
    directories = gs.prepare_extents(result, tmp_path / "S-1_GA.png", tmp_path / "extents")
    kinds = [{"near" in s for s in json.loads((d / "request.json").read_text())["context"]["spaces"]}
             for d in directories]
    assert kinds == [{False}, {True}, {True}]
    for space in result["spaces"]:
        if space["kind"] == "cargo_hold" and space["view_id"] == "v1":
            space["extent"] = {"frames": [80, 120], "x_m": [62.0, 94.0], "z_m": [2.0, 15.0], "view_id": "v1",
                               "status": {"x": "measured_from_scale", "z": "measured_from_scale"},
                               "basis": "outline"}
    assert len([s for s in gs.merged_spaces(result) if s["kind"] == "cargo_hold" and "extent" in s]) == 1


def _depth_run(tmp_path, deck_shift_px=0.0, deck_frame=100, tier=True, tall_ballast=False, ballast_at_deck=False,
               uncertain_below=False):
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
            if uncertain_below:  # the model is not sure of any boundary below the deck
                for extent in extents:
                    if extent["image_id"] == "v1":
                        extent["basis"] = "uncertain"
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


def test_a_pair_boxed_on_one_side_is_two_tanks_in_the_arrangement_input():
    """A "(P&S)" wing tank boxed on its label's side: a measured tank and its guessed mirror,
    so the cargo tank between them is not read as full breadth."""
    entry = {"id": "ballast_tank-007", "kind": "ballast_tank", "label": "NO.3 W.B.T. (P&S)", "number": "3",
             "status": "read", "source_record": {"kind": "unknown", "reason": "test"},
             "extent": {"frames": [40, 60], "x_m": [30.0, 45.0], "y_m": [9.5, 16.0], "side": "both",
                        "status": {"x": "measured_from_scale", "y": "measured_from_scale"}}}
    port, starboard = gs._split_pair(entry)
    assert (port["extent"]["side"], port["extent"]["y_m"], port["extent"]["status"]["y"]) == (
        "port", [9.5, 16.0], "measured_from_scale")
    assert (starboard["extent"]["side"], starboard["extent"]["y_m"], starboard["extent"]["status"]["y"]) == (
        "starboard", [-16.0, -9.5], "guessed")
    assert port["id"] != starboard["id"] and entry["extent"]["side"] == "both"  # the reading is unchanged
    across = json.loads(json.dumps(entry))
    across["extent"]["y_m"] = [-12.0, 12.0]  # a pair boxed across the centreline: split there
    assert [(s["extent"]["side"], s["extent"]["y_m"]) for s in gs._split_pair(across)] == [
        ("port", [0.0, 12.0]), ("starboard", [-12.0, 0.0])]
    profile_only = json.loads(json.dumps(entry))
    del profile_only["extent"]["y_m"]  # no plan breadth: one tank each side (lane W, round u6)
    assert [s["extent"]["side"] for s in gs._split_pair(profile_only)] == ["port", "starboard"]
    unlabelled = json.loads(json.dumps(across))
    unlabelled["label"] = "ENGINE ROOM"  # a space across the centreline without a pair label stays one
    assert gs._split_pair(unlabelled) == [unlabelled]


def test_the_arrangement_gate_finds_spaces_without_volume_fragments_and_cargo_losses():
    def space(space_id, kind, label, x, y, z):
        return {"id": space_id, "kind": kind, "label": label, "number": None, "status": "read",
                "source_record": {"kind": "unknown", "reason": "test"},
                "extent": {"x_m": list(x), "y_m": list(y), "z_m": list(z), "side": "both", "status": {}}}
    particulars = {"breadth_m": {"value": 20.0}, "depth_m": {"value": 10.0}}
    good = {"particulars": particulars, "spaces": [
        space("h", "cargo_hold", "NO.1 CARGO HOLD", (10, 30), (-10, 10), (1, 10)),
        space("t", "ballast_tank", "NO.1 W.B.T.", (10, 30), (-10, 10), (0, 1))]}
    assert gs.arrangement_gate(good)["passed"]
    swallowed = {"particulars": particulars, "spaces": [
        space("h", "cargo_hold", "NO.1 CARGO HOLD", (10, 30), (-10, 10), (0, 10)),
        space("t", "ballast_tank", "NO.1 W.B.T.", (10, 30), (-10, 10), (0, 9))]}
    report = gs.arrangement_gate(swallowed)
    assert not report["passed"] and report["max_cargo_loss"] > 0.85
    covered = {"particulars": particulars, "spaces": [
        space("p", "other_tank", "F.W.T. (P)", (0, 5), (0, 2), (0, 5)),
        space("s", "other_tank", "F.W.T. (S)", (0, 5), (-2, 0), (0, 5)),
        space("b", "other_tank", "NO. 4", (0, 5), (-2, 2), (0, 5))]}
    report = gs.arrangement_gate(covered)
    assert report["fragments"] == ["NO. 4"] and report["no_volume"] == ["b"] and not report["passed"]


def test_one_compartment_with_two_labels_is_one_space_in_the_arrangement_input():
    entry = lambda i, kind, label, number: {
        "id": i, "kind": kind, "label": label, "number": number, "status": "read",
        "source_record": {"kind": "unknown", "reason": "test"},
        "extent": {"x_m": [20.7, 24.2], "y_m": [0.1, 10.0], "z_m": [0.0, 11.5], "side": "port", "status": {}}}
    spaces = [entry("a", "other_tank", "E.Q.T. (P)", None), entry("b", "fuel_tank", "NO.2 F.O.T. (P)", "2P")]
    kept, dropped = gs._without_same_boxes(spaces, {"breadth_m": {"value": 20.0}, "depth_m": {"value": 11.5}})
    assert [s["id"] for s in kept] == ["b"] and dropped[0]["id"] == "a" and "same box" in dropped[0]["reason"]


def _space(space_id, kind, label, x, v, at, axis="z_m", view="v1", frames=None):
    extent = {"frames": frames or [int(x[0]), int(x[1])], "x_m": list(x), "x_measured_m": list(x), axis: list(v),
              "status": {"x": "measured_from_scale", axis[0]: "measured_from_scale"}, "view_id": view,
              "label_at_m": list(at), "basis": "outline"}
    return {"id": space_id, "kind": kind, "label": label, "number": None, "status": "read",
            "source_record": {"kind": "read", "regions": [{"sheet": "S_GA.png", "page": 0, "view": None, "box_px": [1.0, 1.0, 9.0, 9.0], "page_px": [100, 100]}]},
            "extent": extent}


def test_a_box_ends_at_a_labelled_strip_inside_it():
    """A hold boxed down to the base line over its double-bottom tank (lane W, round u4r: holds
    lost most of their volume) ends at the tank top."""
    hold = _space("cargo_hold-1", "cargo_hold", "NO.2 CARGO HOLD", (40, 60), (0.0, 18.0), (50, 10))
    tank = _space("ballast_tank-2", "ballast_tank", "NO.2 W.B.T. (P/S)", (40, 60), (0.0, 1.8), (50, 0.9))
    result = {"spaces": [hold, tank], "checks": []}
    stats = gs.resolve_overlaps(result)
    assert hold["extent"]["z_m"] == [1.8, 18.0] and hold["extent"]["status"]["z"] == "measured_from_scale"
    assert stats["trimmed"] == 1 and hold["extent"]["trimmed_by"] == ["ballast_tank-2"]
    assert tank["extent"]["z_m"] == [0.0, 1.8]


def test_a_box_that_takes_in_a_neighbour_it_cannot_be_cut_from_is_a_guess():
    room = _space("other_space-1", "other_space", "BOSUN STORE", (180, 200), (10.0, 20.0), (190, 18))
    void = _space("other_space-2", "other_space", "VOID SPACE", (186, 194), (11.0, 14.0), (190, 12))
    result = {"spaces": [room, void], "checks": []}
    gs.resolve_overlaps(result)
    assert room["extent"]["status"] == {"x": "guessed", "z": "guessed"} and room["extent"]["covers"] == ["other_space-2"]
    assert "extent_covers_a_labelled_neighbour" in {c["code"] for c in result["checks"]}


def test_a_tank_drawn_over_a_cargo_tank_in_the_profile_gets_no_full_breadth_extent():
    """A wing ballast tank drawn over a cargo tank in the profile, with no plan breadth, would take
    the cargo tank's volume as a full-breadth box (lane W, round u4r: 99 % lost)."""
    cot = _space("cargo_tank-1", "cargo_tank", "NO.1 C.O.T. (P&S)", (150, 170), (2.0, 21.0), (158, 12))
    wbt = _space("ballast_tank-2", "ballast_tank", "NO.1 W.B.T. (P&S)", (150, 170), (0.0, 21.5), (162, 8))
    result = {"spaces": [cot, wbt], "checks": [], "views": [{"view_id": "v1", "kind": "profile"}]}
    gs.resolve_overlaps(result)
    assert wbt["extent"]["projection_of"] == "cargo_tank-1" and "projection_of" not in cot["extent"]
    merged = {entry["id"]: entry for entry in gs.merged_spaces(result)}
    assert "extent" not in merged["ballast_tank-2"] and "extent_withheld" in merged["ballast_tank-2"]
    assert merged["cargo_tank-1"]["extent"]["z_m"] == [2.0, 21.0]


def test_a_tank_labelled_per_side_on_one_plan_and_as_a_pair_on_another_is_one_pair():
    """Deck plan: NO.6 C.O.TK(P) and (S); tank top: NO.6 C.O.TK(P&S). Two tanks, not four."""
    port = _space("cargo_tank-1", "cargo_tank", "NO.6 C.O.TK(P)", (36, 57), (0.2, 15.6), (46, 8), "y_m", "v8")
    starboard = _space("cargo_tank-2", "cargo_tank", "NO.6 C.O.TK(S)", (36, 57), (-15.8, -0.7), (46, -8), "y_m", "v8")
    pair = _space("cargo_tank-3", "cargo_tank", "NO.6 C.O.TK(P&S)", (36, 57), (0.3, 11.1), (46, 6), "y_m", "v9")
    for space, number, side in ((port, "6P", "port"), (starboard, "6S", "starboard"), (pair, "6", "both")):
        space["number"], space["extent"]["side"] = number, side
    result = {"spaces": [port, starboard, pair], "checks": [],
              "views": [{"view_id": "v8", "kind": "deck_plan"}, {"view_id": "v9", "kind": "tank_top_plan"}]}
    tanks = [s for s in gs.merged_spaces(result) if s["kind"] == "cargo_tank"]
    assert sorted(s["extent"]["side"] for s in tanks) == ["port", "starboard"]


def test_two_plan_boxes_that_hold_each_others_labels_are_guessed_across():
    cot = _space("cargo_tank-1", "cargo_tank", "NO.3 C.O.T. (P)", (80, 100), (0.0, 16.0), (90, 6), "y_m", "v2")
    wbt = _space("ballast_tank-2", "ballast_tank", "NO.3 W.B.T. (P)", (80, 100), (2.0, 16.0), (90, 14), "y_m", "v2")
    result = {"spaces": [cot, wbt], "checks": []}
    gs.resolve_overlaps(result)
    assert cot["extent"]["status"]["y"] == "guessed" and wbt["extent"]["status"]["y"] == "guessed"


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


def test_a_perpendicular_mark_counts_only_on_the_profile():
    """The LBP needs F.P. on the profile's frame scale; an F.P. in a plan does not count (round u6)."""
    places = {name: [(0.0, 0.0)] for name in gs.PROFILE_PLACES}
    plan_places = {name: [(0.0, 0.0)] for name in gs.PLAN_PLACES}
    work = {"kinds": {"v1": "profile", "v2": "deck_plan"},
            "raw": {"points": {"v1": places, "v2": plan_places},
                    "marks": {"v1": {"ap": [(0.0, 0.0)]}, "v2": {"fp": [(0.0, 0.0)]}}}}
    assert gs.missing_places(work) == ["F.P."]


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
    # Holds boxed one rail height (1 m) above the pointed line (round u5): the boxes may end on
    # the rail; neither value is given.
    rail = _depth_run(tmp_path / "rb", deck_shift_px=12.0)
    depth = rail["measured"]["depth_m"]
    assert depth["value"] is None and "rail height" in depth["reason"]


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


def test_a_box_outboard_of_the_hull_gets_no_space_extent():
    ladder = {"id": "x", "kind": "other_space", "label": "BOAT DECK STORE", "number": None, "status": "read",
              "source_record": {"kind": "unknown", "reason": "test"},
              "extent": {"x_m": [10.0, 18.0], "y_m": [12.5, 14.0], "side": "port", "status": {}}}
    inside = json.loads(json.dumps(ladder))
    inside["id"], inside["extent"]["y_m"] = "y", [8.0, 11.0]
    kept = gs._without_outboard_extents([ladder, inside], {"breadth_m": {"value": 24.0}})
    assert "extent" not in kept[0] and "outboard" in kept[0]["extent_withheld"] and "extent" in kept[1]


def test_cranes_left_without_an_extent_get_one_more_request(tmp_path):
    """Deck equipment comes late in the extents order (lane W, round u6r: three cranes skipped)."""
    result = _result(tmp_path)
    crane = json.loads(json.dumps(next(s for s in result["spaces"] if s["id"] == "cargo_hold-001")))
    crane.update(id="cargo_crane-050", kind="cargo_crane", label="DECK CRANE", number=None)
    crane["source_record"]["regions"][0]["box_px"] = [_px(100), 380.0, _px(102), 400.0]
    result["spaces"].append(crane)
    asked = []

    def call(request_dir, provider_dir):
        if request_dir.name.startswith("extents"):
            asked.append((request_dir.name, [s["space_id"] for s in json.loads(
                (request_dir / "request.json").read_text())["context"]["spaces"]]))
            reply = _extent_reply(request_dir)
            if request_dir.name != "extents-deck":  # the main request leaves the crane out
                reply["reply"]["ga_scale"]["extents"] = [e for e in reply["reply"]["ga_scale"]["extents"]
                                                         if e["space_id"] != "cargo_crane-050"]
            else:
                reply["reply"]["ga_scale"]["extents"] = [dict(reply["reply"]["ga_scale"]["extents"][0],
                                                              space_id="cargo_crane-050")]
            return reply
        return _scale_reply(request_dir)

    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    assert asked[-1] == ("extents-deck", ["cargo_crane-050"])
    assert "extent" in next(s for s in result["spaces"] if s["id"] == "cargo_crane-050")
    assert stats["extents"]["deck_requests"] == 1



def _redraw_run(tmp_path, redrawn_bottom_px, redrawn_top_px=DECK_Y):
    """A hold box that holds the label of a space without a box, and its redrawn box."""
    result = _result(tmp_path)
    void = json.loads(json.dumps(next(s for s in result["spaces"] if s["id"] == "other_space-006")))
    void.update(id="other_space-060", label="VOID SPACE", view_id="v1")
    void["source_record"]["regions"][0]["box_px"] = [1100.0, 440.0, 1160.0, 450.0]
    result["spaces"].append(void)
    asked = []

    def call(request_dir, provider_dir):
        if request_dir.name == "extents-redraw":
            asked.extend(json.loads((request_dir / "request.json").read_text())["context"]["spaces"])
            x0, y0 = _image_xy(request_dir, "v1", _px(80), redrawn_top_px)
            x1, y1 = _image_xy(request_dir, "v1", _px(120), redrawn_bottom_px)
            return {"reply": {"ga_scale": {"ticks": [], "spacing_labels": [], "spacing_boundaries": [], "points": [],
                                           "note": "", "extents": [{"space_id": "cargo_hold-001", "image_id": "v1",
                                                                    "box": [x0, y0, x1, y1], "basis": "outline"}]}}}
        return _extent_reply(request_dir) if request_dir.name == "extents" else _scale_reply(request_dir)

    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    hold = next(s for s in result["spaces"] if s["id"] == "cargo_hold-001")
    return result, stats, asked, hold


def test_a_box_over_the_label_of_a_space_without_a_box_is_drawn_again(tmp_path):
    """Review round 4: boxes took in stores and tanks that had a label but no box."""
    result, stats, asked, hold = _redraw_run(tmp_path, redrawn_bottom_px=430.0)
    assert [(entry["space_id"], [other["label"] for other in entry["exclude"]]) for entry in asked] == [
        ("cargo_hold-001", ["VOID SPACE"])]
    assert hold["extent"]["redrawn"] and hold["extent"]["status"]["x"] == gs.MEASURED
    assert stats["extents"]["redraw_requests"] == 1 and stats["extents"]["redraw_kept"] == 1


def test_a_redrawn_box_that_still_holds_the_label_is_refused_and_guessed(tmp_path):
    result, stats, _, hold = _redraw_run(tmp_path, redrawn_bottom_px=BASE_Y - 24)
    assert "redrawn" not in hold["extent"] and stats["extents"]["redraw_kept"] == 0
    assert set(hold["extent"]["status"].values()) == {"guessed"} and "other_space-060" in hold["extent"]["covers"]
    assert any(c["code"] == "extent_covers_a_labelled_neighbour" for c in result["checks"])



def _local_scale(local_frames=(67, 137), stretched=True, mirror=False):
    """Frame numbers every 5 frames at 800 mm (8 px a frame), with one-frame 1200 mm intervals."""
    def x(frame):
        place = 100 + 8.0 * frame + sum(4.0 for k in local_frames if stretched and frame >= k + 1)
        return 3000 - place if mirror else place

    ticks = [(frame, x(frame)) for frame in range(0, 201, 5)]
    labels = [(800.0, x(30)), (800.0, x(100)), (800.0, x(170))]
    labels += [(1200.0, (x(k) + x(k + 1)) / 2) for k in local_frames]
    return ticks, labels


@pytest.mark.parametrize("mirror", [False, True])
def test_a_local_spacing_printed_for_one_frame_is_a_one_frame_interval(mirror):
    """Review round 4: "1200" printed under close bulkheads inside a range of 800."""
    ticks, labels = _local_scale(mirror=mirror)
    table, reason = gs.spacing_table(ticks, labels, [])
    assert reason == "established"
    assert [(s["from_frame"], s["to_frame"], s["spacing_mm"]) for s in table.spans] == [
        (0, 67, 800.0), (67, 68, 1200.0), (68, 137, 800.0), (137, 138, 1200.0), (138, 200, 800.0)]
    assert table.x_m(140) - table.x_m(60) == pytest.approx(80 * 0.8 + 2 * 0.4)


def test_a_second_spacing_that_the_frame_numbers_do_not_show_is_refused():
    ticks, labels = _local_scale(stretched=False)
    table, reason = gs.spacing_table(ticks, labels, [])
    assert table is None and "no change drawn" in reason



def _guessed_tank_over_a_hold():
    """Lane W, round u6r3: a short untyped tank label got a box guessed along a whole hold."""
    def entry(space_id, kind, label, extent):
        return {"id": space_id, "kind": kind, "label": label, "number": None, "status": "read",
                "source_record": {"kind": "read", "regions": [{"box_px": [0, 0, 10, 10]}]}, "extent": extent}

    hold = entry("cargo_hold-001", "cargo_hold", "NO.4 CARGO HOLD",
                 {"x_m": [20.0, 48.0], "y_m": [-10.0, 10.0], "z_m": [1.5, 14.0], "side": "both",
                  "status": {"x": "measured_from_scale", "y": "measured_from_scale", "z": "measured_from_scale"}})
    tank = entry("other_tank-002", "other_tank", "X. Y. (P)",
                 {"x_m": [22.0, 47.0], "y_m": [7.5, 10.5], "side": "port", "status": {"x": "guessed", "y": "guessed"}})
    room = entry("other_space-003", "other_space", "STORE",
                 {"x_m": [50.0, 54.0], "y_m": [-3.0, 3.0], "side": "centre", "status": {"x": "guessed", "y": "guessed"}})
    particulars = {"breadth_m": {"value": 32.0}, "depth_m": {"value": 18.0}}
    return [hold, tank, room], particulars


def test_a_box_guessed_on_every_axis_does_not_cover_a_cargo_space():
    spaces, particulars = _guessed_tank_over_a_hold()
    kept = gs._without_guessed_over_cargo(spaces, particulars)
    assert "extent" in kept[0] and "extent" in kept[2]  # the hold, and a guessed room beside it
    assert "extent" not in kept[1] and "cargo" in kept[1]["extent_withheld"]


def test_the_gate_fails_a_box_guessed_on_every_axis_over_a_hold():
    """The regression case of lane W's gate (round u6r3)."""
    spaces, particulars = _guessed_tank_over_a_hold()
    report = gs.arrangement_gate({"spaces": spaces, "particulars": particulars})
    assert report["guessed_over_cargo"] == ["X. Y. (P)"] and not report["passed"]
    report = gs.arrangement_gate({"spaces": gs._without_guessed_over_cargo(spaces, particulars),
                                  "particulars": particulars})
    assert report["guessed_over_cargo"] == [] and report["passed"]


@pytest.mark.parametrize("box, withheld", [([0, 0, 280, 40], True), ([0, 0, 150, 90], False)])
def test_a_short_untyped_label_keeps_a_small_guessed_box(box, withheld):
    space = {"id": "other_tank-1", "kind": "other_tank", "label": "X. Y. (P)", "number": None, "status": "read",
             "source_record": {"kind": "read", "regions": [{"box_px": [0, 0, 97, 61]}]},
             "extent": {"outline_box_px": box, "status": {"x": "guessed", "y": "guessed"}}}
    result = {"spaces": [space], "checks": []}
    assert gs.withhold_oversized_guesses(result) == int(withheld)
    assert ("extent" not in space) is withheld



def test_a_guessed_side_tank_against_the_shell_keeps_its_extent():
    """A wing tank inside a hold box drawn to the shell is not a small space over the hold."""
    spaces, particulars = _guessed_tank_over_a_hold()
    spaces[0]["extent"]["y_m"] = [-16.0, 16.0]
    spaces[1]["extent"]["y_m"] = [13.8, 16.0]
    kept = gs._without_guessed_over_cargo(spaces, particulars)
    assert "extent" in kept[1]



def test_a_redrawn_box_that_leaves_its_own_label_is_refused(tmp_path):
    """Round u6r5: cargo tanks were redrawn as a strip at the bottom to leave out a label."""
    _, stats, _, hold = _redraw_run(tmp_path, redrawn_bottom_px=BASE_Y - 24, redrawn_top_px=452.0)
    assert stats["extents"]["redraw_kept"] == 0 and "redrawn" not in hold["extent"]



def test_a_redrawn_box_cut_to_a_strip_is_refused(tmp_path):
    """Rounds u6r5 and u6r6: holds and cargo tanks were cut to strips to leave out a label."""
    _, stats, _, hold = _redraw_run(tmp_path, redrawn_bottom_px=418.0, redrawn_top_px=400.0)
    assert stats["extents"]["redraw_kept"] == 0 and "redrawn" not in hold["extent"]



@pytest.mark.parametrize("label, z, withheld", [("X.W.T. (P)", [12.6, 18.0], False), ("D.B. W.B.T. (P)", None, True)])
def test_a_guessed_side_tank_without_a_drawn_height_is_not_full_height(label, z, withheld):
    """Lane W, round u6r7: side tanks guessed on every axis became full-height columns in a hold."""
    spaces, particulars = _guessed_tank_over_a_hold()
    spaces[1]["label"] = label
    spaces[1]["extent"]["y_m"] = [13.8, 16.0]
    tank = gs._side_boxes_without_height(spaces, particulars)[1]
    assert ("extent" not in tank) is withheld
    if z:
        assert tank["extent"]["z_m"] == z and tank["extent"]["status"]["z"] == "guessed"


def test_the_gate_limits_a_guessed_box_to_a_small_share_of_a_hold_also_at_the_shell():
    spaces, particulars = _guessed_tank_over_a_hold()
    spaces[0]["extent"]["y_m"] = [-16.0, 16.0]
    spaces[1]["extent"]["y_m"] = [10.0, 16.0]  # against the shell, full height: 17 % of the hold
    report = gs.arrangement_gate({"spaces": spaces, "particulars": particulars})
    assert report["guessed_over_cargo"] == ["X. Y. (P)"] and not report["passed"]


def test_a_hold_boxed_off_the_centreline_is_centred_and_guessed():
    spaces, particulars = _guessed_tank_over_a_hold()
    spaces[0]["extent"]["y_m"] = [-7.0, 12.0]
    hold = gs._centred_when_off_centre(spaces, particulars)[0]
    assert hold["extent"]["y_m"] == [-9.5, 9.5] and hold["extent"]["status"]["y"] == "guessed"
    assert hold["extent"]["status"]["x"] == "measured_from_scale"


def test_a_note_of_the_same_kind_inside_a_hatch_box_is_not_a_neighbour():
    """Lane W, round u6r7: a hatch-cover note inside a hatch box took the hatch's extent."""
    result = {"views": [{"view_id": "v2", "kind": "deck_plan"}], "spaces": [
        {"id": "h", "kind": "cargo_hatch", "label": "NO. 2 CARGO HATCH", "status": "read", "view_id": "v2",
         "source_record": {"regions": [{"box_px": [10, 10, 20, 20]}]},
         "extent": {"outline_box_px": [0, 0, 100, 100], "view_id": "v2", "status": {"x": "measured_from_scale"}}},
        {"id": "n", "kind": "cargo_hatch", "label": "STEEL HATCH COVER", "status": "read", "view_id": "v2",
         "source_record": {"regions": [{"box_px": [40, 40, 60, 60]}]}}]}
    assert gs.covered_labels(result) == {}



def test_a_crane_box_above_the_deck_reaches_down_to_the_deck():
    """Lane W, round u6r8: crane posts started 8 m above the deck."""
    crane = {"id": "c", "kind": "cargo_crane", "label": "DECK CRANE", "status": "read",
             "extent": {"x_m": [30.0, 34.0], "z_m": [19.8, 31.0], "status": {"x": "measured_from_scale",
                                                                            "z": "measured_from_scale"}}}
    on_deck = gs._deck_equipment_on_the_deck([crane], {"depth_m": {"value": 12.0}})[0]
    assert on_deck["extent"]["z_m"] == [12.0, 31.0] and on_deck["extent"]["status"]["z"] == "guessed"
    assert on_deck["extent"]["status"]["x"] == "measured_from_scale"


def test_a_clean_scale_reply_is_read_alone_when_the_earlier_marks_spoil_it(tmp_path):
    """Round u8: the first reply drew changes on one side of a local spacing only."""
    result = _result(tmp_path)
    attempts = []

    def call(request_dir, provider_dir):
        if request_dir.name.startswith("scale"):
            attempts.append(request_dir.name)
            reply = _scale_reply(request_dir)
            if request_dir.name == "scale":  # a second spacing in the 800 range, no change drawn
                labels = reply["reply"]["ga_scale"]["spacing_labels"]
                middle = next(label for label in labels if label["printed"].startswith("800"))
                labels.append({**middle, "printed": "650 MM", "x": middle["x"] + 200})
            return reply
        return _extent_reply(request_dir)

    gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    assert attempts == ["scale", "scale-2"] and result["frames"]["status"] == "read"



def _outline_run(tmp_path, outline_px):
    """The test sheet with an outline traced for the port ballast tank of the tank-top plan."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    result = _result(tmp_path)

    def call(request_dir, provider_dir):
        if request_dir.name != "extents":
            return _scale_reply(request_dir)
        reply = _extent_reply(request_dir)
        if outline_px is not None:
            for entry in reply["reply"]["ga_scale"]["extents"]:
                if entry["space_id"] == "ballast_tank-004":
                    entry["outline"] = [list(_image_xy(request_dir, "v2", x, y)) for x, y in outline_px]
        return reply

    gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    result["particulars"] = {}
    tank = next(s for s in result["spaces"] if s["id"] == "ballast_tank-004")
    return result, tank


TAPERED = [(_px(80), 922.0), (_px(120), 922.0), (_px(120), 1095.0), (_px(84), 1095.0)]


def test_an_outline_traced_in_its_box_is_kept_as_a_trace():
    """PM decision 2026-11-12: an optional outline for a boundary that is not a rectangle."""
    import tempfile
    result, tank = _outline_run(Path(tempfile.mkdtemp()), TAPERED)
    outline = tank["extent"]["outline"]
    assert outline["plane"] == "xy" and outline["status"] == "traced" and len(outline["points_m"]) == 4
    assert tank["extent"]["status"]["y"] == gs.MEASURED  # the trace adds no measured status
    entry = next(s for s in gs.arrangement_input(result, "S-1")["spaces"] if s["label"] == "NO.2 W.B.T. (P)")
    assert entry["extent"]["outline_m"][0]["plane"] == "xy"


@pytest.mark.parametrize("outline_px, reason", [
    # Down over the centreline to the hold's label: it takes in a labelled neighbour.
    ([(_px(80), 922.0), (_px(120), 922.0), (_px(120), 1102.0), (_px(80), 1102.0)], "holds the label of"),
    ([(_px(70), 922.0), (_px(120), 922.0), (_px(120), 1095.0)], "leaves its box"),
    ([(_px(80), 990.0), (_px(120), 990.0), (_px(120), 1095.0)], "own label"),
])
def test_an_outline_that_takes_in_a_neighbours_label_or_leaves_its_box_is_dropped(tmp_path, outline_px, reason):
    result, tank = _outline_run(tmp_path, outline_px)
    assert "outline" not in tank["extent"] and "extent" in tank
    assert any(c["code"] == "outline_dropped" and reason in c["reason"] for c in result["checks"])


def test_an_arrangement_input_without_outlines_is_as_before(tmp_path):
    plain, _ = _outline_run(tmp_path / "a", None)
    traced, _ = _outline_run(tmp_path / "b", TAPERED)

    def without_outlines(data):
        for space in data["spaces"]:
            space.get("extent", {}).pop("outline_m", None)
        return data["spaces"]

    assert not any("outline_m" in s.get("extent", {}) for s in gs.arrangement_input(plain, "S-1")["spaces"])
    assert without_outlines(gs.arrangement_input(traced, "S-1")) == gs.arrangement_input(plain, "S-1")["spaces"]


def test_the_mirror_of_a_traced_tank_gets_the_mirrored_outline():
    entry = {"id": "t", "kind": "ballast_tank", "label": "NO.2 W.B.T. (P&S)", "number": "2", "status": "read",
             "extent": {"x_m": [10.0, 20.0], "y_m": [5.0, 15.0], "side": "both", "status": {"x": "m", "y": "m"},
                        "outline_m": [{"plane": "xy", "points": [[10.0, 5.0], [20.0, 5.0], [20.0, 15.0]],
                                       "status": "traced"}]}}
    first, second = gs._split_pair(entry)
    assert first["extent"]["outline_m"][0]["points"][2] == [20.0, 15.0]
    assert second["extent"]["outline_m"][0]["points"][2] == [20.0, -15.0]
    assert second["extent"]["outline_m"][0]["status"] == "guessed"



def _misread_scale(spacing_b, kink=None):
    """Frames 0-50 at 800 mm (8 px a frame, printed "800"), frames 50-100 printed "600" but drawn
    at ``spacing_b`` (or at ``kink`` from frame 75 on, with no change drawn there)."""
    def x(frame):
        place = 100 + 8.0 * min(frame, 50)
        for start, end, mm in ((50, 75, spacing_b), (75, 100, kink or spacing_b)):
            place += max(0, min(frame, end) - start) * mm / 100.0
        return place

    ticks = [(frame, x(frame)) for frame in range(0, 101, 5)]
    return ticks, [(800.0, x(25)), (600.0, x(75))], [x(50)]


def test_a_spacing_the_frame_numbers_contradict_is_chosen_from_the_fit():
    """Round u9n2: a printed "800" read as "600" in every reply refused the whole scale."""
    table, reason = gs.spacing_table(*_misread_scale(700.0))
    assert reason == "established"
    assert [(s["spacing_mm"], s.get("status")) for s in table.spans] == [
        (800.0, None), (700.0, gs.CHOSEN_BY_FIT)]


def test_a_range_holding_two_spacings_is_still_refused():
    table, reason = gs.spacing_table(*_misread_scale(700.0, kink=900.0))
    assert table is None and "do not fit" in reason



def test_a_missing_fuel_tank_extent_is_a_coverage_warning_not_a_failure():
    spaces, particulars = _guessed_tank_over_a_hold()
    report = gs.arrangement_gate({"spaces": [spaces[0]], "particulars": particulars})
    assert report["passed"] and report["warnings"] == ["no fuel tank has an extent", "no ballast tank has an extent"]



def test_a_hold_read_twice_with_a_note_is_one_hold():
    """Round u10: "NO. 5 HOLD (PORT USE W. B.)" beside "NO. 5 HOLD" gave two holds."""
    def hold(space_id, label, view, extent):
        return {"id": space_id, "kind": "cargo_hold", "label": label, "number": "5", "status": "read",
                "view_id": view, "source_record": source_record.read([source_record.region(
                    "S-1_GA.png", view="plan", box_px=[0, 0, 10, 10], page_px=[100, 100])]),
                "extent": {**extent, "view_id": view, "basis": "outline",
                           "status": {axis: "measured_from_scale" for axis in "xyz"}}}

    profile = {"frames": [20, 50], "x_m": [24.0, 54.0], "z_m": [6.0, 16.0]}
    plan = {"frames": [20, 50], "x_m": [24.0, 54.0], "y_m": [-8.0, 8.0], "side": "centre"}
    result = {"views": [{"view_id": "v1", "kind": "profile"}, {"view_id": "v3", "kind": "tank_top_plan"}],
              "spaces": [hold("a", "NO. 5 HOLD", "v1", profile), hold("b", "NO. 5 HOLD", "v3", plan),
                         hold("c", "NO. 5 HOLD (PORT USE W. B.)", "v3", {**plan, "side": "port"}),
                         hold("d", "NO. 5 HOLD (PORT USE W. B.)", "v1", profile)]}
    holds = [s for s in gs.merged_spaces(result) if s["kind"] == "cargo_hold"]
    assert len(holds) == 1 and holds[0]["extent"]["y_m"] == [-8.0, 8.0]
    # Only profile readings: still one hold.
    result["spaces"] = [result["spaces"][0], result["spaces"][3]]
    assert len([s for s in gs.merged_spaces(result) if s["kind"] == "cargo_hold"]) == 1



def test_a_change_drawn_frames_past_a_one_frame_spacing_is_left_out():
    """Round u10: a change drawn four frames past a one-frame "1200" made a four-frame range."""
    ticks, labels = _local_scale(local_frames=(67,))
    x = dict(ticks)

    def place(frame):  # sheet x of any frame, as _local_scale draws it
        return 100 + 8.0 * frame + (4.0 if frame >= 68 else 0.0)

    good = [place(67), place(68)]
    table, reason = gs.spacing_table(ticks, labels, good)
    assert reason == "established" and (67, 68, 1200.0) in [(s["from_frame"], s["to_frame"], s["spacing_mm"])
                                                              for s in table.spans]
    table, reason = gs.spacing_table(ticks, labels, [place(67), place(71)])  # the second change misplaced
    assert reason == "established"
    spans = [(s["from_frame"], s["to_frame"], s["spacing_mm"]) for s in table.spans]
    assert (67, 68, 1200.0) in spans and not any(mm == 1200.0 and b - a > 1 for a, b, mm in spans)
    assert x  # the frame numbers are the fixture's



def test_uncertain_boxes_that_agree_with_the_deck_line_give_an_unconfirmed_depth(tmp_path):
    """PM decision, round u10: a depth with its own status, never measured, never evidence."""
    agreed = _depth_run(tmp_path / "a", uncertain_below=True)
    depth = agreed["measured"]["depth_m"]
    assert depth["status"] == gs.UNCONFIRMED and depth["value"] == pytest.approx(15.0, abs=0.15)
    assert "extent_above_the_deck" not in {c["code"] for c in agreed["checks"]}  # confirms no box
    assert gs.arrangement_input(agreed, "S-1")["particulars"]["depth_m"]["status"] == gs.UNCONFIRMED
    apart = _depth_run(tmp_path / "b", uncertain_below=True, deck_shift_px=-60.0)
    assert apart["measured"]["depth_m"]["value"] is None



def test_two_cargo_tanks_with_different_numbers_at_one_place_both_lose_their_extents():
    """Round u10: one place read as NO.2, NO.3 and NO.5 in three views."""
    spaces, particulars = _guessed_tank_over_a_hold()
    hold = spaces[0]
    other = json.loads(json.dumps(hold))
    other.update(id="cargo_hold-009", label="NO.5 CARGO HOLD", number="5")
    hold["number"] = "2"
    kept = gs._without_cargo_number_conflicts([hold, other, spaces[2]], particulars)
    assert ["extent" in s for s in kept] == [False, False, True]
    assert "different number" in kept[0]["extent_withheld"]
    # Two tanks of one number (port and starboard) are not a conflict.
    other["number"] = "2P"
    assert all("extent" in s for s in gs._without_cargo_number_conflicts([hold, other], particulars))



def test_a_peak_tank_ends_below_the_spaces_boxed_above_it():
    """Astra round 6: forepeak tanks boxed up through the bosun store above them."""
    def box(space_id, kind, label, x, z):
        return {"id": space_id, "kind": kind, "label": label, "status": "read",
                "extent": {"view_id": "v1", "x_m": x, "z_m": z, "basis": "uncertain",
                           "status": {"x": "guessed", "z": "guessed"}}}

    result = {"views": [{"view_id": "v1", "kind": "profile"}], "checks": [], "spaces": [
        box("t", "ballast_tank", "F.P.T. (C)", [225.0, 240.0], [2.0, 20.0]),
        box("s", "other_space", "BOSUN STORE", [225.0, 236.0], [14.6, 24.0]),
        box("v", "other_space", "VOID", [236.0, 240.0], [12.3, 14.7]),
        box("d", "accommodation_deck", "FORECASTLE DECK", [226.0, 239.0], [16.0, 19.0]),
        box("b", "other_tank", "BILGE TK", [226.0, 230.0], [2.0, 4.0])]}  # low in the tank: kept apart
    assert gs._end_below_spaces_above(result) == 1
    tank = result["spaces"][0]["extent"]
    assert tank["z_m"] == [2.0, 12.3] and tank["status"]["z"] == "guessed" and set(tank["trimmed_by"]) == {"s", "v"}



@pytest.mark.parametrize("printed, sides", [
    ("18.200 x 15.000", (18.2, 15.0)), ("15,480 X 20,600", (15.48, 20.6)), ("15480 x 20600", (15.48, 20.6)),
    ("15,480 x 17,200 mm", (15.48, 17.2)), ("NO.5 (15.47 x 15.30)", (15.47, 15.3)),
    ("1.5 x 2", None), ("12 x", None),
])
def test_a_printed_hatch_size_parses_to_metres(printed, sides):
    assert gs.parse_hatch_size(printed) == (pytest.approx(sides) if sides else None)


def _hatches(at_px):
    """Two hatches in one deck plan, side by side; a size printed at ``at_px``."""
    def hatch(space_id, label, box_px, x_m):
        return {"id": space_id, "kind": "cargo_hatch", "label": label, "number": label[-1], "status": "read",
                "view_id": "v2", "source_record": source_record.read([source_record.region(
                    "S-1_GA.png", view="plan", box_px=box_px, page_px=[1000, 1000])]),
                "extent": {"view_id": "v2", "outline_box_px": box_px, "x_m": x_m, "frames": [10, 30],
                                            "y_m": [-11.0, 11.0], "basis": "outline",
                                            "status": {"x": "measured_from_scale", "y": "measured_from_scale"}}}

    first = hatch("cargo_hatch-1", "NO. 1", [100, 100, 300, 300], [10.0, 26.4])
    second = hatch("cargo_hatch-2", "NO. 2", [400, 100, 600, 300], [40.0, 56.4])
    first["extent"]["printed_size_raw"] = {"text": "15.480 x 20.600", "at_px": at_px}
    return {"spaces": [first, second], "checks": []}


def test_a_size_printed_inside_one_hatch_is_its_length_and_breadth():
    """PM decision 2026-11-12: printed hatch sizes (measured lengths were 1-2 m long)."""
    result = _hatches([200, 200])
    assert gs.apply_printed_hatch_sizes(result) == 1
    sized = result["spaces"][0]["extent"]["printed_size_m"]
    assert (sized["length"], sized["breadth"]) == (15.48, 20.6)  # the order closer to the measured box
    entry = gs._joined(result["spaces"][0], None)
    assert entry["extent"]["x_m"] == [10.46, 25.94] and entry["extent"]["y_m"] == [-10.3, 10.3]
    assert entry["extent"]["status"] == {"x": gs.PRINTED, "y": gs.PRINTED}
    assert entry["extent"]["measured_box_m"] == {"x_m": [10.0, 26.4], "y_m": [-11.0, 11.0]}


@pytest.mark.parametrize("at_px", [[350, 200], [500, 200]])  # between the hatches; inside the other one
def test_a_size_not_inside_this_hatch_alone_is_ignored(at_px):
    result = _hatches(at_px)
    assert gs.apply_printed_hatch_sizes(result) == 0
    assert "printed_size_m" not in result["spaces"][0]["extent"]
    assert any(c["code"] == "printed_hatch_size_ignored" for c in result["checks"])



def test_every_reported_hatch_size_is_used_or_ignored_with_a_reason():
    """Round hS2: a size reported for a hatch whose box was redrawn was dropped silently."""
    result = _hatches([200, 200])
    result["spaces"].append({"id": "other_space-9", "kind": "other_space", "label": "HATCH COVER STORE",
                             "status": "read", "view_id": "v2"})
    reported = [{"space_id": "cargo_hatch-1", "text": "15.480 x 20.600"},
                {"space_id": "cargo_hatch-2", "text": "15.480 x 20.600"},   # its box carries no size: no box to tie
                {"space_id": "other_space-9", "text": "12.0 x 8.0"}]         # not a hatch
    assert gs.apply_printed_hatch_sizes(result, reported) == 1
    reasons = sorted(c["reason"] for c in result["checks"] if c["code"] == "printed_hatch_size_ignored")
    assert reasons == ["it was given for a space that is not a cargo hatch", "its hatch has no box to tie it to"]


def test_a_redrawn_hatch_keeps_the_size_reported_with_its_first_box(tmp_path):
    """Round hS2: the redraw replaced a hatch's box and its printed size was lost."""
    result = _result(tmp_path)
    hatch = next(s for s in result["spaces"] if s["id"] == "cargo_hold-001")
    hatch.update(kind="cargo_hatch", label="NO.2 HATCH")
    void = json.loads(json.dumps(next(s for s in result["spaces"] if s["id"] == "other_space-006")))
    void.update(id="other_space-060", label="VOID SPACE", view_id="v1")
    void["source_record"]["regions"][0]["box_px"] = [1100.0, 440.0, 1160.0, 450.0]
    result["spaces"].append(void)

    def call(request_dir, provider_dir):
        if request_dir.name == "extents":
            reply = _extent_reply(request_dir)
            entry = next(e for e in reply["reply"]["ga_scale"]["extents"] if e["space_id"] == "cargo_hold-001")
            entry.update(printed_size="18.2 x 15.0", printed_size_at=list(_image_xy(request_dir, "v1", 1250.0, 400.0)))
            return reply
        if request_dir.name == "extents-redraw":  # the box drawn again, above the void, without the size
            x0, y0 = _image_xy(request_dir, "v1", _px(80), DECK_Y)
            x1, y1 = _image_xy(request_dir, "v1", _px(120), 430.0)
            return {"reply": {"ga_scale": {"ticks": [], "spacing_labels": [], "spacing_boundaries": [], "points": [],
                                           "note": "", "extents": [{"space_id": "cargo_hold-001", "image_id": "v1",
                                                                    "box": [x0, y0, x1, y1], "basis": "outline"}]}}}
        return _scale_reply(request_dir)

    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    assert stats["extents"]["redraw_kept"] == 1 and hatch["extent"]["redrawn"]
    assert hatch["extent"]["printed_size_m"]["text"] == "18.2 x 15.0"



def test_every_check_code_of_the_scale_pass_is_listed_for_a_replay():
    """A replay removes the scale pass's checks before it runs the pass again (round hS2: kept
    checks were written twice)."""
    import re as regex
    source = (Path(gs.__file__)).read_text()
    written = set(regex.findall(r'"code": "([a-z_0-9]+)"', source))
    assert written <= set(gs.SCALE_PASS_CHECKS)



def test_a_printed_chain_span_survives_the_extents_and_reaches_the_frame_record(tmp_path):
    """Backlog item 5: the dimension chain, read in the scale request (no extra request)."""
    result = _result(tmp_path)

    def call(request_dir, provider_dir):
        if request_dir.name.startswith("scale"):
            reply = _scale_reply(request_dir)
            y_text, y_line = BASE_Y + 70, BASE_Y + 80
            image_id = _holding(request_dir, "v1", _px(102.5), y_text)
            places = [_image_xy(request_dir, image_id, x, y) for x, y in
                      ((_px(102.5), y_text), (_px(100), y_line), (_px(105), y_line))]
            reply["reply"]["ga_scale"]["chain_spans"] = [{"image_id": image_id, "printed": "4000",
                                                          "at": list(places[0]), "from": list(places[1]),
                                                          "to": list(places[2])}]
            return reply
        return _extent_reply(request_dir)

    stats = gs.scale_pass(result, tmp_path / "S-1_GA.png", tmp_path / "scale", call)
    assert stats["printed_spans"] == 1
    assert result["frames"]["printed_spans"] == [
        {"from_frame": 100, "to_frame": 105, "length_m": 4.0, "text": "4000", "status": "printed"}]
