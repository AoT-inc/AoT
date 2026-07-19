# coding=utf-8
"""
ext_context_fallback.py — 외부 센서 만료 시 fallback 컨텍스트 (P2-2).

외부 센서(기상 스테이션, 외부 온습도 등)가 만료됐을 때:
  1. 마지막 유효 값을 캐싱해 보수적 fallback 으로 사용한다.
  2. 개구부·차광막은 안전 게이트가 강제 폐쇄한다.
  3. 내부 전용 액추에이터(난방·냉방·CO₂·가습)는 L1-L3 를 계속 실행한다.

fallback 원칙 (보수적 기본값):
  - wind  : 0.0 m/s  (개구부는 게이트가 이미 폐쇄, 강풍 가정 불필요)
  - rain  : 0.0      (강우는 게이트가 이미 차단)
  - T_ext : last_known → 없으면 T_int (중립)
  - RH_ext: last_known → 없으면 RH_int (중립)
  - wind_dir: last_known → 없으면 0.0

참조: docs/dev/integrated_env_control_design.md §P2-2
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ExtContextCache:
    """마지막으로 수신된 유효 외부 컨텍스트를 보관한다."""
    values: Dict        = field(default_factory=dict)
    last_good_ts: float = 0.0          # 마지막 유효 수신 epoch

    def update(self, ext: dict, now: float = None):
        """ext 가 신선한 경우 캐시를 갱신한다."""
        if ext:
            self.values = dict(ext)
            self.last_good_ts = now or time.time()

    def age(self, now: float = None) -> float:
        """마지막 유효 수신으로부터 경과 초."""
        if self.last_good_ts <= 0:
            return float('inf')
        return (now or time.time()) - self.last_good_ts

    def is_empty(self) -> bool:
        return not self.values


def build_fallback_context(
    cache: ExtContextCache,
    internal: dict,
    now: float = None,
) -> dict:
    """
    외부 센서가 만료됐을 때 사용할 보수적 fallback 컨텍스트를 반환한다.

    우선순위:
      1. 캐시에 마지막으로 저장된 값
      2. 내부 센서값 (T_int, RH_int) → 중립 외부 환경 가정
      3. 절대 보수 기본값

    Args:
        cache:    ExtContextCache (마지막 유효 외부값)
        internal: 현재 사이클 내부 센서 dict (T, RH 키)
        now:      현재 epoch (None 이면 time.time())

    Returns:
        fallback 외부 컨텍스트 dict + '_stale': True 마커
    """
    last = cache.values

    T_int  = internal.get('T',  20.0)
    RH_int = internal.get('RH', 60.0)

    fallback = {
        # 기상 조건 — 보수적 (게이트가 이미 개구부 닫음)
        'wind':     0.0,
        'rain':     0.0,
        'wind_dir': last.get('wind_dir', 0.0),

        # 온도·습도 — 캐시 우선, 없으면 내부값(중립 가정)
        'T':        last.get('T',  T_int),
        'RH':       last.get('RH', RH_int),
        'T_ext':    last.get('T_ext', T_int),
        'RH_ext':   last.get('RH_ext', RH_int),

        # 기타 외부 환경 — 캐시 유지 또는 안전 기본
        'CO2_ext':  last.get('CO2_ext', 400.0),
        'solar':    last.get('solar',   0.0),
        'dewpoint': last.get('dewpoint', 0.0),

        # 만료 마커 (assess / situation 에서 참고 가능)
        '_stale':   True,
        '_stale_age': cache.age(now),
    }

    return fallback
