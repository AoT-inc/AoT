# coding=utf-8
"""응답 계약(data / next / say) — 설계 plans/mcp_act_say_split_design.md §2·§5-1, 사용자 결정 2026-10-29.

고정하는 계약(LLM 없음, 결정론적):
  1. 시범 op 5개(find.resolve, screen.act, overview.failure, record.note, weather.forecast)의 응답은
     ``status`` → ``say``(있으면) → ``next``(있으면) → 나머지 data 순서다.
  2. ``say`` 는 사용자에게 전할 뜻만 담는다 — 호출 문법·도구 이름·id·단계 중계·'말하지 마라' 꼬리가 없고 짧다.
  3. ``next`` 는 기계용이다 — 할 호출·사용자 답 뒤의 호출·짧은 이유. 사용자에게 할 말("ask the user…")이 없다.
  4. 보통 성공에는 say 가 없다. 시범 밖 op 와 승인 대기 응답은 그대로다.
  5. 서버 안내문은 SPEAKING 이 맨 앞이고 클라이언트가 자르는 2,048자 안이다. 도구 머리의 말하기 규칙은 overview 한 곳뿐이다.
"""
import json
import re
import unittest
from unittest import mock

from aot.tools.domain import act_say


#: say 에 있으면 안 되는 것 — 호출 문법, 도구 이름(도메인·안쪽), 서술 동사, 꼬리.
_DOMAIN_TOOLS = ('overview', 'measure', 'weather', 'find', 'detail', 'records', 'screen_view', 'help',
                 'control', 'record', 'cultivate', 'configure', 'screen', 'remove')
_SAY_BAD = re.compile(
    r"op\s*=|\b(?:%s)\s*\(|\b[a-z]+_[a-z_]+\b|\btools?\b|\bcall(?:s|ed|ing)?\b|\bresend\b|"
    r"Internal note|do not tell|don't mention|never mention|narrate" % "|".join(_DOMAIN_TOOLS), re.I)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
#: next 안에 사용자에게 하라는 말이 섞이면 안 된다(행동·말하기 섞임).
_NEXT_SPEECH = re.compile(r"\bask (?:the user|which)|\btell the user|\bin the user's language|Internal note", re.I)
_TAILS = ('Internal note:', 'Do not tell the user about this')


def _words(say):
    return sum(len(str(v).split()) for v in say.values())


class ContractShapeMixin:
    """모든 시범 응답에 공통으로 거는 검사."""

    def assertContract(self, body, say=None):
        keys = list(body)
        if keys and keys[0] == 'must':
            # 꼭 할 호출 하나(F-16 ①)는 맨 앞 — 그 뒤는 같은 계약이다.
            self.assertIsInstance(body['must'], str)
            keys = keys[1:]
        self.assertEqual('status', keys[0], body)
        if 'say' in body:
            self.assertEqual('say', keys[1], body)
            s = body['say']
            self.assertTrue(s and set(s) <= {'tell', 'ask', 'avoid'}, s)
            for k, v in s.items():
                self.assertIsInstance(v, str, k)
                self.assertIsNone(_SAY_BAD.search(v), (k, v))
                self.assertIsNone(_UUID.search(v), (k, v))
            self.assertLessEqual(_words(s), 30, s)
        if 'next' in body:
            self.assertEqual('next', keys[2 if 'say' in body else 1], body)
            self.assertIsNone(_NEXT_SPEECH.search(json.dumps(body['next'], ensure_ascii=False)), body['next'])
        for k, v in body.items():
            if isinstance(v, str):
                for tail in _TAILS:
                    self.assertNotIn(tail, v, k)
        if say is False:
            self.assertNotIn('say', body)
        elif say:
            self.assertIn(say, body.get('say', {}), body)


def _shape(tool, op, body):
    out = act_say.shape([{'type': 'text', 'text': json.dumps(body, ensure_ascii=False)}], tool, op)
    return json.loads(out[0]['text'])


