"""Source records (docs/SOURCE_RECORD.md): the schema and each producer that writes one."""
import json

import numpy as np
import pytest

from vessel_reconstruction import source_record as sr

SHA = 'a' * 64


# ---------------------------------------------------------------- schema

def test_three_kinds_validate():
    page = sr.region('ga.pdf', view='plan_1deck', page=0, box_px=[10, 20, 110, 220], page_px=[400, 300])
    assert page == {'sheet': 'ga.pdf', 'page': 0, 'view': 'plan', 'box_px': [10.0, 20.0, 110.0, 220.0],
                    'page_px': [400, 300]}
    sr.validate(sr.read([page]))
    sr.validate(sr.guessed('beam box over the deck extent', [page, sr.part_input('main_deck')]))
    sr.validate(sr.unknown('not recorded'))


def test_a_region_without_pixels_has_a_null_box_and_never_an_invented_one():
    dxf = sr.region('ga.dxf', view='profile')
    assert dxf['box_px'] is None and 'page_px' not in dxf
    # A box without the page size it is measured in is not kept.
    assert sr.region('ga.pdf', view='plan', box_px=[1, 2, 3, 4])['box_px'] is None
    sr.validate(sr.read([dxf]))


def test_a_box_is_clipped_to_the_page_and_an_empty_one_is_dropped():
    assert sr.region('a.png', view='plan', box_px=[-5, 10, 50, 900], page_px=[40, 100])['box_px'] == [0, 10, 40, 100]
    assert sr.region('a.png', view='plan', box_px=[60, 10, 80, 20], page_px=[40, 100])['box_px'] is None


@pytest.mark.parametrize('record', [
    {'kind': 'approved'},
    {'kind': 'read', 'regions': []},
    {'kind': 'read', 'regions': [{'sheet': 'a.pdf', 'page': 0, 'view': 'plan', 'box_px': [0, 0, 5, 5]}]},
    {'kind': 'read', 'regions': [{'sheet': 'a.pdf', 'page': 0, 'view': 'plan', 'box_px': [0, 0, 50, 5],
                                  'page_px': [10, 10]}]},
    {'kind': 'read', 'regions': [{'sheet': 'a.pdf', 'page': -1, 'view': 'plan', 'box_px': None}]},
    {'kind': 'read', 'regions': [{'sheet': 'a.pdf', 'page': 0, 'view': 'elevation', 'box_px': None}]},
    {'kind': 'guessed', 'method': ' ', 'inputs': []},
    {'kind': 'guessed', 'method': 'x', 'inputs': [{'part': 'a', 'extra': 1}]},
    {'kind': 'unknown', 'reason': ''},
])
def test_invalid_records_are_refused(record):
    with pytest.raises(ValueError):
        sr.validate(record)


def test_records_stay_small():
    regions = [sr.region(f'sheet{i}.pdf', view='plan', box_px=[0, 0, 10, 10], page_px=[100, 100]) for i in range(30)]
    record = sr.guessed('x' * 5000, regions + [sr.part_input(f'p{i}') for i in range(30)])
    sr.validate(record)
    assert len(record['inputs']) == sr.MAX_INPUTS and len(record['method']) == sr.MAX_TEXT
    assert len(json.dumps(record)) < 2500
    assert len(sr.read(regions)['regions']) == sr.MAX_REGIONS


# ---------------------------------------------------------------- ship-cad parts

def _program():
    return {'schema': 'ship-cad/v1', 'components': [
        {'id': 'house', 'op': 'deckhouse', 'source': {'view': 'plan', 'region': 'house', 'method': 'closed_outline'},
         'args': {'outline': 'house_outline', 'height': 'house_height'}}]}


