# coding=utf-8
"""device_binding 쓰기 게이트웨이 — bind / unbind / rebind.

여기서 지키는 것은 세 가지다.

1. **슬롯을 조용히 덮어쓰지 않는다.** 점유된 슬롯에 bind 하면 실패한다.
   덮어쓰기가 허용되면 교체 이력이 사라지고, 이력이 사라지면 장치 교체를
   관통하는 시계열 접합의 근거가 없어진다(B3).
2. **교체는 한 트랜잭션이다.** rebind 는 옛 바인딩을 종료하고 새것을 만드는
   두 동작이지만, 중간 상태가 밖에서 보이면 안 된다. 옛 행을 끝내지 않은 채
   새 행이 들어가면 GB-1 유니크 인덱스에서 스스로 충돌한다 — 아래
   `test_rebind_survives_the_unique_index` 가 그 결과를 지킨다.
3. **다중 점유 슬롯을 단일 점유처럼 다루지 않는다.** sensors/weather 는 같은
   role 에 여러 장치를 등록해 가중평균하는 것이 정상이라, 슬롯 키로 교체하면
   나머지 장치까지 함께 종료된다.

GB-1/GB-2 를 DB 가 실제로 무는지는 `test_geo_invariants_attack.py` 담당이다
(원시 SQL 공격). 여기는 게이트웨이의 의미론을 본다.
"""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_binding as B
from aot.databases.geo_integrity_ddl import apply_binding
from aot.databases.models import GeoBinding, Output


SHAPE = 'shape-uuid-0001'
DEV_A = 'dev-aaaa-0001'
DEV_B = 'dev-bbbb-0002'


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


