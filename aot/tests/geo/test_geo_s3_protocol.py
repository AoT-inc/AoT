# coding=utf-8
"""S3 구조 개편 회귀 테스트 — 파생 소속·upsert 전용 저장·복제 거부목록.

세 가지 구조 불변식을 고정한다 (docs/design/geo-data-integrity.md S3):
  I9   save_overlays 는 upsert 전용 — 페이로드 누락은 절대 삭제가 아니다.
       db_id 를 잃은 피처는 node_id 로 기존 행을 되찾아 갱신한다(중복 금지).
  I10  clone_model 은 교차참조 컬럼(map_overlay_id·map_config_id)을 암묵
       복사하지 않는다 — 복제본은 미배치로 시작한다.
  파생 소속: 장치 ↔ zone 소속은 저장 컬럼이 아니라 마커 좌표에서 파생된다.
       zone 이 삭제 후 재생성돼 id 가 바뀌어도 소속은 흔들리지 않는다
       (2026-08-03 사고의 최다 발생원 재현 → 이제 무해함을 고정).
"""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases import clone_model
from aot.databases.models import GeoMap, GeoShape, Input, Output


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    try:                                    # 삭제 연쇄 경로가 gettext 사용
        from flask_babel import Babel
        Babel(app)
    except Exception:
        pass
    return app


def _poly(coords):
    return {'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [coords]},
            'properties': {}}


def _point(lng, lat, props=None):
    return {'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lng, lat]},
            'properties': props or {}}


ZONE_RING = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]


