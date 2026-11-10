"""Intake of a dropped drawing set and the sheet-only draft path (no CAD here)."""
import json

import fitz
import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import intake
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.materialize import materialize_sections, materialized_spec
from vessel_reconstruction.schema import validate_spec


def three_view_png(path, dpi=150):
    """A small lines sheet: a long profile, a long plan below it, a body plan and a framed title."""
    image = Image.new("RGB", (1400, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(60, 200), (300, 120), (900, 110), (980, 60)], fill="black", width=3)  # profile
    draw.line([(60, 200), (980, 200)], fill="black", width=3)
    draw.line([(60, 420), (300, 340), (900, 330), (980, 420)], fill="black", width=3)  # plan
    draw.line([(60, 420), (980, 420)], fill="black", width=3)
    # Body plan: grid, centreline at x = 1200, baseline at y = 260, curves on both sides.
    for x in range(1080, 1321, 40):
        draw.line([(x, 60), (x, 260)], fill=(200,) * 3, width=1)
    for y in range(60, 261, 40):
        draw.line([(1080, y), (1320, y)], fill=(200,) * 3, width=1)
    draw.line([(1200, 60), (1200, 260)], fill=(120,) * 3, width=1)
    draw.line([(1080, 260), (1320, 260)], fill=(120,) * 3, width=1)
    for offset in (40, 70, 100):
        draw.line([(1200, 255), (1200 + offset, 200), (1200 + offset + 10, 80)], fill="black", width=3)
        draw.line([(1200, 255), (1200 - offset, 200), (1200 - offset - 10, 80)], fill="black", width=3)
    draw.rectangle([1080, 400, 1340, 540], outline="black", width=3)  # title block
    for row in range(3):
        draw.text((1100, 420 + 30 * row), "LOA 24.0 m BEAM 7.2 m", fill="black")
    image.save(path, dpi=(dpi, dpi))
    return path


def two_page_pdf(path):
    document = fitz.open()
    for index in range(2):
        page = document.new_page(width=600, height=400)
        page.draw_line((50, 300), (550, 300 - 40 * index), color=(0, 0, 0), width=2)
        page.draw_bezier((100, 300), (150, 100), (250, 100), (300, 300), color=(0, 0, 0), width=2)
    document.save(path)
    return path


def test_prepare_reads_pdf_pages_and_a_png_and_never_refuses(tmp_path):
    pdf = two_page_pdf(tmp_path / "set.pdf")
    png = three_view_png(tmp_path / "sheet.png")
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    preview = intake.prepare([pdf, png, broken], tmp_path / "prep", render_dpi=100)
    assert [p["kind"] for p in preview["pages"]] == ["pdf", "pdf", "raster"]
    assert [p["page_index"] for p in preview["pages"]] == [0, 1, 0]
    first = preview["pages"][0]
    assert (first["width_px"], first["height_px"]) == (834, 556)  # 600 x 400 pt at 100 dpi
    assert first["dpi"] == 100 and first["dpi_source"] == "pdf_render"
    assert "low_dpi" in {w["code"] for w in first["warnings"]}
    assert all(p["regions"] and p["thumbnail_png_base64"] for p in preview["pages"])
    for page in preview["pages"]:
        for region in page["regions"]:
            assert region["label"] in intake.LABELS and 0 <= region["confidence"] <= 1
    assert preview["warnings"][0]["code"] == "unreadable_file"
    assert json.loads((tmp_path / "prep/preview.json").read_text())["pages"]


def test_layout_rules_name_the_views_of_a_three_view_sheet(tmp_path):
    preview = intake.prepare([three_view_png(tmp_path / "sheet.png")], tmp_path / "prep")
    page = preview["pages"][0]
    assert page["dpi"] == 150
    labels = {r["label"] for r in page["regions"]}
    assert {"profile", "half_breadth", "body_plan", "title_block"} <= labels
    body = next(r for r in page["regions"] if r["label"] == "body_plan")
    # The light grid and axes belong to the body plan region.
    assert body["region_px"][1] <= 62 and body["region_px"][3] >= 259


def test_unknown_page_is_other_with_a_warning(tmp_path):
    path = tmp_path / "blank.png"
    Image.new("RGB", (400, 300), "white").save(path)
    page = intake.prepare([path], tmp_path / "prep")["pages"][0]
    assert [r["label"] for r in page["regions"]] == ["other"]
    codes = {w["code"] for w in page["warnings"]}
    assert {"no_view_found", "dpi_unknown", "small_image"} <= codes