class FindResolveTest(ContractShapeMixin, unittest.TestCase):

    def _resolve(self, state, got):
        from aot.tools.domain import dispatch
        with mock.patch.object(dispatch.targets, 'resolve', lambda ref, **kw: (state, got)), \
                mock.patch.object(dispatch.targets, 'rank', lambda cands, user=None: list(cands)), \
                mock.patch.object(dispatch, '_children_of', lambda t: []), \
                mock.patch('aot.tools.domain.aliases.listing', lambda t=None: {'aliases': []}), \
                mock.patch('aot.tools.screen_follow.follow_resolved', lambda *a, **k: None):
            out = dispatch._run(None, 'find', {'op': 'resolve', 'target': '육묘장'},
                                {'scope_user_uuid': 'u', 'transport': 'mcp_http'})
        return json.loads(out[0]['text'])

    def test_one_match_says_nothing(self):
        body = self._resolve('ok', {'kind': 'facility', 'id': 'F1', 'name': '육묘장',
                                    'path': '김제 > 육묘장'})
        self.assertContract(body, say=False)
        self.assertEqual('success', body['status'])
        self.assertEqual('F1', body['target']['id'])

    def test_several_matches_ask_by_name_and_wait(self):
        cands = [{'kind': 'facility', 'id': 'F1', 'name': '육묘장', 'path': '김제 > 육묘장'},
                 {'kind': 'widget', 'id': 'W1', 'name': '육묘장', 'path': 'dashboard 김제 > 육묘장',
                  'on_screen': True}]
        body = self._resolve('ambiguous', cands)
        self.assertContract(body, say='ask')
        self.assertEqual('needs_disambiguation', body['status'])
        self.assertIn('김제 > 육묘장', body['say']['ask'])
        self.assertNotIn('message', body)                               # 같은 말 반복 없음
        self.assertIn('after_user', body['next'])
        self.assertIn('a graph is the widget', body['next']['why'])     # 해석 도움은 기계 이유로
        self.assertEqual(['F1', 'W1'], [c['id'] for c in body['candidates']])   # id 는 data 에만

    def test_unknown_name_with_similar_asks_and_picks_nothing(self):
        err = {"error": "Nothing named '선포장' — no map, place, plot or device has that name. "
                        "Similar names: '3포장', '1포장' — the word may have been misheard. Ask the user "
                        "which one they mean; do not pick. If it is a name they use, record.alias_add saves it.",
               "similar": [{'kind': 'site', 'id': 's3', 'name': '3포장', 'path': '김제 > 3포장'},
                           {'kind': 'site', 'id': 's1', 'name': '1포장', 'path': '김제 > 1포장'}]}
        body = self._resolve('none', err)
        self.assertContract(body, say='ask')
        self.assertEqual('not_found', body['status'])
        self.assertEqual("Did you mean '3포장' or '1포장'?", body['say']['ask'])
        self.assertNotIn('Ask the user', body['error'])
        self.assertTrue(body['error'].startswith("Nothing named '선포장'"))
        self.assertIn('alias_add', body['next']['why'])

    def test_unknown_name_without_similar_tells(self):
        body = self._resolve('none', {"error": "Nothing named 'zz' — no map, place, plot or device has that name."})
        self.assertContract(body, say='tell')
        self.assertEqual("Nothing named 'zz'.", body['say']['tell'])


