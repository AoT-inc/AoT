# coding=utf-8
"""
calibration.py — P3-3: 효과계수 자동 캘리브레이션 (Recursive Least Squares).

알고리즘: 망각 RLS (λ=0.95)
  K̂(t+1) = K̂(t) + P(t)·x(t)·e(t) / (λ + P(t)·x(t)²)
  P(t+1) = (P(t) - P(t)·x(t)²·P(t) / (λ + P(t)·x(t)²)) / λ
  where x = cmd_pct/100, e = ΔY_obs - K̂·x

사용 조건:
  - Δcmd > 5%  (유의미한 변화만)
  - 외란 없음  (rain=0, wind < 5 m/s)
  - 수렴 보호: K_learned ∈ [K_default × 0.1, K_default × 5]

API:
  rls = RLSCalibrator(k_default=2.0, lambda_=0.95, bounds_factor=(0.1, 5.0))
  rls.update(cmd_pct_prev, cmd_pct_now, delta_obs, disturbed)
  k = rls.k_hat
  state = rls.state_dict()   # DB 저장용
  rls2 = RLSCalibrator.from_state(state)
"""

import math
from collections import deque
from typing import Dict, List, Optional, Tuple


# 액추에이터 kind 별 센서 응답 지연 사이클 수 (cycle_sec≈60s 기준)
# 명령 변화 이후 몇 사이클 뒤에 센서 변화를 관측할지 결정.
_LAG_CYCLES = {
    'opening':         3,
    'cooler':          3,
    'heater':          5,
    'fogger':          2,
    'co2_injector':    2,
    'shade':           4,
    'curtain':         5,
    'exhaust_fan':     3,
    'intake_fan':      3,
    'circulation_fan': 2,
}
_DEFAULT_LAG = 3


class RLSCalibrator:
    """단일 효과계수 K의 Recursive Least Squares 추정기."""

    def __init__(self, k_default: float, lambda_: float = 0.95,
                 bounds_factor: tuple = (0.1, 5.0)):
        self.k_default = float(k_default)
        self.lambda_   = float(lambda_)
        self.k_min     = self.k_default * bounds_factor[0]
        self.k_max     = self.k_default * bounds_factor[1]

        self.k_hat  = self.k_default  # 현재 추정값
        self._P     = 1.0             # 추정 분산 (초기 불확실성 크게)
        self.n_updates = 0

    # ── RLS 갱신 ─────────────────────────────────────────────────────────────

    def update(self, cmd_pct_prev: float, cmd_pct_now: float,
               delta_obs: float, disturbed: bool = False) -> bool:
        """관측 ΔY 를 이용해 K 추정값 갱신.

        Args:
            cmd_pct_prev: 이전 사이클 명령 (0~100)
            cmd_pct_now:  현재 사이클 명령 (0~100)
            delta_obs:    관측된 변수 변화량 (native 단위)
            disturbed:    외란 여부 (True 면 갱신 스킵)

        Returns:
            True if update was applied.
        """
        if disturbed:
            return False

        delta_cmd = abs(cmd_pct_now - cmd_pct_prev)
        if delta_cmd < 5.0:
            return False

        # 현재 적용된 명령이 응답을 만들므로 cmd_pct_now 를 리그레서로 사용
        x = cmd_pct_now / 100.0
        if abs(x) < 1e-6:
            return False

        lam = self.lambda_
        P   = self._P

        # 칼만 이득
        denom = lam + P * x * x
        gain  = P * x / denom

        # 예측 오차
        e = delta_obs - self.k_hat * x

        # 갱신
        self.k_hat = self.k_hat + gain * e
        self._P    = (P - gain * x * P) / lam

        # 수렴 보호
        self.k_hat = max(self.k_min, min(self.k_max, self.k_hat))
        self.n_updates += 1
        return True

    # ── 상태 직렬화 ───────────────────────────────────────────────────────────

    def state_dict(self) -> dict:
        return {
            'k_hat':      self.k_hat,
            'P':          self._P,
            'n_updates':  self.n_updates,
            'k_default':  self.k_default,
            'lambda_':    self.lambda_,
            'k_min':      self.k_min,
            'k_max':      self.k_max,
        }

    @classmethod
    def from_state(cls, state: dict) -> 'RLSCalibrator':
        obj = cls.__new__(cls)
        obj.k_default  = state['k_default']
        obj.lambda_    = state.get('lambda_', 0.95)
        obj.k_min      = state.get('k_min', obj.k_default * 0.1)
        obj.k_max      = state.get('k_max', obj.k_default * 5.0)
        obj.k_hat      = state.get('k_hat', obj.k_default)
        obj._P         = state.get('P', 1.0)
        obj.n_updates  = state.get('n_updates', 0)
        return obj

    @property
    def variance(self) -> float:
        return self._P

    def is_converged(self, threshold: float = 0.01) -> bool:
        """분산이 threshold 이하이면 수렴으로 판단."""
        return self._P < threshold