def _measurements(sheet_region=True):
    outline = {'status': 'measured', 'kind': 'outline', 'value': [[0, 0], [1, 0], [0, 1]], 'view': 'plan',
               'region': 'house', 'method': 'closed_outline', 'source_sha256': SHA, 'entity_ids': ['a']}
    height = {'status': 'measured', 'kind': 'interval', 'value': [1, 2], 'view': 'profile', 'region': 'height',
              'method': 'parallel_lines', 'source_sha256': SHA, 'entity_ids': ['b']}
    if sheet_region:
        outline['sheet_region'] = {'sheet': 'ga.pdf', 'page': 0, 'view': 'plan', 'box_px': [10, 10, 60, 40],
                                   'page_px': [200, 100]}
        height['sheet_region'] = {'sheet': 'ga.pdf', 'page': 0, 'view': 'profile'}
    return {'house_outline': outline, 'house_height': height}


def test_a_traced_part_is_read_from_its_measurement_regions():
    from vessel_reconstruction.ship_cad import resolve_program

    [part] = resolve_program(_program(), _measurements())
    record = sr.validate(part['source_record'])
    assert record['kind'] == 'read'
    assert [(r['view'], r['box_px']) for r in record['regions']] == [('plan', [10, 10, 60, 40]), ('profile', None)]


def test_a_part_with_a_guess_says_the_rule_and_its_inputs():
    from vessel_reconstruction.ship_cad import resolve_program

    measurements = _measurements()
    del measurements['house_height']
    guesses = {'house_height': {'kind': 'interval', 'value': [1, 3], 'source': 'guessed',
                                'basis': 'deck height plus 2 m'}}
    [part] = resolve_program(_program(), measurements, guesses)
    record = sr.validate(part['source_record'])
    assert record['kind'] == 'guessed'
    assert 'deck height plus 2 m' in record['method']
    assert record['inputs'][0]['sheet'] == 'ga.pdf'


def test_a_measurement_without_a_sheet_is_unknown_not_invented():
    from vessel_reconstruction.ship_cad import resolve_program

    [part] = resolve_program(_program(), _measurements(sheet_region=False))
    assert part['source_record']['kind'] == 'unknown'
    assert 'house_outline' in part['source_record']['reason']


def test_an_inline_model_value_is_a_guess():
    program = _program()
    program['components'][0]['args']['height'] = {'value': [1, 2.5], 'source': 'ai_inferred',
                                                  'basis': 'model read the house height'}
    from vessel_reconstruction.ship_cad import resolve_program

    [part] = resolve_program(program, _measurements())
    assert part['source_record']['kind'] == 'guessed'
    assert 'model read the house height' in part['source_record']['method']


def test_component_record_lists_the_parts_a_part_is_built_on():
    record = sr.component_record({}, part_refs=['main_deck'])
    assert record == {'kind': 'guessed', 'method': 'Built from other parts', 'inputs': [{'part': 'main_deck'}]}
    assert sr.component_record({}, unspecified=True)['kind'] == 'unknown'


# ---------------------------------------------------------------- GA readers

def test_vector_ga_reader_names_the_sheet_without_a_box():
    from benchmarks.gunnerus.whole_vessel import VectorReader

    reader = object.__new__(VectorReader)
    reader.source_file = 'GA.dxf'
    assert reader.sheet_region('plan_1deck', [[0, 0]]) == {'sheet': 'GA.dxf', 'page': 0, 'view': 'plan'}


def test_raster_ga_reader_box_inverts_its_pixel_formula():
    from benchmarks.gunnerus.whole_vessel_raster import RASTER_VIEWS, RasterReader

    name = next(iter(RASTER_VIEWS))
    crop = RasterReader.crop(name, {'s': 0.05, 'ox': 120.0, 'oy': 900.0}, (1000, 1600))
    reader = object.__new__(RasterReader)
    reader.source_file, reader.crops, reader.page_px = 'GA.pdf', {name: crop}, [1600, 1000]
    points = [[crop['x_of_column'](c), crop['v_of_row'](r)] for c, r in ((5, 7), (40, 30))]
    region = reader.sheet_region(name, points)
    expected = [crop['col0'] + 5, crop['row0'] + 7, crop['col0'] + 40, crop['row0'] + 30]
    assert np.allclose(region['box_px'], expected)
    assert region['page_px'] == [1600, 1000] and region['sheet'] == 'GA.pdf'
    sr.validate(sr.read([sr.region(**{k: region[k] for k in ('sheet', 'page', 'view')},
                                   box_px=region['box_px'], page_px=region['page_px'])]))


