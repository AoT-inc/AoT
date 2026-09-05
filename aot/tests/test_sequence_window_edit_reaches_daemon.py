# coding=utf-8
"""시퀀스 창(시작·종료·주기) 편집이 **실제 동작까지 닿는가**.

## 왜 이 테스트가 있나

창 시간은 두 곳에 있다 — 레거시 컬럼(`Trigger.timer_start_time`/`timer_end_time`/
`period`)과 정본 JSON(`Trigger.timer_schedule`). 데몬은

    parse_schedule(timer_schedule) or from_legacy(레거시 컬럼…)

이므로 **JSON 이 한 번이라도 만들어진 시퀀스에서는 레거시 컬럼만 고쳐 봐야
아무 효과가 없다.** 그런데 화면은 레거시 컬럼을 되읽어 새 값을 보여주므로,
사용자는 바뀐 줄 안다. 실측(2026-09-05 로컬): 레거시 `timer_end_time` 을
11:11 로 바꿔도 실효 `window_end` 는 JSON 의 23:59 그대로였다.

Functions 편집 폼(`utils_trigger.trigger_mod`)이 정확히 그 상태였다 — 저장도
되고 "Daemon response: Sequence settings refreshed" 성공 메시지까지 나오는데
관수 시간은 하나도 안 바뀐다. 사용자 신고 "종료 시간을 변경해도 작동이
중단되지 않음" 의 경로 중 하나다.

`apply_shared_window()` 가 그 반영을 맡고, 여기서는 (1) 함수 자체의 규칙과
(2) 폼 저장 경로가 실제로 그것을 부르는지를 고정한다.
"""
import ast
import pathlib

import pytest

from aot.utils.weekly_schedule import (
    active_entry_now, apply_shared_window, from_legacy, parse_schedule)

SRC = (pathlib.Path(__file__).parent.parent
       / 'aot_flask' / 'utils' / 'utils_trigger.py').read_text()


def _shared(start='05:30', end='17:00', period=3600):
    return from_legacy(start, end, '0,1,2,3,4,5,6', period)


# ---- apply_shared_window: shared 모드 ----

def test_shared_window_reaches_the_day_entries():
    """`active_entry_now()` 는 **요일 항목**을 읽는다 — shared 만 고치면 무효다."""
    sched = _shared(end='17:00')
    assert apply_shared_window(sched, end='21:00') is True

    assert sched['shared']['end'] == '21:00'
    for i in range(7):
        assert sched['days'][str(i)]['end'] == '21:00', f'{i}요일이 안 따라왔다'


def test_period_is_written_as_int_seconds():
    sched = _shared()
    apply_shared_window(sched, period=10800.0)
    assert sched['shared']['period'] == 10800
    assert sched['days']['0']['period'] == 10800


def test_none_fields_are_left_alone():
    """일부만 고치는 호출에서 나머지가 지워지면 안 된다."""
    sched = _shared(start='05:30', end='17:00', period=3600)
    apply_shared_window(sched, end='21:00')
    assert sched['days']['3']['start'] == '05:30'
    assert sched['days']['3']['period'] == 3600


def test_enabled_flags_survive():
    """창만 고치는 것이지 요일 on/off 를 건드리는 것이 아니다."""
    sched = _shared()
    sched['days']['2']['enabled'] = False
    apply_shared_window(sched, end='21:00')
    assert sched['days']['2']['enabled'] is False


# ---- apply_shared_window: per_day 는 손대지 않는다 ----

def test_per_day_is_refused_not_flattened():
    """요일마다 창이 다른 것이 per_day 의 존재 이유다 — 전역 값 하나를 7일에
    퍼뜨리면 짜 둔 구성이 통째로 사라진다(주기에서 실제로 겪은 사고)."""
    sched = _shared()
    sched['mode'] = 'per_day'
    sched['days']['4']['end'] = '20:30'      # 금요일만 다르게 짜 뒀다

    assert apply_shared_window(sched, end='21:00') is False
    assert sched['days']['4']['end'] == '20:30', 'per_day 구성이 뭉개졌다'
    assert sched['days']['0']['end'] == '17:00'


# ---- 반영 결과가 실제 판정(active_entry_now)까지 닿는가 ----

