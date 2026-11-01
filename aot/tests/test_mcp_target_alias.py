# coding=utf-8
"""대상 별칭·비슷한 이름·같은 이름 후보 정렬 — MCP 점검 2026-10-28 세션 E.

고정하는 계약:
  1. 별칭은 이름보다 먼저 맞는다 — 위젯 '육묘장' 과 시설 '육묘장' 이 겹쳐도 별칭
     '육묘장 그래프' 는 위젯 하나로 풀리고 matched='alias' 다(2026-10-28 사례).
  2. 별칭 열쇠는 표기만 다른 것을 모은다('육묘장그래프'). 화면 종류(위젯)의 별칭은
     그 종류를 받는 operation 에서만 맞는다.
  3. 한 별칭은 한 대상 — 다른 대상에 이미 있으면 저장하지 않고 알린다. 같은 대상이면
     그대로 성공, 다른 대상의 이름과 같으면 저장하되 경고한다.
  4. 끝내 못 찾으면 글자 하나만 다른 이름을 고르지 않고 함께 준다('선포장' →
     1포장·3포장, '육류장' → 육묘장). 두 글자 이름은 보지 않는다.
  5. 같은 이름 후보는 사용자가 지금 보는 대시보드의 것이 앞이고 on_screen 이 붙는다.
  6. MCP 연산: record.alias_add → add_target_alias(target_id, name), remove.alias_delete →
     delete_target_alias, find.aliases 는 목록(읽기), find.resolve 에 그 대상의 별칭이 실린다.
     안쪽 도구는 옛 tools/list 에 싣지 않는다(도메인 전용).

라이브 DB 를 쓰지 않는다(임시 sqlite).
"""
import json
import os
import tempfile
import unittest
from unittest import mock


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


class TargetAliasTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import Dashboard, GeoMap, GeoShape, Widget

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'alias.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        db.session.add(GeoMap(unique_id='map-g', name='김제'))
        db.session.add(GeoMap(unique_id='map-y', name='영양'))

        def shape(uid, geo, typ, name, geom):
            db.session.add(GeoShape(
                unique_id=uid, geo_id=geo, type=typ,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': geom}))

        shape('site-1', 'map-g', 'site', '1포장', _square(0.0, 0.0, 0.05))
        shape('site-3', 'map-g', 'site', '3포장', _square(0.1, 0.1, 0.05))
        shape('site-n', 'map-y', 'site', '육묘장 대지', _square(0.5, 0.5, 0.05))
        shape('fac-n', 'map-y', 'facility', '육묘장', _square(0.51, 0.51, 0.01))
        db.session.add(Dashboard(unique_id='dash-g', name='김제'))
        db.session.add(Dashboard(unique_id='dash-y', name='영양 보드'))
        db.session.add(Widget(unique_id='w-nur', name='육묘장', tab_id='dash-g',
                              graph_type='graph'))
        db.session.add(Widget(unique_id='w-tg', name='온도', tab_id='dash-g',
                              graph_type='graph'))
        db.session.add(Widget(unique_id='w-ty', name='온도', tab_id='dash-y',
                              graph_type='graph'))
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

    def tearDown(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import TargetAlias
        TargetAlias.query.delete()
        db.session.commit()

    def _target(self, ref, accepts=()):
        from aot.tools.domain import targets
        state, t = targets.resolve(ref, accepts=accepts)
        self.assertEqual('ok', state, (ref, t))
        return t

    def _add(self, alias, ref, accepts=('widget',)):
        from aot.tools.domain import aliases
        return aliases.add(alias, self._target(ref, accepts), user='u-1')

    # 1·2 ─ 별칭이 먼저
    def test_same_name_widget_and_facility_is_ambiguous_without_alias(self):
        from aot.tools.domain import targets
        state, cands = targets.resolve('육묘장', accepts=('widget', 'facility'))
        self.assertEqual('ambiguous', state)
        self.assertEqual({'widget', 'facility'}, {c['kind'] for c in cands})

    def test_alias_resolves_before_names(self):
        from aot.tools.domain import targets
        self.assertEqual('success', self._add('육묘장 그래프', 'w-nur')['status'])
        for said in ('육묘장 그래프', '육묘장그래프', ' 육묘장  그래프 '):
            state, t = targets.resolve(said, accepts=('widget', 'facility'))
            self.assertEqual(('ok', 'w-nur', 'alias', '육묘장 그래프'),
                             (state, t.get('id'), t.get('matched'), t.get('alias')), said)
        # 위젯을 받지 않는 operation 에서는 위젯 별칭이 끼어들지 않는다.
        state, t = targets.resolve('육묘장 그래프', accepts=('facility', 'site'))
        self.assertFalse(state == 'ok' and t.get('id') == 'w-nur', (state, t))

    def test_alias_beats_another_things_exact_name(self):
        from aot.tools.domain import targets
        body = self._add('육묘장', 'w-nur')
        self.assertEqual('success', body['status'])
        self.assertIn('육묘장', body.get('warning', ''))           # 시설 이름과 겹친다
        state, t = targets.resolve('육묘장', accepts=('widget', 'facility'))
        self.assertEqual(('ok', 'w-nur'), (state, t['id']))

    def test_speech_variant_alias_on_a_place(self):
        self._add('산포장', 'site-3', accepts=())
        t = self._target('산포장')
        self.assertEqual(('site', 'site-3', 'alias'), (t['kind'], t['id'], t['matched']))

    # 3 ─ 중복
    def test_duplicate_alias_is_refused_and_same_target_is_fine(self):
        from aot.databases.models import TargetAlias
        self._add('큰밭', 'site-1', accepts=())
        again = self._add('큰 밭', 'site-1', accepts=())
        self.assertEqual(('success', True), (again['status'], again.get('already')))
        other = self._add('큰밭', 'site-3', accepts=())
        self.assertEqual(('error', 'alias_taken'), (other['status'], other['reason_code']))
        self.assertEqual(['site-1'], [e['id'] for e in other['existing']])
        self.assertEqual(1, TargetAlias.query.count())

    def test_alias_of_a_deleted_target_is_replaced(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import TargetAlias
        db.session.add(TargetAlias(alias='옛밭', alias_key='옛밭', target_kind='site',
                                   target_id='gone', created_at=0.0))
        db.session.commit()
        body = self._add('옛밭', 'site-1', accepts=())
        self.assertEqual('success', body['status'])
        self.assertEqual(['site-1'], [r.target_id for r in TargetAlias.query.all()])

    def test_listing_and_delete(self):
        from aot.tools.domain import aliases
        self._add('산포장', 'site-3', accepts=())
        self._add('큰밭', 'site-1', accepts=())
        got = aliases.listing()
        self.assertEqual({'산포장', '큰밭'}, {a['alias'] for a in got['aliases']})
        got = aliases.listing(self._target('3포장'))
        self.assertEqual(['산포장'], [a['alias'] for a in got['aliases']])
        self.assertEqual('alias_not_found', aliases.delete('없는말')['reason_code'])
        self.assertEqual(['산포장'], aliases.delete('산 포장')['deleted'])
        self.assertEqual(1, aliases.listing()['count'])

    # 4 ─ 비슷한 이름
    def test_unknown_name_offers_similar_names_without_picking(self):
        from aot.tools.domain import targets
        state, err = targets.resolve('선포장')
        self.assertEqual('none', state)
        self.assertEqual({'site-1', 'site-3'}, {t['id'] for t in err['similar']})
        self.assertIn('do not pick', err['error'])
        state, err = targets.resolve('육류장')
        self.assertEqual('none', state)
        self.assertIn('fac-n', {t['id'] for t in err.get('similar', ())})
        self.assertEqual([], targets.similar_names('김재'))   # 두 글자는 보지 않는다

    def test_resolve_card_carries_similar_and_alias(self):
        from aot.tools.domain import dispatch
        body = json.loads(dispatch._resolve_card({'target': '선포장'})[0]['text'])
        self.assertEqual('unknown_target', body['reason_code'])
        self.assertEqual({'1포장', '3포장'}, {c['name'] for c in body['similar']})
        self._add('산포장', 'site-3', accepts=())
        body = json.loads(dispatch._resolve_card({'target': '산포장'})[0]['text'])
        self.assertEqual(('alias', '산포장', 'alias'),
                         (body['matched'], body['alias'], body['target']['matched_by']))

    # 5 ─ 지금 보는 대시보드 먼저
    def test_candidates_on_the_viewed_dashboard_come_first(self):
        from aot.tools.domain import targets
        state, cands = targets.resolve('온도', accepts=('widget',))
        self.assertEqual('ambiguous', state)
        for here, first in (({'dash-y'}, 'w-ty'), ({'dash-g'}, 'w-tg')):
            with mock.patch.object(targets, 'viewed_dashboards', return_value=here):
                ranked = targets.rank([dict(c) for c in cands], 'u-1')
            self.assertEqual(first, ranked[0]['id'])
            self.assertTrue(ranked[0].get('on_screen'))
            self.assertFalse(ranked[1].get('on_screen'))
        with mock.patch.object(targets, 'viewed_dashboards', return_value=set()):
            self.assertEqual([c['id'] for c in cands],
                             [c['id'] for c in targets.rank(list(cands), 'u-1')])

    def test_viewed_dashboards_reads_presence(self):
        from aot.tools.domain import targets
        rows = [{'page_kind': 'dashboard', 'page_ref': 'dash-g', 'seen_at': 100.0},
                {'page_kind': 'dashboard', 'page_ref': 'dash-y', 'seen_at': 90.0},
                {'page_kind': 'map', 'page_ref': 'map-g', 'seen_at': 100.0}]
        states = {'dash-g': 'viewing', 'dash-y': 'open', 'map-g': 'viewing'}
        with mock.patch('aot.utils.web_presence.recent', return_value=rows), \
                mock.patch('aot.utils.web_presence.state_of',
                           side_effect=lambda r, now: states[r['page_ref']]):
            self.assertEqual({'dash-g'}, targets.viewed_dashboards('u-1', now=100.0))
        self.assertEqual(set(), targets.viewed_dashboards(None))


    # 6 ─ MCP 연산
    def _plan(self, tool, args):
        from aot.tools.domain import contract, dispatch
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        return dispatch.plan(tool, args)

    def test_alias_add_and_delete_route_to_inner_tools(self):
        v = self._plan('record', {'op': 'alias_add', 'target': '3포장', 'alias': '산포장'})
        self.assertEqual(('call', 'add_target_alias'), v[:2], v)
        self.assertEqual(('site-3', '산포장'), (v[2]['target_id'], v[2]['name']))
        v = self._plan('remove', {'op': 'alias_delete', 'alias': '산포장'})
        self.assertEqual(('call', 'delete_target_alias'), v[:2], v)
        self.assertEqual('산포장', v[2]['name'])
        self.assertNotIn('target_id', v[2])
        # 위젯도 별칭을 받는다 — 같은 이름의 시설과 겹치면 고르지 않고 되묻는다.
        v = self._plan('record', {'op': 'alias_add', 'target': '육묘장', 'alias': '육묘장 그래프'})
        self.assertEqual('refuse', v[0])
        body = json.loads(v[1][0]['text'])
        self.assertEqual({'w-nur', 'fac-n'}, {c['id'] for c in body['candidates']})
        self.assertIn('for a graph, it is the widget', body['message'])

    def test_handlers_save_list_and_delete(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        from aot.tools.domain import dispatch
        got = S.add_target_alias(target_id='w-nur', name='육묘장 그래프')
        self.assertEqual('success', got['status'], got)
        self.assertEqual('unknown_target', S.add_target_alias(target_id='nope', name='x')['reason_code'])
        body = json.loads(dispatch._aliases_card({})[0]['text'])
        self.assertEqual([('육묘장 그래프', 'w-nur')],
                         [(a['alias'], a['target']['id']) for a in body['aliases']])
        body = json.loads(dispatch._aliases_card({'target': '3포장'})[0]['text'])
        self.assertEqual(0, body['count'])
        S.add_target_alias(target_id='site-3', name='산포장')
        body = json.loads(dispatch._resolve_card({'target': '3포장'})[0]['text'])
        self.assertEqual(['산포장'], body.get('aliases'))
        self.assertEqual(['산포장'], S.delete_target_alias(name='산포장', target_id='site-3')['deleted'])
        self.assertIn('record.alias_add', json.loads(
            dispatch._resolve_card({'target': '선포장'})[0]['text'])['error'])

    def test_inner_tools_are_domain_only(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain.contract import catalog
        from aot.tools.mcp_safety_gate import record_write_tools
        for name in ('add_target_alias', 'delete_target_alias'):
            self.assertIn(name, R.DOMAIN_ONLY_TOOLS)
            self.assertIn(name, catalog())
            self.assertIn(name, record_write_tools())          # 기록 쓰기 — 승인 없음
            self.assertNotIn(name, R.approval_required_tools())
            self.assertTrue(R.tool_in_profile(name, R.TOOL_PROFILE_OPERATIONS))

    def test_navigate_to_a_name_that_is_not_a_dashboard_asks_with_routes(self):
        # 2026-10-29 재시험: screen.act(navigate, '육묘장') 이 'No dashboard or tab' 로 끝나
        # 갈 곳이 없었다. 위젯은 그 대시보드로, 시설은 지도 항목으로 — 고르지 않고 되묻는다.
        from aot.tools.domain import targets
        nav = {'op': 'act', 'action': 'navigate', 'target': '육묘장'}
        with mock.patch.object(targets, 'viewed_dashboards', return_value={'dash-g'}):
            v = self._plan('screen', dict(nav))
        self.assertEqual('refuse', v[0])
        body = json.loads(v[1][0]['text'])
        self.assertEqual(('needs_disambiguation', 'ambiguous_target'),
                         (body['status'], body['reason_code']))
        self.assertEqual(['w-nur', 'fac-n'], [c['id'] for c in body['candidates']])
        self.assertTrue(body['candidates'][0]['on_screen'])
        # 보고 있는 대시보드의 위젯은 강조, 아니면 그 대시보드로 간다.
        self.assertEqual("screen(op='act', action='highlight', target='w-nur')",
                         body['candidates'][0]['resend'])
        self.assertEqual("screen(op='act', action='open_map_item', target='fac-n')",
                         body['candidates'][1]['resend'])
        self.assertIn('for a graph, it is the widget', body['message'])
        self.assertIn('ask which one', body['message'])
        # 같은 이름 위젯 둘 — 보는 대시보드의 것이 앞, 각자 제 대시보드로 간다.
        with mock.patch.object(targets, 'viewed_dashboards', return_value={'dash-y'}):
            v = self._plan('screen', dict(nav, target='온도'))
        cands = json.loads(v[1][0]['text'])['candidates']
        self.assertEqual(['w-ty', 'w-tg'], [c['id'] for c in cands])
        self.assertIn("action='highlight', target='w-ty'", cands[0]['resend'])
        self.assertEqual("screen(op='act', action='navigate', page='dashboard', "
                         "target='dash-g')", cands[1]['resend'])
        # 하나뿐이면 예전처럼 next 한 줄이다.
        v = self._plan('screen', dict(nav, target='3포장'))
        body = json.loads(v[1][0]['text'])
        self.assertEqual('unknown_target', body['reason_code'])
        self.assertEqual("screen(op='act', action='open_map_item', target='3포장')",
                         body['next']['resend'])

if __name__ == '__main__':
    unittest.main()
