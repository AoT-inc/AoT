# coding=utf-8
"""겹치는 zone 사이 소속 판정 — 동점 규칙이 하나로 통일돼 있는지 고정한다.

배경(2026-09-25, 매뉴얼 지도 챕터 작성 중 발견): 로컬 서버 김제 site '3포장'은
zone 들의 면적 합(47,007 m²)이 site 면적(31,446 m²)을 넘는다 — zone 끼리도
겹친다는 뜻이다. 그런데 소속을 정하는 경로가 이 레포에 셋 있었고, 겹친 후보
사이의 동점 규칙이 서로 달랐다:

  · `aot/utils/geo_hierarchy.py` `build_geo_parent_map()` — **가장 작은 면적**
    이 이긴다(가장 구체적인 부모). site/zone 을 가리지 않고 면적만 봤다.
  · `aot/aot_flask/geo/device_membership.py` `_best_container()` — zone 이
    site 를 이기는 것까지는 같았지만, zone 끼리 겹치면 `load_containers()`
    가 돌려준 순서에서 **먼저 나온 쪽**이 이겼다(면적과 무관) — 그 쿼리에
    `order_by` 가 없어 순서는 DB 반환 순서(대개 생성=PK 순서)일 뿐 기하가
    아니었다.
  · `aot/aot_flask/geo/geo_overlays.py` `find_containing_shape()` — 문서에는
    "smallest (most specific)" 라고 적혀 있었지만 실제 구현은
    `device_membership` 과 같은 "먼저 나온 쪽" 이었다(현재 호출자는 없다).

`project_geo_containment_criteria` 메모는 이 동점 규칙 차이를 "정상 중첩에서는
같은 답이라 실측 차이 0" 이라며 일부러 안 건드렸다고 적어 뒀다 — 그 실측은
site-vs-zone 만 봤고 **zone-vs-zone 중첩은 애초에 없었다**. 김제 3포장처럼
zone 끼리 겹치면 이 전제가 깨진다.

2026-09-25 결정: 세 곳을 `aot/utils/geo_hierarchy.py` `pick_smallest_container()`
하나로 통일했다(가장 작은 면적, site/zone 구분 없이 — geo_hierarchy 가 이미
쓰던 규칙 그대로). zone 끼리 겹치지 않는 한(대부분의 지도) 결과는 이전과
동일하다. 이 파일은 (1) 겹치는 zone 에서 세 경로가 **이제 같은 답**을 내고
(2) `_best_container` 의 답이 더 이상 `containers` 리스트 순서에 좌우되지
않는다는 것을 고정한다 — 회귀하면(누군가 순서 기반 지름길로 되돌리면) 여기서
잡힌다.
"""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    try:
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


