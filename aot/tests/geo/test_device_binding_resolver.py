# coding=utf-8
"""device_binding 리졸버 — 우선순위·폴백, 그리고 인메모리 격리.

핵심은 마지막 테스트다: **읽기 리졸버는 ORM 객체를 고치지 않는다.**

`FacilityManager._to_dict()` 의 `'fittings': f.fittings or []` 는 ORM 이 들고
있는 JSON 객체를 참조로 넘긴다. 리졸버가 그 안의 dict 를 제자리에서 고치면
같은 세션의 뒤이은 독자(`check_geo_integrity` 의 dangling-fitting 등)가
저장값 대신 해석값을 보게 되고, "저장된 것"과 "해석된 것"의 구분이 사라진다.

주의 — 여기서 검증하는 것은 **인메모리 격리**이지 DB 되써넣기가 아니다.
`db.Column(JSON)` 은 Mutable 래퍼가 없어 SQLAlchemy 가 제자리 변경을 추적
하지 않으므로, 제자리 수정만으로 DB 가 바뀌지는 않는다(2026-08-08 통제
실험으로 확인). 구현 중 되써넣기로 오진했던 적이 있는데, 그 근거였던 실험
자체가 틀렸다 — 얕은 복사 `list(f.fittings)` 로 내부 dict 을 공유한 채 고치면
ORM 이 '변경 없음'으로 보아 오염이 저장되지 않는다. 그래서 "폴백이 레거시
값을 안 돌려준다"로 보였던 것이고, 실제로는 레거시 값이 처음부터 바뀐 적이
없었다. 같은 함정을 다시 밟지 않도록 아래 헬퍼는 깊은 복사로 오염시킨다.
"""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoBinding, GeoFacility
from aot.aot_flask.geo import device_binding as B
from aot.utils.time_utils import utc_now


FAC = 'fac-uuid-1'
FIT = 'Fmp0001'
BOUND_DEV = 'dev-bound-0001'
LEGACY_DEV = 'dev-legacy-9999'


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


