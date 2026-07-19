# coding=utf-8
"""
tests/test_safety.py — P4-3 safety.py 단위 테스트.

테스트 항목:
  - WriteDisabled: 쓰기 비활성화 상태에서 write 도구 차단
  - SafetyViolation: 값 범위 초과 / delta 초과
  - RateLimitExceeded: 시간당 호출 횟수 초과
  - ConfirmationRequired: 정상 write 도구는 토큰 발행
  - confirm / reject / expire: 토큰 상태 전이
  - get_pending_confirmations: 만료 항목 자동 정리
  - read 도구: safety_check → None (통과)
"""

import time
import types
import sys
import pytest

# ── safety 모듈 임포트 (Flask 없이) ─────────────────────────────────────────
import importlib

# 테스트 실행 전 모듈 상태를 격리하기 위해 모듈을 직접 리임포트
import aot.mcp_server.safety as safety_mod


def _reload():
    """각 테스트마다 모듈 상태 초기화."""
    # 내부 상태 초기화
    safety_mod._write_enabled = False
    safety_mod._pending_tokens.clear()
    safety_mod._call_log.clear()


# ─────────────────────────────────────────────────────────────────────────────
# WriteDisabled
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteDisabled:
    def setup_method(self):
        _reload()

    def test_write_tool_blocked_when_disabled(self):
        with pytest.raises(safety_mod.WriteDisabled):
            safety_mod.safety_check('set_vpd_target', {'value': 1.0}, 'agent1')

    def test_read_tool_passes_when_write_disabled(self):
        result = safety_mod.safety_check('list_facilities', {}, 'agent1')
        assert result is None

    def test_write_enabled_allows_confirmation(self):
        safety_mod.set_write_enabled(True)
        with pytest.raises(safety_mod.ConfirmationRequired):
            safety_mod.safety_check('set_vpd_target', {'value': 1.0}, 'agent1')


# ─────────────────────────────────────────────────────────────────────────────
# SafetyViolation — 값 범위
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyViolation:
    def setup_method(self):
        _reload()
        safety_mod.set_write_enabled(True)

    def test_vpd_below_min(self):
        with pytest.raises(safety_mod.SafetyViolation, match='out of range'):
            safety_mod.safety_check('set_vpd_target', {'value': 0.1}, 'agent1')

    def test_vpd_above_max(self):
        with pytest.raises(safety_mod.SafetyViolation, match='out of range'):
            safety_mod.safety_check('set_vpd_target', {'value': 3.0}, 'agent1')

    def test_vpd_delta_exceeded(self):
        with pytest.raises(safety_mod.SafetyViolation, match='delta'):
            safety_mod.safety_check(
                'set_vpd_target', {'value': 2.0}, 'agent1',
                current_value=1.0)   # delta = 1.0 > 0.5

    def test_vpd_delta_ok(self):
        # delta = 0.3 ≤ 0.5: ConfirmationRequired 발생해야 함
        with pytest.raises(safety_mod.ConfirmationRequired):
            safety_mod.safety_check(
                'set_vpd_target', {'value': 1.3}, 'agent1',
                current_value=1.0)

    def test_method_point_below_min(self):
        with pytest.raises(safety_mod.SafetyViolation):
            safety_mod.safety_check(
                'update_method_point', {'new_value': -0.1}, 'agent1')

    def test_method_point_above_max(self):
        with pytest.raises(safety_mod.SafetyViolation):
            safety_mod.safety_check(
                'update_method_point', {'new_value': 3.1}, 'agent1')


# ─────────────────────────────────────────────────────────────────────────────
# RateLimitExceeded
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimit:
    def setup_method(self):
        _reload()
        safety_mod.set_write_enabled(True)

    def test_rate_limit_exceeded_after_n_calls(self):
        limit = safety_mod.WRITE_BOUNDS['set_vpd_target'].max_calls_per_hour  # 5
        for i in range(limit):
            with pytest.raises(safety_mod.ConfirmationRequired):
                safety_mod.safety_check('set_vpd_target', {'value': 1.0 + i * 0.01}, 'agent1')

        with pytest.raises(safety_mod.RateLimitExceeded):
            safety_mod.safety_check('set_vpd_target', {'value': 1.5}, 'agent1')

    def test_rate_limit_per_agent_independent(self):
        limit = safety_mod.WRITE_BOUNDS['set_vpd_target'].max_calls_per_hour
        for i in range(limit):
            with pytest.raises(safety_mod.ConfirmationRequired):
                safety_mod.safety_check('set_vpd_target', {'value': 1.0 + i * 0.01}, 'agent_A')

        # agent_B 는 별도 카운터
        with pytest.raises(safety_mod.ConfirmationRequired):
            safety_mod.safety_check('set_vpd_target', {'value': 1.0}, 'agent_B')


