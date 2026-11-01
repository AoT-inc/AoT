# coding=utf-8
"""actuator_paired 자동 발견이 시설과 무관한 출력까지 데려오던 문제.

김제 스냅숏(2026-10)에서 시설 코디네이터가 `TEST 측창1~4`·`TEST 천창(전용쌍)`·
`천창1` 6개를 자기 액추에이터로 편입했다. 이 출력들은 어느 시설의 슬롯에도
현재 바인딩이 없고(전부 끝났거나 처음부터 없다) 지도에 마커도 없다. 앞선
두 판정(`78b56f6ce` 형제 시설 소유 · `7401dace9` 다른 지도의 마커)은 둘 다 "남의
것임이 확인된 장치"만 걸러서 이런 **무관한 장치** 는 그대로 통과했다.
시설에 없는 장치라 환경이 반응하지 않는데도 매 사이클 개도 명령이 나갔다.

규칙: 시설을 정한 코디네이터는 내 시설 슬롯에 바인딩이 있거나 내 지도에 마커가
있는 출력만 데려온다. 시설이 없는 코디네이터(수동 설치)는 예전 그대로다.
"""
import logging
import types
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoBinding, GeoFacility, GeoShape, Output
from aot.utils.time_utils import utc_now

# 앱 컨텍스트 밖에서 먼저 import — 번역 문자열을 평가하는 모듈이 딸려 온다.
from aot.aot_flask.geo import device_binding as _device_binding  # noqa: F401
from aot.aot_flask.geo import facility_integration as _facility_integration  # noqa: F401
from aot.functions.custom_functions.env_coordinator_impl import (
    _profile_loader_mixin as _loader)
from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin \
    import ProfileLoaderMixin, _paired_outside_facility_scope

FAC = 'fac-mine'
FAC_OTHER = 'fac-other'
MAP = 'map-mine'
MAP_OTHER = 'map-other'

OWN = 'out-own-fitting'            # 내 시설 fitting 에 바인딩
MARK_MINE = 'out-marker-my-map'    # 바인딩 없이 내 지도에만 마커
UNOWNED = 'out-unowned'            # 바인딩도 마커도 없음 (TEST 측창)
ENDED = 'out-ended'                # 바인딩이 모두 끝남 (천창1)
OTHER_FAC = 'out-other-facility'   # 다른 시설 슬롯에 현재 바인딩
OTHER_MAP = 'out-other-map'        # 다른 지도에만 마커
BOTH = 'out-other-fac-my-map'      # 다른 시설 바인딩 + 내 지도 마커
ALL = [OWN, MARK_MINE, UNOWNED, ENDED, OTHER_FAC, OTHER_MAP, BOTH]


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _bind(kind, spatial_id, dev, ended=False, role='actuator'):
    GeoBinding(spatial_kind=kind, spatial_id=spatial_id, role=role,
               device_kind='output', device_id=dev, channel_id='0',
               valid_from=utc_now(),
               valid_to=utc_now() if ended else None,
               ended_reason='unbound' if ended else None).save()


def _marker(uid, geo, dev):
    GeoShape(unique_id=uid, geo_id=geo, type='aot_device', device_id=dev,
             feature={'type': 'Feature', 'properties': {},
                      'geometry': {'type': 'Point', 'coordinates': [0, 0]}}).save()
    _bind('shape', uid, dev, role='marker')


