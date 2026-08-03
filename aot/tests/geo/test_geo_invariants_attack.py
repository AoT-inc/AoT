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
from aot.databases.geo_integrity_ddl import apply_tier1, apply_tier2
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


if __name__ == '__main__':
    unittest.main()
