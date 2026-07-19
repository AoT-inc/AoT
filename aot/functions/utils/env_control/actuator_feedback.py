# coding=utf-8
"""
env_control/actuator_feedback.py — 액추에이터 실제 상태 추적 및 신뢰도 관리.

명령(commanded_pct)과 실제 반응(actual_pct) 의 불일치를 감지하여
trust_score 를 관리한다. Stage 1 캘리브레이션 학습기가 trust_score 를
가중치로 사용한다.

실제 위치 피드백이 없는 경우(대부분의 온실 액추에이터): dispatch 성공/실패를
피드백 대리값으로 사용하고, 센서 응답(온도·습도 변화)이 명령과 반대 방향이면
mismatch 로 감지한다(Stage 1 에서 통합).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional


# 신뢰도 감쇠·회복 계수
_TRUST_DECAY   = 0.15   # dispatch 실패 1회당 감쇠
_TRUST_RECOVER = 0.05   # dispatch 성공 1회당 회복
_MISMATCH_DECAY = 0.10  # 센서 불응 감지 시 추가 감쇠
_MIN_TRUST     = 0.1
_MAX_TRUST     = 1.0


@dataclass
class ActuatorFeedback:
    """단일 액추에이터의 피드백 상태."""
    actuator_id: str
    commanded_pct: float = 0.0
    actual_pct: Optional[float] = None   # 실제 위치 (피드백 없으면 None)
    last_dispatch_ts: float = 0.0
    last_dispatch_ok: bool = True
    mismatch_count: int = 0
    success_count: int = 0
    trust_score: float = 1.0

    def record_dispatch(self, value: float, success: bool, ts: float = 0.0):
        """dispatch 결과를 기록하고 trust_score 를 업데이트."""
        self.commanded_pct    = value
        self.last_dispatch_ts = ts or time.time()
        self.last_dispatch_ok = success
        if success:
            self.success_count += 1
            self.trust_score = min(_MAX_TRUST,
                                   self.trust_score + _TRUST_RECOVER)
        else:
            self.mismatch_count += 1
            self.trust_score = max(_MIN_TRUST,
                                   self.trust_score - _TRUST_DECAY)

    def record_sensor_mismatch(self):
        """Stage 1: 센서 응답이 명령과 반대 방향일 때 호출."""
        self.mismatch_count += 1
        self.trust_score = max(_MIN_TRUST,
                               self.trust_score - _MISMATCH_DECAY)

    def effective_pct(self) -> float:
        """제어에 사용할 '현재 위치' 추정값 (actual > commanded 순)."""
        if self.actual_pct is not None:
            return self.actual_pct
        return self.commanded_pct

    @property
    def is_suspicious(self) -> bool:
        return self.trust_score < 0.5 or self.mismatch_count > 5


class ActuatorFeedbackRegistry:
    """모든 액추에이터 피드백 레코드를 관리하는 레지스트리."""

    def __init__(self):
        self._records: Dict[str, ActuatorFeedback] = {}

    def get(self, actuator_id: str) -> ActuatorFeedback:
        if actuator_id not in self._records:
            self._records[actuator_id] = ActuatorFeedback(actuator_id=actuator_id)
        return self._records[actuator_id]

    def record_dispatch(self, actuator_id: str, value: float,
                        success: bool, ts: float = 0.0):
        self.get(actuator_id).record_dispatch(value, success, ts)

    def effective_pct(self, actuator_id: str) -> float:
        return self.get(actuator_id).effective_pct()

    def trust_score(self, actuator_id: str) -> float:
        return self.get(actuator_id).trust_score

    def suspicious_ids(self) -> list:
        return [aid for aid, fb in self._records.items() if fb.is_suspicious]

    def state_dict(self) -> dict:
        return {
            aid: {
                'commanded_pct':    fb.commanded_pct,
                'trust_score':      round(fb.trust_score, 3),
                'mismatch_count':   fb.mismatch_count,
                'success_count':    fb.success_count,
                'last_dispatch_ok': fb.last_dispatch_ok,
            }
            for aid, fb in self._records.items()
        }
