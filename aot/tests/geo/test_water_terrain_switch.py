# coding=utf-8
"""
물 회로 지형(DEM) 바꾸기 (계획서 15·16절 T6) — 네트워크·DB 없음, 합성 표본기.

미리보기 비교(합계·압력·바뀌는 구간) / 지금 DEM 이 없을 때 / 계산 중 단일 비행·재시작 / 실패 사유 /
활성화는 후보만 켜고 되돌리기가 그대로 복원 / 다른 DEM 으로 다시 바뀌면 되돌리기 기록은 무시.
"""
import pytest
from flask import Flask

from aot.tests.geo.test_water_terrain_cache import FakeSampler, _net
from aot.utils import water_net_link, water_terrain as W, water_terrain_switch as S

SLOPE_A = lambda x, z: 0.05 * x      # 5 %
SLOPE_B = lambda x, z: 0.20 * x      # 20 %


class Row:
    def __init__(self, uid, name, active):
        self.unique_id, self.name, self.is_activated = uid, name, active


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(W, 'cache_root', lambda: str(tmp_path / 'wtc'))
    monkeypatch.setattr(W, '_last_attempt', {})
    monkeypatch.setattr(W, '_inflight', set())
    monkeypatch.setattr(W, '_submit', lambda fn: fn())
    monkeypatch.setattr(S, '_previews', {})
    cur = FakeSampler(SLOPE_A, url='http://a.invalid/{z}/{x}/{y}.png')
    cand = FakeSampler(SLOPE_B, url='http://b.invalid/{z}/{x}/{y}.png')
    st = {'cur': cur, 'cand': cand, 'net': _net(), 'rows': [Row('a', 'AWS', True), Row('b', 'Mapterhorn', False)],
          'current_id': 'a'}
    monkeypatch.setattr(W, '_sampler', lambda: st['cur'])
    monkeypatch.setattr(S, 'candidate_sampler', lambda lid: st['cand'] if lid == 'b' else None)
    monkeypatch.setattr(S, '_dem_rows', lambda: st['rows'])
    monkeypatch.setattr(S, 'current_id', lambda: st['current_id'])
    monkeypatch.setattr(water_net_link, 'network_for_map', lambda m: _net() if st['net'] is not None else None)
    monkeypatch.setattr(water_net_link, '_emitter_points', lambda n: {})
    monkeypatch.setattr(water_net_link, '_emitter_flows', lambda n, m, p: {e.id: e.flow_lph for e in n.emitters})
    monkeypatch.setattr(water_net_link, '_emitter_pressures', lambda n, m, p: {e.id: 2.0 for e in n.emitters})

    def fake_areas(net, map_uuid, points, terrain=water_net_link._AUTO):
        ids = [e.id for e in net.emitters]
        return [{'id': 'z1', 'name': '구역', 'pressure': [
            water_net_link.pressure_brief(r) for r in water_net_link._pressure_rows(net, map_uuid, ids, None, terrain)]}]
    monkeypatch.setattr(water_net_link, '_area_rows', fake_areas)

    applied = []

    def fake_apply(rows, active_ids):
        applied.append(set(active_ids))
        for r in rows:
            r.is_activated = r.unique_id in active_ids
        st['current_id'] = next((r.unique_id for r in rows if r.is_activated), None)
    monkeypatch.setattr(S, '_apply_active', fake_apply)
    monkeypatch.setattr(S, '_switch_path', lambda: str(tmp_path / 'switch.json'))
    app = Flask('t')
    with app.app_context():
        yield st, applied


def _ready_current(st):
    W.build('m1', _net(), st['cur'])


def test_preview_compares_current_with_candidate(env):
    st, _ = env
    _ready_current(st)
    got = S.start_preview('m1', 'b')
    assert got['state'] == 'ready' and got['candidate'] == {'id': 'b', 'name': 'Mapterhorn'}
    r = got['result']
    t = r['totals']
    assert t['pipes'] == 1 and t['horizontal_m'] == pytest.approx(100.0)
    assert t['slant_before'] == pytest.approx(100.0 * 1.0025 ** 0.5, rel=1e-3)
    assert t['slant_after'] == pytest.approx(100.0 * 1.04 ** 0.5, rel=1e-3)
    assert t['unknown_before'] == 0 and t['unknown_after'] == 0
    circuit = r['areas'][0]['circuits'][0]
    assert circuit['level_before'] and circuit['level_after']
    assert circuit['bar_after'][0] is not None
    assert r['segments_total'] >= 1 and r['segments']
    sg = r['segments'][0]
    assert sg['kind'] == 'main' and sg['slant_after'] > sg['slant_before']
    # 후보의 계보 캐시가 저장돼 활성화하면 바로 ready 다
    assert W.read_entry('m1', W.cache_key('m1', _net(), st['cand'])) is not None


def test_preview_without_current_dem_has_no_before_numbers(env):
    st, _ = env
    st['cur'] = None
    got = S.start_preview('m1', 'b')
    t = got['result']['totals']
    assert got['state'] == 'ready' and t['slant_before'] is None and t['unknown_before'] is None
    assert t['slant_after'] > t['horizontal_m']
    assert got['result']['segments']                       # 이전에 지형이 없었으면 수평 길이와 견준다


