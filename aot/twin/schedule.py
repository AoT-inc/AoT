# coding=utf-8
"""정기 실행 시각 계산 — 하루 한두 번 '벽시계 시각'에 돌리기 위한 순수 함수 (계획서 §9.8).

발행은 구획 현지 오늘 00 시 기준 36 시간 유효(계약 §7)라, 하루 한 번만 돌아도 비는 시간이 없다
(다음 날 아침 발행이 만료 전에 앞 발행을 대신한다). 두 번 돌리면 예보·관측을 하루에 한 번 더 새로 한다.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Sequence, Tuple

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_run_at(items: Sequence[str]) -> Tuple[Tuple[int, int], ...]:
    out = []
    for s in items:
        m = _HHMM.match(str(s).strip())
        if not m:
            raise ValueError(f"run_at '{s}' 는 HH:MM 이어야 한다")
        out.append((int(m.group(1)), int(m.group(2))))
    return tuple(sorted(set(out)))


def _zone(name: str):
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


def check_timezone(name: str) -> None:
    try:
        _zone(name)
    except Exception as e:                       # ZoneInfoNotFoundError·ValueError
        raise ValueError(f"시간대 '{name}' 를 모른다") from e


def next_run(now: float, run_at: Sequence[Tuple[int, int]], tz_name: str) -> float:
    """`now` 보다 **뒤**인 가장 이른 예약 시각(epoch 초). 없으면(run_at 이 비면) ValueError."""
    if not run_at:
        raise ValueError("run_at 이 비었다")
    z = _zone(tz_name)
    local = _dt.datetime.fromtimestamp(now, z)
    cands = []
    for add in (0, 1, 2):                        # 오늘·내일·모레 (일광절약 경계 여유)
        day = (local + _dt.timedelta(days=add)).date()
        for h, m in run_at:
            t = _dt.datetime(day.year, day.month, day.day, h, m, tzinfo=z).timestamp()
            if t > now:
                cands.append(t)
    return min(cands)
