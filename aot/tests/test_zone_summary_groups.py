# coding=utf-8
"""센서 요약의 그룹별 평균(`groups`) — 리허설 센서 위치 규칙 PR2.

영양 육묘장 대지(시설 4 + 노지 1 + 실외 1), 김제 3포장(시설 + 3-1 노지 + 토양
복합장치 + 실외 모델), 김제 1포장(기상원 없는 대지)을 모형으로 한다.

규칙:
  · 같은 위치 유형(placement)·장소·매질(air/soil)끼리 묶어 평균을 낸다.
  · 실외(outdoor)는 참고값 그룹 — 시설/노지 평균에 섞지 않는다.
  · 모델·비활성·위치 모름·방위·통신 채널·오래된 값은 평균에서 빼고 사유를 낸다.
  · 한 장치가 공기·토양 채널을 둘 다 가지면 두 그룹에 모두 나온다(채널 단위 판정).
  · 기본 응답은 그룹 요약만. `sensors` 등 호환 키는 detail=true 에서만.
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from aot.databases.models import DeviceMeasurements, GeoShape, Input
from aot.tests.test_classify_sensors import _ClsBase, _marker
from aot.tests.test_place_members_split import _input


def _dm(uid, ch, meas, unit, name=''):
    DeviceMeasurements(device_id=uid, channel=ch, measurement=meas, unit=unit,
                       name=name).save()


class _GroupsBase(_ClsBase):

    #: (장치, 채널) → 값. 없으면 20.
    vals = {}
    ages = {}

    def _summary(self, models=(), **kw):
        from aot.space import shape_index
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        shape_index.invalidate()
        now = datetime.now(timezone.utc)
        vals, ages = self.vals, self.ages

        def _read(did, unit, channel, *a, **k):
            at = now - timedelta(seconds=ages.get(did, 0))
            return [(at, vals.get((did, channel), 20.0))]
        with mock.patch('aot.utils.influx.read_influxdb_list',
                        side_effect=_read), \
                mock.patch('aot.utils.inputs.model_input_drivers',
                           return_value=set(models)):
            return S.get_zone_sensor_summary(**kw)

    @staticmethod
    def _group(zone, placement, medium='air', place=None):
        hits = [g for g in zone['groups'] if g['placement'] == placement
                and g['medium'] == medium
                and (place is None or g['place_name'] == place)]
        return hits[0] if hits else None

    @staticmethod
    def _avg(group, meas='temperature'):
        return {a['measurement']: a for a in group['avg']}[meas]


class TestNiyangNursery(_GroupsBase):
    """시설 + 노지 + 실외가 한 대지에 있는 영양 육묘장 모형."""

    def setUp(self):
        super(TestNiyangNursery, self).setUp()
        _input('wx', '기상대', 'temperature', 'radiation')
        _marker('wx', 'wx', 55, 85)
        self.vals = {('fs-in', 0): 20.0, ('fs-unset', 0): 22.0,
                     ('fs-geo', 0): 24.0, ('open-site', 0): 18.0,
                     ('zone-s', 0): 16.0, ('wx', 0): 5.0, ('fs-out', 0): 7.0}

    def _zone(self, **kw):
        out = self._summary(zone_ids=['site'], **kw)
        return out, [z for z in out['zones'] if z['zone_id'] == 'site'][0]

    def test_facility_group_averages_only_facility_sensors(self):
        _, z = self._zone()
        g = self._group(z, 'facility')
        self.assertEqual(g['place_name'], '육묘장3')
        self.assertEqual(g['n_devices'], 3)
        t = self._avg(g)
        self.assertEqual((t['avg_last'], t['n']), (22.0, 3))   # 외기 5·7 이 섞이면 달라진다

    def test_open_field_is_split_per_place(self):
        _, z = self._zone()
        fields = {g['place_name']: g for g in z['groups']
                  if g['placement'] == 'open_field'}
        self.assertEqual(self._avg(fields['3포장'])['avg_last'], 18.0)
        self.assertEqual(self._avg(fields['3-1'])['avg_last'], 16.0)

    def test_outdoor_is_a_reference_group_apart_from_the_rest(self):
        _, z = self._zone()
        o = self._group(z, 'outdoor')
        self.assertTrue(o['reference'])
        self.assertEqual(self._avg(o)['avg_last'], 6.0)         # (5 + 7) / 2
        for g in z['groups']:
            if g['placement'] != 'outdoor':
                self.assertNotIn('reference', g)

    def test_group_order_is_facility_then_field_then_outdoor(self):
        _, z = self._zone()
        order = [g['placement'] for g in z['groups']]
        self.assertEqual(order, sorted(order, key=['facility', 'open_field',
                                                   'outdoor'].index))

    def test_default_response_has_no_sensor_list(self):
        out, z = self._zone()
        for k in ('sensors', 'indoor', 'outdoor', 'location'):
            self.assertNotIn(k, z)
        self.assertIn('detail_hint', out)
        self.assertIn('groups', z)

    def test_detail_brings_back_the_compat_keys(self):
        for flag in ({'detail': True}, {'_detail': True}):
            out, z = self._zone(**flag)
            self.assertNotIn('detail_hint', out)
            self.assertTrue(z['sensors'] and z['indoor'] and z['outdoor'])
            self.assertIn('groups', z)
            self.assertEqual({d['location'] for d in z['sensors']},
                             {'indoor', 'open_field', 'outdoor'})

    def test_detail_false_strings_stay_compact(self):
        _, z = self._zone(detail='false')
        self.assertNotIn('sensors', z)

    def test_indoor_avg_only_when_a_single_group(self):
        _, z = self._zone()
        self.assertNotIn('indoor_avg', z)             # 시설·노지가 갈린다
        self.assertIn('groups', z['indoor_avg_note'])
        _, z = self._zone(detail=True)
        self.assertIn('indoor_avg', z)                 # 호환 키는 전부 싣는다

    def test_detail_avg_follows_groups_not_raw_location(self):
        """detail 의 indoor_avg 도 비활성 장치를 뺀 시설 그룹에서 온다."""
        Input.query.filter(Input.unique_id == 'fs-geo').update(
            {'is_activated': False})
        _, z = self._zone(detail=True)
        fac = self._group(z, 'facility')
        for a in z.get('indoor_avg') or []:
            self.assertEqual(a['devices'], fac['n_devices'])
        self.assertNotIn('outdoor', {d['location'] for d in z['sensors']
                                     if d['device_id'] in z['indoor']})

    def test_inactive_device_is_excluded_with_reason(self):
        Input.query.filter(Input.unique_id == 'fs-geo').update(
            {'is_activated': False})
        _, z = self._zone()
        self.assertEqual(self._group(z, 'facility')['n_devices'], 2)
        self.assertIn({'device': '시설 안 마커', 'reason': 'inactive'},
                      z['excluded'])

    def test_stale_value_is_excluded_and_named(self):
        self.ages = {'fs-unset': 3 * 3600}
        out, z = self._zone()
        self.assertEqual(self._group(z, 'facility')['n_devices'], 2)
        self.assertEqual([e['device'] for e in z['stale_excluded']],
                         ['미러-온습도03'])
        self.assertIn('freshness_basis', out)


class TestGimjeThird(_GroupsBase):
    """김제 3포장 — 시설 1 + 노지 + 토양 복합장치 + 실외 모델."""

    def setUp(self):
        super(TestGimjeThird, self).setUp()
        # 토양 측정 센서지만 대기 온습도도 함께 주는 복합 측정장치.
        _input('combo', '토양온습도_1')
        _dm('combo', 0, 'temperature', 'C', '대기 온도')
        _dm('combo', 1, 'humidity', 'percent', '대기 습도')
        _dm('combo', 2, 'temperature', 'C', '토양 온도')
        _dm('combo', 3, 'volumetric_water_content', 'm3_m3', '토양 수분')
        _marker('combo', 'combo', 20, 30)                  # 구역 3-1
        # 실외 모델 — 예보 값이다.
        Input(unique_id='fc', name='SIM 기상대', device='OPEN_METEO',
              is_activated=True).save()
        _dm('fc', 0, 'temperature', 'C')
        _marker('fc', 'fc', 55, 85)
        # 기상대 — 풍향(방위)과 배터리 같은 통신 채널도 낸다.
        _input('wx', '기상대', 'temperature', 'radiation')
        _dm('wx', 5, 'wind_direction', 'bearing', '풍향')
        _marker('wx', 'wx', 56, 85)
        self.vals = {('combo', 0): 25.0, ('combo', 1): 60.0,
                     ('combo', 2): 17.0, ('combo', 3): 0.31,
                     ('zone-s', 0): 23.0, ('fs-in', 0): 20.0,
                     ('fs-unset', 0): 22.0, ('fs-geo', 0): 24.0,
                     ('open-site', 0): 18.0, ('wx', 0): 3.0, ('fc', 0): 4.0}

    def _zone(self, uid='zone-a'):
        out = self._summary(zone_ids=[uid])
        return out, out['zones'][0]

    def test_composite_device_appears_in_both_air_and_soil_groups(self):
        _, z = self._zone()
        air = self._group(z, 'open_field', 'air', '3-1')
        soil = self._group(z, 'open_field', 'soil', '3-1')
        self.assertIn('토양온습도_1', air['devices'])
        self.assertIn('토양온습도_1', soil['devices'])
        # 같은 'temperature' 라도 공기와 토양이 섞이지 않는다.
        self.assertEqual(self._avg(air)['avg_last'], 24.0)      # (25 + 23) / 2
        self.assertEqual(self._avg(soil)['avg_last'], 17.0)
        self.assertEqual(self._avg(soil, 'volumetric_water_content')['avg_last'],
                         0.31)
        self.assertNotIn('humidity', {a['measurement'] for a in soil['avg']})

    def test_model_and_bearing_are_left_out_with_reasons(self):
        # 모델 사유는 모델 드라이버를 지정한 호출에서 본다.
        out = self._summary(models={'OPEN_METEO'}, zone_ids=['site'])
        z = [x for x in out['zones'] if x['zone_id'] == 'site'][0]
        reasons = {(e['device'], e['reason']) for e in z['excluded']}
        self.assertIn(('SIM 기상대', 'model'), reasons)
        self.assertTrue(any(r == 'bearing' for _, r in reasons))
        o = self._group(z, 'outdoor')
        self.assertNotIn('wind_direction', {a['measurement'] for a in o['avg']})
        self.assertTrue(any('FORECAST' in n for n in out['_reading']))

    def test_comm_channel_is_not_averaged(self):
        _dm('fs-in', 7, 'electrical_potential', 'volt', '배터리')
        out = self._summary(zone_ids=['site'], measurement_type='electrical')
        z = [x for x in out['zones'] if x['zone_id'] == 'site'][0]
        for g in z['groups']:
            self.assertNotIn('electrical_potential',
                             {a['measurement'] for a in g['avg']})
        self.assertTrue(any(e['reason'] == 'link_channel' for e in z['excluded']))

    def test_unknown_group_helper_excludes_unplaced(self):
        from aot.tools.data_tools.measurement import MeasurementToolsMixin as M
        from aot.space.device_membership import Placement
        rd = [{'device_id': 'u', 'device_name': '미배치', 'location': 'indoor',
               'channels': [{'channel': 0, 'measurement': 'temperature',
                             'unit': 'C', 'last_value': 30.0,
                             'last_time': datetime.now(timezone.utc).isoformat()}]}]
        groups, excluded, stale = M._zone_groups(
            rd, {'u': Placement('unplaced', None, None, None)}, {}, set(),
            lambda d, t: False, None)
        self.assertEqual(groups, [])
        self.assertEqual(excluded, [{'device': '미배치', 'reason': 'unplaced'}])


class TestGimjeFirstWithoutWeather(_GroupsBase):

    def test_site_without_weather_station_has_no_outdoor_group(self):
        out = self._summary(zone_ids=['site2'])
        z = out['zones'][0]
        self.assertEqual([g['placement'] for g in z['groups']], ['open_field'])
        self.assertEqual(z['groups'][0]['place_name'], '1포장')
        # 그룹이 하나뿐이면 기본 응답에도 indoor_avg 가 간다(둘 이상일 때만).
        self.assertNotIn('indoor_avg_note', z)


class TestChannelAverages(_GroupsBase):
    """채널 단위 평균 · devices_more · 강우 표시 라벨 (구역 3-1 의 노지 그룹)."""

    def setUp(self):
        super(TestChannelAverages, self).setUp()
        # 한 장치에 같은 이름·단위(temperature C) 채널 둘 + °F 채널 하나 + 강우 +
        # 거리 센서(length mm, 이름이 강우가 아님).
        _input('multi', '다채널')
        _dm('multi', 0, 'temperature', 'C', 'air a')
        _dm('multi', 1, 'temperature', 'C', 'air b')
        _dm('multi', 2, 'temperature', 'F', 'air f')
        _dm('multi', 3, 'length', 'mm', 'rain')
        _dm('multi', 4, 'length', 'mm', 'distance')
        _marker('multi', 'multi', 20, 30)
        for i in range(3):
            _input('extra-%d' % i, '추가%d' % i, 'temperature')
            _marker('extra-%d' % i, 'extra-%d' % i, 20, 30)
        self.vals = {('zone-s', 0): 16.0, ('multi', 0): 20.0,
                     ('multi', 1): 30.0, ('multi', 2): 70.0,
                     ('multi', 3): 4.0, ('multi', 4): 150.0,
                     ('extra-0', 0): 10.0, ('extra-1', 0): 10.0,
                     ('extra-2', 0): 10.0}

    def _g(self):
        out = self._summary(zone_ids=['site'])
        z = [z for z in out['zones'] if z['zone_id'] == 'site'][0]
        return self._group(z, 'open_field', place='3-1')

    def test_every_channel_of_a_device_enters_the_average(self):
        t = [a for a in self._g()['avg']
             if (a['measurement'], a['unit']) == ('temperature', 'C')][0]
        # zone-s 16 + multi 20, 30 + extra 10 x3 = 96 / 6
        self.assertEqual((t['avg_last'], t['n'], t['n_devices']), (16.0, 6, 5))

    def test_units_are_not_mixed(self):
        f = [a for a in self._g()['avg']
             if (a['measurement'], a['unit']) == ('temperature', 'F')][0]
        self.assertEqual((f['avg_last'], f['n']), (70.0, 1))
        self.assertNotIn('n_devices', f)       # 채널 수와 같으면 생략

    def test_device_names_overflow_is_stated(self):
        g = self._g()
        self.assertEqual(g['n_devices'], 5)
        self.assertEqual(len(g['devices']), 3)
        self.assertEqual(g['devices_more'], 2)

    def test_no_devices_more_when_all_names_fit(self):
        out = self._summary(zone_ids=['site'])
        z = [z for z in out['zones'] if z['zone_id'] == 'site'][0]
        o = self._group(z, 'open_field', place='3포장')
        self.assertNotIn('devices_more', o)

    def test_rain_label_is_display_only(self):
        g = self._g()
        by = {a['measurement']: a for a in g['avg']}
        self.assertEqual(by['precipitation']['raw_measurement'], 'length')
        self.assertEqual(by['precipitation']['unit'], 'mm')
        # 이름이 강우가 아닌 length 는 그대로 — 거리 센서를 강우로 부르지 않는다.
        self.assertIn('length', by)
        self.assertNotIn('raw_measurement', by['length'])
        # 저장 정의는 그대로다.
        row = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == 'multi',
            DeviceMeasurements.channel == 3).first()
        self.assertEqual(row.measurement, 'length')

    def test_detail_channel_keeps_raw_measurement(self):
        out = self._summary(zone_ids=['site'], detail=True)
        z = [z for z in out['zones'] if z['zone_id'] == 'site'][0]
        dev = [d for d in z['sensors'] if d['device_id'] == 'multi'][0]
        ch = {c['channel']: c for c in dev['channels']}
        self.assertEqual(ch[3]['measurement'], 'precipitation')
        self.assertEqual(ch[3]['raw_measurement'], 'length')
        self.assertEqual(ch[4]['measurement'], 'length')


class TestResponseSize(_GroupsBase):
    """3포장 크기의 장소 — 기본 응답이 목표(8,000자) 이하, detail 보다 작다."""

    MEAS = (('temperature', 'C'), ('humidity', 'percent'), ('vpd', 'kPa'),
            ('dewpoint', 'C'), ('co2', 'ppm'), ('light', 'lux'))

    def setUp(self):
        super(TestResponseSize, self).setUp()
        for i in range(14):
            uid = 'big-%02d' % i
            _input(uid, '미러-온습도%02d 센서 이름이 꽤 긴 편' % i)
            for ch, (m, u) in enumerate(self.MEAS):
                _dm(uid, ch, m, u, m)
            # 시설 폴리곤 안 / 노지 구역 / 대지 직속에 나눠 놓는다.
            x, y = ((75, 75) if i % 3 == 0 else (20, 30) if i % 3 == 1
                    else (50, 80))
            _marker(uid, uid, x, y)
        _input('wx', '기상대', 'temperature', 'radiation')
        _marker('wx', 'wx', 55, 85)

    def test_default_is_compact(self):
        small = self._summary(zone_ids=['site'])
        big = self._summary(zone_ids=['site'], detail=True)
        n_small = len(json.dumps(small, ensure_ascii=False))
        n_big = len(json.dumps(big, ensure_ascii=False))
        print('\n[size] default=%d detail=%d' % (n_small, n_big))
        self.assertLessEqual(n_small, 8000)
        self.assertLess(n_small * 2, n_big)


class TestConsumers(unittest.TestCase):

    def test_overview_keeps_soil_unplaced_and_outdoor_apart(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        fresh = datetime.now(timezone.utc).isoformat()

        def ch(v, **kw):
            return [dict({'measurement': 'temperature', 'unit': 'C',
                          'last_value': v}, **kw)]
        summary = {'zones': [{'sensors': [
            {'device_id': 'a', 'device_name': 'a', 'last_time': fresh,
             'location': 'indoor', 'placement': 'facility', 'channels': ch(20.0)},
            {'device_id': 'b', 'device_name': 'b', 'last_time': fresh,
             'location': 'indoor', 'placement': 'facility', 'channels': ch(24.0)
             + ch(15.0, medium='soil')},
            {'device_id': 'u', 'device_name': 'u', 'last_time': fresh,
             'location': 'indoor', 'placement': 'unplaced', 'channels': ch(39.0)},
            {'device_id': 'w', 'device_name': 'w', 'last_time': fresh,
             'location': 'outdoor', 'placement': 'outdoor', 'channels': ch(5.0)},
        ]}]}
        with mock.patch.object(S, 'get_zone_sensor_summary',
                               return_value=summary) as m:
            sensors, _ = S._overview_sensors(SimpleNamespace(unique_id='z'),
                                             brief=False)
        self.assertTrue(m.call_args.kwargs.get('detail'))
        self.assertEqual(22.0, sensors['temperature']['avg'])
        self.assertEqual(5.0, sensors['outdoor']['temperature']['avg'])
        self.assertEqual(15.0, sensors['soil']['temperature']['avg'])


class TestPickOrder(_ClsBase):

    def test_placed_before_outdoor_keeps_indoor_first(self):
        from aot.space import shape_index
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        _input('wx', '가-기상대', 'temperature', 'radiation')
        _marker('wx', 'wx', 55, 85)
        shape_index.invalidate()
        zone = GeoShape.query.filter(GeoShape.unique_id == 'site').first()
        with mock.patch('aot.utils.inputs.model_input_drivers',
                        return_value=set()):
            ids = [i.unique_id for i in S._pick_zone_inputs(zone, 'temperature')]
        self.assertEqual(ids[-1], 'wx')
        self.assertNotEqual(ids[0], 'wx')


class TestDetailIsAMetaArgument(unittest.TestCase):

    def test_schema_does_not_carry_detail(self):
        from aot.tools.tool_registry import _MCP_TOOL_PAYLOADS as VIRTUAL_TOOLS
        tool = [t for t in VIRTUAL_TOOLS
                if t.get('tool_name') == 'get_zone_sensor_summary'][0]
        self.assertNotIn('detail', tool['input_schema']['properties'])

    def test_meta_keys_are_not_flagged_as_typos(self):
        from aot.tools.tool_execution import _CLIENT_META_ARGS, _likely_typo
        self.assertTrue({'detail', '_detail'} <= _CLIENT_META_ARGS)
        self.assertIsNone(_likely_typo('detail', {'zone_ids', 'time_range'}))

    def test_handler_accepts_it_without_ignored_arguments_note(self):
        from aot.tools import tool_execution as te
        seen = {}

        def _fake(**kw):
            seen.update(kw)
            return {'zones': []}
        with mock.patch('aot.tools.tool_registry.build_tool_map',
                        return_value={'get_zone_sensor_summary': _wrap(_fake)}):
            out = te._dispatch_virtual_tool(
                'get_zone_sensor_summary', {'zone_ids': ['x'], 'detail': True})
        self.assertTrue(seen.get('detail'))
        self.assertNotIn('_ignored_arguments', out)


def _wrap(fn):
    """실제 처리기와 같은 서명(detail 을 이름으로 받는다)을 가진 가짜."""
    def handler(zone_ids=None, measurement_type=None, time_range='7d',
                detail=False, _detail=False, **extra):
        return fn(zone_ids=zone_ids, detail=detail)
    return handler


if __name__ == '__main__':
    unittest.main()
