"""Power handoff must not treat effective power as engine brake power."""
import pytest
from vessel_reconstruction.holtrop import HoltropResistance
from vessel_reconstruction.weights_efficiency.engine import brake_power_from_holtrop


def test_holtrop_power_handoff_retains_efficiencies():
    resistance = HoltropResistance(1000, 100, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, .001, .001, 1e8, .1, "synthetic", ())
    result = brake_power_from_holtrop(resistance, thrust_deduction=.2, wake_fraction=.3,
                                     open_water_efficiency=.7, relative_rotative_efficiency=1,
                                     shaft_efficiency=.98, sources=("synthetic",))
    assert result.quantities["calm_brake_power_kw"].value == pytest.approx(100 / ((.8/.7)*.7*.98))
    assert "synthetic" in result.quantities["calm_brake_power_kw"].sources