class ScreenActTest(ContractShapeMixin, unittest.TestCase):

    def test_screen_permission_is_asked_and_the_token_goes_to_next(self):
        body = _shape('screen', 'act', {
            "status": "needs_confirmation", "confirmed": False, "confirm_token": "tok123",
            "screen": "Mac — dashboard '영양'", "action": "open the map item 3포장",
            "ask_user": "Ask the user: do this on Mac? (open)",
            "note": "An [Allow] card is also shown on that screen; if the user taps it, it runs without "
                    "another call. Once the user agrees in the conversation, call screen_action with only "
                    "confirm_token."})
        self.assertContract(body, say='ask')
        self.assertNotIn('ask_user', body)
        self.assertNotIn('note', body)
        self.assertIn("confirm_token='tok123'", body['next']['after_user'])
        self.assertIn("Mac — dashboard '영양'", body['say']['ask'])

    def test_queued_tells_the_link_and_never_done(self):
        body = _shape('screen', 'act', {
            "status": "queued", "action": "open", "link": "https://x/y",
            "note": "Sent. The screen has not run it yet … If the user is on a phone talking to you in "
                    "another app, give them this link to tap."})
        self.assertContract(body, say='tell')
        self.assertEqual('done', body['say']['avoid'])
        self.assertIn('tap the link', body['say']['tell'])
        self.assertEqual('https://x/y', body['link'])

    def test_sent_is_a_machine_note(self):
        body = _shape('screen', 'act', {"status": "sent", "action": "open",
                                        "note": "The screen has not confirmed it yet; …"})
        self.assertContract(body, say=False)
        self.assertIn('screen_view', body['next']['why'])

    def test_expired_and_rejected_say_not_done(self):
        for st in ('expired', 'rejected'):
            with self.subTest(status=st):
                body = _shape('screen', 'act', {"status": st, "note": "Not done: declined. Ask again if still wanted."})
                self.assertContract(body, say='tell')
                self.assertTrue(body['say']['tell'].startswith('Not done'))
                self.assertEqual('done', body['say']['avoid'])

    def test_partial_tells_what_happened(self):
        body = _shape('screen', 'act', {"status": "partial", "done": "the window opened; the tab did not",
                                        "message": "tab x missing"})
        self.assertContract(body, say='tell')
        self.assertIn('the tab did not', body['say']['tell'])

    def test_plain_success_says_nothing_and_loading_is_machine(self):
        body = _shape('screen', 'act', {"status": "success", "done": "navigate", "message": None,
                                        "note": "The page is loading; get_screen may still show the old page."})
        self.assertContract(body, say=False)
        self.assertIn('loading', body['next']['why'])
        self.assertNotIn('note', body)

    def test_the_old_say_after_a_time_move_becomes_next(self):
        body = _shape('screen', 'act', {"status": "success", "done": "map time",
                                        "say": "Done. Now answer with the forecast values themselves, in "
                                               "the user's language; never mention the slider move or this note."})
        self.assertContract(body, say=False)
        self.assertIn('answer with the values', body['next']['why'])

    def test_settings_dialog_tells_and_asks(self):
        body = _shape('screen', 'act', {
            "status": "error", "reason_code": "settings_dialog_open",
            "error": "A settings window ('Sensor options') is open on that screen, so the page was not changed: "
                     "leaving would discard what the user is entering. Ask the user, or send action=close_modal "
                     "first (unsaved values are lost) and then navigate again."})
        self.assertContract(body, say='ask')
        self.assertIn("'Sensor options'", body['say']['tell'])
        self.assertIn('close_modal', body['next']['after_user'])
        self.assertNotIn('Ask the user', body['error'])

    def test_wrong_action_with_several_routes_asks_once(self):
        """육묘장 navigate(2026-10-29 재시험) — '물어보고(말) resend 를 보내라(행동)' 가 한 문단이던 응답."""
        from aot.tools.domain import dispatch
        refusal = dispatch._error(
            "No dashboard or tab named '육묘장'. '육묘장' names 2 things that open another way — ask which one "
            "the user means, then send its resend. If more than one screen is open, add screen='<id>' "
            "(the screen value from screen_view op=current).",
            status="needs_disambiguation", reason_code='ambiguous_target',
            candidates=[{'kind': 'widget', 'name': '육묘장', 'id': 'w-nur', 'path': 'widget > 육묘장',
                         'on_screen': True,
                         'resend': "screen(op='act', action='highlight', target='w-nur')"},
                        {'kind': 'facility', 'name': '육묘장', 'id': 'fac-n', 'path': '김제 > 육묘장',
                         'resend': "screen(op='act', action='open_map_item', target='fac-n')"}],
            next={"why": "'육묘장' names 2 things that open another way — ask which one the user means, then "
                         "send its resend. If more than one screen is open, add screen='<id>'."})
        with mock.patch.object(dispatch, 'plan', lambda *a, **k: ('refuse', refusal)), \
                mock.patch.object(dispatch, '_audit_refusal', lambda *a, **k: None):
            out = dispatch._run(None, 'screen', {'op': 'act', 'action': 'navigate', 'target': '육묘장'}, {})
        body = json.loads(out[0]['text'])
        self.assertContract(body, say='ask')
        self.assertEqual("Which one: widget > 육묘장; 김제 > 육묘장?", body['say']['ask'])
        self.assertEqual("send the chosen candidate's resend", body['next']['after_user'])
        self.assertIn("screen='<id>'", body['next']['why'])
        self.assertNotIn('message', body)
        self.assertTrue(all(c.get('resend') for c in body['candidates']))

    def test_wrong_action_with_one_route_resends_silently(self):
        body = _shape('screen', 'act', {
            "status": "error", "reason_code": "unknown_target",
            "message": "'3포장' is a site, not a dashboard or tab. A site goes with action=open_map_item, "
                       "not action=navigate.",
            "next": {"why": "A site goes with action=open_map_item, not action=navigate.",
                     "resend": "screen(op='act', action='open_map_item', target='김제 > 3포장')"}})
        self.assertContract(body, say=False)
        self.assertEqual("'3포장' is a site, not a dashboard or tab.", body['message'])
        self.assertIn('open_map_item', body['next']['resend'])


