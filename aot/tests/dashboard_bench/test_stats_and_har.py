# coding=utf-8
"""순수 계산 모듈 시험 — 브라우저·서버 없이 돈다."""
import json

from aot.tests.dashboard_bench import harstats, stats


def test_quantile_interpolates():
    assert stats.quantile([1, 2, 3, 4], 0.5) == 2.5
    assert stats.quantile([10], 0.9) == 10.0
    assert stats.quantile([], 0.5) is None
    assert stats.quantile([None, 4, 2], 0.5) == 3.0     # None 은 뺀다


def test_summarize_median_and_iqr():
    s = stats.summarize([100, 110, 120, 130, 500])
    assert s['n'] == 5 and s['median'] == 120
    assert s['q1'] == 110 and s['q3'] == 130 and s['iqr'] == 20
    assert s['min'] == 100 and s['max'] == 500
    assert stats.summarize([None])['n'] == 0


def test_summarize_runs_picks_keys():
    out = stats.summarize_runs([{'a': 1, 'b': 5}, {'a': 3}], ['a', 'b'])
    assert out['a']['median'] == 2 and out['b']['n'] == 1


def _req(url, t, enc, status=200, **kw):
    return dict(url=url, method='GET', t=t, enc=enc, status=status, **kw)


def test_request_metrics_splits_first_load_and_steady():
    reqs = [_req('http://h/a.js', 0.1, 1000), _req('http://h/b.css', 0.2, 500),
            _req('http://h/data_batch', 10.0, 2000), _req('http://h/data_batch', 20.0, 2000, status=304),
            _req('http://h/x', 30.0, 100, failed=1)]
    reqs[-1].pop('enc')
    m = harstats.request_metrics(reqs, settle_s=5.0, dwell_s=60.0)
    assert m['first_requests'] == 2 and m['first_bytes'] == 1500
    assert m['steady_requests'] == 2 and m['steady_bytes'] == 4000
    assert m['ratio_304'] == 0.5
    # 60초 4000바이트 → 시간당 240,000바이트
    assert round(m['poll_bytes_per_hour']) == 240000
    assert m['poll_by_url']['/data_batch']['n'] == 2
    assert m['poll_requests_per_min'] == 2.0


def test_request_metrics_empty_steady_has_no_ratio():
    m = harstats.request_metrics([_req('http://h/a', 0.1, 10)], settle_s=5, dwell_s=30)
    assert m['ratio_304'] is None and m['steady_requests'] == 0


def test_total_blocking_time_counts_only_excess_over_50ms_in_window():
    tasks = [(100, 30), (200, 120), (300, 51), (5000, 400)]
    assert harstats.total_blocking_time(tasks, 0, 1000) == 70 + 1
    assert harstats.total_blocking_time(tasks, 150, 1000) == 71


def _har(entries):
    return {'log': {'entries': entries}}


def _entry(t, url, method='GET', body=None, headers=None):
    e = {'startedDateTime': f'2026-11-08T01:00:{t:06.3f}Z',
         'request': {'method': method, 'url': url, 'headers': headers or [], 'cookies': [{'name': 's'}]},
         'response': {'status': 200, 'headers': [{'name': 'Set-Cookie', 'value': 'x'}], 'cookies': [{'name': 's'}]}}
    if body:
        e['request']['postData'] = {'text': body, 'mimeType': 'application/json'}
    return e


def test_sanitize_har_removes_cookies_and_auth():
    har = _har([_entry(0, 'http://h/', headers=[
        {'name': 'Cookie', 'value': 'session=SECRET'}, {'name': 'X-CSRFToken', 'value': 'T'},
        {'name': 'Accept', 'value': '*/*'}])])
    clean = harstats.sanitize_har(har)
    text = json.dumps(clean)
    assert 'SECRET' not in text and 'Set-Cookie' not in text
    assert [h['name'] for h in clean['log']['entries'][0]['request']['headers']] == ['Accept']
    assert har['log']['entries'][0]['request']['headers'][0]['name'] == 'Cookie'   # 원본은 그대로


