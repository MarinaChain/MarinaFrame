"""scripts/add_run_sheets.py: sheets a later stage read are rendered into the run with a record
the desktop app reads (app/core/src/sources.rs ADDED_SHEETS_FILE)."""

import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import add_run_sheets  # noqa: E402
from web_demo_sheets import Render, SheetError  # noqa: E402


@pytest.fixture
def run(tmp_path, monkeypatch):
    task = tmp_path / "run"
    (task / "whole_vessel").mkdir(parents=True)
    (task / "state.json").write_text("{}")
    execution = {"result": {"components": [
        {"id": "tank_no_1", "provenance": {"outline": {"basis": 'label "No 1" (DXF box (100, 200, 600, 450))'}}},
        {"id": "deck", "provenance": {"deck_top": {"basis": "DXF box (1, 2, 3, 4)"}}},
    ]}}
    (task / "whole_vessel/execution.json").write_text(json.dumps(execution))
    sheets = tmp_path / "sheets"
    (sheets / "cjob").mkdir(parents=True)
    (sheets / "cjob/tank.dxf").write_bytes(b"tank sheet")
    (sheets / "ga.dxf").write_bytes(b"ga sheet")
    picture = tmp_path / "render.png"
    Image.new("L", (2000, 1000), 255).save(picture)
    # A 1000 x 500 unit drawing from (100, 200), rendered at 2 px per unit.
    monkeypatch.setattr(
        add_run_sheets, "render_dxf", lambda path, cache: Render(picture, 2000, 1000, (100.0, 200.0, 1100.0, 700.0))
    )
    return task, sheets


def listed(sheets, **change):
    def digest(name):
        return hashlib.sha256((sheets / name).read_bytes()).hexdigest()

    rows = [
        {"sheet": "ga.dxf", "sha256": digest("ga.dxf"), "role": "General arrangement"},
        {"sheet": "cjob/tank.dxf", "sha256": digest("cjob/tank.dxf"), "role": "Tank arrangement", "dxf_boxes_view": "plan"},
    ]
    rows[0].update(change)
    return rows


def test_sheets_are_rendered_into_the_run_with_part_boxes(run, tmp_path):
    task, sheets = run
    record = add_run_sheets.add_sheets(task, sheets, listed(sheets), tmp_path / "cache", 5)
    saved = json.loads((task / "sources/sheets.json").read_text())
    assert saved == record and saved["schema"] == "marinaframe.run-sheets.v1"
    ga, tank = saved["sheets"]
    assert (ga["name"], ga["role"], ga["width_px"], ga["height_px"]) == ("ga.dxf", "General arrangement", 2000, 1000)
    assert (task / ga["file"]).is_file() and ga["file"].startswith("sources/sheets/")
    assert "part_boxes" not in ga
    # Only a part whose outline names a DXF box gets a box, flipped to pixel rows.
    assert tank["part_boxes"] == {"view": "plan", "boxes": {"tank_no_1": [0.0, 500.0, 1000.0, 1000.0]}}
    # The run's own records are unchanged.
    assert "page_px" not in (task / "whole_vessel/execution.json").read_text()


def test_a_sheet_with_another_hash_is_refused(run, tmp_path):
    task, sheets = run
    with pytest.raises(SheetError, match="SHA-256"):
        add_run_sheets.add_sheets(task, sheets, listed(sheets, sha256="0" * 64), tmp_path / "cache", 5)
    assert not (task / "sources/sheets.json").exists()


def test_the_listed_sheets_come_from_the_selection_file():
    selection = Path(__file__).resolve().parent.parent / "scripts/web_demo_runs.json"
    names = [sheet["sheet"] for sheet in add_run_sheets.listed_sheets(selection, "gunnerus")]
    assert len(names) == 10 and "extended/CJOB/Tank Arrangement Rev0.dxf" in names
    with pytest.raises(SheetError):
        add_run_sheets.listed_sheets(selection, "sample-hull")
