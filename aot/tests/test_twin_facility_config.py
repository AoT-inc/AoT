# coding=utf-8
"""디지털트윈 시설 설정(`twin_config` scope 'facility', `twin_facility_config`) — 검사·판정·발견·API.

- 순수: 저장 검사(칸·scale·옵션), 판정 순서, 새 '실측' 판별, 시설 부품 이름과의 일치.
- DB(sqlite 진짜 모델): 시설 행만으로 켜기(대지 켜짐 무관), 출력 태그 = 코디네이터 uuid(없으면 시설 uuid + 노트),
  가상 출력 채널의 실측 거부, 미러 실측 알림은 새로 정할 때 한 번, 노지 대지 목록에 시설만 있는 대지가 안 낀다.
- 읽기 경로: `scale` 은 장치 상태 계열만 0~100 % 로 옮기고 없으면 변환하지 않는다.
- API: 저장 → 되읽기, 가상 출력 실측 422, 모르는 칸 422, 없는 시설 422.
"""
import datetime
import json
import os
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import (Conversion, CustomController, DeviceMeasurements, GeoFacility, GeoMap, GeoPlot, GeoShape,
                                  Input, Misc, Output)
from aot.tests.test_twin_config import (H, INFO, RAIN, _APP, _poly, _sq, setUpModule,  # noqa: F401
                                        tearDownModule)
from aot.twin.discovery import DbCatalog, build_plan, combine
from aot.twin.gate import LazyApp
from aot.twin.models import facility_greybox as FG
from aot.twin.settings import _series as parse_series
from aot.twin.types import Provenance, TargetKind
from aot.utils import twin_config as TC
from aot.utils import twin_facility_config as TF

M = lambda uid, ch=0, unit='C': {'unique_id': uid, 'unit': unit, 'channel': ch, 'provenance': 'measured'}  # noqa: E731
MIRROR = lambda uid, ch=0, unit='C': {'unique_id': uid, 'unit': unit, 'channel': ch, 'provenance': 'mirror'}  # noqa: E731

FULL = {'inputs': {'T_int': M('s1', 0), 'RH_int': M('s1', 1, 'percent'), 'T_ext': M('w1', 0),
                   'RH_ext': M('w1', 1, 'percent')},
        'controls': {'vent': M('v1', 0, 'percent')}}


