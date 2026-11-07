from benchmarks.localisation.summarize import drawing_table, stats, usage


def test_empty_measurements_keep_frozen_denominators():
    rows = drawing_table([])
    assert len(rows) == 16
    assert sum(r['planned'] for r in rows) == 320
    assert sum(r['position_px']['n'] for r in rows) == 0


def test_usage_includes_failed_calls_and_provider_list_cost():
    records = [{'state': 'failed', 'usage': {'prompt_tokens': 7, 'completion_tokens': 3,
                'cost': 0, 'list_cost': .002}, 'observed_cost_usd': 0, 'images': [{}]},
               {'state': 'completed', 'usage': {}, 'images': []}]
    total = usage(records)
    assert total['calls'] == 2
    assert total['prompt_tokens'] == 7
    assert total['completion_tokens'] == 3
    assert total['list_cost_usd'] == .002
    assert total['missing_usage'] == 1
    assert stats([None, 0])['n'] == 1
