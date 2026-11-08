"""Canonical W19a table is the source of W19b measurement projections."""
import numpy as np
from vessel_reconstruction.vessel_model import VesselTable, StationRow
from vessel_reconstruction.fit_feedback import measurement_table


def test_measurement_projection_keeps_station_geometry_and_cells():
    table = VesselTable([StationRow('s1', 1., [[0.,0.],[1.,1.],[2.,2.]], 'fitted'),
                         StationRow('s2', 2., [[0.,0.],[2.,1.],[3.,2.]], 'fitted')], [0.,1.,2.])
    projection = measurement_table(table)
    np.testing.assert_allclose(projection.hb_m,table.cells())
    assert projection.station_ids == ['s1','s2']
    assert projection.station_hb(0,1.) == 1.
