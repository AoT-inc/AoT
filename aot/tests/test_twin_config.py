# coding=utf-8
"""디지털트윈 S3: 대지·구획 트윈 설정(`twin_config` 표) — 상속·검사·제안·판정·서비스 연결·API.

- 순수: 대지 → 구획 상속(null 덮어쓰기), 저장 검사, 거리, 채널 후보 종류, 판정.
- DB(sqlite 진짜 모델): 저장 → `overrides()` → `build_plan` 이 같은 대상을 만든다, 구획 제외·null,
  관측 센서 제안(구획 안·30 m 안만), 예보 입력 제안(채널 메타만 본다 — 제공자 이름 무관),
  '모든 대지에 켜기' 는 빈 칸만 채운다, 마이그레이션 재실행.
- API: 플래그가 꺼져 있으면 404, 쓰기 권한, 잘못된 설정 422.
"""
import base64
import datetime
import importlib.util
import os
import tempfile
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import (DeviceMeasurements, GeoMap, GeoPlot, GeoShape, Input, Misc,
                                  TwinConfig)
from aot.inputs.open_meteo_daily_forecast import INPUT_INFORMATION as OM_DAILY
from aot.twin.discovery import DbCatalog, build_plan, combine
from aot.twin.gate import LazyApp
from aot.utils import twin_config as TC

_HERE = os.path.dirname(os.path.abspath(__file__))
RAIN = {'unique_id': 'rain-1', 'unit': 'mm', 'channel': 0, 'provenance': 'measured'}
THETA = {'unique_id': 'soil-1', 'unit': 'percent', 'channel': 0, 'provenance': 'measured'}


def _poly(ring):
    return {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [ring]}, 'properties': {}}


def _sq(x0, y0, d):
    return [[x0, y0], [x0, y0 + d], [x0 + d, y0 + d], [x0 + d, y0], [x0, y0]]


# ── 순수 ─────────────────────────────────────────────────────────────────────

