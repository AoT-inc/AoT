# coding=utf-8
"""장소 소속 정본(device_membership.PlaceIndex · place_members)과 그 배선.

배경(2026-10-08): 같은 "3포장" 을 물어도 읽기 도구마다 다른 집합이 나왔다.
`list_plots(zone_id=3포장)` 2건 · `resolve_target` 구획 14건 ·
`get_zone_sensor_summary` 장치 20여 개 · `search_devices` 는 소속을 3-1/3-2 로만.
소속 규칙이 다섯 벌이었다(.local/reports/place-membership-unification-20261008.md).

규칙(사용자 결정 2026-10-08):
  · 장소를 물으면 하위 장소의 내용까지 포함한다.
  · 장치 소속은 마커뿐 아니라 바인딩까지 본다.
  · `aot/tools/data_tools` 는 소속을 정본으로만 묻는다.
"""
import ast
import os
import unittest
from datetime import date

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_TOOLS = os.path.join(_HERE, '..', 'tools', 'data_tools')


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


def _poly(coords, name=None, **props):
    p = dict(props)
    if name:
        p['name'] = name
    return {'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [coords]},
            'properties': p}


def _point(x, y):
    return {'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [x, y]},
            'properties': {}}


SITE = [[0, 0], [0, 100], [100, 100], [100, 0], [0, 0]]
ZONE_A = [[10, 10], [10, 40], [40, 40], [40, 10], [10, 10]]
ZONE_B = [[60, 10], [60, 40], [90, 40], [90, 10], [60, 10]]
# 구역 A 안의 장치 영역 폴리곤(밸브가 맡은 범위) — 장소가 아니다.
VALVE_AREA = [[12, 12], [12, 20], [20, 20], [20, 12], [12, 12]]
PLOT_IN_A = [[25, 25], [25, 35], [35, 35], [35, 25], [25, 25]]


