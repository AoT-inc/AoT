# coding=utf-8
"""2026-11-03 MCP 수정 S5 B — 같은 이름이 여러 곳이면 읽기·화면 이동은 맥락이 하나만 가리킬 때 그것으로 가고 어떻게 골랐는지 말한다.

고정하는 것: ① 지금 보는 대시보드·탭, 지도 화면, 이 대화가 최근 가리킨 대상이 하나만 가리키면 고른다 ② 맥락이 둘 이상이거나 없으면 되묻는다
③ 쓰기(물리 제어 …)는 늘 되묻는다 ④ 응답에 picked_by·say·next(바꾸는 길)가 실린다 ⑤ 사용자의 별칭이 먼저다(해석기).
"""
import json
import unittest
from unittest import mock

from aot.tools.domain import act_say, dispatch, targets
from aot.tools.domain.registry import Op

_READ = Op('overview', 'place', 'Place', {'site': 'get_place', 'zone': 'get_place'}, 'read',
           target_arg={'site': 'place', 'zone': 'place'})
_WRITE = Op('control', 'device_set', 'Set', {'site': 'set_x', 'zone': 'set_x'}, 'physical',
            target_arg={'site': 'place', 'zone': 'place'})
_NAV = Op('screen', 'act', 'Change the page', {'dashboard': 'screen_action', 'tab': 'screen_action', 'map': 'screen_action'},
          'screen', target_arg={'dashboard': 'dashboard', 'tab': 'tab', 'map': 'item'},
          extra_args={'action': 'what to do'})


def _c(kind, id_, name='영양'):
    return {'kind': kind, 'id': id_, 'name': name, 'path': '%s > %s' % (kind, name)}


SITE, ZONE = _c('site', 's1'), _c('zone', 'z1')


def _plan(tool, op, ops, *, cands, here=(), tabs=(), kinds=(), recent=(), user='u-1', args=None):
    with mock.patch.object(dispatch.targets, 'resolve', lambda ref, accepts=(), only=None: ('ambiguous', [dict(c) for c in cands])), \
            mock.patch.object(targets, 'viewed_dashboards', return_value=set(here)), \
            mock.patch.object(targets, 'viewed_tabs', return_value=set(tabs)), \
            mock.patch.object(targets, 'viewed_page_kinds', return_value=set(kinds)), \
            mock.patch.object(targets, 'recent_ids', return_value=set(recent)):
        return dispatch.plan(tool, dict({'op': op, 'target': '영양'}, **(args or {})), ops=ops, user=user)


