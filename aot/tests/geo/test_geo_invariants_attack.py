# coding=utf-8
"""지도 데이터 불변식 공격 테스트 — 우회 경로로 위반을 시도하고 DB 가 막는지 검증.

2026-08-03 사고의 교훈: 오염원 24건 중 다수가 ORM 이벤트도 거치지 않는
bulk delete / 원시 SQL / 직접 INSERT 였다. 따라서 여기서는 일부러 가장
낮은 계층(원시 SQL, bulk delete)으로 공격한다 — 앱 계층 가드가 전부
우회된 상황에서도 DB 트리거·인덱스가 막아야 통과다.

"완성 판정은 주장이 아니라 공격 테스트로 한다"
(docs/design/geo-data-integrity.md). 새 불변식을 추가하면 반드시 여기에
공격을 추가할 것.

주의: Tier-2 는 앱 수정(S4)이 선행돼야 운영에 켤 수 있다. 이 테스트는
격리된 인메모리 DB 라 순서 제약 없이 Tier-2 의 차단력 자체를 검증한다.
"""
import json
import unittest

import sqlalchemy as sa
from flask import Flask
from sqlalchemy.exc import IntegrityError

from aot.aot_flask.extensions import db
from aot.databases.geo_integrity_ddl import (
    apply_binding, apply_tier1, apply_tier2)
from aot.databases.models import (
    GeoFacility, GeoFacilitySetpoint, GeoMap, GeoShape, Input, Output)


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _feature(aot_type=None, geom_type='Point', coords=None):
    props = {}
    if aot_type is not None:
        props['aot_type'] = aot_type
    return json.dumps({
        'type': 'Feature',
        'geometry': {'type': geom_type,
                     'coordinates': coords or [126.9, 35.8]},
        'properties': props,
    })


class _Base(unittest.TestCase):
    TIERS = (apply_tier1,)

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        raw = db.engine.raw_connection()
        try:
            for tier in self.TIERS:
                tier(raw)
            raw.commit()
        finally:
            raw.close()
        GeoMap(unique_id='map-1', name='공격 대상 지도',
               category='design').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # -- helpers ----------------------------------------------------------
    def _raw(self, sql, **params):
        res = db.session.execute(sa.text(sql), params)
        db.session.commit()
        return res

    def _attack(self, tag, sql, **params):
        """원시 SQL 공격이 지정 불변식 태그로 차단되는지 확인."""
        with self.assertRaises(IntegrityError) as ctx:
            self._raw(sql, **params)
        db.session.rollback()
        self.assertIn(tag, str(ctx.exception))

    def _insert_shape(self, uid, stype, geo_id='map-1', device_id=None,
                      channel_id=None, feature=None, parent_id=None):
        self._raw(
            'INSERT INTO geo_shape '
            '(unique_id, geo_id, device_id, channel_id, type, parent_id,'
            ' feature, created_at, updated_at) '
            "VALUES (:u, :g, :d, :c, :t, :p, :f, '2026-08-03', '2026-08-03')",
            u=uid, g=geo_id, d=device_id, c=channel_id, t=stype,
            p=parent_id, f=feature or _feature())

    def _shape_id(self, uid):
        return self._raw(
            'SELECT id FROM geo_shape WHERE unique_id=:u', u=uid).scalar()

    def _count(self, table, where, **params):
        return self._raw(
            'SELECT COUNT(*) FROM "%s" WHERE %s' % (table, where),
            **params).scalar()


