# coding=utf-8
"""실외 값이 **얼마나 오래** 없었는가 — 두절 시계의 정본은 이 모듈 한 곳이다 (2026-10-12 김제, 근거 58).

## 왜 있는가

실외를 모르는 동안 개구부는 제자리에 서고(`coordinator` 2.6) 닫는 쪽만 허용된다(근거 58). 그런데 하드 습도 상한
(`_force_dehumid`)이 야간 파킹을 풀어 연 창은 그 두 규칙의 틈에 있었다 — 김제 10/10 22:30 에 RH 91~95 % 로 25~30 % 열린
창이 기상청 값이 끊긴 01:30 이후 3 시간 13~25 % 로 묶였다(근거 16). 비가 오기 시작해도 볼 수 없는 채로 열려 있다.

다만 **잠깐의 끊김**은 평소다: 기상대 관측은 간헐적으로 최대 31 분 벌어진다(`ext_context_fallback.carry_forward_outdoor`).
짧은 끊김에서 제습 중인 창을 닫으면 습도 한계를 지키려던 동작이 흔들린다. 그래서 끊김이 `OUTAGE_DEHUMID_GRACE_S` 를
넘긴 뒤에만 서야 하고, 그러려면 **끊긴 시각**을 사이클을 넘어 기억해야 한다.

## 규칙

- 두절 = 실외를 지어낸 사이클(`_ext_synthetic`) **또는** 강우·풍속을 잃음(`vent_open_ceiling`). 값이 한 번이라도
  돌아오면(= 두 조건이 모두 거짓) 시계는 즉시 0 으로 돌아간다 — 래치가 없다.
- 시각은 이 모듈이 아니라 호출자가 넘긴다(`now`). 리플레이가 시계를 고정하기 때문이다.
- **사이클이 오래 비었으면 시계를 다시 시작한다**(`MAX_GAP_S`). 제어가 멈춰 있던(시간창 밖·정지) 동안은 두절이었는지
  알 수 없다 — 모르는 시간을 두절에 보태지 않는다.
- 재시작을 넘는다(`cycle_memory`, 코디네이터 속성 `_outage_state`). 재시작 직후 실외 캐시는 비어 있어 곧바로 '지어낸
  값' 으로 읽히는데, 시계까지 0 이 되면 재시작할 때마다 30 분이 다시 시작된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# 이 시간 넘게 이어진 두절이어야 "오래 끊겼다" — 이보다 짧은 끊김은 기상대의 평소 간격이다.
OUTAGE_DEHUMID_GRACE_S = 1800.0

# 사이클 사이가 이보다 벌어졌으면(정지·시간창 밖) 그 사이를 두절로 세지 않는다. `cycle_memory.MEMORY_MAX_AGE_S` 와 같다.
MAX_GAP_S = 1800.0


@dataclass
class OutageState:
    """두절이 시작된 시각과 마지막으로 본 시각(epoch 초). 재시작을 넘는다(`cycle_memory`)."""
    since: Optional[float] = None
    seen: Optional[float] = None


def update(state: OutageState, outage: bool, now: float) -> Optional[float]:
    """이번 사이클의 두절 여부를 시계에 반영하고 **두절이 이어진 초**를 돌려준다(두절이 아니면 None).

    제자리에서 `state` 를 고친다. 시계가 거꾸로 갔거나(`now` < 시작) 사이클 간격이 `MAX_GAP_S` 를 넘었으면
    지금부터 다시 센다.
    """
    now = float(now)
    seen = state.seen
    state.seen = now
    if not outage:
        state.since = None
        return None
    since = state.since
    if (since is None or now < since
            or (seen is not None and (now - float(seen) > MAX_GAP_S or now < float(seen)))):
        state.since = since = now
    return max(0.0, now - float(since))
