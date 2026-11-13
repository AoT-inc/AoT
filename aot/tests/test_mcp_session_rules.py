# coding=utf-8
"""지침 의존을 서버 강제·응답 안 시점 지시로 — 설계 docs/design/mcp-domain-surface.md F-16.

claude.ai 는 서버 안내문(instructions)을 모델에 넘기지 않는다. 그래서:
  ① 꼭 할 호출 하나는 응답 맨 앞 `must` 한 줄(선택·카드 권유·사용자 답 뒤 호출은 올리지 않는다).
  ② 세션의 첫 도구 응답에 핵심 규칙(`rules`)을 한 번. 세션 열쇠가 없으면 싣지 않는다.
  ③ 지침은 서버가 강제하는 승인 문장을 빼고, MAP TIME 은 at(사용자가 말한 시각)·focus(답이 가리키는 시각)로.
  ④ 같은 세션의 규칙 위반(예보 직후 지도 시간 직접 이동, 같은 거절 반복)은 그 응답에 교정 한 줄, 세션당 한 번.
  ⑤ 같은 도구·같은 인자의 승인 대기가 살아 있으면 새로 만들지 않고 그 번호를 — 이 대화가 이미 물었으면 다시 묻지 않는다.
"""
import json
import unittest
from unittest import mock

from aot.tools.domain import act_say, session_rules


def _blocks(body):
    return [{'type': 'text', 'text': json.dumps(body, ensure_ascii=False)}]


def _body(out):
    return json.loads(out[0]['text'])


# ── ① must ───────────────────────────────────────────────────────────────────

