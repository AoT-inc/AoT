# coding=utf-8
"""장치 상태의 출처(basis)와 가동 이력 → 상태 계열 (설계서 §5.1, 결정 4).

| basis | 뜻 | 동기화(UKF) |
|---|---|---|
| `actual` | 장치의 실제 상태 계열(개도·가동 피드백) | 쓴다 |
| `duty_log` | 가동 이력(`duration_time`: 켠 시각에 찍힌 켜진 초)에서 만든 켜짐/꺼짐 계단 | 쓴다 |
| `command` | 보낸 명령만 있음(출력 채널의 `percent` 기록) — **'추정'** | **뺀다**, 예측 입력에만 |
| `none` | 읽을 계열이 없음 | — |

우선순위는 `actual > duty_log > command`. 단 개도형 장치(창·차광·커튼)의 `duty_log` 는 **움직인 시간**이지 위치가 아니므로
쓰지 않는다 — 그런 종류는 `actual > command`. 켜짐/꺼짐 장치(난방·냉방·분무·CO₂·팬)는 `actual > duty_log > command`.

이 모듈은 순수 변환이다(DB·Influx 를 모른다). 읽기는 서버 쪽 `aot.utils.twin_device_state` 가 한다.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from . import catalog as C

ACTUAL, DUTY_LOG, COMMAND, NONE = "actual", "duty_log", "command", "none"
BASES = (ACTUAL, DUTY_LOG, COMMAND)
#: 동기화(UKF)에 넣는 출처. `command` 는 명령≠실제일 수 있어 예측 입력에만 쓴다(결정 4).
SYNC_BASES = (ACTUAL, DUTY_LOG)

#: 읽기 어댑터가 `SeriesRef.unit` 으로 쓰는 표식 — 가동 이력은 측정값 그대로가 아니라 계단으로 바꿔 읽는다.
DUTY_UNIT = "duty_log"

#: 개도(위치)로 움직이는 종류의 목록표 행 이름 — 가동 이력이 위치를 말해 주지 않는다.
_POSITION_ROWS = frozenset({"window", "shade", "curtain"})


def is_position_kind(kind: Optional[str]) -> bool:
    return C.row_for(kind).name in _POSITION_ROWS


def choose_basis(kind: Optional[str], has_actual: bool, has_duty: bool, has_command: bool) -> str:
    """읽을 수 있는 출처 가운데 가장 좋은 것. 종류는 `duty_log` 를 쓸 수 있는지만 정한다."""
    if has_actual:
        return ACTUAL
    if has_duty and not is_position_kind(kind):
        return DUTY_LOG
    if has_command:
        return COMMAND
    return NONE


def estimated(basis: str) -> bool:
    """화면이 '추정' 으로 표시해야 하는가."""
    return basis == COMMAND


def duty_step_series(events: Iterable[Tuple[float, float]], t_start: float, t_end: float,
                     on_pct: float = 100.0) -> Tuple[List[float], List[float]]:
    """가동 이력 → `[t_start, t_end]` 의 켜짐/꺼짐 계단 `(times, values)`.

    `events` = (켠 시각 epoch, 켜진 초). 음수 초는 크기로 읽는다(출력 모듈이 부호로 방향을 남기는 경우). 겹치면 합친다.
    구간 밖에서 시작해 걸쳐 오는 사건도 반영한다. 첫 점은 `t_start` 의 상태(켜졌으면 `on_pct`, 아니면 0), 이후 점은 상태가 바뀔
    때마다이고, 마지막 점은 `t_end` 의 상태다. 사건이 하나도 없으면 전 구간 0 이다(꺼짐으로 읽는다 — 호출자가 '이력 없음'과
    구분해야 하면 사건 수를 따로 본다).
    """
    spans = sorted((float(t), float(t) + abs(float(d))) for t, d in events if d is not None and abs(float(d)) > 0)
    merged: List[List[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    times: List[float] = [float(t_start)]
    vals: List[float] = [0.0]
    for a, b in merged:
        if b <= t_start or a >= t_end:
            continue
        if a <= t_start:
            vals[0] = float(on_pct)
        else:
            times.append(a)
            vals.append(float(on_pct))
        if b < t_end:
            times.append(b)
            vals.append(0.0)
    if times[-1] < t_end:
        times.append(float(t_end))
        vals.append(vals[-1])
    return times, vals
