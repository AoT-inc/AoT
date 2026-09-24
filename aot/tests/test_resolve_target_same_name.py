# coding=utf-8
"""이름이 같은 대상 — 조용히 하나를 고르지 않는다.

벤치(26-09-23):

- '육묘장' 은 지도 두 장(영양·그린)의 부지 둘과, 영양 부지 **안의** 같은 이름
  시설 하나에 걸린다. 리졸버는 그중 시설을 골라 "exactly one entity" 라고
  답했고, 모델 열두 번 중 한 번만 이름이 겹친다는 것을 짚었다.
- 같은 이유로 resolve_target → 구역 요약 경로는 **시설**(센서 7개)을, 이름 없이
  부른 구역 요약은 **부지**(센서 8개)를 봐서 센서 하나가 빠졌다. 같은 이름이
  안팎으로 겹치면 이름은 바깥(부지) 전체를 가리킨다 — 구역 요약·공간 트리가
  나열하는 그 도형이다.
- 'v111' 은 출력장치가 둘이다(하나는 지도에 있고 하나는 없다).
"""
import os
import tempfile
import unittest


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]]}


def _point(x, y):
    return {'type': 'Point', 'coordinates': [x, y]}


class TestSameNameTargets(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import GeoMap, GeoShape, Output

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'same.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        db.session.add(GeoMap(unique_id='map-a', name='영양'))
        db.session.add(GeoMap(unique_id='map-b', name='그린'))

        def shape(uid, geo, typ, name, geom, device_id=None):
            db.session.add(GeoShape(unique_id=uid, geo_id=geo, type=typ, device_id=device_id,
                                    feature={'type': 'Feature', 'properties': {'name': name},
                                             'geometry': geom}))

        # 영양: 부지 '육묘장' 안에 같은 이름의 시설 — 한 곳이다.
        # 운영 DB 처럼 시설이 먼저 저장돼 있다(id 순서가 고르는 쪽을 정했다).
        shape('fac-a', 'map-a', 'facility', '육묘장', _square(0.002, 0.002, 0.003))
        shape('site-a', 'map-a', 'site', '육묘장', _square(0.0, 0.0, 0.01))
        # 그린: 다른 곳의 부지 '육묘장'.
        shape('site-b', 'map-b', 'site', '육묘장', _square(1.0, 1.0, 0.01))
        # 한 지도 안에서만 겹치는 이름(안팎) — 모호하지 않다.
        shape('fac-c', 'map-a', 'facility', '묘포', _square(0.102, 0.102, 0.003))
        shape('site-c', 'map-a', 'site', '묘포', _square(0.1, 0.1, 0.01))
        # 이름이 하나뿐인 구역.
        shape('zone-1', 'map-a', 'zone', '3-2', _square(0.2, 0.2, 0.01))
        # v111: 지도에 놓인 출력(마커+폴리곤) + 지도에 없는 같은 이름의 출력.
        db.session.add(Output(unique_id='out-mapped', name='v111', output_type='virtual_on_off_single'))
        db.session.add(Output(unique_id='out-loose', name='v111', output_type='virtual_on_off_single'))
        shape('mk-1', 'map-a', 'aot_device', 'v111', _point(0.205, 0.205), device_id='out-mapped')
        shape('pg-1', 'map-a', 'device', 'v111', _square(0.204, 0.204, 0.001), device_id='out-mapped')
        # 마커+폴리곤이 하나뿐인 장치 — 한 장치다.
        db.session.add(Output(unique_id='out-v121', name='v121', output_type='virtual_on_off_single'))
        shape('mk-2', 'map-a', 'aot_device', 'v121', _point(0.206, 0.206), device_id='out-v121')
        shape('pg-2', 'map-a', 'device', 'v121', _square(0.2055, 0.2055, 0.001), device_id='out-v121')
        # 한 지도 안, 서로 다른 부지에 같은 이름 구역 '1' (실측: 산양삼 구례·진안).
        shape('site-g', 'map-a', 'site', '구례', _square(0.3, 0.3, 0.01))
        shape('site-j', 'map-a', 'site', '진안', _square(0.4, 0.4, 0.01))
        shape('z1-g', 'map-a', 'zone', '1', _square(0.302, 0.302, 0.002))
        shape('z1-j', 'map-a', 'zone', '1', _square(0.402, 0.402, 0.002))
        # 'twin': 입력과 출력이 같은 이름, 둘 다 지도에 없고 탭 행도 없다 —
        # 구역·지도·탭 단서가 똑같다.
        from aot.databases.models import Input
        db.session.add(Input(unique_id='in-twin', name='twin', device='TEST_TWIN',
                             tab_id='tab-gone'))
        db.session.add(Output(unique_id='out-twin', name='twin',
                              output_type='virtual_on_off_single', tab_id='tab-gone'))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()

    @property
    def S(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    # ── F4: 서로 다른 곳이면 고르지 않는다 ────────────────────────────────
    def test_two_places_with_one_name_ask_instead_of_picking(self):
        out = self.S.resolve_target_tool('육묘장')
        self.assertEqual(out['status'], 'needs_disambiguation', out)
        self.assertEqual(out.get('error'), 'ambiguous_name')
        wheres = sorted(c['where'] for c in out['candidates'])
        self.assertEqual(len(wheres), 2, out['candidates'])
        self.assertTrue(any('영양' in w for w in wheres) and any('그린' in w for w in wheres))
        self.assertTrue(any('ask the user' in r for r in out['_reading']))

    def test_write_resolver_does_not_coin_flip(self):
        """쓰기 도구가 함께 쓰는 리졸버 — 모호하면 아무것도 고르지 않는다."""
        self.assertIsNone(self.S._resolve_note_target('육묘장')[0])

    def test_the_map_name_disambiguates(self):
        self.assertEqual(self.S._resolve_note_target('그린 육묘장')[0], 'site-b')
        self.assertEqual(self.S._resolve_note_target('영양 육묘장')[0], 'site-a')

    def test_each_candidate_carries_a_name_that_resolves(self):
        out = self.S.resolve_target_tool('육묘장')
        for c in out['candidates']:
            self.assertEqual(self.S._resolve_note_target(c['use_name'])[0], c['target_id'])

    def test_two_devices_with_one_name_ask(self):
        out = self.S.resolve_target_tool('v111')
        self.assertEqual(out['status'], 'needs_disambiguation', out)
        self.assertEqual(len(out['candidates']), 2, out['candidates'])
        self.assertIsNone(self.S._resolve_note_target('v111')[0])

    def test_write_tool_refusal_lists_the_candidates(self):
        out = self.S.add_schedule_tool(date='2026-10-01', content='점검', target_name='육묘장')
        self.assertEqual(out.get('status'), 'needs_disambiguation', out)
        self.assertEqual(len(out.get('candidates') or []), 2, out)

    # ── 모호하지 않은 것은 종전대로 ──────────────────────────────────────
    def test_marker_and_polygon_of_one_device_are_one_thing(self):
        out = self.S.resolve_target_tool('v121')
        self.assertEqual(out['status'], 'success', out)

    def test_a_unique_zone_still_resolves(self):
        out = self.S.resolve_target_tool('3-2')
        self.assertEqual(out['status'], 'success')
        self.assertEqual(out['target_id'], 'zone-1')
        self.assertNotIn('candidates', out)

    # ── F3: 같은 이름이 안팎으로 겹치면 바깥 전체 ────────────────────────
    def test_nested_same_name_is_one_place_and_means_the_outer_one(self):
        out = self.S.resolve_target_tool('묘포')
        self.assertEqual(out['status'], 'success', out)
        self.assertEqual(out['target_id'], 'site-c')

    def test_same_map_duplicates_get_a_site_qualified_name(self):
        out = self.S.resolve_target_tool('1')
        self.assertEqual(out['status'], 'needs_disambiguation', out)
        names = sorted(c.get('use_name') or '' for c in out['candidates'])
        self.assertEqual(names, ['구례 1', '진안 1'])
        self.assertEqual(self.S._resolve_note_target('진안 1')[0], 'z1-j')
        self.assertEqual(self.S._resolve_note_target('구례 1')[0], 'z1-g')

    def test_a_translated_alias_does_not_undo_the_refusal(self):
        """이름이 여럿에 걸려 None 이 나오면, 번역 별칭 재시도가 또 다른 하나를
        조용히 고르면 안 된다(실측: '육묘장' → 일본어 지도의 '育苗場')."""
        from unittest import mock
        from aot.tools import providers
        real_get = providers.get

        def fake_get(name):
            if name == 'reverse_lookup':
                return lambda t: '3-2' if t == '육묘장' else None
            return real_get(name)

        with mock.patch.object(providers, 'get', side_effect=fake_get):
            self.assertIsNone(self.S._resolve_note_target('육묘장')[0])

    def test_a_read_over_an_ambiguous_name_says_so(self):
        ids, scope = self.S._scope_for_target('육묘장')
        self.assertEqual(scope['target_type'], 'ambiguous')
        self.assertIn('site-a', ids)
        self.assertIn('site-b', ids)
        self.assertIn('ALL of them', self.S._ambiguous_scope_reading(scope))
        self.assertIn('never by id', self.S._ambiguous_scope_reading(scope))

    # ── 되물을 때 id 를 보이지 않게(26-09-23 재측정 P6) ─────────────────
    def test_every_place_candidate_has_a_where_and_the_no_id_rule(self):
        from aot.tools import mcp_safety_gate as gate
        for name in ('육묘장', 'v111', '1'):
            with self.subTest(name=name):
                out = self.S.resolve_target_tool(name)
                self.assertEqual(out['status'], 'needs_disambiguation', out)
                for c in out['candidates']:
                    self.assertTrue(c.get('where'), c)
                # 실행층이 붙인다 — 읽기 도구라도 되묻는 응답이면.
                out = gate.annotate_write_outcome('resolve_target', 'executed', out)
                self.assertIn(gate.CANDIDATES_NO_IDS, out['_reading'])
                self.assertNotIn('performed', out)

    def test_same_name_devices_are_told_apart_without_ids(self):
        """get_device_detail 의 후보가 id 로만 갈리던 것(lat_14)."""
        out = self.S.get_device_detail(device_id='v111')
        self.assertTrue(out.get('needs_disambiguation'), out)
        wheres = [c.get('where') for c in out['candidates']]
        self.assertTrue(all(wheres), out['candidates'])
        self.assertEqual(len(set(wheres)), 2, wheres)
        self.assertTrue(any('영양' in w for w in wheres), wheres)
        self.assertTrue(any('not on a map' in w for w in wheres), wheres)

    def test_device_where_is_stable_and_splits_identical_clues(self):
        """리뷰 5 — 도형 순서와 무관, 단서가 같으면 종류로 가르고, 번역 문구 없음."""
        first = self.S.get_device_detail(device_id='v111')['candidates']
        again = self.S.get_device_detail(device_id='v111')['candidates']
        self.assertEqual([c['where'] for c in first], [c['where'] for c in again])
        mapped = [c['where'] for c in first if 'on map' in c['where']]
        # 도형 둘(마커+폴리곤)이 같은 지도라 지도 이름은 한 번만.
        self.assertEqual(mapped, ['zone 3-2, on map 영양'], first)

        out = self.S.get_device_detail(device_id='twin')
        self.assertTrue(out.get('needs_disambiguation'), out)
        wheres = {c['kind']: c['where'] for c in out['candidates']}
        self.assertEqual(len(set(wheres.values())), 2, wheres)
        self.assertIn('input TEST_TWIN', wheres['input'])
        self.assertIn('output virtual_on_off_single', wheres['output'])
        for w in wheres.values():
            self.assertTrue(w.startswith('not on a map'), w)
            self.assertNotIn('tab', w)
