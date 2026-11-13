# coding=utf-8
"""Sonnet 4차 점검(2026-10-09)에서 나온 세 가지.

1. 시설 ID 가 도구마다 달랐다 — 공간 트리는 도형 ID, 제어 상태·작물 현황·이상
   점검은 시설 행 ID. 트리에서 본 ID 로 이상 점검을 부르면 센서 0개였다.
2. 이상 점검이 '이상 없음' 이라 25일째 무응답인 센서가 대화에서 사라졌다 —
   장애 판정은 그대로 두고 관찰로 곁에 싣는다.
3. 누적 DLI/GDD 가 비면 '안 돌았거나 꺼짐' 이라고만 해 원인을 추측해야 했다.
"""
import os
import types
from unittest import mock

from aot.tools.aot_data_tool_service import AoTDataToolService as S
from aot.tools.data_tools import measurement as M

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_anomalies_facility_scope_accepts_the_tree_id():
    seen = {}

    def fake_summary(scope_type, scope_id):
        seen['args'] = (scope_type, scope_id)
        return {}
    fac = types.SimpleNamespace(unique_id='fac-row', sensors=[])
    with mock.patch.object(S, '_resolve_facility', return_value=fac), \
            mock.patch.object(S, '_silent_devices_in_scope', return_value=None), \
            mock.patch('aot.tools.providers.get', return_value=fake_summary):
        out = S.get_anomalies(scope_type='facility', scope_id='shape-id')
    assert seen['args'] == ('facility', 'fac-row')
    assert out['scope']['id'] == 'fac-row'


def test_anomalies_unknown_facility_is_an_error_not_zero_devices():
    with mock.patch.object(S, '_resolve_facility', return_value=None):
        out = S.get_anomalies(scope_type='facility', scope_id='nope')
    assert 'error' in out


def test_silent_devices_are_an_observation_in_scope():
    """허용 시간(주기 ×3, 하한 300초) 안에 값이 없는 장치만 — 30일을 거슬러
    찾지 않는다(그게 7~8초였다). 창은 그 장치의 허용 시간이다."""
    devs = [types.SimpleNamespace(unique_id='a', name='온습도_4', period=300),
            types.SimpleNamespace(unique_id='b', name='온습도_9', period=300),
            types.SimpleNamespace(unique_id='c', name='일1회', period=86400)]
    q = mock.MagicMock()
    q.filter_by.return_value.all.return_value = devs
    windows = {}

    full_ages = {'a': 25 * 86400, 'c': None, 'b': 10.0}

    def last_seen(uid, window_s=None, max_channels=None):
        if max_channels == 1:                 # 1단계: 첫 채널, 허용 시간 창
            windows[uid] = window_s
            return (None, None, None) if uid in ('a', 'c') else (10.0, 'x', 'ch0')
        age = full_ages[uid]                  # 2단계: freshness 와 같은 조회
        return (age, 'x', 'ch0') if age is not None else (None, None, None)
    with mock.patch.object(M, 'Input', types.SimpleNamespace(query=q)), \
            mock.patch('aot.services.resolvers.device_resolver.ai_excluded',
                       return_value=False), \
            mock.patch.object(S, '_last_seen_seconds', side_effect=last_seen), \
            mock.patch('aot.space.device_membership.PlaceIndex',
                       side_effect=RuntimeError('no db')):
        allscope = S._silent_devices_in_scope('system', None)
        with mock.patch('aot.space.device_membership.place_members',
                        return_value={'a'}):
            zone = S._silent_devices_in_scope('zone', 'z1')
    assert allscope['count'] == 2
    # 30일 넘게 조용한 장치는 dormant 로 분리되어 목록에 남는다(E4 silent_level).
    assert [e['name'] for e in allscope['examples']] == ['온습도_4']
    assert allscope['dormant_count'] == 1
    assert {e['name']: e['silent_for'] for e in allscope['dormant']}['일1회'] == 'no value in 30 days'
    assert windows['a'] == 900 and windows['c'] == 3 * 86400   # 같은 허용 시간 규칙
    assert zone['count'] == 1


def test_anomalies_attach_silent_devices_with_a_reading():
    with mock.patch('aot.tools.providers.get', return_value=lambda t, i: {}), \
            mock.patch.object(S, '_silent_devices_in_scope',
                              return_value={'count': 1, 'never_reported': 0,
                                            'examples': []}):
        out = S.get_anomalies()
    assert out['silent_devices']['count'] == 1
    assert 'NOT faults' in out['_reading'][0]


def test_cumulative_says_the_tracker_is_off():
    fn = types.SimpleNamespace(custom_options='{"cumulative_tracker_enabled": false}')
    q = mock.MagicMock()
    q.filter_by.return_value.first.return_value = fn
    with mock.patch('aot.functions.utils.env_control.cumulative_tracker.load_recent_state',
                    return_value=[]), \
            mock.patch.object(M, 'CustomController', types.SimpleNamespace(query=q)):
        out = S.get_cumulative_status(function_id='f1')
    assert out['tracker_enabled'] is False
    assert 'turned OFF' in out['summary']


def test_facility_tools_share_one_resolver():
    src = {n: open(os.path.join(_ROOT, 'tools', 'data_tools', n), encoding='utf-8').read()
           for n in ('device.py', 'space.py', 'measurement.py')}
    assert 'cls._resolve_facility(facility_id)' in src['device.py']        # 제어 상태
    assert src['space.py'].count('cls._resolve_facility(') >= 2           # 작물 현황·용량
    assert 'cls._resolve_facility(scope_id)' in src['measurement.py']     # 이상 점검
    assert "n['facility_id'] = fid" in src['space.py']                    # 트리
