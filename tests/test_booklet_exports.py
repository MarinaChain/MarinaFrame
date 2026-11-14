"""Booklet input reaches the report, package and the run's accuracy line."""
import csv
import io
import json
from zipfile import ZipFile

import pytest

from test_booklet_check import barge_values, booklet_data
from test_exports import make_box_task, pdf_text
from vessel_reconstruction.accuracy_summary import summarise
from vessel_reconstruction.exports import ExportError, export_draft
from vessel_reconstruction.exports.__main__ import main


def test_booklet_export_reaches_csv_manifest_zip_pdf_and_accuracy_line(tmp_path):
    task = make_box_task(tmp_path)
    source = tmp_path / "booklet.json"
    source.write_text(json.dumps(booklet_data([{"draft": 3, **barge_values(3)}, {"draft": 6, "volume": 1920}])))
    before = source.read_bytes()
    out = tmp_path / "out"
    manifest = export_draft(task, "r1", out, booklet=source)
    assert source.read_bytes() == before
    entry = next(e for e in manifest["files"] if e["role"] == "booklet_check")
    csv_text = (out / entry["file"]).read_text(encoding='utf-8')
    csv_rows = list(csv.reader(io.StringIO(csv_text)))
    start = next(i for i, row in enumerate(csv_rows) if row and row[0] == "row")
    rows = [dict(zip(csv_rows[start], row)) for row in csv_rows[start + 1:]]
    assert len(rows) == 18
    assert [r["label"] for r in rows].count("within tolerance") == 9
    assert [r["label"] for r in rows].count("not comparable") == 9
    assert all(r["reason"] for r in rows if r["label"] == "not comparable")
    assert "0.05" in csv_text and "t*m/cm" in csv_text
    assert manifest["booklet_check"]["comparable"] == 9
    assert manifest["engineering_approved"] is False
    with ZipFile(out / manifest["package"]["file"]) as archive:
        assert archive.read(entry["file"]).decode() == csv_text
    flat = " ".join(pdf_text(next(out.glob("*_report.pdf"))).split())
    assert "Booklet check" in flat and "Box booklet" in flat
    assert "booklet check: 9 of 9 within tolerance" in flat and "9 not comparable" in flat
    assert "Density 1.025 t/m3" in flat and "even_keel" in flat
    assert "booklet comparison is secondary evidence only" in flat
    assert "(displacement, LCB, KMT) can agree while the local hull shape is wrong" in flat
    assert "primary accuracy number remains the section-shape error at withheld stations" in flat


def test_trimmed_booklet_summary_does_not_imply_a_pass(tmp_path):
    from vessel_reconstruction.booklet_check import parse_booklet

    source = parse_booklet({**booklet_data(), "trim": "trimmed"})
    out = tmp_path / "out"
    manifest = export_draft(make_box_task(tmp_path), "r1", out, booklet=source)
    assert manifest["booklet_check"]["comparable"] == 0
    flat = " ".join(pdf_text(next(out.glob("*_report.pdf"))).split())
    assert "no values comparable" in flat


def test_table_fallback_is_named_in_csv_and_pdf(tmp_path):
    from vessel_reconstruction.booklet_check import parse_booklet

    out = tmp_path / "out"
    export_draft(make_box_task(tmp_path, with_cad=False), "r1", out,
                 booklet=parse_booklet(booklet_data([{"draft": 3, "volume": 960}])))
    assert "table: trapezoid" in next(out.glob("*_booklet_check.csv")).read_text()
    assert "Table method" in pdf_text(next(out.glob("*_report.pdf")))


def test_cli_booklet_option_and_invalid_input_error(tmp_path, capsys):
    task = make_box_task(tmp_path)
    source = tmp_path / "booklet.json"
    source.write_text(json.dumps(booklet_data([{"draft": 3, "volume": 960}])))
    args = ["--task", str(task), "--revision", "r1", "--out", str(tmp_path / "out"), "--booklet", str(source)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["booklet_check"]["within"] == 1
    source.write_text("{bad json")
    assert main(args) == 2
    assert "booklet" in json.loads(capsys.readouterr().err)["error"].lower()
    source.unlink()
    assert main(args) == 2
    assert "booklet" in json.loads(capsys.readouterr().err)["error"].lower()


def test_invalid_booklet_api_fails_before_writing_outputs(tmp_path):
    task = make_box_task(tmp_path)
    source = tmp_path / "bad.json"
    source.write_text("{}")
    out = tmp_path / "out"
    with pytest.raises(ExportError, match="booklet"):
        export_draft(task, "r1", out, booklet=source)
    assert not out.exists()


def test_accuracy_hook_uses_comparable_cells_and_keeps_unavailable_count():
    facts = {"hull": {"booklet_check": {"within": 7, "outside": 2, "comparable": 9, "not_comparable": 18}}}
    result = summarise(facts)["hull"]
    assert "booklet check: 7 of 9 within tolerance" in result.line
    assert "18 not comparable" in result.line and result.caution
    facts["hull"]["booklet_check"] = {"within": 0, "outside": 0, "comparable": 0, "not_comparable": 27}
    assert "no values comparable" in summarise(facts)["hull"].line


def test_csv_keeps_multiline_title_in_a_single_safe_cell(tmp_path):
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet, write_comparison_csv
    from test_booklet_check import box_mesh

    check = compare_booklet(parse_booklet({**booklet_data(), "title": "=SUM(1)\nunsafe"}), triangles=box_mesh())
    path = tmp_path / "check.csv"
    write_comparison_csv(check, path)
    rows = list(csv.reader(io.StringIO(path.read_text())))
    assert [r for r in rows if r and "Booklet:" in r[0]] == [["# Booklet: =SUM(1)\nunsafe"]]
    assert len([r for r in rows if r and r[0] in {"1", "2", "3"}]) == 27