class TestTier1Attacks(_Base):

    # I1 ------------------------------------------------------------------
    def test_i1_garbage_type_insert_blocked(self):
        with self.assertRaises(IntegrityError) as ctx:
            self._insert_shape('s-bad', 'banana')
        db.session.rollback()
        self.assertIn('GEO-I1', str(ctx.exception))

    def test_i1_garbage_type_update_blocked(self):
        self._insert_shape('s-ok', 'zone')
        self._attack('GEO-I1',
                     "UPDATE geo_shape SET type='banana' "
                     "WHERE unique_id='s-ok'")

    # I2 ------------------------------------------------------------------
    def test_i2_duplicate_marker_blocked_even_with_null_vs_zero_channel(self):
        # INSERT 경로는 channel NULL, UPDATE/API 경로는 '0' 을 쓰는 비대칭이
        # 중복 마커의 실제 발생 경로였다. COALESCE 인덱스가 접는지 검증.
        self._insert_shape('m-1', 'aot_device', device_id='dev-1',
                           channel_id=None)
        with self.assertRaises(IntegrityError):
            self._insert_shape('m-2', 'aot_device', device_id='dev-1',
                               channel_id='0')
        db.session.rollback()

    def test_i2_ai_bulk_create_cannot_duplicate_markers(self):
        # AI 대량생성 시나리오: 게이트웨이를 모르는 코드가 직접 INSERT 해도
        # 두 번째 마커는 DB 가 거부한다.
        self._insert_shape('m-a', 'aot_device', device_id='dev-ai',
                           channel_id='0')
        with self.assertRaises(IntegrityError):
            self._insert_shape('m-b', 'aot_device', device_id='dev-ai',
                               channel_id='0')
        db.session.rollback()

    def test_i2_other_channel_and_other_map_still_allowed(self):
        self._insert_shape('m-c0', 'aot_device', device_id='dev-2',
                           channel_id='0')
        self._insert_shape('m-c1', 'aot_device', device_id='dev-2',
                           channel_id='1')          # 다른 채널: 허용
        GeoMap(unique_id='map-2', name='둘째 지도', category='design').save()
        self._insert_shape('m-c0b', 'aot_device', device_id='dev-2',
                           channel_id='0', geo_id='map-2')  # 다른 지도: 허용

    def test_i2_drawn_regions_may_repeat(self):
        # 그려진 구역(type='device' 폴리곤)은 한 장치에 여러 개가 정당하다
        # (밸브 하나가 두 구역 관수). 과차단 회귀 방지.
        for uid in ('r-1', 'r-2'):
            self._insert_shape(uid, 'device', device_id='dev-3',
                               channel_id='0',
                               feature=_feature(geom_type='Polygon',
                                                coords=[[[0, 0], [0, 1],
                                                         [1, 1], [0, 0]]]))

    # I3 ------------------------------------------------------------------
    def _build_facility(self, suffix=''):
        self._insert_shape('fs%s' % suffix, 'facility')
        sid = self._shape_id('fs%s' % suffix)
        GeoFacility(unique_id='fac%s' % suffix, shape_uuid='fs%s' % suffix,
                    geo_id='map-1', name='시설', render_mode='parametric').save()
        GeoFacilitySetpoint(facility_uuid='fac%s' % suffix,
                            source='manual').save()
        self._insert_shape('bay%s' % suffix, 'facility_bay', parent_id=sid)
        return sid

    def test_i3_raw_sql_delete_still_cascades(self):
        self._build_facility('-r')
        self._raw("DELETE FROM geo_shape WHERE unique_id='fs-r'")
        self.assertEqual(self._count('geo_facility',
                                     "shape_uuid='fs-r'"), 0)
        self.assertEqual(self._count('geo_facility_setpoint',
                                     "facility_uuid='fac-r'"), 0)
        self.assertEqual(self._count('geo_shape',
                                     "unique_id='bay-r'"), 0)

    def test_i3_bulk_orm_delete_still_cascades(self):
        # 2026-08-03 실제 우회 경로: Query.delete() 는 ORM 이벤트·파이썬
        # 연쇄삭제를 전부 건너뛴다. 트리거는 건너뛸 수 없다.
        self._build_facility('-b')
        GeoShape.query.filter_by(unique_id='fs-b').delete(
            synchronize_session=False)
        db.session.commit()
        self.assertEqual(self._count('geo_facility',
                                     "shape_uuid='fs-b'"), 0)
        self.assertEqual(self._count('geo_facility_setpoint',
                                     "facility_uuid='fac-b'"), 0)

    # I4 ------------------------------------------------------------------
    def test_i4_shape_delete_releases_device_membership(self):
        self._insert_shape('z-1', 'zone')
        zid = self._shape_id('z-1')
        Input(name='센서', map_overlay_id=zid).save()
        Output(name='밸브', map_overlay_id=zid).save()
        self._raw("DELETE FROM geo_shape WHERE unique_id='z-1'")
        self.assertEqual(self._count('input', 'map_overlay_id IS NOT NULL'), 0)
        self.assertEqual(self._count('output', 'map_overlay_id IS NOT NULL'), 0)

    def test_i4_covers_sql_keyword_tables(self):
        # "trigger"/"function" 은 SQL 예약어 — 인용 누락이면 트리거 생성
        # 자체가 조용히 실패했을 것이므로 실제 동작으로 검증한다.
        self._insert_shape('z-2', 'zone')
        zid = self._shape_id('z-2')
        self._raw('UPDATE "input" SET map_overlay_id=NULL')
        db.session.execute(sa.text(
            'INSERT INTO "trigger" (unique_id, name, map_overlay_id)'
            " VALUES ('tr-1', '관수', :z)"), {'z': zid})
        db.session.execute(sa.text(
            'INSERT INTO "function" (unique_id, name, map_overlay_id)'
            " VALUES ('fn-1', '환경', :z)"), {'z': zid})
        db.session.commit()
        self._raw("DELETE FROM geo_shape WHERE unique_id='z-2'")
        self.assertEqual(
            self._count('trigger', 'map_overlay_id IS NOT NULL'), 0)
        self.assertEqual(
            self._count('function', 'map_overlay_id IS NOT NULL'), 0)

    # I5 ------------------------------------------------------------------
    def test_i5_map_delete_cleans_everything(self):
        # geo_design.py:144 시나리오 — 아무 가드 없는 원시 지도 삭제도
        # 도형·시설·장치 링크를 남기지 않아야 한다.
        self._build_facility('-m')
        zid = self._shape_id('fs-m')
        Input(name='센서2', map_overlay_id=zid,
              map_config_id='map-1').save()
        self._raw("DELETE FROM geo_map WHERE unique_id='map-1'")
        self.assertEqual(self._count('geo_shape', "geo_id='map-1'"), 0)
        self.assertEqual(self._count('geo_facility', "geo_id='map-1'"), 0)
        self.assertEqual(self._count('input', 'map_overlay_id IS NOT NULL'), 0)
        self.assertEqual(self._count('input', 'map_config_id IS NOT NULL'), 0)


