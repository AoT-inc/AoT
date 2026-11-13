# coding=utf-8
"""동기화에서 예보·모델값·시뮬레이터 입력을 자동으로 뺀다 — 도형 상속·저장된 선택 모두, 결과·트윈 탭에는 한 줄만.

미러 센서(현장 실측의 사본)와 실측 센서는 그대로다. 새 설정 칸은 없다.
"""
import datetime
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements, GeoMap, GeoPlot, GeoShape, Input, Misc
from aot.twin.discovery import DbCatalog, build_plan
from aot.twin.gate import LazyApp
from aot.utils import twin_config as TC
from aot.utils import twin_facility_config as TF

INFO = {
    'OPEN_METEO_FORECAST': {'data_origin': 'model', 'measurements_dict': {0: {}, 1: {}}},
    'TEST_SAVE_VALUE': {'measurements_dict': {0: {}}},
    'MQTT_PAHO_JSON': {'measurements_dict': {0: {}}},
    'SOIL_PROBE': {'measurements_dict': {}},
    'SOME_STATION': {'measurements_dict': {}},
}


def _poly(ring):
    return {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [ring]}, 'properties': {}}


def _sq(x0, y0, d):
    return [[x0, y0], [x0, y0 + d], [x0 + d, y0 + d], [x0 + d, y0], [x0, y0]]


def _ser(uid, unit, ch=0):
    return {'unique_id': uid, 'unit': unit, 'channel': ch, 'provenance': 'unknown'}


class ExclusionTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        try:
            from flask_babel import Babel
            Babel(self.app)
        except Exception:
            pass
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add(Misc())
        GeoMap(unique_id='m1', name='지도', category='design').save()
        site = _poly(_sq(126.88, 35.86, 0.01))
        site['properties']['name'] = 'A 포장'
        GeoShape(unique_id='site-1', geo_id='m1', type='site', feature=site).save()
        for uid, x in (('p1', 126.882), ('p2', 126.885)):
            db.session.add(GeoPlot(unique_id=uid, geo_id='m1', name=uid, kind='vegetation', subject='들깨',
                                   started_on=datetime.date(2026, 6, 20), feature=_poly(_sq(x, 35.862, 0.001))))
        # 입력: 실측 기상대, 모델 격자 날씨('SIM 김제 기상대'), 시뮬레이터 센서, 미러 센서, 실측 토양
        for uid, dev, name in (('wx-real', 'SOME_STATION', '기상대'),
                               ('wx-model', 'OPEN_METEO_FORECAST', 'SIM 김제 기상대'),
                               ('soil-sim', 'TEST_SAVE_VALUE', 'SIM 현장센서'),
                               ('soil-mirror', 'MQTT_PAHO_JSON', '미러-온습도01'),
                               ('soil-real', 'SOIL_PROBE', '토양온습도_1')):
            db.session.add(Input(unique_id=uid, device=dev, name=name))
        for uid, mm, unit, nm in (('wx-real', 'precipitation', 'mm', '강수'), ('wx-model', 'precipitation', 'mm', '강수'),
                                  ('soil-sim', 'volumetric_water_content', 'percent', '토양수분'),
                                  ('soil-mirror', 'volumetric_water_content', 'percent', '토양수분'),
                                  ('soil-real', 'volumetric_water_content', 'percent', '토양수분')):
            db.session.add(DeviceMeasurements(device_id=uid, channel=0, measurement=mm, unit=unit, name=nm))
        db.session.commit()
        # 드라이버 판정은 첫 결과를 전역에 캐시한다. 가짜 목록의 결과가 같은 작업자의 다음 시험으로 새지 않게 한다.
        for name in ('_MODEL_DRIVERS', '_FORECAST_TIME_DRIVERS', '_DAILY_FORECAST_DRIVERS'):
            c = mock.patch(f'aot.utils.inputs.{name}', None)
            c.start()
            self.addCleanup(c.stop)
        for target, fn in (('aot.utils.inputs.parse_input_information', lambda: INFO),):
            p = mock.patch(target, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)
        a = mock.patch.object(TC, 'agreement', return_value={})
        a.start()
        self.addCleanup(a.stop)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _plan(self):
        cat = DbCatalog(LazyApp(lambda: self.app))
        return build_plan(cat.sites(), TC.resolved_overrides(), cat.forecast_channels)

    def test_saved_selection_that_is_not_an_observation_is_dropped_with_its_reason(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': _ser('wx-model', 'mm'), 't_air': _ser('wx-real', 'C')}},
                set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'theta': _ser('soil-sim', 'percent')}})
        TC.save('plot', 'p2', None, {'inputs': {'theta': _ser('soil-mirror', 'percent')}})
        ov = TC.resolved_overrides()
        s = ov['sites']['site-1']
        self.assertNotIn('rain', s['inputs'])                                # 모델값 — 빠진다
        self.assertEqual(s['inputs']['t_air']['unique_id'], 'wx-real')       # 실측 기상대 — 그대로
        self.assertEqual(s['excluded']['rain']['reason'], 'model')
        self.assertEqual(s['excluded']['rain']['name'], 'SIM 김제 기상대')
        p1, p2 = ov['plots']['p1'], ov['plots']['p2']
        self.assertIsNone(p1['inputs']['theta'])                             # 시뮬레이터 — 빠진다(대지 값으로 되돌지 않게 null)
        self.assertEqual(p1['excluded']['theta']['reason'], 'simulated')
        self.assertEqual(p2['inputs']['theta']['unique_id'], 'soil-mirror')  # 미러 — 그대로
        self.assertNotIn('excluded', p2)
        # 저장된 표는 건드리지 않는다
        self.assertEqual(TC.overrides()['sites']['site-1']['inputs']['rain']['unique_id'], 'wx-model')

    def test_inherited_weather_station_that_is_a_model_value_is_dropped(self):
        TC.save('site', 'site-1', True, {}, set_enabled=True)
        with mock.patch('aot.space.device_membership.weather_device_ids',
                        return_value=(['wx-model'], 'bound')):
            ov = TC.resolved_overrides()
        s = ov['sites']['site-1']
        self.assertNotIn('rain', s.get('inputs', {}))
        self.assertEqual(s['excluded']['rain']['unique_id'], 'wx-model')

    def test_plan_reads_one_line_and_the_run_result_carries_it(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': _ser('wx-model', 'mm')}}, set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'theta': _ser('soil-real', 'percent')}})
        plans = self._plan()
        line = '관측이 아님 — 동기화에서 제외: 비(모델값, SIM 김제 기상대)'
        self.assertTrue(any(line in n for n in plans[0].notes))
        t = next(x for x in plans[0].targets if x.target_id == 'p1')
        self.assertNotIn('rain', t.inputs)
        self.assertEqual(t.options['excluded_inputs']['rain']['line'], line)
        from aot.twin.engine import excluded_lines
        self.assertEqual(excluded_lines(t), [line])

    def test_replaced_input_is_not_reported_as_excluded(self):
        """구획이 다른(관측) 비를 직접 골랐으면 대지의 제외 줄은 지난 일이다."""
        TC.save('site', 'site-1', True, {'inputs': {'rain': _ser('wx-model', 'mm')}}, set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'theta': _ser('soil-real', 'percent'),
                                                'rain': _ser('wx-real', 'mm')}})
        t = next(x for x in self._plan()[0].targets if x.target_id == 'p1')
        self.assertEqual(t.inputs['rain'].unique_id, 'wx-real')
        self.assertNotIn('excluded_inputs', t.options)

    def test_tab_reads_the_exclusion_and_verdict_and_diagnosis_follow(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': _ser('wx-model', 'mm')}}, set_enabled=True)
        v = TC.site_view('site-1')
        self.assertEqual(v['used']['rain']['excluded'], 'model')
        self.assertEqual(v['verdict']['code'], 'rain_not_observation')
        self.assertEqual({p['diagnosis'] for p in v['plots']}, {'rain_not_observation'})
        # 비를 관측으로 바꾸고 구획 센서가 시뮬레이터면 센서만 빠진다
        TC.save('site', 'site-1', True, {'inputs': {'rain': _ser('wx-real', 'mm')}}, set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'theta': _ser('soil-sim', 'percent')}})
        TC.save('plot', 'p2', None, {'inputs': {'theta': _ser('soil-mirror', 'percent')}})
        v = TC.site_view('site-1')
        self.assertNotIn('excluded', v['used']['rain'])
        diag = {p['plot_id']: p['diagnosis'] for p in v['plots']}
        self.assertEqual(diag, {'p1': 'sensor_not_observation', 'p2': 'synced'})
        self.assertEqual(v['verdict']['code'], 'partial')                    # p1 은 센서 없는 구획처럼 센다
        pv = TC.plot_view('p1')
        self.assertEqual(pv['used']['theta']['excluded'], 'simulated')
        self.assertEqual(pv['diagnosis'], 'sensor_not_observation')
        self.assertNotIn('excluded', TC.plot_view('p2')['used']['theta'])

    def test_facility_inputs_that_are_not_observations_leave_the_verdict_and_the_view_says_so(self):
        ins = {'T_int': _ser('soil-real', 'C'), 'RH_int': _ser('soil-real', 'percent'),
               'T_ext': _ser('wx-model', 'C'), 'RH_ext': _ser('wx-real', 'percent')}
        exc = {k: e['reason'] for k, e in TC.exclusions(ins).items()}
        self.assertEqual(exc, {'T_ext': 'model'})
        v = TF.verdict(True, {'inputs': ins, 'controls': {'vent': _ser('soil-real', 'percent')}}, exc)
        self.assertEqual((v['code'], v['missing'], v['excluded']), ('missing_inputs', ['T_ext'], ['T_ext']))
        self.assertEqual(TF.verdict(True, {'inputs': ins})['missing'], [])   # 판정 인자를 안 주면 예전과 같다

    def test_facility_plan_drops_the_input_and_notes_it(self):
        from aot.twin.discovery import FacilityInfo, SiteInfo
        ov = {'sites': {}, 'plots': {}, 'facilities': {'fac-1': {'enabled': True, 'inputs': {
            'T_int': _ser('soil-real', 'C'), 'T_ext': _ser('wx-model', 'C')}, 'controls': {}}}}
        TC.drop_non_observations(ov)
        site = SiteInfo('site-1', 'A', 'UTC', facilities=[FacilityInfo('fac-1', '온실', 'coord-1')])
        plan = build_plan([site], ov, lambda i: [])[0]
        t = plan.targets[0]
        self.assertEqual(set(t.inputs), {'T_int'})
        self.assertTrue(any('관측이 아님 — 동기화에서 제외: T_ext(모델값, SIM 김제 기상대)' in n for n in plan.notes))

    def test_unreadable_device_info_drops_nothing(self):
        with mock.patch.object(TC, '_device_names', side_effect=RuntimeError('db')):
            self.assertEqual(TC.exclusions({'rain': _ser('wx-model', 'mm')}), {})
