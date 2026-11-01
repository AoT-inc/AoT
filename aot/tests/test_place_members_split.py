# coding=utf-8
"""장소 소속의 실내/실외 분리(B1 · PR1) — `place_members_split` 과 센서 요약.

배경(리허설 B1): 대지의 기상대가 구역·시설의 센서와 같은 줄에 실려, 모델이
외기 온도를 실내 평균에 섞어 보고했다. 실외 = 그 장소를 감싸는 대지의
기상원(`weather_device_ids` — 지정 우선, 없으면 측정값 추론).

규칙:
  · `place_members` 는 바뀌지 않는다(노트·일정·화면 소속이 쓴다).
  · 지도에 마커 없이 시설 설비에만 매인 기상대도 추론에 걸리면 실외다.
  · 센서 요약의 장소 평균(`indoor_avg`)은 실내만으로 센다.
"""
import unittest
from datetime import datetime, timezone
from unittest import mock

from aot.aot_flask.extensions import db
from aot.databases.models import GeoShape
from aot.tests.test_place_membership import _Base, _point, _poly

FAC_SHAPE = [[60, 60], [60, 90], [90, 90], [90, 60], [60, 60]]


def _input(uid, name, *meas):
    from aot.databases.models import DeviceMeasurements, Input
    Input(unique_id=uid, name=name, device='MQTT_PAHO_JSON',
          is_activated=True).save()
    for i, m in enumerate(meas):
        DeviceMeasurements(device_id=uid, channel=i, measurement=m,
                           unit='C').save()


class _SplitBase(_Base):

    def setUp(self):
        super(_SplitBase, self).setUp()
        # 구역 A 안의 실내 센서 둘(sensor-1 은 _Base 의 마커).
        _input('sensor-1', '온습도1', 'temperature')
        _input('sensor-2', '온습도2', 'temperature')
        GeoShape(unique_id='mk-sensor-2', geo_id='m1', type='aot_device',
                 device_id='sensor-2', channel_id='0',
                 feature=_point(20, 30)).save()
        # 대지 안·구역 밖의 기상대(마커) — 일사로 기상원임을 안다.
        _input('wx-1', '기상대', 'temperature', 'radiation')
        GeoShape(unique_id='mk-wx', geo_id='m1', type='aot_device',
                 device_id='wx-1', channel_id='0',
                 feature=_point(50, 80)).save()


class TestPlaceMembersSplit(_SplitBase):

    def test_inferred_weather_station_is_outdoor(self):
        from aot.aot_flask.geo.device_membership import place_members_split
        sp = place_members_split('site')
        self.assertEqual(sp['outdoor'], {'wx-1'})
        self.assertEqual(sp['source'], 'inferred')
        self.assertNotIn('wx-1', sp['indoor'])
        self.assertIn('sensor-1', sp['indoor'])
        self.assertIn('valve-1', sp['indoor'])
        self.assertEqual(sp['weather_place'], 'site')

    def test_zone_gets_the_enclosing_sites_weather(self):
        from aot.aot_flask.geo.device_membership import (place_members,
                                                         place_members_split)
        sp = place_members_split('zone-a')
        self.assertEqual(sp['weather_place'], 'site')
        self.assertEqual(sp['outdoor'], {'wx-1'})
        self.assertEqual(sp['indoor'], place_members('zone-a'))

    def test_bound_weather_wins_over_inference(self):
        from aot.databases.models import GeoBinding
        from aot.aot_flask.geo.device_membership import place_members_split
        _input('wx-2', '지정 기상대', 'temperature')
        GeoBinding(spatial_kind='weather', spatial_id='site', role='weather',
                   device_kind='input', device_id='wx-2').save()
        sp = place_members_split('zone-a')
        self.assertEqual(sp['outdoor'], {'wx-2'})
        self.assertEqual(sp['source'], 'bound')
        # 지정이 정본이라 추론에 걸리던 wx-1 은 이제 실내 소속이다.
        self.assertIn('wx-1', place_members_split('site')['indoor'])

    def test_unplaced_station_bound_to_a_facility_fitting_is_outdoor(self):
        """미러-기상대처럼 지도 마커 없이 시설 설비에만 매인 기상대."""
        from aot.databases.models import GeoBinding, GeoFacility
        from aot.aot_flask.geo.device_membership import place_members_split
        GeoShape.query.filter(GeoShape.unique_id == 'mk-wx').delete()
        db.session.commit()
        GeoShape(unique_id='fac-shape', geo_id='m1', type='facility',
                 feature=_poly(FAC_SHAPE, '육묘장')).save()
        GeoFacility(unique_id='fac-1', shape_uuid='fac-shape',
                    geo_id='m1', name='육묘장').save()
        GeoBinding(spatial_kind='fitting', spatial_id='fac-1:fit-wx',
                   role='sensor', device_kind='input',
                   device_id='wx-1').save()
        sp = place_members_split('site')
        self.assertEqual(sp['outdoor'], {'wx-1'})
        self.assertEqual(sp['source'], 'inferred')
        self.assertEqual(place_members_split('fac-shape')['outdoor'], {'wx-1'})

    def test_place_members_is_unchanged(self):
        from aot.aot_flask.geo.device_membership import (device_ids_in_area,
                                                         place_members)
        for uid in ('site', 'zone-a', 'zone-b'):
            self.assertEqual(place_members(uid), device_ids_in_area(uid))
        self.assertIn('wx-1', place_members('site'))
        self.assertIsNone(place_members('no-such-place'))

    def test_unknown_place_is_none(self):
        from aot.aot_flask.geo.device_membership import place_members_split
        self.assertIsNone(place_members_split('no-such-place'))