class _Base(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        GeoMap(unique_id='m1', name='지도', category='design').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


class TestDerivedMembership(_Base):
    """소속 = 마커 좌표에서 파생. zone id 가 바뀌어도 흔들리지 않는다."""

    def _place(self):
        zone = GeoShape(unique_id='z1', geo_id='m1', type='zone',
                        feature=_poly(ZONE_RING))
        zone.save()
        GeoShape(unique_id='mk1', geo_id='m1', type='aot_device',
                 device_id='dev-1', channel_id='0',
                 feature=_point(5, 5)).save()
        GeoShape(unique_id='mk2', geo_id='m1', type='aot_device',
                 device_id='dev-out', channel_id='0',
                 feature=_point(20, 20)).save()   # zone 밖
        return zone

    def test_marker_inside_zone_is_member(self):
        from aot.aot_flask.geo.device_membership import (
            device_ids_in_shape, zone_for_device)
        zone = self._place()
        self.assertEqual(device_ids_in_shape(zone), {'dev-1'})
        z = zone_for_device('dev-1', 'm1')
        self.assertIsNotNone(z)
        self.assertEqual(z.unique_id, 'z1')
        self.assertIsNone(zone_for_device('dev-out', 'm1'))  # zone 밖 장치

    def test_zone_beats_site(self):
        from aot.aot_flask.geo.device_membership import zone_for_device
        GeoShape(unique_id='site1', geo_id='m1', type='site',
                 feature=_poly([[-5, -5], [-5, 15], [15, 15],
                                [15, -5], [-5, -5]])).save()
        self._place()
        z = zone_for_device('dev-1', 'm1')
        self.assertEqual(z.type, 'zone')

    def test_membership_survives_zone_recreation(self):
        # 2026-08-03 최다 발생원: zone 삭제 후 새 id 로 재생성. 저장 컬럼
        # 방식은 소속이 전원 끊겼다. 파생 방식은 아무 일도 없어야 한다.
        from aot.aot_flask.geo.device_membership import zone_for_device
        zone = self._place()
        old_id = zone.id
        db.session.delete(zone)
        db.session.commit()
        GeoShape(unique_id='z1-new', geo_id='m1', type='zone',
                 feature=_poly(ZONE_RING)).save()
        z = zone_for_device('dev-1', 'm1')
        self.assertIsNotNone(z)
        self.assertNotEqual(z.id, old_id)
        self.assertEqual(z.unique_id, 'z1-new')

    def test_site_polygon_includes_nested_zone_devices(self):
        from aot.aot_flask.geo.device_membership import device_ids_in_shape
        site = GeoShape(unique_id='site1', geo_id='m1', type='site',
                        feature=_poly([[-5, -5], [-5, 15], [15, 15],
                                       [15, -5], [-5, -5]]))
        site.save()
        self._place()
        self.assertEqual(device_ids_in_shape(site), {'dev-1'})


class TestUpsertOnlySave(_Base):
    """I9 — save_overlays 는 페이로드 누락으로 절대 지우지 않는다."""

    def _two_zones(self):
        a = GeoShape(unique_id='za', geo_id='m1', type='zone',
                     feature=_poly(ZONE_RING))
        a.save()
        af = dict(a.feature)
        af['properties'] = {'node_id': 'node-a'}
        a.feature = af
        b = GeoShape(unique_id='zb', geo_id='m1', type='zone',
                     feature=_poly([[20, 20], [20, 30], [30, 30],
                                    [30, 20], [20, 20]]))
        b.save()
        bf = dict(b.feature)
        bf['properties'] = {'node_id': 'node-b'}
        b.feature = bf
        db.session.commit()
        return a, b

    def test_omitted_rows_survive(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        a, b = self._two_zones()
        feat = dict(a.feature)
        feat['properties'] = {'node_id': 'node-a', 'db_id': a.id,
                              'aot_type': 'zone'}
        result, err = GeoOverlayManager.save_overlays(
            {'map_uuid': 'm1', 'type': 'zone', 'features': [feat]})
        self.assertIsNone(err)
        self.assertEqual(result['stats']['deleted'], 0)
        # b 는 페이로드에 없었지만 살아 있어야 한다.
        self.assertEqual(
            GeoShape.query.filter_by(unique_id='zb').count(), 1)

    def test_lost_db_id_rematches_by_node_id_no_duplicate(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        a, b = self._two_zones()
        # 클라이언트가 db_id 를 잃어버린 채 재전송 (드로우 라이브러리 왕복 등)
        feat = dict(a.feature)
        feat['properties'] = {'node_id': 'node-a', 'aot_type': 'zone'}
        result, err = GeoOverlayManager.save_overlays(
            {'map_uuid': 'm1', 'type': 'zone', 'features': [feat]})
        self.assertIsNone(err)
        self.assertEqual(result['stats']['updated'], 1)
        self.assertEqual(result['stats']['inserted'], 0)   # 중복 INSERT 금지
        self.assertEqual(result['stats']['deleted'], 0)    # 재생성 금지
        self.assertEqual(GeoShape.query.filter_by(
            geo_id='m1', type='zone').count(), 2)          # 그대로 2개

    def test_explicit_allow_empty_still_clears(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        self._two_zones()
        result, err = GeoOverlayManager.save_overlays(
            {'map_uuid': 'm1', 'type': 'zone', 'features': [],
             'allow_empty': True})
        self.assertIsNone(err)
        self.assertEqual(result['stats']['deleted'], 2)
        self.assertEqual(GeoShape.query.filter_by(
            geo_id='m1', type='zone').count(), 0)


class TestCloneDenylist(_Base):
    """I10 — 복제본은 교차참조를 물려받지 않는다(미배치로 시작)."""

    def test_clone_does_not_copy_cross_refs(self):
        src = Output(name='원본밸브', map_overlay_id=42,
                     map_config_id='some-map-uuid')
        src.save()
        dup = clone_model(src, unique_id='dup-uuid-1')
        self.assertIsNotNone(dup)
        self.assertEqual(dup.name, '원본밸브')          # 일반 컬럼은 복사
        self.assertIsNone(dup.map_overlay_id)           # 교차참조는 미복사
        self.assertIsNone(dup.map_config_id)

    def test_explicit_kwarg_still_works(self):
        src = Input(name='원본센서', map_config_id='keep-me')
        src.save()
        dup = clone_model(src, unique_id='dup-uuid-2',
                          map_config_id='explicit-map')
        self.assertEqual(dup.map_config_id, 'explicit-map')


if __name__ == '__main__':
    unittest.main()


class TestExplicitDeletes(_Base):
    """I9 — 지워야 할 것은 지워진다. 단, '누락'이 아니라 '명시'로만.

    2026-08-04 회귀: upsert 전용 전환 후 full-sync 경로의 삭제가 무효화돼
    사용자가 도형을 지우고 저장해도 새로고침하면 되살아났다. 프런트가
    deletedNodeIds 를 보내지 않고 '누락'으로만 표현했기 때문이다.
    """

    def _two_zones(self):
        a = GeoShape(unique_id='za', geo_id='m1', type='zone',
                     feature=_poly(ZONE_RING))
        a.save()
        af = dict(a.feature); af['properties'] = {'node_id': 'node-a'}
        a.feature = af
        b = GeoShape(unique_id='zb', geo_id='m1', type='zone',
                     feature=_poly([[20, 20], [20, 30], [30, 30],
                                    [30, 20], [20, 20]]))
        b.save()
        bf = dict(b.feature); bf['properties'] = {'node_id': 'node-b'}
        b.feature = bf
        db.session.commit()
        return a, b

    def test_explicit_delete_by_node_id_removes_row(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        a, b = self._two_zones()
        feat = dict(a.feature)
        feat['properties'] = {'node_id': 'node-a', 'db_id': a.id}
        result, err = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'zone', 'features': [feat],
            'deletes': ['node-b']})
        self.assertIsNone(err)
        self.assertEqual(result['stats']['deleted'], 1)
        self.assertEqual(GeoShape.query.filter_by(unique_id='zb').count(), 0)
        self.assertEqual(GeoShape.query.filter_by(unique_id='za').count(), 1)

    def test_explicit_delete_by_db_id_removes_row(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        a, b = self._two_zones()
        result, err = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'zone', 'features': [],
            'allow_empty': True, 'deletes': [b.id]})
        self.assertIsNone(err)
        # allow_empty 전체 비우기가 우선 — 둘 다 사라진다(명시 의사)
        self.assertEqual(GeoShape.query.filter_by(
            geo_id='m1', type='zone').count(), 0)

    def test_delete_list_cannot_reach_other_types(self):
        # 스코프 밖 id 를 넘겨도 남의 도형은 못 지운다.
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        a, b = self._two_zones()
        site = GeoShape(unique_id='s1', geo_id='m1', type='site',
                        feature=_poly(ZONE_RING))
        site.save()
        result, err = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'zone', 'features': [],
            'deletes': [site.id]})
        self.assertIsNone(err)
        self.assertEqual(GeoShape.query.filter_by(unique_id='s1').count(), 1)

    def test_upserted_row_is_never_deleted_by_the_same_call(self):
        # 같은 요청에 upsert 와 delete 가 함께 오면 upsert 가 이긴다.
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        a, b = self._two_zones()
        feat = dict(a.feature)
        feat['properties'] = {'node_id': 'node-a', 'db_id': a.id}
        result, err = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'zone', 'features': [feat],
            'deletes': ['node-a']})
        self.assertIsNone(err)
        self.assertEqual(result['stats']['deleted'], 0)
        self.assertEqual(GeoShape.query.filter_by(unique_id='za').count(), 1)