class PureTest(unittest.TestCase):
    def test_keys_match_the_model_part(self):
        self.assertEqual(set(TF.CONTROL_KEYS), set(FG.CONTROL_NAMES))
        wired = {'T_int', 'RH_int', 'CO2_int', 'T_ext', 'RH_ext', 'CO2_ext', 'solar', 'wind'}
        self.assertEqual(set(TF.INPUT_KEYS), wired)

    def test_validate_keeps_known_and_rejects_unknown(self):
        ok = TF.validate_config({'inputs': {'T_int': dict(M('s1'), extra=1), 'solar': None},
                                 'controls': {'vent': dict(M('v1', 0, 'percent'),
                                                           scale={'from_min': '0', 'from_max': 1})},
                                 'options': {'T_high': '33', 'forecast_series': {'site': ' site-1 '}}})
        self.assertEqual(ok['inputs']['T_int'], M('s1'))
        self.assertIsNone(ok['inputs']['solar'])
        self.assertEqual(ok['controls']['vent']['scale'], {'from_min': 0.0, 'from_max': 1.0})
        self.assertEqual(ok['options'], {'T_high': 33.0, 'forecast_series': {'site': 'site-1'}})
        for bad in ({'forecast': {}}, {'inputs': {'rain': M('x')}}, {'controls': {'light': M('x')}},
                    {'options': {'greybox': {}}}, {'options': {'T_high': 999}},
                    {'options': {'forecast_series': {'site': ''}}},
                    {'controls': {'vent': dict(M('v'), scale={'from_min': 1, 'from_max': 1})}},
                    {'inputs': {'T_int': dict(M('s'), provenance='maybe')}},
                    {'inputs': {'T_int': {'unique_id': 's', 'channel': 0}}}):
            with self.assertRaises(TC.TwinConfigError, msg=str(bad)):
                TF.validate_config(bad)

    def test_verdict_order_matches_the_model_part(self):
        v = TF.verdict(False, {})
        self.assertEqual((v['code'], v['enabled']), ('missing_inputs', False))
        self.assertEqual(v['missing'], list(TF.REQUIRED_INPUTS))
        no_ctl = {'inputs': FULL['inputs']}
        self.assertEqual(TF.verdict(True, no_ctl)['code'], 'no_controls')           # 지금 영양·김제
        mirror = {'inputs': dict(FULL['inputs'], T_int=MIRROR('s1')), 'controls': FULL['controls']}
        v = TF.verdict(True, mirror)
        self.assertEqual((v['code'], v['unverified']), ('ready', []))               # 출처 표시는 판정에 쓰지 않는다
        self.assertEqual(TF.verdict(True, FULL)['code'], 'ready')

    def test_scale_parses_into_series_ref_and_none_means_no_conversion(self):
        r = parse_series(dict(M('v', 0, 'percent'), scale={'from_min': 0, 'from_max': 4}))
        self.assertEqual(r.scale, (0.0, 4.0))
        self.assertIsNone(parse_series(M('v')).scale)
        with self.assertRaises(ValueError):
            parse_series(dict(M('v'), scale={'from_min': 2, 'from_max': 1}))

    def test_model_part_scales_only_when_asked(self):
        from aot.twin.types import SeriesRef
        raw = [0.0, 2.0, 9.0, -1.0]
        plain = SeriesRef('v', 'percent', 0, Provenance.MEASURED)
        scaled = SeriesRef('v', 'percent', 0, Provenance.MEASURED, (0.0, 4.0))
        self.assertEqual(FG.apply_scale(plain, raw), raw)                        # 없으면 변환하지 않는다
        self.assertEqual(FG.apply_scale(scaled, raw), [0.0, 50.0, 100.0, 0.0])   # 범위 → 0~100, 밖은 자른다


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
        db.session.add(GeoPlot(unique_id='p1', geo_id='m1', name='p1', kind='vegetation', subject='들깨',
                               started_on=datetime.date(2026, 6, 20), feature=_poly(_sq(126.882, 35.862, 0.001))))
        # 시설 둘 — f1 은 코디네이터 있음, f2 는 없음
        for fid, sid, x in (('fac-1', 'shp-1', 126.884), ('fac-2', 'shp-2', 126.887)):
            GeoShape(unique_id=sid, geo_id='m1', type='facility', feature=_poly(_sq(x, 35.865, 0.002))).save()
            db.session.add(GeoFacility(unique_id=fid, shape_uuid=sid, geo_id='m1', name='시설 ' + fid))
        db.session.add(CustomController(unique_id='coord-1', device='env_coordinator', name='Env Coordinator',
                                        is_activated=True,
                                        custom_options=json.dumps({'geo_facility_id_device_id': 'fac-1'})))
        db.session.add(Input(unique_id='mir-1', device='MQTT_PAHO_JSON', name='미러-온습도01'))
        db.session.add(DeviceMeasurements(device_id='mir-1', channel=0, measurement='temperature', unit='C'))
        db.session.add(Output(unique_id='out-virt', output_type='virtual_on_off_single', name='가상 측창'))
        db.session.add(Input(unique_id='in-real', device='MQTT_PAHO_JSON', name='개도 상태'))
        db.session.commit()
        p = mock.patch('aot.utils.inputs.parse_input_information', return_value=INFO)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _plan(self):
        cat = DbCatalog(LazyApp())
        sites = cat._sites()
        return build_plan(sites, combine(TC.overrides(), {}), lambda uid: []), sites

    def test_catalog_binds_facilities_to_the_site_and_finds_the_coordinator(self):
        sites = DbCatalog(LazyApp())._sites()
        site = next(s for s in sites if s.site_id == 'site-1')
        self.assertEqual({f.facility_uuid: f.coordinator_uid for f in site.facilities},
                         {'fac-1': 'coord-1', 'fac-2': ''})

    def test_facility_row_alone_turns_it_on_regardless_of_site(self):
        plans, _ = self._plan()
        self.assertEqual(plans, [])                                        # 기본 끔 — 아무것도 켜지지 않는다
        TC.save('site', 'site-1', True, None, set_enabled=True)             # 대지만 켜면 시설은 안 켜진다
        plans, _ = self._plan()
        self.assertEqual([t.kind for p in plans for t in p.targets], [TargetKind.FIELD])
        TC.save('facility', 'fac-1', True, FULL, set_enabled=True)
        plans, _ = self._plan()
        kinds = sorted((t.kind.value, t.target_id) for p in plans for t in p.targets)
        self.assertEqual(kinds, [('facility', 'coord-1'), ('field', 'p1')])
        TC.save('site', 'site-1', False, None, set_enabled=True)            # 대지를 꺼도 켜진 시설은 그대로
        plans, _ = self._plan()
        self.assertEqual([(t.kind.value, t.facility) for p in plans for t in p.targets], [('facility', 'fac-1')])

    def test_facility_target_wiring_and_tag_fallback(self):
        TC.save('facility', 'fac-1', True, {'inputs': FULL['inputs'], 'controls': {
            'vent': dict(M('v1', 0, 'percent'), scale={'from_min': 0, 'from_max': 4})}}, set_enabled=True)
        TC.save('facility', 'fac-2', True, {'inputs': {'T_int': MIRROR('s9')}}, set_enabled=True)
        plans, _ = self._plan()
        (plan,) = plans
        by = {t.facility: t for t in plan.targets}
        a, b = by['fac-1'], by['fac-2']
        self.assertEqual((a.target_id, a.kind), ('coord-1', TargetKind.FACILITY))
        self.assertEqual(a.controls['vent'].scale, (0.0, 4.0))
        self.assertEqual(a.inputs['T_int'].provenance, Provenance.MEASURED)
        self.assertEqual(b.target_id, 'fac-2')                              # 코디네이터 없음 → 시설 uuid
        self.assertEqual(b.inputs['T_int'].provenance, Provenance.MIRROR)
        self.assertTrue(any('코디네이터)가 없어' in n for n in plan.notes))
        self.assertEqual(b.controls, {})                                    # 장치 상태 없음 → 부품이 not_twinnable

    def test_facility_only_site_is_not_a_field_site_for_the_settings_table(self):
        TC.save('plot', 'p1', None, {}, set_enabled=True)
        self.assertEqual([s.site_id for s in TC.catalog_sites()], ['site-1'])
        db.session.delete(GeoPlot.query.filter_by(unique_id='p1').first())
        db.session.commit()
        self.assertEqual(TC.catalog_sites(), [])                            # 시설만 있는 대지는 노지 목록에 안 낀다
        self.assertEqual([r['facility_id'] for r in TF.overview()], ['fac-1', 'fac-2'])

    def test_provenance_label_is_not_checked_on_save(self):
        self.assertEqual(TF.save('fac-1', None, {'controls': {'vent': M('out-virt', 0, 'percent')}}), [])
        self.assertEqual(TF.save('fac-1', True, {'inputs': {'T_int': M('mir-1')}}, set_enabled=True), [])   # 알림 없음

    def test_converted_channel_is_suggested_with_its_stored_unit(self):
        """미러 온도(원 단위 F, F→C 변환)는 °C 로 저장된다 — 읽는 쪽은 저장 단위로 찾으니 제안도 저장 단위여야 한다."""
        db.session.add(Conversion(unique_id='conv-fc', convert_unit_from='F', convert_unit_to='C',
                                  equation='(x-32)*5/9'))
        db.session.add(Input(unique_id='mir-f', device='MQTT_PAHO_JSON', name='미러-온습도03'))
        db.session.add(DeviceMeasurements(unique_id='dm-f', device_id='mir-f', channel=0, measurement='temperature',
                                          unit='F', conversion_id='conv-fc'))
        db.session.add(DeviceMeasurements(unique_id='dm-h', device_id='mir-f', channel=1, measurement='humidity',
                                          unit='percent'))
        db.session.commit()
        by = {(c['unique_id'], c['channel']): c for c in TC.channels(['mir-f'])}
        self.assertEqual(by[('mir-f', 0)]['unit'], 'C')
        self.assertTrue(TC._label(by[('mir-f', 0)]).endswith('(C)'))
        self.assertEqual(by[('mir-f', 1)]['unit'], 'percent')                      # 변환 없는 채널은 그대로
        row = TF._channel_of_measurement('dm-f')
        self.assertEqual((row['unit'], row['channel']), ('C', 0))
        # 변환 정의가 없어졌어도 원 단위로 되돌아간다(찾지 못한 변환으로 단위를 지어내지 않는다)
        dm = DeviceMeasurements.query.filter_by(unique_id='dm-f').one()
        self.assertEqual(TC.stored_unit(dm, {}), 'F')

    def test_unknown_facility_rejected(self):
        with self.assertRaises(TC.TwinConfigError):
            TF.save('nope', True, {}, set_enabled=True)

    def test_view_reports_verdict_tag_and_site(self):
        TC.save('facility', 'fac-1', True, {'inputs': FULL['inputs']}, set_enabled=True)
        v = TF.facility_view('fac-1', with_suggestions=False)
        self.assertEqual((v['verdict']['code'], v['enabled'], v['coordinator'], v['site_id']),
                         ('no_controls', True, 'coord-1', 'site-1'))
        self.assertIsNone(TF.facility_view('fac-2', with_suggestions=False)['coordinator'])


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.c = _APP['client']
        self.k = _APP['keys']
        for target, kw in (('aot.utils.twin_gate.twin_enabled', {'return_value': True}),):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        with _APP['app'].app_context():
            if GeoFacility.query.filter_by(unique_id='fac-api').first() is None:
                db.session.add(GeoFacility(unique_id='fac-api', shape_uuid='shp-api', geo_id='m1', name='API 시설'))
                db.session.add(Output(unique_id='out-virt', output_type='virtual_on_off_single', name='가상'))
                db.session.commit()
        for name in ('catalog',):
            p = mock.patch('aot.utils.twin_facility_config._catalog', return_value=[])
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch('aot.utils.twin_facility_config.suggestions', return_value={})
        p.start()
        self.addCleanup(p.stop)

    def _h(self, who='admin'):
        return {'X-API-KEY': self.k[who], 'Accept': H}

    def test_put_then_read_back_and_overview(self):
        r = self.c.put('/api/twin/config/facility/fac-api', headers=self._h(),
                       json={'enabled': False, 'config': {'inputs': {'T_int': MIRROR('x')}}})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        j = r.get_json()
        self.assertFalse(j['enabled'])
        self.assertEqual(j['verdict']['code'], 'missing_inputs')
        self.assertEqual(j['notices'], [])
        g = self.c.get('/api/twin/config/facility/fac-api', headers=self._h())
        self.assertEqual(g.get_json()['config']['inputs']['T_int'], MIRROR('x'))
        ov = self.c.get('/api/twin/config/overview', headers=self._h()).get_json()
        self.assertIn('facilities', ov)

    def test_422_for_unknown_key_and_unknown_facility(self):
        h = self._h()
        r = self.c.put('/api/twin/config/facility/fac-api', headers=h, json={'config': {'inputs': {'rain': RAIN}}})
        self.assertEqual(r.status_code, 422)
        r = self.c.put('/api/twin/config/facility/nope', headers=h, json={'enabled': True})
        self.assertEqual(r.status_code, 422)

    def test_viewer_cannot_write_and_flag_off_is_404(self):
        self.assertEqual(self.c.put('/api/twin/config/facility/fac-api', headers=self._h('viewer'),
                                    json={'enabled': True}).status_code, 403)
        with mock.patch('aot.utils.twin_gate.twin_enabled', return_value=False), \
                mock.patch.dict(os.environ, {'AOT_TWIN_ENABLED': ''}):
            self.assertEqual(self.c.get('/api/twin/config/facility/fac-api', headers=self._h()).status_code, 404)


if __name__ == '__main__':
    unittest.main()