class FailureTest(ContractShapeMixin, unittest.TestCase):
    _UNKNOWN = ("MCP server status is not readable from this process (unknown, not offline); a call that "
                "just answered means the server is reachable.")

    def test_unreadable_server_with_no_failures_is_unknown_not_offline(self):
        body = _shape('overview', 'failure', {
            "failure_summary": [self._UNKNOWN], "failed_tasks": [],
            "mcp_status": [{"name": "AoT", "is_degraded": None}],
            "recommendation": "Check the MCP server status, restart the server, or verify device connectivity.",
            "lookback_minutes": 60})
        self.assertContract(body, say='tell')
        self.assertEqual('unknown', body['status'])
        self.assertEqual('offline', body['say']['avoid'])
        self.assertIn('unknown, not offline', body['say']['tell'])
        self.assertNotIn('recommendation', body)
        self.assertEqual([], body['failure_summary'])

    def test_no_failures_is_plain_success(self):
        body = _shape('overview', 'failure', {
            "failure_summary": ["Could not identify a specific error cause."], "failed_tasks": [],
            "mcp_status": [{"name": "AoT", "is_degraded": False}],
            "recommendation": "No recent failure records. Check device power and network connectivity."})
        self.assertContract(body, say=False)
        self.assertEqual('success', body['status'])
        self.assertEqual([], body['failure_summary'])
        self.assertNotIn('recommendation', body)

    def test_real_failures_keep_the_recommendation_as_data(self):
        body = _shape('overview', 'failure', {
            "failure_summary": ["[Valve] Physical execution failed: timeout"], "failed_tasks": [{}],
            "mcp_status": [], "recommendation": "Check the MCP server status."})
        self.assertContract(body)
        self.assertEqual(["[Valve] Physical execution failed: timeout"], body['failure_summary'])
        self.assertIn('recommendation', body)


