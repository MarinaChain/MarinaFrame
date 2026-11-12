"""Synthetic tests for open, inconsistently oriented public hull surfaces."""
import numpy as np
import pytest
from vessel_reconstruction import performance_geometry


def box_surface():
    v = np.array([(0,-10,0),(100,-10,0),(100,10,0),(0,10,0),
                  (0,-10,10),(100,-10,10),(100,10,10),(0,10,10)],float)
    # Open at deck, includes side/bottom/aft/fore shell; mixed orientation.
    f = np.array([(0,2,1),(0,3,2),(0,1,5),(0,5,4),(1,2,6),(1,6,5),
                  (2,3,7),(2,7,6),(3,0,4),(3,4,7)])
    mesh = v[f]
    mesh[::2] = mesh[::2,::-1]
    return mesh


def test_surface_particulars_do_not_depend_on_face_winding():
    result = performance_geometry.surface_particulars(
        box_surface(), waterline_z_m=6, lpp_m=100, aft_perpendicular_x_m=0,
        forward_x_sign=1, half_hull=False, station_count=101, height_count=101)
    assert result["volume_m3"] == pytest.approx(12000, rel=1e-5)
    assert result["wetted_surface_m2"] == pytest.approx(3440)
    assert result["cm"] == pytest.approx(1)
    assert result["cwp"] == pytest.approx(1)
    assert result["transom_area_m2"] == pytest.approx(120)
    assert result["lcb_percent_lwl_forward"] == pytest.approx(0, abs=1e-5)
    assert result["geometry_warnings"]


def test_surface_lcb_uses_waterline_midpoint_not_perpendicular_midpoint():
    result = performance_geometry.surface_particulars(
        box_surface(), waterline_z_m=6, lpp_m=80, aft_perpendicular_x_m=0,
        forward_x_sign=1, half_hull=False, station_count=101, height_count=101)
    assert result["lcb_percent_lwl_forward"] == pytest.approx(0,abs=1e-5)


def test_surface_particulars_stated_half_hull_doubles_only_surface_area():
    mesh = box_surface()
    # Keep nonnegative-side half of a symmetric box by changing negative y to 0.
    mesh[:,:,1] = np.maximum(mesh[:,:,1],0)
    # Remove artificial centreline panels: they are not wetted shell.
    mesh = mesh[~np.all(mesh[:,:,1] == 0,axis=1)]
    result = performance_geometry.surface_particulars(
        mesh, waterline_z_m=6, lpp_m=100, aft_perpendicular_x_m=0,
        forward_x_sign=1, half_hull=True, station_count=101, height_count=101)
    assert result["volume_m3"] == pytest.approx(12000,rel=1e-5)
    assert result["wetted_surface_m2"] == pytest.approx(3440)


@pytest.mark.parametrize("changes", [{"station_count": 2},{"height_count": 2},
    {"forward_x_sign": 0},{"lpp_m": 0},{"waterline_z_m": -1}])
def test_surface_particulars_reject_bad_sampling_basis(changes):
    args = dict(waterline_z_m=6,lpp_m=100,aft_perpendicular_x_m=0,
                forward_x_sign=1,half_hull=False,station_count=101,height_count=101)
    args.update(changes)
    with pytest.raises(ValueError):
        performance_geometry.surface_particulars(box_surface(),**args)
