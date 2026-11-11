"""Host calibration of the raster tank-plan cases loads (no reader run)."""
from pathlib import Path

import pytest

from benchmarks.tanks.raster_cases import CASES



def _sources() -> Path | None:
    """The git-ignored work/sources folder of this checkout, or of the main checkout when the
    tests run in a worktree below it."""
    for folder in Path(__file__).resolve().parents:
        if (folder / 'work' / 'sources' / 'tanks-public').is_dir():
            return folder / 'work' / 'sources'
    return None


def test_huddell_case_is_three_sheets_with_scale_bars():
    sheets = CASES['arthur_m_huddell']
    assert [relative.split('(sheet_')[1][:1] for relative, _ in sheets] == ['7', '9', '8']
    roles = {}
    for _, spec in sheets:
        assert spec.scale_bar is not None and spec.frame_spacing_m is None
        assert spec.schedule is not None
        for view in spec.views:
            assert all(0.0 <= share <= 1.0 for share in view.window)
            assert view.window[0] < view.window[2] and view.window[1] < view.window[3]
            roles[view.name] = (view.kind, view.role if view.kind == 'plan' else None)
    assert roles == {'profile': ('profile', None), 'inner_bottom': ('plan', 'double_bottom'),
                     'deep_tank_top': ('plan', 'above'), 'upper_deck': ('plan', 'above'),
                     'second_deck': ('plan', 'above')}


@pytest.mark.parametrize('case', sorted(CASES))
def test_case_sheet_files_exist_when_sources_are_present(case):
    sources = _sources()
    if sources is None:
        pytest.skip('work/sources is not present')
    for relative, _ in CASES[case]:
        assert (sources / relative).exists(), relative
