"""Synthetic CAD diagnostics; no public or restricted geometry inputs."""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip('OCP')
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer


@pytest.fixture
def diagnostic():
    path = Path(__file__).parents[1] / 'scripts' / 'diagnose_cfd_surface.py'
    spec = importlib.util.spec_from_file_location('cfd_topology_diagnostic', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_closed_box_has_no_free_edges(diagnostic):
    result = diagnostic.diagnose_shape(BRepPrimAPI_MakeBox(1000, 2000, 3000).Shape())
    assert len(result['faces']) == 6
    assert result['free_edges'] == 0
    assert result['multiple_edges'] == 0
    assert result['shells_after_sewing'] == 1
    assert sum(face['area_full_scale_m2'] for face in result['faces']) == pytest.approx(22)
    assert all(face['valid'] for face in result['faces'])


def test_open_face_reports_boundary_endpoints_in_metres(diagnostic):
    explorer = TopExp_Explorer(BRepPrimAPI_MakeBox(1000, 2000, 3000).Shape(), TopAbs_FACE)
    result = diagnostic.diagnose_shape(explorer.Current())
    assert result['free_edges'] == 4
    assert len(result['free_edge_bounds_full_scale_m']) == 4
    for edge in result['free_edge_bounds_full_scale_m']:
        assert len(edge['endpoints']) == 2
        assert all(0 <= value <= 3 for point in edge['endpoints'] for value in point)
        assert edge['degenerate'] is False