class ActuatorCalibrator:
    """단일 액추에이터의 (temperature, humidity, co2) 각 효과계수 RLS 추정.

    기능:
      - kind 별 lag 버퍼: 명령 변화 이후 τ 사이클 뒤 관측값을 매칭
      - trust_score 가중: 신뢰도 낮은 사이클은 RLS 갱신 스킵
      - 능동 탐색 가중치: probe 사이클은 가중치 ×2
    """

    _DEFAULT_K = {
        'opening':         {'temperature': 0.08, 'humidity': 0.06, 'co2': 0.04},
        'cooler':          {'temperature': 2.5,  'humidity': 0.8},
        'heater':          {'temperature': 2.0,  'humidity': 1.5},
        'fogger':          {'humidity': 3.0,     'temperature': 0.5},
        'co2_injector':    {'co2': 80.0},
        'shade':           {'temperature': 1.0},
        'curtain':         {'temperature': 2.0},
        'circulation_fan': {'temperature': 0.3,  'humidity': 0.5},
        'exhaust_fan':     {'temperature': 0.5,  'humidity': 0.5,  'co2': 0.3},
        'intake_fan':      {'temperature': 0.5,  'humidity': 0.5},
    }

    def __init__(self, actuator_id: str, kind: str, enabled: bool = False):
        self.actuator_id = actuator_id
        self.kind        = kind
        self.enabled     = enabled
        self._lag        = _LAG_CYCLES.get(kind, _DEFAULT_LAG)
        defaults = self._DEFAULT_K.get(kind, {})
        self._rls: Dict[str, RLSCalibrator] = {
            var: RLSCalibrator(k_def)
            for var, k_def in defaults.items()
        }
        # lag 버퍼: deque of (cmd_pct, sensor_snapshot_dict, clean_flag, probe_flag)
        self._lag_buf: deque = deque(maxlen=self._lag + 2)

    # ── 버퍼 기반 갱신 API (매 사이클 호출) ──────────────────────────────────

    def push_cycle(
        self,
        cmd_pct: float,
        sensor_snapshot: Dict[str, float],
        clean_for_learning: bool = True,
        trust_score: float = 1.0,
        is_probe: bool = False,
    ):
        """매 사이클 명령과 센서값을 버퍼에 적재.

        lag 사이클 수가 쌓이면 자동으로 RLS 갱신을 시도한다.
        """
        self._lag_buf.append({
            'cmd': cmd_pct,
            'sensors': dict(sensor_snapshot),
            'clean': clean_for_learning,
            'trust': trust_score,
            'probe': is_probe,
        })

        if len(self._lag_buf) < self._lag + 1:
            return   # 아직 lag 만큼 쌓이지 않음

        # (lag)번 앞 사이클 명령  vs  현재 사이클 센서
        past  = self._lag_buf[-self._lag - 1]
        now   = self._lag_buf[-1]

        if not past['clean'] or not now['clean']:
            return   # 오염된 사이클 스킵

        if past['trust'] < 0.5:
            return   # 신뢰도 낮은 액추에이터 스킵

        cmd_prev = self._lag_buf[-self._lag - 1 - 1]['cmd'] if len(self._lag_buf) > self._lag + 1 else 0.0
        cmd_now  = past['cmd']
        probe_w  = 2.0 if past['probe'] else 1.0

        for var, rls in self._rls.items():
            s_past = past['sensors'].get(var)
            s_now  = now['sensors'].get(var)
            if s_past is None or s_now is None:
                continue
            delta_obs = (s_now - s_past) * probe_w
            rls.update(cmd_prev, cmd_now, delta_obs, disturbed=False)

    def update(self, var: str, cmd_pct_prev: float, cmd_pct_now: float,
               delta_obs: float, disturbed: bool = False) -> bool:
        """직접 갱신 API (하위 호환 유지)."""
        if not self.enabled:
            return False
        rls = self._rls.get(var)
        if rls is None:
            return False
        return rls.update(cmd_pct_prev, cmd_pct_now, delta_obs, disturbed)

    def k_hat(self, var: str) -> float:
        rls = self._rls.get(var)
        return rls.k_hat if rls else 0.0

    def k_hat_all(self) -> Dict[str, float]:
        return {var: rls.k_hat for var, rls in self._rls.items()}

    def state_dict(self) -> dict:
        return {
            'actuator_id': self.actuator_id,
            'kind':        self.kind,
            'enabled':     self.enabled,
            'rls':         {var: rls.state_dict() for var, rls in self._rls.items()},
        }

    @classmethod
    def from_state(cls, state: dict) -> 'ActuatorCalibrator':
        obj = cls.__new__(cls)
        obj.actuator_id = state['actuator_id']
        obj.kind        = state['kind']
        obj.enabled     = state.get('enabled', False)
        obj._lag        = _LAG_CYCLES.get(obj.kind, _DEFAULT_LAG)
        obj._rls = {
            var: RLSCalibrator.from_state(rls_state)
            for var, rls_state in state.get('rls', {}).items()
        }
        obj._lag_buf = deque(maxlen=obj._lag + 2)
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# CalibrationRegistry — 전체 액추에이터 캘리브레이터 관리
# ─────────────────────────────────────────────────────────────────────────────

