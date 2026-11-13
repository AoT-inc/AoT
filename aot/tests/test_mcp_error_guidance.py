# coding=utf-8
"""오류·거절 응답이 다음 행동을 바로 알려 준다 — 2026-11-07 MCP 지연 실측 트랙 A (#1·#2·#3·#6).

낭비 턴의 대부분은 오류·거절 뒤 모델이 다른 도구로 돌아가 탐색하는 턴이다. 고정하는 것:

  A1. 안쪽 도구가 예외 없이 `status:error` 로 답해도 원인이 감사 `error` 칸에 남는다
      (길이 상한, UUID·비밀값 가림). 실패 166건 중 162건의 원인이 기록에 없었다.
  A2. `unknown_argument` 거절이 뜻이 같은 인자를 "use X instead" 로, 끝에 `help` 호출 한 줄로 안내한다.
      읽기 op 는 쪽 나누기 어휘(limit·offset)를 몰라도 거절하지 않고 무시한 뒤 `read_as.ignored` 로 알린다.
      쓰기 op 와 다른 인자는 지금처럼 거절한다.
  A3. `unknown_target` 이 쓰기·화면 조작에서도 다음 호출 한 줄(`next.call`)을 싣는다.
  A4. action 을 안 말한 화면 이동도 같은 이름의 대시보드·탭이 겹치면 대시보드로 간다(되묻지 않는다);
      지도·대지가 같은 이름이면 그대로 되묻고, 되묻는 말은 후보의 id 를 다시 넘기게 한다(사용자에게는 path 로 말한다).

도구·인자 이름은 늘리지 않는다 — 기존 응답 칸(`next`·`read_as`)만 쓴다.
"""
import json
import unittest
from unittest import mock


from aot.tools import tool_execution as te


def _plan(tool, args, kind='zone', resolve=None):
    from aot.tools.domain import contract, dispatch
    contract._STATE.update(ok=True, problems=[])

    def default(ref, **kw):
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref),
                      'path': 'map > %s' % ref, 'matched': 'exact'}
    try:
        with mock.patch.object(dispatch.targets, 'resolve', resolve or default), \
                mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
            return dispatch.plan(tool, args)
    finally:
        contract._STATE.clear()


def _text(verdict):
    return json.loads(verdict[1][0]['text'])


# ── A1 ──────────────────────────────────────────────────────────────────────

class FailureNoteTest(unittest.TestCase):

    def test_message_of_an_error_result_is_the_note(self):
        got = te._failure_note(None, {'status': 'error', 'message': 'No plot named 3포장'})
        self.assertEqual('No plot named 3포장', got)

    def test_falls_back_to_reason_code_then_a_bare_word(self):
        self.assertEqual('attach_bad', te._failure_note(None, {'status': 'error', 'reason_code': 'attach_bad'}))
        self.assertEqual('error', te._failure_note(None, {'status': 'error'}))

    def test_uuids_and_secrets_are_hidden_and_length_is_capped(self):
        msg = ('device 3f2b8c1e-aaaa-4bbb-8ccc-1234567890ab failed; api_key=sk_live_ABCDEF token: xyz '
               'Bearer abcdefghijklmnopqrstuvwxyz0123456789ABCD ' + 'x ' * 400)
        got = te._failure_note(None, {'status': 'error', 'message': msg})
        self.assertLessEqual(len(got), 300)
        for leaked in ('3f2b8c1e', 'sk_live', 'xyz', 'abcdefghijklmnop'):
            self.assertNotIn(leaked, got)
        self.assertIn('<id>', got)

    def test_not_for_success_blocked_or_non_dict(self):
        self.assertEqual('', te._failure_note(None, {'status': 'success', 'message': 'ok'}))
        self.assertEqual('', te._failure_note({'status': 'refused'}, {'status': 'error', 'message': 'm'}))
        self.assertEqual('', te._failure_note(None, ['x']))


# 감사 칸 확인은 장부 테스트의 fixture·도우미를 그대로 쓴다.
from aot.tests.test_mcp_quality_ledger import (  # noqa: E402,F401
    _patch_exec, _rows, app)


