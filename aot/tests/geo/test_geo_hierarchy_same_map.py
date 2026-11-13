# coding=utf-8
"""공간 계층의 부모는 **같은 지도** 안에서만 고른다.

배경(2026-10-08, 외부 MCP 클라이언트 Sonnet 보고): 로컬 서버에서 김제 지도의
대지 '3포장' 이 `get_spatial_tree` 최상위에 없었다. 시험용 지도(New Design
Map)의 대지 '농장' 이 같은 자리를 덮고 있었고, 부모 판정
(`build_geo_parent_map`)이 지도를 가리지 않고 후보를 골라 3포장을 그 아래로
넣었다. 3-1·3-2 도 그 지도의 '1구역'·'2구역' 아래로 들어가, `resolve_target`
의 children 에 다른 지도의 구역이 섞였다(지도를 넘는 부모 5건).

지도들은 같은 좌표계를 쓰므로 다른 지도의 도형도 기하로는 "감싼다" — 그래서
기하만 보면 이 오류는 보이지 않는다. 장치 소속(`device_membership`)은 처음부터
지도 단위였다.

이 파일이 고정하는 것:
  1. 다른 지도의 대지가 감싸도 부모가 되지 않는다(도형·구획 둘 다).
  2. 옛 판정이 캐시에 남긴 지도를 넘는 부모는 TTL 을 기다리지 않고 버린다.
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


# 다른 지도의 큰 대지 — 아래 둘을 기하로 통째로 감싼다.
OTHER_SITE_RING = [[-50, -50], [-50, 150], [150, 150], [150, -50], [-50, -50]]
# 이 지도의 대지와 그 안의 구역.
SITE_RING = [[0, 0], [0, 100], [100, 100], [100, 0], [0, 0]]
ZONE_RING = [[10, 10], [10, 40], [40, 40], [40, 10], [10, 10]]
# 구역 안의 구획.
PLOT_RING = [[15, 15], [15, 25], [25, 25], [25, 15], [15, 15]]


class _Base(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        GeoMap(unique_id='m1', name='김제', category='design').save()
        GeoMap(unique_id='m2', name='New Design Map', category='design').save()
        self.other = GeoShape(unique_id='other-site', geo_id='m2', type='site',
                              feature=_poly(OTHER_SITE_RING))
        self.other.save()
        self.site = GeoShape(unique_id='site', geo_id='m1', type='site',
                             feature=_poly(SITE_RING))
        self.site.save()
        self.zone = GeoShape(unique_id='zone', geo_id='m1', type='zone',
                             feature=_poly(ZONE_RING))
        self.zone.save()
        self.shapes = [self.other, self.site, self.zone]

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


class TestShapeParentStaysOnItsMap(_Base):

    def test_other_map_site_is_not_a_parent(self):
        from aot.utils.geo_hierarchy import build_geo_parent_map
        pm = build_geo_parent_map(self.shapes, use_cache=False)
        # 예전 판정: site 의 부모가 other-site(다른 지도) 였다.
        self.assertIsNone(pm[self.site.id])
        self.assertEqual(pm[self.zone.id], self.site.id)
        self.assertIsNone(pm[self.other.id])

    def test_cached_cross_map_parent_is_discarded(self):
        """옛 판정이 캐시에 남긴 값 — site 의 부모가 other-site 라고 적혀
        있어도, 읽을 때 버리고 기하로 다시 계산해야 한다."""
        from aot.space import containment_cache as cc
        from aot.utils.geo_hierarchy import build_geo_parent_map
        cc.store([
            (cc.KIND_SHAPE, 'other-site', None, 'm2'),
            (cc.KIND_SHAPE, 'site', 'other-site', 'm1'),   # 지도를 넘는 옛 값
            (cc.KIND_SHAPE, 'zone', 'site', 'm1'),
        ])
        pm = build_geo_parent_map(self.shapes, use_cache=True)
        self.assertIsNone(pm[self.site.id])
        self.assertEqual(pm[self.zone.id], self.site.id)


class TestPlotParentStaysOnItsMap(_Base):

    def _plot(self):
        from datetime import date
        from aot.databases.models import GeoPlot
        p = GeoPlot(unique_id='plot1', geo_id='m1', subject='콩',
                    started_on=date(2026, 6, 15), feature=_poly(PLOT_RING))
        p.save()
        return p

    def test_plot_inside_its_own_zone_not_other_maps_site(self):
        from aot.utils.geo_hierarchy import _plot_ids_inside
        self._plot()
        self.assertEqual(_plot_ids_inside(['zone'], use_cache=False), ['plot1'])
        # 다른 지도의 대지로 물으면 나오지 않는다(그 지도의 구획이 아니다).
        self.assertEqual(_plot_ids_inside(['other-site'], use_cache=False), [])

    def test_plot_outside_its_maps_places_is_not_claimed_by_other_map(self):
        """이 지도의 대지 밖에 있는 구획 — 감싸는 것은 다른 지도의 대지뿐이다.
        예전에는 그 대지가 부모가 됐고, 부모가 없다고 판정해도 "물어본 도형
        안에 있으면 넣는다" 는 보조 분기가 다시 넣었다."""
        from datetime import date
        from aot.databases.models import GeoPlot
        from aot.utils.geo_hierarchy import _plot_ids_inside
        GeoPlot(unique_id='plot-out', geo_id='m1', subject='팥',
                started_on=date(2026, 6, 15),
                feature=_poly([[120, 120], [120, 130], [130, 130],
                               [130, 120], [120, 120]])).save()
        self.assertEqual(_plot_ids_inside(['other-site'], use_cache=False), [])

    def test_cached_cross_map_plot_parent_is_discarded(self):
        from aot.space import containment_cache as cc
        from aot.utils.geo_hierarchy import _plot_ids_inside
        self._plot()
        cc.store([(cc.KIND_PLANTING, 'plot1', 'other-site', 'm1')])
        self.assertEqual(_plot_ids_inside(['zone'], use_cache=True), ['plot1'])


if __name__ == '__main__':
    unittest.main()
