"""Boundary tests for annotation evidence, grouped splits and rights-aware exports."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from PIL import Image

from vessel_reconstruction import dataset_pipeline as dp

SCHEMA = Path(__file__).parents[1] / 'schemas' / 'annotation-v1.schema.json'


@pytest.fixture
def sample(tmp_path):
    path=tmp_path/'drawing.png'; Image.new('L',(40,30),255).save(path)
    h=dp.digest(path)
    doc={'schema_version':'marinaframe-annotation-1','annotation_id':'annotation-a','revision':1,
         'previous_revision_sha256':None,'created_utc':'2026-11-06T20:00:00Z',
         'source_item_id':'a','source_family':'family-a','vessel_id':'vessel-a',
         'asset':{'file':'drawing.png','sha256':h,'width_px':40,'height_px':30,
                  'coordinate_convention':'x_right_y_down_origin_top_left; bbox=[left,top,right,bottom] half-open'},
         'annotator':{'id':'assistant-a','role':'assistant'},'split':'development','gold_truth':False,
         'features':[{'id':'panel-a','kind':'panel','observation':'observed','review_status':'provisional',
                      'value':{'view':'body_plan'},'geometry':{'bbox_px':[1,2,39,28]},
                      'evidence':[{'asset_file':'drawing.png','asset_sha256':h,'inspection_id':'view-a',
                                   'description':'Test fixture only; not a source inspection claim.',
                                   'source_url':'https://example.org/drawing','bbox_px':[1,2,39,28]}],
                      'uncertainty':'Provisional fixture.','alternatives':[]}],
         'reviews':[],'disagreements':[],'source_limitations':['Unit test fixture, not engineering evidence.']}
    return tmp_path,doc


def validate(sample,doc=None,**kwargs):
    root,base=sample; path=root/'annotation.json'
    path.write_text(json.dumps(base if doc is None else doc))
    return dp.validate_annotation(path,root,SCHEMA,**kwargs)


def test_valid_provisional_stays_non_gold(sample):
    result=validate(sample)
    assert result['valid'] and not result['gold_truth']
    assert not result['professional_identity_authenticated'] and not result['engineering_approved']
    assert result['validator_version']


@pytest.mark.parametrize('field,value',[('created_utc','2026-99-99T20:00:00Z'),('created_utc','2026-11-06'),
                                        ('gold_truth','false'),('revision',True),('schema_version','marinaframe-annotation-2')])
def test_schema_rejects_bad_top_level_types_and_formats(sample,field,value):
    root,doc=sample; doc[field]=value
    assert not validate(sample)['valid']


def test_unknown_field_and_prefix_item_length_rejected(sample):
    root,doc=sample; doc['features'][0]['geometry']['bbox_px'].append(9)
    assert not validate(sample)['valid']
    doc['features'][0]['geometry']={'unsupported_shape':[]}
    assert not validate(sample)['valid']


@pytest.mark.parametrize('uri',['file:///etc/passwd','https://user:secret@example.org/x','not a uri'])
def test_source_uri_is_explicit_web_locator(sample,uri):
    sample[1]['features'][0]['evidence'][0]['source_url']=uri
    assert not validate(sample)['valid']


def test_inference_needs_derivation_and_unknown_needs_null(sample):
    feature=sample[1]['features'][0];feature['observation']='inferred'
    assert not validate(sample)['valid']
    feature['derivation']='Derived from visible test drawing region.'
    assert validate(sample)['valid']
    feature['observation']='unknown'
    assert not validate(sample)['valid']
    feature['value']=None
    assert validate(sample)['valid']


@pytest.mark.parametrize('box',[[2,1,1,20],[0,0,41,30],[0,0,0,10]])
def test_source_coordinate_bounds_and_order(sample,box):
    sample[1]['features'][0]['geometry']['bbox_px']=box
    assert not validate(sample)['valid']


def test_point_must_be_inside_half_open_frame(sample):
    sample[1]['features'][0]['geometry']={'point_px':[40,0]}
    assert not validate(sample)['valid']


def test_hash_dimensions_and_secondary_evidence_are_verified(sample):
    root,doc=sample; doc['asset']['width_px']=41
    assert not validate(sample)['valid']
    doc['asset']['width_px']=40;doc['features'][0]['evidence'][0]['asset_sha256']='0'*64
    assert not validate(sample)['valid']
    doc['features'][0]['evidence'][0]['asset_sha256']=doc['asset']['sha256']
    Image.new('L',(40,30),0).save(root/'drawing.png')
    assert not validate(sample)['valid']


@pytest.mark.parametrize('unsafe',['../drawing.png','/tmp/drawing.png','a/../drawing.png','drawing\\.png'])
def test_path_escape_is_rejected(sample,unsafe):
    sample[1]['asset']['file']=unsafe
    assert not validate(sample)['valid']


def test_symlink_is_rejected(sample):
    root,doc=sample;(root/'link.png').symlink_to(root/'drawing.png');doc['asset']['file']='link.png'
    assert not validate(sample)['valid']


def test_non_finite_and_duplicate_json_keys_rejected(sample):
    root,doc=sample;path=root/'annotation.json'
    path.write_text(json.dumps(doc).replace('"width_px": 40','"width_px": NaN'))
    assert not dp.validate_annotation(path,root,SCHEMA)['valid']
    path.write_text(json.dumps(doc).replace('"revision": 1','"revision": 1, "revision": 2'))
    assert not dp.validate_annotation(path,root,SCHEMA)['valid']


def test_duplicate_feature_and_contradictory_alternatives(sample):
    root,doc=sample;doc['features'].append(deepcopy(doc['features'][0]))
    assert not validate(sample)['valid']
    doc['features'].pop();doc['features'][0]['alternatives']=[
        {'id':'choice-a','reason':'First','geometry':None,'selected':True},
        {'id':'choice-b','reason':'Second','geometry':None,'selected':True}]
    assert not validate(sample)['valid']


def test_review_references_must_exist(sample):
    sample[1]['reviews']=[{'reviewer_id':'r','reviewer_role':'assistant','reviewed_utc':'2026-11-06T20:01:00Z',
                          'decision':'request_changes','features':['missing'],'notes':'No such feature.'}]
    assert not validate(sample)['valid']


def test_revision_lineage_is_content_bound(sample):
    root,doc=sample;previous=root/'previous.json';previous.write_text(json.dumps(doc))
    doc['revision']=2;doc['previous_revision_sha256']=dp.digest(previous)
    assert not validate(sample)['valid']
    assert validate(sample,previous_revision_path=previous)['valid']
    previous.write_text(previous.read_text()+' ')
    assert not validate(sample,previous_revision_path=previous)['valid']


def test_gold_needs_two_distinct_registered_reviewers_and_feature_coverage(sample):
    root,doc=sample;doc['gold_truth']=True;doc['annotator']={'id':'engineer-a','role':'human_engineer'}
    doc['features'][0]['review_status']='accepted'
    doc['reviews']=[{'reviewer_id':person,'reviewer_role':'human_engineer','reviewed_utc':'2026-11-06T20:01:00Z',
                     'decision':'accept','features':['panel-a'],'notes':'Fixture assertion, not authenticated person.'}
                    for person in ['engineer-b','engineer-c']]
    assert not validate(sample)['valid']
    registry={'schema_version':'marinaframe-reviewer-registry-1','reviewers':[
        {'id':person,'role':'human_engineer','qualified':True} for person in ['engineer-a','engineer-b','engineer-c']]}
    report=validate(sample,reviewer_registry=registry)
    assert report['valid'] and not report['professional_identity_authenticated'] and not report['engineering_approved']
    doc['reviews'][1]['features']=[]
    assert not validate(sample,reviewer_registry=registry)['valid']
    doc['reviews'][1]['features']=['panel-a'];doc['reviews'][1]['reviewer_id']='engineer-b'
    assert not validate(sample,reviewer_registry=registry)['valid']


def test_external_schema_refs_are_not_retrieved(sample):
    root,doc=sample;schema=json.loads(SCHEMA.read_text());schema['properties']['features']={'$ref':'https://example.org/remote.json'}
    schema_path=root/'schema.json';schema_path.write_text(json.dumps(schema));path=root/'annotation.json';path.write_text(json.dumps(doc))
    result=dp.validate_annotation(path,root,schema_path)
    assert not result['valid'] and 'external references' in result['errors'][0]['message']


def item(doc,**overrides):
    out={'item_id':doc['source_item_id'],'vessel_id':doc['vessel_id'],'design_group_id':doc['vessel_id']+'-all',
         'source_family':doc['source_family'],'asset_sha256':doc['asset']['sha256'],'split':doc['split'],
         'annotation_file':'annotation.json','rights':{'local_processing':'owner_authorized','training':'owner_authorized',
                                                     'source_redistribution':'unresolved','derived_distribution':'unresolved'}}
    out.update(overrides);return out


@pytest.mark.parametrize('shared',['vessel_id','source_family','asset_sha256','design_group_id','duplicate_group_id'])
def test_any_grouping_edge_prevents_cross_split_leakage(sample,shared):
    a=item(sample[1]);b=item(sample[1],item_id='b',vessel_id='vessel-b',source_family='family-b',
                           design_group_id='design-b',asset_sha256='1'*64,split='sealed_final')
    if shared=='duplicate_group_id':a[shared]='declared-near-duplicate'
    b[shared]=a[shared]
    with pytest.raises(dp.DatasetError,match='crosses'):dp.group_items([a,b])


def test_grouping_links_are_transitive(sample):
    a=item(sample[1]);b=item(sample[1],item_id='b',source_family='family-b',asset_sha256='1'*64)
    c=item(sample[1],item_id='c',vessel_id='vessel-c',design_group_id='c',source_family='family-b',asset_sha256='2'*64)
    groups=dp.group_items([a,b,c]);assert len(groups)==1 and len(groups[0]['items'])==3


def manifest_file(sample,items):
    path=sample[0]/'manifest.json';path.write_text(json.dumps({'schema_version':dp.DATASET_VERSION,'items':items}));return path


def test_provisional_export_is_opt_in_and_unknown_values_are_withheld(sample):
    root,doc=sample;validate(sample);manifest=manifest_file(sample,[item(doc)])
    strict=dp.build_dataset(manifest,root,SCHEMA,root/'strict')
    explicit=dp.build_dataset(manifest,root,SCHEMA,root/'provisional',allow_provisional=True)
    assert strict['training_rows']==0 and explicit['training_rows']==1
    row=json.loads((root/'provisional/development-labels.jsonl').read_text())
    assert row['label_status']=='provisional_assistant_label' and row['gold_truth'] is False
    doc['features'][0]['observation']='unknown';doc['features'][0]['value']=None;validate(sample)
    result=dp.build_dataset(manifest,root,SCHEMA,root/'unknown',allow_provisional=True)
    assert result['training_rows']==0


@pytest.mark.parametrize('split',['validation','sealed_final'])
def test_non_development_rows_never_enter_training(sample,split):
    root,doc=sample;doc['split']=split;validate(sample);manifest=manifest_file(sample,[item(doc)])
    report=dp.build_dataset(manifest,root,SCHEMA,root/'out',allow_provisional=True)
    assert report['training_rows']==0 and report['sealed_final_rows_emitted_for_training']==0


def test_rights_deny_training_and_release_without_blocking_authorized_local_use(sample):
    root,doc=sample;validate(sample);a=item(doc);a['rights']['training']='unresolved'
    manifest=manifest_file(sample,[a]);report=dp.build_dataset(manifest,root,SCHEMA,root/'out',allow_provisional=True)
    assert report['training_rows']==0 and report['public_release_allowlist']==[]
    assert report['restricted_files_excluded_from_public_release']==['annotation.json','drawing.png']
    local=dp.review_packet(manifest,root,SCHEMA,root/'local.html',audience='local')
    release=dp.review_packet(manifest,root,SCHEMA,root/'release.html',audience='release')
    assert local['included_items']==['a'] and release['rights_omitted_items']==['a']
    assert 'data:image/png;base64' in (root/'local.html').read_text()
    assert 'data:image/png;base64' not in (root/'release.html').read_text()
    assert 'body_plan' not in (root/'release.html').read_text()


def test_manifest_annotation_identity_mismatch_fails(sample):
    root,doc=sample;validate(sample);manifest=manifest_file(sample,[item(doc,item_id='different')])
    with pytest.raises(dp.DatasetError,match='mismatch'):dp.build_dataset(manifest,root,SCHEMA,root/'out')


def test_review_html_escapes_untrusted_annotations_and_has_aggregate_bound(sample,monkeypatch):
    root,doc=sample;doc['features'][0]['uncertainty']='<script>unexpected()</script>';validate(sample)
    manifest=manifest_file(sample,[item(doc)])
    dp.review_packet(manifest,root,SCHEMA,root/'review.html')
    text=(root/'review.html').read_text()
    assert '<script>unexpected' not in text and '&lt;script&gt;' in text
    monkeypatch.setattr(dp,'MAX_PACKET_IMAGE_BYTES',1)
    with pytest.raises(dp.DatasetError,match='Aggregate'):dp.review_packet(manifest,root,SCHEMA,root/'bounded.html')