class TestMapCloneIsolation(_Base):
    """지도 복제는 '구조'만 옮기고 원본과 얽히지 않는다.

    2026-08-04 확인된 3결함:
      - device_id 그대로 복사 → 원본 장치가 두 지도에 존재
      - parent_id 미복사 → 계층 평탄화, facility_bay 가 부모를 잃고
        facility_io(parent_id 로 bay 조회)에서 영구히 도달 불가
      - node_id 그대로 복사 → 지도 간 중복, save_delta 의 node_id 폴백이
        첫 일치를 잡아 엉뚱한 지도의 도형을 편집할 수 있음
    """

    def _source_map(self):
        from aot.databases.models import GeoMap
        GeoMap(unique_id='src', name='원본 지도', category='design').save()
        site = GeoShape(unique_id='s-site', geo_id='src', type='site',
                        feature={'type': 'Feature',
                                 'geometry': {'type': 'Polygon',
                                              'coordinates': [ZONE_RING]},
                                 'properties': {'node_id': 'n-site',
                                                'name': '포장'}})
        site.save()
        bay = GeoShape(unique_id='s-bay', geo_id='src', type='facility_bay',
                       parent_id=site.id,
                       feature={'type': 'Feature',
                                'geometry': {'type': 'Polygon',
                                             'coordinates': [ZONE_RING]},
                                'properties': {'node_id': 'n-bay',
                                               'parent_node_id': 'n-site'}})
        bay.save()
        marker = GeoShape(unique_id='s-mk', geo_id='src', type='aot_device',
                          device_id='dev-original', channel_id='0',
                          feature=_point(5, 5, {'node_id': 'n-mk'}))
        marker.save()
        return site, bay, marker

    def test_clone_omits_device_bound_shapes(self):
        from aot.aot_flask.utils.utils_map_config import clone_map_config
        self._source_map()
        cloned = clone_map_config('src', '복제 장치')
        db.session.commit()
        rows = GeoShape.query.filter_by(geo_id=cloned.unique_id).all()
        self.assertEqual({r.type for r in rows}, {'site', 'facility_bay'})
        self.assertTrue(all(r.device_id is None for r in rows))
        # 원본 장치는 여전히 원본 지도에만 있다.
        self.assertEqual(GeoShape.query.filter_by(
            device_id='dev-original').count(), 1)

    def test_clone_remaps_parent_id_to_new_map(self):
        from aot.aot_flask.utils.utils_map_config import clone_map_config
        self._source_map()
        cloned = clone_map_config('src', '복제 장치')
        db.session.commit()
        new_site = GeoShape.query.filter_by(
            geo_id=cloned.unique_id, type='site').first()
        new_bay = GeoShape.query.filter_by(
            geo_id=cloned.unique_id, type='facility_bay').first()
        self.assertIsNotNone(new_bay.parent_id)          # 평탄화 금지
        self.assertEqual(new_bay.parent_id, new_site.id)  # 새 지도의 부모
        # 원본 지도의 행을 가리키지 않는다.
        self.assertNotEqual(new_bay.parent_id,
                            GeoShape.query.filter_by(
                                unique_id='s-site').first().id)

    def test_clone_reissues_node_ids_and_remaps_labels(self):
        from aot.aot_flask.utils.utils_map_config import clone_map_config
        self._source_map()
        cloned = clone_map_config('src', '복제 장치')
        db.session.commit()
        new_site = GeoShape.query.filter_by(
            geo_id=cloned.unique_id, type='site').first()
        new_bay = GeoShape.query.filter_by(
            geo_id=cloned.unique_id, type='facility_bay').first()
        new_site_nid = new_site.feature['properties']['node_id']
        self.assertNotEqual(new_site_nid, 'n-site')       # 재발급
        # 자식의 parent_node_id 가 새 부모를 정확히 가리킨다.
        self.assertEqual(new_bay.feature['properties']['parent_node_id'],
                         new_site_nid)
