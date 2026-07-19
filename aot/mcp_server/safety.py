# coding=utf-8
"""
mcp_server/safety.py — P4-3: AI 작업 안전 경계 3계층.

Layer 1: 권한 (read / write 분리)
Layer 2: 값 범위 검증 + 변화량 제한
Layer 3: 사용자 승인 큐 (60s TTL)

외부 인터페이스:
  safety_check(tool_name, params, agent_id) → ConfirmationToken (write) 또는 None (read)
  confirm(token_id, user_id)
  get_pending_confirmations() → list[dict]
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# 예외
# ─────────────────────────────────────────────────────────────────────────────

class SafetyViolation(Exception):
    """값 범위·불변식 위반 — 호출 즉시 거부."""


class RateLimitExceeded(Exception):
    """시간당 호출 횟수 초과."""


class ConfirmationRequired(Exception):
    """쓰기 도구: 사용자 승인 대기 중 — token_id 포함."""
    def __init__(self, token_id: str, message: str = ''):
        self.token_id = token_id
        super().__init__(message or f'Confirmation required: {token_id}')


class WriteDisabled(Exception):
    """쓰기 기능이 전역으로 비활성화 상태."""


# ─────────────────────────────────────────────────────────────────────────────
# WriteBounds — 도구별 값 제한 정의
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WriteBounds:
    field: str
    min_val: float | None
    max_val: float | None
    max_delta_per_call: float | None  # None = 무제한
    max_calls_per_hour: int = 10

    def in_range(self, value: float) -> bool:
        if self.min_val is not None and value < self.min_val:
            return False
        if self.max_val is not None and value > self.max_val:
            return False
        return True


# 도구별 제한 테이블
WRITE_BOUNDS: dict[str, WriteBounds] = {
    'set_vpd_target': WriteBounds(
        field='value', min_val=0.3, max_val=2.5,
        max_delta_per_call=0.5, max_calls_per_hour=5),
    'update_method_point': WriteBounds(
        field='new_value', min_val=0.0, max_val=3.0,
        max_delta_per_call=0.3, max_calls_per_hour=10),
    'request_manual_lock': WriteBounds(
        field=None, min_val=None, max_val=None,
        max_delta_per_call=None, max_calls_per_hour=3),
    'acknowledge_alert': WriteBounds(
        field=None, min_val=None, max_val=None,
        max_delta_per_call=None, max_calls_per_hour=20),
}

# 쓰기 전용 도구 목록 (승인 필요)
WRITE_TOOLS = frozenset(WRITE_BOUNDS.keys())

# 보호된 시드 프리셋 (is_seed=True) 수정 불가 도구
SEED_PROTECTED_TOOLS = frozenset({'update_method_point'})

# ─────────────────────────────────────────────────────────────────────────────
# 승인 토큰 인메모리 저장소 (소량 — DB 저장은 MCPConfirmation 모델로 별도)
# ─────────────────────────────────────────────────────────────────────────────

_CONFIRMATION_TTL_SEC = 60

@dataclass
class ConfirmationToken:
    token_id: str
    tool_name: str
    params: dict
    agent_id: str
    expires_at: float  # time.time()
    status: str = 'pending'  # pending | approved | rejected | expired

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


_pending_tokens: dict[str, ConfirmationToken] = {}

# 호출 횟수 추적 {agent_id: {tool_name: [(timestamp, ...)]}}
_call_log: dict[str, dict[str, list[float]]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# 전역 쓰기 활성화 플래그 (기본 OFF)
# ─────────────────────────────────────────────────────────────────────────────

_write_enabled: bool = False


def set_write_enabled(enabled: bool) -> None:
    global _write_enabled
    _write_enabled = enabled


def is_write_enabled() -> bool:
    return _write_enabled


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────

def safety_check(
    tool_name: str,
    params: dict,
    agent_id: str = 'unknown',
    current_value: float | None = None,
) -> ConfirmationToken | None:
    """안전 검사 수행.

    read-only 도구  → None 반환 (통과)
    write 도구      → ConfirmationToken 반환 (ConfirmationRequired 예외 발생)
    위반 시         → SafetyViolation / RateLimitExceeded / WriteDisabled 예외
    """
    # Layer 1: 쓰기 전역 차단
    if tool_name in WRITE_TOOLS and not _write_enabled:
        raise WriteDisabled(
            f'Write tools are globally disabled. '
            f'Enable via set_write_enabled(True) or UI settings.')

    # 읽기 도구는 바로 통과
    if tool_name not in WRITE_TOOLS:
        return None

    bounds = WRITE_BOUNDS[tool_name]

    # Layer 2: 값 범위
    if bounds.field and bounds.field in params:
        val = float(params[bounds.field])
        if not bounds.in_range(val):
            raise SafetyViolation(
                f'{tool_name}: {bounds.field}={val} out of range '
                f'[{bounds.min_val}, {bounds.max_val}]')
        if bounds.max_delta_per_call is not None and current_value is not None:
            delta = abs(val - current_value)
            if delta > bounds.max_delta_per_call:
                raise SafetyViolation(
                    f'{tool_name}: delta={delta:.3f} exceeds '
                    f'max_delta_per_call={bounds.max_delta_per_call}')

    # Layer 2: 레이트 리밋
    _check_rate_limit(agent_id, tool_name, bounds.max_calls_per_hour)

    # Layer 3: 승인 토큰 발행
    token = _create_token(tool_name, params, agent_id)
    raise ConfirmationRequired(token.token_id,
                               f'Awaiting user approval for {tool_name}')


def confirm(token_id: str, user_id: str = 'user') -> ConfirmationToken:
    """사용자가 승인 확인 버튼을 클릭했을 때 호출."""
    token = _pending_tokens.get(token_id)
    if token is None:
        raise KeyError(f'Unknown confirmation token: {token_id}')
    if token.is_expired():
        token.status = 'expired'
        raise TimeoutError(f'Confirmation token {token_id} expired')
    token.status = 'approved'
    return token


def reject(token_id: str, user_id: str = 'user') -> ConfirmationToken:
    token = _pending_tokens.get(token_id)
    if token is None:
        raise KeyError(f'Unknown confirmation token: {token_id}')
    token.status = 'rejected'
    return token


def get_pending_confirmations() -> list[dict]:
    """대기 중인 확인 목록 반환 (만료 항목 자동 정리)."""
    now = time.time()
    expired = [tid for tid, t in _pending_tokens.items() if t.is_expired()]
    for tid in expired:
        _pending_tokens[tid].status = 'expired'

    return [
        {
            'token_id': t.token_id,
            'tool_name': t.tool_name,
            'params': t.params,
            'agent_id': t.agent_id,
            'expires_in': max(0, int(t.expires_at - now)),
            'status': t.status,
        }
        for t in _pending_tokens.values()
        if t.status == 'pending'
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _check_rate_limit(agent_id: str, tool_name: str, limit: int) -> None:
    now = time.time()
    window = 3600.0
    calls = _call_log.setdefault(agent_id, {}).setdefault(tool_name, [])
    # 1시간 이전 기록 제거
    calls[:] = [t for t in calls if now - t < window]
    if len(calls) >= limit:
        raise RateLimitExceeded(
            f'{tool_name}: rate limit {limit}/hour exceeded for {agent_id}')
    calls.append(now)


def _create_token(tool_name: str, params: dict, agent_id: str) -> ConfirmationToken:
    token = ConfirmationToken(
        token_id=str(uuid.uuid4()),
        tool_name=tool_name,
        params=params,
        agent_id=agent_id,
        expires_at=time.time() + _CONFIRMATION_TTL_SEC,
    )
    _pending_tokens[token.token_id] = token
    return token