class _DB(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        for uid in ALL:
            Output(unique_id=uid, name=uid, output_type='actuator_paired').save()
        GeoFacility(unique_id=FAC, shape_uuid='s-mine', geo_id=MAP, name='내 시설',
                    fittings=[], actuators=[]).save()
        GeoFacility(unique_id=FAC_OTHER, shape_uuid='s-other', geo_id=MAP, name='남 시설',
                    fittings=[], actuators=[]).save()
        _bind('fitting', FAC + ':F1', OWN)
        _marker('m-mine', MAP, MARK_MINE)
        _bind('fitting', FAC + ':F0', ENDED, ended=True)
        _bind('fitting', FAC_OTHER + ':F9', OTHER_FAC)
        _marker('m-other', MAP_OTHER, OTHER_MAP)
        _bind('fitting', FAC_OTHER + ':F8', BOTH)
        _marker('m-both', MAP, BOTH)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


class TestScopeRule(_DB):

    def _outside(self, facility=FAC, geo=MAP):
        return _paired_outside_facility_scope(ALL, facility, geo)

    def test_무관한_출력은_뺀다(self):
        """바인딩도 마커도 없는 것, 바인딩이 모두 끝난 것."""
        out = self._outside()
        self.assertIn(UNOWNED, out)
        self.assertIn(ENDED, out)

    def test_다른_시설_슬롯에_매인_출력은_내_지도_마커가_있어도_뺀다(self):
        out = self._outside()
        self.assertIn(OTHER_FAC, out)
        self.assertIn(BOTH, out)

    def test_다른_지도_마커만_있는_출력은_뺀다(self):
        self.assertIn(OTHER_MAP, self._outside())

    def test_내_시설_슬롯과_내_지도_마커는_남긴다(self):
        out = self._outside()
        self.assertNotIn(OWN, out)
        self.assertNotIn(MARK_MINE, out)

    def test_정확히_이_집합이다(self):
        self.assertEqual(self._outside(),
                         {UNOWNED, ENDED, OTHER_FAC, OTHER_MAP, BOTH})

    def test_지도가_없는_시설은_마커로_구제하지_않는다(self):
        out = self._outside(geo=None)
        self.assertIn(MARK_MINE, out)
        self.assertNotIn(OWN, out)

    def test_시설이_없으면_아무것도_빼지_않는다(self):
        """수동 설치(시설 미지정)는 예전 그대로 — 이 판정을 받지 않는다."""
        self.assertEqual(_paired_outside_facility_scope(ALL, '', None), set())
        self.assertEqual(_paired_outside_facility_scope([], FAC, MAP), set())


def _stub(facility_uuid, disabled=''):
    class Stub(ProfileLoaderMixin):
        def _attach_electric_kw(self):
            pass

        def _warn_shared_actuators(self, facility_uuid):
            pass

        def _apply_pending_commissioning_anchors(self, facility_uuid):
            pass

    s = Stub()
    s.logger = logging.getLogger('test_paired_discovery_scope')
    s.unique_id = 'coord-1'
    s.geo_facility_id_device_id = facility_uuid
    s.disabled_actuators = disabled
    s.bay_scope = ''
    return s


def _no_rows(model, *a, **k):
    q = mock.MagicMock()
    q.all.return_value = []
    q.filter.return_value = q
    return q


class TestReloadProfilesDiscovery(_DB):
    """`_reload_profiles` 전체를 통과시켜 실제로 등록되는 집합을 본다."""

    def _loaded(self, facility_uuid, disabled=''):
        s = _stub(facility_uuid, disabled)
        with mock.patch.object(_loader, 'db_retrieve_table_daemon', _no_rows), \
             mock.patch('aot.aot_flask.geo.facility_integration.'
                        'get_facility_integration', return_value=(None, 'x')):
            s._reload_profiles()
        return {p.actuator_id for p in s._profiles}

    def test_시설_코디네이터는_무관한_출력을_편입하지_않는다(self):
        # 시설 통합 적재를 막아 두었으므로 내 시설 슬롯의 OWN 도 발견 경로로 온다
        # (실제로는 시설 경로가 먼저 등록한다). 핵심은 무관한 5개가 없다는 것.
        got = self._loaded(FAC)
        self.assertEqual(got, {OWN, MARK_MINE})

    def test_시설이_없는_코디네이터는_예전_그대로다(self):
        """마커가 다른 지도에 있는 것만 빠지고(7401dace9) 나머지는 전부 들어온다."""
        got = self._loaded('')
        self.assertTrue({UNOWNED, ENDED, OWN, MARK_MINE} <= got)


class TestDisabledActuatorsApplyToDiscovery(_DB):
    """`disabled_actuators` 가 자동 발견 경로에도 걸리는가.

    시설 경로(섹션 1)만 그 목록을 보고, 발견 경로(섹션 2)는 안 봤다. 화면에서 껐는데
    같은 장치를 발견 경로가 다시 등록해 계속 움직였다 — 조용한 실패다.
    """

    def _run(self, facility_uuid, disabled):
        s = _stub(facility_uuid, disabled)
        with mock.patch.object(_loader, 'db_retrieve_table_daemon', _no_rows), \
             mock.patch('aot.aot_flask.geo.facility_integration.'
                        'get_facility_integration', return_value=(None, 'x')):
            s._reload_profiles()
        return s, {p.actuator_id for p in s._profiles}

    def test_발견된_장치도_끄면_빠진다(self):
        s, got = self._run(FAC, MARK_MINE)
        self.assertEqual(got, {OWN})
        self.assertEqual([e['name'] for e in s._excluded_actuators], [MARK_MINE])
        self.assertEqual(s._excluded_actuators[0]['reason'], 'disabled')

    def test_시설이_없는_코디네이터에도_걸린다(self):
        s, got = self._run('', '%s, %s' % (UNOWNED, OWN))
        self.assertNotIn(UNOWNED, got)
        self.assertNotIn(OWN, got)
        self.assertIn(MARK_MINE, got)
        self.assertEqual({e['name'] for e in s._excluded_actuators}, {UNOWNED, OWN})

    def test_끄지_않으면_그대로다(self):
        s, got = self._run(FAC, '')
        self.assertEqual(got, {OWN, MARK_MINE})
        self.assertEqual(s._excluded_actuators, [])

    def test_다시_켜면_제외_목록도_비워진다(self):
        """사이클 사이에 옛 목록이 남지 않는다."""
        s, _ = self._run('', UNOWNED)
        self.assertTrue(s._excluded_actuators)
        with mock.patch.object(_loader, 'db_retrieve_table_daemon', _no_rows):
            s.disabled_actuators = ''
            s._reload_profiles()
        self.assertEqual(s._excluded_actuators, [])
        self.assertIn(UNOWNED, {p.actuator_id for p in s._profiles})


if __name__ == '__main__':
    unittest.main()