class TestZoneSummaryLocation(_SplitBase):

    def _summary(self, ages=None, **kw):
        """ages: {장치: 마지막 값이 몇 초 전인가}. 기본은 방금."""
        from datetime import timedelta
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        now = datetime.now(timezone.utc)
        vals = {'sensor-1': 20.0, 'sensor-2': 22.0, 'wx-1': 5.0}

        def _read(did, *a, **k):
            at = now - timedelta(seconds=(ages or {}).get(did, 0))
            return [(at, vals.get(did, 1.0))]
        with mock.patch('aot.utils.influx.read_influxdb_list',
                        side_effect=_read):
            kw.setdefault('detail', True)     # 호환 키는 detail 에서만 싣는다
            return S.get_zone_sensor_summary(**kw)

    def test_zone_lists_indoor_and_outdoor_and_averages_indoor_only(self):
        out = self._summary(zone_ids=['zone-a'])
        z = out['zones'][0]
        # 시설이 없는 구역이라 실내가 아니라 노지다 — indoor 로 읽히면 안 된다.
        self.assertEqual(z['indoor'], [])
        self.assertEqual(sorted(z['open_field']), ['sensor-1', 'sensor-2'])
        self.assertEqual(z['outdoor'], ['wx-1'])
        by_id = {d['device_id']: d for d in z['sensors']}   # 호환 키 유지
        self.assertEqual(by_id['wx-1']['location'], 'outdoor')
        self.assertEqual(by_id['wx-1']['location_source'], 'inferred')
        self.assertEqual(by_id['sensor-1']['location'], 'open_field')
        self.assertNotIn('indoor_avg', z)
        avg = {a['measurement']: a for a in z['open_field_avg']}
        # 실외 5.0 이 섞였으면 15.67 이 된다.
        self.assertEqual(avg['temperature']['avg_last'], 21.0)
        self.assertEqual(avg['temperature']['devices'], 2)
        self.assertTrue(any("'location'" in n for n in out['_reading']))

    def test_stale_sensor_is_left_out_of_indoor_avg_and_named(self):
        """멈춘 센서의 옛값이 평균에 섞이던 문제(F2/G1) — 정본 신선도로 거른다."""
        out = self._summary(zone_ids=['zone-a'], ages={'sensor-2': 3 * 3600})
        z = out['zones'][0]
        # 정상 센서 하나만 남아 평균 항목은 없다(하나면 그 값이 곧 평균).
        self.assertNotIn('open_field_avg', z)
        self.assertEqual([e['device'] for e in z['stale_excluded']], ['온습도2'])
        self.assertEqual(z['stale_excluded_count'], 1)
        self.assertEqual(z['stale_excluded'][0]['reason'], 'stale')
        self.assertIn('last_time', z['stale_excluded'][0])
        self.assertIn('freshness_basis', out)

    def test_fresh_sensors_report_no_stale_excluded(self):
        out = self._summary(zone_ids=['zone-a'])
        self.assertNotIn('stale_excluded', out['zones'][0])
        self.assertNotIn('freshness_basis', out)

    def test_bound_source_is_reported(self):
        from aot.databases.models import GeoBinding
        GeoBinding(spatial_kind='weather', spatial_id='site', role='weather',
                   device_kind='input', device_id='wx-1').save()
        out = self._summary(zone_ids=['site'])
        wx = [d for d in out['zones'][0]['sensors'] if d['device_id'] == 'wx-1']
        self.assertEqual(wx[0]['location_source'], 'bound')

    def test_overview_does_not_repeat_the_station_under_each_zone(self):
        out = self._summary()
        where = [z['zone_name'] for z in out['zones']
                 for d in z['sensors'] if d['device_id'] == 'wx-1']
        self.assertEqual(where, ['3포장'], out)
        site = [z for z in out['zones'] if z['zone_name'] == '3포장'][0]
        self.assertEqual(site['outdoor'], ['wx-1'])


class TestZonePickPrefersIndoor(_SplitBase):
    """F7/G2: 이름 A-Z 로 '가-기상대'(실외)가 구역 대표가 되던 문제."""

    def setUp(self):
        super(TestZonePickPrefersIndoor, self).setUp()
        _input('wx-in', '가-기상대', 'temperature', 'humidity', 'radiation')
        GeoShape(unique_id='mk-wx-in', geo_id='m1', type='aot_device',
                 device_id='wx-in', channel_id='0',
                 feature=_point(25, 35)).save()
        _input('sensor-1b', '나-온습도', 'temperature', 'humidity')
        GeoShape(unique_id='mk-s1b', geo_id='m1', type='aot_device',
                 device_id='sensor-1b', channel_id='0',
                 feature=_point(22, 32)).save()

    def _pick(self, kind):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        zone = GeoShape.query.filter(GeoShape.unique_id == 'zone-a').first()
        return S, S._pick_zone_inputs(zone, kind)

    def test_indoor_leads_and_outdoor_goes_last(self):
        for kind in ('humidity', 'temperature'):
            S, picks = self._pick(kind)
            ids = [i.unique_id for i in picks]
            self.assertEqual(ids[-1], 'wx-in', ids)
            self.assertNotEqual(ids[0], 'wx-in')

    def test_zone_pick_says_what_was_left_out(self):
        S, picks = self._pick('humidity')
        note = S._zone_pick_note(picks[0], picks)
        self.assertEqual(note['outdoor_not_used'], ['가-기상대'])
        self.assertNotIn('answered_by_outdoor', note)
        last = S._zone_pick_note(picks[-1], picks)
        self.assertTrue(last['answered_by_outdoor'])

    def test_outdoor_is_kept_when_no_indoor_has_the_measurement(self):
        S, picks = self._pick('radiation')
        self.assertEqual(picks[0].unique_id, 'wx-in')


if __name__ == '__main__':
    unittest.main()