class PureTest(unittest.TestCase):
    def test_effective_inherits_site_and_plot_overrides_with_null(self):
        site = {'inputs': {'rain': RAIN, 't_air': {'unique_id': 't', 'unit': 'C', 'channel': 1}},
                'forecast': {'input': 'fc-1'}}
        plot = {'inputs': {'theta': THETA, 't_air': None}}
        e = TC.effective(site, plot)
        self.assertEqual(e['rain'], {'value': RAIN, 'origin': 'site'})
        self.assertEqual(e['t_air'], {'value': None, 'origin': 'plot'})          # null = 이 구획에서는 없음
        self.assertEqual(e['theta'], {'value': THETA, 'origin': 'plot'})
        self.assertEqual(e['et0'], {'value': None, 'origin': None})
        self.assertEqual(e['forecast']['origin'], 'site')

    def test_validate_rejects_unknown_and_bad_values(self):
        ok = TC.validate_config({'inputs': {'rain': dict(RAIN, extra=1), 'theta': None},
                                 'options': {'rain': {'agg': 'daily_sum', 'scale': 2}},
                                 'forecast': {'input': ' fc-1 ', 'max_age_h': '24'}}, 'site')
        self.assertEqual(ok['inputs']['rain'], RAIN)                             # 모르는 칸은 저장하지 않는다
        self.assertIsNone(ok['inputs']['theta'])
        self.assertEqual(ok['forecast'], {'input': 'fc-1', 'max_age_h': 24.0})
        for bad in ({'nope': 1}, {'inputs': {'wind': RAIN}}, {'inputs': {'rain': dict(RAIN, provenance='x')}},
                    {'inputs': {'rain': dict(RAIN, unit='')}}, {'inputs': {'rain': {'unit': 'mm'}}},
                    {'options': {'rain': {'agg': 'max'}}}, {'options': {'rain': {'scale': 0}}},
                    {'forecast': {'max_age_h': 3}}, 'text'):
            with self.assertRaises(TC.TwinConfigError, msg=repr(bad)):
                TC.validate_config(bad, 'site')

    def test_distance_inside_zero_and_metres_outside(self):
        g = {'type': 'Polygon', 'coordinates': [_sq(127.0, 36.0, 0.001)]}
        self.assertEqual(TC.distance_m(g, 127.0005, 36.0005), 0.0)
        d = TC.distance_m(g, 127.001 + 0.0002, 36.0005)        # 동쪽 경계에서 경도 0.0002° ≈ 18 m
        self.assertAlmostEqual(d, 18.0, delta=1.0)
        self.assertIsNone(TC.distance_m({'type': 'Polygon', 'coordinates': []}, 0, 0))

    def test_channel_kinds_narrow(self):
        self.assertEqual(TC.channel_kinds('volumetric_water_content', 'percent', '', 'soil'), ['theta'])
        self.assertEqual(TC.channel_kinds('temperature', 'C', '지온', 'soil'), ['soil_t'])
        self.assertEqual(TC.channel_kinds('electrical_conductivity', 'percent', '', 'soil'), [])
        self.assertEqual(TC.channel_kinds('precipitation', 'mm', ''), ['rain'])
        self.assertEqual(TC.channel_kinds('temperature', 'C', 'Air'), ['t_air'])
        self.assertEqual(TC.channel_kinds('humidity', 'percent', ''), [])

    def test_verdict_codes(self):
        site = {'inputs': {'rain': RAIN}}
        good = {'included': True, 'effective': {'theta': {'value': THETA}}}
        unv = {'included': True, 'effective': {'theta': {'value': dict(THETA, provenance='unknown')}}}
        none = {'included': True, 'effective': {}}
        out = {'included': False, 'effective': {}}
        self.assertEqual(TC.verdict(False, site, [good])['code'], 'off')
        self.assertEqual(TC.verdict(True, site, [out])['code'], 'no_plots')
        self.assertEqual(TC.verdict(True, {}, [good])['code'], 'no_rain')
        v = TC.verdict(True, site, [unv])
        self.assertEqual((v['code'], v['unverified']), ('ready', 0))          # 출처 표시는 보지 않는다 — 위치로 정해진 센서 그대로
        self.assertEqual(TC.verdict(True, site, [good, none])['code'], 'partial')
        self.assertEqual(TC.verdict(True, site, [good, out])['code'], 'ready')

    def test_verdict_sensorless_codes(self):
        """센서 없는 구획은 기본으로 관측 없이 예측만 한다 — 판정이 '막힘' 이 아니라 '참고용' 이 된다."""
        site = {'inputs': {'rain': RAIN}}
        good = {'included': True, 'effective': {'theta': {'value': THETA}}}
        none = {'included': True, 'effective': {}, 'sensorless': 'predict'}
        off = {'included': True, 'effective': {}, 'sensorless': 'off'}
        v = TC.verdict(True, site, [none, none])
        self.assertEqual((v['code'], v['sensorless'], v['ready']), ('sensorless', 2, 0))
        v = TC.verdict(True, site, [good, none, off])
        self.assertEqual((v['code'], v['sensorless'], v['ready']), ('partial', 1, 1))
        self.assertEqual(TC.verdict(True, site, [off, off])['code'], 'no_sensor')     # 끄면 예전처럼 막힘
        self.assertEqual(TC.verdict(True, {}, [none])['code'], 'no_rain')             # 비는 늘 필요하다

    def test_sensorless_mode_plot_beats_site_and_defaults_to_predict(self):
        self.assertEqual(TC.sensorless_mode({}, {}), 'predict')
        self.assertEqual(TC.sensorless_mode({'options': {'sensorless': 'off'}}, {}), 'off')
        self.assertEqual(TC.sensorless_mode({'options': {'sensorless': 'off'}},
                                            {'options': {'sensorless': 'predict'}}), 'predict')
        with self.assertRaises(TC.TwinConfigError):
            TC.validate_config({'options': {'sensorless': 'maybe'}}, 'plot')
        self.assertEqual(TC.validate_config({'options': {'sensorless': 'off'}}, 'plot')['options'],
                         {'sensorless': 'off'})

    def test_diagnose_plot_names_cause_in_order(self):
        eff = lambda **k: {kk: {'value': vv} for kk, vv in k.items()}
        base = {'included': True, 'started_on': '2026-06-20', 'sensorless': 'predict',
                'effective': eff(rain=RAIN)}
        d = lambda e, n=None, on=True: TC.diagnose_plot(on, e, n)
        self.assertEqual(d(dict(base, included=False)), 'excluded')
        self.assertEqual(d(base, on=False), 'site_off')
        self.assertEqual(d(dict(base, started_on=None)), 'no_planted')
        self.assertEqual(d(dict(base, effective=eff())), 'no_rain')
        self.assertEqual(d(dict(base, effective=eff(rain=RAIN, theta=THETA))), 'synced')
        self.assertEqual(d(dict(base, effective=eff(rain=RAIN, theta=dict(THETA, provenance='unknown')))),
                         'synced')                                           # 출처 표시는 판정에 쓰지 않는다
        self.assertEqual(d(base, 2), 'suggest_sensor')
        self.assertEqual(d(base, 0), 'sensorless')
        self.assertEqual(d(base, None), 'sensorless')
        self.assertEqual(d(dict(base, sensorless='off'), 0), 'sensorless_off')

    def test_combine_dev_json_wins(self):
        db_ov = {'sites': {'s': {'enabled': True, 'inputs': {'rain': RAIN}}}}
        dev = {'sites': {'s': {'inputs': {'t_air': RAIN}}}}
        c = combine(db_ov, dev)
        self.assertEqual(set(c['sites']['s']['inputs']), {'rain', 't_air'})
        self.assertTrue(c['sites']['s']['enabled'])


# ── DB ───────────────────────────────────────────────────────────────────────