class CalibrationRegistry:
    """함수 단위로 모든 ActuatorCalibrator 를 보유하고 직렬화한다."""

    def __init__(self, enabled: bool = False):
        self.enabled  = enabled
        self._cals: Dict[str, ActuatorCalibrator] = {}

    def get_or_create(self, actuator_id: str, kind: str) -> ActuatorCalibrator:
        if actuator_id not in self._cals:
            self._cals[actuator_id] = ActuatorCalibrator(
                actuator_id, kind, enabled=self.enabled)
        return self._cals[actuator_id]

    def push_cycle(
        self,
        actuator_id: str,
        kind: str,
        cmd_pct: float,
        sensor_snapshot: Dict[str, float],
        clean_for_learning: bool = True,
        trust_score: float = 1.0,
        is_probe: bool = False,
    ):
        if not self.enabled:
            return
        cal = self.get_or_create(actuator_id, kind)
        cal.push_cycle(cmd_pct, sensor_snapshot, clean_for_learning,
                       trust_score, is_probe)

    def k_hat(self, actuator_id: str, var: str) -> Optional[float]:
        """학습된 K 반환. 없으면 None (효과함수가 기본값 사용)."""
        cal = self._cals.get(actuator_id)
        if cal is None:
            return None
        rls = cal._rls.get(var)
        if rls is None or rls.n_updates < 5:
            return None    # 수렴 전 기본값 유지
        return rls.k_hat

    def state_dict(self) -> dict:
        return {
            'enabled': self.enabled,
            'cals':    {aid: c.state_dict() for aid, c in self._cals.items()},
        }

    @classmethod
    def from_state(cls, state: dict) -> 'CalibrationRegistry':
        obj = cls(enabled=state.get('enabled', False))
        for aid, cs in state.get('cals', {}).items():
            obj._cals[aid] = ActuatorCalibrator.from_state(cs)
        return obj


def is_disturbed(ext_ctx: dict, wind_threshold: float = 5.0) -> bool:
    """외란 여부 판단 — 강우 또는 강풍 시 True."""
    rain = ext_ctx.get('rain', 0.0) or 0.0
    wind = ext_ctx.get('wind', 0.0) or 0.0
    return rain > 0 or wind > wind_threshold