def test_write_spec_copies_sources_and_writes_a_sheet_only_spec(tmp_path):
    pdf = two_page_pdf(tmp_path / "set.pdf")
    png = three_view_png(tmp_path / "sheet.png")
    preview = intake.prepare([pdf, png], tmp_path / "prep", render_dpi=100)
    preview["pages"][0]["skip"] = True  # a cover page
    preview["particulars"] = {"vessel_name": "Survey launch 24 m", "loa_m": 24.0, "beam_m": 7.2}
    written = intake.write_spec(preview, tmp_path / "run")
    spec = json.loads((tmp_path / "run/spec.json").read_text())
    assert written["gaps"] == [] and spec["sections"] == []
    assert spec["source"]["file"] == "sources/sheet.png"  # the page with the body plan
    assert spec["constraints"] == {"length_m": 24.0, "beam_m": 7.2}
    assert (tmp_path / "run/sources/set.pdf").is_file()
    record = json.loads((tmp_path / "run/intake.json").read_text())
    assert [p["page_id"] for p in record["pages"]] == ["p2", "p3"]
    assert "thumbnail_png_base64" not in record["pages"][0]
    gaps = {g["kind"] for g in validate_spec(spec, tmp_path / "run")}
    assert "insufficient_sections" in gaps  # the strict path still requires sections


def test_pdf_page_becomes_the_source_with_its_page_index(tmp_path):
    preview = intake.prepare([two_page_pdf(tmp_path / "set.pdf")], tmp_path / "prep", render_dpi=120)
    preview["pages"][0]["skip"] = True
    intake.write_spec(preview, tmp_path / "run")
    source = json.loads((tmp_path / "run/spec.json").read_text())["source"]
    assert (source["page_index"], source["render_dpi"]) == (1, 120)


def test_schema_accepts_sheet_only_only_when_allowed(tmp_path):
    (tmp_path / "d.png").write_bytes(b"x")
    (tmp_path / "intake.json").write_text("{}")
    spec = {"schema_version": "1.0", "vessel_id": "v", "units": "m", "source": {"file": "d.png"},
            "symmetry": "port_starboard", "symmetry_evidence": "assumed", "end_closure": "flat_at_terminal_stations",
            "sections": [], "intake": {"file": "intake.json"}}
    assert validate_spec(spec, tmp_path, allow_sheet_only=True) == []
    assert "insufficient_sections" in {g["kind"] for g in validate_spec(spec, tmp_path)}
    spec["intake"] = {"file": "intake.json", "extra": 1}
    assert "invalid_intake" in {g["kind"] for g in validate_spec(spec, tmp_path, allow_sheet_only=True)}


def test_domain_captures_a_sheet_only_spec_with_its_intake_record(tmp_path):
    preview = intake.prepare([three_view_png(tmp_path / "sheet.png")], tmp_path / "prep")
    written = intake.write_spec(preview, tmp_path / "run")
    (tmp_path / "task").mkdir()
    tools = DomainTools(tmp_path / "task", written["spec_path"])
    assert tools.state["input_errors"] == [] and tools.state["sheet_only"] is True
    assert tools.describe()["sheet_only"] is True
    assert {h["label"] for h in tools.intake_hints()} >= {"body_plan", "profile"}
    survey = tools.execute("survey_sheet", {})
    assert survey["sheet_survey"]["intake_regions"]


def _state(setups=(), stations=(), principal=None, views=()):
    return {"sheet_setups": {f"setup-{i}": s for i, s in enumerate(setups)},
            "described_views": list(views),
            "vessel_description": {"stations": list(stations), "principal": principal or {}}}


def _sheet(tmp_path):
    path = three_view_png(tmp_path / "sheet.png")
    image = np.asarray(Image.open(path).convert("RGB"))
    hints = intake.survey_page(image)
    return image, hints


def test_materialize_uses_the_read_setup_and_stations(tmp_path):
    image, hints = _sheet(tmp_path)
    body = next(h["region_px"] for h in hints if h["label"] == "body_plan")
    setup = {"view": "body", "view_id": "body", "setup_id": "setup-a", "region_px": body,
             "pixels_per_metre": 20.0, "centreline_px": 1200.0, "baseline_px": 260.0}
    stations = [{"id": f"st{i}", "x_m": 4.0 * i} for i in range(1, 6)]
    made = materialize_sections(image, {}, _state([setup], stations, views=[
        {"view_id": "body", "kind": "body", "region_px": body}]), hints)
    sections = made["sections"]
    assert [s["x_m"] for s in sections] == [4.0, 8.0, 12.0, 16.0, 20.0]
    assert all(s["calibration"] == {"pixels_per_metre": 20.0, "centerline_px": 1200.0, "baseline_px": 260.0}
               for s in sections)
    # Aft stations read the left half of the overlaid body plan, fore stations the right half.
    assert sections[0]["roi_px"][2] < 1240 and sections[-1]["roi_px"][0] > 1160
    assert all(s["evidence"].startswith("ai_inferred") for s in sections)
    spec = {"schema_version": "1.0", "vessel_id": "v", "units": "m", "source": {"file": "sheet.png"},
            "symmetry": "port_starboard", "symmetry_evidence": "assumed",
            "end_closure": "flat_at_terminal_stations", "sections": [], "intake": {"file": "intake.json"}}
    _, gaps = materialized_spec(spec, sections, tmp_path)
    assert gaps == []


