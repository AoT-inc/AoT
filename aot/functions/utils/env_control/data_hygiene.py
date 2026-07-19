# coding=utf-8
"""
env_control/data_hygiene.py — 학습 데이터 품질 검사.

is_clean_for_learning() 은 매 사이클 호출되어 해당 사이클의 센서·명령 데이터를
Stage 1 RLS 학습에 사용할 수 있는지 판단한다.

오염 판정 기준:
  1. 외란: 강우 또는 강풍 (is_disturbed 재사용)
  2. 일사 급변: 전 사이클 대비 solar 변화 > SOLAR_JUMP_W (클라우드 패스)
  3. 다중 액추에이터 동시 변경: 두 개 이상이 동시에 크게 움직이면 식별성 저하
  4. 센서 이상치: MAD 기반 robust z-score 로 급격한 내부 환경 변화 감지
"""

from __future__ import annotations

from collections import deque
from typing import Dict, Optional

# 임계값
SOLAR_JUMP_W          = 100.0   # W/m²: 클라우드 패스 판정
MULTI_ACT_THRESHOLD   = 10.0   # %: 동시 큰 변화 판정 기준
MULTI_ACT_MAX_COUNT   = 2      # 이 수 초과 시 오염
MAD_OUTLIER_FACTOR    = 3.5    # k·MAD 초과 시 이상치
_HISTORY_LEN          = 30     # robust z-score 계산 윈도우


class DataHygieneChecker:
    """사이클마다 호출되며 학습 가능 여부를 반환하는 상태형 검사기."""

    def __init__(self, wind_threshold: float = 5.0):
        self._wind_threshold    = wind_threshold
        self._solar_history: deque     = deque(maxlen=_HISTORY_LEN)
        self._T_history: deque         = deque(maxlen=_HISTORY_LEN)
        self._RH_history: deque        = deque(maxlen=_HISTORY_LEN)
        self._prev_solar: Optional[float] = None
        self._prev_cmds: Dict[str, float]  = {}

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def check(
        self,
        external: dict,
        internal: dict,
        current_cmds: Dict[str, float],
    ) -> bool:
        """
        True  = 이번 사이클 데이터는 학습에 사용 가능(clean).
        False = 오염 — 학습 스킵.
        """
        solar = external.get('solar', 0.0) or 0.0
        wind  = external.get('wind',  0.0) or 0.0
        rain  = external.get('rain',  0.0) or 0.0
        T     = internal.get('T')
        RH    = internal.get('RH')

        # 1. 외란
        if rain > 0 or wind > self._wind_threshold:
            self._update_history(solar, T, RH, current_cmds)
            return False

        # 2. 일사 급변
        if self._prev_solar is not None and abs(solar - self._prev_solar) > SOLAR_JUMP_W:
            self._update_history(solar, T, RH, current_cmds)
            return False

        # 3. 다중 액추에이터 동시 큰 변화 (식별성 저하)
        large_movers = sum(
            1 for aid, v in current_cmds.items()
            if abs(v - self._prev_cmds.get(aid, 0.0)) >= MULTI_ACT_THRESHOLD
        )
        if large_movers > MULTI_ACT_MAX_COUNT:
            self._update_history(solar, T, RH, current_cmds)
            return False

        # 4. 센서 이상치
        if T is not None and _is_outlier(T, self._T_history):
            self._update_history(solar, T, RH, current_cmds)
            return False
        if RH is not None and _is_outlier(RH, self._RH_history):
            self._update_history(solar, T, RH, current_cmds)
            return False

        self._update_history(solar, T, RH, current_cmds)
        return True

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    def _update_history(self, solar, T, RH, cmds):
        self._prev_solar = solar
        if T is not None:
            self._T_history.append(T)
        if RH is not None:
            self._RH_history.append(RH)
        self._solar_history.append(solar)
        self._prev_cmds = dict(cmds)


def _is_outlier(value: float, history: deque) -> bool:
    """MAD 기반 robust z-score 로 이상치를 판정."""
    if len(history) < 5:
        return False
    import statistics
    median = statistics.median(history)
    deviations = [abs(x - median) for x in history]
    mad = statistics.median(deviations)
    if mad < 1e-6:
        return False
    z = abs(value - median) / (1.4826 * mad)
    return z > MAD_OUTLIER_FACTOR
