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
        # **이 실외값이 지어낸 것인가.** 캐시가 있으면 마지막 '실측'이라 근거가
        # 되지만, 캐시가 비면 위에서 실외를 **내부값으로 가정**해 채운 것이라
        # 근거가 아니다(T_ext=T_int). 그 가정은 "실외 = 실내" 를 뜻하므로 환기
        # 무익 판정이 서고 개구부가 닫힌다 — 한여름에 기상대가 죽으면 창이
        # 닫힌다는 뜻이다. 판단하는 쪽이 이 둘을 구분할 수 있어야 한다.
        '_ext_synthetic': cache.is_empty(),
    }

    return fallback


# 실외값 승계 대상 키. 'T'/'RH' 는 situation.py 가, 'T_ext'/'RH_ext' 는 안전
# 게이트(_build_gate_env)가 읽는다 — 한쪽만 이으면 두 판단이 서로 다른 실외를
# 보게 된다.
CARRY_FORWARD_KEYS = ('T', 'RH', 'T_ext', 'RH_ext')


def carry_forward_outdoor(external: dict, cached: dict) -> list:
    """이번 사이클에 빈 실외값을 **마지막 유효 실측**으로 잇는다(제자리 수정).

    없는 값을 지어내는 것과 마지막 실측을 잠깐 더 쓰는 것은 전혀 다르다.
    `situation.py` 는 external 에 'T'/'RH' 가 없으면 20°C/60% 를 기본값으로 채우는데,
    그 가짜 실외는 VPD 0.93 이라 웬만한 야간 실내(0.3 안팎)보다 **높다**. 그러면
    "창을 열면 건조해진다" 로 읽혀 환기 무익 게이트가 풀리고 창이 열린다. 실제
    실외(예: 23°C/96% → VPD 0.11)면 정반대 판단이 나온다.

    2026-08-22 aot-005 새벽 창호 진동의 원인이 이것이다. 기상대 관측이 간헐적으로
    최대 31분 벌어지는데(중앙값 60초) `sensor_max_age`(1200초)를 넘긴 사이클마다
    가짜 실외가 들어가 40분 주기로 창이 열렸다 닫혔다 했다. 실측 리플레이에서
    가짜 실외가 뜬 야간 사이클 10회와 창이 열린 10회가 1:1 로 대응했고, 이 승계를
    넣은 뒤 같은 입력에서 10회 → 0회가 됐다.

    밤사이 실외는 천천히 변하므로 20~30분 된 실측이 지어낸 상수보다 비교할 수 없이
    낫다. **캐시에도 없으면 손대지 않는다** — 그때는 아무 근거가 없다는 뜻이고,
    호출부의 fallback 컨텍스트가 맡을 몫이다.

    Args:
        external: 이번 사이클 외부 컨텍스트 (제자리에서 수정된다)
        cached:   마지막 유효 외부값 (`ExtContextCache.values`)

    Returns:
        실제로 이어 붙인 키 목록 (진단·로깅용, 없으면 빈 리스트)
    """
    carried = []
    # **빈 dict 를 falsy 로 걸러내면 안 된다.** 실외 수집기가 없는 설치에서
    # 관측이 늦은 사이클의 external 은 정확히 `{}` 이고, 그게 바로 이어 붙여야
    # 하는 경우다. 걸러내는 것은 None(호출부가 아예 안 만든 경우)뿐이다.
    if external is None or not cached:
        return carried
    for key in CARRY_FORWARD_KEYS:
        if external.get(key) is None and cached.get(key) is not None:
            external[key] = cached[key]
            carried.append(key)
    return carried
