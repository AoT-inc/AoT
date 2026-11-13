"""음성 모드 승인 재확인 반복·작업 과정 노출 (2026-10-25).

- 사용자가 같은 건을 이미 승인했으면 AI 가 되묻지 않고 승인한다 → 승인과 실행이 한 호출이다.
- '도구를 찾겠다·이렇게 부르겠다' 를 말하지 않는 규칙은 예보만이 아니라 서버 지침 전체에 걸린다.
"""
import unittest
from unittest import mock


class SpeakingRuleIsGlobalTest(unittest.TestCase):
    def test_every_profile_gets_the_rule(self):
        from aot.tools import tool_execution as te
        for profile in (None, 'lite', 'operations'):
            with self.subTest(profile=profile):
                self.assertIn(te.SPEAKING_RULE, te._server_instructions(profile))

    def test_rule_forbids_narrating_work_and_repeat_approval(self):
        from aot.tools.tool_execution import SPEAKING_RULE
        self.assertIn('narrate nothing', SPEAKING_RULE)
        self.assertIn('final result', SPEAKING_RULE)
        # 2026-11-10(F-16): 승인 한 번·되읽기 규칙은 지침이 아니라 승인 대기 응답이 싣고, 같은 요청은 서버가 다시 묻지 않게 한다.
        from aot.tools.domain.act_say import APPROVAL_WHY, ALREADY_ASKED_WHY
        self.assertNotIn('Ask approval once', SPEAKING_RULE)
        self.assertIn('Ask once', APPROVAL_WHY)
        self.assertIn('read-back', APPROVAL_WHY)
        self.assertIn('do not ask again', ALREADY_ASKED_WHY)

    def test_rule_flow_ack_then_silence_then_a_short_result_with_limits(self):
        """2026-10-26 응답 흐름: 시작에 몇 마디, 중간에는 말하지 않음, 끝에 결과 1~2문장 + 값의 성격·범위, 모르는 원인은 모른다고."""
        from aot.tools.tool_execution import SPEAKING_RULE
        text = SPEAKING_RULE
        self.assertLess(text.index('open with a few words'), text.index('narrate nothing'))
        self.assertLess(text.index('narrate nothing'), text.index('final result'))
        for needle in ('1-2 sentences', 'model forecast or measured', 'range', 'unknown cause: say so'):
            self.assertIn(needle, text)
        # 2026-10-29: 결과의 next(할 호출)·say(전할 뜻) 규약 — 계약 op 결과는 더는 말을 시키지 않아 '이 규칙이 이긴다' 는 뺐다.
        self.assertIn("next: make the calls the question needs", text)
        self.assertIn("silently", text)
        # 2026-11-10(F-16): 응답 맨 앞 must(꼭 할 호출 하나)를 먼저.
        self.assertIn("must: do it first", text)
        self.assertIn("say: convey in the user's language", text)

    def test_no_profile_is_told_anything_about_the_map_slider(self):
        """슬라이더는 서버가 혼자 옮긴다(2026-10-27) — AI 에게 규칙을 주면 혼잣말이 되풀이하고 음성 모드가 읽는다."""
        from aot.tools import tool_execution as te
        for profile in (None, 'lite', 'operations'):
            with self.subTest(profile=profile):
                text = te._server_instructions(profile).lower()
                self.assertNotIn('slider', text)
                self.assertNotIn('_answer_time', text)


