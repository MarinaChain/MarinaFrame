import pytest


def test_frame_fit_recovers_scale_offset_and_axis_swap():
    from benchmarks.localisation.calibrate import fit_frame
    truth = [[10, 20], [50, 80], [90, 30], [20, 90], [80, 60]]
    answers = [[y / 2 + 3, x / 4 - 7] for x, y in truth]
    result = fit_frame(answers, truth)
    assert result['axis_order'] == 'yx'
    assert result['scale'] == pytest.approx([4, 2])
    assert result['offset'] == pytest.approx([28, -6])
    assert result['rms_px'] < 1e-10


def test_marks_are_inside_non_square_image():
    from benchmarks.localisation.calibrate import calibration_image
    image, marks = calibration_image(4096, 240)
    assert image.size == (4096, 240)
    assert set(marks) == {'A', 'B', 'C', 'D', 'E', 'F'}
    assert all(0 <= x < 4096 and 0 <= y < 240 for x, y in marks.values())