class ContextPick(unittest.TestCase):

    def test_no_context_asks_as_before(self):
        v = _plan('overview', 'place', [_READ], cands=[SITE, ZONE])
        self.assertEqual('refuse', v[0])
        self.assertIn('needs_disambiguation', v[1][0]['text'])

    def test_recent_target_picks_and_says_how(self):
        v = _plan('overview', 'place', [_READ], cands=[SITE, ZONE], recent=['z1'])
        self.assertEqual('call', v[0])
        self.assertEqual('z1', v[2]['place'])
        meta = v[2][dispatch.META_KEY]
        self.assertEqual('context', meta['picked_by'])
        self.assertEqual('recent', meta['picked'][0]['by'])
        self.assertEqual(['s1'], [o['id'] for o in meta['picked'][0]['others']])

    def test_two_recent_candidates_still_ask(self):
        v = _plan('overview', 'place', [_READ], cands=[SITE, ZONE], recent=['z1', 's1'])
        self.assertEqual('refuse', v[0])

    def test_nav_rule_dashboard_over_tab_is_unchanged(self):
        # 후보가 대시보드와 탭뿐이면 지금처럼 대시보드(사용자 결정 2026-10-26) — 탭을 보는 중이어도 이미 보는 곳으로 가지 않는다.
        from aot.tools.domain.registry_data import OPS
        dash, tab = _c('dashboard', 'd1'), _c('tab', 't1')
        v = _plan('screen', 'act', list(OPS), cands=[dash, tab], tabs=['t1'], args={'action': 'navigate'})
        self.assertEqual('call', v[0])
        self.assertIn('d1', json.dumps(v[2]))
        self.assertNotIn('t1', json.dumps(v[2]))

    def test_map_page_picks_the_map_among_other_kinds(self):
        dash, mp = _c('dashboard', 'd1'), _c('map', 'm1')
        nav = Op('overview', 'place', 'x', {'dashboard': 'g', 'map': 'g'}, 'read',
                 target_arg={'dashboard': 'a', 'map': 'a'})
        v = _plan('overview', 'place', [nav], cands=[dash, mp], kinds=['map'])
        self.assertEqual('call', v[0])
        self.assertEqual('m1', v[2]['a'])
        self.assertEqual('screen', v[2][dispatch.META_KEY]['picked'][0]['by'])

    def test_screen_beats_recent_and_two_on_screen_stop(self):
        d1, d2 = _c('dashboard', 'd1'), _c('dashboard', 'd2')
        op = Op('overview', 'place', 'x', {'dashboard': 'g'}, 'read', target_arg={'dashboard': 'a'})
        self.assertEqual('refuse', _plan('overview', 'place', [op], cands=[d1, d2], here=['d1', 'd2'], recent=['d1'])[0])
        v = _plan('overview', 'place', [op], cands=[d1, d2], here=['d1'], recent=['d2'])
        self.assertEqual('d1', v[2]['a'])

    def test_writes_never_pick(self):
        v = _plan('control', 'device_set', [_WRITE], cands=[SITE, ZONE], recent=['z1'], here=['s1'])
        self.assertEqual('refuse', v[0])
        self.assertIn('needs_disambiguation', v[1][0]['text'])

    def test_no_user_no_context(self):
        v = _plan('overview', 'place', [_READ], cands=[SITE, ZONE], recent=['z1'], user=None)
        self.assertEqual('refuse', v[0])


class RememberedTargets(unittest.TestCase):

    def test_remember_and_expire(self):
        targets._RECENT.clear()
        targets.remember('u', 's', [SITE], now=100.0)
        self.assertEqual({'s1'}, targets.recent_ids('u', 's', now=200.0))
        self.assertEqual(set(), targets.recent_ids('u', 's', now=100.0 + targets._RECENT_TTL_S + 1))
        self.assertEqual(set(), targets.recent_ids('u', 'other', now=200.0))
        targets._RECENT.clear()

    def test_explicit_resolution_is_remembered_by_plan(self):
        targets._RECENT.clear()
        with mock.patch.object(dispatch.targets, 'resolve', lambda ref, accepts=(), only=None: ('ok', dict(SITE))):
            dispatch.plan('overview', {'op': 'place', 'target': '영양'}, ops=[_READ], user='u-1', session='sess')
        self.assertIn('s1', targets.recent_ids('u-1', 'sess'))
        targets._RECENT.clear()


class ResponseShape(unittest.TestCase):

    def _body(self, tool, op):
        picks = [{"asked": "영양", "as": {"kind": "zone", "name": "영양", "id": "z1", "path": "zone > 영양"},
                  "by": "recent", "others": [{"kind": "site", "name": "영양", "id": "s1", "path": "site > 영양"}]}]
        out = [{'type': 'text', 'text': json.dumps({'status': 'success', 'value': 1,
                                                   'read_as': {'picked_by': 'context', 'picked': picks}})}]
        return json.loads(act_say.shape(out, tool, op)[0]['text'])

    def test_say_and_next_come_before_data_for_any_op(self):
        for tool, op in (('overview', 'place'), ('screen', 'act'), ('weather', 'forecast')):
            body = self._body(tool, op)
            keys = list(body)
            self.assertEqual('status', keys[0], (tool, op))
            self.assertLess(keys.index('say'), keys.index('next'))
            self.assertLess(keys.index('next'), keys.index('value'))
            self.assertIn("I took it to be zone 영양", body['say']['tell'])
            self.assertIn('s1', body['next']['after_user'])

    def test_no_pick_no_change(self):
        out = [{'type': 'text', 'text': json.dumps({'status': 'success', 'value': 1})}]
        self.assertEqual(out, act_say.shape(out, 'overview', 'place'))