def test_materialize_never_stops_without_a_reading(tmp_path):
    image, hints = _sheet(tmp_path)
    made = materialize_sections(image, {}, _state(principal={"loa": {"value": 24.0}}), hints)
    sections = made["sections"]
    assert len(sections) == 11 and made["warnings"]
    assert made["report"]["scale_basis"].startswith("long-view ink length")
    # Datums are measured from the drawn grid of the intake's body region.
    assert {s["calibration"]["centerline_px"] for s in sections} == {1200.0}
    assert {s["calibration"]["baseline_px"] for s in sections} == {260.0}


def test_materialize_replaces_body_regions_that_miss_the_sheet(tmp_path):
    image, hints = _sheet(tmp_path)
    # The model gave a body region in 0-1000 coordinates; it misses the body plan.
    setup = {"view": "body", "view_id": "body", "setup_id": "setup-a", "region_px": [40, 40, 300, 300],
             "pixels_per_metre": 1.0, "centreline_px": 50.0, "baseline_px": 290.0}
    made = materialize_sections(image, {}, _state([setup], principal={"beam": {"value": 7.2}}), hints)
    assert made["report"]["panel_source"] == "the intake's body regions"
    assert all(s["roi_px"][0] >= 1000 for s in made["sections"])
    assert any("do not match" in w for w in made["warnings"])


def blurred_body_plan():
    """A grey, blurred scan of a body plan: light grid, dash-dot centreline at x = 200, baseline at y = 260."""
    from PIL import ImageFilter
    image = Image.new("RGB", (400, 320), (235,) * 3)
    draw = ImageDraw.Draw(image)
    for x in range(80, 321, 40):
        if x != 200:
            draw.line([(x, 40), (x, 260)], fill=(205,) * 3, width=1)
    for y in range(60, 261, 40):
        draw.line([(60, y), (340, y)], fill=(205,) * 3, width=1)
    for top in range(30, 270, 24):  # dash-dot: a long dash and a dot
        draw.line([(200, top), (200, top + 14)], fill=(110,) * 3, width=1)
        draw.line([(200, top + 18), (200, top + 19)], fill=(110,) * 3, width=1)
    draw.line([(60, 260), (340, 260)], fill=(110,) * 3, width=2)
    for offset in (50, 90, 125):
        draw.line([(200, 258), (200 + offset, 200), (200 + offset + 8, 70)], fill="black", width=3)
        draw.line([(200, 258), (200 - offset, 200), (200 - offset - 8, 70)], fill="black", width=3)
    return np.asarray(image.filter(ImageFilter.GaussianBlur(1.5)))


def test_grid_datums_find_a_dash_dot_centreline_on_a_blurred_scan():
    from vessel_reconstruction.materialize import grid_datums
    datums = grid_datums(blurred_body_plan(), [0, 0, 400, 320])
    assert abs(datums["centreline_px"] - 200) <= 1.0
    assert abs(datums["baseline_px"] - 260) <= 1.5


def _section(sid, x, ppm=20.0, centre=1200.0):
    return {"id": sid, "x_m": x, "z_max_m": 5.0,
            "calibration": {"pixels_per_metre": ppm, "centerline_px": centre, "baseline_px": 260.0}}


def test_setup_changes_name_moved_stations_scales_datums_and_dimensions():
    from vessel_reconstruction.first_hull_tools import setup_changes
    old = {"sections": [_section("1", 0.0), _section("2", 10.0)], "constraints": {"beam_m": 7.2}}
    assert setup_changes(old, old) == []
    # Reading noise (0.5 % of the length, half a pixel) keeps the built hull.
    noisy = {"sections": [_section("1", 0.0), _section("2", 10.05, centre=1200.5)], "constraints": {"beam_m": 7.2}}
    assert setup_changes(old, noisy) == []
    corrected = {"sections": [_section("1", 0.0, ppm=2.0), _section("2", 100.0, ppm=2.0, centre=1190.0)],
                 "constraints": {"beam_m": 13.4}}
    changes = setup_changes(old, corrected)
    assert any("x 10 -> 100" in c for c in changes) and any("scale" in c for c in changes)
    assert any("centerline_px" in c for c in changes) and any("beam_m" in c for c in changes)


