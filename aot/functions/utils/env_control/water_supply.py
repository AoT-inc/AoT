# coding=utf-8
"""분무용 물 공급 판정 — 물이 있는가의 정본은 **이 모듈 한 곳**이다 (2026-10-09).

## 왜 있는가

분무기는 물이 없으면 헛돈다(펌프 공회전·노즐 건조·가습 기대 오류). 그런데 코디네이터는
탱크 수위도 수압도 몰라서, 극한 고온 보호가 읽는 이음매(`internal['_water_available']`,
`heat_protect`)는 늘 기본값 True 였다. 이 모듈이 그 이음매를 채운다.

## 입력은 측정 하나다

수위(%)·수압(kPa)·유량 스위치(0/1) 중 **하나**를 코디네이터 옵션으로 묶는다
(`water_supply_signal`). 판정은 문턱과 방향 둘뿐이다.

    above   문턱 **이상**이면 물이 있다   (수위·수압·유량 — 값이 클수록 풍족)
    below   문턱 **이하**이면 물이 있다   (바닥 경보 스위치 — 1 이 "비었다")

## 의미 — 보수적인 쪽으로 간다

    옵션을 켜지 않았거나 신호를 지정하지 않았다   → 있다 (종전 동작과 완전히 같다)
    묶였고 값이 유효하고 문턱을 넘었다           → 있다
    묶였고 값이 유효하고 문턱 아래다             → 없다 (WATER_LOW)
    묶였는데 값이 없거나 만료다                  → 없다 (WATER_STALE)

⚠ 값을 모르는 것도 "없다" 로 본다. 물이 있는지 **모르는** 채로 펌프를 돌리는 것이 물이 있는데
  잠깐 쉬는 것보다 비싸다(공회전으로 펌프가 상한다). 쉬는 쪽은 되돌리기 쉽다 — 신호가 돌아오는
  사이클에 곧바로 풀린다. 이미 돌고 있는 분무를 **강제로 끊는** 것은 이 모듈이 아니라
  `coordinator` 의 파킹과 전달 비율 0 이 한다(결과는 같고, 적분이 그 사실을 안다).

## 이력 (깜빡임 방지)

수압·수위는 펌프가 돌면 출렁인다. 문턱 하나로 가르면 분무가 켜질 때 수압이 떨어져 바로 "없다",
꺼지면 올라가 "있다" 로 매 사이클 뒤집힌다. 그래서 **없다 → 있다** 로 돌아오려면 문턱에서
`WATER_HYST_FRAC`(문턱의 5 %)만큼 더 와야 한다. 문턱이 0 이면 이력도 0 이다.
처음 판정(직전이 없음)은 이력 없이 문턱으로 가른다.
"""
# @manual ai/env-control#water-supply
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

# 판정 결과(CH92 에 그대로 기록된다 — 숫자를 바꾸면 옛 기록이 뜻을 잃는다)
WATER_UNBOUND = 0    # 옵션을 켜지 않았다 / 신호가 없다 (기록하지 않는다)
WATER_OK = 1         # 물이 있다
WATER_LOW = 2        # 신호가 유효한데 문턱 미달
WATER_STALE = 3      # 신호가 없거나 만료

WATER_HYST_FRAC = 0.05   # 문턱의 이 비율만큼 더 와야 "없다 → 있다"

DIR_ABOVE = 'above'
DIR_BELOW = 'below'
_DIRECTIONS = (DIR_ABOVE, DIR_BELOW)

STATE_LABEL = {
    WATER_UNBOUND: 'unbound',
    WATER_OK: 'ok',
    WATER_LOW: 'low',
    WATER_STALE: 'stale',
}


@dataclass
class WaterSupplyConfig:
    """옵션 → 설정. `enabled` 이고 신호가 묶여야 `bound` 다."""
    bound: bool = False
    threshold: float = 0.5
    direction: str = DIR_ABOVE


def normalise_direction(value) -> str:
    """알 수 없는 값은 기본(above) — 저장 경로가 검증을 지나지 않아도 판정이 서야 한다."""
    v = str(value or '').strip().lower()
    return v if v in _DIRECTIONS else DIR_ABOVE


def judge(cfg: WaterSupplyConfig, value: Optional[float],
          prev_state: int = WATER_UNBOUND) -> Tuple[bool, int]:
    """(물이 있는가, 상태 코드). `value` 는 **유효(신선)한 값만** — 없으면 None.

    `prev_state` 는 직전 사이클의 상태 코드다(이력용). 처음이면 `WATER_UNBOUND`.
    """
    if not cfg.bound:
        return True, WATER_UNBOUND
    if value is None:
        return False, WATER_STALE
    try:
        v = float(value)
        thr = float(cfg.threshold)
    except (TypeError, ValueError):
        return False, WATER_STALE
    if v != v:                                  # NaN
        return False, WATER_STALE
    hyst = abs(thr) * WATER_HYST_FRAC
    was_out = prev_state in (WATER_LOW, WATER_STALE)
    if normalise_direction(cfg.direction) == DIR_ABOVE:
        ok = v >= (thr + hyst if was_out else thr)
    else:
        ok = v <= (thr - hyst if was_out else thr)
    return (True, WATER_OK) if ok else (False, WATER_LOW)


def describe(state: int, value: Optional[float], cfg: WaterSupplyConfig) -> str:
    """사람이 읽는 한 줄(전환 로그용)."""
    if state == WATER_OK:
        return '물 공급 정상 (신호 %s)' % _fmt(value)
    if state == WATER_LOW:
        return '물 공급 부족 — 신호 %s, 문턱 %s (%s)' % (
            _fmt(value), _fmt(cfg.threshold),
            '이상이어야 함' if normalise_direction(cfg.direction) == DIR_ABOVE
            else '이하여야 함')
    if state == WATER_STALE:
        return '물 공급 신호가 없거나 오래됐다'
    return '물 공급 감지 꺼짐'


def _fmt(v) -> str:
    try:
        return '%.2f' % float(v)
    except (TypeError, ValueError):
        return '-'