# 대지 — 두 zone 을 모두 감싸는 큰 사각형. area = 120*120 = 14400.
SITE_RING = [[-10, -10], [-10, 110], [110, 110], [110, -10], [-10, -10]]
# zone-big — 먼저 만든다(= 더 작은 PK). area = 100*60 = 6000.
ZONE_BIG_RING = [[0, 0], [0, 60], [100, 60], [100, 0], [0, 0]]
# zone-small — 나중에 만든다(= 더 큰 PK). area = 40*100 = 4000.
# zone-big 과 겹친다: x∈[0,40] · y∈[0,60] 구간이 두 zone 모두의 안이다.
ZONE_SMALL_RING = [[0, 0], [0, 100], [40, 100], [40, 0], [0, 0]]
# 두 zone 이 겹치는 안쪽의 한 점 — 겹침 자체는 실제로 존재해야 이 테스트가
# 의미가 있다(대지 밖·둘 다 밖인 점을 고르면 아무것도 증명하지 못한다).
OVERLAP_POINT = (20, 30)


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

    def _place_site_and_overlapping_zones(self):
        """site 하나 + 서로 겹치는 zone 둘. zone-big 을 zone-small 보다 먼저
        저장한다(= 더 작은 PK) — 순서 기반 옛 규칙이었다면 zone-big 이 이겼을
        배치를 그대로 써서, 지금은 면적으로만 zone-small 이 이기는지 본다."""
        site = GeoShape(unique_id='site1', geo_id='m1', type='site',
                        feature=_poly(SITE_RING))
        site.save()
        zone_big = GeoShape(unique_id='zone-big', geo_id='m1', type='zone',
                            feature=_poly(ZONE_BIG_RING))
        zone_big.save()
        zone_small = GeoShape(unique_id='zone-small', geo_id='m1',
                              type='zone', feature=_poly(ZONE_SMALL_RING))
        zone_small.save()
        return site, zone_big, zone_small

    def _assert_overlap_is_real(self, zone_big, zone_small):
        """전제 점검: 두 zone 이 실제로 겹치고, 고른 점이 그 겹친 안에 있다."""
        from shapely.geometry import Point, shape as shapely_shape

        big_poly = shapely_shape(zone_big.feature['geometry'])
        small_poly = shapely_shape(zone_small.feature['geometry'])
        self.assertGreater(big_poly.intersection(small_poly).area, 0,
                           'zone-big·zone-small 이 겹치지 않으면 이 테스트는'
                           ' 아무것도 보여주지 못합니다')
        p = Point(*OVERLAP_POINT)
        self.assertTrue(big_poly.contains(p))
        self.assertTrue(small_poly.contains(p))
        # zone-small 이 zone-big 보다 작아야 "가장 작은 면적" 규칙이 의미가
        # 있다 — 우연히 같은 면적이면 동점 규칙 자체가 시험되지 않는다.
        self.assertLess(small_poly.area, big_poly.area)


class TestDeviceMarkerZoneAgreesWithHierarchy(_Base):
    """장치 마커 하나 — `zone_for_device` 와 `build_geo_parent_map` 이 같은
    zone(더 작은 쪽)을 답해야 한다."""

    def test_marker_in_overlap_resolves_to_smallest_zone_on_both_paths(self):
        from aot.aot_flask.geo.device_membership import zone_for_device
        from aot.utils.geo_hierarchy import build_geo_parent_map

        site, zone_big, zone_small = self._place_site_and_overlapping_zones()
        self._assert_overlap_is_real(zone_big, zone_small)
        marker = GeoShape(unique_id='mk1', geo_id='m1', type='aot_device',
                          device_id='dev-1', channel_id='0',
                          feature=_point(*OVERLAP_POINT))
        marker.save()

        membership_zone = zone_for_device('dev-1', 'm1')
        self.assertIsNotNone(membership_zone)

        all_shapes = [site, zone_big, zone_small, marker]
        parent_map = build_geo_parent_map(all_shapes, use_cache=False)
        parent_id = parent_map.get(marker.id)
        self.assertIsNotNone(parent_id)
        hierarchy_zone_uuid = next(
            s.unique_id for s in all_shapes if s.id == parent_id)

        # 핵심: 겹치는 zone 이라도 두 경로가 같은 답을 내야 한다 — 그리고
        # 그 답은 더 작은(더 구체적인) zone-small 이어야 한다. zone-big 이
        # 나오면 device_membership 이 여전히 순서(먼저 만든 쪽)로 고르고
        # 있다는 뜻이고, 둘이 서로 다른 값이 나오면 통일이 깨진 것이다.
        self.assertEqual(membership_zone.unique_id, 'zone-small')
        self.assertEqual(hierarchy_zone_uuid, 'zone-small')
        self.assertEqual(membership_zone.unique_id, hierarchy_zone_uuid)