class ApprovalRunsInTheSameCallTest(unittest.TestCase):
    def _run(self, exec_return):
        from aot.tools import mcp_safety_gate as gate
        from aot.tools import tool_execution as te
        approved = {'status': 'success', 'confirmation_id': 'c1', 'new_status': 'approved'}
        with mock.patch.object(gate, 'execute_approved', return_value=exec_return):
            return te._run_after_approval('c1', dict(approved))

    def test_executed_carries_the_result_and_forbids_a_second_call(self):
        out = self._run(('executed', {'status': 'configured'}))
        self.assertTrue(out['executed'])
        self.assertEqual({'status': 'configured'}, out['execution'])
        self.assertIn('Do NOT call the tool again', out['message'])
        self.assertIn('ask for approval again', out['message'])

    def test_failed_is_reported_and_not_retried(self):
        out = self._run(('failed', {'status': 'error', 'performed': 'unknown'}))
        self.assertFalse(out['executed'])
        self.assertTrue(out['unconfirmed'])
        self.assertIn('do not retry', out['message'])

    def test_without_an_executing_identity_the_old_recall_path_remains(self):
        out = self._run(('refused', {'status': 'error', 'reason_code': 'not_approved'}))
        self.assertNotIn('executed', out)
        self.assertNotIn('message', out)

    def test_an_execution_exception_keeps_the_approval(self):
        from aot.tools import mcp_safety_gate as gate
        from aot.tools import tool_execution as te
        approved = {'status': 'success', 'new_status': 'approved'}
        with mock.patch.object(gate, 'execute_approved', side_effect=RuntimeError('x')):
            self.assertEqual(approved, te._run_after_approval('c1', dict(approved)))


class WordingTest(unittest.TestCase):
    def test_tool_description_no_longer_says_approving_runs_nothing(self):
        from aot.tools import tool_execution as te
        desc = next(t['description'] for t in te._EXTRA_TOOLS
                    if t['name'] == 'respond_to_confirmation')
        self.assertNotIn('executes nothing', desc)
        self.assertIn('RUNS the request in the same call', desc)
        self.assertIn('without asking again', desc)
        self.assertIn('read-back', desc)
        self.assertNotIn('already', desc)

    def test_domain_next_steps_read_back_before_approving(self):
        import json
        from aot.tools.domain import dispatch
        out = [{'type': 'text', 'text': json.dumps(
            {'status': 'pending_approval', 'confirmation_id': 'c1'})}]
        body = json.loads(dispatch._approval_next(out, 'control', {'op': 'x'})[0]['text'])
        self.assertIn('Read back confirm_with_user', body['next']['1_ask'])
        self.assertIn('request alone is not approval', body['next']['1_ask'])
        self.assertIn('please approve', body['next']['1_ask'])
        self.assertNotIn('Skip', body['next']['1_ask'])
        self.assertIn('approving also runs it', body['next']['2_answer'])
        self.assertIn('only if that answer says it did not run', body['next']['3_run'])
        self.assertIn('narrate', body['message'])


class ReadBackTest(unittest.TestCase):
    """요청이 곧 승인이 되면 AI 가 다른 장치로 알아들어도 그대로 움직인다 — 서버가 풀어 낸 대상을 되읽게 한다."""

    def test_read_back_uses_the_server_resolved_name_not_the_ai_title(self):
        from aot.tools import mcp_safety_gate as gate
        with mock.patch.object(gate, '_resolve_device_display_name', return_value='동쪽 측창'):
            text = gate.read_back_text('operate_device', {
                'device_id': 'd1', 'state': 'on', '_title': '서쪽 측창 켜기'})
        self.assertEqual('동쪽 측창 켜기', text)

    def test_physical_extras_are_included(self):
        from aot.tools import mcp_safety_gate as gate
        with mock.patch.object(gate, '_resolve_device_display_name', return_value='측창'):
            text = gate.read_back_text('operate_device', {
                'device_id': 'd1', 'state': 'on', 'duration_seconds': 30})
        self.assertEqual('측창 을 30초 동안 켜기', text)          # 시간은 문장 안에 — 내부 인자 이름 없이

    def test_pending_response_carries_the_read_back_and_forbids_request_as_approval(self):
        from aot.tools import mcp_safety_gate as gate
        import inspect
        src = inspect.getsource(gate.gate)
        self.assertIn('"confirm_with_user": read_back_text(tool_name, arguments)', src)
        self.assertIn('Their own request', src)
        self.assertIn('please approve', src)
        self.assertIn('only a yes given after that read-back counts', src)
