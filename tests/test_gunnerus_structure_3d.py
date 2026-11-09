"""Gunnerus 3D structure (docs/STRUCTURE_V2.md section 8): frame labels, level runs, and the drawing
reader on the licensed sheets (skipped when they are not on this machine)."""
from pathlib import Path

import pytest

from benchmarks.gunnerus import structure_3d, structure_3d_reading
from benchmarks.gunnerus.whole_vessel_internals import frame_index


def sources_dir() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "work" / "sources" / "gunnerus"
        if (candidate / structure_3d_reading.MIDSHIP).is_file():
            return candidate
    return None


def test_frame_label_inverts_frame_index():
    for label in ["0", "12", "27", "A", "E", "J", "28", "30", "45"]:
        assert structure_3d.frame_label(frame_index(label)) == label


def test_level_runs_share_the_step_frame():
    stations = [structure_3d.station(i) for i in range(30, 36)]  # frames 30 to 35 (x 15.0 to 17.5)
    runs = structure_3d.level_runs(stations, lambda x: 1075 if x < 16.5 else 1250)
    assert [[s.x for s in run] for run in runs] == [[15.0, 15.5, 16.0, 16.5], [16.5, 17.0, 17.5]]


@pytest.mark.skipif(sources_dir() is None, reason="licensed Gunnerus drawings not available")
def test_reader_finds_the_section_members_and_labels():
    reading = structure_3d_reading.read_all(sources_dir())
    section = reading.section_i
    assert section.db_girders_m == [-3.525, -1.875, 0.0, 1.875, 3.525]
    assert [g["y_m"] for g in section.deck_girders] == [-1.875, 1.875]
    assert section.floor_plate["mm"] == 8.0 and section.floor_stiffener_profile == "100x8"
    assert round(section.datums.z_m(section.datums.deck_y), 3) == 4.287
    assert reading.strakes.thickness_mm == [10.0, 8.0, 8.0, 7.0]
    assert reading.plan.deck_beam_profile == "HP140x8"
    assert reading.plan.girder_thickness[3525]["mm"] == 9.0
    assert reading.section_g.bulkhead_stiffener_profile == "HP 100x7"
