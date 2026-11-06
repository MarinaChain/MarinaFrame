"""Tests for evaluation integrity, not assertions mirroring the hull implementation."""
from __future__ import annotations
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from benchmarks.evaluate import section_error_metrics, score_result, verify_manifest, threshold_baseline
from benchmarks.generate import generate_section_sheet, sha256


def rectangle_sections():
    return [{'id':f's{i}', 'x_m':float(i*4),
             'points_yz_m':[[2.0,float(z)] for z in np.linspace(0,3,65)]}
            for i in range(3)]


def render_case(tmp_path):
    return generate_section_sheet(rectangle_sections(),tmp_path/'inference',
        label_dir=tmp_path/'labels', reference_volume_m3=96,
        provenance={'secret_shape_parameters':[2.,3.,8.]})


def test_inference_inputs_exclude_answers_and_shape_parameters(tmp_path):
    receipt=render_case(tmp_path)
    spec=json.loads(Path(receipt['spec']).read_text())
    truth=json.loads(Path(receipt['ground_truth']).read_text())
    text=Path(receipt['spec']).read_text()
    assert set(p.name for p in (tmp_path/'inference').iterdir()) == {'drawing.png','spec.json'}
    assert Path(receipt['ground_truth']).parent == tmp_path/'labels'
    for forbidden in ['points_yz','reference_volume','secret_shape_parameters','render_seed']:
        assert forbidden not in text
    assert len(truth['sections'])==3
    assert truth['reference_volume_m3']==96
    assert len(spec['sections'])==3


def test_rerender_cannot_replace_frozen_images(tmp_path):
    receipt=render_case(tmp_path)
    original_hash=sha256(Path(receipt['image']))
    with pytest.raises(FileExistsError):
        render_case(tmp_path)
    assert sha256(Path(receipt['image']))==original_hash


def test_complete_wrong_geometry_fails_even_if_cad_is_valid():
    truth={'sections':rectangle_sections(),'beam_m':4.,'reference_volume_m3':96.}
    wrong=copy.deepcopy(truth['sections'])
    for section in wrong:
        for p in section['points_yz_m']:p[0]*=1.2
    result={'status':'review_required','sections':wrong,
        'metrics':{'cad_valid':True,'solid_count':1,'volume_m3':115.2}}
    score=score_result(result,truth,expected_outcome='reconstruct',
        gate={'maximum_relative_volume_error':.03,'maximum_rms_section_error_over_beam':.01})
    assert not score['passed']
    assert score['relative_volume_error']==pytest.approx(.2)
    assert score['rms_section_error_over_beam']==pytest.approx(.1)


def test_missing_station_or_vertical_interval_cannot_be_ignored():
    truth={'sections':rectangle_sections(),'beam_m':4.}
    missing=section_error_metrics(truth['sections'][:-1],truth)
    assert not missing['complete']
    assert missing['missing_section_ids']==['s2']
    cropped=copy.deepcopy(truth['sections'])
    cropped[1]['points_yz_m']=cropped[1]['points_yz_m'][5:]
    result=section_error_metrics(cropped,truth)
    assert not result['complete']
    assert result['missing_section_ids']==['s1']


def test_block_with_published_exports_is_not_correct_abstention():
    score=score_result({'status':'blocked','exports':{'step':'model.step'}},{},
        expected_outcome='blocked',gate={})
    assert not score['passed']
    safe=score_result({'status':'blocked','gaps':[{'code':'missing_scale'}]},{},
        expected_outcome='blocked',gate={})
    assert safe['passed']


def test_changed_input_is_refused_by_manifest_verification(tmp_path):
    receipt=render_case(tmp_path)
    case={'case_id':'rect','spec':'inference/spec.json',
        'ground_truth':'labels/ground_truth.json',
        'spec_sha256':receipt['spec_sha256'],'image_sha256':receipt['image_sha256'],
        'ground_truth_sha256':sha256(Path(receipt['ground_truth']))}
    manifest=tmp_path/'suite_manifest.json'
    manifest.write_text(json.dumps({'cases':[case]}))
    (tmp_path/'suite_manifest.sha256').write_text(sha256(manifest))
    assert len(verify_manifest(tmp_path)['cases'])==1
    image=Path(receipt['image'])
    image.write_bytes(image.read_bytes()+b'alteration')
    with pytest.raises(ValueError,match='drawing hash mismatch'):
        verify_manifest(tmp_path)


