"""Public-source inspection must distinguish cap from real submerged skin."""
import importlib.util
from pathlib import Path

import cadquery as cq
import pytest


def inspector():
    path = Path(__file__).parents[1] / 'scripts' / 'inspect_kvdb_solid.py'
    spec = importlib.util.spec_from_file_location('kvdb_inspection', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clipped_box_excludes_only_waterplane_and_retains_transom():
    module = inspector()
    # Native z points down. Half of this 10 x 4 x 2 box is submerged.
    shape = cq.Solid.makeBox(10, 4, 2, cq.Vector(-4, -2, -2))
    result = module.inspect_shape(shape, scale=1, draft=1)
    assert result['volume_model_m3'] == pytest.approx(40)
    assert result['wetted_area_model_m2'] == pytest.approx(68)
    assert result['waterplane_area_model_m2'] == pytest.approx(40)
    assert result['immersed_aft_closure_area_model_m2'] == pytest.approx(4)
    assert sum(face['waterplane_cap'] for face in result['faces']) == 1


def test_aft_closure_candidate_need_not_be_axis_normal():
    module = inspector()
    shape = cq.Solid.makeBox(10, 4, 2, cq.Vector(-4, -2, -2))
    shape = shape.rotate((0, 0, 0), (0, 0, 1), 0.01)
    result = module.inspect_shape(shape, scale=1, draft=1)
    assert result['immersed_aft_closure_area_model_m2'] == pytest.approx(4)


def test_inspection_rejects_disconnected_solids():
    module = inspector()
    first = cq.Solid.makeBox(1, 1, 1)
    second = cq.Solid.makeBox(1, 1, 1, cq.Vector(3, 0, 0))
    with pytest.raises(ValueError, match='one valid'):
        module.inspect_shape(cq.Compound.makeCompound([first, second]), scale=1, draft=0.5)
