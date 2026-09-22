# coding=utf-8
"""
calibration.py — P3-3: 효과 배율 자동 캘리브레이션 (Recursive Least Squares).

## 무엇을 배우나 — K 가 아니라 **모델 대비 배율 θ** (2026-09-22 재설계)

효과 함수의 K 는 조건과 곱해지는 계수다 — 개구부 온도 효과는
`|ΔT| × 개도 × K × 풍속 보정 × 면적 × 형태`. 예전 RLS 는 `ΔY ≈ K × (cmd/100)` 을
배워 그 값을 효과 함수의 K 자리에 **그대로 넣었다.** 단위가 다르다 — ΔT·풍속·
면적이 이미 곱해지는 자리에 그것들을 뺀 값이 들어가면 모델이 통째로 틀어진다.
또 관측 ΔY 는 부호가 있는데 K 는 양수 크기라 내리는 장치(냉방의 온도)는 K 가
하한에 붙었다.

그래서 이제는 **모델이 예측한 변화 대비 실제 변화의 비율 θ** 를 배운다.

  x = lag × (Δcmd/100) × 예측 속도(100 % 기준, 부호 있음)   ← 모델 예측
  y = (이후 lag 사이클의 관측 변화) − lag × (명령 바꾸기 전 기울기) ← 관측
  y ≈ θ · x

θ 는 무차원이고 기본값 1.0(= 모델 그대로)이다. 효과 함수는 자기 K 에 θ 를 곱한다
(`effect_functions._calibrated_k`). 조건(ΔT·풍속·면적)은 모델이 계속 맡으므로 단위가
맞고, 예측과 관측이 둘 다 부호를 가지므로 내리는 장치도 θ≈1 로 수렴한다.

## 효과를 섞지 않는다

관측 변화는 모든 장치와 외란이 함께 만든다. 그래서 **이 장치만** 명령이 바뀐
사이클에서만 배운다(`others_steady`) — 다른 장치가 같이 움직이면 누구 몫인지 가를
수 없다. 명령 바꾸기 직전의 기울기를 빼서 이미 진행 중이던 흐름도 덜어낸다.

## 능동 탐색 가중치

탐색(probe) 사이클은 계획된 단독 가진이라 더 믿을 만하다 — **갱신의 무게**를 2배로
둔다(가중 최소제곱). 예전에는 관측값 자체를 2배로 만들어 K 를 2배 쪽으로 끌었다.

사용 조건:
  - Δcmd ≥ 5 %, 예측 |x| 가 너무 작지 않을 것
  - 외란 없음(데이터 위생 clean), 장치 신뢰도 ≥ 0.5, 다른 장치 정지
  - 수렴 보호: θ ∈ [0.1, 5]
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

    def update_xy(self, x: float, y: float, weight: float = 1.0) -> bool:
        """y ≈ k·x 한 점으로 갱신(가중 RLS). 리그레서를 호출자가 만든다.

        `weight` 는 이 관측의 무게다 — √w 를 x·y 양쪽에 곱하는 것이 가중 최소제곱이다.
        관측값에만 곱하면 추정치가 그 배수 쪽으로 끌린다.
        """
        if abs(x) < 1e-9 or weight <= 0.0:
            return False
        r = math.sqrt(weight)
        x, y = x * r, y * r
        lam, P = self.lambda_, self._P
        gain = P * x / (lam + P * x * x)
        self.k_hat = self.k_hat + gain * (y - self.k_hat * x)
        self._P = (P - gain * x * P) / lam
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
    """단일 액추에이터의 변수별(temperature, humidity, co2) **효과 배율 θ** 추정.

    기능:
      - kind 별 lag 버퍼: 명령 변화 이후 τ 사이클 뒤 관측값을 매칭
      - trust_score 가중: 신뢰도 낮은 사이클은 RLS 갱신 스킵
      - 다른 장치가 함께 움직인 사이클은 스킵(효과를 섞지 않는다)
      - 능동 탐색 가중치: probe 사이클은 갱신 무게 ×2
    """

    # 배율을 배우는 변수. VPD 는 온도·습도 효과에서 유도되므로 따로 배우지 않는다.
    VARS = ('temperature', 'humidity', 'co2')
    # 예측 변화가 이보다 작으면 비율이 잡음에 휘둘린다(native 단위, lag 전체).
    _MIN_PRED = {'temperature': 0.05, 'humidity': 0.2, 'co2': 5.0}
    MODEL = 'scale_v1'

    def __init__(self, actuator_id: str, kind: str, enabled: bool = False):
        self.actuator_id = actuator_id
        self.kind        = kind
        self.enabled     = enabled
        self._lag        = _LAG_CYCLES.get(kind, _DEFAULT_LAG)
        self._rls: Dict[str, RLSCalibrator] = {
            var: RLSCalibrator(1.0) for var in self.VARS
        }
        self._lag_buf: deque = deque(maxlen=self._lag + 3)

    # ── 버퍼 기반 갱신 API (매 사이클 호출) ──────────────────────────────────

    def push_cycle(
        self,
        cmd_pct: float,
        sensor_snapshot: Dict[str, float],
        clean_for_learning: bool = True,
        trust_score: float = 1.0,
        is_probe: bool = False,
        pred_rate100: Optional[Dict[str, float]] = None,
        others_steady: bool = True,
    ):
        """매 사이클 명령·센서·예측을 버퍼에 적재하고, 조건이 되면 θ 를 갱신한다.

        Args:
            pred_rate100:  변수별 **부호 있는** 예측 변화 속도(native/사이클, 100 % 기준)
                           — 코디네이터의 `live_effect`(↑=+, ↓=−). 없으면 배우지 않는다.
            others_steady: 이 사이클에 **다른** 장치의 명령이 거의 안 바뀌었는가.
        """
        self._lag_buf.append({
            'cmd': cmd_pct,
            'sensors': dict(sensor_snapshot),
            'clean': clean_for_learning,
            'trust': trust_score,
            'probe': is_probe,
            'pred': dict(pred_rate100 or {}),
            'steady': others_steady,
        })
        L = self._lag
        if len(self._lag_buf) < L + 2:
            return
        pre, past, now = self._lag_buf[-L - 2], self._lag_buf[-L - 1], self._lag_buf[-1]
        window = list(self._lag_buf)[-L - 2:]
        if not all(e['clean'] for e in window):
            return   # 오염된 사이클 스킵
        if past['trust'] < 0.5:
            return   # 신뢰도 낮은 액추에이터 스킵
        if not past['steady']:
            return   # 다른 장치가 같이 움직였다 — 누구 몫인지 가를 수 없다
        d_cmd = past['cmd'] - pre['cmd']
        if abs(d_cmd) < 5.0:
            return
        weight = 2.0 if past['probe'] else 1.0
        for var, rls in self._rls.items():
            rate = past['pred'].get(var)
            s_pre, s_past, s_now = (e['sensors'].get(var) for e in (pre, past, now))
            if rate is None or None in (s_pre, s_past, s_now):
                continue
            x = L * (d_cmd / 100.0) * rate
            if abs(x) < self._MIN_PRED.get(var, 0.0):
                continue
            y = (s_now - s_past) - L * (s_past - s_pre)
            rls.update_xy(x, y, weight)

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
            'model':       self.MODEL,
            'rls':         {var: rls.state_dict() for var, rls in self._rls.items()},
        }

    @classmethod
    def from_state(cls, state: dict) -> 'ActuatorCalibrator':
        """저장 상태에서 복원. **옛 K 모델 상태는 버린다** — 단위가 다른 값이다.

        예전 상태(`model` 없음)의 k_hat 은 `ΔY/(cmd/100)` 이라 배율 θ 자리에 넣으면
        모델을 수십 배로 키우거나 줄인다. 기본값(θ=1)에서 다시 배운다.
        """
        obj = cls(state['actuator_id'], state['kind'], state.get('enabled', False))
        if state.get('model') != cls.MODEL:
            return obj
        for var, rls_state in state.get('rls', {}).items():
            obj._rls[var] = RLSCalibrator.from_state(rls_state)
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
        pred_rate100: Optional[Dict[str, float]] = None,
        others_steady: bool = True,
    ):
        if not self.enabled:
            return
        cal = self.get_or_create(actuator_id, kind)
        cal.push_cycle(cmd_pct, sensor_snapshot, clean_for_learning,
                       trust_score, is_probe, pred_rate100, others_steady)

    def k_hat(self, actuator_id: str, var: str) -> Optional[float]:
        """학습된 **배율 θ** 반환(이름은 저장 형식 호환을 위해 k_hat). 없으면 None."""
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
