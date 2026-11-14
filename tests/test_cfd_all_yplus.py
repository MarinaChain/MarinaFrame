import pytest
from vessel_reconstruction.cfd.all_yplus import all_yplus_field, convergence_stop


def test_frozen_wall_pairing_preserves_other_patches():
    text='boundaryField { inlet { type fixedValue; value uniform 1; } hull { type fixedValue; value uniform 0; } }'
    assert 'nutUSpaldingWallFunction' in all_yplus_field(text,'nut')
    assert 'kqRWallFunction' in all_yplus_field(text,'k')
    omega=all_yplus_field(text,'omega')
    assert 'blending binomial; n 2;' in omega
    assert 'inlet { type fixedValue; value uniform 1; }' in omega


def test_stop_requires_minimum_and_three_successive_comparisons():
    assert not convergence_stop([1.0]*499)['stop']
    assert convergence_stop([1.0]*500)['stop']
    assert not convergence_stop([1.0]*300+[1.2]*200)['stop']
    assert convergence_stop([1.0]*2000)['stop']
    with pytest.raises(ValueError):
        convergence_stop([float('nan')]*500)