class NoteWriteTest(ContractShapeMixin, unittest.TestCase):

    def test_general_memo_tells_no_place(self):
        body = _shape('record', 'note', {
            "note_id": "n1", "name": "점검", "status": "created", "no_location": True,
            "note_hint": "Saved as a general memo with no location; it will not appear on any device.",
            "attached_links": 1})
        self.assertContract(body, say='tell')
        self.assertEqual('created', body['status'])
        self.assertTrue(body['no_location'])
        self.assertNotIn('note_hint', body)
        self.assertIn('no place', body['say']['tell'])

    def test_note_on_a_place_says_where_so_a_wrong_place_is_caught(self):
        body = _shape('record', 'note', {"note_id": "n1", "status": "created", "target_id": "z",
                                         "attached_to": "3포장"})
        self.assertContract(body, say='tell')
        self.assertIn('3포장', body['say']['tell'])

    def test_a_written_note_hands_back_its_id_and_the_fix_calls(self):
        body = _shape('record', 'note', {"note_id": "n1", "status": "created", "attached_to": "3포장"})
        self.assertIn("target='n1'", body['next']['fix'])
        self.assertIn("op='delete', kind='note'", body['next']['fix'])
        self.assertEqual('n1', body['note_id'])

    def test_a_moved_or_hidden_note_says_so(self):
        moved = _shape('record', 'note', {"note_id": "n1", "status": "modified", "changed": ["target"],
                                          "attached_to": "4포장"})
        self.assertIn('Moved to 4포장', moved['say']['tell'])
        hidden = _shape('record', 'note', {"note_id": "n1", "status": "archived", "changed": ["archive"]})
        self.assertIn('Hidden', hidden['say']['tell'])


class ForecastTest(ContractShapeMixin, unittest.TestCase):

    def test_card_hint_becomes_a_next_call(self):
        from aot.utils import ai_screen_cards as cards
        body = _shape('weather', 'forecast', {"card_hint": cards.AUTO_CARD_HINT, "status": "success",
                                              "summary": {"temp": {"max": 20}}})
        self.assertContract(body, say=False)
        self.assertNotIn('card_hint', body)
        self.assertTrue(body['next']['call'].startswith("screen(op='card'"))

    def test_fanned_out_results_lose_their_card_hints(self):
        body = _shape('weather', 'forecast', {"status": "success", "results": [
            {"target": {"name": "a"}, "result": {"card_hint": "x", "summary": {}}},
            {"target": {"name": "b"}, "result": {"card_hint": "x", "summary": {}}}]})
        self.assertContract(body, say=False)
        self.assertNotIn('card_hint', json.dumps(body))
        self.assertIn('call', body['next'])

    def test_map_time_is_a_machine_slot_not_a_hint(self):
        from aot.tools import screen_follow as sf
        from aot.tools.domain import dispatch
        ctx = {'scope_user_uuid': 'u-dom', 'transport': 'mcp_http', 'tool_profile': 'operations'}
        out = [{'type': 'text', 'text': json.dumps({'status': 'success', 'forecasts': [{}]})}]
        with mock.patch.object(sf, 'follow_time',
                               lambda *a, **k: {'slider': 'sent to 2026-10-28 15:00 (Asia/Seoul)'}):
            got = dispatch._follow('weather', out, None, ctx, None, None, {'op': 'forecast'})
        body = json.loads(act_say.shape(got, 'weather', 'forecast')[0]['text'])
        self.assertContract(body, say=False)
        self.assertNotIn('time_hint', body)
        mt = body['next']['map_time']
        self.assertEqual('2026-10-28 15:00 (Asia/Seoul)', mt['shows'])
        self.assertIn("map_op='time'", mt['if_answer_names_another_time'])
        with mock.patch.object(sf, 'follow_time',
                               lambda *a, **k: {'slider': 'not moved: another forecast just set a different time'}):
            got = dispatch._follow('weather', out, None, ctx, None, None, {'op': 'forecast'})
        self.assertEqual('unknown', json.loads(got[0]['text'])['next']['map_time']['shows'])


