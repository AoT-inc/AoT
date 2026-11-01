# coding=utf-8
"""유효기한 (원칙 1, 계약 §7). 만료된 발행은 소비자가 통째로 무시한다 — 마지막 값으로 채우지 않는다."""
from __future__ import annotations

from typing import Optional

from .types import Status

DEFAULT_PERIOD_S = 3600.0


def valid_until_for(t0: float, period_s: float, status: Status, kind: str = "facility") -> float:
    """발행 한 건의 유효기한. status ≥ UNSYNCED 이면 즉시 만료(계약 §7-3).
    시설 `t0 + 2×주기`, 노지 일 격자 `t0 + 36 h`(계약 §10.3) — 노지 시 격자는 `t0 + 3×주기`."""
    if int(status) >= int(Status.UNSYNCED):
        return float(t0)
    if kind == "field_daily":
        return float(t0) + 36 * 3600.0
    mult = 3.0 if kind == "field_hourly" else 2.0
    return float(t0) + mult * float(period_s)


def is_expired(valid_until: Optional[float], now: float) -> bool:
    """유효기한이 없거나 지났으면 True. 알 수 없으면 만료로 본다(안전한 쪽)."""
    return valid_until is None or now > valid_until