class TestFacilityResolution(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        B.reset_fallback_log()

        self.fac = GeoFacility(
            unique_id=FAC, shape_uuid='shape-1', geo_id='map-1', name='검증시설',
            fittings=[{'id': FIT, 'kind': 'window', 'actuator_id': LEGACY_DEV},
                      {'id': 'Fmp0002', 'kind': 'fan', 'actuator_id': None}])
        self.fac.save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _bind(self, device_id=BOUND_DEV):
        GeoBinding(spatial_kind='fitting', spatial_id='%s:%s' % (FAC, FIT),
                   role='actuator', device_kind='output', device_id=device_id,
                   channel_id='0', valid_from=utc_now()).save()

    def _payload(self):
        """_to_dict 와 같은 방식으로 ORM 객체를 참조로 담은 payload."""
        return {'fittings': self.fac.fittings, 'actuators': self.fac.actuators}

    # -- 우선순위 ---------------------------------------------------------
    def test_binding_wins_over_stored_json(self):
        self._bind()
        out = B.resolve_facility_payload(FAC, self._payload())
        got = [f for f in out['fittings'] if f['id'] == FIT][0]['actuator_id']
        self.assertEqual(got, BOUND_DEV)

    def test_falls_back_to_stored_json_when_unbound(self):
        out = B.resolve_facility_payload(FAC, self._payload())
        got = [f for f in out['fittings'] if f['id'] == FIT][0]['actuator_id']
        self.assertEqual(got, LEGACY_DEV)

    def test_ended_binding_is_not_current(self):
        self._bind()
        b = GeoBinding.query.first()
        b.valid_to = utc_now()
        b.ended_reason = 'unbound'
        db.session.commit()

        out = B.resolve_facility_payload(FAC, self._payload())
        got = [f for f in out['fittings'] if f['id'] == FIT][0]['actuator_id']
        self.assertEqual(got, LEGACY_DEV,
                         '종료된 바인딩은 현재가 아니므로 레거시로 폴백해야 한다')

    # -- 인메모리 격리 (핵심) ---------------------------------------------
    def test_resolution_does_not_mutate_the_orm_object(self):
        """리졸버가 ORM 이 들고 있는 JSON 을 고치면 안 된다.

        고치면 같은 세션의 뒤이은 독자가 저장값 대신 해석값을 보게 되고,
        무엇이 저장된 값인지 아무도 말할 수 없게 된다. 특히
        `check_geo_integrity` 의 dangling-fitting 은 저장값을 봐야 한다 —
        해석값을 보면 죽은 참조가 살아 있는 것으로 보인다.
        """
        self._bind()

        payload = self._payload()
        B.resolve_facility_payload(FAC, payload)

        # 반환된 payload 는 바인딩 값이지만,
        self.assertEqual(
            [f for f in payload['fittings'] if f['id'] == FIT][0]['actuator_id'],
            BOUND_DEV)

        # ORM 객체가 들고 있는 값은 저장값 그대로여야 한다.
        stored = [f for f in self.fac.fittings
                  if f['id'] == FIT][0]['actuator_id']
        self.assertEqual(stored, LEGACY_DEV,
                         '리졸버가 ORM 의 JSON 을 제자리에서 고쳤다 — '
                         '읽기가 인메모리 상태를 오염시킨 회귀')

    def test_stored_value_survives_a_later_commit(self):
        """해석 후 무관한 커밋이 일어나도 저장값은 그대로여야 한다.

        (현재 스키마에서 제자리 수정이 DB 까지 가지는 않지만, Mutable 래퍼가
        추가되는 날 이 테스트가 경보가 된다.)
        """
        self._bind()
        B.resolve_facility_payload(FAC, self._payload())

        db.session.commit()
        db.session.expire_all()
        fresh = GeoFacility.query.filter_by(unique_id=FAC).first()
        stored = [f for f in fresh.fittings if f['id'] == FIT][0]['actuator_id']
        self.assertEqual(stored, LEGACY_DEV)

    # -- 폴백 신호의 신뢰성 ------------------------------------------------
    def test_dead_reference_does_not_raise_the_fallback_signal(self):
        """죽은 참조는 폴백이 아니다.

        백필은 실존하지 않는 장치를 가리키는 참조에 바인딩을 만들지 않는다
        (고아를 정본으로 승격시키지 않는 정책). 그래서 죽은 참조는 "바인딩
        없음 + 레거시 값 있음"이 되어 폴백과 모양이 같은데, 그대로 두면
        백필을 다 끝내도 폴백 경고가 영원히 켜진 채 남는다. 켜져 있는 게
        정상인 경고는 아무도 안 보게 되고(CI 13연속 실패), 무엇보다 이
        신호는 Phase C 의 게이팅 조건이라 못 쓰게 되면 안 된다.

        실제로 2026-08-08 로컬 백필 적용 직후 이 증상이 나왔다 — 죽은 참조
        19건이 폴백 경고를 계속 띄웠다.
        """
        # LEGACY_DEV 는 어떤 장치 테이블에도 없는 uuid = 죽은 참조
        B.reset_fallback_log()
        B.resolve_facility_payload(FAC, self._payload())
        self.assertNotIn('facility.fittings/actuators', B._fallback_seen,
                         '죽은 참조가 폴백 신호를 울렸다 — 게이팅 신호 오염')

    def test_live_reference_without_binding_does_raise_it(self):
        """살아있는 연결이 바인딩 없이 읽히면 그때는 울려야 한다."""
        from aot.databases.models import Output
        Output.query.delete()
        Output(unique_id=LEGACY_DEV, name='살아있는 출력').save()

        B.reset_fallback_log()
        B.resolve_facility_payload(FAC, self._payload())
        self.assertIn('facility.fittings/actuators', B._fallback_seen,
                      '전환되지 않은 살아있는 연결인데 신호가 없다')

    def test_unchanged_items_are_not_copied_needlessly(self):
        """이미 값이 같으면 원본 객체를 그대로 둔다(불필요한 사본 방지)."""
        self._bind(device_id=LEGACY_DEV)      # 저장값과 동일한 바인딩
        payload = self._payload()
        before = payload['fittings']
        B.resolve_facility_payload(FAC, payload)
        self.assertIs(payload['fittings'], before)


class TestShapeResolution(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        B.reset_fallback_log()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _shape(self, uid, stype='aot_device', device_id='dev-legacy'):
        from aot.databases.models import GeoShape
        s = GeoShape(unique_id=uid, geo_id='map-1', type=stype,
                     device_id=device_id, channel_id='0', feature={})
        s.save()
        return s

    def test_batch_resolution_matches_single(self):
        s = self._shape('sh-1')
        GeoBinding(spatial_kind='shape', spatial_id='sh-1', role='marker',
                   device_kind='output', device_id='dev-bound',
                   channel_id='0', valid_from=utc_now()).save()
        self.assertEqual(B.device_for_shape(s), 'dev-bound')
        self.assertEqual(B.devices_for_shapes([s]), {'sh-1': 'dev-bound'})

    def test_channel_suffix_is_stripped_on_fallback(self):
        """레거시 컬럼에는 'uuid::3' 형태가 섞여 있다(프런트 계약)."""
        s = self._shape('sh-2', stype='device', device_id='dev-x::3')
        self.assertEqual(B.device_for_shape(s), 'dev-x')

    def test_non_device_shape_types_are_ignored(self):
        """site/zone 은 장치를 매다는 자리가 아니다."""
        s = self._shape('sh-3', stype='zone', device_id='dev-y')
        self.assertIsNone(B.device_for_shape(s))
        self.assertEqual(B.devices_for_shapes([s]), {})


if __name__ == '__main__':
    unittest.main()