def test_same_dem_shows_no_changed_segments(env):
    st, _ = env
    st['cand'] = FakeSampler(SLOPE_A, url='http://a2.invalid/{z}/{x}/{y}.png')
    _ready_current(st)
    r = S.start_preview('m1', 'b')['result']
    assert r['segments_total'] == 0 and r['segments'] == []


def test_uncovered_pipes_are_reported(env):
    st, _ = env
    st['cand'] = FakeSampler(SLOPE_B, url='http://c.invalid/{z}/{x}/{y}.png', known=lambda x, z: x < 50)
    _ready_current(st)
    t = S.start_preview('m1', 'b')['result']['totals']
    assert t['unknown_before'] == 0 and t['unknown_after'] == 1


def test_single_flight_while_warming_and_restart_when_done(env, monkeypatch):
    st, _ = env
    jobs = []
    # 지금 DEM 의 선계산 예약(terrain_ref 가 낸다)은 세지 않는다 — 미리보기 일만 센다
    monkeypatch.setattr(W, '_submit', lambda fn: jobs.append(fn) if 'start_preview' in fn.__qualname__ else None)
    first = S.start_preview('m1', 'b')
    again = S.start_preview('m1', 'b', restart=True)       # 계산 중에는 새로 시작하지 않는다
    assert first['state'] == again['state'] == 'warming' and len(jobs) == 1
    jobs[0]()
    assert S.start_preview('m1', 'b')['state'] == 'ready'
    assert len(jobs) == 1                                   # 끝난 것을 다시 읽는 건 일을 만들지 않는다
    S.start_preview('m1', 'b', restart=True)                # 새 후보를 고를 때는 처음부터
    assert len(jobs) == 2


def test_failures_have_reasons(env):
    st, _ = env
    assert S.start_preview('m1', 'zzz') == {'state': 'failed', 'reason': 'not-found', 'candidate': None}
    st['rows'].append(Row('c', 'Broken', False))
    assert S.start_preview('m1', 'c')['reason'] == 'no-sampler'
    st['net'] = None
    assert S.start_preview('m1', 'b')['state'] == 'empty'


def test_timeout_does_not_store(env, monkeypatch):
    st, _ = env
    monkeypatch.setattr(W, 'warm_tiles', lambda net, sampler, deadline: False)
    assert S.start_preview('m1', 'b')['reason'] == 'timeout'


def test_background_exception_is_contained(env, monkeypatch):
    monkeypatch.setattr(S, 'compare', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    got = S.start_preview('m1', 'b')
    assert got['state'] == 'failed' and got['reason'] == 'error'


def test_state_lists_other_dems_only(env):
    st, _ = env
    s = S.state()
    assert s['current'] == {'id': 'a', 'name': 'AWS'} and s['candidates'] == [{'id': 'b', 'name': 'Mapterhorn'}]
    assert s['switched'] is None
    assert 'key' not in str(s).lower()


def test_activate_turns_others_off_and_revert_restores(env):
    st, applied = env
    st['rows'] = [Row('a', 'AWS', True), Row('b', 'Mapterhorn', False), Row('c', 'MapTiler', True)]
    got = S.activate('b')
    assert got['ok'] and applied[-1] == {'b'}
    assert got['current']['id'] == 'b' and got['switched']['from']['id'] == 'a' and got['switched']['to']['id'] == 'b'
    back = S.revert()
    assert back['ok'] and applied[-1] == {'a', 'c'}         # 그때 켜져 있던 입력 그대로
    assert back['switched'] is None and S.revert()['reason'] == 'nothing-to-revert'


def test_activate_edge_cases(env):
    st, applied = env
    assert S.activate('zzz') == {'ok': False, 'reason': 'not-found'}
    assert S.activate('a') == {'ok': False, 'reason': 'already-active'} and not applied


def test_revert_record_is_ignored_after_another_change(env):
    st, applied = env
    S.activate('b')
    st['current_id'] = 'a'                                   # 사용자가 다른 곳에서 다시 바꿨다
    assert S.state()['switched'] is None
    assert S.revert() == {'ok': False, 'reason': 'nothing-to-revert'}


def test_site_and_zone_rows_do_not_double_count_segments(env, monkeypatch):
    """대지는 구역을 품어 같은 배관 구간이 두 행에 나온다 — 바뀌는 구간은 물리 구간 하나로 센다."""
    st, _ = env
    _ready_current(st)
    one = S.start_preview('m1', 'b')['result']
    base = water_net_link._area_rows
    monkeypatch.setattr(S, '_previews', {})

    def nested(net, map_uuid, points, terrain=water_net_link._AUTO):
        rows = base(net, map_uuid, points, terrain=terrain)
        return rows + [dict(rows[0], id='z-inner', name='안쪽 구역')]      # 같은 회로·같은 구간이 구역에도 든다
    monkeypatch.setattr(water_net_link, '_area_rows', nested)
    two = S.start_preview('m1', 'b')['result']
    assert len(two['areas']) == 2                                           # 압력 행은 소속마다 따로 나온다
    assert two['segments_total'] == one['segments_total'] >= 1
    keys = [(sg['pipe'], sg['s_a'], sg['s_b']) for sg in two['segments']]
    assert len(keys) == len(set(keys))
