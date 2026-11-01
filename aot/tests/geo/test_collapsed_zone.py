# coding=utf-8
"""접힌 zone 판정(`collapsed_zones_by_site`) — 서버 단일 판정.

조건: zone 정확히 1개 · 경계 겹침 >= 0.98 양방향 · 이름 비음/기본/site 와 같음 ·
zone 전용 사용자 데이터 없음. 애매하면 접지 않는다.
"""
import unittest
from types import SimpleNamespace as NS

from aot.utils.geo_hierarchy import collapsed_zone_for_site, collapsed_zones_by_site


def _ring(x0, y0, x1, y1):
    return [[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]


def _shape(i, typ, ring, name='', meta=None, geo_id='m1'):
    return NS(id=i, unique_id='u%d' % i, type=typ, geo_id=geo_id, parent_id=None,
              meta_json=meta,
              feature={'type': 'Feature', 'properties': {'name': name},
                       'geometry': {'type': 'Polygon', 'coordinates': [ring]}})


SITE = _ring(0, 0, 100, 100)


def _run(shapes):
    return collapsed_zones_by_site(shapes, use_cache=False)


class TestCollapsedZone(unittest.TestCase):

    def test_same_area_default_name_collapses(self):
        site, zone = _shape(1, 'site', SITE, '우리 밭'), _shape(2, 'zone', SITE, '구역 1')
        self.assertEqual(_run([site, zone]), {1: zone})
        self.assertIs(collapsed_zone_for_site(site, [site, zone], use_cache=False), zone)

    def test_empty_and_same_as_site_name_collapse(self):
        for zname in ('', '우리 밭'):
            site, zone = _shape(1, 'site', SITE, '우리 밭'), _shape(2, 'zone', SITE, zname)
            self.assertEqual(list(_run([site, zone])), [1], zname)

    def test_custom_name_does_not_collapse(self):
        site, zone = _shape(1, 'site', SITE, '우리 밭'), _shape(2, 'zone', SITE, '하우스 앞')
        self.assertEqual(_run([site, zone]), {})

    def test_two_zones_do_not_collapse(self):
        shapes = [_shape(1, 'site', SITE, 'S'),
                  _shape(2, 'zone', _ring(0, 0, 50, 100)),
                  _shape(3, 'zone', _ring(50, 0, 100, 100))]
        self.assertEqual(_run(shapes), {})

    def test_small_zone_does_not_collapse(self):
        shapes = [_shape(1, 'site', SITE, 'S'), _shape(2, 'zone', _ring(10, 10, 40, 40))]
        self.assertEqual(_run(shapes), {})

    def test_overlap_threshold_both_directions(self):
        # 99% 겹침 → 접힘, 90% → 안 접힘
        self.assertEqual(list(_run([_shape(1, 'site', SITE, 'S'),
                                    _shape(2, 'zone', _ring(0, 0, 100, 99.5))])), [1])
        self.assertEqual(_run([_shape(1, 'site', SITE, 'S'),
                               _shape(2, 'zone', _ring(0, 0, 100, 90))]), {})

    def test_zone_user_data_does_not_collapse(self):
        for meta in ({'photo_url': '/x.jpg'}, {'rep_key': 'a|b'},
                     {'hidden_rows': {'now': ['RH']}}, {'description': '메모'}):
            site, zone = _shape(1, 'site', SITE, 'S'), _shape(2, 'zone', SITE, '', meta)
            self.assertEqual(_run([site, zone]), {}, meta)

    def test_empty_meta_values_still_collapse(self):
        site, zone = _shape(1, 'site', SITE, 'S'), _shape(2, 'zone', SITE, '', {'photo_url': None, 'hidden_rows': {}})
        self.assertEqual(list(_run([site, zone])), [1])

    def test_slightly_larger_zone_still_collapses_and_two_near_copies_do_not(self):
        site = _shape(1, 'site', SITE, 'S')
        big = _shape(2, 'zone', _ring(-0.5, -0.5, 100.5, 100.5))
        self.assertEqual(list(_run([site, big])), [1])
        big2 = _shape(3, 'zone', _ring(0, 0, 100, 100))
        self.assertEqual(_run([site, big, big2]), {})

    def test_non_site_and_missing_are_none(self):
        zone = _shape(2, 'zone', SITE)
        self.assertIsNone(collapsed_zone_for_site(zone, [zone], use_cache=False))
        self.assertIsNone(collapsed_zone_for_site(None))


class TestCollapsedZoneConsumers(unittest.TestCase):
    """판정 결과를 소비하는 쪽(트리·경로·지도 API·필지 요약)이 같은 답을 낸다."""

    def setUp(self):
        from flask import Flask
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoMap, GeoShape
        from aot.utils import geo_hierarchy
        geo_hierarchy._COLLAPSED_CACHE.update(tag=None, map={})
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        try:
            from flask_babel import Babel
            Babel(app)
        except Exception:
            pass
        self.ctx = app.app_context()
        self.ctx.push()
        self.db = db
        db.create_all()
        GeoMap(unique_id='m1', name='김제', category='design').save()

        def _f(ring, name):
            return {'type': 'Feature', 'properties': {'name': name},
                    'geometry': {'type': 'Polygon', 'coordinates': [ring]}}
        self.site = GeoShape(unique_id='site', geo_id='m1', type='site',
                             feature=_f(SITE, '우리 밭'))
        self.zone = GeoShape(unique_id='zone', geo_id='m1', type='zone',
                             feature=_f(_ring(0.1, 0.1, 99.9, 99.9), '구역 1'))
        self.site.save()
        self.zone.save()

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.ctx.pop()

    def test_cached_map_and_invalidation_on_edit(self):
        from aot.utils.geo_hierarchy import collapsed_zone_site_map
        self.assertEqual(collapsed_zone_site_map(), {'zone': 'site'})
        self.zone.meta_json = {'photo_url': '/p.jpg'}
        self.zone.save()
        self.assertEqual(collapsed_zone_site_map(), {})

    def test_path_skips_collapsed_zone(self):
        from aot.aot_flask.geo.device_membership import PlaceIndex
        idx = PlaceIndex()
        self.assertEqual(idx.path(self.zone), '우리 밭')
        self.zone.meta_json = {'rep_key': 'a|b'}
        self.zone.save()
        self.assertEqual(PlaceIndex().path(self.zone), '우리 밭 > 구역 1')

    def test_spatial_tree_flattens(self):
        from aot.ai.services.ai_context_service import AIContextService
        AIContextService.invalidate_spatial_cache()
        tree = AIContextService.get_spatial_hierarchy()
        self.assertEqual(len(tree), 1)
        node = tree[0]
        self.assertEqual(node['unique_id'], 'site')
        self.assertEqual(node['collapsed_zone'], 'zone')
        self.assertEqual([c['unique_id'] for c in node['children']], [])
        # 접힌 zone 에 사진이 붙으면 펼친다.
        self.zone.meta_json = {'photo_url': '/p.jpg'}
        self.zone.save()
        AIContextService.invalidate_spatial_cache()
        node = AIContextService.get_spatial_hierarchy()[0]
        self.assertNotIn('collapsed_zone', node)
        self.assertEqual([c['unique_id'] for c in node['children']], ['zone'])

    def test_geojson_flags(self):
        from aot.aot_flask.routes_geo_shape import _shapes_to_geojson
        z = _shapes_to_geojson('zone', '#0f0', 'm1')['features'][0]['properties']
        s = _shapes_to_geojson('site', '#f00', 'm1')['features'][0]['properties']
        self.assertTrue(z.get('collapsed'))
        self.assertEqual(s.get('collapsed_zone'), 'zone')
        self.assertNotIn('collapsed', s)

    def test_site_summary_flags_collapsed_child(self):
        from unittest import mock
        from aot.aot_flask.geo import site_summary as ss
        with mock.patch.object(ss, '_link_status', return_value={}), \
                mock.patch.object(ss, 'prefetch_last_values', return_value={}), \
                mock.patch.object(ss, '_child_entry', side_effect=lambda sh, ids, *a, **k: {
                    'uuid': sh.unique_id, 'kind': 'zone', 'issues': {'comm_fault': 0},
                    'status': 'ok'}), \
                mock.patch.object(ss, '_rollup_status', return_value='ok'), \
                mock.patch.object(ss, '_plot_counts', return_value={}), \
                mock.patch.object(ss, 'upcoming_schedule', return_value={}), \
                mock.patch.object(ss, '_today_block', return_value={}), \
                mock.patch.object(ss, '_notes_block', return_value={}):
            out = ss._build_summary('site')
        self.assertEqual(out['site']['collapsed_zone'], 'zone')
        self.assertEqual(out['site']['counts']['zones'], 0)
        self.assertTrue(out['children'][0]['collapsed'])

    def test_plot_dict_and_mcp_list_follow_flag(self):
        from datetime import date
        from aot.databases.models import GeoPlot
        from aot.aot_flask.geo import plot_context
        ring = _ring(20, 20, 30, 30)
        GeoPlot(unique_id='plot1', geo_id='m1', subject='콩',
                started_on=date(2026, 6, 15),
                feature={'type': 'Feature', 'properties': {},
                         'geometry': {'type': 'Polygon', 'coordinates': [ring]}}).save()
        row = GeoPlot.query.filter_by(unique_id='plot1').first()
        d = plot_context.to_dict(row)
        self.assertTrue(d.get('zone_collapsed'))
        self.assertEqual(d['zone_kind'], 'zone')          # 사실 왜곡 금지
        self.assertEqual(d['site_uuid'], 'site')
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S._plot_summary(d)
        self.assertNotIn('zone_name', out)
        self.assertEqual(out.get('zone_kind'), 'zone')
        # 사진이 붙으면 펼친다.
        self.zone.meta_json = {'photo_url': '/p.jpg'}
        self.zone.save()
        d2 = plot_context.to_dict(row)
        self.assertNotIn('zone_collapsed', d2)
        self.assertIn('zone_name', S._plot_summary(d2))


if __name__ == '__main__':
    unittest.main()


class TestSiteDirectPlots(unittest.TestCase):
    """필지 모달이 직속 구획을 낸다 — zone 없는 필지, 접힌 zone, zone 2개 이상."""

    def setUp(self):
        from flask import Flask
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoMap
        from aot.utils import geo_hierarchy
        geo_hierarchy._COLLAPSED_CACHE.update(tag=None, map={})
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        self.db = db
        db.create_all()
        GeoMap(unique_id='m1', name='김제', category='design').save()

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.ctx.pop()

    @staticmethod
    def _feat(ring, name=''):
        return {'type': 'Feature', 'properties': {'name': name},
                'geometry': {'type': 'Polygon', 'coordinates': [ring]}}

    def _shape(self, uid, typ, ring, name=''):
        from aot.databases.models import GeoShape
        GeoShape(unique_id=uid, geo_id='m1', type=typ,
                 feature=self._feat(ring, name)).save()

    def _plot(self, uid, ring, subject):
        from datetime import date
        from aot.databases.models import GeoPlot
        GeoPlot(unique_id=uid, geo_id='m1', subject=subject,
                started_on=date(2026, 6, 15), feature=self._feat(ring)).save()

    def _plots(self, site_uuid='site'):
        from aot.aot_flask.geo import site_summary as ss
        from aot.databases.models import GeoShape
        site = GeoShape.query.filter_by(unique_id=site_uuid).first()
        from aot.utils.geo_hierarchy import collapsed_zone_site_map
        cz = next((z for z, s in collapsed_zone_site_map().items()
                   if s == site_uuid), None)
        return sorted(p['uuid'] for p in ss._direct_plots(site, cz))

    def test_zoneless_site_lists_its_plots(self):
        self._shape('site', 'site', SITE, '우리 밭')
        self._plot('p1', _ring(10, 10, 20, 20), '콩')
        self._plot('p2', _ring(30, 30, 40, 40), '깨')
        self.assertEqual(self._plots(), ['p1', 'p2'])

    def test_collapsed_zone_plots_listed_by_site(self):
        self._shape('site', 'site', SITE, '우리 밭')
        self._shape('zone', 'zone', _ring(0.1, 0.1, 99.9, 99.9), '구역 1')
        self._plot('p1', _ring(10, 10, 20, 20), '콩')
        self.assertEqual(self._plots(), ['p1'])

    def test_multi_zone_site_does_not_repeat_zone_plots(self):
        self._shape('site', 'site', SITE, '우리 밭')
        self._shape('za', 'zone', _ring(0, 0, 50, 100), 'A')
        self._shape('zb', 'zone', _ring(50, 0, 100, 100), 'B')
        self._plot('pa', _ring(10, 10, 20, 20), '콩')
        self._plot('pb', _ring(60, 10, 70, 20), '깨')
        self.assertEqual(self._plots(), [])
        # zone 어디에도 안 든 구획은 필지 직속이다.
        self._shape('site2', 'site', _ring(200, 200, 300, 300), '둘째')
        self._plot('pc', _ring(210, 210, 220, 220), '팥')
        self.assertEqual(self._plots('site2'), ['pc'])

    def test_summary_payload_has_plots_key(self):
        from unittest import mock
        from aot.aot_flask.geo import site_summary as ss
        self._shape('site', 'site', SITE, '우리 밭')
        self._plot('p1', _ring(10, 10, 20, 20), '콩')
        with mock.patch.object(ss, '_link_status', return_value={}), \
                mock.patch.object(ss, 'prefetch_last_values', return_value={}), \
                mock.patch.object(ss, '_rollup_status', return_value='ok'), \
                mock.patch.object(ss, 'upcoming_schedule', return_value={}), \
                mock.patch.object(ss, '_today_block', return_value={}), \
                mock.patch.object(ss, '_notes_block', return_value={}):
            out = ss._build_summary('site')
        self.assertEqual([p['uuid'] for p in out['plots']], ['p1'])
        self.assertEqual(out['plots'][0]['name'], '콩')
