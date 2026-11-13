# coding=utf-8
"""센서 조회가 쏟아지지 않게 — 2026-10-31 사용자 지적 "AI 센서 조회 때 모든 데이터가 쏟아진다".

고정하는 계약(도메인 표면 measure.* 만 줄고, 안쪽 도구의 다른 소비자는 그대로):
  1. measure.history — 측정 항목도 limit 도 안 정하면 채널마다 최소·최대·평균·건수와 최소·최대 시각 한 줄(값 목록 없음).
     정하면 값 목록 — 최근 N 건이 아니라 기간 전체를 N 칸으로 나눈 평균(2026-11-09 음성 시험: '어제 온도' 에
     밤 11시대 20건만 갔다). 통계는 예전 숫자 그대로. `zone_pick` 은 규칙 문장 없이 짧다. 더 받는 길은 응답의 `next`.
  2. measure.summary 대상 없음 — 곳마다 평균 대신 대지마다 한 줄. 대지는 빠짐없이(25곳에서 자르지 않는다).
     대상이나 측정 종류를 주면 예전 모양 그대로.
  3. measure.channels — 이름·단위 표(같은 계열은 묶음, id 없음). `measurement` 를 주면 그 채널만 id·select_value 와.
     detail.device 는 `channels` 와 `measurements` 가 같은 표를 두 번 싣지 않는다.
  4. measure.freshness — 끊긴 장치만 이름, 나머지는 개수. 판정은 그대로. `include_fresh` 면 예전 전체 모양.

켜는 곳은 도메인 명부의 `defaults_by_kind` 의 처리기 인자 `brief` 하나다 — 인앱 AI·날씨·트윈·화면 값 읽기는 이 인자를
안 주므로 응답이 바뀌지 않는다. 라이브 DB·Influx 를 쓰지 않는다(임시 sqlite, 읽기 가짜).
"""
import copy
import inspect
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from aot.databases.models import DeviceMeasurements, GeoShape, Input
from aot.tests.test_classify_sensors import _ClsBase, _marker
from aot.tests.test_place_membership import _point, _poly
from aot.tests.test_place_members_split import _input


def _tokens(value):
    from aot.tools import tool_execution as te
    return te._estimate_tokens(json.dumps(value, ensure_ascii=False))


def _lines(out):
    """통계 한 줄 모양(columns + rows) → 채널마다 사전."""
    cols = out['channels']['columns']
    return [dict(zip(cols, row)) for row in out['channels']['rows']]


def _channels(uid, rows):
    """장치에 채널을 단다 — rows = [(측정 이름, 단위, 이름)]."""
    for i, (meas, unit, name) in enumerate(rows):
        DeviceMeasurements(device_id=uid, channel=i, measurement=meas, unit=unit, name=name).save()


