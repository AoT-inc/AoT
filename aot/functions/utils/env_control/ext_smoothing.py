# coding=utf-8
"""실외 온습도의 시간 이동평균 — 판단용 값만 고르고 안전 판정은 원본을 본다 (2026-10-01).

## 왜

실외 기상 값은 몇 분~한 시간에 한 번 들어오고, 정수 단위(습도 1 %p)로 바뀐다. 과습
구간에서는 실내외 VPD·이슬점 차이가 0.1 kPa 안팎이라 그 한 칸이 판정을 뒤집는다.
실측(로컬 쿠마모토, 2026-10-01): 실외 습도가 88 ↔ 94 % 를 오가자 VPD 차이가 +0.15 ↔ 0.00
을 오갔고, 천창이 그때마다 열렸다 닫혔다(근거 1 ↔ 15, 2시간 주기).

## 무엇을 고르고 무엇을 안 고르는가

  · 고르는 것: 온도·습도(`T`·`RH`·`T_ext`·`RH_ext`) — 환기 효과 모델·무익 판정·과습 구간이
    읽는 값이다. 시간 상수 `EXT_SMOOTH_TAU_S`(30분).
  · 고르지 않는 것: 강우·풍속·풍향·일사 — 안전 게이트는 **원본**을 본다(`_build_gate_env`
    는 이 모듈을 거치지 않는다). 비가 오기 시작했는데 평균이 늦게 따라오면 안 된다.
  · 지어낸 값(`_ext_synthetic`)은 평균하지 않는다 — 없는 값을 평균에 섞는 것은 더 나쁘다.

## 끊김

사이클 사이가 `RESET_GAP_S` 를 넘으면 평균을 버리고 원본에서 다시 시작한다 — 재시작 뒤에
두 시간 전 값이 끌려오면 안 된다.
"""
# @manual ai/env-control#humid-zone
from __future__ import annotations

import math
from typing import Dict, Optional

# ⚠ 30분이던 것을 10분으로 줄였다(2026-10-01). 아침에 외기가 빠르게 건조해질 때 평균이 늦게
#   따라와, 원본으로는 VPD 차이 0.35 kPa 인데 평균으로는 0.1~0.25 로 읽혀 환기 무익(문턱 0.25)이
#   40분 넘게 창을 닫아 두었다(쿠마모토 10:11~10:51 재현 — 실내 VPD 0.5 · 목표 1.0).
#   잡음 억제는 `VENT_MIN_VPD_GAP` 이 이미 맡는다. 사이클 주기(10분) 정도면 정수 단위 한 칸을 고른다.
EXT_SMOOTH_TAU_S = 600.0
RESET_GAP_S = 7200.0

_PAIRS = (('T', 'RH'), ('T_ext', 'RH_ext'))


class OutdoorSmoother:
    def __init__(self, tau_s: float = EXT_SMOOTH_TAU_S,
                 reset_gap_s: float = RESET_GAP_S):
        self.tau_s = float(tau_s)
        self.reset_gap_s = float(reset_gap_s)
        self._last_ts: Optional[float] = None
        self._state: Dict[str, float] = {}

    def reset(self) -> None:
        self._last_ts = None
        self._state = {}

    def smooth(self, ext: dict, now_ts: float) -> dict:
        """`ext` 의 복사본을 돌려준다(입력을 고치지 않는다)."""
        if not isinstance(ext, dict) or ext.get('_ext_synthetic'):
            self.reset()
            return ext
        dt = None if self._last_ts is None else max(0.0, now_ts - self._last_ts)
        if dt is None or dt > self.reset_gap_s:
            self._state = {}
            alpha = 1.0
        else:
            alpha = 1.0 - math.exp(-dt / self.tau_s) if self.tau_s > 0 else 1.0
        out = dict(ext)
        for keys in _PAIRS:
            for k in keys:
                v = ext.get(k)
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    self._state.pop(k, None)
                    continue
                prev = self._state.get(k)
                y = float(v) if prev is None else prev + alpha * (float(v) - prev)
                self._state[k] = y
                out[k] = y
        self._last_ts = now_ts
        return out
