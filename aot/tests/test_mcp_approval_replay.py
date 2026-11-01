# coding=utf-8
"""승인 하나는 **한 번만** 실행된다 — 재승인·동시 승인·동시 재호출.

배경(2026-10-08 코드 검토): 승인된 요청을 실행하는 경로가 셋인데, 셋 다
"행을 읽어 상태를 확인 → 나중에 쓴다" 였다. 확인과 쓰기 사이가 비어 있으면
겹친 요청이 둘 다 확인을 통과한다.

  1. 웹 승인(`_decide`) 은 `consumed`·`rejected`·만료만 막았다. 이미
     `executed`·`failed`·`approved` 인 요청도 다시 승인되고, 웹 라우트는 승인
     직후 `execute_approved` 를 부르므로 **같은 장치 명령이 또 나갔다.**
  2. `execute_approved` 는 "approved 인가" 를 본 뒤 실행이 끝나서야 상태를
     바꿨다 — 승인 버튼 두 번(두 탭·두 사람·재시도)이 둘 다 실행된다.
  3. MCP 재호출(`_confirmation_id`) 의 1회용 소비도 같은 모양이었다.

고친 방식은 하나다: 상태 전이를 **조건부 갱신**(`WHERE status = 기대값`)으로
선점하고, 선점에 실패하면 실행하지 않는다.

동시성은 결정적으로 재현한다. (a) 세션에 남은 옛 행 — 다른 요청이 이미 상태를
바꿨는데 이 요청은 옛 값을 들고 있는 순간. (b) 실행 도중 재진입 — 첫 실행이
끝나기 전에 두 번째 실행이 들어오는 순간.
"""
import json
from unittest import mock

from sqlalchemy import text

from aot.aot_flask.extensions import db
from aot.databases.models import MCPConfirmation
from aot.tests.test_mcp_record_write_guard import _AGENT, _Fixture
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_execution as te


class _Counting(object):
    """장치 실행을 대신해 횟수만 센다. 재진입 훅을 걸 수 있다."""

    def __init__(self):
        self.calls = 0
        self.on_call = None

    def __call__(self, *a, **k):
        self.calls += 1
        if self.on_call is not None:
            hook, self.on_call = self.on_call, None
            hook()
        return {"status": "success", "result": "ok"}