class ScopeTest(unittest.TestCase):

    def test_ops_outside_the_pilot_are_untouched(self):
        raw = {"note": "x", "status": "success"}                     # card_hint 는 OldCardHintTest
        out = [{'type': 'text', 'text': json.dumps(raw)}]
        self.assertIs(out, act_say.shape(out, 'overview', 'place'))
        self.assertEqual(6, len(act_say.PILOT))          # 시범 5 + control.confirm(승인 결과)

    def test_a_pending_approval_the_frame_did_not_annotate_is_untouched(self):
        raw = {"status": "pending_approval", "confirmation_id": "c", "next": {"1_ask": "x"}, "message": "m"}
        out = [{'type': 'text', 'text': json.dumps(raw)}]
        self.assertIs(out, act_say.shape(out, 'screen', 'act'))

    def test_non_json_is_untouched(self):
        out = [{'type': 'text', 'text': 'plain'}]
        self.assertIs(out, act_say.shape(out, 'find', 'resolve'))


class ApprovalTest(ContractShapeMixin, unittest.TestCase):
    """승인 대기 응답(2단계, 2026-10-29) — claude.ai 는 서버 안내문을 받지 않아 승인 규칙을 응답이 전한다.
    승인 흐름(토큰·만료·되읽기·승인 = 실행)은 그대로이고 글이 놓이는 칸만 바뀐다."""

    CID = 'e3a3edb3-21f4-4433-876e-120c47e1b1a5'

    def _pending(self, read_back='동쪽 측창 켜기 (duration_seconds=30)', op='output_on', extra=None):
        from aot.tools.domain import dispatch
        gate_body = {
            "status": "pending_approval", "reason_code": "awaiting_user", "confirmation_id": self.CID,
            "tool_name": "operate_device", "expires_in_sec": 900, "execute_within_sec": 300,
            "message": "This tool changes system state, so it needs user approval. … Internal note: never quote.",
            "call_state": "pending_approval", "performed": False,
            "_reading": ["Not done yet - it is waiting for a person to approve it. Say so; do not describe it as done."]}
        if read_back is not None:
            gate_body["confirm_with_user"] = read_back
        gate_body.update(extra or {})
        inner_args = {'device_id': 'd1', 'state': 'on', 'duration_seconds': 30}
        with mock.patch.object(dispatch, 'plan', lambda *a, **k: ('call', 'operate_device', dict(inner_args))), \
                mock.patch('aot.tools.tool_execution._execute_tool',
                           lambda *a, **k: [{'type': 'text', 'text': json.dumps(gate_body, ensure_ascii=False)}]):
            out = dispatch._run(None, 'control', {'op': op, 'target': '동쪽 측창', 'duration': 30},
                                {'scope_user_uuid': 'u', 'transport': 'mcp_http'})
        return json.loads(out[0]['text'])

    def test_read_back_is_asked_first_and_the_approve_call_waits_for_the_user(self):
        body = self._pending()
        self.assertContract(body, say='ask')
        self.assertEqual(['status', 'say', 'next'], list(body)[:3])
        self.assertEqual('pending_approval', body['status'])
        ask = body['say']['ask']
        self.assertIn('동쪽 측창 켜기', ask)                         # 서버가 푼 대상 이름
        self.assertIn('duration seconds 30', ask)                    # 값도 되읽는다(호출 문법 없이)
        self.assertIn('please approve', ask)
        self.assertEqual('done', body['say']['avoid'])
        nxt = body['next']
        self.assertEqual("control(op='confirm', target='%s', decision='approve')" % self.CID, nxt['after_user'])
        self.assertIn("decision='reject'", nxt['if_no'])
        self.assertIn("_confirmation_id='%s'" % self.CID, nxt['if_not_run'])
        self.assertEqual({'target': '동쪽 측창', 'duration': 30}, nxt['same_arguments'])

    def test_the_safety_sentences_moved_not_dropped(self):
        body = self._pending()
        why = body['next']['why']
        for needle in ('request alone is not approval', 'wrong target', 'only a yes', 'never approve for them',
                       'no second ask', 'also runs it', 'if_no', 'Ask once'):
            self.assertIn(needle, why)
        # 인앱 AI 도 읽는 안쪽 안전 칸은 그대로다.
        self.assertIn('do not describe it as done', body['_reading'][0])
        self.assertFalse(body['performed'])
        self.assertEqual(self.CID, body['confirmation_id'])
        # 섞인 문단(게이트·틀의 message)과 되읽기 원문 칸은 say 로 옮겨 없다.
        self.assertNotIn('message', body)
        self.assertNotIn('confirm_with_user', body)

    def test_a_recall_still_waiting_tells_instead_of_asking_again(self):
        body = self._pending(read_back=None)
        self.assertContract(body, say='tell')
        self.assertNotIn('ask', body['say'])
        self.assertIn('after_user', body['next'])