def test_a_corrected_reading_after_the_first_hull_builds_it_again(tmp_path, monkeypatch):
    from vessel_reconstruction import first_hull_tools
    preview = intake.prepare([three_view_png(tmp_path / "sheet.png")], tmp_path / "prep")
    written = intake.write_spec(preview, tmp_path / "run")
    (tmp_path / "task").mkdir()
    tools = DomainTools(tmp_path / "task", written["spec_path"])
    body = next(h["region_px"] for h in tools.intake_hints() if h["label"] == "body_plan")
    tools.state.update(_state(views=[{"view_id": "body", "kind": "body", "region_px": body}]))
    first = {"stations": [{"id": f"{i}", "x_m": 1.0 * i} for i in range(5)], "principal": {"loa": {"value": 4.0}}}
    tools._describe_vessel(json.loads(json.dumps(first)))
    tools._materialize_sections()
    tools.state.update(vessel_table={"stations": []}, selected={"0": "old"}, authored_sections={"1": {}})
    built = []
    monkeypatch.setattr(first_hull_tools, "build_first_hull",
                        lambda t: built.append(t.state.get("materialized_spec_sha256")) or {"message": "built"})
    # The same reading again keeps the hull.
    same = tools._describe_vessel(json.loads(json.dumps(first)))
    assert built == [] and same["status"] == "vessel_described", same.get("setup_changes")
    # The title block read again: LOA 40 m, stations ten times farther apart.
    corrected = {"stations": [{"id": f"{i}", "x_m": 10.0 * i} for i in range(5)],
                 "principal": {"loa": {"value": 40.0}}}
    rebuilt = tools._describe_vessel(corrected)
    assert built == [None], "the sections are materialized again from the corrected reading"
    assert rebuilt["setup_changes"] and tools.state["selected"] == {} and tools.state["authored_sections"] == {}


def test_prepare_types_every_page_and_checks_the_drawing_set(tmp_path, monkeypatch):
    # OCR is replaced so the test does not depend on the tesseract program.
    monkeypatch.setattr("vessel_reconstruction.sheet_types.ocr_read", lambda gray, **kw: ("", ""))
    pdf = tmp_path / "Tank Plan Rev1.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=400)
    page.insert_text((40, 40), "TANK PLAN   tank schedule   capacity   SCALE 1:50", fontsize=14)
    page.draw_line((50, 300), (550, 300), color=(0, 0, 0), width=2)
    document.save(pdf)
    png = three_view_png(tmp_path / "sheet.png")
    asked = []

    def ask(prompt, pngs):
        asked.append(len(pngs))
        return '{"type": "lines_plan", "confidence": 0.8, "evidence": "sheer and body plan"}'

    preview = intake.prepare([pdf, png], tmp_path / "prep", render_dpi=100, ask=ask)
    tank, sheet = (p["sheet"] for p in preview["pages"])
    assert tank["type"] == "tank_plan" and tank["source"].startswith("file_name") and tank["scale"]["main_ratio"] == 50.0
    assert sheet["source"] == "model:claude-sonnet-5-5" and sheet["type"] == "lines_plan"
    assert asked == [1]  # only the sheet code could not settle was asked
    found = {item["id"]: item["status"] for item in preview["set"]["checklist"]}
    assert found["tanks_plan"] == "met" and found["hull_lines"] == "met" and found["steel_shell"] == "missing"
    assert "steel_shell" in preview["set"]["missing_required"]
    assert preview["set"]["engineering_approved"] is False
    assert preview["set"]["rules"] and preview["set"]["outputs"]


def test_prepare_reports_completed_pages(tmp_path, monkeypatch):
    from vessel_reconstruction import progress

    reports = []
    monkeypatch.setattr(progress, "report", lambda stage, part=0, total=0, **kw: reports.append((stage, part, total)))
    pdf = two_page_pdf(tmp_path / "set.pdf")
    intake.prepare([pdf], tmp_path / "prep", render_dpi=100)
    assert reports == [("Reading drawings", 0, 0), ("Read page 1", 0, 0), ("Read page 2", 0, 0)]


def test_each_model_question_reports_progress(monkeypatch):
    from vessel_reconstruction import progress

    reports = []
    monkeypatch.setattr(progress, "report", lambda stage, part=0, total=0, **kw: reports.append(stage))
    ask = intake._reporting_ask(lambda prompt, pngs: f"answer to {prompt}")
    assert ask("a", []) == "answer to a" and ask("b", []) == "answer to b"
    assert reports == ["Asking the model (question 1)", "Asking the model (question 2)"]
    assert intake._reporting_ask(None) is None