def test_audit_row_keeps_why_an_inner_tool_failed(app, monkeypatch):
    _patch_exec(monkeypatch, result={'status': 'error', 'message': 'attach: card needs a title'})
    te._execute_tool(app, 'search_devices', {}, agent_id='a')
    row = _rows()[0]
    assert row['error'] == 'attach: card needs a title'
    assert row['result_summary'] == 'error'


def test_audit_row_of_a_success_has_no_error(app, monkeypatch):
    _patch_exec(monkeypatch, result={'status': 'success'})
    te._execute_tool(app, 'search_devices', {}, agent_id='a')
    assert _rows()[0]['error'] == ''


# ── A2 ──────────────────────────────────────────────────────────────────────

class UnknownArgumentTest(unittest.TestCase):

    def test_refusal_names_the_same_meaning_argument_and_ends_with_a_help_call(self):
        # 실측: control 계열이 duration_minutes 를 받지 않는다고 거절됐다 — 그 op 의 시간 인자는 duration.
        from aot.tools.domain import dispatch
        from aot.tools.domain.registry import find_op
        o = find_op(dispatch._ops(), 'control', 'device_set')
        self.assertIn('duration', set(o.args))
        text = dispatch._same_meaning(o, ['duration_minutes', 'duration_seconds'])
        self.assertIn('duration_minutes: use duration instead.', text)
        self.assertIn('duration_seconds: use duration instead.', text)

    def test_search_word_is_pointed_at_query(self):
        v = _plan('find', {'op': 'plots', 'search': '콩'}, kind='map')
        self.assertEqual('refuse', v[0], v)
        self.assertIn('search: use query instead.', _text(v)['message'])

    def test_period_on_an_op_that_takes_none_gets_no_made_up_suggestion_but_a_help_call(self):
        v = _plan('measure', {'op': 'energy', 'target': '3포장', 'period': '7d'}, kind='zone')
        self.assertEqual('refuse', v[0], v)
        body = _text(v)
        self.assertEqual('unknown_argument', body['reason_code'])
        self.assertIn('does not take period', body['message'])
        self.assertNotIn('instead', body['message'])
        self.assertEqual("help(target='measure.energy') lists what it takes", body['next']['call'])

    def test_period_is_pointed_at_the_time_argument_the_op_really_takes(self):
        v = _plan('control', {'op': 'device_set', 'target': 'v1', 'state': 'on', 'period': '15m'},
                  kind='output')
        self.assertEqual('refuse', v[0], v)
        self.assertIn('period: use duration instead.', _text(v)['message'])

    def test_a_read_op_ignores_paging_words_and_says_so(self):
        v = _plan('measure', {'op': 'energy', 'target': '3포장', 'limit': 50, 'offset': 10}, kind='zone')
        self.assertEqual('call', v[0], v)
        inner_args = v[2]
        self.assertNotIn('limit', inner_args)
        self.assertNotIn('offset', inner_args)
        self.assertEqual(['limit', 'offset'], inner_args['_domain_meta']['ignored'])

    def test_a_read_op_still_refuses_other_unknown_arguments(self):
        v = _plan('measure', {'op': 'energy', 'target': '3포장', 'limit': 5, 'bogus': 1}, kind='zone')
        self.assertEqual('refuse', v[0], v)
        msg = _text(v)['message']
        self.assertIn('does not take bogus', msg)
        self.assertNotIn('limit', msg.split('It takes')[0])

    def test_a_write_op_still_refuses_paging_words(self):
        v = _plan('control', {'op': 'device_set', 'target': 'v1', 'state': 'on', 'limit': 5}, kind='output')
        self.assertEqual('refuse', v[0], v)
        self.assertEqual('unknown_argument', _text(v)['reason_code'])
        self.assertIn('does not take limit', _text(v)['message'])

    def test_ignored_words_are_carried_into_the_response_read_as(self):
        from aot.tools.domain import dispatch
        out = [{'type': 'text', 'text': json.dumps({'status': 'success'})}]
        body = json.loads(dispatch._annotate(out, {'ignored': ['limit']})[0]['text'])
        self.assertEqual({'ignored': ['limit']}, body['read_as'])


# ── A3 ──────────────────────────────────────────────────────────────────────