class TestTier2Attacks(_Base):
    TIERS = (apply_tier1, apply_tier2)

    # I6 ------------------------------------------------------------------
    def test_i6_stored_aot_type_is_unrepresentable(self):
        # 드리프트의 전제 조건(두 번째 사본) 자체를 표현 불가능하게.
        with self.assertRaises(IntegrityError) as ctx:
            self._insert_shape('d-1', 'zone', feature=_feature('zone'))
        db.session.rollback()
        self.assertIn('GEO-I6', str(ctx.exception))
        self._insert_shape('d-2', 'zone', feature=_feature())  # 없으면 허용

    def test_i6_update_cannot_reintroduce_aot_type(self):
        self._insert_shape('d-3', 'zone', feature=_feature())
        self._attack('GEO-I6',
                     'UPDATE geo_shape SET feature=:f '
                     "WHERE unique_id='d-3'", f=_feature('site'))

    # I7 ------------------------------------------------------------------
    def test_i7_label_feedback_loop_is_dead(self):
        # 라벨 이름 변경 되먹임 고리의 마지막 단계(/delta 가 row.type 을
        # 덮어씀)를 재현 — 이제 어떤 경로로도 재분류는 불가능해야 한다.
        self._insert_shape('d-4', 'device', feature=_feature())
        self._attack('GEO-I7',
                     "UPDATE geo_shape SET type='aot_device' "
                     "WHERE unique_id='d-4'")

    def test_i7_same_value_update_is_not_blocked(self):
        self._insert_shape('d-5', 'zone', feature=_feature())
        self._raw("UPDATE geo_shape SET type='zone' WHERE unique_id='d-5'")

    # I8 ------------------------------------------------------------------
    def test_i8_phantom_map_shapes_are_unrepresentable(self):
        # routes_geo.py:552 의 '__parcel_import__' 영구 누수 시나리오.
        with self.assertRaises(IntegrityError) as ctx:
            self._insert_shape('p-1', 'site', geo_id='__parcel_import__')
        db.session.rollback()
        self.assertIn('GEO-I8', str(ctx.exception))


