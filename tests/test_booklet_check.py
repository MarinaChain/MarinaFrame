"""Booklet comparisons against closed-form barge and Wigley hydrostatics."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from test_exports import box_section, prism


UNITS = {"draft": "m", "volume": "m3", "displacement": "t", "lcb": "m", "vcb": "m", "kmt": "m",
         "waterplane_area": "m2", "lcf": "m", "tpc": "t/cm", "mct": "t*m/cm"}


def barge_values(draft, density=1.025):
    length, beam = 40, 8
    volume = length * beam * draft
    return {"volume": volume, "displacement": volume * density, "lcb": length / 2, "vcb": draft / 2,
            "kmt": draft / 2 + length * beam**3 / (12 * volume), "waterplane_area": length * beam,
            "lcf": length / 2, "tpc": density * length * beam / 100,
            "mct": density * beam * length**3 / 12 / (100 * length)}


def booklet_data(rows=None):
    return {"schema_version": 1, "title": "Box booklet", "trim": "even_keel",
            "density": {"value": 1.025, "unit": "t/m3"}, "units": dict(UNITS),
            "datum": {"x_origin_m": 0, "x_direction": 1, "z_origin_m": 0},
            "mct_basis": "hydrostatic", "trim_length_m": 40,
            "rows": rows if rows is not None else [{"draft": d, **barge_values(d)} for d in (1, 3, 5)]}


def box_mesh():
    return prism([(0, 0), (4, 0), (4, 5), (0, 5)], 40)


@pytest.mark.parametrize("method", ["mesh", "table"])
def test_barge_all_quantities_multiple_drafts_and_top_boundary(method):
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    geometry = {"triangles": box_mesh()} if method == "mesh" else {
        "sections": [box_section(f"s{i}", x, "traced") for i, x in enumerate(np.linspace(0, 40, 101))]}
    check = compare_booklet(parse_booklet(booklet_data()), **geometry)
    assert check.summary == {"within": 27, "outside": 0, "not_comparable": 0, "comparable": 27, "total": 27}
    for cell in check.comparisons:
        assert cell.computed == pytest.approx(cell.printed, rel=0.0003, abs=1e-9)
        assert cell.label == "within tolerance"
        assert cell.method.startswith(method)


def wigley_values(draft, length=40, beam=8, depth=5, density=1.025):
    waterline_factor = 2 * draft / depth - (draft / depth)**2
    volume = 2 * length * beam / 3 * (draft**2 / depth - draft**3 / (3 * depth**2))
    vcb = (2 * draft**3 / (3 * depth) - draft**4 / (4 * depth**2)) / (
        draft**2 / depth - draft**3 / (3 * depth**2))
    awp = 2 * length * beam / 3 * waterline_factor
    inertia_t = 4 * length * beam**3 / 105 * waterline_factor**3
    inertia_l = beam * length**3 / 30 * waterline_factor
    return {"volume": volume, "displacement": density * volume, "lcb": length / 2, "vcb": vcb,
            "kmt": vcb + inertia_t / volume, "waterplane_area": awp, "lcf": length / 2,
            "tpc": density * awp / 100, "mct": density * inertia_l / (100 * length)}


def wigley_geometry():
    """Wigley canoe up to z=5, extended vertically to z=6 so every draft cuts it."""
    xs = np.linspace(0, 40, 121)
    zs = np.r_[np.linspace(0, 5, 81), 6]
    sections, side_vertices = [], []
    for x in xs:
        widths = 4 * (1 - (2 * x / 40 - 1)**2) * (1 - ((np.minimum(zs, 5) - 5) / 5)**2)
        sections.append({"id": str(x), "x_m": x, "points_yz_m": [[0, 0], *zip(widths, zs), [0, 6]]})
        side_vertices.append([[x, y, z] for y, z in zip(widths, zs)])
    vertices = np.array(side_vertices)
    triangles = []
    for i in range(len(xs) - 1):
        for j in range(len(zs) - 1):
            a, b, c, d = vertices[i, j], vertices[i + 1, j], vertices[i + 1, j + 1], vertices[i, j + 1]
            triangles.extend([[a, b, c], [a, c, d]])
        # Close the deck between the two half hulls.
        a, b = vertices[i, -1].copy(), vertices[i + 1, -1].copy()
        c, d = b * [1, -1, 1], a * [1, -1, 1]
        triangles.extend([[a, b, c], [a, c, d]])
    half = np.array(triangles)
    # Only side triangles need reflection; reflecting the deck would duplicate it.
    sides = np.array([t for t in triangles if not all(p[2] == 6 for p in t)])
    return np.concatenate([half, sides[:, ::-1] * [1, -1, 1]]), sections


@pytest.mark.parametrize("method", ["mesh", "table"])
def test_wigley_against_exact_integrals_at_printed_drafts(method):
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    mesh, sections = wigley_geometry()
    data = booklet_data([{"draft": d, **wigley_values(d)} for d in (2.5, 5)])
    geometry = {"triangles": mesh} if method == "mesh" else {"sections": sections}
    check = compare_booklet(parse_booklet(data), **geometry)
    assert check.summary["within"] == 18
    for cell in check.comparisons:
        assert cell.computed == pytest.approx(cell.printed, rel=0.001)


def test_datum_conversion_and_density_units():
    from vessel_reconstruction.booklet_check import compare_booklet, load_booklet

    data = booklet_data([{"draft": 3000, "volume": 960, "displacement": 984, "lcb": 4, "lcf": 4,
                          "vcb": 1.5, "kmt": barge_values(3)["kmt"]}])
    data["units"]["draft"] = "mm"
    data["density"] = {"value": 1025, "unit": "kg/m3"}
    data["datum"] = {"x_origin_m": 124, "x_direction": -1, "z_origin_m": 7}
    mesh = box_mesh() + [100, 0, 7]
    check = compare_booklet(load_booklet(json.dumps(data)), triangles=mesh)
    assert check.summary["within"] == 6
    assert check.comparisons[0].waterline_z_m == 10


def test_range_missing_trim_and_zero_reference_are_explicit():
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    data = booklet_data([{"draft": d, "volume": 0, "lcb": 20} for d in (-1, 0, 3, 6)])
    check = compare_booklet(parse_booklet(data), triangles=box_mesh())
    assert len(check.comparisons) == 36
    assert check.summary == {"within": 1, "outside": 1, "not_comparable": 34, "comparable": 2, "total": 36}
    volume = next(c for c in check.comparisons if c.draft_m == 3 and c.quantity == "volume")
    assert volume.error == 960 and volume.relative_error_percent is None
    assert volume.tolerance == 0 and volume.label == "outside tolerance"
    for trim in ("trimmed", "unknown"):
        data["trim"] = trim
        check = compare_booklet(parse_booklet(data), triangles=box_mesh())
        assert check.summary["comparable"] == 0
        assert all(c.label == "not comparable" for c in check.comparisons)


@pytest.mark.parametrize("extra", [{"trim_m": 0.1}, {"heel_deg": 10}])
def test_even_keel_label_does_not_override_nonzero_trim_or_heel(extra):
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    data = {**booklet_data(), **extra}
    check = compare_booklet(parse_booklet(data), triangles=box_mesh())
    assert check.summary["comparable"] == 0


def test_mct_requires_explicit_basis_and_trim_length():
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    for change in ({"mct_basis": "stability"}, {"mct_basis": "unknown"}, {"trim_length_m": None}):
        check = compare_booklet(parse_booklet({**booklet_data(), **change}), triangles=box_mesh())
        assert check.summary["within"] == 24
        assert all(c.label == "not comparable" and c.reason for c in check.comparisons if c.quantity == "mct")


@pytest.mark.parametrize("field,value", [("volume", float("nan")), ("draft", float("inf")), ("lcb", True),
                                        ("waterplane_arrea", 123)])
def test_invalid_row_values_and_typo_are_rejected(field, value):
    from vessel_reconstruction.booklet_check import parse_booklet

    data = booklet_data([{"draft": 3, field: value}])
    with pytest.raises(ValueError):
        parse_booklet(data)


def test_unknown_units_and_missing_required_metadata_are_rejected():
    from vessel_reconstruction.booklet_check import parse_booklet

    for field in ("units", "datum", "trim", "density"):
        data = booklet_data()
        del data[field]
        with pytest.raises(ValueError):
            parse_booklet(data)
    data = booklet_data()
    data["units"]["volume"] = "gallons"
    with pytest.raises(ValueError, match="unit"):
        parse_booklet(data)


def test_tolerance_floor_length_rule_and_exact_limit():
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    data = booklet_data([{"draft": 3, "lcb": 20.5, "lcf": 20.5001, "kmt": barge_values(3)["kmt"] + .05}])
    check = compare_booklet(parse_booklet(data), triangles=box_mesh())
    cells = {c.quantity: c for c in check.comparisons}
    assert cells["lcb"].label == "within tolerance"
    assert cells["lcf"].label == "outside tolerance"
    assert cells["kmt"].label == "within tolerance"
    assert cells["kmt"].tolerance == .05


def test_missing_values_are_null_not_zero_and_input_is_not_changed():
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    data = booklet_data([{"draft": 3, "volume": None}])
    before = copy.deepcopy(data)
    check = compare_booklet(parse_booklet(data), triangles=box_mesh())
    assert check.summary["comparable"] == 0
    assert all(c.printed is None for c in check.comparisons)
    assert json.loads(json.dumps(check.as_dict(), allow_nan=False))["summary"]["not_comparable"] == 9
    assert data == before


def test_example_booklet_is_an_exact_box_data_fixture():
    from vessel_reconstruction.booklet_check import compare_booklet, load_booklet

    source = Path(__file__).parents[1] / "examples" / "booklet_box.json"
    check = compare_booklet(load_booklet(source), triangles=box_mesh())
    assert check.summary["within"] == 27


def test_alternate_units_convert_to_the_same_answers():
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    values = barge_values(3)
    values.update({"volume": values["volume"] / .3048**3, "displacement": 984000,
                   "waterplane_area": 320 / .3048**2, "lcb": 20 / .3048,
                   "tpc": 3280, "mct": values["mct"] * 9.80665})
    data = booklet_data([{"draft": 3 / .3048, **values}])
    data["units"].update({"draft": "ft", "volume": "ft3", "displacement": "kg", "waterplane_area": "ft2",
                          "lcb": "ft", "tpc": "kg/cm", "mct": "kN*m/cm"})
    assert compare_booklet(parse_booklet(data), triangles=box_mesh()).summary["within"] == 9


def test_centres_use_length_tolerance_on_long_hulls():
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    data = booklet_data([{"draft": 3, "lcb": 101.9, "lcf": 102.1}])
    check = compare_booklet(parse_booklet(data), triangles=box_mesh() * [5, 1, 1])
    cells = {c.quantity: c for c in check.comparisons}
    assert cells["lcb"].tolerance == 2
    assert cells["lcb"].label == "within tolerance"
    assert cells["lcf"].label == "outside tolerance"


def test_failed_calculation_keeps_every_cell_and_reason():
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    check = compare_booklet(parse_booklet(booklet_data()), sections=[box_section("only", 0, "traced")])
    assert check.summary["not_comparable"] == 27
    assert all("needs at least two stations" in c.reason for c in check.comparisons)
    assert all(c.computed is None for c in check.comparisons)


def test_repeated_printed_drafts_are_not_deduplicated():
    from vessel_reconstruction.booklet_check import compare_booklet, parse_booklet

    check = compare_booklet(parse_booklet(booklet_data([{"draft": 3, "volume": 960}] * 2)), triangles=box_mesh())
    assert len(check.comparisons) == 18
    assert {c.row for c in check.comparisons} == {1, 2}
    assert check.summary["within"] == 2
