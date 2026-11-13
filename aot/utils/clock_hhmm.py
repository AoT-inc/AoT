# coding=utf-8
"""하루 시각 `HH:MM` 문자열의 **정본 파서** — 읽기와 저장 검사가 모두 여기를 지난다.

## 왜 이 모듈이 있나

env_coordinator 의 운전 시간창(`time_start`/`time_end`)과 야간 파킹 시각
(`night_vent_start`/`night_vent_end`)은 자유 텍스트 옵션이라 아무 값이나 저장됐고,
읽는 쪽은 `'HH:MM'` 문자열끼리 **사전식으로** 비교했다. `'6:00'` 처럼 자리를 안 맞춘
값이면 `'6:00' > '20:00'` 이 되어 창이 "자정 넘는 구간" 으로 뒤집혀 00:00~05:59 가
창 안으로 새었다(2026-11-11 재현). 저장 시 정규화도, 읽을 때 같은 파서도 없었다.

## 규칙

  - **분 단위 정수로만 비교한다.** 문자열 비교를 새로 쓰지 말 것.
  - `parse_hhmm()` 이 읽기·검사 양쪽의 유일한 파서다. `H:MM`·`HH:MM`·`HH:MM:SS`
    (초는 버림)를 받고 `24:00` 은 하루의 끝(1440분)으로 받는다.
  - 시각의 **의미**(어느 시간대의 시각인가)는 여기서 다루지 않는다 — 호출하는 쪽이
    장소 시간대로 만든 현재 시각을 `minutes_of_day()` 로 넘긴다.
"""
import re

_HHMM = re.compile(r'^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$')

DAY_END_MINUTES = 24 * 60


def parse_hhmm(value):
    """`'6:00'`/`'06:00'`/`'06:00:30'`/`'24:00'` → 하루 중 분(0~1440). 못 읽으면 None."""
    if value is None:
        return None
    match = _HHMM.match(str(value))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3) or 0)
    if minute > 59 or second > 59 or hour > 24:
        return None
    total = hour * 60 + minute
    return total if total <= DAY_END_MINUTES else None


def normalize_hhmm(value):
    """읽을 수 있으면 `HH:MM` 로 맞춘 문자열, 아니면 None."""
    minutes = parse_hhmm(value)
    if minutes is None:
        return None
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def minutes_of_day(moment):
    """`datetime` 의 시각을 하루 중 분(0~1439)으로. 초는 버린다(분 단위 비교)."""
    return moment.hour * 60 + moment.minute


def in_window(now_min, start_min, end_min):
    """하루 중 `now_min` 이 `[start, end]` 안인가. 양 끝 포함, `start > end` 면 자정을 넘는 창.

    기존 규칙을 그대로 옮겼다 — 시작과 끝이 같으면 그 한 분만 안이다.
    """
    if start_min <= end_min:
        return start_min <= now_min <= end_min
    return now_min >= start_min or now_min <= end_min