class TestBindingAttacks(_Base):
    """GB-1·GB-2 — 공간-장치 바인딩 (docs/design/geo-device-binding.md).

    이 불변식들이 지키는 것은 "슬롯 하나에 지금 장치 하나"와 "바인딩은
    지워지지 않고 끝난다"다. 둘 다 앱 계층에서만 지키면 장치 삭제 진입점
    17곳이 각자 구현하게 되고, 그중 하나만 빠뜨려도 조용히 갈린다.
    """
    TIERS = (apply_tier1,)

    def setUp(self):
        super(TestBindingAttacks, self).setUp()
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()

    def _bind(self, uid, spatial_kind='shape', spatial_id='sh-1',
              role='marker', device_kind='output', device_id='dev-1',
              channel_id='0', measurement_id=None, valid_to=None,
              ended_reason=None, valid_from='2026-08-08 00:00:00'):
        self._raw(
            'INSERT INTO geo_binding '
            '(unique_id, spatial_kind, spatial_id, role, device_kind,'
            ' device_id, channel_id, measurement_id, valid_from, valid_to,'
            ' ended_reason) '
            'VALUES (:u, :sk, :si, :r, :dk, :d, :c, :m, :vf, :vt, :er)',
            u=uid, sk=spatial_kind, si=spatial_id, r=role, dk=device_kind,
            d=device_id, c=channel_id, m=measurement_id, vf=valid_from,
            vt=valid_to, er=ended_reason)

    def _current(self, uid):
        row = self._raw('SELECT valid_to, ended_reason FROM geo_binding '
                        'WHERE unique_id=:u', u=uid).fetchone()
        return row

    # GB-3 — 장치 삭제 연쇄 -------------------------------------------------
    #
    # 앱 계층(end_all_for_device)이 이미 같은 일을 하고 삭제 경로 17곳이 전부
    # 그 문을 지나간다. 그런데도 트리거를 두는 이유는 원시 SQL·bulk delete·
    # 진단 일괄 삭제가 앱 규약을 아예 통과하지 않기 때문이다 — geo_shape.
    # device_id 가 정확히 그렇게 썩었다(정책 6갈래, 진입점 17곳, 실제로
    # 정리하는 곳 4곳, 아무도 몇 주 동안 모름).
    def test_gb3_raw_device_delete_ends_its_bindings(self):
        """앱을 통과하지 않은 삭제도 바인딩을 남기지 못한다."""
        self._raw("INSERT INTO output (unique_id, name) VALUES ('dev-x', 'v')")
        self._bind('b-1', device_id='dev-x', spatial_id='sh-1')

        self._raw("DELETE FROM output WHERE unique_id='dev-x'")

        valid_to, reason = self._current('b-1')
        self.assertIsNotNone(valid_to, '장치가 사라졌는데 바인딩이 현재로 남았다')
        self.assertEqual(reason, 'device_deleted')

    def test_gb3_does_not_touch_other_devices(self):
        self._raw("INSERT INTO output (unique_id, name) VALUES ('dev-x', 'v')")
        self._raw("INSERT INTO output (unique_id, name) VALUES ('dev-y', 'w')")
        self._bind('b-1', device_id='dev-x', spatial_id='sh-1')
        self._bind('b-2', device_id='dev-y', spatial_id='sh-2')

        self._raw("DELETE FROM output WHERE unique_id='dev-x'")
        self.assertIsNone(self._current('b-2')[0])

    def test_gb3_does_not_revive_an_already_ended_binding(self):
        """이미 끝난 바인딩의 사유를 덧칠하지 않는다 — 이력이 왜곡된다."""
        self._raw("INSERT INTO output (unique_id, name) VALUES ('dev-x', 'v')")
        self._bind('b-1', device_id='dev-x', spatial_id='sh-1',
                   valid_to='2026-08-08 01:00:00', ended_reason='replaced')

        self._raw("DELETE FROM output WHERE unique_id='dev-x'")

        valid_to, reason = self._current('b-1')
        self.assertEqual(reason, 'replaced')
        self.assertEqual(str(valid_to)[:19], '2026-08-08 01:00:00')

    def test_gb3_covers_every_device_table(self):
        """마커는 Function·PID·Trigger 에도 붙는다 — 3종으로 좁히면 샌다."""
        cases = [('input', 'input'), ('output', 'output'), ('pid', 'pid'),
                 ('trigger', 'trigger'), ('conditional', 'conditional'),
                 ('custom_controller', 'device'), ('function', 'function')]
        for i, (table, kind) in enumerate(cases):
            dev, uid, shape = 'd-%d' % i, 'b-%d' % i, 'sh-%d' % i
            self._raw("INSERT INTO %s (unique_id, name) VALUES (:d, 'x')"
                      % table, d=dev)
            self._bind(uid, device_id=dev, device_kind=kind, spatial_id=shape)
            self._raw("DELETE FROM %s WHERE unique_id=:d" % table, d=dev)
            self.assertIsNotNone(
                self._current(uid)[0],
                '%s 삭제가 바인딩을 끝내지 않았다' % table)

    # GB-4 — 공간 요소 삭제 연쇄 --------------------------------------------
    def test_gb4_shape_delete_ends_its_binding(self):
        self._raw("INSERT INTO geo_shape (unique_id, geo_id, type, feature) "
                  "VALUES ('sh-9', 'map-1', 'device', '{}')")
        self._bind('b-1', spatial_id='sh-9', role='area')

        self._raw("DELETE FROM geo_shape WHERE unique_id='sh-9'")

        valid_to, reason = self._current('b-1')
        self.assertIsNotNone(valid_to, '도형이 사라졌는데 바인딩이 남았다')
        self.assertEqual(reason, 'spatial_deleted')

    def test_gb4_facility_delete_ends_both_slot_shapes(self):
        """시설 슬롯 주소는 두 모양이다 — 한쪽만 보면 나머지가 남는다."""
        self._raw("INSERT INTO geo_shape (unique_id, geo_id, type, feature) "
                  "VALUES ('sh-f', 'map-1', 'facility', '{}')")
        self._raw("INSERT INTO geo_facility "
                  "(unique_id, shape_uuid, geo_id, name, render_mode) "
                  "VALUES ('fac-1', 'sh-f', 'map-1', '온실A', '3d')")
        self._bind('b-1', spatial_kind='fitting', spatial_id='fac-1:F1',
                   role='actuator')
        self._bind('b-2', spatial_kind='sensor_role', spatial_id='fac-1',
                   role='indoor_temp')

        self._raw("DELETE FROM geo_facility WHERE unique_id='fac-1'")

        self.assertIsNotNone(self._current('b-1')[0], 'fitting 이 남았다')
        self.assertIsNotNone(self._current('b-2')[0], 'sensor_role 이 남았다')

    def test_gb4_does_not_end_a_lookalike_prefix(self):
        """'fac-1' 삭제가 'fac-10:...' 슬롯을 끌고 가면 안 된다."""
        self._raw("INSERT INTO geo_shape (unique_id, geo_id, type, feature) "
                  "VALUES ('sh-f', 'map-1', 'facility', '{}')")
        self._raw("INSERT INTO geo_facility "
                  "(unique_id, shape_uuid, geo_id, name, render_mode) "
                  "VALUES ('fac-1', 'sh-f', 'map-1', '온실A', '3d')")
        self._bind('b-1', spatial_kind='fitting', spatial_id='fac-10:F1',
                   role='actuator')

        self._raw("DELETE FROM geo_facility WHERE unique_id='fac-1'")
        self.assertIsNone(self._current('b-1')[0],
                          '이름이 비슷한 다른 시설의 슬롯까지 끝냈다')

    def test_gb4_end_survives_gb2_timestamp_check(self):
        """같은 초에 만들어 지운 바인딩도 GB-2 에 걸리지 않는다.

        SQLite 는 시각을 문자열로 비교한다. SQLAlchemy 가 쓴 valid_from 은
        소수점 6자리인데 트리거의 strftime('%f') 는 3자리라, 그냥 now() 를
        쓰면 '12.500' < '12.500000' 이 되어 GB-2 의 "valid_to 가 valid_from
        보다 이르다"가 삭제를 통째로 막는다.
        """
        self._raw("INSERT INTO geo_shape (unique_id, geo_id, type, feature) "
                  "VALUES ('sh-9', 'map-1', 'device', '{}')")
        self._raw("INSERT INTO geo_binding "
                  "(unique_id, spatial_kind, spatial_id, role, device_kind,"
                  " device_id, channel_id, valid_from) "
                  "VALUES ('b-1','shape','sh-9','area','output','dev-1','0',"
                  " strftime('%Y-%m-%d %H:%M:%f','now') || '999')")

        self._raw("DELETE FROM geo_shape WHERE unique_id='sh-9'")
        self.assertIsNotNone(self._current('b-1')[0])

    # GB-1a — 단일 점유 -----------------------------------------------------
    def test_gb1_single_slot_cannot_have_two_current_bindings(self):
        """한 창을 두 모터가 열 수는 없다."""
        self._bind('b-1', device_id='dev-1')
        with self.assertRaises(IntegrityError):
            self._bind('b-2', device_id='dev-2')
        db.session.rollback()

    def test_gb1_ended_binding_frees_the_slot(self):
        """교체의 정상 경로 — 종료 후 같은 슬롯에 새 장치를 붙일 수 있다."""
        self._bind('b-1', device_id='dev-1',
                   valid_to='2026-08-08 01:00:00', ended_reason='replaced')
        self._bind('b-2', device_id='dev-2')
        self.assertEqual(
            self._count('geo_binding', 'valid_to IS NULL'), 1)

    def test_gb1_same_shape_different_channel_is_allowed(self):
        """채널이 다르면 다른 슬롯이다(다채널 릴레이의 구역별 배정)."""
        self._bind('b-1', spatial_id='sh-1', role='area', channel_id='5')
        self._bind('b-2', spatial_id='sh-1', role='area', channel_id='6')
        self.assertEqual(self._count('geo_binding', '1=1'), 2)

    # GB-1b — 다중 점유 -----------------------------------------------------
    def test_gb1_sensor_role_allows_multiple_devices(self):
        """sensors 는 같은 role 에 여러 장치를 등록해 가중평균하는 것이
        정상이다. 단일 규칙을 일괄 적용했다면 여기서 막혀 정상 기능이
        DB 에서 거부됐을 것이다."""
        self._bind('b-1', spatial_kind='sensor_role', spatial_id='fac-1',
                   role='indoor_temp', device_kind='input', device_id='in-1',
                   measurement_id='m-1')
        self._bind('b-2', spatial_kind='sensor_role', spatial_id='fac-1',
                   role='indoor_temp', device_kind='input', device_id='in-2',
                   measurement_id='m-2')
        self.assertEqual(
            self._count('geo_binding', 'valid_to IS NULL'), 2)

    def test_gb1_same_input_two_measurements_same_role_is_allowed(self):
        """한 센서의 서로 다른 측정 채널 둘을 같은 role 에 넣는 것은 정상."""
        self._bind('b-1', spatial_kind='sensor_role', spatial_id='fac-1',
                   role='indoor_temp', device_kind='input', device_id='in-1',
                   measurement_id='m-1')
        self._bind('b-2', spatial_kind='sensor_role', spatial_id='fac-1',
                   role='indoor_temp', device_kind='input', device_id='in-1',
                   measurement_id='m-2')
        self.assertEqual(
            self._count('geo_binding', 'valid_to IS NULL'), 2)

    def test_gb1_exact_duplicate_sensor_binding_blocked(self):
        """같은 (장치, 채널, 측정값)의 중복 등록은 집계를 왜곡하므로 막는다."""
        self._bind('b-1', spatial_kind='sensor_role', spatial_id='fac-1',
                   role='indoor_temp', device_kind='input', device_id='in-1',
                   measurement_id='m-1')
        with self.assertRaises(IntegrityError):
            self._bind('b-2', spatial_kind='sensor_role', spatial_id='fac-1',
                       role='indoor_temp', device_kind='input',
                       device_id='in-1', measurement_id='m-1')
        db.session.rollback()

    def test_gb1_duplicate_with_null_measurement_blocked(self):
        """measurement_id 가 NULL 이어도 중복은 중복이다 — SQLite 의
        'NULL 은 서로 다르다' 규칙을 COALESCE 로 접어 막는다."""
        self._bind('b-1', spatial_kind='weather', spatial_id='fac-1',
                   role='forecast_temperature', device_kind='input',
                   device_id='in-1')
        with self.assertRaises(IntegrityError):
            self._bind('b-2', spatial_kind='weather', spatial_id='fac-1',
                       role='forecast_temperature', device_kind='input',
                       device_id='in-1')
        db.session.rollback()

    # GB-2 — 수명 정합 + 어휘 ----------------------------------------------
    def test_gb2_ended_binding_requires_reason(self):
        """이유 없는 종료는 '왜 끝났나'에 답할 수 없다 — 이력의 존재 이유가
        사라진다."""
        self._attack(
            'GEO-GB2',
            'INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id,'
            ' role, device_kind, device_id, channel_id, valid_from, valid_to)'
            " VALUES ('b-x','shape','sh-1','marker','output','dev-1','0',"
            "'2026-08-08 00:00:00','2026-08-08 01:00:00')")

    def test_gb2_update_cannot_end_without_reason(self):
        """UPDATE 경로도 같이 막는다 — 트리거가 INSERT 에만 있으면
        '만들고 나서 고치기'로 우회된다."""
        self._bind('b-1')
        self._attack('GEO-GB2',
                     "UPDATE geo_binding SET valid_to='2026-08-08 01:00:00' "
                     "WHERE unique_id='b-1'")

    def test_gb2_valid_to_before_valid_from_blocked(self):
        self._attack(
            'GEO-GB2',
            'INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id,'
            ' role, device_kind, device_id, channel_id, valid_from, valid_to,'
            ' ended_reason)'
            " VALUES ('b-x','shape','sh-1','marker','output','dev-1','0',"
            "'2026-08-08 02:00:00','2026-08-08 01:00:00','replaced')")

    def test_gb2_unknown_spatial_kind_blocked(self):
        self._attack(
            'GEO-GB2',
            'INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id,'
            ' role, device_kind, device_id, channel_id, valid_from)'
            " VALUES ('b-x','banana','sh-1','marker','output','dev-1','0',"
            "'2026-08-08 00:00:00')")

    def test_gb2_unknown_device_kind_blocked(self):
        self._attack(
            'GEO-GB2',
            'INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id,'
            ' role, device_kind, device_id, channel_id, valid_from)'
            " VALUES ('b-x','shape','sh-1','marker','banana','dev-1','0',"
            "'2026-08-08 00:00:00')")

    def test_gb2_function_pid_trigger_kinds_are_allowed(self):
        """마커는 Function·PID·Trigger 에도 붙는다(place_device). 어휘를
        input/output/device 3종으로 좁혔다면 정상 배치가 여기서 막힌다."""
        for i, kind in enumerate(
                ('function', 'pid', 'trigger', 'conditional', 'device')):
            self._bind('b-%d' % i, spatial_id='sh-%d' % i,
                       device_kind=kind, device_id='dev-%d' % i)
        self.assertEqual(self._count('geo_binding', 'valid_to IS NULL'), 5)

    def test_gb2_unknown_end_reason_blocked(self):
        self._attack(
            'GEO-GB2',
            'INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id,'
            ' role, device_kind, device_id, channel_id, valid_from, valid_to,'
            ' ended_reason)'
            " VALUES ('b-x','shape','sh-1','marker','output','dev-1','0',"
            "'2026-08-08 00:00:00','2026-08-08 01:00:00','because')")

    def test_gb2_null_channel_blocked(self):
        """NULL/'0' 비대칭이 중복 마커의 실제 발생 경로였다(I2). 같은 구멍을
        바인딩에서 되풀이하지 않는다."""
        self._attack(
            'GEO-GB2',
            'INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id,'
            ' role, device_kind, device_id, channel_id, valid_from)'
            " VALUES ('b-x','shape','sh-1','marker','output','dev-1',NULL,"
            "'2026-08-08 00:00:00')")


