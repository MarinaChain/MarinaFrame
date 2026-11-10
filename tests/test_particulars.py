"""Printed particulars: reads, sources, abstentions, conflicts and intake/export use."""
import json
from types import SimpleNamespace

import fitz
import numpy as np
import pytest

from vessel_reconstruction import particulars as reader
from vessel_reconstruction.drawing_set import analyse_page
from vessel_reconstruction.exports.hydrostatics import design_draft
from vessel_reconstruction.exports.identity import known_particulars
from vessel_reconstruction import intake


def readings(text, sheet="p1"):
    return reader.read_text(text, source={"sheet": sheet, "text_source": "pdf_text", "bbox_space": "page_px"})


def page(text, sheet="p1", skip=False):
    return {"page_id": sheet, "skip": skip, "sheet": {"particulars": readings(text, sheet)}}


@pytest.mark.parametrize("text,field,value", [
    ("LENGTH OVER ALL\n36.25\n[m]", "loa_m", 36.25),
    ("LENGTH BETV. PERP.\n33.90\n[m]", "lpp_m", 33.9),
    ("L.P.P. = 12000 mm", "lpp_m", 12),
    ("LBP: 12,5 m", "lpp_m", 12.5),
    ('LOA 100\'-6 1/2"', "loa_m", 30.6451),
    ("Beam moulded = 9.60 [m]", "beam_m", 9.6),
    ("Moulded depth: 420 cm", "depth_m", 4.2),
    ("Design draught 2.50 m", "draft_m", 2.5),
    ("Draught (design): 2500 mm", "draft_m", 2.5),
    ("Scantling draft = 2.787 m", "scantling_draft_m", 2.787),
    ("Displacement: 1,250.5 tonnes", "displacement_t", 1250.5),
    ("Year built: 2006", "built_year", 2006),
    ("Builder: Example Shipyard Ltd.", "builder", "Example Shipyard Ltd."),
    ("IMO No. 9074729", "imo", "9074729"),
])
def test_printed_field(text, field, value):
    found = readings(text)
    assert len(found) == 1
    assert found[0]["field"] == field
    assert found[0]["value"] == (pytest.approx(value) if isinstance(value, float) else value)
    assert found[0]["status"] == "read"
    assert found[0]["source"]["sheet"] == "p1"
    assert found[0]["source"]["text"] == text


@pytest.mark.parametrize("text", [
    "Frame 24 100 mm; SCALE 1:50; DWL 3", "Design draft: unknown 4 m",
    "Displacement 600 m3", "Deadweight 300 t", "Draught max. loaded 2.787 m",
    "DEPTH TO A-DECK 6.687 m", 'LOA 10\'-15"', "Built: 123", "Beam 0 m",
])
def test_no_invention(text):
    assert readings(text) == []


def test_conflicts_keep_both_sources_and_typed_value_wins():
    pages = [page("Beam 8 m\nDesign draft 2 m"), page("Beam 9 m", "p2"), page("Beam 8 m", "p3")]
    result = reader.resolve(pages, {"beam_m": 10})
    assert result["values"] == {"beam_m": 10, "draft_m": 2}
    assert result["fields"]["beam_m"]["status"] == "typed"
    assert len(result["fields"]["beam_m"]["readings"]) == 3
    assert result["check_items"][0]["code"] == "particulars_conflict"
    unresolved = reader.resolve(pages)
    assert "beam_m" not in unresolved["values"]
    assert unresolved["fields"]["beam_m"]["status"] == "conflict"
    assert reader.resolve([pages[0], {**pages[1], "skip": True}])["values"]["beam_m"] == 8


def test_pdf_text_and_ocr_words_keep_value_boxes(tmp_path):
    path = tmp_path / "sheet.pdf"
    with fitz.open() as doc:
        p = doc.new_page(width=500, height=200)
        p.insert_text((20, 40), "LOA 36.25 m")
        doc.save(path)
    gray = np.full((200, 500), 255, np.uint8)
    result = analyse_page(path=path, page_index=0, gray=gray,
                          info={"full_px": [1000, 400]}, file_name=path.name, ocr=lambda g: "")
    value = result["particulars"][0]
    assert value["value"] == 36.25
    assert value["source"]["bbox_space"] == "page_px"
    box = value["source"]["bbox"]
    assert box[0] == 40 and box[1] < 80 < box[3] and box[2] > box[0]
    words = [{"text": word, "bbox": [i * 50, 10, i * 50 + 45, 30], "line": [1, 1, 1]}
             for i, word in enumerate(["Design", "draft", "2.5", "m"])]
    found = reader.read_words(words, source={"text_source": "ocr"})
    assert found[0]["source"]["bbox"] == [0, 10, 195, 30]


def test_intake_writes_read_draft_but_typed_draft_wins(tmp_path):
    source = tmp_path / "sheet.pdf"
    with fitz.open() as doc:
        p = doc.new_page()
        p.insert_text((20, 40), "LOA 20 m; Design draft 2.5 m; Scantling draft 3 m")
        doc.save(source)
    preview = intake.prepare([source], tmp_path / "preview", render_dpi=40)
    assert preview["set"]["particulars"]["values"]["draft_m"] == 2.5
    intake.write_spec(preview, tmp_path / "run")
    spec = json.loads((tmp_path / "run/spec.json").read_text())
    assert spec["design_draft_m"] == 2.5
    assert design_draft(spec, 10, 0, None) == (2.5, "read from drawing: p1")
    assert design_draft(spec, 10, 0, 4) == (4, "given for this export")
    domain = tmp_path / "domain"
    (domain / "input").mkdir(parents=True)
    (domain / "input/intake.json").write_bytes((tmp_path / "run/intake.json").read_bytes())
    known = known_particulars(SimpleNamespace(spec=spec), domain, {})
    assert known["draft_m"] == 2.5 and known["scantling_draft_m"] == 3
    assert known["sources"]["draft_m"]["status"] == "read"
    preview["particulars"] = {"draft_m": 2.8, "loa_m": 21}
    intake.write_spec(preview, tmp_path / "typed")
    typed = json.loads((tmp_path / "typed/spec.json").read_text())
    assert typed["design_draft_m"] == 2.8 and typed["constraints"]["length_m"] == 21
    assert typed["design_draft_source"]["status"] == "typed"