class ConfirmResultTest(ContractShapeMixin, unittest.TestCase):
    """승인 결과(control.confirm, 3단계 2026-10-29) — 실행 결과를 알릴 것은 say, 다시 부르지·묻지 않음은 next."""

    _RAN = ("Approved and already carried out — report the outcome in 'execution' to the user. Do NOT call the "
            "tool again or ask for approval again. Internal note: never quote, translate or narrate it or your "
            "actions; reply only in the user's language.")

    def _one(self, **kw):
        body = dict({"status": "success", "confirmation_id": "c1", "new_status": "approved"}, **kw)
        return _shape('control', 'confirm', body)

    def test_approved_and_run_tells_the_result_and_stops(self):
        body = self._one(executed=True, execution={"status": "created"}, message=self._RAN,
                         _reading=["x"], call_state="executed")
        self.assertContract(body, say='tell')
        self.assertIn('give the result from execution', body['say']['tell'])
        self.assertEqual(act_say.CONFIRM_DONE, body['next']['why'])
        self.assertNotIn('message', body)
        self.assertEqual({"status": "created"}, body['execution'])
        self.assertEqual(["x"], body['_reading'])                     # 안쪽 칸은 그대로

    def test_approved_but_not_run_or_unknown(self):
        body = self._one(executed=False, execution={"status": "error", "message": "offline"}, message="x")
        self.assertContract(body, say='tell')
        self.assertIn('did not run', body['say']['tell'])
        self.assertEqual('done', body['say']['avoid'])
        self.assertIn('do not retry', body['next']['why'])
        body = self._one(executed=False, unconfirmed=True, execution={"performed": "unknown"}, message="x")
        self.assertIn('unknown', body['say']['tell'])
        self.assertIn('read its state first', body['next']['why'])

    def test_approved_without_a_server_run_goes_to_the_rerun_call(self):
        body = self._one()
        self.assertContract(body, say=False)
        self.assertIn("_confirmation_id='c1'", body['next']['call'])

    def test_rejected_expired_and_already_handled(self):
        body = _shape('control', 'confirm', {"status": "success", "confirmation_id": "c1", "new_status": "rejected"})
        self.assertContract(body, say='tell')
        self.assertIn('nothing was done', body['say']['tell'])
        self.assertEqual(act_say.CONFIRM_DONE, body['next']['why'])
        body = _shape('control', 'confirm', {"status": "error", "confirmation_id": "c1",
                                             "message": "The confirmation expired."})
        self.assertContract(body, say='tell')
        self.assertIn('expired', body['say']['tell'])
        self.assertIn('make the request again', body['next']['why'])
        body = _shape('control', 'confirm', {"status": "error", "reason_code": "already_decided",
                                             "message": "Already handled (status=approved)."})
        self.assertContract(body, say='tell')
        self.assertEqual(act_say.CONFIRM_DONE, body['next']['why'])

    def test_an_argument_error_is_left_for_the_ai_to_fix(self):
        raw = {"status": "error", "message": "decision ('approve'|'reject') is required."}
        body = _shape('control', 'confirm', dict(raw))
        self.assertContract(body, say=False)
        self.assertEqual(raw['message'], body['message'])

    def test_several_at_once_are_counted(self):
        body = _shape('control', 'confirm', {"status": "batch_complete", "count": 3, "succeeded": 3, "results": [
            {"confirmation_id": "a", "status": "success", "new_status": "approved", "executed": True,
             "execution": {}, "message": self._RAN},
            {"confirmation_id": "b", "status": "success", "new_status": "approved", "executed": False,
             "execution": {}, "message": "x"},
            {"confirmation_id": "c", "status": "success", "new_status": "rejected"}]})
        self.assertContract(body, say='tell')
        self.assertEqual("Of 3: 1 approved and done, 1 rejected, 1 approved but not run - give each result.",
                         body['say']['tell'])
        self.assertEqual('all done', body['say']['avoid'])
        self.assertIn(act_say.CONFIRM_DONE, body['next']['why'])
        self.assertNotIn('Internal note', json.dumps(body, ensure_ascii=False))
        self.assertTrue(all('message' not in r for r in body['results']))


