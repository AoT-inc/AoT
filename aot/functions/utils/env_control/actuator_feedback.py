# coding=utf-8
"""
env_control/actuator_feedback.py — 액추에이터 실제 상태 추적 및 신뢰도·의심 관리.

명령(commanded_pct)과 실제 반응(actual_pct) 의 불일치를 감지하여
trust_score 를 관리한다. Stage 1 캘리브레이션 학습기가 trust_score 를
가중치로 사용한다.

실제 위치 피드백이 없는 경우(대부분의 온실 액추에이터): dispatch 성공/실패를
피드백 대리값으로 사용하고, 센서 응답(온도·습도 변화)이 명령과 반대 방향이면
mismatch 로 감지한다(Stage 1 에서 통합).

## 의심(suspected) — 제어가 읽는 판정 (2026-10-09)

`trust_score` 는 **학습 가중치와 로그**에만 쓰였고 제어는 아무것도 바꾸지 않았다. 고장난 장치에
계속 명령을 쌓으면 적분이 와인드업하고, 그 장치가 하고 있다고 믿는 몫이 부하 분담 장부에 남아
나머지 장치가 덜 일한다. 그래서 별도 판정이 있다 — 의심 상태의 장치는 코디네이터가 **부하 분담에서
빼고 제자리에 둔다**(근거 `REASON_ACTUATOR_SUSPECT`, 전송도 하지 않는다).

의심이 되는 경로는 둘이다.

  ① 전송 실패가 이어졌다 — `SUSPECT_FAIL_CYCLES` 사이클 연속(그리고 `SUSPECT_FAIL_SPAN_S` 이상 걸쳐)
     실패. 성공이 한 번이라도 섞이면 처음부터 센다. (전송 실패는 `dispatch_adapters` 가 데몬의
     거부를 예외로 올려 `failed` 에 들어온다 — 조용한 성공이 아니다.)
  ② 오래 세게 명령했는데 반응이 없다 — 코디네이터의 반응 없음 판정(`coordinator.NOFX_*`)이 낸 후보를
     `record_no_effect` 가 받는다. **같은 도메인에서 다른 장치를 최근에 제외했으면 받지 않는다**
     (`NOFX_DOMAIN_COOLDOWN_S`) — 센서가 명령에 반응하지 않는 열린 루프 시설에서 창이 차례로
     전부 제외되는 연쇄를 막는다.

⚠ **`is_suspicious`(trust_score < 0.5 or mismatch_count > 5)는 이 판정이 아니다.** `mismatch_count`
   는 평생 누적이라 몇 주에 걸쳐 흩어진 실패 6번이면 영원히 의심이 된다 — 학습 가중치에는 괜찮아도
   제어에서 장치를 빼는 근거로는 거짓 양성이 너무 많다. 그래서 의심은 **연속·시간**으로 따로 센다.

## 회복

의심은 `SUSPECT_HOLD_S` 뒤에 **자동으로 풀린다**(재시도). 풀린 직후는 시험 기간이다 — 전송 실패는
`PROBATION_FAIL_CYCLES` 번만 연속돼도 다시 의심이 되고, 전송이 한 번 성공하면 시험이 끝난다.
의심 중에는 전송을 하지 않으므로 그 사이 회복을 관찰할 방법이 없다 — 그래서 시간으로 푼다.
영속화하지 않는다: 재시작하면 모두 풀린다(보수적 — 장치를 계속 쓴다).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# 신뢰도 감쇠·회복 계수
_TRUST_DECAY   = 0.15   # dispatch 실패 1회당 감쇠
_TRUST_RECOVER = 0.05   # dispatch 성공 1회당 회복
_MISMATCH_DECAY = 0.10  # 센서 불응 감지 시 추가 감쇠
_MIN_TRUST     = 0.1
_MAX_TRUST     = 1.0

# ── 의심 판정 문턱 ────────────────────────────────────────────────────────────
# @manual ai/env-control#actuators-suspected
SUSPECT_FAIL_CYCLES = 5        # 연속 전송 실패 이만큼이면 의심(① 경로)
SUSPECT_FAIL_SPAN_S = 240.0    # …그리고 첫 실패에서 이만큼은 지나야(주기가 짧아도 일시 두절과 가른다)
PROBATION_FAIL_CYCLES = 2      # 풀린 직후엔 이만큼만 연속 실패해도 다시 의심
SUSPECT_HOLD_S = 1800.0        # 의심을 이만큼 두었다가 자동으로 풀어 재시도한다(30분)
NOFX_DOMAIN_COOLDOWN_S = 21600.0   # 한 도메인에서 '반응 없음' 으로 제외한 뒤 다음 제외까지 쉬는 시간(6시간)

# @manual-end

# 의심 사유
REASON_DISPATCH = 'dispatch'    # 전송 실패가 이어졌다
REASON_NO_EFFECT = 'no_effect'  # 오래 세게 명령했는데 반응이 없다


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
    # ── 의심 상태(제어가 읽는다) ─────────────────────────────────────────────
    fail_streak: int = 0                 # 연속 전송 실패 수
    fail_first_ts: float = 0.0           # 그 연속의 첫 실패 시각
    suspected: bool = False
    suspect_reason: str = ''             # REASON_DISPATCH / REASON_NO_EFFECT
    suspect_since: float = 0.0
    probation: bool = False              # 풀린 직후 시험 기간
    suspect_count: int = 0               # 지금까지 의심이 된 횟수(진단용)

    def record_dispatch(self, value: float, success: bool, ts: float = 0.0):
        """dispatch 결과를 기록하고 trust_score 를 업데이트."""
        self.commanded_pct    = value
        self.last_dispatch_ts = ts or time.time()
        self.last_dispatch_ok = success
        if success:
            self.success_count += 1
            self.trust_score = min(_MAX_TRUST,
                                   self.trust_score + _TRUST_RECOVER)
            self.fail_streak = 0
            self.fail_first_ts = 0.0
            if self.probation:
                self.probation = False      # 풀린 뒤 첫 성공 — 회복
        else:
            self.mismatch_count += 1
            self.trust_score = max(_MIN_TRUST,
                                   self.trust_score - _TRUST_DECAY)
            if self.fail_streak == 0:
                self.fail_first_ts = self.last_dispatch_ts
            self.fail_streak += 1
            need = PROBATION_FAIL_CYCLES if self.probation else SUSPECT_FAIL_CYCLES
            span = 0.0 if self.probation else SUSPECT_FAIL_SPAN_S
            if (not self.suspected and self.fail_streak >= need
                    and (self.last_dispatch_ts - self.fail_first_ts) >= span):
                self._suspect(REASON_DISPATCH, self.last_dispatch_ts)

    def record_sensor_mismatch(self):
        """Stage 1: 센서 응답이 명령과 반대 방향일 때 호출."""
        self.mismatch_count += 1
        self.trust_score = max(_MIN_TRUST,
                               self.trust_score - _MISMATCH_DECAY)

    def _suspect(self, reason: str, ts: float):
        self.suspected = True
        self.suspect_reason = reason
        self.suspect_since = ts
        self.probation = False
        self.suspect_count += 1

    def release_if_due(self, now: float) -> bool:
        """`SUSPECT_HOLD_S` 가 지났으면 풀고(시험 기간으로) True."""
        if self.suspected and (now - self.suspect_since) >= SUSPECT_HOLD_S:
            self.suspected = False
            self.suspect_reason = ''
            self.probation = True
            # 시험은 새로 센다 — 의심 전의 실패 연속을 이어받지 않는다.
            self.fail_streak = 0
            self.fail_first_ts = 0.0
            return True
        return False

    def effective_pct(self) -> float:
        """제어에 사용할 '현재 위치' 추정값 (actual > commanded 순)."""
        if self.actual_pct is not None:
            return self.actual_pct
        return self.commanded_pct

    @property
    def is_suspicious(self) -> bool:
        """학습 가중치·로그용 — 제어는 `suspected` 를 읽는다(모듈 머리말)."""
        return self.trust_score < 0.5 or self.mismatch_count > 5


class ActuatorFeedbackRegistry:
    """모든 액추에이터 피드백 레코드를 관리하는 레지스트리."""

    def __init__(self):
        self._records: Dict[str, ActuatorFeedback] = {}
        # 도메인별로 '반응 없음' 제외를 마지막에 한 시각 — 연쇄 제외를 막는 쿨다운.
        self._noeffect_domain_ts: Dict[str, float] = {}

    def get(self, actuator_id: str) -> ActuatorFeedback:
        if actuator_id not in self._records:
            self._records[actuator_id] = ActuatorFeedback(actuator_id=actuator_id)
        return self._records[actuator_id]

    def record_dispatch(self, actuator_id: str, value: float,
                        success: bool, ts: float = 0.0):
        self.get(actuator_id).record_dispatch(value, success, ts)

    def record_no_effect(self, actuator_id: str, domain: str = '',
                         ts: float = 0.0) -> bool:
        """코디네이터의 '오래 세게 명령했는데 반응이 없다' 후보를 받는다 → 의심이 됐으면 True.

        `record_sensor_mismatch` 가 이 경로의 입구다(신뢰도 감쇠는 한 번만 — 이미 의심이면 무시).
        같은 도메인에서 최근(`NOFX_DOMAIN_COOLDOWN_S`)에 다른 장치를 이 사유로 제외했으면 받지
        않는다 — 열린 루프 시설에서 창이 차례로 전부 제외되는 연쇄를 막는다.
        """
        fb = self.get(actuator_id)
        if fb.suspected:
            return False
        now = ts or time.time()
        last = self._noeffect_domain_ts.get(domain)
        if last is not None and (now - last) < NOFX_DOMAIN_COOLDOWN_S:
            return False
        fb.record_sensor_mismatch()
        fb._suspect(REASON_NO_EFFECT, now)
        self._noeffect_domain_ts[domain] = now
        return True

    def refresh(self, now: float = 0.0) -> List[str]:
        """기한이 찬 의심을 풀고 → 풀린 id 목록."""
        now = now or time.time()
        return [aid for aid, fb in self._records.items() if fb.release_if_due(now)]

    def suspected_ids(self) -> List[str]:
        return [aid for aid, fb in self._records.items() if fb.suspected]

    def suspect_reason(self, actuator_id: str) -> str:
        fb = self._records.get(actuator_id)
        return fb.suspect_reason if fb and fb.suspected else ''

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
                'actual_pct':       fb.actual_pct,
                'trust_score':      round(fb.trust_score, 3),
                'mismatch_count':   fb.mismatch_count,
                'success_count':    fb.success_count,
                'last_dispatch_ok': fb.last_dispatch_ok,
                'suspected':        fb.suspected,
                'suspect_reason':   fb.suspect_reason,
            }
            for aid, fb in self._records.items()
        }