class MustLineTest(unittest.TestCase):

    def _lead(self, body):
        return _body(act_say.lead(_blocks(body)))

    def test_a_refusal_with_a_resend_puts_that_call_first(self):
        resend = "screen(op='act', action='open_map_item', target='김제 > 3포장')"
        body = self._lead({'status': 'error', 'reason_code': 'unknown_target', 'message': 'x',
                           'next': {'why': 'a site goes with open_map_item', 'resend': resend}})
        self.assertEqual(['must', 'status'], list(body)[:2])
        self.assertEqual(resend, body['must'])
        self.assertEqual('resend', list(body['next'])[0])           # next 안에서도 그 열쇠가 먼저(우선순위만)
        self.assertEqual({'why', 'resend'}, set(body['next']))       # 열쇠 이름은 그대로

    def test_an_argument_refusal_points_to_its_fix_call(self):
        body = self._lead({'status': 'error', 'reason_code': 'unknown_argument', 'message': 'x',
                           'next': {'call': "help(target='control.device_set') lists what it takes"}})
        self.assertEqual("help(target='control.device_set') lists what it takes", body['must'])

    def test_approved_but_not_run_must_run_now(self):
        call = act_say.CONFIRM_RUN % 'c1'
        body = self._lead({'status': 'success', 'next': {'call': call}})
        self.assertEqual(call, body['must'])

    def test_optional_and_waiting_things_are_not_must(self):
        cases = [
            {'status': 'success', 'next': {'call': act_say.CARD_CALL}},                     # 카드(현행 유지)
            {'status': 'success', 'next': {'optional': "screen(op='card', ...)"}},           # 카드 권유
            {'status': 'success', 'next': {'call': "find(op='tree') lists the places"}},     # 성공의 권유
            {'status': 'success', 'next': {'fix': 'record(...)', 'map_time': {'shows': 'x'}}},
            {'status': 'pending_approval', 'next': {'after_user': 'control(...)', 'call': 'x'}},
            {'status': 'not_found', 'say': {'ask': 'Did you mean A?'},
             'next': {'after_user': 'call again', 'resend': 'x(...)'}},                      # 먼저 묻는다
            {'status': 'success'},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertNotIn('must', self._lead(dict(case)))

    def test_non_json_is_untouched(self):
        out = [{'type': 'text', 'text': 'plain'}]
        self.assertIs(out, act_say.lead(out))

    def test_the_frame_exit_adds_it_and_a_rename_keeps_it_first(self):
        from aot.tools.domain import dispatch
        refusal = {'status': 'error', 'reason_code': 'unknown_argument', 'message': 'x',
                   'next': {'call': "help(target='screen.act') lists what it takes"}}
        with mock.patch.object(dispatch, '_run_call_inner', lambda *a, **k: _blocks(refusal)), \
                mock.patch.object(dispatch.renames, 'resolve_call',
                                  lambda t, a, ops: (t, a, {'op': 'old -> act'})):
            out = dispatch._run(None, 'screen', {'op': 'act', 'speed': 3},
                                {'scope_user_uuid': 'u', 'transport': 'mcp_http'})
        body = _body(out)
        self.assertEqual(['must', 'status', 'next', 'renamed'], list(body)[:4])


# ── ②·④ 세션 머리 ─────────────────────────────────────────────────────────────

class SessionHeadTest(unittest.TestCase):

    def setUp(self):
        session_rules.reset()

    def _annotate(self, tool, args, body, key='s1', user='u1', now=0.0):
        return _body(session_rules.annotate(_blocks(body), tool, args, key, user, now=now))

    def test_rules_come_once_on_the_first_response_of_a_session(self):
        first = self._annotate('overview', {}, {'status': 'success', 'x': 1})
        self.assertEqual('rules', list(first)[0])
        self.assertEqual(list(session_rules.RULES), first['rules'])
        self.assertTrue(3 <= len(first['rules']) <= 4)
        text = ' '.join(first['rules'])
        for needle in ('narrate', '1-2 sentences', 'UUID', '`now`', 'at=', 'focus'):
            self.assertIn(needle, text)
        self.assertLess(len(json.dumps(first['rules'])), 450)        # 응답 상한에 견줘 아주 작다(약 100토큰)
        again = self._annotate('overview', {}, {'status': 'success'}, now=1.0)
        self.assertNotIn('rules', again)
        other = self._annotate('overview', {}, {'status': 'success'}, key='s2', now=2.0)
        self.assertIn('rules', other)                                 # 다른 세션은 다시 한 번
        other_user = self._annotate('overview', {}, {'status': 'success'}, user='u2', now=3.0)
        self.assertIn('rules', other_user)                            # 같은 헤더 값이라도 사용자가 다르면 다른 세션

    def test_no_session_key_means_nothing_is_added(self):
        out = _blocks({'status': 'success'})
        self.assertIs(out, session_rules.annotate(out, 'overview', {}, None, 'u1'))

    def test_a_non_json_first_response_waits_for_the_next_one(self):
        out = [{'type': 'text', 'text': 'plain'}]
        self.assertIs(out, session_rules.annotate(out, 'overview', {}, 's1', 'u1', now=0.0))
        self.assertIn('rules', self._annotate('overview', {}, {'status': 'success'}, now=1.0))

    def test_moving_the_map_time_right_after_a_forecast_gets_one_correction(self):
        self._annotate('weather', {'op': 'forecast', 'target': '김제'}, {'status': 'success'}, now=0.0)
        move = {'op': 'act', 'action': 'map_control', 'map_op': 'time', 'value': '2026-11-10T15:00+09:00'}
        body = self._annotate('screen', move, {'status': 'success'}, now=30.0)
        self.assertEqual('correction', list(body)[0])
        self.assertEqual(session_rules.CORRECT_MAP_TIME, body['correction'])
        self.assertIn('at=', body['correction'])
        # 같은 교정은 세션당 한 번.
        self._annotate('weather', {'op': 'forecast', 'target': '김제'}, {'status': 'success'}, now=60.0)
        self.assertNotIn('correction', self._annotate('screen', move, {'status': 'success'}, now=70.0))

    def test_no_correction_when_the_forecast_already_named_the_time(self):
        """at·focus 로 시각을 알렸는데 서버가 못 옮겨(화면 여럿) AI 가 직접 옮긴 것은 위반이 아니다."""
        for args in ({'op': 'forecast', 'target': '김제', 'focus': '15:00'},
                     {'op': 'forecast', 'target': '김제', 'at': 'tomorrow 15:00'}):
            self.setUp()
            self._annotate('weather', args, {'status': 'success'}, now=0.0)
            out = self._annotate('screen', {'op': 'act', 'action': 'map_control', 'map_op': 'time',
                                            'value': '2026-11-11T15:00:00+09:00'}, {'status': 'success'}, now=30.0)
            self.assertNotIn('correction', out)

    def test_an_unknown_focus_does_not_count_as_naming_the_time(self):
        from aot.tools.domain.session_rules import _named_time
        self.assertTrue(_named_time({'focus': 'max'}))
        self.assertTrue(_named_time({'focus': '15:00'}))
        self.assertFalse(_named_time({'focus': 'foo'}))
        self.assertFalse(_named_time({'focus': '25:99'}))

    def test_no_correction_without_a_recent_forecast_or_for_other_screen_acts(self):
        move = {'op': 'act', 'action': 'map_control', 'map_op': 'time', 'value': 'x'}
        self.assertNotIn('correction', self._annotate('screen', move, {'status': 'success'}, now=0.0))
        self._annotate('weather', {'op': 'forecast'}, {'status': 'success'}, now=10.0)
        self.assertNotIn('correction', self._annotate(
            'screen', {'op': 'act', 'action': 'open_map_item'}, {'status': 'success'}, now=20.0))
        late = 10.0 + session_rules.FORECAST_WINDOW_S + 1
        self.assertNotIn('correction', self._annotate('screen', move, {'status': 'success'}, now=late))

    def test_the_same_refusal_twice_gets_one_correction(self):
        args = {'op': 'device_set', 'target': 'v1', 'speed': 3}
        refusal = {'status': 'error', 'reason_code': 'unknown_argument', 'message': 'x',
                   'must': "help(target='control.device_set') lists what it takes",
                   'next': {'call': "help(target='control.device_set') lists what it takes"}}
        self.assertNotIn('correction', self._annotate('control', args, dict(refusal), now=0.0))
        body = self._annotate('control', args, dict(refusal), now=1.0)
        self.assertEqual(['correction', 'must', 'status'], list(body)[:3])   # must 는 교정 바로 뒤, 그대로
        self.assertEqual(session_rules.CORRECT_REPEAT, body['correction'])
        self.assertNotIn('correction', self._annotate('control', args, dict(refusal), now=2.0))

    def test_a_changed_call_or_a_success_between_is_not_a_repeat(self):
        refusal = {'status': 'error', 'reason_code': 'unknown_argument', 'message': 'x'}
        self._annotate('control', {'op': 'device_set', 'speed': 3}, dict(refusal), now=0.0)
        self.assertNotIn('correction', self._annotate(
            'control', {'op': 'device_set', 'speed': 4}, dict(refusal), now=1.0))
        self._annotate('overview', {}, {'status': 'success'}, now=2.0)
        self.assertNotIn('correction', self._annotate(
            'control', {'op': 'device_set', 'speed': 4}, dict(refusal), now=3.0))

    def test_the_transport_adds_it_only_on_the_domain_surface(self):
        from aot import aot_mcp_server as srv
        role = mock.Mock(user_id='u1')
        out = _blocks({'status': 'success'})
        with mock.patch.dict('os.environ', {'AOT_MCP_SURFACE': 'legacy'}):
            self.assertIs(out, srv._session_head(out, 'get_spatial_tree', {}, 's9', role))
        with mock.patch.dict('os.environ', {'AOT_MCP_SURFACE': ''}):
            self.assertIn('rules', _body(srv._session_head(out, 'overview', {}, 's9', role)))
        # 실패는 응답을 막지 않는다.
        with mock.patch.object(session_rules, 'annotate', side_effect=RuntimeError('x')):
            self.assertIs(out, srv._session_head(out, 'overview', {}, 's10', role))


# ── ③ 지침 ───────────────────────────────────────────────────────────────────

class InstructionsTest(unittest.TestCase):

    def test_the_approval_sentence_left_and_must_came_in(self):
        from aot.tools import tool_execution as te
        self.assertNotIn('Ask approval once', te.SPEAKING_RULE)
        self.assertIn('must: do it first', te.SPEAKING_RULE)

    def test_map_time_says_at_for_a_named_time_and_focus_for_the_answer(self):
        from aot.tools import tool_execution as te
        rule = te.MAP_TIME_RULE
        self.assertIn('at=<time>', rule)
        self.assertIn('focus=max|min|rain_start', rule)
        self.assertIn('The server moves the map', rule)
        self.assertLess(rule.index('at=<time>'), rule.index('focus='))
        self.assertNotIn('slider', rule.lower())


# ── ⑤ 승인 중복 ───────────────────────────────────────────────────────────────

class AlreadyAskedTest(unittest.TestCase):
    CID = 'e3a3edb3-21f4-4433-876e-120c47e1b1a5'

    def setUp(self):
        session_rules.reset()

    def _pending(self, already=False, session='s1'):
        from aot.tools.domain import dispatch
        gate_body = {"status": "pending_approval", "reason_code": "awaiting_user", "confirmation_id": self.CID,
                     "tool_name": "operate_device", "confirm_with_user": "동쪽 측창 켜기",
                     "message": "…", "performed": False}
        if already:
            gate_body["already_asked"] = True
        inner_args = {'device_id': 'd1', 'state': 'on'}
        with mock.patch.object(dispatch, 'plan', lambda *a, **k: ('call', 'operate_device', dict(inner_args))), \
                mock.patch('aot.tools.tool_execution._execute_tool',
                           lambda *a, **k: _blocks(gate_body)):
            out = dispatch._run(None, 'control', {'op': 'output_on', 'target': '동쪽 측창'},
                                {'scope_user_uuid': 'u', 'transport': 'mcp_http', 'session_key': session})
        return _body(out)

    def test_the_same_request_again_in_the_same_conversation_waits(self):
        first = self._pending()
        self.assertIn('ask', first['say'])
        again = self._pending(already=True)
        self.assertNotIn('ask', again['say'])
        self.assertIn('Still waiting', again['say']['tell'])
        self.assertEqual(act_say.ALREADY_ASKED_WHY, again['next']['why'])
        self.assertIn('already asked; wait for the user', again['next']['why'])
        self.assertIn(self.CID, again['next']['after_user'])
        self.assertNotIn('already_asked', again)
        self.assertNotIn('confirm_with_user', again)
        self.assertNotIn('must', again)

    def test_a_pending_made_by_another_conversation_is_read_back_here(self):
        self._pending(session='s1')
        here = self._pending(already=True, session='s2')
        self.assertIn('동쪽 측창 켜기', here['say']['ask'])
        self.assertEqual(act_say.APPROVAL_WHY, here['next']['why'])

    def test_without_a_session_key_it_is_read_back_again(self):
        self._pending(session=None)
        here = self._pending(already=True, session=None)
        self.assertIn('ask', here['say'])


# ── ⑤ 게이트: 같은 요청은 같은 번호 ─────────────────────────────────────────────

from aot.tests.test_mcp_record_write_guard import _Fixture  # noqa: E402


class GateReusesTheOpenRequestTest(_Fixture):

    def _ask(self, state='on'):
        return self._call('operate_device', {'device_id': self.output_id, 'state': state}, self._role('Editor'))

    def test_the_same_write_again_returns_the_same_pending_number(self):
        first = self._ask()
        self.assertEqual('pending_approval', first['status'], first)
        self.assertNotIn('already_asked', first)
        again = self._ask()
        self.assertEqual('pending_approval', again['status'], again)
        self.assertEqual(first['confirmation_id'], again['confirmation_id'])
        self.assertTrue(again['already_asked'])
        self.assertIn('Already asked', again['message'])
        self.assertEqual(1, self._mine_confirmations().filter_by(status='pending').count())

    def test_different_arguments_or_a_decided_request_make_a_new_one(self):
        from aot.tools import mcp_safety_gate as gate
        first = self._ask('on')
        other = self._ask('off')
        self.assertNotEqual(first['confirmation_id'], other['confirmation_id'])
        self.assertNotIn('already_asked', other)
        gate.reject(first['confirmation_id'], user_id=self.user_uuids['Editor'])
        renewed = self._ask('on')
        self.assertNotEqual(first['confirmation_id'], renewed['confirmation_id'])
        self.assertNotIn('already_asked', renewed)

    def test_the_same_name_resolved_to_another_device_makes_a_new_request(self):
        """해석된 대상 id 가 다르면(같은 이름이 다른 장치로 풀림) 옛 대기를 재사용하지 않는다."""
        def ask(dev):
            return self._call('operate_device', {'device_id': self.output_id, 'state': 'on',
                                                 '_domain_target': {'kind': 'output', 'id': dev, 'name': '히터'}},
                              self._role('Editor'))
        first = ask('dev-A')
        self.assertEqual('pending_approval', first['status'], first)
        same = ask('dev-A')
        self.assertTrue(same['already_asked'])
        self.assertEqual(first['confirmation_id'], same['confirmation_id'])
        other = ask('dev-B')
        self.assertNotIn('already_asked', other)
        self.assertNotEqual(first['confirmation_id'], other['confirmation_id'])


if __name__ == '__main__':
    unittest.main()