FAKE_FC = {'measurements_dict': {0: {'measurement': 'precipitation', 'unit': 'mm', 'forecast_lead_d': 0,
                                     'daily_stat': 'sum'}}}
SOIL_MOD = {'provenance': 'measured', 'measurements_dict': {}}
INFO = {'OPEN_METEO_DAILY_FORECAST': OM_DAILY, 'ANY_FUTURE_FORECAST': FAKE_FC, 'SOIL_PROBE': SOIL_MOD}


class DbTest(unittest.TestCase):
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
                                   started_on=datetime.date(2026, 6, 20),
                                   feature=_poly(_sq(x, 35.862, 0.001))))
        # 토양 센서 둘: p1 동쪽 경계에서 약 18 m(제안), 약 90 m(제안 아님). 기상대 지정 장치 하나.
        for uid, lng in (('soil-near', 126.883 + 0.0002), ('soil-far', 126.883 + 0.001)):
            db.session.add(Input(unique_id=uid, device='SOIL_PROBE', name=uid))
            db.session.add(DeviceMeasurements(device_id=uid, channel=0, measurement='volumetric_water_content',
                                              unit='percent', name='토양수분'))
            db.session.add(DeviceMeasurements(device_id=uid, channel=1, measurement='temperature',
                                              unit='C', name='지온'))
            GeoShape(unique_id='mk-' + uid, geo_id='m1', type='aot_device', device_id=uid,
                     feature={'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lng, 35.8625]},
                              'properties': {}}).save()
        db.session.add(Input(unique_id='wx-1', device='SOME_STATION', name='기상대'))
        db.session.add(DeviceMeasurements(device_id='wx-1', channel=0, measurement='precipitation', unit='mm',
                                          name='강수'))
        db.session.add(DeviceMeasurements(device_id='wx-1', channel=1, measurement='temperature', unit='C',
                                          name='기온'))
        # 예보 입력 둘 — 하나는 기존 모듈, 하나는 이름 모를 새 모듈(채널 메타만 같다). 가까운 것이 먼저.
        db.session.add(Input(unique_id='fc-far', device='OPEN_METEO_DAILY_FORECAST', name='먼 예보',
                             latitude=37.5, longitude=127.0, is_activated=True))
        db.session.add(Input(unique_id='fc-near', device='ANY_FUTURE_FORECAST', name='가까운 예보',
                             latitude=35.87, longitude=126.89, is_activated=True))
        db.session.commit()
        # 드라이버 판정은 첫 결과를 전역에 캐시한다. 가짜 목록의 결과가 같은 작업자의 다음 시험으로 새지 않게 한다.
        for name in ('_MODEL_DRIVERS', '_FORECAST_TIME_DRIVERS', '_DAILY_FORECAST_DRIVERS'):
            c = mock.patch(f'aot.utils.inputs.{name}', None)
            c.start()
            self.addCleanup(c.stop)
        p = mock.patch('aot.utils.inputs.parse_input_information', return_value=INFO)
        p.start()
        self.addCleanup(p.stop)
        w = mock.patch('aot.aot_flask.geo.device_membership.weather_device_ids',
                       side_effect=lambda sid: (['wx-1'], 'bound') if sid == 'site-1' else ([], 'none'))
        w.start()
        self.addCleanup(w.stop)
        a = mock.patch.object(TC, 'agreement', return_value={})
        a.start()
        self.addCleanup(a.stop)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_saved_settings_drive_the_service_plan(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': RAIN}, 'forecast': {'input': 'fc-far'}},
                set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'theta': THETA}})
        TC.save('plot', 'p2', False, None, set_enabled=True)
        ov = TC.overrides()
        self.assertEqual(ov['sites']['site-1']['enabled'], True)
        self.assertNotIn('enabled', ov['plots']['p1'])                          # NULL = 대지를 따른다
        cat = DbCatalog(LazyApp(lambda: self.app))
        plans = build_plan(cat.sites(), ov, cat.forecast_channels)
        self.assertEqual([p.site_id for p in plans], ['site-1'])
        t = plans[0].targets
        self.assertEqual([x.target_id for x in t], ['p1'])                       # p2 제외
        self.assertEqual(set(t[0].inputs), {'rain', 'theta'})
        self.assertEqual(t[0].inputs['theta'].provenance.value, 'measured')
        # 앞날 예보는 대지 예보 계열 — 고른 입력은 대지 예보 출처 지정(geo_binding)에 저장된다
        self.assertEqual(t[0].options['forecast_series'], {'site': 'site-1'})
        from aot.aot_flask.geo import device_binding as B
        self.assertEqual(B.site_forecast_ids('site-1'), ['fc-far'])
        self.assertNotIn('forecast', TC.get_row('site', 'site-1').config_dict())   # 트윈 표에는 두지 않는다
        self.assertEqual(TC.read('site', 'site-1')[1]['forecast'], {'input': 'fc-far'})

    def test_old_screen_resending_a_designated_forecast_keeps_the_order(self):
        """예전 트윈 탭은 저장 때마다 예보 칸을 되보냈다 — 이미 지정된 입력이면 순서(시간별 → 일별)를 흔들지 않는다."""
        from aot.aot_flask.geo import device_binding as B
        db.session.add(Input(unique_id='fc-hourly', device='ANY_HOURLY', name='시간별'))
        db.session.commit()
        B.set_site_forecast('site-1', ['fc-hourly', 'fc-far'], commit=True)
        TC.save('site', 'site-1', True, {'forecast': {'input': 'fc-far'}}, set_enabled=True)
        self.assertEqual(B.site_forecast_ids('site-1'), ['fc-hourly', 'fc-far'])
        v = TC.site_view('site-1')
        self.assertEqual(v['forecast_source']['selected'], ['fc-hourly', 'fc-far'])

    def test_plot_null_drops_inherited_input(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': RAIN}}, set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'rain': None, 'theta': THETA}})
        cat = DbCatalog(LazyApp(lambda: self.app))
        plans = build_plan(cat.sites(), TC.overrides(), cat.forecast_channels)
        p1 = next(x for x in plans[0].targets if x.target_id == 'p1')
        self.assertEqual(set(p1.inputs), {'theta'})

    def test_nothing_saved_means_nothing_runs(self):
        cat = DbCatalog(LazyApp(lambda: self.app))
        self.assertEqual(build_plan(cat.sites(), TC.overrides(), cat.forecast_channels), [])

    def test_sensor_suggestion_near_first_then_nearest_with_provenance_from_module(self):
        s = TC.plot_suggestions('p1')
        self.assertEqual([c['unique_id'] for c in s['theta']], ['soil-near'])
        self.assertEqual(s['theta'][0]['why'], 'near')
        self.assertAlmostEqual(s['theta'][0]['distance_m'], 18.0, delta=1.5)
        self.assertEqual(s['theta'][0]['provenance'], 'measured')               # 모듈이 밝힌 값
        self.assertEqual([(c['unique_id'], c['channel']) for c in s['soil_t']], [('soil-near', 1)])
        s2 = TC.plot_suggestions('p2')                                          # 둘 다 30 m 밖 → 가장 가까운 것(거리 표시)
        self.assertEqual([c['unique_id'] for c in s2['theta']], ['soil-far', 'soil-near'])
        self.assertEqual({c['why'] for c in s2['theta']}, {'zone'})                  # 같은 대지 안 센서 = 구역 대표값
        self.assertGreater(s2['theta'][0]['distance_m'], 30)
        self.assertEqual(TC.read('plot', 'p1'), (None, {}))                     # 제안은 저장하지 않는다

    def test_plot_suggestion_far_sensor_outside_site_is_nearest(self):
        """대지 밖(구역 대표 아님)이라도 같은 지도의 가장 가까운 토양 센서를 거리와 함께 제안한다."""
        GeoShape(unique_id='mk-out', geo_id='m1', type='aot_device', device_id='soil-far',
                 feature={'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [126.9, 35.8625]},
                          'properties': {}}).save()
        db.session.query(GeoShape).filter_by(unique_id='mk-soil-far').delete()
        db.session.commit()
        with mock.patch('aot.aot_flask.geo.plot_context.sensors_for_plot', return_value={'from_zone': []}):
            s = TC.plot_suggestions('p2')
        self.assertEqual([c['unique_id'] for c in s['theta']], ['soil-near', 'soil-far'])
        self.assertEqual({c['why'] for c in s['theta']}, {'nearest'})

    def test_site_weather_falls_back_to_nearest_channel_on_the_map(self):
        GeoShape(unique_id='mk-wx', geo_id='m1', type='aot_device', device_id='wx-1',
                 feature={'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [126.8812, 35.8625]},
                          'properties': {}}).save()
        site = next(x for x in TC.catalog_sites() if x.site_id == 'site-1')
        with mock.patch('aot.aot_flask.geo.device_membership.weather_device_ids', return_value=([], 'none')):
            s = TC.site_suggestions(site)
        self.assertEqual([(c['unique_id'], c['why']) for c in s['rain']], [('wx-1', 'weather_nearest')])
        self.assertEqual([c['unique_id'] for c in s['t_air']], ['wx-1'])
        self.assertIn('distance_m', s['rain'][0])
        with mock.patch('aot.aot_flask.geo.device_membership.weather_device_ids',
                        return_value=(['wx-1'], 'inferred')):
            s = TC.site_suggestions(site)
        self.assertEqual(s['rain'][0]['why'], 'weather_inferred')

    def test_site_forecast_inside_first_and_create_offer_only_when_none_near(self):
        site = next(x for x in TC.catalog_sites() if x.site_id == 'site-1')
        s = TC.site_suggestions(site)
        self.assertEqual(s['forecast'][0]['input'], 'fc-near')
        self.assertNotIn('forecast_create', s)                                   # 가까운 켜진 예보가 있다
        # 먼 입력이 대지 안 장치로 놓여 있으면 거리와 상관없이 앞에 온다
        GeoShape(unique_id='mk-fc', geo_id='m1', type='aot_device', device_id='fc-far',
                 feature={'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [126.8812, 35.8625]},
                          'properties': {}}).save()
        with mock.patch('aot.aot_flask.geo.device_membership.device_ids_in_area', return_value={'fc-far'}):
            s = TC.site_suggestions(site)
        self.assertEqual((s['forecast'][0]['input'], s['forecast'][0]['why']), ('fc-far', 'forecast_inside'))
        for r in Input.query.filter(Input.unique_id.in_(['fc-far', 'fc-near'])).all():
            r.is_activated = False
        db.session.commit()
        s = TC.site_suggestions(site)
        self.assertEqual(s['forecast_create']['module'], TC.forecast_module())
        self.assertAlmostEqual(s['forecast_create']['lat'], 35.862, delta=0.01)

    def test_forecast_module_is_chosen_by_channel_meta_only(self):
        mods = TC._forecast_modules()
        self.assertEqual(set(mods), {'OPEN_METEO_DAILY_FORECAST', 'ANY_FUTURE_FORECAST'})   # 소일 센서 모듈은 아니다
        self.assertEqual(TC.forecast_module(), sorted(mods, key=lambda m: (-mods[m], m))[0])
        self.assertIsNone(TC.forecast_module({'SOIL_PROBE': SOIL_MOD}))

    def test_ensure_site_forecast_creates_once_and_selects_it(self):
        for r in Input.query.filter(Input.unique_id.in_(['fc-far', 'fc-near'])).all():
            r.is_activated = False
        db.session.commit()
        def made(*_a, **_k):                    # 진짜처럼 입력 행이 생긴다 — 지정은 있는 장치만 받는다
            db.session.add(Input(unique_id='fc-new', device='OPEN_METEO_DAILY_FORECAST', name='새 예보'))
            db.session.commit()
            return 'fc-new'
        with mock.patch.object(TC, 'create_forecast_input', side_effect=made) as mk:
            self.assertEqual(TC.ensure_site_forecast('site-1'), 'fc-new')
            self.assertEqual(TC.read('site', 'site-1')[1]['forecast']['input'], 'fc-new')
            self.assertEqual(TC.ensure_site_forecast('site-1'), None)             # 이미 정해 뒀다
            self.assertEqual(mk.call_count, 1)

    def test_ensure_site_forecast_with_near_input_only_fills_empty_slot(self):
        with mock.patch.object(TC, 'create_forecast_input') as mk:
            self.assertIsNone(TC.ensure_site_forecast('site-1'))
            mk.assert_not_called()
        self.assertEqual(TC.read('site', 'site-1')[1]['forecast'], {'input': 'fc-near'})

    def test_create_forecast_input_builds_a_complete_input(self):
        msgs = {'success': [], 'info': [], 'warning': [], 'error': []}
        with mock.patch('aot.aot_flask.utils.utils_input.check_input_channels_exist', return_value=msgs), \
                mock.patch('aot.aot_flask.utils.utils_general.controller_activate_deactivate',
                           return_value=msgs) as act:
            uid = TC.create_forecast_input(35.86, 126.88, '새 예보')
        row = Input.query.filter_by(unique_id=uid).one()
        self.assertEqual((row.name, row.latitude, row.longitude), ('새 예보', 35.86, 126.88))
        self.assertEqual(row.device, TC.forecast_module())
        self.assertEqual(act.call_args[0][1:4], ('activate', 'Input', uid))
        with self.assertRaises(TC.TwinConfigError):
            TC.create_forecast_input(95, 126.88)

    def test_spinup_from_is_validated(self):
        TC.save('plot', 'p1', None, {'options': {'spinup_from': '2026-08-05'}})
        self.assertEqual(TC.read('plot', 'p1')[1]['options']['spinup_from'], '2026-08-05')
        with self.assertRaises(TC.TwinConfigError):
            TC.save('plot', 'p1', None, {'options': {'spinup_from': '8/5'}})

    def test_site_suggestions_bound_weather_and_forecast_by_meta(self):
        site = next(x for x in TC.catalog_sites() if x.site_id == 'site-1')
        s = TC.site_suggestions(site)
        self.assertEqual([(c['unique_id'], c['channel']) for c in s['rain']], [('wx-1', 0)])
        self.assertEqual([(c['unique_id'], c['channel']) for c in s['t_air']], [('wx-1', 1)])
        self.assertEqual(s['rain'][0]['provenance'], 'unknown')                  # 모듈이 밝히지 않음 → 미확인
        self.assertEqual([f['input'] for f in s['forecast']], ['fc-near', 'fc-far'])

    def test_forecast_channels_are_not_observation_candidates_and_names(self):
        db.session.add(DeviceMeasurements(device_id='fc-far', channel=0, measurement='precipitation', unit='mm',
                                          name='Rain (daily sum) +0d'))
        db.session.commit()
        by = {(c['unique_id'], c['channel']): c for c in TC.channels()}
        self.assertEqual(by[('fc-far', 0)]['kinds'], [])                       # 예보 채널은 비 관측 후보가 아님
        self.assertEqual(by[('wx-1', 0)]['kinds'], ['rain'])
        TC.save('site', 'site-1', True, {'inputs': {'rain': dict(RAIN, unique_id='wx-1')},
                                         'forecast': {'input': 'fc-far'}}, set_enabled=True)
        v = TC.with_names(TC.site_view('site-1'))
        self.assertEqual(v['names']['wx-1'], '기상대')
        self.assertEqual(v['names']['fc-far'], '먼 예보')

    def test_enable_all_fills_only_empty_slots(self):
        mine = dict(RAIN, unique_id='my-rain')
        TC.save('site', 'site-1', False, {'inputs': {'rain': mine}}, set_enabled=True)
        res = TC.enable_all(apply_suggestions=True)
        self.assertEqual(res['sites'], 1)
        en, cfg = TC.read('site', 'site-1')
        self.assertTrue(en)
        self.assertEqual(cfg['inputs']['rain']['unique_id'], 'my-rain')          # 사용자가 고른 것은 그대로
        self.assertEqual(cfg['inputs']['t_air']['unique_id'], 'wx-1')
        self.assertEqual(cfg['forecast'], {'input': 'fc-near'})
        self.assertEqual(TC.read('plot', 'p1')[1]['inputs']['theta']['unique_id'], 'soil-near')
        self.assertEqual(TC.read('plot', 'p2')[1]['inputs']['theta']['unique_id'], 'soil-far')   # 가까운 센서가 제안

    def test_enable_all_without_suggestions_only_turns_on(self):
        TC.enable_all()
        en, cfg = TC.read('site', 'site-1')
        self.assertTrue(en)
        self.assertEqual(cfg, {})

    def test_views_and_overview(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': RAIN}}, set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'theta': THETA}})
        v = TC.site_view('site-1')
        self.assertEqual(v['verdict']['code'], 'ready')                           # p2 는 구역 센서를 도형 상속으로 쓴다
        self.assertEqual([p['plot_id'] for p in v['plots']], ['p1', 'p2'])
        pv = TC.plot_view('p1')
        self.assertTrue(pv['eligible'])
        self.assertEqual(pv['effective']['rain']['origin'], 'site')
        self.assertEqual(pv['effective']['theta']['origin'], 'plot')
        self.assertFalse(TC.plot_view('nope')['eligible'])
        ov = {r['site_id']: r for r in TC.overview()}
        self.assertEqual(ov['site-1']['verdict']['code'], 'partial')
        self.assertEqual(ov['site-1']['sensor_suggested_plots'], 1)               # p2 는 30 m 안엔 없지만 가까운 센서가 제안

    def test_site_view_uses_inherited_values_and_marks_where_they_come_from(self):
        """저장된 선택이 없으면 도형 상속값이 '쓰는 값' — 기상대(비·기온)·구획 센서. 직접 정한 것은 own."""
        TC.save('site', 'site-1', True, {'inputs': {'rain': RAIN}}, set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'theta': THETA}})
        v = TC.site_view('site-1')
        p1, p2 = v['plots']
        self.assertEqual((p1['diagnosis'], p2['diagnosis']), ('synced', 'synced'))
        self.assertEqual(v['used']['rain']['origin'], 'own')                     # 직접 지정
        self.assertEqual(v['used']['t_air']['origin'], 'inherited')              # 기상대에서 물려받음
        self.assertEqual(v['used']['t_air']['value']['unique_id'], 'wx-1')
        self.assertEqual(p1['used']['theta']['origin'], 'own')
        self.assertEqual(p2['used']['theta']['origin'], 'inherited')             # 구역 대표 센서(zone)
        self.assertEqual(p2['used']['theta']['value']['unique_id'], 'soil-far')
        self.assertEqual(p2['used']['theta']['why'], 'zone')
        self.assertEqual(v['config']['inputs'], {'rain': RAIN})                  # 상속값은 저장하지 않는다
        self.assertEqual(TC.read('plot', 'p2')[1], {})
        self.assertEqual(v['verdict']['code'], 'ready')

    def test_plot_view_says_what_the_plot_uses_and_what_clearing_an_override_falls_back_to(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': RAIN}}, set_enabled=True)
        TC.save('plot', 'p1', None, {'inputs': {'theta': THETA, 't_air': None}})
        u1 = TC.plot_view('p1')['used']
        self.assertEqual((u1['theta']['origin'], u1['rain']['origin']), ('own', 'site'))   # 직접 지정 / 대지 값
        self.assertEqual(u1['t_air']['origin'], 'none')                                    # 이 구획에서는 없음(덮어쓰기)
        self.assertEqual(u1['t_air']['fallback']['origin'], 'inherited')                   # 걷으면 기상대를 따른다
        u2 = TC.plot_view('p2')['used']
        self.assertEqual(u2['theta']['origin'], 'inherited')
        self.assertEqual(u2['theta']['why'], 'zone')
        self.assertEqual(u2['t_air']['origin'], 'inherited')                               # 대지 기상대 상속이 구획까지

    def test_null_input_is_an_override_and_stops_inheritance(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': None}}, set_enabled=True)
        v = TC.site_view('site-1')
        self.assertEqual(v['used']['rain']['origin'], 'none')
        self.assertEqual(v['verdict']['code'], 'no_rain')
        self.assertEqual([p['diagnosis'] for p in v['plots']], ['no_rain', 'no_rain'])

    def test_resolved_overrides_fill_only_missing_inputs_for_enabled_sites(self):
        TC.save('plot', 'p1', None, {'inputs': {'theta': THETA}})
        self.assertNotIn('inputs', TC.resolved_overrides()['sites'].get('site-1', {}))       # 꺼진 대지는 채우지 않는다
        TC.save('site', 'site-1', True, {'inputs': {'rain': RAIN}}, set_enabled=True)
        ov = TC.resolved_overrides()
        ins = ov['sites']['site-1']['inputs']
        self.assertEqual(ins['rain'], RAIN)                                                  # 직접 정한 것이 이긴다
        self.assertEqual(ins['t_air']['unique_id'], 'wx-1')
        self.assertEqual(ov['plots']['p1']['inputs']['theta'], THETA)
        self.assertEqual(ov['plots']['p2']['inputs']['theta']['unique_id'], 'soil-far')
        self.assertNotIn('theta', TC.overrides()['plots'].get('p2', {}).get('inputs', {}))   # 표에는 쓰지 않았다

    def test_other_site_choice_comes_first_with_rain_options(self):
        """같은 지도의 다른 대지에서 사용자가 고른 비·기온을 맨 앞에 — 묶는 법(options.rain)도 같이."""
        site2 = _poly(_sq(126.80, 35.80, 0.01))
        site2['properties']['name'] = 'B 포장'
        GeoShape(unique_id='site-2', geo_id='m1', type='site', feature=site2).save()
        db.session.add(GeoPlot(unique_id='p3', geo_id='m1', name='p3', kind='vegetation', subject='콩',
                               started_on=datetime.date(2026, 6, 20), feature=_poly(_sq(126.802, 35.802, 0.001))))
        db.session.add(Input(unique_id='wx-2', device='SOME_STATION', name='다른 기상대'))
        db.session.add(DeviceMeasurements(device_id='wx-2', channel=3, measurement='precipitation', unit='mm',
                                          name='강수15분'))
        db.session.commit()
        mine = {'unique_id': 'wx-2', 'unit': 'mm', 'channel': 3, 'provenance': 'measured'}
        TC.save('site', 'site-2', True, {'inputs': {'rain': mine},
                                         'options': {'rain': {'agg': 'hourly_mean_sum', 'scale': 4, 'kind': 'station'}}},
                set_enabled=True)
        sites = TC.catalog_sites()
        site1 = next(x for x in sites if x.site_id == 'site-1')
        rain = TC.site_suggestions(site1, sites)['rain']
        self.assertEqual([(c['unique_id'], c['why']) for c in rain], [('wx-2', 'other_site'), ('wx-1', 'weather_bound')])
        self.assertEqual(rain[0]['rain_options']['scale'], 4)
        self.assertEqual(rain[0]['from_site'], 'B 포장')
        self.assertEqual([c['unique_id'] for c in TC.site_suggestions(site1)['rain']], ['wx-1'])    # sites 를 안 주면 예전과 같다
        TC.enable_all(apply_suggestions=True, sites=sites)                                          # 빈 칸 채우기도 같은 순서
        cfg = TC.read('site', 'site-1')[1]
        self.assertEqual(cfg['inputs']['rain']['unique_id'], 'wx-2')
        self.assertEqual(cfg['options']['rain']['scale'], 4)
        self.assertEqual(TC.read('site', 'site-2')[1]['inputs']['rain'], mine)                      # 남의 설정은 그대로

    def test_unique_per_target(self):
        TC.save('site', 'site-1', True, None, set_enabled=True)
        TC.save('site', 'site-1', None, {'inputs': {'rain': RAIN}})
        self.assertEqual(TwinConfig.query.count(), 1)
        self.assertEqual(TC.read('site', 'site-1')[0], True)                      # enabled 를 안 주면 그대로


def _load_migration():
    return _load_named('p6_91_twin_config_20261021')


def _load_named(name):
    path = os.path.join(_HERE, '..', '..', 'alembic_db', 'alembic', 'versions', name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_chain_and_idempotent(tmp_path):
    import sqlalchemy as sa
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    mod = _load_migration()
    assert mod.revision == 'p6_91_twin_config_20261021'
    assert mod.down_revision == 'p6_90_twin_settings_20261021'
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'mig.db'))

    def run(fn):
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                getattr(mod, fn)()
    run('upgrade')
    run('upgrade')
    cols = {c['name'] for c in sa.inspect(engine).get_columns('twin_config')}
    assert {'scope', 'target_id', 'enabled', 'config'} <= cols
    run('downgrade')
    run('downgrade')
    assert 'twin_config' not in sa.inspect(engine).get_table_names()


# ── API ──────────────────────────────────────────────────────────────────────

_APP = {}
H = 'application/vnd.aot.v1+json'


def setUpModule():
    import flask_login
    from flask import Blueprint
    from flask_babel import Babel
    from flask_restx import Api

    from aot.aot_flask.api import api as global_api
    from aot.aot_flask.api.twin import ns_twin
    from aot.aot_flask.extensions import csrf
    from aot.databases.models import Role, User

    tmp = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(tmp.name, 't.db'),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY='x', WTF_CSRF_ENABLED=False,
                      TESTING=True)
    db.init_app(app)
    csrf.init_app(app)
    bp = Blueprint('api_twin_cfg_test', __name__, url_prefix='/api')
    api = Api(bp, default_mediatype=H)
    for media, fn in global_api.representations.items():
        api.representations[media] = fn
    api.add_namespace(ns_twin)
    csrf.exempt(bp)
    Babel(app)
    app.register_blueprint(bp)
    lm = flask_login.LoginManager()
    lm.init_app(app)

    @lm.request_loader
    def _load(req):
        try:
            return User.find_by_api_key(base64.b64decode(req.headers.get('X-API-KEY')))
        except Exception:
            return None

    with app.app_context():
        db.create_all()
        db.session.add(Misc())
        admin = Role(name='Admin', edit_settings=True, view_settings=True)
        viewer = Role(name='Viewer', edit_settings=False, view_settings=True)
        db.session.add_all([admin, viewer])
        db.session.commit()
        keys = {}
        for name, role in (('admin', admin), ('viewer', viewer)):
            u = User(name='u_' + name, email=name + '@example.com', role_id=role.id)
            u.set_password('correct horse battery staple')
            db.session.add(u)
            db.session.flush()
            keys[name] = base64.b64encode(u.issue_api_key(name, 'full')).decode()
        db.session.add(GeoPlot(unique_id='p1', geo_id='m1', name='p1', kind='vegetation', subject='들깨',
                               started_on=datetime.date(2026, 6, 20)))
        db.session.commit()
    _APP.update(app=app, tmp=tmp, keys=keys, client=app.test_client())