def test_height_interval_points_span_both_levels():
    from benchmarks.gunnerus.whole_vessel import level_points

    low = {'z': 1.0, 'extent': [2.0, 9.0]}
    high = {'z': 3.5, 'extent': None, 'x_range': [3.0, 8.0]}
    points = np.array(level_points(low, high))
    assert points[:, 0].min() == 2.0 and points[:, 0].max() == 9.0
    assert points[:, 1].min() == 1.0 and points[:, 1].max() == 3.5


# ---------------------------------------------------------------- construction plan parts

def test_internal_parts_name_their_dxf_sheets_and_guesses():
    from benchmarks.gunnerus import whole_vessel_internals as internals

    tank = internals.Part('tank_db1', 'tank', 'DB 1', [], {'outline': 'traced', 'height': 'traced'},
                          {'outline': {'source': 'traced', 'basis': 'label region'},
                           'height': {'source': 'traced', 'basis': 'tank top'}},
                          {'plan': 'below_tank_top'})
    record = sr.validate(internals.part_source_record(tank))
    assert record['kind'] == 'read'
    assert {(r['sheet'], r['view']) for r in record['regions']} == {
        (internals.TANK_PLAN, 'plan'), (internals.LONG_SECTION, 'profile')}
    assert all(r['box_px'] is None for r in record['regions'])

    plate = internals.Part('tank_top_1', 'deck', 'Tank top', [], {},
                           {'level': {'source': 'traced', 'basis': 'line'},
                            'thickness': {'source': 'guessed', 'basis': 'plate 10 mm'}}, {})
    record = sr.validate(internals.part_source_record(plate))
    assert record['kind'] == 'guessed' and 'plate 10 mm' in record['method']
    assert record['inputs'] == [sr.region(internals.LONG_SECTION, view='profile')]

    unbuilt = internals.Part('tank_x', 'tank', 'X', [], {}, {}, {}, notes=['no plan region holds its label'])
    assert internals.part_source_record(unbuilt) == sr.unknown('no plan region holds its label')


# ---------------------------------------------------------------- raster tank plans

def test_unturn_box_inverts_deskew():
    cv2 = pytest.importorskip('cv2')
    from vessel_reconstruction.tank_plan_raster import unturn_box

    width, height, angle = 900, 600, 1.5
    ink = np.zeros((height, width), np.uint8)
    ink[100:120, 700:760] = 255  # a label far from the centre
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), -angle, 1.0)  # as deskew turns it
    turned = cv2.warpAffine(ink, matrix, (width, height), flags=cv2.INTER_NEAREST)
    rows, cols = np.nonzero(turned)
    box = unturn_box([cols.min(), rows.min(), cols.max() + 1, rows.max() + 1], (width, height), angle)
    # The box of a turned box is a little larger than the label; its centre is where the label is.
    assert abs((box[0] + box[2]) / 2 - 730) < 2 and abs((box[1] + box[3]) / 2 - 110) < 2
    assert unturn_box([1, 2, 3, 4], (10, 10), 0.0) == [1, 2, 3, 4]


def _raster_tank(place, z_source='traced'):
    from vessel_reconstruction.tank_plan_raster import PlanTank, RasterTank

    plan = PlanTank('sheet2_plan', 'FO TK 1 P', 'fo1p', 3, {}, (1.0, 5.0), 1, 'above', place=place)
    return RasterTank(plan, 'fuel oil', 'FO TK 1 P', None, z_source, 'from the tank top to the deck', None, None, 0.0)