class TestBindingDriftSkipsMissingTable(unittest.TestCase):
    """binding-drift 검사가 '못 본 것'을 '문제 없음'으로 보고하지 않는지.

    두 경우를 갈라야 한다:
      - geo_binding 이 **없는** 설치(p6_27 이전) → 검사 대상 아님, 빈 목록
      - 테이블은 있는데 조회가 **실패**하는 경우(부분 적용 마이그레이션,
        컬럼 누락, 파손) → 침묵하지 말고 위로 던져 종료 2 로 드러나야 한다

    `try: 조회 except: return []` 는 둘을 구분하지 못해 후자를 '드리프트
    0건'으로 만든다. 아래 두 번째 테스트가 그 차이를 잡는 음성 대조다 —
    try/except 구현으로 되돌리면 실패한다.
    """

    def setUp(self):
        self.app = _make_app()
        # check_geo_integrity 는 aot.start_flask_ui 를 끌어오고, 그 사슬의
        # lazy_gettext 가 current_app.extensions['babel'] 을 찾는다. 이
        # 테스트의 앱은 맨 Flask 라 붙여 주지 않으면 KeyError 로 죽는다 —
        # 검사 대상(세션 오염 방지)과 무관한 실패다.
        try:
            from flask_babel import Babel
            Babel(self.app)
        except Exception:
            pass
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        # p6_27 이전 상태 재현
        db.session.execute(sa.text('DROP TABLE IF EXISTS geo_binding'))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_missing_table_is_skipped_quietly(self):
        """테이블이 아예 없으면 검사 대상이 아니다 — 조용히 건너뛴다."""
        from aot.scripts.check_geo_integrity import _binding_drift

        self.assertEqual(_binding_drift([], set()), [])

    def test_broken_table_is_not_reported_as_clean(self):
        """테이블은 있는데 스키마가 어긋난 경우(부분 적용된 마이그레이션).
        '드리프트 0건'으로 침묵하면 사람은 정상이라고 믿는다."""
        from aot.scripts.check_geo_integrity import _binding_drift

        # 컬럼이 모자란 geo_binding — 조회가 실패하는 상태를 만든다.
        db.session.execute(sa.text(
            'CREATE TABLE geo_binding (id INTEGER PRIMARY KEY, '
            'unique_id VARCHAR(36))'))
        db.session.commit()

        with self.assertRaises(Exception):
            _binding_drift([], set())


if __name__ == '__main__':
    unittest.main()