# ─────────────────────────────────────────────────────────────────────────────
# ConfirmationRequired — 토큰 발행
# ─────────────────────────────────────────────────────────────────────────────

class TestConfirmationRequired:
    def setup_method(self):
        _reload()
        safety_mod.set_write_enabled(True)

    def test_token_issued(self):
        with pytest.raises(safety_mod.ConfirmationRequired) as exc_info:
            safety_mod.safety_check('set_vpd_target', {'value': 1.0}, 'agent1')
        token_id = exc_info.value.token_id
        assert token_id in safety_mod._pending_tokens

    def test_token_fields(self):
        with pytest.raises(safety_mod.ConfirmationRequired) as exc_info:
            safety_mod.safety_check('set_vpd_target', {'value': 1.2}, 'agent_x')
        tid = exc_info.value.token_id
        tok = safety_mod._pending_tokens[tid]
        assert tok.tool_name == 'set_vpd_target'
        assert tok.params == {'value': 1.2}
        assert tok.agent_id == 'agent_x'
        assert tok.status == 'pending'
        assert tok.expires_at > time.time()


# ─────────────────────────────────────────────────────────────────────────────
# confirm / reject / expire
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenLifecycle:
    def setup_method(self):
        _reload()
        safety_mod.set_write_enabled(True)

    def _get_token_id(self):
        with pytest.raises(safety_mod.ConfirmationRequired) as exc_info:
            safety_mod.safety_check('set_vpd_target', {'value': 1.0}, 'agent1')
        return exc_info.value.token_id

    def test_confirm_sets_approved(self):
        tid = self._get_token_id()
        token = safety_mod.confirm(tid, 'user1')
        assert token.status == 'approved'

    def test_reject_sets_rejected(self):
        tid = self._get_token_id()
        token = safety_mod.reject(tid, 'user1')
        assert token.status == 'rejected'

    def test_confirm_unknown_token(self):
        with pytest.raises(KeyError):
            safety_mod.confirm('nonexistent-token-id', 'user1')

    def test_confirm_expired_token(self):
        tid = self._get_token_id()
        # 만료시간을 과거로 설정
        safety_mod._pending_tokens[tid].expires_at = time.time() - 1
        with pytest.raises(TimeoutError):
            safety_mod.confirm(tid, 'user1')
        assert safety_mod._pending_tokens[tid].status == 'expired'

    def test_get_pending_excludes_expired(self):
        tid = self._get_token_id()
        safety_mod._pending_tokens[tid].expires_at = time.time() - 1

        pending = safety_mod.get_pending_confirmations()
        assert all(p['token_id'] != tid for p in pending)
        # 상태는 expired 로 업데이트
        assert safety_mod._pending_tokens[tid].status == 'expired'

    def test_get_pending_returns_active(self):
        tid = self._get_token_id()
        pending = safety_mod.get_pending_confirmations()
        ids = [p['token_id'] for p in pending]
        assert tid in ids

    def test_get_pending_expires_in_positive(self):
        tid = self._get_token_id()
        pending = safety_mod.get_pending_confirmations()
        info = next(p for p in pending if p['token_id'] == tid)
        assert info['expires_in'] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 읽기 도구 통과
# ─────────────────────────────────────────────────────────────────────────────

class TestReadTools:
    def setup_method(self):
        _reload()

    @pytest.mark.parametrize('tool_name', [
        'list_facilities',
        'get_facility_state',
        'get_sensor_history',
        'list_functions',
        'get_function_state',
        'list_methods',
        'list_outputs',
        'get_recent_events',
        'analyze_control_performance',
        'detect_sensor_anomaly',
        'suggest_setpoint_adjustment',
        'compare_periods',
    ])
    def test_read_tool_passes(self, tool_name):
        result = safety_mod.safety_check(tool_name, {}, 'agent1')
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# WriteBounds 경계값
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteBounds:
    def test_in_range(self):
        b = safety_mod.WriteBounds('v', 0.3, 2.5, 0.5)
        assert b.in_range(0.3) is True
        assert b.in_range(2.5) is True
        assert b.in_range(0.29) is False
        assert b.in_range(2.51) is False

    def test_no_bounds(self):
        b = safety_mod.WriteBounds(None, None, None, None)
        assert b.in_range(9999) is True