def test_raster_tank_record_places_its_label_on_the_named_sheet():
    from vessel_reconstruction.tank_plan_raster import tank_record

    place = {'sheet_number': 1, 'view': 'plan', 'box_px': [100, 50, 180, 70], 'page_px': [3000, 2000]}
    files = [('profile.pdf', 0), ('plans.tif', 0)]
    record = sr.validate(tank_record(_raster_tank(place), files)['source_record'])
    assert record == {'kind': 'read', 'regions': [{'sheet': 'plans.tif', 'page': 0, 'view': 'plan',
                                                   'box_px': [100.0, 50.0, 180.0, 70.0], 'page_px': [3000, 2000]}]}
    guessed = tank_record(_raster_tank(place, 'guessed'), files)['source_record']
    assert guessed['kind'] == 'guessed' and guessed['method'].startswith('Height: ')
    assert guessed['inputs'][0]['sheet'] == 'plans.tif'
    assert tank_record(_raster_tank(place))['source_record']['kind'] == 'unknown'


def test_tank_record_file_round_trips(tmp_path):
    path = tmp_path / f'case_DRAFT{sr.TANK_RECORDS_SUFFIX}'
    sr.write_records(path, {'fo1p': sr.unknown('x')})
    assert json.loads(path.read_text()) == {'schema': sr.SCHEMA, 'records': {'fo1p': sr.unknown('x')}}
    with pytest.raises(ValueError):
        sr.write_records(path, {'bad': {'kind': 'read', 'regions': []}})


# ---------------------------------------------------------------- hull sections

def test_ingest_records_each_section_region_on_its_page(tmp_path):
    from PIL import Image

    from vessel_reconstruction.ingest import extract_sections

    Image.new('RGB', (420, 420), 'white').save(tmp_path / 'drawing.png')
    spec = {'units': 'm', 'source': {'file': 'drawing.png'}, 'sections': [{
        'id': 'st5', 'x_m': 12.5, 'roi_px': [65, 40, 350, 375],
        'calibration': {'centerline_px': 90, 'baseline_px': 360, 'pixels_per_metre': 60},
        'authored': {'points_yz_m': [[0, 0], [1, 1], [2, 3]], 'source_label': 'ai_inferred',
                     'basis': 'faint curve'}}]}
    [section] = extract_sections(spec, tmp_path)['sections']
    record = sr.validate(section['source_record'])
    assert record['kind'] == 'guessed' and 'faint curve' in record['method']
    assert record['inputs'] == [{'sheet': 'drawing.png', 'page': 0, 'view': 'body plan',
                                 'box_px': [65.0, 40.0, 350.0, 375.0], 'page_px': [420, 420]}]


def test_traced_section_record():
    record = sr.traced_section('lines.pdf', [1, 2, 30, 40], page=2, page_px=[100, 100])
    assert record == {'kind': 'read', 'regions': [{'sheet': 'lines.pdf', 'page': 2, 'view': 'body plan',
                                                   'box_px': [1.0, 2.0, 30.0, 40.0], 'page_px': [100, 100]}]}


def test_finish_sections_says_what_the_build_did():
    traced = sr.traced_section('lines.pdf', [1, 2, 30, 40], page=0, page_px=[100, 100])
    sections = [
        {'id': 'a', 'x_m': 0.0, 'source_label': 'traced', 'source_record': dict(traced)},
        {'id': 'b', 'x_m': 1.0, 'source_label': 'interpolated', 'evidence': {}},
        {'id': 'c', 'x_m': 2.0, 'source_label': 'repaired', 'source_record': dict(traced)},
        {'id': 'd', 'x_m': 3.0},
    ]
    sr.finish_sections(sections)
    kinds = [s['source_record']['kind'] for s in sections]
    assert kinds == ['read', 'guessed', 'guessed', 'unknown']
    assert sections[1]['source_record']['inputs'] == [{'part': 'a'}, {'part': 'c'}]
    assert sections[2]['source_record']['inputs'] == traced['regions']
    sr.finish_sections(sections[:1], faired=True)
    assert sections[0]['source_record']['kind'] == 'guessed'
