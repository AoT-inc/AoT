"""도메인 표면의 승인 흐름 — 승인 대기 → 사용자 승인 → 같은 operation 다시 → 실행.

2026-10-14 사용자 시험: 예전 표면에서는 사용자가 "승인" 이라고 하면 LLM 이
respond_to_confirmation 으로 AoT 승인을 처리했는데, 도메인 표면에서는 안 됐다.
원인 셋 — 안내문이 옛 이름(respond_to_confirmation)이었고, `control.confirm` 의 대상
(승인 번호)을 틀이 풀지 못했고, 다시 부른 호출의 `_confirmation_id` 를 틀이 버렸다.
이 테스트는 실제 게이트·승인 큐·처리기를 지나 공지가 등록되는지까지 본다.
"""
import json
from unittest import mock

from aot.tests.test_mcp_tool_profiles import OPS, _AppFixture, _PREFIX


class DomainApprovalFlowTest(_AppFixture):

    def setUp(self):
        super().setUp()
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        p = mock.patch('aot.tools.tool_execution.domain_surface_enabled', lambda: True)
        p.start()
        self.addCleanup(p.stop)
        self.role = self._auth(self._issue('Editor', 'full', OPS))

    def _call(self, tool, args):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        out = te._execute_tool(self.app, tool, dict(args),
                               agent_id='user:%s' % _PREFIX.lower(), role=self.role,
                               scope_user_uuid=getattr(self.role, 'user_id', None),
                               transport='mcp_http',
                               tool_profile=mcp_auth.tool_profile_of(self.role))
        return json.loads(out[0]['text'])

    def test_user_approval_through_the_llm_runs_the_write(self):
        args = {'op': 'notice_add', 'title': '승인 흐름 시험', 'body': '본문'}
        first = self._call('record', args)
        self.assertEqual('pending_approval', first.get('status'), first)
        cid = first['confirmation_id']
        # 응답 계약(2026-10-29): 되읽기·묻기는 say.ask, 승인 뒤 보낼 정확한 호출은 next.after_user.
        self.assertEqual(['status', 'say', 'next'], list(first)[:3], first)
        self.assertIn('승인 흐름 시험', first['say']['ask'])
        self.assertEqual("control(op='confirm', target='%s', decision='approve')" % cid,
                         first['next']['after_user'])

        answer = self._call('control', {'op': 'confirm', 'target': cid,
                                        'decision': 'approve'})
        self.assertEqual('executed', answer.get('call_state'), answer)
        # 승인이 곧 실행이다(2026-10-25) — 같은 호출이 결과까지 싣고, 되묻거나 다시 부르라고 하지 않는다.
        self.assertTrue(answer.get('executed'), answer)
        self.assertEqual('created', answer['execution'].get('status'), answer)
        # 응답 계약(2026-10-29 3단계): 결과를 알릴 것은 say.tell, 다시 부르지·묻지 않음은 next — 'Internal note' 꼬리 없음.
        self.assertEqual(['status', 'say', 'next'], list(answer)[:3], answer)
        self.assertIn('give the result', answer['say']['tell'])
        self.assertIn('do not call the operation again', answer['next']['why'])
        self.assertIn('do not ask for approval again', answer['next']['why'])
        self.assertNotIn('Internal note', json.dumps(answer, ensure_ascii=False))

        # 옛 방식(같은 도구 + _confirmation_id 재호출)은 다시 돌리지 않고 저장된 결과를 돌려준다.
        again = self._call('record', dict(args, _confirmation_id=cid))
        self.assertEqual('already_executed', again.get('call_state'), again)
        self.assertNotEqual('pending_approval', again.get('status'), again)

        from aot.databases.models import MCPConfirmation
        self.db.session.remove()
        self.assertEqual(1, MCPConfirmation.query.count())     # 승인 대기가 쌓이지 않았다


class FullUuidIsNeverANameTest(_AppFixture):
    """2026-10-18 구획 단계 확정이 승인 대기에서 멈췄다 — 승인 번호(uuid)가 이름 풀이로
    넘어가 숫자 조각('e3a3edb3' → 구역 '3-2')에 걸렸고, `control.confirm` 이
    "구역은 받지 않는다" 로 거절됐다. 완전한 uuid 는 이름 풀이를 타지 않는다."""

    CID = 'e3a3edb3-21f4-4433-876e-120c47e1b1a5'

    def _boom(self, *a, **k):
        raise AssertionError('a full uuid must not reach name matching')

    def test_resolver_does_not_fuzzy_match_a_uuid(self):
        from aot.tools.domain import targets
        with mock.patch.object(targets, '_token_candidates', self._boom), \
                mock.patch.object(targets, '_fallback', self._boom), \
                mock.patch.object(targets, '_prefix_candidates', self._boom):
            state, got = targets._resolve(self.CID, {'confirmation'})
        self.assertEqual('none', state)

    def test_confirm_plan_takes_the_uuid_as_a_confirmation(self):
        from aot.tools.domain import dispatch, targets
        with mock.patch.object(targets, '_token_candidates', self._boom), \
                mock.patch.object(targets, '_fallback', self._boom), \
                mock.patch.object(targets, '_prefix_candidates', self._boom):
            plan = dispatch.plan('control', {'op': 'confirm', 'target': self.CID,
                                             'decision': 'approve'})
        self.assertEqual('call', plan[0], plan)
        self.assertEqual('respond_to_confirmation', plan[1])
        self.assertEqual(self.CID, plan[2].get('confirmation_id'))