class TestPlotZoneAttributionAgreesWithHierarchy(_Base):
    """구획(GeoPlot) 폴리곤 — `zone_for_plot`(=`container_for_geometry`) 와
    `build_geo_parent_map` 이 같은 zone 을 답해야 한다. `get_zone_sensor_summary`
    ·plot_context 가 실제로 쓰는 것은 device_membership 쪽이다."""

    def test_plot_in_overlap_resolves_to_smallest_zone_on_both_paths(self):
        from aot.aot_flask.geo.device_membership import container_for_geometry
        from aot.utils.geo_hierarchy import build_geo_parent_map

        site, zone_big, zone_small = self._place_site_and_overlapping_zones()
        self._assert_overlap_is_real(zone_big, zone_small)

        # 구획은 겹친 구간 안의 작은 사각형이라고 두면 된다 — 대표점만
        # 문제이므로 정확한 크기는 중요하지 않다.
        plot_geom = {'type': 'Polygon',
                    'coordinates': [[[15, 25], [15, 35], [25, 35],
                                     [25, 25], [15, 25]]]}

        membership_zone = container_for_geometry('m1', plot_geom)
        self.assertIsNotNone(membership_zone)
        self.assertEqual(membership_zone.unique_id, 'zone-small')

        # geo_hierarchy 쪽에는 구획을 표현할 GeoShape 행이 없으므로(GeoPlot 은
        # GeoShape 가 아니다), 같은 대표점을 갖는 'aot_device' 종류의 자리
        # 표시 행으로 같은 판정을 재현한다 — containment_point() 가 기하
        # 종류와 무관하게 같은 기준(대표점)을 쓰므로 결과는 동일하다.
        from aot.utils.geo_hierarchy import containment_point
        from shapely.geometry import shape as shapely_shape

        pt = containment_point(shapely_shape(plot_geom))
        stand_in = GeoShape(unique_id='plot-stand-in', geo_id='m1',
                            type='aot_device',
                            feature=_point(pt.x, pt.y))
        stand_in.save()
        all_shapes = [site, zone_big, zone_small, stand_in]
        parent_map = build_geo_parent_map(all_shapes, use_cache=False)
        parent_id = parent_map.get(stand_in.id)
        hierarchy_zone_uuid = next(
            s.unique_id for s in all_shapes if s.id == parent_id)
        self.assertEqual(hierarchy_zone_uuid, 'zone-small')

        self.assertEqual(membership_zone.unique_id, hierarchy_zone_uuid)


class TestBestContainerTiebreakIsOrderIndependent(unittest.TestCase):
    """DB 를 거치지 않는 순수 로직 확인 — `_best_container` 가 이제
    `containers` 리스트 순서가 아니라 면적으로만 고른다는 것을 직접 본다.
    (통일 전에는 이 테스트가 반대로 실패했다 — 순서를 뒤집으면 답도 뒤집혔다.)
    """

    def test_order_of_same_kind_candidates_no_longer_flips_the_answer(self):
        from shapely.geometry import shape as shapely_shape

        from aot.aot_flask.geo.device_membership import _best_container

        big = shapely_shape(_poly(ZONE_BIG_RING)['geometry'])      # area 6000
        small = shapely_shape(_poly(ZONE_SMALL_RING)['geometry'])  # area 4000
        self.assertLess(small.area, big.area)

        class _Shape:
            def __init__(self, unique_id):
                self.unique_id = unique_id

        zone_big = _Shape('zone-big')
        zone_small = _Shape('zone-small')

        winner_when_big_first = _best_container(
            OVERLAP_POINT,
            [(zone_big, 'zone', big), (zone_small, 'zone', small)])
        winner_when_small_first = _best_container(
            OVERLAP_POINT,
            [(zone_small, 'zone', small), (zone_big, 'zone', big)])

        # 리스트 순서를 뒤집어도 답은 똑같이 더 작은 zone-small 이어야 한다.
        self.assertEqual(winner_when_big_first.unique_id, 'zone-small')
        self.assertEqual(winner_when_small_first.unique_id, 'zone-small')
        self.assertEqual(winner_when_big_first.unique_id,
                         winner_when_small_first.unique_id)


if __name__ == '__main__':
    unittest.main()
