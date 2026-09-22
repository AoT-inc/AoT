# coding=utf-8
"""
env_control/solar_lead.py — 일사 선행 예측(그림자 기록 전용).

## 왜

일사가 바뀌면 실내 온도가 뒤따라 움직인다. 2026-09-22 aot-005 지난 7일(흐린 날·맑은 날
혼재, 10분 단위)을 보면, 일사가 10분 새 ±300 W/m² 바뀐 사건 71건 평균에서 실내 온도가
**10~20분 뒤 ±0.6~0.8 °C** 따라오고 20~30분에 정점, 그 뒤 창 제어가 되돌렸다. 제어
주기가 10분이면 온도를 보고 반응할 때 이미 정점 근처다 — 선행 지표가 쓸모 있을 자리다.

그런데 사건 하나하나의 예측력은 약했다. "지금 일사 − 최근 60분 평균" 으로 20~30분 뒤
온도 변화를 예측하면, 앞 4일로 맞추고 뒤 3일로 재서 "변화 없음" 대비 skill **+0.10~0.16**
이었다(창 되먹임·10분 해상도·짧은 구름). 구름마다 창을 여닫게 할 위험이 더 커서
**제어에 쓰지 않고 기록만** 한다 — 여러 현장·계절의 skill 을 보고 정한다.

## 무엇을 기록하나

    x      = S − S̄₆₀          (지금 일사 − 60분 지수평균) [W/m²]
    ΔT̂     = g · x            20분 뒤 실내 온도 변화 예측 [°C]
    g      현장에서 배운다 — 20분이 지나 실제 변화가 나오면 (x, ΔT) 로 갱신
           (망각 최소제곱, 사전값 100 W/m² 당 0.3 °C = aot-005 분석값)
    skill  1 − RMSE(ΔT̂) / RMSE(0) — 낮(일사 > 20 W/m²)만, **예측 당시의 g** 로 잰다
           (나중에 배운 g 로 과거를 다시 맞히면 점수가 부풀려진다).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Optional

TAU_S       = 3600.0     # 일사 평균의 시정수 — 분석에서 가장 나았던 60분
HORIZON_S   = 1200.0     # 20분 뒤를 예측
G_PRIOR     = 0.003      # °C per W/m² (= 100 W/m² 당 0.3 °C)
PRIOR_N     = 50.0       # 사전값의 무게(표본 수 환산)
FORGET      = 0.999      # 표본마다 곱하는 망각 인자
DAY_SOLAR   = 20.0       # W/m² — 이보다 어두우면 평가하지 않는다
MIN_SKILL_N = 30


class SolarLead:
    def __init__(self):
        self.S_f: Optional[float] = None
        self.t_last: Optional[float] = None
        self.sxx = PRIOR_N * (100.0 ** 2)          # 사전: x = 100 W/m² 표본 PRIOR_N 개
        self.sxy = PRIOR_N * (100.0 ** 2) * G_PRIOR
        self._pending: deque = deque(maxlen=512)   # (t, x, T, g_at_pred, daytime)
        self.n = 0
        self.se_model = 0.0
        self.se_zero = 0.0

    @property
    def g(self) -> float:
        return self.sxy / self.sxx if self.sxx > 0 else G_PRIOR

    def step(self, now: float, solar: Optional[float], T: Optional[float],
             dt: float) -> Optional[dict]:
        """한 사이클. 일사를 모르면 아무것도 하지 않는다(None)."""
        if solar is None:
            return None
        S = float(solar)
        if self.S_f is None:
            self.S_f = S
        else:
            gap = dt if self.t_last is None else max(0.0, now - self.t_last)
            a = 1.0 - math.exp(-gap / TAU_S)
            self.S_f += a * (S - self.S_f)
        self.t_last = now
        x = S - self.S_f

        if T is not None:
            self._resolve(now, float(T))
            self._pending.append((now, x, float(T), self.g, S > DAY_SOLAR))

        skill = None
        if self.n >= MIN_SKILL_N and self.se_zero > 1e-12:
            skill = round(1.0 - math.sqrt(self.se_model / self.se_zero), 3)
        return {'x': round(x, 1), 'pred_dT': round(self.g * x, 3),
                'g_per_100W': round(self.g * 100.0, 3), 'horizon_min': HORIZON_S / 60.0,
                'n': self.n, 'skill': skill}

    def _resolve(self, now: float, T_now: float) -> None:
        """예측한 지 HORIZON_S 가 지난 것을 실제 변화와 맞춰 본다."""
        while self._pending and now - self._pending[0][0] >= HORIZON_S:
            t0, x0, T0, g0, day = self._pending.popleft()
            # 너무 늦게 풀리는 표본(데이터 공백)은 버린다 — 지평이 달라진다.
            if now - t0 > HORIZON_S * 1.5:
                continue
            y = T_now - T0
            self.sxx = FORGET * self.sxx + x0 * x0
            self.sxy = FORGET * self.sxy + x0 * y
            if day:
                self.n += 1
                self.se_model += (y - g0 * x0) ** 2
                self.se_zero += y * y


__all__ = ['SolarLead', 'TAU_S', 'HORIZON_S', 'G_PRIOR']