class TestApprovalRunsOnce(_Fixture):

    def setUp(self):
        super(TestApprovalRunsOnce, self).setUp()
        self.run = _Counting()
        self._patches = [
            mock.patch.object(te, '_dispatch_virtual_tool', self.run),
            mock.patch('aot.tools.aot_native_tool_engine.AoTNativeToolEngine.execute',
                       self.run),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        super(TestApprovalRunsOnce, self).tearDown()

    # -- helpers ------------------------------------------------------------
    def _args(self):
        return {'device_id': self.output_id, 'state': 'on'}

    def _pending_cid(self):
        body = self._call('operate_device', self._args(), self._role('Editor'))
        self.assertEqual(body['status'], 'pending_approval', body)
        return body['confirmation_id']

    def _web_approve(self, cid):
        """웹 라우트와 같은 순서: 승인이 성공하면 곧바로 실행."""
        r = gate.approve(cid, user_id=self.user_uuids['Editor'])
        if r.get('status') != 'success':
            return r, None
        return r, gate.execute_approved(cid)

    def _status(self, cid):
        db.session.expire_all()
        return MCPConfirmation.query.filter_by(unique_id=cid).first().status

    def _stale_row(self, cid, now_status):
        """다른 요청이 상태를 이미 바꿔 **커밋까지 한** 순간 — 이 요청의 세션에는
        바뀌기 전 값을 든 행 객체가 그대로 남아 있다(겹친 요청이 보는 세상)."""
        from sqlalchemy.orm.attributes import set_committed_value
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        seen = row.status
        db.session.execute(
            text("UPDATE mcp_confirmation SET status = :s WHERE unique_id = :u"),
            {'s': now_status, 'u': cid})
        db.session.commit()
        set_committed_value(row, 'status', seen)   # 이 세션은 옛 값을 믿는다
        return row

    # -- 1. 재승인 ----------------------------------------------------------
    def test_reapproving_an_executed_request_does_not_run_it_again(self):
        cid = self._pending_cid()
        r, (status, _res) = self._web_approve(cid)
        self.assertEqual(status, 'executed')
        self.assertEqual(self.run.calls, 1)

        r2, second = self._web_approve(cid)
        self.assertNotEqual(r2.get('status'), 'success', r2)
        self.assertIsNone(second)
        self.assertEqual(self.run.calls, 1)
        self.assertEqual(self._status(cid), 'executed')

    def test_reapproving_an_already_approved_request_is_refused(self):
        """MCP 로 승인만 된(아직 AI 가 재호출하지 않은) 요청을 웹에서 또 승인하면
        웹이 실행하고 AI 재호출이 한 번 더 실행했다."""
        cid = self._pending_cid()
        self.assertEqual(gate.approve(cid, user_id=self.user_uuids['Editor'])['status'],
                         'success')
        r2, second = self._web_approve(cid)
        self.assertNotEqual(r2.get('status'), 'success', r2)
        self.assertEqual(self.run.calls, 0)

    def test_an_approved_request_can_still_be_rejected(self):
        """실행 전이라면 승인을 거둘 수 있다 — 거부는 아무것도 실행하지 않는다."""
        cid = self._pending_cid()
        gate.approve(cid, user_id=self.user_uuids['Editor'])
        self.assertEqual(gate.reject(cid, user_id=self.user_uuids['Editor'])['status'],
                         'success')
        self.assertEqual(self._status(cid), 'rejected')

    # -- 2. 동시 승인 -------------------------------------------------------
    def test_concurrent_decision_with_a_stale_row_is_refused(self):
        cid = self._pending_cid()
        row = self._stale_row(cid, 'approved')       # 다른 요청이 먼저 승인
        self.assertEqual(row.status, 'pending')      # 이 요청은 아직 대기로 본다
        r = gate.approve(cid, user_id=self.user_uuids['Editor'])
        self.assertNotEqual(r.get('status'), 'success', r)

    def test_execution_reentered_while_running_does_not_run_twice(self):
        cid = self._pending_cid()
        gate.approve(cid, user_id=self.user_uuids['Editor'])
        inner = {}

        def second_click():
            inner['result'] = gate.execute_approved(cid)
        self.run.on_call = second_click

        status, _res = gate.execute_approved(cid)
        self.assertEqual(status, 'executed')
        self.assertEqual(self.run.calls, 1)
        self.assertEqual(inner['result'][0], 'refused', inner)
        self.assertEqual(self._status(cid), 'executed')

    # -- 3. MCP 재호출 소비 -------------------------------------------------
    def test_concurrent_mcp_consume_with_a_stale_row_is_refused(self):
        cid = self._pending_cid()
        gate.approve(cid, user_id=self.user_uuids['Editor'])
        role = self._role('Editor')                  # 세션을 건드리는 준비는 먼저
        row = self._stale_row(cid, 'consumed')       # 다른 재호출이 먼저 소비
        self.assertEqual(row.status, 'approved')     # 이 요청은 아직 승인됨으로 본다
        blocked = gate.gate('operate_device', dict(self._args(), _confirmation_id=cid),
                            agent_id=_AGENT, role=role)
        self.assertIsNotNone(blocked, '이미 소비된 승인으로 실행을 허락했다')
        self.assertEqual(blocked.get('reason_code'), 'confirmation_already_used', blocked)

    def test_single_mcp_consume_still_works(self):
        cid = self._pending_cid()
        gate.approve(cid, user_id=self.user_uuids['Editor'])
        blocked = gate.gate('operate_device', dict(self._args(), _confirmation_id=cid),
                            agent_id=_AGENT, role=self._role('Editor'))
        self.assertIsNone(blocked, blocked)
        self.assertEqual(self._status(cid), 'consumed')


if __name__ == '__main__':
    import unittest
    unittest.main()