def test_negative_dimensions_and_decimal_comma_mass():
    assert readings("Beam: -4 m") == []
    assert readings("Displacement 1,25 t")[0]["value"] == 1.25


def test_ocr_tsv_positions_are_rescaled_to_input_pixels(monkeypatch):
    from vessel_reconstruction import sheet_types
    monkeypatch.setattr(sheet_types, "ocr_available", lambda: True)
    words = []
    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    tsv += "5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t90\tBeam\n"
    sheet_types.ocr_read(np.full((200, 400), 255, np.uint8), side=200, words_out=words,
                         runner=lambda *a, **kw: SimpleNamespace(returncode=0, stdout=tsv))
    assert words == [{"text": "Beam", "line": ["1", "1", "1", "1"], "bbox": [20, 40, 80, 60]}]


def test_strips_keep_their_full_page_boxes(monkeypatch):
    from vessel_reconstruction import sheet_scale
    from vessel_reconstruction import sheet_types
    def ocr(gray, **kwargs):
        out = kwargs.get("words_out")
        if out is not None:
            out.extend([{"text": word, "bbox": [i * 30, 0, (i + 1) * 30, 10], "line": [1, 1, 1]}
                        for i, word in enumerate(["Beam", "8", "m"])])
        return "Beam 8 m", ""
    monkeypatch.setattr(sheet_types, "ocr_read", ocr)
    words = []
    sheet_scale.strip_text(np.full((100, 200), 255, np.uint8), words_out=words)
    assert words[0]["bbox"][1] == 82
    assert words[3]["bbox"][0] == 160


def test_conflicting_drawings_do_not_fall_back_to_a_stale_spec_draft(tmp_path):
    domain = tmp_path / "domain"
    (domain / "input").mkdir(parents=True)
    record = {"particulars": {}, "pages": [page("Design draft 2 m"), page("Design draft 3 m", "p2")]}
    (domain / "input/intake.json").write_text(json.dumps(record))
    known = known_particulars(SimpleNamespace(spec={"design_draft_m": 2}), domain, {})
    assert "draft_m" not in known
    assert known["check_items"][0]["field"] == "draft_m"


def test_export_uses_typed_draft_before_an_old_spec(tmp_path):
    from test_exports import make_box_task
    from vessel_reconstruction.exports.source import load_build
    from vessel_reconstruction.exports.package import compute_hydrostatics
    task = make_box_task(tmp_path, with_cad=False)
    (task / "domain/input").mkdir()
    (task / "domain/input/intake.json").write_text(json.dumps({"particulars": {"draft_m": 2}}))
    build = load_build(task, "r1")
    hydro, error = compute_hydrostatics(build, None)
    assert error is None and hydro.draft_m == 2
    assert hydro.draft_basis == "specification design_draft_m"


@pytest.mark.parametrize("text,field,value", [
    ("LOA [m]: 36.25", "loa_m", 36.25),
    ("Depth (mm) 4200", "depth_m", 4.2),
    ("Built in 2006", "built_year", 2006),
])
def test_units_in_heading_and_built_note(text, field, value):
    assert readings(text)[0]["field"] == field
    assert readings(text)[0]["value"] == value


def test_build_year_in_another_vessels_narrative_is_not_a_particular():
    assert readings("Other vessel Wawona (HAER No. WA-14), which he built in 1897.") == []


def test_leading_decimal_is_not_read_as_a_whole_metre():
    assert readings("Design draft .5 m")[0]["value"] == 0.5


def test_rotated_pdf_boxes_follow_the_rendered_page(tmp_path):
    path = tmp_path / "rotated.pdf"
    with fitz.open() as document:
        p = document.new_page(width=500, height=200)
        p.insert_text((20, 40), "Beam 8 m")
        p.set_rotation(90)
        document.save(path)
    words = reader.pdf_words(path, 0, [200, 500])
    box = reader.read_words(words, source={})[0]["source"]["bbox"]
    assert 150 < box[0] < box[2] < 180
    assert box[1] == 20 and box[3] < 100


def test_export_labels_guess_when_printed_drafts_conflict(tmp_path):
    from test_exports import make_box_task
    from vessel_reconstruction.exports.source import load_build
    from vessel_reconstruction.exports.package import compute_hydrostatics
    task = make_box_task(tmp_path, with_cad=False)
    (task / "domain/input").mkdir()
    record = {"pages": [page("Design draft 2 m"), page("Design draft 4 m", "p2")]}
    (task / "domain/input/intake.json").write_text(json.dumps(record))
    hydro, error = compute_hydrostatics(load_build(task, "r1"), None)
    assert error is None and hydro.draft_basis.startswith("assumed:")


def test_metric_and_feet_readings_respect_printed_precision():
    from vessel_reconstruction import particulars
    def page(text, page_id):
        return {"page_id": page_id, "sheet": {"particulars": particulars.read_text(text, source={})}}
    feet = page("LOA 100 ft", "feet")
    same = page("LOA 30.5 m", "same")
    different = page("LOA 32.00 m", "different")
    assert particulars.resolve([feet, same])["fields"]["loa_m"]["status"] == "read"
    assert particulars.resolve([feet, different])["fields"]["loa_m"]["status"] == "conflict"