def test_simple_baseline_uses_pixels_and_obeys_missing_scale(tmp_path):
    receipt=render_case(tmp_path)
    spec=json.loads(Path(receipt['spec']).read_text())
    baseline=threshold_baseline(spec,tmp_path/'inference')
    assert baseline['status']=='section_estimate'
    assert baseline['volume_m3']==pytest.approx(96,rel=.03)
    spec['sections'][1].pop('calibration')
    failed=threshold_baseline(spec,tmp_path/'inference')
    assert failed['status']=='blocked'
    assert failed['volume_m3'] is None


def test_empty_challenge_requires_no_image_to_baseline():
    result=threshold_baseline({'sections':[]},Path('/not-an-image-directory'))
    assert result['status']=='blocked'


def test_station_displacement_and_duplicate_predictions_cannot_pass():
    truth={'sections':rectangle_sections(),'beam_m':4.}
    shifted=copy.deepcopy(truth['sections'])
    shifted[1]['x_m']+=1.
    score=section_error_metrics(shifted,truth)
    assert not score['complete']
    assert score['position_mismatch_section_ids']==['s1']
    duplicated=copy.deepcopy(truth['sections'])+[copy.deepcopy(truth['sections'][1])]
    score=section_error_metrics(duplicated,truth)
    assert not score['complete']
    assert score['duplicate_prediction_ids']==['s1']


def test_evaluation_retains_pass_failure_and_timeout_in_every_artifact(tmp_path, monkeypatch):
    import benchmarks.evaluate as evaluation
    receipt=render_case(tmp_path)
    gates={'minimum_pass_fraction':.9,'maximum_relative_volume_error':.03,
           'maximum_rms_section_error_over_beam':.01}
    common={'category':'clean','spec':'inference/spec.json',
        'ground_truth':'labels/ground_truth.json','expected_outcome':'reconstruct',
        'spec_sha256':receipt['spec_sha256'],'image_sha256':receipt['image_sha256'],
        'ground_truth_sha256':sha256(Path(receipt['ground_truth']))}
    ids=['passing','blocked','timeout']
    manifest={'suite':'integrity-fixture','cases':[dict(common,case_id=i) for i in ids],
        'contract_sha256':'test-contract','contract':{'gates':{'clean':gates},'assistance':[]}}
    file=tmp_path/'suite_manifest.json';file.write_text(json.dumps(manifest))
    (tmp_path/'suite_manifest.sha256').write_text(sha256(file))
    def fake_inference(spec_path,output_path,**kwargs):
        assert (kwargs['code_root']/'vessel_reconstruction'/'pipeline.py').exists()
        state=output_path.name
        result={'status':'review_required' if state=='passing' else state,
                'sections':rectangle_sections() if state=='passing' else [],
                'metrics':{'volume_m3':96.,'cad_valid':True,'solid_count':1} if state=='passing' else {},
                'gaps':[] if state=='passing' else [{'kind':state,'message':'retained fixture failure'}]}
        return {'return_code':0 if state=='passing' else 2,'wall_seconds':.01,'result':result}
    monkeypatch.setattr(evaluation,'_run_inference',fake_inference)
    out=tmp_path/'results'
    report=evaluation.evaluate(tmp_path,out,jobs=2)
    checkpoint=[json.loads(line) for line in (out/'cases.jsonl').read_text().splitlines()]
    assert [r['case_id'] for r in checkpoint]==ids
    assert checkpoint==report['records']
    assert json.loads((out/'report.json').read_text())['records']==checkpoint
    assert report['groups']['clean']['attempted']==3
    assert report['groups']['clean']['passed']==1
    assert not report['all_predeclared_numeric_gates_met']
    assert (out/'cases.csv').read_text().count('\n')==4
    assert '| timeout | timeout | False |' in (out/'report.md').read_text()
    with pytest.raises(FileExistsError):
        evaluation.evaluate(tmp_path,out,jobs=2)