class _Base(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        # GB-1 유니크 인덱스를 실제로 건다 — 게이트웨이가 파이썬에서만 막고
        # DB 는 통과시키는 상태를 테스트가 정상으로 보면 안 된다.
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()
        B.reset_fallback_log()
        Output(unique_id=DEV_A, name='출력 A').save()
        Output(unique_id=DEV_B, name='출력 B').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _current(self, role='area'):
        return B.current_one('shape', SHAPE, role=role)


class TestBind(_Base):

    def test_bind_creates_a_current_binding(self):
        row = B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        self.assertIsNone(row.valid_to)
        self.assertEqual(self._current().device_id, DEV_A)

    def test_occupied_slot_is_refused(self):
        """덮어쓰기 대신 거부 — 교체 이력을 잃지 않기 위해서다."""
        B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        with self.assertRaises(B.BindingConflict):
            B.bind('shape', SHAPE, 'area', 'output', DEV_B)
        db.session.rollback()
        self.assertEqual(self._current().device_id, DEV_A)

    def test_ended_binding_frees_the_slot(self):
        row = B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        B.unbind(row.unique_id, 'unbound', commit=True)
        B.bind('shape', SHAPE, 'area', 'output', DEV_B, commit=True)
        self.assertEqual(self._current().device_id, DEV_B)

    def test_other_channel_is_a_different_slot(self):
        """다채널 릴레이 — 한 구역에 채널이 다른 여러 배정은 정상이다."""
        B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        B.bind('shape', SHAPE, 'area', 'output', DEV_B, channel_id='2',
               commit=True)
        self.assertEqual(len(B.current('shape', SHAPE, role='area')), 2)

    def test_channel_is_normalised_to_string_zero(self):
        """NULL/'0' 비대칭이 중복 마커의 실제 발생 경로였다(I2)."""
        row = B.bind('shape', SHAPE, 'area', 'output', DEV_A, channel_id=None)
        self.assertEqual(row.channel_id, '0')

    def test_channel_suffix_is_stripped_from_device_id(self):
        """프런트 계약의 'uuid::3' 이 그대로 저장되면 안 된다."""
        row = B.bind('shape', SHAPE, 'area', 'output', DEV_A + '::3',
                     channel_id='3')
        self.assertEqual(row.device_id, DEV_A)

    def test_vocabulary_is_enforced_before_the_db_sees_it(self):
        with self.assertRaises(B.BindingError):
            B.bind('greenhouse', SHAPE, 'area', 'output', DEV_A)
        with self.assertRaises(B.BindingError):
            B.bind('shape', SHAPE, 'area', 'relay', DEV_A)

    # -- 다중 점유 --------------------------------------------------------
    def test_multi_occupancy_allows_several_devices_in_one_role(self):
        """sensors 는 같은 role 에 여러 장치를 등록해 가중평균한다."""
        B.bind('sensor_role', 'fac-1', 'indoor_temp', 'input', DEV_A,
               measurement_id='m-1', commit=True)
        B.bind('sensor_role', 'fac-1', 'indoor_temp', 'input', DEV_B,
               measurement_id='m-2', commit=True)
        self.assertEqual(
            len(B.current('sensor_role', 'fac-1', role='indoor_temp')), 2)

    def test_multi_occupancy_still_refuses_exact_duplicates(self):
        B.bind('sensor_role', 'fac-1', 'indoor_temp', 'input', DEV_A,
               measurement_id='m-1', commit=True)
        with self.assertRaises(B.BindingConflict):
            B.bind('sensor_role', 'fac-1', 'indoor_temp', 'input', DEV_A,
                   measurement_id='m-1')
        db.session.rollback()

    def test_same_device_different_measurement_is_allowed(self):
        """한 Input 의 서로 다른 측정 채널 둘을 같은 role 에 넣는 것은 정상."""
        B.bind('sensor_role', 'fac-1', 'indoor_temp', 'input', DEV_A,
               measurement_id='m-1', commit=True)
        B.bind('sensor_role', 'fac-1', 'indoor_temp', 'input', DEV_A,
               measurement_id='m-2', commit=True)
        self.assertEqual(
            len(B.current('sensor_role', 'fac-1', role='indoor_temp')), 2)


class TestUnbind(_Base):

    def test_unbind_ends_but_does_not_delete(self):
        row = B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        B.unbind(row.unique_id, 'unbound', commit=True)

        self.assertIsNone(self._current(), '종료된 바인딩이 현재로 남았다')
        self.assertEqual(GeoBinding.query.count(), 1,
                         '바인딩은 지워지는 것이 아니라 끝나는 것이다(B3)')
        ended = GeoBinding.query.first()
        self.assertIsNotNone(ended.valid_to)
        self.assertEqual(ended.ended_reason, 'unbound')

    def test_unbind_is_idempotent(self):
        row = B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        first = B.unbind(row.unique_id, 'unbound', commit=True)
        again = B.unbind(row.unique_id, 'device_deleted', commit=True)
        self.assertEqual(again.valid_to, first.valid_to)
        self.assertEqual(again.ended_reason, 'unbound',
                         '이미 끝난 바인딩의 사유를 덧칠하면 안 된다')

    def test_unknown_reason_is_refused(self):
        row = B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        with self.assertRaises(B.BindingError):
            B.unbind(row.unique_id, 'because')

    def test_unknown_binding_raises(self):
        with self.assertRaises(B.BindingNotFound):
            B.unbind('no-such-uid', 'unbound')


class TestRebind(_Base):

    def test_rebind_ends_the_old_and_starts_the_new(self):
        B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        B.rebind('shape', SHAPE, 'area', 'output', DEV_B, commit=True)

        self.assertEqual(self._current().device_id, DEV_B)
        old = GeoBinding.query.filter_by(device_id=DEV_A).first()
        self.assertEqual(old.ended_reason, 'replaced')
        self.assertIsNotNone(old.valid_to)

    def test_rebind_survives_the_unique_index(self):
        """교체가 자기 자신과 충돌하지 않는다.

        옛 행이 아직 valid_to IS NULL 인 채로 새 행이 들어가면 GB-1a 부분
        유니크 인덱스에 걸린다. 이 테스트는 인덱스가 실제로 걸린 DB 에서
        돈다(setUp 의 apply_binding).

        주의 — 결과를 지키는 테스트이지 구현의 flush 순서를 지키는 테스트가
        아니다. 2026-08-08 음성 대조에서 rebind 의 명시 flush 를 빼도
        통과했다: SQLAlchemy 의 save_obj 가 같은 테이블에서 UPDATE 를
        INSERT 보다 먼저 emit 하기 때문이다. 그 내부 순서가 바뀌는 날
        이 테스트가 경보가 된다.
        """
        B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        B.rebind('shape', SHAPE, 'area', 'output', DEV_B, commit=True)
        rows = GeoBinding.query.filter_by(spatial_id=SHAPE).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(1 for r in rows if r.valid_to is None), 1)

    def test_rebind_to_the_same_device_is_a_no_op(self):
        """마커를 끌 때마다 호출되는 경로가 있다 — 이력을 쓰레기로 만들지 않는다."""
        first = B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        again = B.rebind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        self.assertEqual(again.unique_id, first.unique_id)
        self.assertEqual(GeoBinding.query.count(), 1)

    def test_rebind_on_empty_slot_just_binds(self):
        row = B.rebind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        self.assertIsNone(row.valid_to)
        self.assertEqual(GeoBinding.query.count(), 1)

    def test_rebind_refuses_multi_occupancy_slots(self):
        """가중평균 구성을 슬롯 키 하나로 날려버리지 않는다."""
        B.bind('sensor_role', 'fac-1', 'indoor_temp', 'input', DEV_A,
               measurement_id='m-1', commit=True)
        with self.assertRaises(B.BindingError):
            B.rebind('sensor_role', 'fac-1', 'indoor_temp', 'input', DEV_B,
                     measurement_id='m-2')
        self.assertEqual(
            len(B.current('sensor_role', 'fac-1', role='indoor_temp')), 1)

    def test_history_reads_the_replacement(self):
        """시계열 접합이 읽을 구간 목록 — 이것이 이력의 최대 실익이다."""
        B.bind('shape', SHAPE, 'area', 'output', DEV_A, commit=True)
        B.rebind('shape', SHAPE, 'area', 'output', DEV_B, commit=True)
        seq = [b.device_id for b in B.history('shape', SHAPE, role='area')]
        self.assertEqual(seq, [DEV_A, DEV_B])


