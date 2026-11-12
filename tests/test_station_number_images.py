"""Label boxes are evidence in attachment pixels, never curve IDs."""
from pathlib import Path

from PIL import Image, ImageDraw

from vessel_reconstruction import station_number_images as labels


def test_synthetic_numbers_missing_station_extra_curve_and_duplicate_claims():
    import numpy as np
    from vessel_reconstruction import body_plan_polyline as polyline
    from vessel_reconstruction import body_plan_reader as reader
    image = Image.new('L', (300, 180), 255)
    draw = ImageDraw.Draw(image)
    sections = []
    for column in (60, 140, 220):
        draw.line([(column, 160), (column, 20)], fill=0, width=2)
        sections.append(polyline.StationPolyline('fore', 1, np.array([[160., column], [20., column]]),
                                                0, (160., column), 70.))
    for text, x in [('7', 62), ('2', 142), ('3', 145)]:
        draw.text((x, 18), text, fill=0)
    layout = reader.SheetLayout(0., 200., {}, 300, ())
    items = [{'printed': text, 'box': [x, 18, x + 4, 24]} for text, x in [('7', 62), ('2', 142), ('3', 145)]]
    # Missing station 6 must not shift 7; the extra curve stays unnamed.
    # Two different printed numbers beside the middle curve invalidate both.
    assert labels.attach_numbers(sections, items, {7, 6, 3, 2}, layout) == {0: 7}


def test_two_nearby_curves_reject_label_without_nearest_wins():
    import numpy as np
    from types import SimpleNamespace
    sides = [SimpleNamespace(side_points=lambda x=x: np.array([[0., x], [20., x]])) for x in (10., 12.)]
    assert labels.attach_numbers(sides, [{'printed': '7', 'box': [10, 4, 12, 6]}], {7},
                                 SimpleNamespace(pixels_per_metre=200.)) == {}


def test_prepare_images_respects_limits_and_maps_box(tmp_path: Path):
    path = tmp_path / 'sheet.png'
    Image.new('L', (4000, 2000), 255).save(path)
    manifest = labels.prepare(path, tmp_path / 'request', (100, 100, 2100, 1900))
    assert manifest['purpose'] == 'station_numbers'
    assert 2 <= len(manifest['images']) <= 6
    assert sum(item['bytes'] for item in manifest['images']) <= 1_400_000
    for item in manifest['images']:
        assert max(item['width'], item['height']) <= 2048
        assert item['width'] * item['height'] <= 1_048_576
    tile = manifest['images'][1]
    mapped = labels.map_item({'printed': '7', 'image_id': tile['image_id'],
                              'box': [0, 0, tile['width'], tile['height']]}, manifest)
    assert mapped['box'] == tile['crop_box_px']


def test_half_without_a_reply_does_not_restore_rank_names():
    import numpy as np
    from vessel_reconstruction import body_plan_polyline as polyline
    from vessel_reconstruction import body_plan_reader as reader
    section = polyline.StationPolyline('fore', 1, np.array([[100., 30.], [0., 40.]]),
                                      0, (100., 30.), 70., station=7)
    half = polyline.HalfReading('fore', True, stations=[section], line_width_px=1.)
    side = reader.SideLayout('fore', 1, (7, 6, 5))
    layout = reader.SheetLayout(0., 100., {}, 100, (side,))
    result, report = labels.name_half(half, side, [], layout)
    assert result.read
    assert result.stations == []
    assert report['unnamed_sections'] == 1
    assert section.station == 7


def test_deduplicate_only_overlapping_agreeing_text():
    items = [{'printed': '7', 'box': [0, 0, 10, 10]},
             {'printed': '7', 'box': [1, 1, 9, 9]},
             {'printed': '8', 'box': [1, 1, 9, 9]}]
    assert labels.deduplicate(items) == [items[1], items[2]]