class _Base(_ClsBase):

    def _svc(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    _NOW = datetime(2026, 10, 31, 3, 0, tzinfo=timezone.utc)

    def _rows(self, n=30, base=20.0):
        now = self._NOW
        return [(now - timedelta(minutes=i), base + i * 0.1) for i in range(n)][::-1]

    def _history(self, **kw):
        S = self._svc()
        with mock.patch('aot.tools.data_tools.measurement.read_influxdb_list',
                        side_effect=lambda did, unit, ch, **k: self._rows(30, 20.0 + ch)), \
                mock.patch.object(S, '_check_influxdb_available', return_value=(True, 'OK')), \
                mock.patch('aot.tools.data_tools.measurement.utc_now', return_value=self._NOW), \
                mock.patch('aot.utils.inputs.model_input_drivers', return_value=set()):
            return S.get_sensor_detail(**kw)


# ── 1. measure.history ──────────────────────────────────────────────────────

class TestHistoryBrief(_Base):

    def setUp(self):
        super(TestHistoryBrief, self).setUp()
        _input('dev-multi', '기상대 시험')
        _channels('dev-multi', [('temperature', 'C', ''), ('humidity', 'percent', ''),
                                ('rssi', 'dBm', '')])
        # 구역 3-1 에 센서 둘.
        for uid, name, x, y in (('z-1', '온습도_5', 20, 20), ('z-2', '온습도_6', 25, 15)):
            _input(uid, name)
            _channels(uid, [('temperature', 'C', ''), ('humidity', 'percent', '')])
            _marker(uid, uid, x, y)

    def test_without_a_measurement_each_channel_is_one_statistics_line(self):
        out = self._history(loc_id='dev-multi', brief=True)
        self.assertIsInstance(out, dict)
        self.assertEqual('success', out['status'])
        self.assertEqual('기상대 시험', out['device_name'])
        self.assertEqual(['measurement', 'unit', 'min', 'min_at', 'max', 'max_at', 'avg', 'count'],
                         out['channels']['columns'])
        self.assertEqual(['temperature', 'humidity', 'rssi'], [c['measurement'] for c in _lines(out)])
        for row in out['channels']['rows']:
            self.assertEqual(8, len(row))
        self.assertNotIn('readings', json.dumps(out['channels']))
        self.assertNotIn('zone_pick', out)

    def test_channels_that_share_a_measurement_name_stay_tellable_apart(self):
        _input('dev-fc', '예보')
        _channels('dev-fc', [('rain', 'mm', 'Rain +0d'), ('rain', 'mm', 'Rain +1d'), ('temperature', 'C', '')])
        out = self._history(loc_id='dev-fc', brief=True)
        self.assertEqual(['measurement', 'name', 'unit', 'min', 'min_at', 'max', 'max_at', 'avg', 'count'],
                         out['channels']['columns'])
        self.assertEqual(['Rain +0d', 'Rain +1d', ''], [c['name'] for c in _lines(out)])
        # 이름이 하나도 없는 장치는 열을 더하지 않는다(위 테스트의 8열).

    def test_the_statistics_are_the_same_numbers_as_before(self):
        old = self._history(loc_id='dev-multi')
        new = self._history(loc_id='dev-multi', brief=True)
        for o, n in zip(old, _lines(new)):
            self.assertEqual(o['stats'], {k: n[k] for k in ('min', 'max', 'avg', 'count')})
            self.assertEqual((o['measurement'], o['readings'][0]['u']), (n['measurement'], n['unit']))

    def test_the_statistics_say_when_the_low_and_the_high_were(self):
        # "어제 최고 온도는 몇 시" — 값 목록 없이도 답이 나와야 한다. _rows 는 시간이 갈수록 값이 준다
        # → 가장 이른 값이 최대(02:31), 가장 늦은 값이 최소(03:00).
        line = _lines(self._history(loc_id='dev-multi', brief=True))[0]
        self.assertIn('T03:00', line['min_at'])
        self.assertIn('T02:31', line['max_at'])
        self.assertNotIn('.', line['max_at'])                         # 분까지 — 마이크로초를 싣지 않는다
    def test_the_way_to_get_more_is_in_the_answer(self):
        out = self._history(loc_id='dev-multi', brief=True)
        self.assertIn("measurement=", out['next']['call'])
        self.assertIn("samples=", out['next']['call'])               # 이 표면의 인자 이름(limit 아님)
        self.assertIn("spread across the period", out['next']['call'])

    def test_naming_a_measurement_gives_readings_with_the_same_statistics(self):
        old = self._history(loc_id='dev-multi', sensor_type='humidity')
        new = self._history(loc_id='dev-multi', sensor_type='humidity', brief=True)
        self.assertIsInstance(new, list)
        self.assertEqual(old[0]['stats'], {k: v for k, v in new[0]['stats'].items()
                                           if k not in ('min_at', 'max_at')})
        self.assertIn('min_at', new[0]['stats'])
        self.assertEqual(30, new[0]['total_readings'])

    def test_a_limit_spreads_that_many_points_over_the_period(self):
        # 1시간을 6칸(10분)으로. 값은 02:31~03:00 에만 있다 → 앞 세 칸은 비어 빠지고 세 점이 남는다(끊김이 보인다).
        new = self._history(loc_id='dev-multi', limit=6, time_range='1h', brief=True)
        pts = new[0]['readings']
        self.assertEqual(3, len(pts))
        self.assertIn('3 averages of 10 min slots', new[0]['readings_shown'])
        self.assertIn('T02:30', pts[0]['t'])
        # 칸마다 평균 — 02:30~02:40 칸에는 02:31~02:39 의 9건이 든다.
        raw = [v for _t, v in self._rows(30, 20.0)]
        self.assertAlmostEqual(round(sum(raw[:9]) / 9, 2), pts[0]['v'])

    def test_a_whole_day_comes_back_hour_by_hour_not_the_last_hour(self):
        # 2026-11-09 음성 시험: '어제 온도' 에 5분 간격 287건 중 밤 22:23~23:58 의 20건만 갔다.
        S = self._svc()
        t0 = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)            # 서울 11-08 00:00
        data = [(t0 + timedelta(minutes=5 * i), float(i // 12)) for i in range(288)]   # 시마다 값 = 그 시
        pts, slot = S._spread_readings(data, 24, (t0, t0 + timedelta(days=1)), 'C', 'Asia/Seoul', {})
        self.assertEqual('60 min', slot)
        self.assertEqual(24, len(pts))
        self.assertEqual('2026-11-08T00:00+09:00', pts[0]['t'])
        self.assertEqual('2026-11-08T23:00+09:00', pts[-1]['t'])
        self.assertEqual([float(h) for h in range(24)], [p['v'] for p in pts])

    def test_slots_are_even_in_real_time_across_a_dst_change(self):
        # 뉴욕 2026-11-01 은 25시간(02:00 EDT → 01:00 EST). 칸은 실제 시간으로 똑같이 나누고 표시는 그곳 오프셋.
        S = self._svc()
        t0 = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)             # 00:00 EDT
        t1 = datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)             # 다음 날 00:00 EST
        data = [(t0 + timedelta(minutes=10 * i), 1.0) for i in range(150)]
        pts, slot = S._spread_readings(data, 25, (t0, t1), 'C', 'America/New_York', {})
        self.assertEqual('60 min', slot)
        self.assertEqual(25, len(pts))
        self.assertEqual('2026-11-01T00:00-04:00', pts[0]['t'])
        self.assertEqual('2026-11-01T01:00-04:00', pts[1]['t'])
        self.assertEqual('2026-11-01T01:00-05:00', pts[2]['t'])           # 같은 01시가 두 번 — 오프셋으로 구별
        self.assertEqual('2026-11-01T23:00-05:00', pts[-1]['t'])

    def test_few_readings_come_back_as_they_are(self):
        # 칸 수보다 적으면 평균하지 않는다 — 원값 그대로(짧은 구간 'FROM/TO' 의 정확한 값).
        new = self._history(loc_id='dev-multi', sensor_type='humidity', limit=50, brief=True)
        self.assertEqual(30, len(new[0]['readings']))
        self.assertNotIn('readings_shown', new[0])

    def test_other_consumers_do_not_pass_brief_and_keep_the_list(self):
        # 인앱 AI·날씨·화면 값 읽기는 brief 를 안 준다 — 기본이 꺼짐이어야 한다.
        sig = inspect.signature(self._svc().get_sensor_detail)
        self.assertIs(False, sig.parameters['brief'].default)
        out = self._history(loc_id='dev-multi')
        self.assertIsInstance(out, list)
        self.assertEqual(5, len(out[0]['readings']))                  # 채널이 여럿이면 5건
        one = self._history(loc_id='dev-multi', time_range='1h', limit=1)
        self.assertEqual(1, len(one[0]['readings']))                  # 화면 값 읽기(limit=1)

    def test_a_zone_names_the_device_that_answered_without_the_rule_text(self):
        out = self._history(loc_id='zone-a', brief=True)
        pick = out['zone_pick']
        self.assertEqual(1 + len(pick['other_devices']), pick['devices_in_zone'])
        self.assertGreaterEqual(pick['devices_in_zone'], 2)
        self.assertNotIn(pick['answered_by'], pick['other_devices'])
        self.assertEqual({'answered_by', 'devices_in_zone', 'other_devices'}, set(pick))
        self.assertNotIn('selection_rule', json.dumps(out))
        self.assertIn("measure(op='latest'", out['next']['why'])      # 한 대의 값 — 구역 전체는 latest 로(옛 이름 summary 아님)

    def test_a_zone_with_a_measurement_keeps_the_readings_and_a_short_zone_pick(self):
        old = self._history(loc_id='zone-a', sensor_type='temperature')
        new = self._history(loc_id='zone-a', sensor_type='temperature', brief=True)
        self.assertEqual([r['stats'] for r in old],
                         [{k: v for k, v in r['stats'].items() if k not in ('min_at', 'max_at')}
                          for r in new])
        self.assertEqual([r['total_readings'] for r in old], [r['total_readings'] for r in new])
        self.assertIn('selection_rule', old[0]['zone_pick'])
        self.assertNotIn('selection_rule', new[0]['zone_pick'])
        self.assertNotIn('note', new[0]['zone_pick'])
        self.assertEqual(old[0]['zone_pick']['answered_by'], new[0]['zone_pick']['answered_by'])
        self.assertEqual(old[0]['zone_pick']['devices_in_zone'], new[0]['zone_pick']['devices_in_zone'])

    def test_several_targets_share_one_next(self):
        out = self._history(loc_ids=['dev-multi', 'z-1'], brief=True)
        self.assertEqual(2, out['count'])
        self.assertIn('next', out)
        for r in out['results']:
            self.assertNotIn('next', r)
            self.assertIn('channels', r)

    def test_forty_channels_are_much_smaller(self):
        _input('dev-big', '예보')
        DeviceMeasurements.query.filter_by(device_id='dev-big').delete()
        _channels('dev-big', [('temperature' if i % 2 else 'humidity', 'C', 'Ch %d +%dh' % (i, i))
                              for i in range(40)])
        old = _tokens(self._history(loc_id='dev-big'))
        new = _tokens(self._history(loc_id='dev-big', brief=True))
        print('history 40 channels: %d -> %d tokens' % (old, new))
        self.assertLess(new, old * 0.5)

    def test_the_zone_answer_is_much_smaller(self):
        old = _tokens(self._history(loc_id='zone-a'))
        new = _tokens(self._history(loc_id='zone-a', brief=True))
        print('history zone: %d -> %d tokens' % (old, new))
        # 0.35 → 0.4 (2026-11-09): 채널마다 최소·최대 시각(`min_at`·`max_at`)이 붙었다 — "최고 온도는 몇 시" 를
        # 다시 조회하지 않고 답하게 하는 값이다. 2채널 구역에서 +약 50 토큰.
        self.assertLess(new, old * 0.4)

    def test_the_domain_surface_turns_brief_on_for_every_target_kind(self):
        from aot.tools.domain import dispatch
        for kind in ('input', 'output', 'device', 'zone', 'site', 'facility'):
            v = _plan('measure', {'op': 'history'}, kind)
            self.assertEqual(('call', 'get_sensor_detail'), v[:2], kind)
            self.assertIs(True, v[2]['brief'], kind)
        v = _plan('measure', {'op': 'history', 'measurement': 'humidity'}, 'zone')
        self.assertEqual('humidity', v[2]['sensor_type'])             # 안쪽이 보고 예전 모양으로 돌린다
        self.assertTrue(dispatch)


def _plan(tool, args, kind='input'):
    from aot.tools.domain import dispatch

    def resolve(ref, **kw):
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref), 'path': 'map > %s' % ref,
                      'matched': 'exact'}
    a = dict({'target': 'x'} if kind != 'none' else {}, **args)
    with mock.patch.object(dispatch.targets, 'resolve', resolve), \
            mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
        return dispatch.plan(tool, a)


