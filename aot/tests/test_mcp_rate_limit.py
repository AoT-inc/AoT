# coding=utf-8
"""MCP 게이트 레이트 리밋이 프로세스 경계를 넘어 공유되는지 검증한다.

회귀 대상: 카운터가 프로세스 인메모리 dict 였을 때, 게이트를 import 하는
프로세스가 둘(웹앱 stdio 브릿지 / HTTP 서버)이라 상한이 실질적으로 두 배가
됐고 재시작하면 0으로 돌아갔다. 여기서는 "이 프로세스의 dict 를 비워도 상한이
그대로 적용된다"로 그 성질을 확인한다 — 다른 프로세스가 이미 슬롯을 쓴 상황과
같은 상태다.
"""
import unittest
from datetime import datetime, timedelta

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.ai.services import mcp_safety_gate as gate
from aot.databases.models import MCPConfirmation


class TestMCPRateLimitSharedAcrossProcesses(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        MCPConfirmation.query.delete()
        db.session.commit()
        gate._call_log.clear()

    def _seed(self, agent_id, tool_name, count, age_sec=0):
        """다른 프로세스가 이미 쓴 슬롯을 흉내낸다 (= 승인 대기 행)."""
        created = datetime.utcnow() - timedelta(seconds=age_sec)
        for _ in range(count):
            row = MCPConfirmation(
                created_at=created,
                expires_at=created + timedelta(seconds=300),
                tool_name=tool_name,
                params_json='{}',
                agent_id=agent_id,
                status='pending',
            )
            db.session.add(row)
        db.session.commit()

    def test_other_process_slots_count(self):
        """인메모리 dict 가 비어 있어도 DB 에 쌓인 만큼 상한에 걸린다."""
        limit = gate._RATE_LIMITS['operate_device']
        self._seed('agent-a', 'operate_device', limit)

        self.assertEqual(gate._call_log, {})  # 이 프로세스는 한 번도 센 적 없음
        with self.assertRaises(gate.RateLimitExceeded):
            gate._check_rate_limit('agent-a', 'operate_device')

    def test_under_limit_passes(self):
        limit = gate._RATE_LIMITS['operate_device']
        self._seed('agent-a', 'operate_device', limit - 1)
        gate._check_rate_limit('agent-a', 'operate_device')  # 예외 없음

    def test_window_expires(self):
        """1시간을 넘긴 행은 세지 않는다."""
        limit = gate._RATE_LIMITS['operate_device']
        self._seed('agent-a', 'operate_device', limit, age_sec=3601)
        gate._check_rate_limit('agent-a', 'operate_device')  # 예외 없음

    def test_scoped_per_agent_and_tool(self):
        """다른 키·다른 도구의 사용량이 섞이지 않는다."""
        limit = gate._RATE_LIMITS['operate_device']
        self._seed('agent-a', 'operate_device', limit)
        gate._check_rate_limit('agent-b', 'operate_device')
        gate._check_rate_limit('agent-a', 'add_schedule')

    def test_default_limit_for_unlisted_tool(self):
        self._seed('agent-a', 'add_schedule', gate._DEFAULT_CALLS_PER_HOUR)
        with self.assertRaises(gate.RateLimitExceeded):
            gate._check_rate_limit('agent-a', 'add_schedule')

    def test_falls_back_to_process_counter_when_db_unavailable(self):
        """DB 가 죽어도 상한이 통째로 열리지는 않는다."""
        from unittest.mock import patch

        limit = gate._DEFAULT_CALLS_PER_HOUR
        with patch.object(MCPConfirmation, 'query') as q:
            q.filter.side_effect = RuntimeError('db down')
            for _ in range(limit):
                gate._check_rate_limit('agent-a', 'add_schedule')
            with self.assertRaises(gate.RateLimitExceeded):
                gate._check_rate_limit('agent-a', 'add_schedule')


class TestMCPConfirmationWindows(unittest.TestCase):
    """승인 유효시간이 '판단 창'과 '실행 창'으로 분리됐는지 확인한다.

    회귀 대상: 두 구간이 한 값이라, 판단 창이 거의 다 지난 뒤 승인하면 실행
    가능 시간이 몇 초밖에 남지 않아 사람이 분명히 승인했는데도 재호출이
    confirmation_expired 로 튕겼다.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        MCPConfirmation.query.delete()
        db.session.commit()

    def _pending(self, age_sec):
        created = datetime.utcnow() - timedelta(seconds=age_sec)
        row = MCPConfirmation(
            created_at=created,
            expires_at=created + timedelta(seconds=gate._CONFIRM_TTL_SEC),
            tool_name='operate_device',
            params_json='{}',
            agent_id='agent-a',
            status='pending',
        )
        row.save()
        return row

    def test_approval_restarts_the_clock(self):
        """판단 창 끝자락에 승인해도 실행 창은 온전히 주어진다."""
        row = self._pending(age_sec=gate._CONFIRM_TTL_SEC - 5)
        self.assertLess(
            (row.expires_at - datetime.utcnow()).total_seconds(), 10)

        res = gate.approve(row.unique_id)
        self.assertEqual(res['status'], 'success')

        row = MCPConfirmation.query.filter_by(unique_id=row.unique_id).first()
        self.assertFalse(row.is_expired())
        remaining = (row.expires_at - datetime.utcnow()).total_seconds()
        self.assertGreater(remaining, gate._APPROVED_TTL_SEC - 10)

    def test_expired_pending_cannot_be_approved(self):
        row = self._pending(age_sec=gate._CONFIRM_TTL_SEC + 1)
        res = gate.approve(row.unique_id)
        self.assertEqual(res['status'], 'error')
        row = MCPConfirmation.query.filter_by(unique_id=row.unique_id).first()
        self.assertEqual(row.status, 'expired')

    def test_reject_does_not_extend(self):
        row = self._pending(age_sec=10)
        before = row.expires_at
        gate.reject(row.unique_id)
        row = MCPConfirmation.query.filter_by(unique_id=row.unique_id).first()
        self.assertEqual(row.status, 'rejected')
        self.assertEqual(row.expires_at, before)


if __name__ == '__main__':
    unittest.main()
