"""Synthetic tests for the round-9 holdout harness (no drawing, no truth file, no model call)."""
import json
import subprocess

from benchmarks.thayer import holdout_value as hv

FAKE_PNG_B64 = 'iVBORw0KGgo='


def test_layout_puts_the_aftbody_left_and_the_grid_on_both_sides():
    layout = hv.sheet_layout()
    aft, fore = layout.sides
    assert (aft.name, aft.sign, aft.stations_outer_first[0], aft.stations_outer_first[-1]) == ('aft', -1, 12, 22)
    assert (fore.name, fore.sign, fore.stations_outer_first[0], fore.stations_outer_first[-1]) == ('fore', 1, 11, 1)
    assert aft.grid_columns[0] == hv.CENTRE_COLUMN - 600 and fore.grid_columns[-1] == hv.CENTRE_COLUMN + 3000
    assert layout.waterlines_low_to_high() == list(hv.WATERLINES)
    # 3'-7" lies 3 7/12 ft above the base row.
    assert abs(hv.BASE_ROW - hv.WATERLINE_ROWS['3-7'] - (3 + 7 / 12) * hv.PIXELS_PER_FT) <= 1.5


def test_truth_loader_skips_crossed_cells_and_converts_feet_inches_eighths(tmp_path):
    rows = {w: [None] * 22 for w in hv.WATERLINES}
    rows['9-7'][0] = '1-0-4'  # station 1
    rows['3-7'][21] = '0-6-0'  # station 22
    path = tmp_path / 'truth.json'
    path.write_text(json.dumps({'stations': list(range(1, 23)), 'rows': rows}))
    truth = hv.load_truth(path)
    assert set(truth) == {(1, '9-7'), (22, '3-7')}
    assert abs(truth[(1, '9-7')] - (1 + 0.5 / 12) * 0.3048) < 1e-9


def test_scorer_finds_a_curve_named_as_its_neighbour():
    truth = {(s, w): 1.0 + s * 0.3 + i * 0.01 for s in (4, 5) for i, w in enumerate(hv.WATERLINES)}
    swapped = {(5 if s == 4 else 4, w): v for (s, w), v in truth.items()}
    assert hv.score(truth, truth)['identity_errors'] == []
    assert hv.score(swapped, truth)['identity_errors'] == [4, 5]


def test_claude_message_carries_the_image_and_folds_a_retry_into_one_user_turn():
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Which station?'},
                                             {'type': 'image_url',
                                              'image_url': {'url': 'data:image/png;base64,' + FAKE_PNG_B64}}]},
                {'role': 'assistant', 'content': 'seven'},
                {'role': 'user', 'content': 'Invalid reply: no JSON.'}]
    message = hv.claude_message(messages)
    image, text = message['message']['content']
    assert message['type'] == 'user' and image['source']['data'] == FAKE_PNG_B64
    assert text['text'].startswith('Which station?') and 'seven' in text['text'] and 'Invalid reply' in text['text']


def test_claude_call_has_no_tools_and_no_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'not-a-real-key')
    seen = {}

    def runner(command, **kwargs):
        seen.update(command=command, env=kwargs['env'])
        result = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '{"station": 7}',
                  'usage': {'input_tokens': 2, 'cache_creation_input_tokens': 100, 'output_tokens': 9}}
        return subprocess.CompletedProcess(command, 0, stdout='{"type": "system"}\n' + json.dumps(result) + '\n')

    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'q'}, {
        'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + FAKE_PNG_B64}}]}]
    text, receipt = hv.claude_call(runner=runner)(messages, tmp_path / 'receipts')
    assert text == '{"station": 7}' and receipt['state'] == 'completed'
    assert receipt['usage'] == {'prompt_tokens': 102, 'completion_tokens': 9}
    command = seen['command']
    assert command[:4] == ['claude', '-p', '--model', 'claude-sonnet-5-5']
    assert command[command.index('--tools') + 1] == ''
    assert 'ANTHROPIC_API_KEY' not in seen['env']
