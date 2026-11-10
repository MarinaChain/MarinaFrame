"""Checks for the DSYHS adapter, without the downloaded data or CAD runtime."""
from zipfile import ZipFile

import pytest
import numpy as np


def test_half_hull_is_reflected_but_full_hull_is_not_duplicated():
    from scripts.check_dsyhs_hydrostatics import complete_hull

    half = np.array([[[0, 0, 0], [1, -1, 0], [0, -1, 1]]], dtype=float)
    full = complete_hull(half)
    assert len(full) == 2
    assert np.array_equal(full[1], half[0, ::-1] * [1, -1, 1])
    assert np.array_equal(complete_hull(full), full)


def test_spline_overshoot_past_the_centreline_is_still_a_half_hull():
    from scripts.check_dsyhs_hydrostatics import complete_hull

    half = np.array([[[0, 1e-5, 0], [1, -1, 0], [0, -1, 1]]], dtype=float)
    assert len(complete_hull(half)) == 2


def test_read_table_keeps_cached_numbers_and_missing_cells(tmp_path):
    from scripts.check_dsyhs_hydrostatics import read_table

    path = tmp_path / "table.xlsx"
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", f'<sst {ns}><si><t>Sysser</t></si><si><t>volc0</t></si></sst>')
        archive.writestr("xl/worksheets/sheet1.xml", f'''<worksheet {ns}><sheetData>
          <row><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
          <row><c r="A2"><v>1</v></c><c r="B2"><f>1/2</f><v>0.5</v></c></row>
          <row><c r="A3"><v>2</v></c></row></sheetData></worksheet>''')
    assert read_table(path) == [{"Sysser": 1.0, "volc0": 0.5}, {"Sysser": 2.0}]


def test_geometry_name_maps_each_overhang_without_substitution():
    from scripts.check_dsyhs_hydrostatics import geometry_name

    assert geometry_name(23, 1) == "IGS/SYSSER23_surface.igs"
    assert geometry_name(23, 0.5) == "IGS/SYSSER23_05_surface.igs"
    assert geometry_name(23, 0) == "IGS/SYSSER23_0_surface.igs"
    with pytest.raises(ValueError):
        geometry_name(23, 0.7)


def test_statistics_exclude_missing_references_and_zero_relative_errors():
    from scripts.check_dsyhs_hydrostatics import error_statistics

    result = error_statistics([{"printed": 0, "computed": 0.1}, {"printed": 2, "computed": 2.2},
                               {"printed": None, "computed": 3}])
    assert result["n"] == 2
    assert result["mean_absolute_error"] == pytest.approx(0.15)
    assert result["max_absolute_error"] == pytest.approx(0.2)
    assert result["relative_n"] == 1
    assert result["mean_absolute_error_percent"] == pytest.approx(10)