class OldCardHintTest(unittest.TestCase):
    """시범 밖 조회의 옛 card_hint — 도메인 표면에서는 뗀다(서버 카드 #370, 설계 §8 실측)."""

    _HINT = "Summary or weather answer: show one card now (screen op=card) unless already shown. Internal note: x"

    def test_a_non_pilot_read_loses_the_hint_and_nothing_else(self):
        raw = {"status": "success", "results": [
            {"target": {"name": "밸브1"}, "result": {"state": "on", "card_hint": self._HINT}}], "count": 1}
        body = _shape('measure', 'output_state', raw)
        self.assertNotIn('card_hint', json.dumps(body, ensure_ascii=False))
        self.assertNotIn('next', body)
        self.assertEqual('on', body['results'][0]['result']['state'])
        body = _shape('detail', 'device', {"card_hint": self._HINT, "status": "success", "name": "x"})
        self.assertEqual({"status": "success", "name": "x"}, body)

    def test_a_server_card_read_that_kept_its_hint_gets_a_card_call(self):
        """서버가 못 올렸으면(여러 화면 등) 안내가 남는다 — AI 가 올릴 길을 next.call 로."""
        body = _shape('overview', 'place', {"card_hint": self._HINT, "status": "success"})
        self.assertNotIn('card_hint', body)
        self.assertTrue(body['next']['call'].startswith("screen(op='card'"))

    def test_the_server_card_list_matches(self):
        from aot.tools.domain import server_card
        self.assertEqual(set(server_card.OPS), set(act_say.SERVER_CARD_OPS))

    def test_pilot_reads_also_lose_it(self):
        body = _shape('overview', 'failure', {"card_hint": self._HINT, "failure_summary": [], "status": "success"})
        self.assertNotIn('card_hint', body)
        self.assertNotIn('next', body)


class InstructionsTest(unittest.TestCase):

    def test_speaking_comes_first_and_survives_the_client_cut(self):
        """클라이언트가 약 2,048자에서 자른다(설계 §1-1) — SPEAKING 이 맨 앞이고 묶음 안내 끝까지 그 안이다."""
        from aot.tools import tool_execution as te
        for profile in (None, 'operations', 'configuration'):
            with self.subTest(profile=profile):
                text = te._server_instructions(profile)
                self.assertTrue(text.startswith('SPEAKING'), text[:40])
        self.assertLessEqual(len(te._server_instructions('operations')), 2000)
        self.assertIn('next', te.SPEAKING_RULE)
        self.assertIn('say', te.SPEAKING_RULE)
        self.assertNotIn('beat tool-result notes', te.SPEAKING_RULE)

    def test_only_the_entry_tool_header_carries_the_contract(self):
        from aot.tools.domain import surface
        self.assertIn(surface.CONTRACT_RULE, surface.HEADERS['overview'])
        for tool, head in surface.HEADERS.items():
            if tool == 'overview':
                continue
            with self.subTest(tool=tool):
                self.assertNotIn("user's language", head)
                self.assertNotIn('narrate', head)


if __name__ == '__main__':
    unittest.main()