class UnknownTargetNextTest(unittest.TestCase):

    @staticmethod
    def _none(ref, **kw):
        return 'none', {'error': "Nothing named '%s' — no map, place, plot or device has that name." % ref}

    def test_screen_act_unknown_target_carries_the_next_call(self):
        # 실측: screen.act(target="쿠마모토") 46건 — 오류 뒤 모델은 탐색 도구로 돌아갔다.
        v = _plan('screen', {'op': 'act', 'action': 'navigate', 'target': '쿠마모토'}, resolve=self._none)
        self.assertEqual('refuse', v[0], v)
        body = _text(v)
        self.assertEqual('unknown_target', body['reason_code'])
        self.assertIn("find(op='resolve', target=<name>)", body['next']['call'])

    def test_a_write_op_unknown_target_names_where_to_look_for_its_kind(self):
        v = _plan('control', {'op': 'device_set', 'target': '없는밸브', 'state': 'on'}, resolve=self._none)
        self.assertEqual('refuse', v[0], v)
        self.assertIn("find(op='devices', query=<word>)", _text(v)['next']['call'])

    def test_a_read_op_keeps_its_existing_next(self):
        v = _plan('measure', {'op': 'energy', 'target': '쿠마모토'}, resolve=self._none)
        self.assertEqual('refuse', v[0], v)
        self.assertIn("find(op='tree')", _text(v)['next']['call'])


# ── A4 ──────────────────────────────────────────────────────────────────────

class AmbiguousTargetTest(unittest.TestCase):
    DASH = {'kind': 'dashboard', 'id': 'D1', 'name': '김제', 'path': 'dashboard > 김제'}
    IN = {'kind': 'tab', 'id': 'T1', 'name': '김제', 'path': 'input tabs > 김제'}
    OUT = {'kind': 'tab', 'id': 'T2', 'name': '김제', 'path': 'output tabs > 김제'}
    FN = {'kind': 'tab', 'id': 'T3', 'name': '김제', 'path': 'function tabs > 김제'}
    SITE = {'kind': 'site', 'id': 'S1', 'name': '김제', 'path': '김제 > 김제'}

    def _act(self, cands, **extra):
        def resolve(ref, accepts=(), only=None):
            fit = [c for c in cands if only is None or c['kind'] in only]
            return ('ambiguous', fit) if len(fit) > 1 else (('ok', fit[0]) if fit else ('none', {'error': 'x'}))
        return _plan('screen', dict({'op': 'act', 'target': '김제'}, **extra), resolve=resolve)

    def test_four_way_tie_without_an_action_goes_to_the_dashboard(self):
        # 실측: '김제' names 4 different things (dashboard; input tabs; output tabs; function tabs) — 19건.
        for extra in ({}, {'action': 'navigate'}):
            v = self._act([self.DASH, self.IN, self.OUT, self.FN], **extra)
            self.assertNotEqual('refuse', v[0], v)
            self.assertEqual('D1', v[2].get('dashboard'), v[2])
            self.assertIn('went to the dashboard', v[2]['_domain_meta']['why'])

    def test_a_place_with_the_same_name_still_asks(self):
        # 지도는 화면 이동이 받는 종류가 아니라 후보에서 빠진다 — 이동이 받는 대지·시설이 겹칠 때만 되묻는다.
        v = self._act([self.DASH, self.IN, self.SITE])
        self.assertEqual('refuse', v[0], v)
        self.assertEqual('ambiguous_target', _text(v)['reason_code'])

    def test_tabs_alone_still_ask_and_say_which_value_to_pass_back(self):
        v = self._act([self.IN, self.OUT])
        self.assertEqual('refuse', v[0], v)
        body = _text(v)
        self.assertEqual('ambiguous_target', body['reason_code'])
        # 'map > 영양' 같은 종류 접두 경로는 입력으로 풀리지 않는다 — 되넘길 값은 id 다(사용자에게는 path 로 말한다).
        self.assertIn("pass that candidate's id as target", body['message'])
        self.assertEqual(['T1', 'T2'], [c['id'] for c in body['candidates']])
        self.assertEqual(['input tabs > 김제', 'output tabs > 김제'], [c['path'] for c in body['candidates']])