def tearDownModule():
    _APP['tmp'].cleanup()


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.c = _APP['client']
        self.k = _APP['keys']
        for target, kw in (('aot.utils.twin_gate.twin_enabled', {'return_value': True}),
                           ('aot.utils.twin_config.catalog_sites', {'return_value': []}),
                           ('aot.utils.twin_config.agreement', {'return_value': {}})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def _h(self, who='admin'):
        return {'X-API-KEY': self.k[who], 'Accept': H}

    def test_flag_off_is_404(self):
        with mock.patch('aot.utils.twin_gate.twin_enabled', return_value=False), \
                mock.patch.dict(os.environ, {'AOT_TWIN_ENABLED': ''}):
            for url in ('/api/twin/config/site/site-1', '/api/twin/config/plot/p1', '/api/twin/config/overview',
                        '/api/twin/config/channels', '/api/twin/plots'):
                self.assertEqual(self.c.get(url, headers=self._h()).status_code, 404, url)

    def test_put_site_and_plot_then_read_back(self):
        r = self.c.put('/api/twin/config/site/site-1', headers=self._h(),
                       json={'enabled': True, 'config': {'inputs': {'rain': RAIN}}})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()['enabled'])
        r = self.c.put('/api/twin/config/plot/p1', headers=self._h(), json={'enabled': False})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        with _APP['app'].app_context():
            self.assertEqual(TC.read('plot', 'p1'), (False, {}))
            self.assertEqual(TC.read('site', 'site-1')[1]['inputs']['rain'], RAIN)

    def test_bad_config_422_and_unknown_plot_404(self):
        r = self.c.put('/api/twin/config/site/s', headers=self._h(),
                       json={'config': {'inputs': {'rain': dict(RAIN, provenance='maybe')}}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.c.put('/api/twin/config/plot/nope', headers=self._h(), json={}).status_code, 404)

    def test_viewer_cannot_write(self):
        self.assertEqual(self.c.get('/api/twin/config/overview', headers=self._h('viewer')).status_code, 200)
        r = self.c.put('/api/twin/config/site/s', headers=self._h('viewer'), json={'enabled': True})
        self.assertEqual(r.status_code, 403)
        r = self.c.post('/api/twin/config/enable_all', headers=self._h('viewer'), json={})
        self.assertEqual(r.status_code, 403)


if __name__ == '__main__':
    unittest.main()