class TestMarkerPathRecordsBinding(unittest.TestCase):
    """마커 배치도 바인딩을 남긴다 — 안 남기면 드리프트가 늘어난다.

    `place_device` 가 `GeoShape.device_id` 컬럼에만 쓰고 바인딩을 만들지
    않으면, UI 로 장치를 놓을 때마다 "레거시에는 있는데 바인딩에는 없는"
    연결이 새로 생긴다. 그게 정확히 `check_geo_integrity` 의 binding-drift 가
    세는 것이고, Phase C 의 게이팅 신호를 전환과 반대 방향으로 민다.

    레거시 컬럼 쓰기는 이 단계에서 제거하지 않는다(Phase C 의 폴백 제거와
    함께 간다) — 그래서 두 저장처가 같은 값을 갖는지도 함께 본다.
    """

    def setUp(self):
        from aot.databases.models import GeoMap
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()
        GeoMap(unique_id='m1', name='배치 검증', category='design').save()
        Output(unique_id=DEV_A, name='밸브').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _place(self, **kw):
        from aot.aot_flask.geo.device_placement import place_device
        return place_device(DEV_A, 'm1', 35.8, 126.9, commit=True, **kw)

    def test_placement_creates_a_marker_binding(self):
        marker = self._place()
        row = B.current_one('shape', marker.unique_id, role='marker')
        self.assertIsNotNone(row, 'place_device 가 바인딩을 남기지 않았다')
        self.assertEqual(row.device_id, DEV_A)
        self.assertEqual(row.device_kind, 'output')
        self.assertEqual(row.device_id, marker.device_id,
                         '두 저장처가 갈렸다 — 이중 저장 기간의 드리프트')

    def test_moving_the_marker_does_not_churn_history(self):
        from aot.aot_flask.geo.device_placement import place_device
        marker = self._place()
        place_device(DEV_A, 'm1', 35.9, 127.0, commit=True)
        self.assertEqual(
            len(B.history('shape', marker.unique_id, role='marker')), 1,
            '이동마다 교체 이력이 쌓이면 이력이 무엇이 바뀌었는지 말해주지 못한다')

    def test_unplacing_ends_the_binding_without_deleting_it(self):
        from aot.aot_flask.geo.device_placement import unplace_device
        marker = self._place()
        uid = marker.unique_id
        unplace_device(DEV_A, 'm1', 0, commit=True)

        self.assertIsNone(B.current_one('shape', uid, role='marker'))
        ended = GeoBinding.query.filter_by(spatial_id=uid).first()
        self.assertIsNotNone(ended, '바인딩 행이 지워졌다 — 이력이 사라진다')
        self.assertEqual(ended.ended_reason, 'unbound')

    def test_unknown_device_gets_no_binding(self):
        """죽은 참조를 정본으로 승격시키지 않는다(백필과 같은 정책)."""
        from aot.aot_flask.geo.device_placement import place_device
        marker = place_device('dev-not-in-any-table', 'm1', 35.8, 126.9,
                              commit=True)
        self.assertIsNotNone(marker, '바인딩 실패가 배치를 막으면 안 된다')
        self.assertEqual(GeoBinding.query.count(), 0)


class TestDeviceKindResolution(_Base):

    def test_kind_comes_from_the_table_the_uuid_lives_in(self):
        self.assertEqual(B.resolve_device_kind(DEV_A), 'output')

    def test_unknown_device_resolves_to_none(self):
        """죽은 참조에 바인딩을 만들지 않기 위한 관문."""
        self.assertIsNone(B.resolve_device_kind('dev-does-not-exist'))

    def test_channel_suffix_is_tolerated(self):
        self.assertEqual(B.resolve_device_kind(DEV_A + '::2'), 'output')


if __name__ == '__main__':
    unittest.main()
