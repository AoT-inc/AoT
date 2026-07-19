# coding=utf-8
"""
env_control/active_probe.py — 능동 탐색 스케줄러 (Stage 1).

안전 조건이 충족되고 제어 부하가 낮을 때 단일 액추에이터를 ±10% 흔들어
학습 식별성을 높인다.

진입 조건:
  - safety_gate 비활성 (gate_result.triggered = False)
  - 최대 편차 < tolerance × 0.5 (제어 여유 충분)
  - 이전 탐색으로부터 probe_interval_sec 이상 경과

동작:
  - 대상 액추에이터 1개 무작위 선택
  - 현재 명령에 PROBE_DELTA_PCT 가산 (0~100 클램프)
  - 2 사이클 유지 후 원복
  - CalibrationRegistry.push_cycle 에 is_probe=True 전달
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

PROBE_DELTA_PCT     = 10.0    # 탐색 변동 폭 (%)
PROBE_HOLD_CYCLES   = 2       # 탐색 유지 사이클 수
DEFAULT_INTERVAL_S  = 3600.0  # 탐색 최소 간격 (초)


@dataclass
class ProbeState:
    """진행 중인 탐색 상태."""
    target_id: str
    original_pct: float
    probe_pct: float
    remaining_cycles: int
    started_ts: float = field(default_factory=time.time)

    @property
    def active(self) -> bool:
        return self.remaining_cycles > 0


class ActiveProbeScheduler:
    """매 사이클 호출되어 탐색 개시·진행·종료를 관리."""

    def __init__(self, interval_sec: float = DEFAULT_INTERVAL_S, enabled: bool = False):
        self.enabled      = enabled
        self.interval_sec = interval_sec
        self._last_ts: float        = 0.0
        self._state: Optional[ProbeState] = None

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def step(
        self,
        commands: Dict[str, float],           # 현재 사이클 명령 {actuator_id: pct}
        profiles: list,                        # ActuatorProfile 목록
        situation,                             # SituationReport (편차 확인용)
        gate_triggered: bool = False,
    ) -> tuple[Dict[str, float], bool]:
        """탐색 로직 실행.

        Returns:
            (modified_commands, is_probe_cycle)
        """
        if not self.enabled:
            return commands, False

        # 진행 중 탐색 계속
        if self._state and self._state.active:
            cmds = dict(commands)
            cmds[self._state.target_id] = self._state.probe_pct
            self._state.remaining_cycles -= 1
            if not self._state.active:
                self._state = None    # 탐색 완료
            return cmds, True

        # 새 탐색 개시 조건
        now = time.time()
        if gate_triggered:
            return commands, False
        if (now - self._last_ts) < self.interval_sec:
            return commands, False
        if not self._is_low_load(situation):
            return commands, False

        # 대상 선택 (kind 필터: 효과가 있는 종류만)
        candidates = [
            p for p in profiles
            if p.kind not in ('circulation_fan',)
            and p.actuator_id in commands
        ]
        if not candidates:
            return commands, False

        target = random.choice(candidates)
        orig   = float(commands.get(target.actuator_id, 0.0))
        delta  = PROBE_DELTA_PCT if random.random() > 0.5 else -PROBE_DELTA_PCT
        probe  = max(0.0, min(100.0, orig + delta))

        self._state = ProbeState(
            target_id=target.actuator_id,
            original_pct=orig,
            probe_pct=probe,
            remaining_cycles=PROBE_HOLD_CYCLES,
        )
        self._last_ts = now

        cmds = dict(commands)
        cmds[target.actuator_id] = probe
        return cmds, True

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    @staticmethod
    def _is_low_load(situation) -> bool:
        """모든 변수의 편차가 tolerance × 0.5 미만이어야 저부하로 판단."""
        if situation is None:
            return False
        for var, dev in situation.deviation_native.items():
            t = situation.target.get(var)
            if t and abs(dev) >= t.tolerance * 0.5:
                return False
        return True
