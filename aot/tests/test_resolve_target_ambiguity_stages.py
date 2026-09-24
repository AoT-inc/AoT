# coding=utf-8
"""이름 해석의 **모든 단계**에서 조용히 고르지 않는다 — 리뷰(26-09-23) 재현.

정확일치 단계만 곳으로 묶던 때 남은 구멍:

- 조사·꼬리말: '육묘장에'(부분일치) → 안쪽 시설, '육묘장 온도'(한정어) → 부지 하나.
- 여러 낱말 지도 이름('New Design Map')을 한정어로 못 알아봐, 저장 순서가
  거꾸로면 'New Design Map 1구역' 이 **다른 지도**의 구역으로 풀렸다.
- 이름이 같은 지도 둘이면 후보의 use_name 이 똑같았다(아무것도 가리키지 못한다).
- '1 구역' 처럼 한정어 없이 여러 구역에 걸리면 첫 행을 골랐다.
- '산양삼 7' 처럼 한정어로도 둘 남으면 resolve_target 이 'target_not_found' 라 했다.
- use_name 이 없는 후보는 쓰기 도구로 갈 길이 없었다(target_id 를 안 받았다).
"""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]]}


class TestAmbiguityAtEveryStage(unittest.TestCase):

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
            'sqlite:///' + os.path.join(cls._tmp.name, 'stages.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        for uid, name in (('map-a', '영양'), ('map-b', '그린'), ('map-n', 'New Design Map'),
                          ('map-t1', '쌍둥이'), ('map-t2', '쌍둥이')):
            db.session.add(GeoMap(unique_id=uid, name=name))

        def shape(uid, geo, typ, name, geom, device_id=None):
            db.session.add(GeoShape(unique_id=uid, geo_id=geo, type=typ, device_id=device_id,
                                    feature={'type': 'Feature', 'properties': {'name': name},
                                             'geometry': geom}))

        # 영양: 부지 '육묘장' 안에 같은 이름 시설(시설이 먼저 저장). 그린: 부지 '육묘장'.
        shape('fac-a', 'map-a', 'facility', '육묘장', _square(0.002, 0.002, 0.003))
        shape('site-a', 'map-a', 'site', '육묘장', _square(0.0, 0.0, 0.01))
        shape('site-b', 'map-b', 'site', '육묘장', _square(1.0, 1.0, 0.01))
        # 여러 낱말 지도 이름 — **다른 지도의 같은 이름 구역이 먼저** 저장돼 있다.
        shape('zone-a1', 'map-a', 'zone', '1구역', _square(0.5, 0.5, 0.01))
        shape('zone-n1', 'map-n', 'zone', '1구역', _square(2.0, 2.0, 0.01))
        # 이름이 같은 지도 둘, 둘레 부지 없음 → 그 하나만 가리키는 이름이 없다.
        shape('zone-t1', 'map-t1', 'zone', 'A동', _square(3.0, 3.0, 0.01))
        shape('zone-t2', 'map-t2', 'zone', 'A동', _square(4.0, 4.0, 0.01))
        # 한 지도, 부지 둘에 같은 이름 구역 '1' — '1 구역' 은 둘 다에 걸린다.
        shape('site-g', 'map-a', 'site', '구례', _square(0.3, 0.3, 0.01))
        shape('site-j', 'map-a', 'site', '진안', _square(0.4, 0.4, 0.01))
        shape('z1-g', 'map-a', 'zone', '1', _square(0.302, 0.302, 0.002))
        shape('z1-j', 'map-a', 'zone', '1', _square(0.402, 0.402, 0.002))
        # 부지 '산양삼' 안의 서로 다른 자리에 같은 이름 구역 '7' — 한정어로도 둘.
        shape('site-s', 'map-b', 'site', '산양삼', _square(5.0, 5.0, 0.1))
        shape('z7-1', 'map-b', 'zone', '7', _square(5.01, 5.01, 0.01))
        shape('z7-2', 'map-b', 'zone', '7', _square(5.05, 5.05, 0.01))
        # 안팎 같은 이름 한 곳(한 지도).
        shape('fac-c', 'map-a', 'facility', '묘포', _square(0.102, 0.102, 0.003))
        shape('site-c', 'map-a', 'site', '묘포', _square(0.1, 0.1, 0.01))
        # 정확히 같은 이름의 장치 하나 + 그 이름을 품은 다른 장치(먼저 저장).
        db.session.add(Output(unique_id='out-v11', name='v11', output_type='virtual_on_off_single'))
        db.session.add(Output(unique_id='out-v1', name='v1', output_type='virtual_on_off_single'))
        # 부분일치 장치 여럿 — Input·Output 에 걸쳐, 이름 같은 장치 둘 포함.
        from aot.databases.models import Input, GeoPlot
        for uid, name in (('out-side1', 'TEST 측창 1'), ('out-side2', 'TEST 측창 2'),
                          ('out-warm-a1', 'SIM 보온 A'), ('out-warm-a2', 'SIM 보온 A'),
                          ('out-warm-b', 'SIM 보온 B'), ('out-lonely', 'lonely-heater-01')):
            db.session.add(Output(unique_id=uid, name=name, output_type='virtual_on_off_single'))
        db.session.add(Input(unique_id='in-side', name='TEST 측창 개도', device='TEST'))
        # 지도에 표지가 있는 장치 둘 + 없는 장치 하나(같은 부분 이름).
        for uid, name in (('out-mk1', 'MK 펌프 1'), ('out-mk2', 'MK 펌프 2'),
                          ('out-mk3', 'MK 펌프 3')):
            db.session.add(Output(unique_id=uid, name=name, output_type='virtual_on_off_single'))
        shape('mk1-marker', 'map-a', 'device', 'MK 펌프 1',
              {'type': 'Point', 'coordinates': [0.7, 0.7]}, device_id='out-mk1')
        shape('mk3-marker', 'map-b', 'device', 'MK 펌프 3',
              {'type': 'Point', 'coordinates': [1.7, 1.7]}, device_id='out-mk3')
        # 구획만 든 구역: 영양 '1구역' 안의 식생 구획 하나.
        import datetime as _dt
        db.session.add(GeoPlot(unique_id='plot-a1', geo_id='map-a', kind='vegetation',
                               subject='고추', name='고추밭A', started_on=_dt.date(2026, 3, 1),
                               feature={'type': 'Feature', 'properties': {},
                                        'geometry': _square(0.502, 0.502, 0.002)}))
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

    def _ids(self, out):
        return sorted(c['target_id'] for c in out.get('candidates') or [])

    # ── 조사·꼬리말: 부분일치·한정어 단계도 고르지 않는다 ─────────────────
    def test_a_particle_does_not_pick_the_inner_facility(self):
        self.assertEqual(self.S._resolve_note_target('육묘장에')[:2], (None, 'ambiguous'))
        out = self.S.resolve_target_tool('육묘장에')
        self.assertEqual(out.get('error'), 'ambiguous_name', out)
        self.assertEqual(self._ids(out), ['site-a', 'site-b'])

    def test_a_trailing_word_does_not_pick_one_site(self):
        for q in ('육묘장 온도', '육묘장 시설'):
            self.assertEqual(self.S._resolve_note_target(q)[:2], (None, 'ambiguous'), q)

    def test_a_particle_under_one_map_is_the_outer_place(self):
        self.assertEqual(self.S._resolve_note_target('영양 육묘장에')[0], 'site-a')

    def test_a_zone_token_without_a_qualifier_is_ambiguous(self):
        self.assertEqual(self.S._resolve_note_target('1 구역')[:2], (None, 'ambiguous'))

    # ── 지도 이름 한정어 ──────────────────────────────────────────────────
    def test_a_multi_word_map_name_qualifies(self):
        self.assertEqual(self.S._resolve_note_target('New Design Map 1구역')[0], 'zone-n1')
        self.assertEqual(self.S._resolve_note_target('영양 1구역')[0], 'zone-a1')

    def test_a_map_qualified_name_does_not_escape_its_map(self):
        # 그 지도에 없는 이름을 다른 지도의 것으로 답하지 않는다.
        self.assertIsNone(self.S._resolve_note_target('New Design Map 육묘장')[0])
        self.assertIsNone(self.S._resolve_note_target('그린 묘포')[0])

    def test_a_shared_map_name_is_not_a_qualifier(self):
        r = self.S._resolve_note_target('쌍둥이 A동')
        self.assertNotIn(r[0], ('zone-t1', 'zone-t2'))

    # ── use_name 은 되짚어 확인된 것만 ────────────────────────────────────
    def test_every_use_name_resolves_back_to_its_candidate(self):
        for q in ('육묘장', '1구역', '1', 'A동', '산양삼 7', '육묘장 온도'):
            out = self.S.resolve_target_tool(q)
            self.assertEqual(out.get('error'), 'ambiguous_name', (q, out))
            names = [c['use_name'] for c in out['candidates'] if c.get('use_name')]
            self.assertEqual(len(names), len(set(names)), (q, names))
            for c in out['candidates']:
                if c.get('use_name'):
                    self.assertEqual(self.S._resolve_note_target(c['use_name'])[0],
                                     c['target_id'], (q, c))

    def test_the_multi_word_map_candidate_gets_a_working_use_name(self):
        out = self.S.resolve_target_tool('1구역')
        by_id = {c['target_id']: c for c in out['candidates']}
        self.assertEqual(by_id['zone-n1'].get('use_name'), 'New Design Map 1구역')
        self.assertEqual(by_id['zone-a1'].get('use_name'), '영양 1구역')

    def test_same_named_maps_get_no_use_name_and_a_target_id_hint(self):
        out = self.S.resolve_target_tool('A동')
        self.assertEqual(self._ids(out), ['zone-t1', 'zone-t2'])
        self.assertTrue(all('use_name' not in c for c in out['candidates']), out)
        self.assertTrue(any("target_id" in r for r in out['_reading']))

    # ── 한정어로도 둘: resolve_target·쓰기 도구가 후보를 낸다 ─────────────
    def test_qualified_ambiguity_is_not_reported_as_not_found(self):
        out = self.S.resolve_target_tool('산양삼 7')
        self.assertEqual(out.get('error'), 'ambiguous_name', out)
        self.assertEqual(self._ids(out), ['z7-1', 'z7-2'])
        note = self.S.create_note(name='x', target_name='산양삼 7')
        self.assertEqual(note.get('error'), 'ambiguous_name', note)
        sch = self.S.add_schedule_tool(date='2026-10-01', content='점검', target_name='산양삼 7')
        self.assertEqual(sch.get('error'), 'ambiguous_name', sch)

    # ── 안팎 같은 이름: 바깥 + also_inside ────────────────────────────────
    def test_nested_same_name_reports_the_inner_shape(self):
        out = self.S.resolve_target_tool('묘포')
        self.assertEqual(out['status'], 'success', out)
        self.assertEqual(out['target_id'], 'site-c')
        self.assertEqual([e['target_id'] for e in out.get('also_inside') or []], ['fac-c'])
        self.assertEqual(out['also_inside'][0]['type'], 'facility')

    def test_candidates_carry_also_inside(self):
        out = self.S.resolve_target_tool('육묘장')
        by_id = {c['target_id']: c for c in out['candidates']}
        self.assertEqual([e['target_id'] for e in by_id['site-a'].get('also_inside') or []],
                         ['fac-a'])
        self.assertNotIn('also_inside', by_id['site-b'])

    # ── 정확히 같은 이름의 장치 하나는 바로 답한다 ─────────────────────────
    def test_one_exact_device_name_is_not_a_partial_match(self):
        self.assertEqual(self.S._resolve_note_target('v1')[0], 'out-v1')

    # ── target_id 경로 ──────────────────────────────────────────────────
    def _fake_scheduler(self):
        calls = []

        class _Fake:
            def propose_job(self, **kw):
                calls.append(kw)
                return SimpleNamespace(id=1, unique_id='job-x', anchor_tz=None,
                                       anchor_source=None)

            def approve_job(self, *a, **kw):
                return None

        from aot.tools import providers
        real = providers.get

        def fake_get(name):
            return _Fake() if name == 'job_scheduler' else real(name)
        return calls, mock.patch.object(providers, 'get', side_effect=fake_get)

    def test_a_candidate_without_use_name_is_reachable_by_target_id(self):
        calls, patch = self._fake_scheduler()
        with patch:
            out = self.S.add_schedule_tool(date='2026-10-01', content='점검',
                                           target_id='zone-t2')
        self.assertEqual(out.get('status'), 'success', out)
        self.assertEqual(calls[0]['target_id'], 'zone-t2')
        self.assertEqual(out['target_type'], 'zone')

    def test_an_unknown_target_id_is_refused(self):
        calls, patch = self._fake_scheduler()
        with patch:
            out = self.S.add_schedule_tool(date='2026-10-01', content='점검',
                                           target_id='no-such-thing')
        self.assertEqual(out.get('error'), 'target_not_found', out)
        self.assertEqual(calls, [])

    def test_edit_schedule_relinks_by_target_id(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models.scheduler import SchedulerJobMeta
        meta = SchedulerJobMeta(unique_id='job-e', action_type='human', target_id='none',
                                params_json='{}', state='APPROVED')
        db.session.add(meta)
        db.session.commit()
        amb = self.S.edit_schedule_tool('job-e', target_name='A동')
        self.assertEqual(amb.get('error'), 'ambiguous_name', amb)
        out = self.S.edit_schedule_tool('job-e', target_id='zone-t1')
        self.assertEqual(out.get('status'), 'success', out)
        self.assertEqual(SchedulerJobMeta.query.filter_by(unique_id='job-e').first().target_id,
                         'zone-t1')

    def test_the_schedule_refusal_is_english_and_structured(self):
        out = self.S.add_schedule_tool(date='2026-10-01', content='점검', target_name='A동')
        self.assertEqual(out['status'], 'needs_disambiguation')
        import re
        self.assertIsNone(re.search('[가-힣]', out['message'].replace('A동', '')),
                          out['message'])
        self.assertIn('target_id', out['message'])
        nf = self.S.add_schedule_tool(date='2026-10-01', content='점검', target_name='없는곳')
        self.assertEqual(nf.get('error'), 'target_not_found')
        self.assertIn('could not be matched', nf['message'])

    # ── 일괄 등록은 단일 등록과 같은 답을 한다 ────────────────────────────
    def test_batch_refuses_an_ambiguous_entry_with_candidates(self):
        err = self.S.validate_schedule_batch(
            [{'target_name': '육묘장', 'time': '09:00'}], content='점검')
        self.assertEqual(err.get('error'), 'ambiguous_target_in_batch', err)
        self.assertEqual(len(err['ambiguous_entries'][0]['candidates']), 2)

    def test_batch_accepts_a_site_whose_only_inner_thing_is_a_same_name_shape(self):
        self.assertIsNone(self.S.validate_schedule_batch(
            [{'target_name': '묘포', 'time': '09:00'}], content='점검'))

    # ── 일괄 등록: 실제로 쓰일 대상(target_id 우선)으로 판정한다 ─────────
    def test_batch_refuses_a_site_with_child_zones_by_name_and_by_id(self):
        self.assertIn('1', [c['name'] for c in self.S._site_zone_children('site-g')])
        by_name = self.S.validate_schedule_batch(
            [{'target_name': '구례', 'time': '09:00'}], content='점검')
        self.assertEqual(by_name.get('error'), 'container_target_in_batch', by_name)
        by_id = self.S.validate_schedule_batch(
            [{'target_id': 'site-g', 'time': '09:00'}], content='점검')
        self.assertEqual(by_id.get('error'), 'container_target_in_batch', by_id)
        # 잎 이름에 부지 id — 이름과 id 가 다른 것을 가리킨다.
        mixed = self.S.validate_schedule_batch(
            [{'target_name': '영양 1구역', 'target_id': 'site-g', 'time': '09:00'}],
            content='점검')
        self.assertEqual(mixed.get('error'), 'target_name_id_mismatch', mixed)

    def test_batch_accepts_a_zone_that_only_holds_plots(self):
        out = self.S.resolve_target_tool('영양 1구역')
        self.assertEqual([c['type'] for c in out['children']], ['plot'], out)
        self.assertIsNone(self.S.validate_schedule_batch(
            [{'target_name': '영양 1구역', 'time': '09:00'}], content='점검'))
        self.assertIsNone(self.S.validate_schedule_batch(
            [{'target_id': 'zone-a1', 'time': '09:00'}], content='점검'))

    def test_batch_refuses_a_name_that_disagrees_with_its_id(self):
        err = self.S.validate_schedule_batch(
            [{'target_name': '묘포', 'target_id': 'zone-n1', 'time': '09:00'}], content='점검')
        self.assertEqual(err.get('error'), 'target_name_id_mismatch', err)
        self.assertEqual(err['mismatched_entries'][0]['id_points_to']['name'], '1구역')
        # 모호한 이름 + 그 후보 중 하나의 id, 안팎 같은 이름의 안쪽 id 는 같은 것이다.
        self.assertIsNone(self.S.validate_schedule_batch(
            [{'target_name': 'A동', 'target_id': 'zone-t2', 'time': '09:00'},
             {'target_name': '묘포', 'target_id': 'fac-c', 'time': '10:00'}], content='점검'))
        unknown = self.S.validate_schedule_batch(
            [{'target_id': 'no-such-thing', 'time': '09:00'}], content='점검')
        self.assertEqual(unknown.get('error'), 'target_not_found', unknown)

    def test_batch_finds_duplicates_by_resolved_target(self):
        for entries in (
                [{'target_id': 'zone-t1', 'time': '09:00'},
                 {'target_id': 'zone-t1', 'time': '10:00'}],
                [{'target_name': '영양 1구역', 'time': '09:00'},
                 {'target_id': 'zone-a1', 'time': '10:00'}],
                [{'target_name': '영양 1구역', 'time': '09:00'},
                 {'target_name': '영양 1구역', 'time': '10:00'}]):
            err = self.S.validate_schedule_batch(entries, content='점검')
            self.assertEqual(err.get('error'), 'duplicate_target', (entries, err))
        self.assertIsNone(self.S.validate_schedule_batch(
            [{'target_id': 'zone-t1', 'time': '09:00'},
             {'target_id': 'zone-t2', 'time': '10:00'}], content='점검'))

    # ── 장치 부분일치: 여럿이면 되묻는다 ─────────────────────────────────
    def test_a_partial_device_name_matching_several_is_ambiguous(self):
        for q, want in (('TEST 측창', ['in-side', 'out-side1', 'out-side2']),
                        ('SIM 보온', ['out-warm-a1', 'out-warm-a2', 'out-warm-b'])):
            self.assertEqual(self.S._resolve_note_target(q)[:2], (None, 'ambiguous'), q)
            out = self.S.resolve_target_tool(q)
            self.assertEqual(out.get('error'), 'ambiguous_name', (q, out))
            self.assertEqual(self._ids(out), want, q)
            for c in out['candidates']:
                if c.get('use_name'):
                    self.assertEqual(self.S._resolve_note_target(c['use_name'])[0],
                                     c['target_id'], (q, c))
        by_id = {c['target_id']: c for c in self.S.resolve_target_tool('SIM 보온')['candidates']}
        self.assertEqual(by_id['out-warm-b'].get('use_name'), 'SIM 보온 B')
        self.assertNotIn('use_name', by_id['out-warm-a1'])
        self.assertNotIn('use_name', by_id['out-warm-a2'])
        sch = self.S.add_schedule_tool(date='2026-10-01', content='점검', target_name='TEST 측창')
        self.assertEqual(sch.get('error'), 'ambiguous_name', sch)

    def test_a_mapped_device_candidate_says_where_it_is(self):
        out = self.S.resolve_target_tool('MK 펌프')
        self.assertEqual(out.get('error'), 'ambiguous_name', out)
        by_id = {c['target_id']: c for c in out['candidates']}
        self.assertEqual(sorted(by_id), ['mk1-marker', 'mk3-marker', 'out-mk2'])
        self.assertIn('영양', by_id['mk1-marker']['where'])
        self.assertIn('그린', by_id['mk3-marker']['where'])
        for c in out['candidates']:
            self.assertEqual(self.S._resolve_note_target(c['use_name'])[0], c['target_id'], c)

    def test_a_partial_device_name_matching_one_is_that_device(self):
        self.assertEqual(self.S._resolve_note_target('lonely-heater')[:2],
                         ('out-lonely', 'output'))
        self.assertEqual(self.S._resolve_note_target('측창 개도')[:2], ('in-side', 'input'))

    # ── get_local_time ──────────────────────────────────────────────────
    def test_local_time_answers_when_every_candidate_shares_a_timezone(self):
        import pytz
        with mock.patch('aot.utils.device_tz.resolve_location_tz',
                        return_value=pytz.timezone('Asia/Seoul')):
            out = self.S.get_local_time_tool(target_name='육묘장')
        self.assertEqual(out['status'], 'success', out)
        self.assertEqual(out['timezone'], 'Asia/Seoul')
        self.assertEqual(len(out['candidates']), 2)

    def test_local_time_asks_when_candidates_differ_in_timezone(self):
        import pytz

        def tz_for(tid):
            return pytz.timezone('Asia/Tokyo' if tid == 'site-b' else 'Asia/Seoul')
        with mock.patch('aot.utils.device_tz.resolve_location_tz', side_effect=tz_for):
            out = self.S.get_local_time_tool(target_name='육묘장')
        self.assertEqual(out['status'], 'needs_disambiguation', out)
        self.assertEqual(sorted(c['timezone'] for c in out['candidates']),
                         ['Asia/Seoul', 'Asia/Tokyo'])

    # ── 주소 ───────────────────────────────────────────────────────────
    def test_get_address_says_ambiguous_not_not_found(self):
        out = self.S.get_address(target_name='육묘장')
        self.assertEqual(out.get('error'), 'ambiguous_name', out)

    # ── 승인 게이트 ─────────────────────────────────────────────────────
    def test_the_gate_refuses_before_queuing_an_approval(self):
        from aot.databases.models import MCPConfirmation
        from aot.tools import mcp_safety_gate as G
        before = MCPConfirmation.query.count()
        with mock.patch('aot.tools.mcp_auth.role_can_write', return_value=True), \
                mock.patch.object(G, 'is_write_enabled', return_value=True):
            out = G.gate('edit_schedule', {'job_id': 'j', 'target_name': '육묘장'})
        self.assertEqual(out.get('reason_code'), 'ambiguous_target', out)
        self.assertEqual(len(out['candidates']), 2)
        self.assertEqual(MCPConfirmation.query.count(), before)

    def test_the_gate_lets_a_target_id_through_to_approval(self):
        from aot.tools import mcp_safety_gate as G
        self.assertIsNone(G._ambiguous_target_refusal(
            'edit_schedule', {'target_name': '육묘장', 'target_id': 'site-b'}))

    def test_the_approver_sees_the_candidates(self):
        from aot.tools import mcp_safety_gate as G
        text = G._build_human_briefing('edit_schedule', {'target_name': '육묘장'})
        self.assertIn('2 different places', text)
        self.assertIn('영양', text)
        self.assertIn('그린', text)
        self.assertNotIn('could not be matched', text)

    # ── 구글 캘린더 가져오기: 고르지 않고, 그 사실을 남긴다 ─────────────
    def test_an_imported_event_is_not_attached_to_one_of_several_places(self):
        import json
        from aot.ai.services import calendar_sync_service as C
        job = C._build_imported_job(SimpleNamespace(user_id=None),
                                    {'location': '육묘장', 'content': '점검'},
                                    {'summary': '점검'}, None, None)
        self.assertEqual(job.target_id, 'none')
        params = json.loads(job.params_json)
        self.assertEqual(params.get('location_ambiguous'), '육묘장')
        self.assertEqual(len(params.get('location_candidates') or []), 2)

    # ── 에이전트 루프: 후보를 보여 준다 ──────────────────────────────────
    def test_the_agent_loop_offers_the_actual_candidates(self):
        from aot.ai.services.agent_loop_service import AgentLoopService
        fn = AgentLoopService._schedule_ambiguity_gate
        with mock.patch.object(AgentLoopService, '_tool_name',
                               side_effect=lambda a: a.get('tool')):
            q, cands = fn([{'tool': 'add_schedule',
                            'params': {'arguments': {'target_name': '1구역'}}}])
        self.assertEqual(sorted(cands), ['New Design Map 1구역', '영양 1구역'])

    def test_the_agent_loop_maps_a_picked_option_back_to_its_target_id(self):
        from aot.ai.services.agent_loop_service import AgentLoopService
        fn = AgentLoopService._schedule_ambiguity_gate
        with mock.patch.object(AgentLoopService, '_tool_name',
                               side_effect=lambda a: a.get('tool')):
            q, cands = fn([{'tool': 'add_schedule',
                            'params': {'arguments': {'target_name': 'A동'}}}])
            self.assertEqual(len(cands), 2)
            # 보기는 이름으로 되풀리지 않지만, 고르면 그 후보의 id 로 바뀐다.
            for i, lbl in enumerate(cands):
                self.assertIsNone(self.S._resolve_note_target(lbl)[0], lbl)
                self.assertTrue(lbl.endswith('#%d' % (i + 1)), lbl)
            want = {c['target_id'] for c in self.S._ambiguous_places('A동')}
            got = set()
            for lbl in cands:
                args = {'target_name': lbl}
                self.assertIsNone(fn([{'tool': 'add_schedule',
                                       'params': {'arguments': args}}]))
                self.assertNotIn('target_name', args)
                got.add(args['target_id'])
            self.assertEqual(got, want)
            # 번호 모양이라도 보기가 아니면 되묻는다.
            self.assertIsNotNone(fn([{'tool': 'add_schedule', 'params': {
                'arguments': {'target_name': 'A동 (없는 곳) #1'}}}]))


if __name__ == '__main__':
    unittest.main()
