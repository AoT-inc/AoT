# coding=utf-8
"""외부 AI 5차 점검(2026-10-10)에서 고친 것 — 틀린 대상에 조용히 성공하지 않는다.

  I-1  get_anomalies: 모르는 범위·없는 지도·id 없는 범위를 '이상 없음' 으로 답하지 않는다.
  I-2  get_crop_status: 시설 필터가 구획 목록에도 걸린다.
  I-3  get_map_equipment: 시설 이름이면 시설이라고, 없는 이름이면 없다고 답한다.
  I-5  get_control_state: 숫자 근거(27)에 이름(humid_cold)을 곁들인다.
  I-8  Open-Meteo: 429 를 받으면 한도가 풀릴 때까지 같은 호스트에 묻지 않는다.
"""
from aot.utils.timekit import FARM, today_at
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest import mock


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


def setUpModule():
    from flask import Flask
    from flask_babel import Babel
    from aot.aot_flask.extensions import db
    import aot.databases.models  # noqa: F401

    global _tmp, _ctx
    _tmp = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = \
        'sqlite:///' + os.path.join(_tmp.name, 'check5.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    Babel(app)
    _ctx = app.app_context()
    _ctx.push()
    db.create_all()
    _seed(db)


def tearDownModule():
    from aot.aot_flask.extensions import db
    db.session.remove()
    _ctx.pop()
    _tmp.cleanup()


def _seed(db):
    from aot.databases.models import (CustomController, FunctionRuntimeState,
                                      GeoFacility, GeoMap, GeoPlot)
    db.session.add(GeoMap(unique_id='map-c5', name='오점검'))
    db.session.add(GeoFacility(unique_id='fac-nursery', name='육묘장3',
                               shape_uuid='shp-nursery', geo_id='map-c5'))
    db.session.add(GeoFacility(unique_id='fac-other', name='다른온실',
                               shape_uuid='shp-other', geo_id='map-c5'))
    db.session.add(GeoPlot(unique_id='plot-open', geo_id='map-c5',
                           subject='콩', started_on=today_at(FARM),
                           feature={'type': 'Feature', 'properties': {},
                                    'geometry': _square(0, 0, 0.001)}))
    db.session.add(GeoPlot(unique_id='plot-nursery', geo_id='map-c5',
                           subject='상추', started_on=today_at(FARM),
                           facility_uuid='fac-nursery', bay_id='b1'))
    db.session.add(GeoPlot(unique_id='plot-other', geo_id='map-c5',
                           subject='토마토', started_on=today_at(FARM),
                           facility_uuid='fac-other', bay_id='b1'))
    db.session.add(CustomController(
        unique_id='ctl-c5', name='환경제어 c5', device='env_coordinator',
        is_activated=True,
        custom_options=json.dumps({'geo_facility_id': 'fac-nursery'})))
    db.session.add(FunctionRuntimeState(function_id='ctl-c5', summary_json=json.dumps({
        'ts': 1760054400.0,
        'commands': [{'slot_key': 'bf73ae5e', 'kind': 'vent', 'pct': 0.0,
                      'reason': 27, 'var': 'humidity'},
                     {'slot_key': '5cf0afd9', 'kind': 'fogger', 'pct': 0.0,
                      'reason': 12, 'var': 'humidity'},
                     {'slot_key': 'x', 'kind': 'vent', 'pct': 10.0,
                      'reason': 'humid_max', 'var': 'humidity'}]})))
    db.session.commit()


def _S():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


class CropStatusFacilityFilterTest(unittest.TestCase):

    def test_name_filter_limits_plots_to_that_facility(self):
        out = _S().get_crop_status(facility_name='육묘장3')
        self.assertEqual('success', out['status'], out)
        # 노지 구획은 이 응답의 대상이 아니다 — 빈 목록이 아니라 키가 없고,
        # 다른 곳에 몇 건 있는지와 어디서 보는지를 말한다(2026-10-19).
        self.assertNotIn('open_field_plots', out)
        self.assertNotIn('plot_count', out)
        self.assertEqual(1, out['open_field_plots_elsewhere'])
        self.assertIn('find.plots', out['facility_filter_note'])
        self.assertEqual(['plot-nursery'],
                         [p['unique_id'] for p in out.get('facility_bay_plots', [])])
        self.assertEqual(['육묘장3'], out['facility_filter'])
        self.assertIn('facility_filter_note', out)

    def test_shape_id_filter_is_the_same_facility(self):
        out = _S().get_crop_status(facility_id='shp-nursery')
        self.assertEqual(['plot-nursery'],
                         [p['unique_id'] for p in out.get('facility_bay_plots', [])])

    def test_unknown_facility_is_an_error_not_an_empty_success(self):
        for kw in ({'facility_name': '없는시설'}, {'facility_id': 'nope'}):
            out = _S().get_crop_status(**kw)
            self.assertEqual('error', out.get('status'), (kw, out))

    def test_no_filter_still_lists_everything(self):
        out = _S().get_crop_status()
        self.assertIn('plot-open', [p['unique_id'] for p in out['open_field_plots']])
        bay = {p['unique_id'] for p in out.get('facility_bay_plots', [])}
        self.assertEqual({'plot-nursery', 'plot-other'}, bay)
        self.assertNotIn('facility_filter', out)


class MapEquipmentPlaceKindTest(unittest.TestCase):

    def test_facility_name_points_to_facility_capacity(self):
        out = _S().get_map_equipment_tool(area_name='육묘장3')
        self.assertEqual('facility', out.get('area_kind'), out)
        self.assertIn('get_facility_capacity', out['message'])

    def test_unknown_place_is_an_error(self):
        out = _S().get_map_equipment_tool(area_name='어디에도없는곳')
        self.assertEqual('error', out.get('status'), out)
        self.assertIn('resolve_target', out['error'])


class AnomalyScopeValidationTest(unittest.TestCase):

    def _call(self, **kw):
        with mock.patch('aot.tools.providers.get') as get:
            get.return_value = lambda st, sid: {'metrics': {}, 'anomalies': []}
            return _S().get_anomalies(**kw), get

    def test_unknown_scope_type_is_refused(self):
        out, get = self._call(scope_type='device', scope_id='x')
        self.assertIn('error', out)
        get.assert_not_called()

    def test_scope_without_id_is_refused(self):
        out, get = self._call(scope_type='zone')
        self.assertIn('error', out)
        get.assert_not_called()

    def test_unknown_map_is_refused_known_map_passes(self):
        out, get = self._call(scope_type='farm', scope_id='no-such-map')
        self.assertIn('error', out)
        get.assert_not_called()
        out, get = self._call(scope_type='farm', scope_id='오점검')
        self.assertEqual('success', out.get('status'), out)
        self.assertEqual({'type': 'farm', 'id': 'map-c5'}, out['scope'])


class ControlReasonNameTest(unittest.TestCase):

    def test_reason_codes_carry_names(self):
        out = _S().get_control_state(facility_id='fac-nursery')
        cmds = out['coordinators'][0]['latest_cycle_summary']['commands']
        names = {c['slot_key']: c.get('reason_name') for c in cmds}
        self.assertEqual({'bf73ae5e': 'humid_cold', '5cf0afd9': 'safety_pre_gate',
                          'x': 'limit_humid_max'}, names)

    def test_names_come_from_the_constants(self):
        from aot.functions.utils.env_control import log_channels as LC
        self.assertEqual('humid_cold', LC.reason_name(LC.REASON_HUMID_COLD))
        self.assertEqual('unknown', LC.reason_name(99999))
        self.assertEqual('unknown', LC.reason_name('no-such-reason'))


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        if self._body is None:
            raise ValueError('no json')
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class OpenMeteoRateLimitTest(unittest.TestCase):

    def setUp(self):
        from aot.inputs import open_meteo_weather as M
        self.M = M
        M._RATE_LIMITED_UNTIL.clear()

    def tearDown(self):
        self.M._RATE_LIMITED_UNTIL.clear()

    def test_until_follows_the_limit_named_in_the_reply(self):
        now = datetime(2026, 10, 9, 22, 33, 21, tzinfo=timezone.utc).timestamp()
        daily = self.M._rate_limit_until(
            _Resp(429, {'reason': 'Daily API request limit exceeded.'}), now)[0]
        self.assertEqual(datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp(), daily)
        hourly = self.M._rate_limit_until(
            _Resp(429, {'reason': 'Hourly API request limit exceeded.'}), now)[0]
        self.assertEqual(datetime(2026, 10, 9, 23, tzinfo=timezone.utc).timestamp(), hourly)
        self.assertEqual(now + 30, self.M._rate_limit_until(
            _Resp(429, None, {'Retry-After': '30'}), now)[0])
        self.assertEqual(now + self.M._RATE_LIMIT_FALLBACK_S,
                         self.M._rate_limit_until(_Resp(429), now)[0])

    def _input(self):
        class _Dev:
            unique_id = 'om-test'
            log_level_debug = False
            custom_options = '{}'
        inst = self.M.InputModule(_Dev(), testing=True)
        inst.latitude, inst.longitude, inst.api_key = 35.8, 126.9, None
        inst.is_enabled = lambda ch: True
        return inst

    def test_a_429_stops_every_input_on_that_host(self):
        a, b = self._input(), self._input()
        with mock.patch.object(self.M.requests, 'get', return_value=_Resp(
                429, {'reason': 'Daily API request limit exceeded.'})) as get:
            a.get_measurement()
            b.get_measurement()
            a.get_measurement()
        self.assertEqual(1, get.call_count)


if __name__ == '__main__':
    unittest.main()
