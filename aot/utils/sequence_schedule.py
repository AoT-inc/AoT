# coding=utf-8
"""시퀀스 스케줄의 **정본** — 읽기와 쓰기가 전부 여기를 지난다.

## 왜 이 모듈이 있나

시퀀스의 창(시작·종료·주기·요일)은 세 곳에 있었다 — 정본 JSON
(`Trigger.timer_schedule`), 레거시 컬럼(`timer_start_time`·`timer_end_time`·
`period`·`timer_weekday`), 위젯 옵션 캐시. 그리고 쓰는 곳이 일곱 곳이었는데
레거시 컬럼을 **서로 다른 규칙으로** 맞췄다(2026-09-21 조사):

  - AI 도구 둘은 JSON 만 쓰고 레거시는 그대로 두었고,
  - 전체 스케줄 저장은 레거시 주기를 "오늘 요일" 로, `to_legacy()` 는 "첫 활성
    요일" 로 두었으며,
  - 요일 토글은 켜짐 플래그만, shared 설정은 폼 값을 그대로 넣었다.

그래서 per_day 에서 레거시 `period` 가 무엇을 뜻하는지는 **마지막에 누가
저장했느냐**에 달려 있었다. 폼에서 고친 종료시간이 무시되고(데몬은 JSON 을 본다),
위젯 저장 한 번에 요일별 주기가 하나로 뭉개지고, 모달이 옛 값을 보여주던 결함이
전부 이 갈래에서 나왔다.

## 규칙

  - **정본은 JSON 하나다.** 읽기는 `load()`, 쓰기는 `save()` 만 쓴다.
  - `save()` 가 검증하고, 통과해야만 JSON 을 쓰고, 레거시 컬럼을 **한 가지
    규칙**(`to_legacy`, per_day 는 첫 활성 요일)으로만 맞춘다. 레거시 컬럼은
    폼·옛 코드가 읽는 거울일 뿐이고 아무도 거기에 먼저 쓰지 않는다.
  - "오늘의 주기" 처럼 **날마다 바뀌는 값은 저장하지 않는다** — 읽을 때
    `today_period()` 로 JSON 에서 계산한다. 저장해 두면 다음 날 낡는다.

`test_sequence_schedule_single_writer.py` 가 이 모듈 밖에서 `timer_schedule` 이나
시퀀스의 레거시 창 컬럼에 직접 쓰는 자리를 AST 로 막는다.
"""
import json

from aot.utils.weekly_schedule import (
    apply_shared_window, from_legacy, get_today_idx, parse_schedule, to_legacy,
    validate)


def load(trigger):
    """이 시퀀스의 스케줄(dict). JSON 이 없거나 깨졌으면 레거시 컬럼에서 만든다.

    ⚠ JSON 이 **검증에 실패해도** 레거시로 폴백한다(`parse_schedule` 이 None).
    그래서 저장 시점에 막아야 한다 — 그러지 않으면 요일별 설정이 통째로 사라진
    채 동작한다(`save()` 가 막는다).
    """
    return parse_schedule(getattr(trigger, 'timer_schedule', None)) or from_legacy(
        getattr(trigger, 'timer_start_time', None),
        getattr(trigger, 'timer_end_time', None),
        getattr(trigger, 'timer_weekday', None),
        getattr(trigger, 'period', None) or 3600)


def normalize_end(end):
    """자정 종료는 '24:00' 으로 적는다 — '00:00' 은 "시작보다 앞" 으로 읽혀 검증에 걸린다."""
    if end is not None and str(end).strip() == '00:00':
        return '24:00'
    return end


def _normalize_ends(schedule):
    if not isinstance(schedule, dict):
        return
    shared = schedule.get('shared')
    if isinstance(shared, dict) and 'end' in shared:
        shared['end'] = normalize_end(shared['end'])
    for entry in (schedule.get('days') or {}).values():
        if isinstance(entry, dict) and 'end' in entry:
            entry['end'] = normalize_end(entry['end'])


def set_window(schedule, start=None, end=None, period=None, day=None):
    """창을 고친다(dict 만 바꾼다 — 저장은 `save()`). 반영했으면 True.

    `day` 를 주면 그 요일 항목만 고친다. 주지 않으면 shared 모드에서만 모든 요일에
    퍼뜨리고, **per_day 에서는 아무것도 하지 않고 False** 를 돌려준다 — 전역 값
    하나를 7일에 퍼뜨리면 요일별로 짜 둔 구성이 통째로 사라진다. 호출자는 False 를
    받으면 사용자에게 알려야 한다(조용히 버리면 안 된다).
    """
    end = normalize_end(end)
    if day is not None:
        entry = schedule.setdefault('days', {}).setdefault(str(int(day)), {})
        if start:
            entry['start'] = str(start)
        if end:
            entry['end'] = str(end)
        if period is not None:
            entry['period'] = int(float(period))
        return True
    return apply_shared_window(schedule, start=start, end=end, period=period)


def save(trigger, schedule):
    """스케줄을 저장한다. 검증에 실패하면 **아무것도 쓰지 않고** 오류 목록을 돌려준다.

    커밋과 데몬 통지는 호출자가 한다(트랜잭션 경계는 호출자의 것이다).
    """
    _normalize_ends(schedule)
    errors = validate(schedule)
    if errors:
        return errors
    trigger.timer_schedule = json.dumps(schedule)
    start, end, weekday_str, period = to_legacy(schedule)
    trigger.timer_start_time = start
    trigger.timer_end_time = end
    trigger.timer_weekday = weekday_str or None
    trigger.period = period
    return []


def entry_for_day(schedule, day_idx):
    return ((schedule or {}).get('days') or {}).get(str(day_idx)) or {}


def today_period(schedule, tz, fallback=3600.0):
    """오늘 요일 항목의 주기(초). 날마다 달라지므로 **저장하지 않고 읽을 때 계산한다.**"""
    try:
        period = entry_for_day(schedule, get_today_idx(str(tz))).get('period')
        if period:
            return float(period)
    except Exception:
        pass
    try:
        shared = (schedule or {}).get('shared') or {}
        if shared.get('period'):
            return float(shared['period'])
    except Exception:
        pass
    return float(fallback or 3600.0)
