# coding=utf-8
"""장치 → 효과 채널 자동 연결 서버 글루 — 가짜 시설 하나(DB)로 읽기·상속·덮어쓰기·상태 출처를 본다."""
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements, GeoFacility, Output
# 앱 컨텍스트 밖에서 먼저 import — 번역 문자열을 평가하는 모듈이 딸려 온다.
from aot.aot_flask.geo import device_binding as _device_binding  # noqa: F401
from aot.aot_flask.geo import facility_integration as FI
from aot.functions.utils.twin_effects import links as L
from aot.utils import twin_effects_link as EL
from aot.utils.twin_config import TwinConfigError

FAC = 'fac-link'
HEAT, FAN, WIN, MYSTERY, LAMP = 'o-heat', 'o-fan', 'o-win', 'o-mystery', 'o-lamp'


def _fit(fid, kind, dev, **extra):
    d = {'id': fid, 'kind': kind, 'actuator_id': dev}
    d.update(extra)
    return d


class _DB(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()
        for uid in (HEAT, FAN, WIN, MYSTERY, LAMP):
            Output(unique_id=uid, name='출력-' + uid, output_type='virtual_on_off_single').save()
        GeoFacility(unique_id=FAC, shape_uuid='s-' + FAC, geo_id='map-1', name='연결 시설', actuators=[
            {'id': 'A1', 'kind': 'heater', 'device_uuid': HEAT, 'specs': {}}],
            fittings=[_fit('F1', 'fan', FAN, fan_role='exhaust_fan', airflow_cmh=48000),
                      _fit('F2', 'window', WIN),
                      _fit('F3', 'mystery_box', MYSTERY),
                      _fit('F4', 'lighting', LAMP)]).save()
        # 출력의 측정 채널 선언: 난방·팬 = 가동 이력(s), 창 = 명령 기록(percent)
        for dev, unit, meas in ((HEAT, 's', 'duration_time'), (FAN, 's', 'duration_time'),
                                (WIN, 'percent', 'duty_cycle'), (WIN, 's', 'duration_time')):
            DeviceMeasurements(device_id=dev, device_type='output', channel=0, unit=unit, measurement=meas).save()
        FI.invalidate_facility_integration_cache()

    def tearDown(self):
        FI.invalidate_facility_integration_cache()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


class TestFacilityRows(_DB):
    def rows(self, cfg=None):
        v = EL.facility_effects(FAC, cfg)
        return v, {r['id']: r for r in v['rows']}

    def test_장치_종류는_위치로_읽고_채널이_자동으로_정해진다(self):
        v, r = self.rows()
        self.assertEqual(v['mode'], 'auto')
        self.assertEqual((r[HEAT]['kind'], r[HEAT]['channel']), ('heater', 'heat'))
        self.assertEqual((r[FAN]['kind'], r[FAN]['channel']), ('exhaust_fan', 'vent'))
        self.assertEqual(r[WIN]['channel'], 'vent')
        self.assertEqual(r[LAMP]['status'], 'unmodeled')            # 보광 — 효과 미반영을 명시
        self.assertIn('par', r[LAMP]['unmodeled_effects'])

    def test_정격과_출처_읽기(self):
        _v, r = self.rows()
        fan = {x['key']: x for x in r[FAN]['ratings']}
        self.assertEqual((fan['rated_m3h']['value'], fan['rated_m3h']['source']), (48000.0, 'device'))
        heat = {x['key']: x for x in r[HEAT]['ratings']}
        self.assertEqual(heat['rated_kW_thermal']['source'], 'unknown')       # 열 정격은 데이터 모델에 없다 — 모름으로 남긴다

    def test_상태_출처_우선순위와_추정_표시(self):
        _v, r = self.rows()
        self.assertEqual(r[HEAT]['basis'], 'duty_log')              # 켜짐/꺼짐 장치 → 가동 이력
        self.assertEqual(r[FAN]['basis'], 'duty_log')
        self.assertEqual(r[WIN]['basis'], 'command')                # 개도형은 가동 이력이 위치가 아니라 명령 기록
        self.assertTrue(r[WIN]['estimated'] and not r[HEAT]['estimated'])
        self.assertEqual(r[LAMP]['basis'], 'none')

    def test_종류를_모르는_설비는_역할을_묻고_정하면_장치가_된다(self):
        _v, r = self.rows()
        self.assertTrue(r[MYSTERY]['needs_kind'])
        self.assertEqual(r[MYSTERY]['status'], 'unknown')
        _v, r = self.rows({'effects': {'devices': {MYSTERY: {'kind': 'cooler'}}}})
        self.assertEqual((r[MYSTERY]['channel'], r[MYSTERY]['kind_from']), ('cool', 'override'))

    def test_읽을_수_없는_시설은_오류로_알린다(self):
        with mock.patch.object(FI, 'get_facility_integration', lambda *a, **k: (None, 'nope')):
            v = EL.facility_effects(FAC, {})
        self.assertEqual(v['error'], 'integration_unreadable')
        self.assertEqual(v['rows'], [])


class TestInherit(_DB):
    def test_손배선이_없으면_위치로_읽은_장치로_채운다(self):
        cfg = EL.inherit_facility(FAC, {'inputs': {'T_int': {'unique_id': 'x', 'unit': 'C', 'channel': 0}}})
        self.assertEqual(cfg['inputs']['T_int']['unique_id'], 'x')                # 입력은 그대로
        self.assertEqual(cfg['controls'][HEAT], {'unique_id': HEAT, 'unit': 'duty_log', 'channel': 0,
                                                'provenance': 'unknown'})
        self.assertEqual(cfg['controls'][WIN]['unit'], 'percent')
        self.assertNotIn(LAMP, cfg['controls'])                                    # 읽을 계열 없음 — 지어내지 않는다
        eff = {d['id']: d for d in cfg['options']['effects']['devices']}
        self.assertEqual(eff[HEAT]['basis'], 'duty_log')
        self.assertEqual(eff[WIN]['basis'], 'command')
        self.assertEqual(eff[FAN]['ratings']['rated_m3h'], 48000.0)
        self.assertIn(LAMP, eff)                                                   # 미반영 장치도 목록에는 남는다(보고용)

    def test_손배선이_있으면_그대로_둔다_덮어쓰기(self):
        manual = {'controls': {'heat': {'unique_id': 'z', 'unit': 'percent', 'channel': 3}}}
        self.assertEqual(EL.inherit_facility(FAC, manual), manual)

    def test_뺀_장치는_연결에서_빠진다(self):
        cfg = EL.inherit_facility(FAC, {'effects': {'devices': {HEAT: {'exclude': True}}}})
        self.assertNotIn(HEAT, cfg['controls'])
        self.assertNotIn(HEAT, {d['id'] for d in cfg['options']['effects']['devices']})

    def test_개발용_options_effects_를_손으로_적었으면_덮지_않는다(self):
        mine = {'devices': [{'id': HEAT, 'kind': 'heater', 'ratings': {}}]}
        cfg = EL.inherit_facility(FAC, {'options': {'effects': mine}})
        self.assertEqual(cfg['options']['effects'], mine)

    def test_읽기_실패는_설정을_그대로_돌려준다(self):
        with mock.patch.object(FI, 'get_facility_integration', lambda *a, **k: (None, 'nope')):
            self.assertEqual(EL.inherit_facility(FAC, {'options': {'T_high': 30.0}}), {'options': {'T_high': 30.0}})


class TestFieldRoster(unittest.TestCase):
    """노지 출력 명단(`options.effects`) — 머리말 effects_* 와 시나리오 effects[] 의 재료. 저장하지 않고 상속으로만 채운다."""

    OUTS = {'v1': {'name': '밸브1', 'output_type': 'x'}, 'v2': {'name': '밸브2', 'output_type': 'x'},
            'v3': {'name': '밸브3', 'output_type': 'x'}}

    def roster(self, cfg):
        with mock.patch.object(EL, '_field_outputs', lambda site_id: dict(self.OUTS)):
            return EL.field_effects_options('site-A', cfg)

    def test_역할을_고른_것만_종류를_갖고_나머지는_모름이다(self):
        r = self.roster({'effects': {'devices': {'v1': {'kind': 'irrigation_drip'}}}})
        self.assertEqual(r, {'devices': [{'id': 'v1', 'kind': 'irrigation_drip'}, {'id': 'v2', 'kind': None},
                                         {'id': 'v3', 'kind': None}]})

    def test_뺀_장치는_명단에서_빠진다(self):
        r = self.roster({'effects': {'devices': {'v2': {'exclude': True}}}})
        self.assertEqual([d['id'] for d in r['devices']], ['v1', 'v3'])

    def test_출력이_없으면_상속하지_않는다(self):
        with mock.patch.object(EL, '_field_outputs', lambda site_id: {}):
            self.assertIsNone(EL.field_effects_options('site-A', {}))


class TestValidate(unittest.TestCase):
    def test_검사(self):
        self.assertEqual(EL.validate_overrides({'devices': {'a': {'kind': 'heater'}}}),
                         {'devices': {'a': {'kind': 'heater'}}})
        self.assertEqual(EL.validate_overrides(None), {})
        with self.assertRaises(TwinConfigError):
            EL.validate_overrides({'devices': {'a': {'kind': '없는종류'}}})
        with self.assertRaises(TwinConfigError):
            EL.validate_overrides({'devices': {'a': {'kind': 'heater'}}}, 'field')   # 노지는 역할만


class TestSite(_DB):
    def _site(self):
        from types import SimpleNamespace
        return SimpleNamespace(site_id='site-1', facilities=[SimpleNamespace(facility_uuid=FAC, name='연결 시설')])

    def test_시설_묶음과_노지_묶음(self):
        for uid in ('v1', 'v2'):
            Output(unique_id=uid, name='밸브-' + uid, output_type='virtual_on_off_single').save()
        DeviceMeasurements(device_id='v2', device_type='output', channel=0, unit='s', measurement='duration_time').save()
        outs = {'v1': {'name': '밸브-v1', 'output_type': 'x'}, 'v2': {'name': '밸브-v2', 'output_type': 'x'},
                HEAT: {'name': '중복', 'output_type': 'x'}}                       # 시설 장치는 노지 묶음에서 빠진다
        cfg = {'effects': {'devices': {'v2': {'kind': 'irrigation_drip'}}}}
        with mock.patch.object(EL, '_field_outputs', lambda sid: outs):
            v = EL.site_effects(self._site(), cfg)
        g = {x['kind']: x for x in v['groups']}
        self.assertEqual([r['id'] for r in g['field']['rows']], ['v1', 'v2'])
        f = {r['id']: r for r in g['field']['rows']}
        self.assertTrue(f['v1']['needs_kind'] and f['v1']['channel'] is None)      # 범용 출력 — 역할을 묻는다
        self.assertEqual((f['v2']['channel'], f['v2']['basis']), ('irrigation_mm', 'duty_log'))
        self.assertFalse(f['v2']['applied'])                                        # 노지 연결은 다음 단계 — 알린다
        self.assertEqual(g['field']['kinds'], L.selectable_kinds('field'))
        self.assertNotIn(HEAT, [r['id'] for r in g['field']['rows']])
        self.assertEqual(v['summary']['total'], g['facility']['summary']['total'] + g['field']['summary']['total'])

    def test_장치가_없는_시설은_묶음을_만들지_않는다(self):
        from types import SimpleNamespace
        GeoFacility(unique_id='fac-empty', shape_uuid='s-empty', geo_id='map-1', name='창고', actuators=[], fittings=[]).save()
        FI.invalidate_facility_integration_cache()
        site = SimpleNamespace(site_id='site-1', facilities=[
            SimpleNamespace(facility_uuid=FAC, name='연결 시설'), SimpleNamespace(facility_uuid='fac-empty', name='창고')])
        with mock.patch.object(EL, '_field_outputs', lambda sid: {}):
            v = EL.site_effects(site, {})
        self.assertEqual([g['id'] for g in v['groups']], [FAC])

    def test_노지_출력이_없으면_시설_묶음만(self):
        with mock.patch.object(EL, '_field_outputs', lambda sid: {}):
            v = EL.site_effects(self._site(), {})
        self.assertEqual([g['kind'] for g in v['groups']], ['facility'])


class TestSaveRules(unittest.TestCase):
    def test_시설_설정_검사는_effects_를_받는다(self):
        from aot.utils import twin_facility_config as TF
        out = TF.validate_config({'effects': {'devices': {'a': {'exclude': True}}}})
        self.assertEqual(out['effects'], {'devices': {'a': {'exclude': True}}})
        with self.assertRaises(TwinConfigError):
            TF.validate_config({'effects': {'devices': {'a': {'kind': 'irrigation_drip'}}}})     # 시설은 시설 종류만

    def test_대지_설정_검사는_노지_역할만(self):
        from aot.utils import twin_config as TC
        out = TC.validate_config({'effects': {'devices': {'v': {'kind': 'irrigation_drip'}}}}, 'site')
        self.assertEqual(out['effects']['devices']['v']['kind'], 'irrigation_drip')
        with self.assertRaises(TwinConfigError):
            TC.validate_config({'effects': {'devices': {'v': {'kind': 'heater'}}}}, 'site')
        with self.assertRaises(TwinConfigError):
            TC.validate_config({'effects': {'devices': {'v': {'exclude': True}}}}, 'plot')       # 구획은 대지에서 정한다


if __name__ == '__main__':
    unittest.main()
