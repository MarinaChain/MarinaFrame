import copy

import pytest


def reading_from_truth(truth):
    return {'schema': 'marinaframe.ga_reading.v1', 'case_id': truth['case_id'],
            'engineering_approved': False, 'frames': truth['frames'],
            'particulars': {k: {'value': v, 'status': 'read'} for k, v in truth['dimensions'].items()},
            'spaces': [{'id': f'reader-{i}', 'kind': s['kind'], 'label': s['label'],
                        'extent': {f'{axis}_m': values[:] for axis, values in s['box_m'].items()}}
                       for i, s in enumerate(truth['spaces'])]}


def test_exact_frame_reading_scores_without_shared_ids():
    from benchmarks.ga_synthetic.generate import arrangements
    from benchmarks.ga_synthetic.score import score

    truth = arrangements()[0]
    reading = reading_from_truth(truth)
    for source, target in zip(truth['spaces'], reading['spaces']):
        del target['extent']['x_m']
        target['extent']['frames'] = source['frames']
    reading['spaces'].reverse()
    result = score(truth, reading)
    assert result['found_fraction'] == 1
    assert result['invented'] == [] and result['missing'] == []
    assert all(row['mean_absolute_face_error_m'] == 0 for row in result['by_kind'].values())
    assert len(result['matches']) == len(truth['spaces'])


def test_face_errors_omissions_inventions_and_guesses():
    from benchmarks.ga_synthetic.generate import arrangements
    from benchmarks.ga_synthetic.score import score

    truth = arrangements()[0]
    reading = reading_from_truth(truth)
    reading['spaces'][0]['extent']['x_m'][0] += 1
    reading['spaces'][0]['extent']['status'] = {'x': 'guessed'}
    omitted = reading['spaces'].pop(1)
    extra = copy.deepcopy(reading['spaces'][0])
    extra['id'] = 'extra'
    extra['extent']['x_m'] = [1000, 1002]
    reading['spaces'].append(extra)
    result = score(truth, reading)
    assert result['found_fraction'] == pytest.approx((len(truth['spaces']) - 1) / len(truth['spaces']))
    assert result['missing'] == [truth['spaces'][1]['id']]
    assert result['invented'] == ['extra']
    match = next(m for m in result['matches'] if m['truth_id'] == truth['spaces'][0]['id'])
    assert match['face_error_m'] == {'x_min': 1, 'x_max': 0, 'y_min': 0, 'y_max': 0, 'z_min': 0, 'z_max': 0}
    assert match['guessed_axes'] == ['x']
    assert omitted['kind'] == 'engine_room'


def test_duplicate_boxes_and_unmeasured_spaces_do_not_raise_recall():
    from benchmarks.ga_synthetic.generate import arrangements
    from benchmarks.ga_synthetic.score import score

    truth = arrangements()[0]
    reading = reading_from_truth(truth)
    duplicate = copy.deepcopy(reading['spaces'][0])
    duplicate['id'] = 'duplicate'
    reading['spaces'].append(duplicate)
    del reading['spaces'][1]['extent']
    result = score(truth, reading)
    assert len(result['invented']) == 1
    assert len(result['missing']) == 1
    assert result['unmeasured'] == ['reader-1']
    assert result['by_kind']['engine_room']['found_fraction'] == 0


def test_nonfinite_measurements_and_wrong_cases_are_rejected():
    from benchmarks.ga_synthetic.generate import arrangements
    from benchmarks.ga_synthetic.score import score

    truth = arrangements()[0]
    reading = reading_from_truth(truth)
    reading['case_id'] = 'wrong'
    with pytest.raises(ValueError, match='case_id'):
        score(truth, reading)
    reading['case_id'] = truth['case_id']
    reading['spaces'][0]['extent']['x_m'][0] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        score(truth, reading)
