# coding=utf-8
"""팬 정격 풍량이 목록형 사양으로만 제어기에 닿던 문제.

`facility_integration` 은 목록형 액추에이터의 `specs.airflow_cmh` 만 `rated_m3h` 로
옮겼다. 팬 **피팅**(`kind='fan'`, `fan_role`)으로 묶은 흡기·배기팬은 종류만 정해지고
풍량은 옮겨지지 않아, 로더가 종류 기본값 3000 m³/h 로 채웠다. 48,000 m³/h 팬이
16분의 1로 계산되면 환기 능력이 모자란 것으로 보여 창과 분무가 그 몫을 떠안는다.

풍량이 적힌 자리는 둘이다 — 목록형 `specs.airflow_cmh`(디자이너 현행), 팬 피팅의
`airflow_cmh`(또는 `specs.airflow_cmh`). 둘 다 읽고, 겹치면 목록형이 이긴다.
"""
import logging
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoFacility, Output

# 앱 컨텍스트 밖에서 먼저 import — 번역 문자열을 평가하는 모듈이 딸려 온다.
from aot.aot_flask.geo import device_binding as _device_binding  # noqa: F401
from aot.aot_flask.geo import facility_integration as FI
from aot.functions.custom_functions.env_coordinator_impl import (
    _profile_loader_mixin as _loader)
from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin \
    import ProfileLoaderMixin

FAC = 'fac-fans'
INTAKE = 'out-intake'
EXHAUST = 'out-exhaust'
CIRC = 'out-circ'


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _fan(fid, role, dev, **extra):
    d = {'id': fid, 'kind': 'fan', 'fan_role': role, 'actuator_id': dev}
    d.update(extra)
    return d


