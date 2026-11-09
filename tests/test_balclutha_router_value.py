"""Synthetic tests for the round-6 router reading (no drawing, no router, no model call)."""
import io
import json

import pytest
from benchmarks.balclutha import router_value as rv
from benchmarks.balclutha import tiled_value as tv

SHEET_WIDTH, SHEET_HEIGHT = 9632, 14442  # the full-resolution sheet 7 (protocol 3.5.4)
FAKE_SECRET = 'not-a-real-secret-0123456789'


def round6_tiles():
    return {tile['id']: tile for tile in tv.tile_boxes(rv.ROUND6_LAYOUT)}


def test_round6_layout_is_one_tile_per_side_and_waterline_inside_the_sheet():
    tiles = round6_tiles()
    assert len(tiles) == 16
    for tile in tiles.values():
        left, top, right, bottom = tile['box']
        assert tv.tile_size(tile) == (4096, 2048)
        assert 0 <= left and right <= SHEET_WIDTH and 0 <= top and bottom <= SHEET_HEIGHT
        assert top < tv.WATERLINE_ROWS[tile['waterline']] < bottom
        assert left < tv.CENTRE_COLUMN < right  # 48 px across the centreline
    fore, aft = tiles['fore-wl32-whole']['box'], tiles['aft-wl04-whole']['box']
    assert fore[2] > tv.BUTTOCK_COLUMNS['fore'][-1] and aft[0] < tv.BUTTOCK_COLUMNS['aft'][-1]


def test_round5_layout_and_prompt_are_unchanged_by_the_layout_parameter():
    assert len(tv.tile_boxes()) == 32
    tile = round6_tiles()['fore-wl16-whole']
    prompt = tv.tile_prompt(tile)
    assert '(4096 x 2048 px)' in prompt and 'y = 1024' in prompt
    with pytest.raises(ValueError, match='outside the tile'):
        tv.parse_crossings(json.dumps({'crossings': [{'station': 12, 'x_px': 4097}]}), tile)
    assert tv.parse_crossings(json.dumps({'crossings': [{'station': 12, 'x_px': 3000}]}), tile) == {12: 3000.0}


def test_responses_input_keeps_images_at_original_detail_and_carries_the_retry_turn():
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'read'},
                                             {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA'}}]},
                {'role': 'assistant', 'content': 'not json'},
                {'role': 'user', 'content': 'Invalid reply'}]
    items = rv.responses_input(messages)
    assert items[0]['content'] == [{'type': 'input_text', 'text': 'read'},
                                   {'type': 'input_image', 'image_url': 'data:image/png;base64,AA', 'detail': 'original'}]
    assert items[1] == {'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'not json'}]}
    assert items[2]['content'] == [{'type': 'input_text', 'text': 'Invalid reply'}]
    body = rv.request_body('gpt-6.1-sol', messages)
    assert body['reasoning'] == {'effort': 'high'} and body['max_output_tokens'] == 32_000
    assert 'temperature' not in body


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def reply_bytes(text, streamed=False):
    response = {'model': 'gpt-6.1-sol', 'status': 'completed',
                'output': [{'type': 'reasoning'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}],
                'usage': {'input_tokens': 12000, 'output_tokens': 900, 'output_tokens_details': {'reasoning_tokens': 700}}}
    if streamed:
        return ('event: response.completed\ndata: ' + json.dumps({'type': 'response.completed', 'response': response})
                + '\n\n').encode()
    return json.dumps(response).encode()


@pytest.mark.parametrize('streamed', [False, True])
def test_call_records_usage_and_never_writes_the_secret(tmp_path, monkeypatch, streamed):
    monkeypatch.setenv(rv.SECRET_ENV, FAKE_SECRET)
    seen = {}

    def opener(request, timeout):
        seen['url'] = request.full_url
        return FakeResponse(reply_bytes('{"crossings": []}', streamed))

    text, receipt = rv.make_call('gpt-6.1-sol', opener)([{'role': 'user', 'content': 'x'}], tmp_path, {})
    assert text == '{"crossings": []}' and receipt['state'] == 'completed'
    assert receipt['usage'] == {'prompt_tokens': 12000, 'completion_tokens': 900, 'reasoning_tokens': 700}
    assert FAKE_SECRET in seen['url'] and seen['url'].endswith('/v1/responses')
    written = ''.join(path.read_text() for path in tmp_path.glob('*.json'))
    assert FAKE_SECRET not in written


def test_failed_call_redacts_the_secret_from_the_error(tmp_path, monkeypatch):
    monkeypatch.setenv(rv.SECRET_ENV, FAKE_SECRET)

    def opener(request, timeout):
        raise OSError(f'cannot reach {request.full_url}')

    text, receipt = rv.make_call('gpt-6-astra', opener)([{'role': 'user', 'content': 'x'}], tmp_path, {})
    assert text == '' and receipt['state'] == 'failed'
    assert FAKE_SECRET not in receipt['error'] and '<secret>' in receipt['error']
    assert FAKE_SECRET not in ''.join(path.read_text() for path in tmp_path.glob('*.json'))


def test_crouton_uses_the_round5_layout_and_settings_and_never_writes_the_key(tmp_path, monkeypatch):
    assert len(tv.tile_boxes(rv.LAYOUTS['crouton-alpha-free'])) == 32
    monkeypatch.setenv('OPENCODE_API_KEY', FAKE_SECRET)
    seen = {}

    def opener(request, timeout):
        seen['headers'] = dict(request.header_items())
        seen['body'] = json.loads(request.data)
        return FakeResponse(json.dumps({'model': 'crouton-alpha-free', 'choices': [
            {'message': {'content': '{"crossings": []}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 30, 'completion_tokens': 9, 'cost': 0}}).encode())

    text, receipt = rv.make_go_call('crouton-alpha-free', opener)([{'role': 'user', 'content': 'x'}], tmp_path, {})
    assert text == '{"crossings": []}' and receipt['usage']['cost'] == 0
    body = seen['body']
    assert body['temperature'] == 0.2 and body['max_tokens'] == 32_000 and 'thinking' not in body
    assert body['reasoning_effort'] == 'high' and 'X-opencode-session' in seen['headers']
    assert FAKE_SECRET not in ''.join(path.read_text() for path in tmp_path.glob('*.json'))


def test_decision_rule_needs_coverage_in_every_repeat_and_median_rms():
    good = {'coverage': 0.7, 'rms_m': 0.1}
    assert rv.decide([good, good, {'coverage': 0.7, 'rms_m': 0.5}]) == (0.1, True)
    assert rv.decide([good, good, {'coverage': 0.5, 'rms_m': 0.1}])[1] is False
    assert rv.decide([good, {'coverage': 0.7, 'rms_m': 0.2}, {'coverage': 0.7, 'rms_m': 0.3}]) == (0.2, False)
    assert rv.decide([good, good, {'coverage': 0.0}]) == (0.1, False)