class _Base(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        GeoMap(unique_id='m1', name='김제', category='design').save()
        GeoShape(unique_id='site', geo_id='m1', type='site',
                 feature=_poly(SITE, '3포장')).save()
        GeoShape(unique_id='zone-a', geo_id='m1', type='zone',
                 feature=_poly(ZONE_A, '3-1')).save()
        GeoShape(unique_id='zone-b', geo_id='m1', type='zone',
                 feature=_poly(ZONE_B, '3-2')).save()
        # 마커로 놓인 센서(구역 A 안).
        bound_shape(unique_id='mk-sensor', geo_id='m1', type='aot_device',
                 device_id='sensor-1', channel_id='0',
                 feature=_point(30, 15)).save()
        # 바인딩으로만 매인 밸브 — 마커가 없다(실측상 흔한 경우).
        GeoShape(unique_id='valve-area', geo_id='m1', type='device',
                 feature=_poly(VALVE_AREA, 'v331')).save()
        from aot.databases.models import GeoBinding
        GeoBinding(spatial_kind='shape', spatial_id='valve-area', role='area',
                   device_kind='output', device_id='valve-1').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


class TestPlaceIndex(_Base):

    def test_path_is_outer_to_inner(self):
        from aot.space.device_membership import PlaceIndex
        idx = PlaceIndex()
        self.assertEqual(idx.path(idx.by_uid['zone-a']), '3포장 > 3-1')
        self.assertTrue(idx.within('zone-a', 'site'))
        self.assertFalse(idx.within('zone-a', 'zone-b'))

    def test_device_paths_use_markers_and_bindings(self):
        """마커만 보던 규칙에서는 바인딩으로만 매인 밸브가 어디에도 없었다."""
        from aot.space.device_membership import PlaceIndex
        paths = PlaceIndex().device_paths(['sensor-1', 'valve-1', 'nowhere'])
        self.assertEqual(paths['sensor-1'], ['3포장 > 3-1'])
        self.assertEqual(paths['valve-1'], ['3포장 > 3-1'])
        self.assertNotIn('nowhere', paths)

    def test_place_members_include_bound_devices_and_descendants(self):
        from aot.space.device_membership import place_members
        site = place_members('site')
        self.assertIn('sensor-1', site)
        self.assertIn('valve-1', site)       # 바인딩
        self.assertEqual(place_members('zone-b'), set())
        self.assertIsNone(place_members('no-such-place'))

    def test_places_named_keeps_the_innermost(self):
        from aot.space.device_membership import places_named
        hits = [s.unique_id for s in places_named('3포장 3-1 밸브')]
        self.assertEqual(hits, ['zone-a'])
        self.assertEqual([s.unique_id for s in places_named('3포장 밸브')], ['site'])

    def test_plot_within_site_through_its_zone(self):
        """예전 list_plots 규칙("가장 안쪽 소속이 물은 곳과 같은가")에서는
        대지로 물으면 구역 안 구획이 빠졌다."""
        from aot.space.device_membership import PlaceIndex
        from aot.databases.models import GeoPlot
        plot = GeoPlot(unique_id='plot-a', geo_id='m1', subject='콩',
                       started_on=date(2026, 6, 15), feature=_poly(PLOT_IN_A))
        plot.save()
        idx = PlaceIndex()
        self.assertTrue(idx.plot_within(plot, 'site'))
        self.assertTrue(idx.plot_within(plot, 'zone-a'))
        self.assertFalse(idx.plot_within(plot, 'zone-b'))
        self.assertEqual(idx.plot_path(plot), '3포장 > 3-1')


class TestPlotWithinFacility(_Base):
    """E8-3: 위치 도형이 없는 시설 구획(김제 육묘장3 설향)은 시설 경로로도 잡힌다."""

    FAC = [[45, 50], [45, 70], [75, 70], [75, 50], [45, 50]]

    def setUp(self):
        super().setUp()
        from aot.databases.models import GeoFacility
        GeoShape(unique_id='fac-shape', geo_id='m1', type='facility',
                 feature=_poly(self.FAC, '육묘장3')).save()
        GeoFacility(unique_id='fac1', shape_uuid='fac-shape', geo_id='m1',
                    name='육묘장3').save()

    def _plot(self, **kw):
        from aot.databases.models import GeoPlot
        plot = GeoPlot(unique_id='plot-f', geo_id='m1', subject='설향',
                       started_on=date(2026, 6, 15), **kw)
        plot.save()
        return plot

    def test_facility_plot_within_its_facility_and_site(self):
        from aot.space.device_membership import PlaceIndex
        idx = PlaceIndex()
        plot = self._plot(facility_uuid='fac1')
        self.assertTrue(idx.plot_within(plot, 'fac-shape'))   # 시설 자체
        self.assertTrue(idx.plot_within(plot, 'site'))        # 시설이 든 대지
        self.assertEqual(idx.plot_path(plot), '3포장 > 육묘장3')

    def test_sibling_zones_do_not_pull_facility_plot(self):
        from aot.space.device_membership import PlaceIndex
        idx = PlaceIndex()
        plot = self._plot(facility_uuid='fac1')
        self.assertFalse(idx.plot_within(plot, 'zone-a'))
        self.assertFalse(idx.plot_within(plot, 'zone-b'))

    def test_plot_without_facility_unchanged(self):
        from aot.space.device_membership import PlaceIndex
        idx = PlaceIndex()
        plot = self._plot(feature=_poly(PLOT_IN_A))
        self.assertTrue(idx.plot_within(plot, 'zone-a'))
        self.assertFalse(idx.plot_within(plot, 'fac-shape'))
        self.assertFalse(idx.plot_within(self._plot_nowhere(), 'site'))

    def _plot_nowhere(self):
        from aot.databases.models import GeoPlot
        p = GeoPlot(unique_id='plot-n', geo_id='m1', subject='무',
                    started_on=date(2026, 6, 15))
        p.save()
        return p

    def test_list_plots_by_facility_and_zone_note(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        self._plot(facility_uuid='fac1')
        by_fac = S.list_plots(zone_id='fac-shape')
        self.assertEqual(by_fac['count'], 1)
        by_site = S.list_plots(zone_id='site')
        self.assertEqual(by_site['count'], 1)
        self.assertIn('시설 이름으로도', by_site.get('note') or '')
        self.assertEqual(S.list_plots(zone_id='zone-a')['count'], 0)


class TestToolsUseTheCanonicalRule(_Base):

    def test_list_plots_by_site_includes_sub_zone_plots(self):
        from aot.databases.models import GeoPlot
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        GeoPlot(unique_id='plot-a', geo_id='m1', subject='콩',
                started_on=date(2026, 6, 15), feature=_poly(PLOT_IN_A)).save()
        out = S.list_plots(zone_id='site')
        self.assertEqual([p.get('place') for p in out['plots']], ['3포장 > 3-1'])
        self.assertEqual(S.list_plots(zone_id='zone-b')['count'], 0)

    def test_anomaly_summary_has_a_zone_scope(self):
        """스키마가 scope_type='zone' 을 허용하는데 분기가 없어 시스템 전체를
        보던 것. 못 찾은 장소는 0건이지 전체가 아니다."""
        from aot.ai.services.ai_summary_service import AISummaryService
        src = ast.unparse(ast.parse(_source_of(AISummaryService.gather_scope_data)))
        self.assertIn("('zone', 'site')", src)
        self.assertIn('place_members', src)


class TestScreensShareTheCanonicalRule(_Base):
    """2단계 — 화면·요약도 같은 정본을 쓴다."""

    def test_place_scope_ids_include_bound_devices(self):
        """노트·일정 화면과 AI 가 같은 함수로 장소 범위를 넓힌다. 예전 노트
        화면은 계층 자손만 봐서 구역에 바인딩된 밸브의 노트가 빠졌다."""
        from aot.space.device_membership import place_scope_ids
        ids, breakdown = place_scope_ids(GeoShape.query.filter_by(
            unique_id='site').first(), include_self=False)
        self.assertIn('valve-1', ids)
        self.assertIn('zone-a', ids)

    def test_site_for_geometry_picks_the_smallest_site(self):
        """대지 안의 대지 — 예전에는 DB 가 먼저 돌려준 대지를 골랐다."""
        from aot.space.device_membership import site_for_geometry
        # 바깥 대지가 DB 에서 **먼저** 읽히게 한다 — 안쪽 대지를 지우고 바깥을
        # 만든 뒤 안쪽을 다시 만든다. 순서 기반 옛 규칙이면 바깥이 나온다.
        GeoShape.query.filter_by(unique_id='site').delete()
        db.session.commit()
        GeoShape(unique_id='outer-site', geo_id='m1', type='site',
                 feature=_poly([[-50, -50], [-50, 150], [150, 150],
                                [150, -50], [-50, -50]], '농장')).save()
        GeoShape(unique_id='site', geo_id='m1', type='site',
                 feature=_poly(SITE, '3포장')).save()
        got = site_for_geometry('m1', _poly(PLOT_IN_A)['geometry'])
        self.assertEqual(got.unique_id, 'site')

    def test_site_summary_counts_devices_placed_directly_on_the_site(self):
        """대지 장치 수가 자식 몫의 합이라, 대지에만 놓인 장치가 빠졌다."""
        from unittest import mock
        from aot.aot_flask.geo import site_summary as ss
        # 대지 안이지만 어느 구역에도 들지 않는 마커.
        bound_shape(unique_id='mk-site', geo_id='m1', type='aot_device',
                 device_id='station-1', channel_id='0',
                 feature=_point(50, 80)).save()
        with mock.patch.object(ss, '_link_status', return_value={}), \
                mock.patch.object(ss, 'prefetch_last_values', return_value={}), \
                mock.patch.object(ss, '_child_entry', side_effect=lambda shape, ids, *a, **k: {
                    'kind': shape.type, 'issues': {'comm_fault': 0}, 'status': 'ok'}), \
                mock.patch.object(ss, '_rollup_status', return_value='ok'), \
                mock.patch.object(ss, '_plot_counts', return_value={}), \
                mock.patch.object(ss, 'upcoming_schedule', return_value={}), \
                mock.patch.object(ss, '_today_block', return_value={}), \
                mock.patch.object(ss, '_notes_block', return_value={}):
            out = ss._build_summary('site')
        # sensor-1(구역 A 마커) + valve-1(바인딩) + station-1(대지 직속).
        self.assertEqual(out['site']['counts']['devices'], 3)


class TestSmallPlaceDefects(_Base):
    """조사 중 찾은 작은 결함 넷(2026-10-08) — 모두 "정본과 다른 판정" 이다."""

    def test_map_id_is_not_taken_as_a_place(self):
        """지도 id 를 장소 인자로 주면 그 지도의 **아무 도형 하나**(마커일 수도
        있다)를 장소로 썼다. 이제는 지도라고 답하고 그 지도의 대지를 알려 준다."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        row, err = S._read_place('m1')
        self.assertIsNone(row)
        self.assertEqual(err.get('reason'), 'map_id_given_for_place')
        self.assertEqual(err.get('sites_on_this_map'), ['3포장'])
        # 같은 조회를 따로 들고 있던 두 도구도 같은 답을 낸다.
        for out in (S.get_sensor_detail(loc_id='m1'),
                    S.get_energy_report(zone_id='m1')):
            self.assertEqual(out.get('reason'), 'map_id_given_for_place', out)

    def test_orphan_equipment_is_placed_on_its_own_map(self):
        """소유 링크 없는 설비는 기하로 소속을 정하는데, 지도를 가리지 않아
        겹쳐 그린 다른 지도의 (더 작은) 구역 이름이 붙었다."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        GeoMap(unique_id='m2', name='시험 지도', category='design').save()
        GeoShape(unique_id='other-zone', geo_id='m2', type='zone',
                 feature=_poly([[14, 14], [14, 18], [18, 18], [18, 14], [14, 14]],
                               '남의 구역')).save()
        GeoShape(unique_id='eq', geo_id='m1', type='equipment_collection',
                 feature={'type': 'FeatureCollection', 'features': [{
                     'type': 'Feature',
                     'geometry': {'type': 'Point', 'coordinates': [16, 16]},
                     'properties': {'sub_type': 'irrigation_valve', 'name': 'EV-1'}}]}
                 ).save()
        res = S._extract_map_equipment(GeoShape.query.all())
        locs = [e['location'] for e in res['equipment'] if e['name'] == 'EV-1']
        self.assertEqual(locs, ['3-1'])

    def test_spatial_tree_cache_tag_sees_deletes_and_edits(self):
        """트리 캐시 태그가 max(id) 만 봐서, 중간 도형 삭제나 제자리 수정 뒤에도
        옛 트리가 나갔다."""
        from aot.ai.services.ai_context_service import AIContextService as A
        before = A._geo_shape_revision_tag()
        GeoShape.query.filter_by(unique_id='zone-b').delete()   # 가장 큰 id 가 아니다
        db.session.commit()
        self.assertNotEqual(A._geo_shape_revision_tag(), before)

    def test_zone_for_device_skips_an_area_polygon_of_the_same_device(self):
        """'device' 종류는 장치 영역 폴리곤이기도 해서, 그것이 먼저 읽히면 점이
        없어 소속이 비었다."""
        from aot.space.device_membership import zone_for_device
        from aot.databases.models import Output
        Output(unique_id='pump-1', name='펌프').save()    # 리졸버는 실존 장치만 푼다
        # 영역 폴리곤을 **먼저** 만든다(작은 id) — 순서 기반이면 이것이 집힌다.
        bound_shape(unique_id='dev-area', geo_id='m1', type='device',
                 device_id='pump-1', channel_id='0',
                 feature=_poly([[11, 11], [11, 13], [13, 13], [13, 11], [11, 11]])).save()
        bound_shape(unique_id='dev-marker', geo_id='m1', type='aot_device',
                 device_id='pump-1', channel_id='0', feature=_point(35, 35)).save()
        z = zone_for_device('pump-1', 'm1')
        self.assertIsNotNone(z)
        self.assertEqual(z.unique_id, 'zone-a')


class TestControlAdjacentPaths(_Base):
    """3단계 — 제어 제안과 구획 센서. 결정(2026-10-08): 화면 규칙을 따른다."""

    def setUp(self):
        super(TestControlAdjacentPaths, self).setUp()
        from aot.databases.models import GeoBinding, GeoFacility, Input, Output
        # 구역 A 안의 온실과 그 설비(측창)에 매인 출력.
        GeoShape(unique_id='fac-shape', geo_id='m1', type='facility',
                 feature=_poly([[30, 30], [30, 38], [38, 38], [38, 30], [30, 30]],
                               '온실')).save()
        GeoFacility(unique_id='fac1', shape_uuid='fac-shape', geo_id='m1',
                    name='온실').save()
        GeoBinding(spatial_kind='fitting', spatial_id='fac1:f1', role='actuator',
                   device_kind='output', device_id='window-1').save()
        for uid, name in (('valve-1', 'v331'), ('window-1', '측창')):
            Output(unique_id=uid, name=name,
                   output_type='virtual_on_off_single').save()
        # 구역 A 폴리곤에 직접 바인딩된 센서(마커 없음)와 마커 센서.
        GeoBinding(spatial_kind='shape', spatial_id='zone-a', role='area',
                   device_kind='input', device_id='bound-sensor').save()
        for uid in ('bound-sensor', 'sensor-1'):
            Input(unique_id=uid, name=uid, device='MQTT_PAHO_JSON').save()

    def _capture_proposal(self, fn, *args):
        from unittest import mock
        from aot.ai.services import intent_resolver as ir
        seen = {}

        def fake(outs, site, zone, raw_cmd, thread_id, source):
            seen.update(outs=sorted(o.unique_id for o in outs), site=site, zone=zone)
            return {'status': 'success'}
        with mock.patch.object(ir, 'build_location_proposal', side_effect=fake):
            getattr(ir, fn)(*args)
        return seen

    def test_map_proposal_on_a_zone_includes_its_facility_fittings(self):
        """구역을 가리키면 구역 화면처럼 — 구역 안 온실 설비도 그 구역 것."""
        got = self._capture_proposal('propose_map_scoped_control', '다 꺼줘',
                                     {'lat': 35, 'lng': 35}, None)
        self.assertEqual(got['zone'], '3-1')
        self.assertEqual(got['site'], '3포장')
        self.assertIn('window-1', got['outs'])
        self.assertIn('valve-1', got['outs'])      # 바인딩만 걸린 밸브

    def test_map_proposal_on_a_site_leaves_facility_fittings_out(self):
        """대지를 가리키면 필지 화면처럼 — 온실 안 설비는 그 시설에서."""
        got = self._capture_proposal('propose_map_scoped_control', '다 꺼줘',
                                     {'lat': 80, 'lng': 50}, None)
        self.assertIsNone(got['zone'])
        self.assertEqual(got['site'], '3포장')
        self.assertNotIn('window-1', got['outs'])
        self.assertIn('valve-1', got['outs'])

    def test_location_proposal_reads_the_place_path(self):
        """1단계가 search_devices 의 'zone' 칸을 'place' 경로로 바꿔, 이 제안의
        장소 표시가 비었다. 경로에서 대지·구역을 읽는다."""
        from unittest import mock
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        rows = {'results': [{'id': 'valve-1', 'type': 'output', 'place': '3포장 > 3-1'}]}
        with mock.patch.object(S, 'search_devices', return_value=rows):
            got = self._capture_proposal('propose_location_scoped_control',
                                         '3포장 3-1 밸브 켜줘', None)
        self.assertEqual((got['site'], got['zone']), ('3포장', '3-1'))

    def test_plot_zone_fallback_includes_bound_sensors(self):
        """구역 폴백이 마커만 봐서, 구역에 바인딩으로 맡긴 센서가 빠졌다."""
        from aot.space import plot_context
        from aot.databases.models import GeoPlot
        # 구역 A 안이지만 구획 자체에는 센서가 없는 자리.
        plot = GeoPlot(unique_id='plot-a', geo_id='m1', subject='콩',
                       started_on=date(2026, 6, 15),
                       feature=_poly([[11, 35], [11, 39], [15, 39], [15, 35], [11, 35]]))
        plot.save()
        got = plot_context.sensors_for_plot(plot)
        self.assertEqual(got['in_plot'], [])
        self.assertIn('bound-sensor', got['from_zone'])
        self.assertIn('sensor-1', got['from_zone'])


class TestScopeNoteMatchesBehaviour(_Base):

    def test_place_scoped_search_note_does_not_claim_name_matching(self):
        """장소로 좁힌 결과는 소속으로 나오는데 안내문이 "이름이 일치한 것" 이라고
        말해, 모델이 응답과 대조해 "설명과 다르다" 고 읽었다(2026-10-08 실측)."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.search_devices(query='3포장')
        note = ' '.join(out.get('_reading') or [])
        self.assertIn('BELONG', note)
        self.assertNotIn('whose NAME matched', note)
        self.assertIn('list_plots', note)


class TestQualifiedNamesNarrowInside(_Base):
    """'장소 + 낱말' 이름 — 낱말을 조용히 버리지 않는다(2026-10-08 외부 MCP 점검).

    '3포장 콩' 이 '콩' 을 버리고 3포장 전체로 답했다. 쓰기 도구가 이 이름을 받으면
    콩 구획이 아니라 3포장 전체에 붙는다.
    """

    def setUp(self):
        super(TestQualifiedNamesNarrowInside, self).setUp()
        from aot.space import shape_index
        from aot.databases.models import GeoPlot
        shape_index.invalidate()
        for uid, subject, ring in (
                ('p-k1', '콩 1구', [[11, 25], [11, 30], [16, 30], [16, 25], [11, 25]]),
                ('p-k2', '콩 2구', [[18, 25], [18, 30], [23, 30], [23, 25], [18, 25]]),
                ('p-nm', '나물콩', [[25, 25], [25, 30], [30, 30], [30, 25], [25, 25]]),
                ('p-k', '콩', [[65, 25], [65, 30], [70, 30], [70, 25], [65, 25]])):
            GeoPlot(unique_id=uid, geo_id='m1', subject=subject,
                    started_on=date(2026, 6, 15), feature=_poly(ring)).save()

    def tearDown(self):
        from aot.space import shape_index
        shape_index.invalidate()
        super(TestQualifiedNamesNarrowInside, self).tearDown()

    def _resolve(self, q):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        return S.resolve_target_tool(q)

    def test_an_exact_name_does_not_hide_the_others(self):
        """정확일치 하나로 정하지 않는다(2026-10-09 외부 MCP 점검).

        '3포장 콩' 이 이름이 '콩' 인 구획 하나로 조용히 정해졌는데, 같은 곳에
        '콩 1구'·'콩 2구'·'나물콩' 이 있었다. 사람이 말한 '콩' 은 대개 그 전부다.
        후보마다 어떻게 걸렸는지(match)를 함께 낸다."""
        out = self._resolve('3포장 콩')
        self.assertEqual(out['status'], 'needs_disambiguation', out)
        got = {c['name']: c.get('match') for c in out['candidates']}
        self.assertEqual(got, {'콩': 'exact', '콩 1구': 'word', '콩 2구': 'word',
                               '나물콩': 'fragment'})
        # 정확일치가 맨 앞 — 사람이 고를 때 가장 그럴듯한 것부터 본다.
        self.assertEqual(out['candidates'][0]['name'], '콩')
        self.assertTrue(any("'match'" in r for r in out['_reading']))

    def test_word_matching_several_plots_is_a_question(self):
        out = self._resolve('3포장 3-1 콩')
        self.assertEqual(out['status'], 'needs_disambiguation', out)
        names = sorted(c['name'] for c in out['candidates'])
        self.assertIn('콩 1구', names)
        self.assertIn('콩 2구', names)
        self.assertNotIn('콩', names)             # 3-1 밖이다
        for c in out['candidates']:
            self.assertIn('3포장 > 3-1', c['where'])

    def test_a_unique_pick_says_how_it_matched(self):
        out = self._resolve('3포장 나물콩')
        self.assertEqual((out['status'], out['target_id']), ('success', 'p-nm'), out)
        self.assertEqual(out['matched'], {'rule': 'exact', 'term': '나물콩',
                                          'within': '3포장'})
        out = self._resolve('3포장 나물')
        self.assertEqual(out['target_id'], 'p-nm', out)
        self.assertEqual(out['matched']['rule'], 'fragment')
        self.assertIn('Confirm with the user', out['note'])

    def test_a_lone_one_letter_fragment_is_not_an_answer(self):
        """한 글자 조각('물' → '나물콩') 하나로는 정하지 않는다."""
        out = self._resolve('3포장 물')
        self.assertEqual(out['target_type'], 'site', out)
        self.assertEqual(out.get('ignored_terms'), ['물'])

    def test_a_write_with_that_name_is_refused_before_approval(self):
        from aot.tools import mcp_safety_gate as gate
        refusal = gate._ambiguous_target_refusal(
            'add_schedule', {'target_name': '3포장 3-1 콩', 'content': 'x'})
        self.assertIsNotNone(refusal, '구역 전체로 승인 요청이 나갈 뻔했다')
        self.assertEqual(refusal['reason_code'], 'ambiguous_target')
        # 정확일치가 섞여 있어도 마찬가지다 — 예전엔 '콩' 하나로 승인 요청이 나갔다.
        refusal = gate._ambiguous_target_refusal(
            'create_note', {'target_name': '3포장 콩', 'content': 'x'})
        self.assertIsNotNone(refusal)
        self.assertEqual(refusal['reason_code'], 'ambiguous_target')

    def test_a_word_that_names_nothing_inside_is_reported_not_dropped(self):
        out = self._resolve('3포장 온도')
        self.assertEqual((out['status'], out['target_type']), ('success', 'site'))
        self.assertEqual(out.get('ignored_terms'), ['온도'])
        self.assertIn('IGNORED', out['note'])

    def test_plain_and_zone_qualified_names_are_unchanged(self):
        self.assertEqual(self._resolve('3포장')['target_type'], 'site')
        out = self._resolve('3포장 3-1')
        self.assertEqual((out['target_type'], out['target_id']), ('zone', 'zone-a'))
        self.assertNotIn('ignored_terms', out)


class TestSameNamePlacesInSearch(_Base):
    """search_devices 가 이름이 같은 두 장소를 한 목록에 섞던 것(2026-10-08)."""

    def setUp(self):
        super(TestSameNamePlacesInSearch, self).setUp()
        from aot.databases.models import Input
        GeoMap(unique_id='m2', name='그린', category='design').save()
        GeoShape(unique_id='gh-site', geo_id='m2', type='site',
                 feature=_poly([[200, 0], [200, 100], [300, 100], [300, 0], [200, 0]],
                               '그린하트바이오')).save()
        GeoShape(unique_id='gh-zone', geo_id='m2', type='zone',
                 feature=_poly([[210, 10], [210, 40], [240, 40], [240, 10], [210, 10]],
                               '3포장')).save()
        Input(unique_id='sensor-1', name='온습도', device='MQTT_PAHO_JSON').save()

    def _search(self, q):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        return S.search_devices(query=q)

    def test_same_name_in_two_places_returns_candidates(self):
        out = self._search('3포장')
        self.assertEqual(out.get('status'), 'needs_disambiguation', out)
        self.assertEqual(out['count'], 0)
        wheres = sorted(c['where'] for c in out['candidates'])
        self.assertEqual(len(wheres), 2)
        self.assertTrue(any('그린' in w for w in wheres), wheres)

    def test_spatial_tree_qualifies_only_repeated_names(self):
        """트리도 같은 규칙 — 다른 지도에도 있는 이름에만 지도 이름을 붙인다
        (2026-10-09). 맨 이름만 나가면 두 '3포장' 이 한 곳으로 읽혔다."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.get_spatial_tree()
        found = {}

        def walk(ns):
            for n in ns:
                found[n.get('unique_id')] = n
                walk(n.get('children') or [])
        walk(out['hierarchy'])
        self.assertEqual(found['site'].get('use_name'), '김제 3포장', out)
        self.assertEqual(found['gh-zone'].get('use_name'), '그린 3포장', out)
        for uid in ('zone-a', 'zone-b', 'gh-site'):
            self.assertNotIn('use_name', found[uid])
            self.assertNotIn('map', found[uid])
        self.assertIn("'use_name'", out['_reading'])

    def test_spatial_tree_can_be_narrowed_to_one_map(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        roots = [n['unique_id'] for n in S.get_spatial_tree(map='그린')['hierarchy']]
        self.assertEqual(['gh-site'], roots)
        self.assertEqual(roots, [n['unique_id'] for n in
                                 S.get_spatial_tree(map='m2')['hierarchy']])
        self.assertEqual('error', S.get_spatial_tree(map='없는 지도').get('status'))

    def test_map_name_qualifier_narrows_to_that_map(self):
        out = self._search('김제 3포장')
        self.assertNotEqual(out.get('status'), 'needs_disambiguation', out)
        ids = {r['id'] for r in out['results']}
        self.assertIn('sensor-1', ids)          # 김제 3포장 > 3-1 의 마커 센서

    def test_paths_name_the_map_only_when_the_root_name_repeats(self):
        """'3포장' 이 김제의 대지이자 그린하트바이오의 구역이라 경로만으로는 어느
        것인지 몰랐다. 맨 앞 이름이 겹칠 때만 지도 이름을 붙인다."""
        from aot.space.device_membership import PlaceIndex
        idx = PlaceIndex()
        self.assertEqual(idx.device_paths(['sensor-1'])['sensor-1'],
                         ['김제 3포장 > 3-1'])
        # 맨 앞 이름(그린하트바이오)이 유일하면 그대로.
        self.assertEqual(idx.path(idx.by_uid['gh-zone']), '그린하트바이오 > 3포장')

    def test_scoped_search_keeps_name_matches_on_that_map_only(self):
        out = self._search('김제 3포장')
        self.assertNotIn('gh-zone', {r['id'] for r in out['results']})

    def test_parent_place_qualifier_narrows_too(self):
        out = self._search('그린하트바이오 3포장')
        self.assertNotEqual(out.get('status'), 'needs_disambiguation', out)
        self.assertNotIn('sensor-1', {r['id'] for r in out['results']})


class TestResolveTargetChildren(_Base):
    """resolve_target 의 children — 시설 포함, 소속 경로, 겹치는 이름은 use_name.

    예전에는 구획과 구역 이름만 한 줄로 늘어놓아 시설이 빠지고, 시설 안 '콩' 과
    노지 '콩 N구' 를 구분할 수 없었다(2026-10-08 외부 MCP 점검).
    """

    def setUp(self):
        super(TestResolveTargetChildren, self).setUp()
        from aot.space import shape_index
        from aot.databases.models import GeoFacility, GeoPlot
        shape_index.invalidate()
        GeoShape(unique_id='fac-shape', geo_id='m1', type='facility',
                 feature=_poly([[60, 60], [60, 70], [70, 70], [70, 60], [60, 60]],
                               '육묘장3')).save()
        GeoFacility(unique_id='fac1', shape_uuid='fac-shape', geo_id='m1',
                    name='육묘장3').save()
        GeoPlot(unique_id='p-a1', geo_id='m1', subject='콩 1구',
                started_on=date(2026, 6, 15),
                feature=_poly([[11, 25], [11, 30], [16, 30], [16, 25], [11, 25]])).save()
        GeoPlot(unique_id='p-fac', geo_id='m1', subject='상추', facility_uuid='fac1',
                started_on=date(2026, 8, 22)).save()
        # 같은 이름의 구획이 다른 대지에 하나 더 — 그러면 이름만으로는 못 가리킨다.
        GeoShape(unique_id='other-site2', geo_id='m1', type='site',
                 feature=_poly([[200, 0], [200, 50], [250, 50], [250, 0], [200, 0]],
                               '2포장')).save()
        GeoPlot(unique_id='p-b1', geo_id='m1', subject='콩 1구',
                started_on=date(2026, 6, 15),
                feature=_poly([[210, 10], [210, 20], [220, 20], [220, 10], [210, 10]])).save()

    def tearDown(self):
        from aot.space import shape_index
        shape_index.invalidate()
        super(TestResolveTargetChildren, self).tearDown()

    def test_site_children_carry_places_and_include_facilities(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.resolve_target_tool('3포장')
        kids = {(c['name'], c['type']): c for c in out['children']}
        self.assertEqual(kids[('3-1', 'zone')]['place'], '3포장 > 3-1')
        self.assertEqual(kids[('육묘장3', 'facility')]['place'], '3포장 > 육묘장3')
        self.assertEqual(kids[('상추', 'plot')]['place'], '3포장 > 육묘장3')
        self.assertEqual(kids[('콩 1구', 'plot')]['place'], '3포장 > 3-1')
        # 이름이 겹치는 자식에는 그것 하나만 가리키는 이름이 붙는다.
        self.assertEqual(kids[('콩 1구', 'plot')].get('use_name'), '3포장 콩 1구')
        self.assertNotIn('use_name', kids[('상추', 'plot')])
        self.assertEqual(S._resolve_note_target('3포장 콩 1구')[0], 'p-a1')

    def test_facility_children_are_its_own_plots(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.resolve_target_tool('육묘장3')
        self.assertEqual(out['target_type'], 'facility')
        self.assertEqual([c['name'] for c in out['children']], ['상추'])


class TestMapEquipmentTotal(_Base):
    """get_map_equipment 의 관수 행은 '그 장소가 직접 소유한 것' 이라, 대지 행만
    보고 대지 전체로 읽었다(2026-10-08). 물은 장소의 합계를 따로 싣는다."""

    def test_total_sums_the_rows_of_the_asked_place(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        def spr(x, y, flow):
            return {'type': 'Feature',
                    'geometry': {'type': 'Point', 'coordinates': [x, y]},
                    'properties': {'sub_type': 'sprinkler_coverage', 'flow': flow}}
        GeoShape(unique_id='eq', geo_id='m1', type='equipment_collection',
                 feature={'type': 'FeatureCollection', 'features': [
                     spr(20, 20, 100), spr(25, 20, 100),     # 구역 3-1 안
                     spr(50, 80, 850)]}).save()              # 대지에 직접
        out = S.get_map_equipment_tool(area_name='3포장')
        rows = {r['area']: r['sprinklers'] for r in out['irrigation']}
        self.assertEqual(rows, {'3-1': 2, '3포장': 1})
        tot = out['irrigation_total']
        self.assertEqual((tot['sprinklers'], tot['sprinkler_flow_lph']), (3, 1050.0))
        self.assertTrue(any('irrigation_total' in r for r in out['_reading']))


def _source_of(fn):
    import inspect
    import textwrap
    return textwrap.dedent(inspect.getsource(fn))


#: data_tools 가 직접 부르면 안 되는 소속 헬퍼 — 정본(PlaceIndex · place_members ·
#: annotate_places · places_named)을 거쳐야 한다. 규칙이 여러 벌이면 갈라지고,
#: 갈라지면 모델이 "도구가 설명과 다르다" 고 보고한다.
_FORBIDDEN = frozenset({'device_zone_map', 'device_ids_in_shape',
                        'device_ids_in_area', 'zone_for_device'})


class TestDataToolsDoNotBypassTheCanonicalRule(unittest.TestCase):

    def test_no_direct_membership_helpers(self):
        hits = []
        for fn in sorted(os.listdir(_DATA_TOOLS)):
            if not fn.endswith('.py'):
                continue
            path = os.path.join(_DATA_TOOLS, fn)
            tree = ast.parse(open(path, encoding='utf-8').read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.Attribute):
                    names = [node.attr]
                elif isinstance(node, ast.Name):
                    names = [node.id]
                elif isinstance(node, ast.Call):
                    # providers.get('device_zone_map') 처럼 문자열로 부르는 경우.
                    names = [a.value for a in node.args
                             if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                for n in names:
                    if n in _FORBIDDEN:
                        hits.append('%s:%d %s' % (fn, node.lineno, n))
        self.assertEqual(hits, [], '정본을 거치지 않는 소속 판정: %s' % hits)


if __name__ == '__main__':
    unittest.main()


class TestZoneOverviewDoesNotRepeatSites(_Base):
    """장소를 지정하지 않은 센서 요약에서 대지가 자기 구역의 장치를 다시 실어
    응답이 두 배가 됐다(2026-10-09 실측 20,354토큰). 대지를 콕 집어 물으면
    자손까지 전부 낸다(소속의 정의는 그대로)."""

    def setUp(self):
        super(TestZoneOverviewDoesNotRepeatSites, self).setUp()
        from aot.databases.models import DeviceMeasurements, Input
        Input(unique_id='sensor-1', name='온습도', device='MQTT_PAHO_JSON').save()
        DeviceMeasurements(device_id='sensor-1', channel=0,
                           measurement='temperature', unit='C').save()

    def _summary(self, **kw):
        from datetime import datetime, timezone
        from unittest import mock
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        with mock.patch('aot.utils.influx.read_influxdb_list',
                        return_value=[(now, 21.0)]):
            kw.setdefault('detail', True)     # 센서 목록은 detail 에서만
            return S.get_zone_sensor_summary(**kw)

    def test_overview_lists_a_zones_device_once(self):
        out = self._summary()
        where = [z['zone_name'] for z in out['zones']
                 for d in z['sensors'] if d['device_id'] == 'sensor-1']
        self.assertEqual(where, ['3-1'], out)
        # 구역으로 다 넘어간 대지는 '데이터 없음' 이 아니다.
        self.assertNotIn('3포장', [z['zone_name'] for z in out.get('zones_without_data', [])])

    def test_asking_for_the_site_still_gives_everything(self):
        out = self._summary(zone_ids=['3포장'])
        ids = [d['device_id'] for d in out['zones'][0]['sensors']]
        self.assertIn('sensor-1', ids)
from aot.tests.geo._legacy_marker import bound_shape
