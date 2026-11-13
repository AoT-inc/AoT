# coding=utf-8
"""통계 여러 개를 Influx 왕복 1회로 묻는 경로 — 결과 동등성과 질의 횟수.

실제 Influx 에는 연결하지 않는다. 조회 함수(`query_string`)를 대역으로 잡고
옛 구현(통계마다 질의)과 새 구현(`group_fns` 한 번)이 **같은 가짜 레코드에서
같은 출력**을 내는지, 그리고 왕복이 줄었는지를 본다.
"""
import math
import random
from datetime import datetime, timedelta, timezone

import pytest
import pytz

from aot.aot_flask.geo.plot_journal import calc as pj_calc
from aot.utils import influx
from aot.utils.timekit import bucket_local_key

_UTC = timezone.utc


class _Rec:
    def __init__(self, t, v, stat=None):
        self._t, self._v = t, v
        self.values = {'_stat': stat} if stat else {}

    def get_time(self):
        return self._t

    def get_value(self):
        return self._v


class _Table:
    def __init__(self, records):
        self.records = records


def _make_rows(start, hours, seed, holes=True):
    """시간 버킷 오른쪽 경계 라벨 → {'min','max','mean'} (일부 통계 누락 포함)."""
    rnd = random.Random(seed)
    rows = {}
    for i in range(1, hours + 1):
        t = start + timedelta(hours=i)
        if holes and rnd.random() < 0.12:
            continue                      # 빈 시간 — 세 통계 모두 없음
        base = rnd.uniform(-5, 30)
        row = {'min': base - rnd.random() * 3, 'max': base + rnd.random() * 3,
               'mean': base}
        if holes and rnd.random() < 0.1:
            del row[rnd.choice(['min', 'max', 'mean'])]   # 일부 통계만 있는 날
        rows[t] = row
    return rows


class _Backend:
    """query_string 대역 — 호출을 기록한다. interleave=True 면 새 경로 응답을 섞는다."""

    def __init__(self, rows, interleave=False):
        self.rows, self.calls, self.interleave = rows, [], interleave

    def __call__(self, unit, uid, **kw):
        self.calls.append(kw)
        fns = kw.get('group_fns')
        if fns:
            recs = [_Rec(t, r[f], f) for f in fns
                    for t, r in sorted(self.rows.items()) if f in r]
            if self.interleave:
                random.Random(1).shuffle(recs)
            return [_Table(recs)]
        fn = kw.get('group_fn') or 'mean'
        recs = [_Rec(t, r[fn]) for t, r in sorted(self.rows.items()) if fn in r]
        return [_Table(recs)] if recs else []


class _DM:
    device_id = 'dev-1'


@pytest.fixture(autouse=True)
def _channel(monkeypatch):
    monkeypatch.setattr(pj_calc, '_channel_info',
                        lambda dm: ('0', 'C', 'temperature', 'temperature'))


def _legacy_daily_stats(backend, tz, bucket_sec=3600,
                        stats=('min', 'max', 'mean')):
    """옛 구현의 접기 규칙(통계마다 질의) — 비교 기준."""
    acc = {}
    for fn in stats:
        for table in backend(None, 'dev-1', group_fn=fn,
                             group_sec=bucket_sec) or []:
            for rec in table.records:
                key = bucket_local_key(rec.get_time(), bucket_sec, tz)
                acc.setdefault(key, {'min': [], 'max': [], 'mean': []})[fn].append(
                    float(rec.get_value()))
    return {k: {'min': min(b['min']) if b['min'] else None,
                'max': max(b['max']) if b['max'] else None,
                'avg': sum(b['mean']) / len(b['mean']) if b['mean'] else None,
                'samples': len(b['mean'])} for k, b in acc.items()}


# 시간대 · UTC 시작 시각(DST 경계 포함)
CASES = [
    ('Asia/Seoul', datetime(2026, 6, 1, tzinfo=_UTC)),
    ('America/New_York', datetime(2026, 10, 31, 3, tzinfo=_UTC)),   # 11/1 DST 종료
    ('Europe/Berlin', datetime(2026, 3, 27, 22, tzinfo=_UTC)),      # 3/29 DST 시작
    ('Asia/Kolkata', datetime(2026, 6, 1, 20, tzinfo=_UTC)),        # +05:30
    ('Pacific/Auckland', datetime(2026, 9, 25, 5, tzinfo=_UTC)),    # 9/27 DST 시작
]


@pytest.mark.parametrize('tzname,start', CASES)
@pytest.mark.parametrize('interleave', [False, True])
def test_daily_channel_stats_same_as_legacy(monkeypatch, tzname, start,
                                            interleave):
    tz = pytz.timezone(tzname)
    rows = _make_rows(start, 24 * 6, seed=len(tzname))
    new_b = _Backend(rows, interleave=interleave)
    monkeypatch.setattr(influx, 'query_string', new_b)
    got = pj_calc.daily_channel_stats(_DM(), 'a', 'b', tz)
    want = _legacy_daily_stats(_Backend(rows), tz)
    assert set(got['by_bucket']) == set(want)
    for k, w in want.items():
        g = got['by_bucket'][k]
        for f in ('min', 'max', 'samples'):
            assert g[f] == w[f], (k, f)
        if w['avg'] is None:
            assert g['avg'] is None
        else:
            assert math.isclose(g['avg'], w['avg'], rel_tol=0, abs_tol=1e-9)
    # 질의 횟수: 채널당 1회 (옛 구현은 3회)
    assert len(new_b.calls) == 1
    assert new_b.calls[0]['group_fns'] == ('min', 'max', 'mean')


def test_daily_channel_stats_empty_channel(monkeypatch):
    b = _Backend({})
    monkeypatch.setattr(influx, 'query_string', b)
    got = pj_calc.daily_channel_stats(_DM(), 'a', 'b', 'Asia/Seoul')
    assert got['by_bucket'] == {} and len(b.calls) == 1


def test_daily_channel_stats_single_stat_keeps_single_query(monkeypatch):
    rows = _make_rows(datetime(2026, 6, 1, tzinfo=_UTC), 48, 3, holes=False)
    b = _Backend(rows)
    monkeypatch.setattr(influx, 'query_string', b)
    got = pj_calc.daily_channel_stats(_DM(), 'a', 'b', 'Asia/Seoul',
                                      stats=('mean',))
    assert len(b.calls) == 1 and b.calls[0].get('group_fn') == 'mean'
    assert all(v['min'] is None and v['max'] is None
               for v in got['by_bucket'].values())


class _S:
    measurement_db_version = '2'
    measurement_db_host = 'x'
    measurement_db_port = 1
    measurement_db_user = measurement_db_password = ''
    measurement_db_dbname = 'b'
    measurement_db_retention_policy = ''


def test_flux_multi_stat_is_one_union_query():
    q = influx._flux_query_and_conn(
        _S(), 'C', 'dev', channel='0', start_str='a', end_str='b',
        group_sec=3600, group_fns=('max', 'min'))[2]
    assert q.count('from(bucket') == 1
    assert 'union(tables: [max_s, min_s])' in q and '_stat' in q
    # 기본 경로는 그대로
    single = influx._flux_query_and_conn(
        _S(), 'C', 'dev', channel='0', start_str='a', end_str='b',
        group_sec=3600, group_fn='max')[2]
    assert 'union' not in single and 'fn: max' in single