# ── 2. measure.summary 대상 없음 ─────────────────────────────────────────────

class TestSummaryBrief(_Base):

    ZONE_FAR = [[500, 0], [500, 50], [550, 50], [550, 0], [500, 0]]
    SITE_EMPTY = [[1000, 0], [1000, 50], [1050, 50], [1050, 0], [1000, 0]]

    def setUp(self):
        super(TestSummaryBrief, self).setUp()
        # 어느 대지에도 안 든 구역 + 센서.
        GeoShape(unique_id='zone-far', geo_id='m1', type='zone',
                 feature=_poly(self.ZONE_FAR, '외딴 구역')).save()
        _input('far-1', '외딴 센서', 'temperature', 'humidity')
        _marker('far-1', 'far-1', 520, 20)
        # 장치가 없는 대지.
        GeoShape(unique_id='site-empty', geo_id='m1', type='site',
                 feature=_poly(self.SITE_EMPTY, '빈 대지')).save()
        self.vals = {('fs-in', 0): 20.0, ('fs-unset', 0): 22.0, ('fs-geo', 0): 24.0,
                     ('open-site', 0): 18.0, ('zone-s', 0): 16.0, ('s2-sensor', 0): 21.5,
                     ('far-1', 0): 30.0, ('far-1', 1): 40.0}
        self.ages = {}

    def _summary(self, **kw):
        from aot.space import shape_index
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        shape_index.invalidate()
        now = datetime.now(timezone.utc)

        def _read(did, unit, channel, *a, **k):
            return [(now - timedelta(seconds=self.ages.get(did, 0)), self.vals.get((did, channel), 20.0))]
        with mock.patch('aot.utils.influx.read_influxdb_list', side_effect=_read), \
                mock.patch('aot.utils.inputs.model_input_drivers', return_value=set()):
            return S.get_zone_sensor_summary(**kw)

    def test_every_site_is_there_one_line_each_and_none_is_cut(self):
        out = self._summary(brief=True)
        named = [s['site'] for s in out['sites']] + out['no_environment_data']
        self.assertEqual({'3포장', '1포장', '외딴 구역', '빈 대지'}, set(named))
        self.assertEqual(4, len(named))
        self.assertNotIn('truncated', out)
        self.assertNotIn('zones', out)
        self.assertEqual(['빈 대지'], out['no_environment_data'])
        self.assertEqual({s['site'] for s in out['sites']}, {'3포장', '1포장', '외딴 구역'})

    def test_a_zone_outside_every_site_is_not_dropped(self):
        out = self._summary(brief=True)
        far = [s for s in out['sites'] if s['site'] == '외딴 구역'][0]
        self.assertEqual('zone', far['kind'])
        self.assertEqual({'temperature': 30.0, 'humidity': 40.0}, far['groups'][0]['avg'])

    def test_it_does_not_cut_at_twenty_five_places(self):
        for i in range(30):
            GeoShape(unique_id='many-%d' % i, geo_id='m1', type='site',
                     feature=_poly([[2000 + i * 100, 0], [2000 + i * 100, 50],
                                    [2050 + i * 100, 50], [2050 + i * 100, 0],
                                    [2000 + i * 100, 0]], '대지%02d' % i)).save()
        out = self._summary(brief=True)
        names = [s['site'] for s in out['sites']] + out['no_environment_data']
        self.assertEqual(4 + 30, len(names))
        self.assertEqual(34, len(set(names)))
        self.assertNotIn('truncated', out)

    def test_values_are_the_same_numbers_as_the_group_averages(self):
        out = self._summary(brief=True)
        site2 = [s for s in out['sites'] if s['site'] == '1포장'][0]
        old = [z for z in self._summary(zone_ids=['site2'])['zones'] if z['zone_id'] == 'site2'][0]
        old_avg = {a['measurement']: a['avg_last'] for g in old['groups'] for a in g['avg']}
        self.assertEqual({'temperature': old_avg['temperature']}, site2['groups'][0]['avg'])
        three = [s for s in out['sites'] if s['site'] == '3포장'][0]
        fac = [g for g in three['groups'] if g['placement'] == 'facility'][0]
        self.assertEqual(22.0, fac['avg']['temperature'])             # (20 + 22 + 24) / 3
        self.assertEqual(3, fac['devices'])

    def test_outdoor_stays_a_reference_group_and_is_never_mixed(self):
        _input('wx', '기상대', 'temperature', 'radiation')
        _marker('wx', 'wx', 55, 85)
        self.vals[('wx', 0)] = 5.0
        out = self._summary(brief=True)
        three = [s for s in out['sites'] if s['site'] == '3포장'][0]
        ref = [g for g in three['groups'] if g.get('reference')]
        self.assertEqual(1, len(ref))
        self.assertEqual('outdoor', ref[0]['placement'])
        self.assertTrue(all(not g.get('reference') for g in three['groups'] if g['placement'] != 'outdoor'))

    def test_silent_devices_are_counted_on_the_line(self):
        self.ages = {'fs-unset': 3 * 3600}
        out = self._summary(brief=True)
        three = [s for s in out['sites'] if s['site'] == '3포장'][0]
        self.assertEqual(1, three['silent_devices'])
        fac = [g for g in three['groups'] if g['placement'] == 'facility'][0]
        self.assertEqual(2, fac['devices'])

    def test_the_way_to_narrow_is_in_the_answer(self):
        out = self._summary(brief=True)
        self.assertIn("target=<a site name", out['next']['call'])
        self.assertIn("measurement=", out['next']['call'])

    def test_with_a_target_the_shape_is_exactly_the_old_one(self):
        old = self._summary(zone_ids=['site'])
        new = self._summary(zone_ids=['site'], brief=True)
        self.assertEqual(old, new)

    def test_with_a_measurement_and_no_target_the_shape_is_the_old_one(self):
        old = self._summary(measurement_type='temperature')
        new = self._summary(measurement_type='temperature', brief=True)
        self.assertEqual(old, new)
        self.assertIn('zones', new)

    def test_the_inner_default_is_off_so_the_in_app_overview_keeps_its_shape(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        self.assertIs(False, inspect.signature(S.get_zone_sensor_summary).parameters['brief'].default)
        out = self._summary()
        self.assertIn('zones', out)
        self.assertNotIn('sites', out)

    def test_the_domain_surface_turns_brief_on_only_without_a_target(self):
        v = _plan('measure', {'op': 'summary'}, 'none')
        self.assertEqual(('call', 'get_zone_sensor_summary'), v[:2])
        self.assertIs(True, v[2]['brief'])
        v = _plan('measure', {'op': 'summary'}, 'zone')
        self.assertNotIn('brief', v[2])                               # 대상을 주면 예전 모양

    def test_it_is_much_smaller_and_complete(self):
        # 곳이 많은 농장 모형 — 대지 12곳, 곳마다 시설·노지 센서.
        for i in range(12):
            uid = 'big-%d' % i
            GeoShape(unique_id='site-%s' % uid, geo_id='m1', type='site',
                     feature=_poly([[3000 + i * 100, 0], [3000 + i * 100, 50],
                                    [3050 + i * 100, 50], [3050 + i * 100, 0],
                                    [3000 + i * 100, 0]], '대지 %02d' % i)).save()
            for j in range(3):
                dev = '%s-%d' % (uid, j)
                _input(dev, '센서 %d-%d' % (i, j), 'temperature', 'humidity', 'vapor_pressure_deficit')
                _marker(dev, dev, 3010 + i * 100 + j, 20)
        old = _tokens(self._summary())
        new = _tokens(self._summary(brief=True))
        print('summary no target: %d -> %d tokens' % (old, new))
        self.assertLess(new, old * 0.5)
        out = self._summary(brief=True)
        self.assertEqual(4 + 12, len(out['sites']) + len(out['no_environment_data']))


# ── 3. measure.channels · detail.device ──────────────────────────────────────

def _forecast(uid='fc-1', name='예보 장치', days=16):
    """예보 장치 모형 — 같은 계열 채널이 오프셋만 달리 여럿."""
    _input(uid, name)
    DeviceMeasurements.query.filter_by(device_id=uid).delete()
    rows = []
    for d in range(days):
        rows.append(('rain', 'mm', 'Rain (daily sum) +%dd' % d))
    for h in (1, 3, 6):
        rows.append(('temperature', 'C', 'Temperature +%dh' % h))
    rows += [('temperature', 'C', 'Window Max Temperature'), ('duration_time', 'h', 'Window Length')]
    _channels(uid, rows)
    return uid


class TestChannelsBrief(_Base):

    def _channels(self, **kw):
        return self._svc().get_device_measurements(**kw)

    def test_the_default_is_a_table_of_names_and_units_without_ids(self):
        uid = _forecast()
        out = self._channels(device_id=uid, brief=True)
        self.assertEqual('success', out['status'])
        names = [c['name'] for c in out['channels']]
        self.assertIn('Rain (daily sum) +0d~+15d', names)
        self.assertIn('Temperature +1h~+6h', names)
        self.assertIn('Window Max Temperature', names)
        rain = [c for c in out['channels'] if c['name'].startswith('Rain')][0]
        self.assertEqual({'name': 'Rain (daily sum) +0d~+15d', 'unit': 'mm', 'n': 16}, rain)
        self.assertEqual(16 + 3 + 2, out['channel_count'])
        text = json.dumps(out['channels'])
        self.assertNotIn('measurement_id', text)
        self.assertNotIn('select_value', text)
        text = json.dumps(out)
        row = DeviceMeasurements.query.filter_by(device_id=uid).first()
        self.assertNotIn(row.unique_id, text)

    def test_naming_a_measurement_gives_those_channels_with_their_ids(self):
        uid = _forecast()
        full = self._channels(device_id=uid)
        out = self._channels(device_id=uid, brief=True, measurement_type='window')
        self.assertEqual(['Window Max Temperature', 'Window Length'], [m['name'] for m in out['measurements']])
        for m in out['measurements']:
            self.assertEqual([f for f in full['measurements'] if f['measurement_id'] == m['measurement_id']], [m])
            self.assertEqual('%s,%s' % (uid, m['measurement_id']), m['select_value'])
        self.assertEqual(uid, out['device_id'])
        self.assertIn('select_by_type', out)

    def test_a_stored_measurement_name_or_a_channel_name_both_pick(self):
        uid = _forecast()
        by_meas = self._channels(device_id=uid, brief=True, measurement_type='rain')
        self.assertEqual(16, len(by_meas['measurements']))
        by_name = self._channels(device_id=uid, brief=True, measurement_type='Temperature +3h')
        self.assertEqual(['Temperature +3h'], [m['name'] for m in by_name['measurements']])

    def test_a_word_that_matches_nothing_lists_the_table_to_choose_from(self):
        uid = _forecast()
        out = self._channels(device_id=uid, brief=True, measurement_type='co2')
        self.assertEqual('not_found', out['status'])
        self.assertTrue(out['channels'])
        self.assertNotIn('select_value', json.dumps(out))

    def test_without_brief_it_is_exactly_the_old_full_answer(self):
        # 인앱 AI·장치 상세·화면 따라가기가 부르는 모양 — id 와 select_value, select_by_type.
        uid = _forecast(days=3)
        out = self._channels(device_id=uid)
        self.assertEqual({'device_id', 'measurements', 'select_by_type'}, set(out))
        self.assertEqual({'measurement_id', 'channel', 'measurement', 'unit', 'name', 'select_value'},
                         set(out['measurements'][0]))
        self.assertIs(False, inspect.signature(self._svc().get_device_measurements).parameters['brief'].default)

    def test_the_table_keeps_a_single_channel_name_as_it_is(self):
        _input('one', '하나')
        DeviceMeasurements.query.filter_by(device_id='one').delete()
        _channels('one', [('temperature', 'C', '기온'), ('humidity', 'percent', '습도')])
        out = self._channels(device_id='one', brief=True)
        self.assertEqual([{'name': '기온', 'unit': 'C', 'measurement': 'temperature'},
                          {'name': '습도', 'unit': 'percent', 'measurement': 'humidity'}], out['channels'])

    def test_it_is_much_smaller(self):
        uid = _forecast()
        old = _tokens(self._channels(device_id=uid))
        new = _tokens(self._channels(device_id=uid, brief=True))
        print('channels (21 channels): %d -> %d tokens' % (old, new))
        self.assertLess(new, old * 0.25)

    def test_the_domain_surface_asks_for_the_table_and_maps_measurement_to_the_filter(self):
        for kind in ('input', 'output', 'device'):
            v = _plan('measure', {'op': 'channels', 'measurement': 'rain'}, kind)
            self.assertEqual(('call', 'get_device_measurements'), v[:2])
            self.assertIs(True, v[2]['brief'])
            self.assertEqual('rain', v[2]['measurement_type'])

    def test_the_next_call_tells_how_to_get_the_ids(self):
        out = self._channels(device_id=_forecast(), brief=True)
        self.assertIn("measurement=", out['next']['call'])
        self.assertIn('select_value', out['next']['call'])


class TestDeviceDetailChannels(_Base):

    def _detail(self, fields):
        S = self._svc()
        with mock.patch.object(S, '_last_seen_seconds', return_value=(42.0, '2026-10-30T09:00:00+09:00', 'x')):
            return S.get_device_detail(device_id=_forecast(), fields=fields)

    def test_the_same_channel_table_is_not_carried_twice(self):
        out = self._detail(['measurements'])
        self.assertIn('measurements', out)
        self.assertNotIn('channels', out)
        self.assertTrue(out['measurements'][0]['select_value'].startswith('fc-1,'))

    def test_the_brief_groups_a_family_and_has_no_ids(self):
        out = self._detail([])
        self.assertNotIn('measurements', out)
        names = [c['name'] for c in out['channels']]
        self.assertIn('Rain (daily sum) +0d~+15d', names)
        self.assertNotIn('measurement_id', json.dumps(out))

    def test_a_short_family_is_still_whole_names(self):
        _input('two', '둘')
        DeviceMeasurements.query.filter_by(device_id='two').delete()
        _channels('two', [('temperature', 'C', '기온'), ('humidity', 'percent', '습도')])
        S = self._svc()
        with mock.patch.object(S, '_last_seen_seconds', return_value=(1.0, 'x', 'y')):
            out = S.get_device_detail(device_id='two', fields=[])
        self.assertEqual([{'name': '기온', 'unit': 'C'}, {'name': '습도', 'unit': 'percent'}], out['channels'])

    def test_it_gets_smaller(self):
        before = copy.deepcopy(self._detail(['measurements']))
        # 중복 제거 전 = 같은 응답 + 이름·단위 표.
        dup = dict(before, channels=[{'name': m['name'], 'unit': m['unit']} for m in before['measurements']])
        print('detail.device fields=measurements: %d -> %d tokens' % (_tokens(dup), _tokens(before)))
        self.assertLess(_tokens(before), _tokens(dup))


# ── 4. measure.freshness ─────────────────────────────────────────────────────

class TestFreshnessBrief(_Base):

    def setUp(self):
        super(TestFreshnessBrief, self).setUp()
        for uid, name in (('f-ok', '정상 센서'), ('f-stale', '끊긴 센서'), ('f-off', '꺼 둔 센서'),
                          ('f-none', '값 없는 센서')):
            _input(uid, name, 'temperature')
        row = Input.query.filter_by(unique_id='f-off').first()
        row.is_activated = False
        row.save()
        self.age = {'f-ok': 30.0, 'f-stale': 4 * 86400.0, 'f-off': 9 * 86400.0, 'f-none': None}

    def _fresh(self, **kw):
        S = self._svc()

        def seen(did, window_s=None):
            age = self.age.get(did, 30.0)
            return (age, None if age is None else '2026-10-31T09:00:00+09:00',
                    None if age is None else 'temperature (ch0)')
        with mock.patch.object(S, '_last_seen_seconds', side_effect=seen):
            return S.get_device_freshness(**kw)

    def test_only_the_silent_devices_are_named(self):
        out = self._fresh(brief=True)
        self.assertEqual(['끊긴 센서'], [d['name'] for d in out['stale_devices']])
        self.assertEqual(['값 없는 센서'], [d['name'] for d in out['no_data_devices']])
        self.assertNotIn('inactive_devices', out)
        self.assertNotIn('known_status_devices', out)
        self.assertNotIn('fresh_devices', out)
        self.assertNotIn('꺼 둔 센서', json.dumps(out, ensure_ascii=False))
        self.assertNotIn('정상 센서', json.dumps(out, ensure_ascii=False))

    def test_the_verdict_and_the_counts_are_unchanged(self):
        old = self._fresh()
        new = self._fresh(brief=True)
        for k in ('status', 'checked', 'stale_count', 'no_data_count', 'inactive_count',
                  'known_status_count', 'removed_count', 'fresh_count', 'scan_window_days', 'basis', 'caveat'):
            self.assertEqual(old[k], new[k], k)
        self.assertEqual(1, new['inactive_count'])
        self.assertEqual(1, new['stale_count'])
        self.assertEqual(1, new['no_data_count'])

    def test_a_silent_device_keeps_the_numbers_that_judge_it(self):
        old = self._fresh()['stale_devices'][0]
        new = self._fresh(brief=True)['stale_devices'][0]
        for k in ('name', 'device_id', 'place', 'last_seen', 'last_seen_channel', 'age_readable', 'periods_late'):
            if old.get(k) is not None:
                self.assertEqual(old[k], new[k], k)
        self.assertNotIn('driver', new)
        self.assertNotIn('expected_within_seconds', new)

    def test_include_fresh_gives_the_old_full_shape(self):
        old = self._fresh(include_fresh=True)
        new = self._fresh(include_fresh=True, brief=True)
        self.assertEqual(old, new)
        self.assertIn('fresh_devices', new)
        self.assertIn('inactive_devices', new)

    def test_a_named_device_is_never_folded_away(self):
        out = self._fresh(device_id='f-off', brief=True)
        self.assertEqual(1, len(out['inactive_devices']))              # 지목하면 그 장치 줄이 있다

    def test_the_way_to_the_rest_is_in_the_answer(self):
        self.assertIn('include_fresh=true', self._fresh(brief=True)['next']['call'])

    def test_the_domain_surface_asks_for_the_brief_without_a_target(self):
        v = _plan('measure', {'op': 'freshness'}, 'none')
        self.assertIs(True, v[2]['brief'])
        v = _plan('measure', {'op': 'freshness'}, 'input')
        self.assertNotIn('brief', v[2])
        self.assertIs(False, inspect.signature(self._svc().get_device_freshness).parameters['brief'].default)

    def test_it_is_smaller(self):
        for i in range(10):
            _input('off-%d' % i, '꺼 둔 %d' % i, 'temperature')
            row = Input.query.filter_by(unique_id='off-%d' % i).first()
            row.is_activated = False
            row.save()
            self.age['off-%d' % i] = 5 * 86400.0
        old = _tokens(self._fresh())
        new = _tokens(self._fresh(brief=True))
        print('freshness: %d -> %d tokens' % (old, new))
        self.assertLess(new, old * 0.6)


# ── 도메인 출구까지 — 틀의 주석(_annotate)·따라가기를 지나도 모양이 산다 ────────────

class TestThroughTheDomainExit(_Base):

    def _run(self, args, kind=None, device=None):
        from aot.tools.domain import dispatch
        S = self._svc()

        def execute(app, name, inner_args, **ctx):
            inner_args = {k: v for k, v in inner_args.items() if not str(k).startswith('_')}
            return [{'type': 'text', 'text': json.dumps(getattr(S, name)(**inner_args),
                                                        ensure_ascii=False, default=str)}]
        patches = [mock.patch('aot.tools.tool_execution._execute_tool', execute),
                   mock.patch('aot.utils.inputs.model_input_drivers', return_value=set()),
                   mock.patch('aot.tools.data_tools.measurement.read_influxdb_list',
                              side_effect=lambda did, unit, ch, **k: self._rows(30, 20.0 + ch)),
                   mock.patch.object(S, '_check_influxdb_available', return_value=(True, 'OK'))]
        if kind:
            patches.append(mock.patch.object(dispatch.targets, 'resolve', lambda ref, **kw: (
                'ok', {'kind': kind, 'id': device, 'name': str(ref), 'path': 'map > %s' % ref,
                       'matched': 'exact'})))
        for p in patches:
            p.start()
        try:
            out = dispatch._run_call_inner(self.app, 'measure', args, {}, None, None)
        finally:
            for p in patches:
                p.stop()
        return json.loads(out[0]['text'])

    def test_history_brief_keeps_status_then_next_then_data(self):
        _input('dev-x', '시험 장치')
        _channels('dev-x', [('temperature', 'C', ''), ('humidity', 'percent', '')])
        body = self._run({'op': 'history', 'target': '시험 장치'}, 'input', 'dev-x')
        self.assertEqual(['status', 'next'], list(body)[:2])
        self.assertEqual(['temperature', 'humidity'], [c['measurement'] for c in _lines(body)])
        body = self._run({'op': 'history', 'target': '시험 장치', 'measurement': 'humidity'}, 'input', 'dev-x')
        self.assertIsInstance(body, list)                              # 항목을 정하면 예전 모양(목록)

    def test_channels_without_and_with_a_measurement(self):
        uid = _forecast()
        body = self._run({'op': 'channels', 'target': '예보 장치'}, 'input', uid)
        self.assertEqual(['status', 'next'], list(body)[:2])
        self.assertNotIn('select_value', json.dumps(body['channels']))
        body = self._run({'op': 'channels', 'target': '예보 장치', 'measurement': 'Window Length'}, 'input', uid)
        self.assertEqual(['Window Length'], [m['name'] for m in body['measurements']])
        self.assertTrue(body['measurements'][0]['select_value'].startswith(uid))

    def test_summary_without_a_target_is_one_line_per_site(self):
        body = self._run({'op': 'summary'})
        self.assertEqual('success', body['status'])
        self.assertIn('sites', body)
        self.assertNotIn('truncated', body)

    def test_a_farm_with_no_sensors_still_names_every_site(self):
        Input.query.delete()
        DeviceMeasurements.query.delete()
        GeoShape.query.filter(GeoShape.type == 'aot_device').delete()
        from aot.space import shape_index
        shape_index.invalidate()
        body = self._run({'op': 'summary'})
        self.assertEqual([], body['sites'])
        self.assertIn('3포장', body['no_environment_data'])
        self.assertIn('1포장', body['no_environment_data'])