class _DB(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        for uid in (INTAKE, EXHAUST, CIRC):
            Output(unique_id=uid, name=uid, output_type='virtual_on_off_single').save()

    def tearDown(self):
        FI.invalidate_facility_integration_cache()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _resolved(self, fittings=None, actuators=None):
        GeoFacility(unique_id=FAC, shape_uuid='s-' + FAC, geo_id='map-1', name='팬 시설',
                    fittings=fittings or [], actuators=actuators if actuators is not None else []
                    ).save()
        integ, err = FI.get_facility_integration(FAC, bypass_cache=True)
        self.assertIsNone(err)
        return {a['output_uuid']: a for a in integ['actuators_resolved']}


class TestFittingAirflowReachesIntegration(_DB):

    def test_팬_피팅만_있어도_풍량이_넘어간다(self):
        r = self._resolved(fittings=[
            _fan('F1', 'intake_fan', INTAKE, airflow_cmh=48000),
            _fan('F2', 'exhaust_fan', EXHAUST, airflow_cmh=48000)])
        self.assertEqual(r[INTAKE]['kind'], 'intake_fan')
        self.assertEqual(r[INTAKE]['rated_m3h'], 48000.0)
        self.assertEqual(r[EXHAUST]['rated_m3h'], 48000.0)

    def test_피팅의_specs_안_풍량도_읽는다(self):
        r = self._resolved(fittings=[
            _fan('F1', 'exhaust_fan', EXHAUST, specs={'airflow_cmh': '12000'})])
        self.assertEqual(r[EXHAUST]['rated_m3h'], 12000.0)

    def test_풍량이_없으면_키를_넣지_않는다(self):
        """모르는 값을 지어내지 않는다 — 로더가 종류 기본값으로 떨어진다."""
        r = self._resolved(fittings=[_fan('F1', 'exhaust_fan', EXHAUST)])
        self.assertNotIn('rated_m3h', r[EXHAUST])

    def test_읽을_수_없는_값은_무시한다(self):
        r = self._resolved(fittings=[
            _fan('F1', 'exhaust_fan', EXHAUST, airflow_cmh='많이'),
            _fan('F2', 'intake_fan', INTAKE, airflow_cmh=-5)])
        self.assertNotIn('rated_m3h', r[EXHAUST])
        self.assertNotIn('rated_m3h', r[INTAKE])

    def test_목록형_사양이_있으면_그쪽이_이긴다(self):
        r = self._resolved(
            fittings=[_fan('F1', 'exhaust_fan', EXHAUST, airflow_cmh=1000)],
            actuators=[{'id': 'A1', 'kind': 'exhaust_fan', 'device_uuid': EXHAUST,
                        'specs': {'airflow_cmh': 48000}}])
        self.assertEqual(r[EXHAUST]['rated_m3h'], 48000.0)

    def test_목록형에_풍량이_비어_있으면_피팅_값을_쓴다(self):
        r = self._resolved(
            fittings=[_fan('F1', 'exhaust_fan', EXHAUST, airflow_cmh=30000)],
            actuators=[{'id': 'A1', 'kind': 'exhaust_fan', 'device_uuid': EXHAUST,
                        'specs': {}}])
        self.assertEqual(r[EXHAUST]['rated_m3h'], 30000.0)

    def test_한_장치에_팬_피팅이_여럿이면_합한다(self):
        r = self._resolved(fittings=[
            _fan('F1', 'exhaust_fan', EXHAUST, airflow_cmh=20000),
            _fan('F2', 'exhaust_fan', EXHAUST, airflow_cmh=10000)])
        self.assertEqual(r[EXHAUST]['rated_m3h'], 30000.0)

    def test_옛_dict_슬롯_장치도_팬_피팅_풍량을_받는다(self):
        r = self._resolved(
            fittings=[_fan('F1', 'exhaust_fan', EXHAUST, airflow_cmh=24000)],
            actuators={'exhaust_fan': EXHAUST})
        self.assertEqual(r[EXHAUST]['rated_m3h'], 24000.0)

    def test_팬이_아닌_피팅의_airflow_는_무시한다(self):
        r = self._resolved(fittings=[
            {'id': 'W1', 'kind': 'side_window', 'actuator_id': CIRC, 'airflow_cmh': 999}])
        self.assertNotIn('rated_m3h', r[CIRC])


class TestReachesProfile(_DB):
    """로더까지 — 프로필의 capacity_meta 에 48,000 이 실린다."""

    def test_팬_피팅_풍량이_프로필까지_닿는다(self):
        GeoFacility(unique_id=FAC, shape_uuid='s-' + FAC, geo_id='map-1', name='팬 시설',
                    fittings=[_fan('F1', 'intake_fan', INTAKE, airflow_cmh=48000),
                              _fan('F2', 'exhaust_fan', EXHAUST, airflow_cmh=48000),
                              _fan('F3', 'exhaust_fan', CIRC)],   # 풍량 미설정
                    actuators=[]).save()

        class Stub(ProfileLoaderMixin):
            def _attach_electric_kw(self): pass
            def _warn_shared_actuators(self, f): pass
            def _apply_pending_commissioning_anchors(self, f): pass

        s = Stub()
        s.logger = logging.getLogger('test_fan_airflow')
        s.unique_id = 'coord-1'
        s.geo_facility_id_device_id = FAC
        s.disabled_actuators = ''
        s.bay_scope = ''

        def _no_rows(model, *a, **k):
            q = mock.MagicMock()
            q.all.return_value = []
            q.filter.return_value = q
            return q

        with mock.patch.object(_loader, 'db_retrieve_table_daemon', _no_rows):
            s._reload_profiles()
        rated = {p.actuator_id: p.capacity_meta.get('rated_m3h') for p in s._profiles}
        self.assertEqual(rated[INTAKE], 48000.0)
        self.assertEqual(rated[EXHAUST], 48000.0)
        self.assertEqual(rated[CIRC], 3000.0)    # 기본값 — 적힌 값이 없을 때만


if __name__ == '__main__':
    unittest.main()