def test_the_edit_actually_moves_the_window_decision():
    """단위 검증의 핵심 — 값이 dict 에 들어갔다가 아니라 **판정이 바뀌는가**.

    ⚠ 벽시계로 `지금±1시간` 을 쓰면 **자정 전후 두 시간대에만 실패한다.**
    창이 자정을 넘으면 `active_entry_now` 가 열려 있지 않다고 답하기 때문이다
    (설계상 미지원). 실제로 이 테스트가 00:0x 에 깨졌다. 그래서 시각을
    고정한다 — `active_entry_now` 는 tzinfo 객체를 그대로 받으므로, 지금
    UTC 가 몇 시든 **현지시각이 정오가 되는 고정 오프셋**을 만들어 넘기면
    언제 돌려도 같은 판정을 본다.
    """
    from datetime import datetime, timezone

    import pytz

    utc = datetime.now(timezone.utc)
    # 현지시각을 12:00 으로 만드는 오프셋(분). pytz.FixedOffset 범위 안으로 접는다.
    offset = (12 * 60) - (utc.hour * 60 + utc.minute)
    while offset > 720:
        offset -= 1440
    while offset <= -720:
        offset += 1440
    tz = pytz.FixedOffset(offset)
    local_hour = datetime.now(tz).hour
    assert local_hour == 12, f'시각 고정 실패: {local_hour}'

    sched = _shared(start='11:00', end='13:00')
    assert active_entry_now(sched, tz) is not None, '테스트 전제: 창이 열려 있어야 한다'

    apply_shared_window(sched, end='11:30')      # 정오 기준 이미 지난 시각
    assert active_entry_now(sched, tz) is None, (
        '종료시간을 과거로 바꿨는데 창이 여전히 열려 있다고 판정된다')


# ---- 폼 저장 경로가 실제로 부르는가 (배선) ----

def _sequence_branch():
    """`trigger_mod` 의 trigger_sequence 분기 소스만 떼어 온다."""
    marker = "elif trigger.trigger_type == 'trigger_sequence':"
    assert marker in SRC, 'trigger_sequence 분기가 사라졌다'
    start = SRC.index(marker)
    tail = SRC[start:]
    end = tail.index('if not messages["error"]:')
    return tail[:end]


def test_form_save_writes_the_authoritative_json():
    """레거시 컬럼만 쓰면 저장은 성공하는데 동작은 안 바뀐다 — 조용한 실패다."""
    branch = _sequence_branch()
    assert 'apply_shared_window' in branch, (
        '폼 저장이 정본 JSON(timer_schedule)을 반영하지 않는다 — '
        '데몬은 레거시 컬럼을 읽지 않으므로 편집이 통째로 무시된다')
    assert 'trigger.timer_schedule' in branch, 'JSON 을 실제로 쓰지 않는다'


def test_per_day_form_save_tells_the_user_instead_of_discarding():
    """per_day 에서는 반영할 수 없다 — 그렇다고 조용히 버리면 안 된다."""
    branch = _sequence_branch()
    assert 'messages["warning"]' in branch, (
        'per_day 에서 시간 편집을 조용히 버린다 — 안 먹는다는 사실을 '
        '사용자가 알 방법이 없다')


def test_a_midnight_crossing_window_is_refused_at_save_time():
    """저장 시점에 막지 않으면 데몬이 읽을 때 조용히 잘린다.

    `parse_schedule` 은 자정을 넘는 창을 거부하고 `from_legacy` 로 폴백하는데,
    그 폴백은 창을 24:00 으로 자르고 **요일별 설정(요일별 창·스텝 on/off·
    요일별 길이)을 통째로 버린다**(실측 2026-09-05: 23:29~02:39 로 저장하자
    데몬의 오늘 항목이 4개 키만 남아 스텝 on/off 가 통째로 무시됐다).
    무시되는 것보다 나쁘므로 저장 자체를 막아야 한다.
    """
    from aot.utils.weekly_schedule import validate

    sched = _shared(start='23:00', end='02:00')
    apply_shared_window(sched, start='23:00', end='02:00')
    assert validate(sched), '자정을 넘는 창인데 검증이 통과한다'

    branch = _sequence_branch()
    assert 'validate_schedule' in branch, (
        '폼 저장이 스케줄을 검증하지 않는다 — 데몬이 읽을 때 폴백해 '
        '요일별 설정이 사라진다')


def test_midnight_end_is_written_as_24_00_not_00_00():
    """자정 종료('00:00')는 '시작보다 앞'으로 읽혀 위 검증에 걸린다 —
    정상 설정이 저장되지 않는 것이라 반드시 24:00 으로 눕혀야 한다."""
    branch = _sequence_branch()
    assert "'24:00'" in branch, "자정 종료를 24:00 으로 정규화하지 않는다"


def test_the_json_write_is_guarded_by_the_helpers_verdict():
    """`apply_shared_window` 가 False(=per_day)를 줬는데도 JSON 을 덮어쓰면
    per_day 구성이 사라진다. 반드시 반환값 분기 안에서 써야 한다."""
    tree = ast.parse(SRC)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        call = node.test
        if isinstance(call, ast.Call) and getattr(call.func, 'id', '') == 'apply_shared_window':
            writes = [n for n in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                      if isinstance(n, ast.Attribute) and n.attr == 'timer_schedule']
            assert writes, 'if 본문에서 timer_schedule 을 쓰지 않는다'
            found = True
    assert found, 'apply_shared_window 의 반환값으로 분기하지 않는다'