def test_pattern_from_har_finds_period_of_polls():
    entries = [_entry(0, 'http://h/dashboard/abc'), _entry(1, 'http://h/static/a.js')]
    entries += [_entry(6 + 10 * i, 'http://h/data_batch', 'POST', body='{"m":1}') for i in range(5)]
    entries += [_entry(8 + 30 * i, 'http://h/api/v1/mcp/confirmations') for i in range(2)]
    pat = harstats.pattern_from_har(_har(entries), settle_ms=5000)
    assert [i['url'] for i in pat['first']] == ['/dashboard/abc', '/static/a.js']
    by_path = {g['url']: g for g in pat['polls']}
    assert round(by_path['/data_batch']['period_s']) == 10
    assert by_path['/data_batch']['body'] == '{"m":1}' and by_path['/data_batch']['method'] == 'POST'
    assert round(by_path['/api/v1/mcp/confirmations']['period_s']) == 30
    assert pat['polls'][0]['url'] == '/data_batch'      # 짧은 주기 먼저


def test_pattern_from_har_empty():
    assert harstats.pattern_from_har(_har([]))['first'] == []


def test_camera_metrics_separates_request_period_from_new_photo_period():
    steady = [_req('http://h/camera/last_image/c1?x=%d' % i, 6 + i, 500000 if i % 4 == 0 else 300,
                   status=200 if i % 4 == 0 else 304) for i in range(20)]
    steady.append(_req('http://h/data_batch', 7, 100))
    m = harstats.request_metrics(steady, settle_s=5.0, dwell_s=20.0)
    assert m['camera_requests'] == 20 and m['camera_new_photos'] == 5
    assert m['camera_304_ratio'] == 0.75
    assert m['camera_request_period_s'] == 1.0 and m['camera_new_photo_period_s'] == 4.0
    # 새 사진 5장 × 500KB 를 20초 → 시간당 환산
    assert round(m['camera_mb_per_hour']) == round((5 * 500000 + 15 * 300) / 20 * 3600 / 1e6)


def test_camera_metrics_none_without_camera():
    m = harstats.request_metrics([_req('http://h/data_batch', 6, 10)], settle_s=5.0, dwell_s=10.0)
    assert m['camera_requests'] == 0 and m['camera_new_photo_period_s'] is None


def test_pattern_treats_simultaneous_requests_as_one_burst():
    # 위젯 3개가 10초마다 같은 순간에 같은 요청을 보낸다 — 주기는 10초, 묶음 크기 3
    entries = [_entry(0, 'http://h/dashboard/abc')]
    for i in range(4):
        for k in range(3):
            entries.append(_entry(6 + 10 * i + k * 0.003, 'http://h/api/geo/output_runtimes', 'POST', body='{}'))
    pat = harstats.pattern_from_har(_har(entries), settle_ms=5000)
    g = pat['polls'][0]
    assert round(g['period_s']) == 10 and g['burst'] == 3 and g['count'] == 12


def test_pattern_skips_external_hosts_and_aborted_requests():
    entries = [_entry(0, 'http://h/dashboard/abc'), _entry(1, 'https://fonts.googleapis.com/css?family=x'),
               _entry(2, 'http://h/static/a.js')]
    entries[2]['response']['status'] = 0
    pat = harstats.pattern_from_har(_har(entries))
    assert [i['url'] for i in pat['first']] == ['/dashboard/abc']


def test_304_is_read_from_raw_network_status_not_the_merged_cache_status():
    # CDP responseReceived 는 재검증 304 를 200 으로 보고한다 — raw_status 가 진실이다
    steady = [_req('http://h/camera/last_image/c1', 6 + i, 400, status=200, raw_status=304) for i in range(4)]
    steady.append(_req('http://h/camera/last_image/c1', 11, 500000, status=200, raw_status=200))
    m = harstats.request_metrics(steady, settle_s=5.0, dwell_s=10.0)
    assert m['ratio_304'] == 0.8 and m['camera_304_ratio'] == 0.8 and m['camera_new_photos'] == 1
    assert m['poll_by_url']['/camera/last_image/c1']['n304'] == 4
