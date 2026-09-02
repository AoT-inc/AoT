# coding=utf-8
"""위젯 저장이 **요일별 주기를 뭉개지 않는가**.

## 왜 이 테스트가 있나

`trigger.period` 는 per_day 모드에서 **오늘의 주기** 하나다 —
`/function_sequence_update_schedule` 가 그렇게 동기화한다. 그런데 위젯 저장의
스케줄 동기화가 그 값을 7개 요일 전부에 덮어썼다. 그래서 위젯에서 **아무 칸이나**
고쳐 저장하면(표시 옵션이든 교차 시간이든) 요일마다 다르게 짜 둔 관수 주기가
조용히 하나로 뭉개졌다.

실측(2026-09-01 로컬, "3포장 밸브제어 v2"): 요일별 주기가 `10800×6 + 금 1200`
이었는데, 관계없는 옵션 하나를 바꿔 저장하자 **전부 60** 이 됐다. 되돌릴 방법도
없다 — 원래 값이 어디에도 남지 않는다.

per_day 는 요일마다 주기가 다른 것이 존재 이유다. 주기 칸을 실제로 고쳤을 때만,
그것도 그 값이 가리키는 오늘 요일에만 반영해야 한다.
"""
import ast
import pathlib

import pytest

SRC = (pathlib.Path(__file__).parent.parent
       / 'widgets' / 'widget_trigger_sequence.py').read_text()


def _per_day_branch():
    """per_day 분기의 소스만 떼어 온다."""
    marker = "elif sched.get('mode') == 'per_day':"
    assert marker in SRC, "per_day 분기가 사라졌다"
    start = SRC.index(marker)
    tail = SRC[start:]
    end = tail.index('except Exception as _e:')
    return tail[:end]


def test_per_day_does_not_overwrite_every_weekday():
    """핵심 회귀. 7일 순회로 주기를 덮어쓰면 요일별 구성이 사라진다."""
    branch = _per_day_branch()
    assert "for i in range(7)" not in branch, (
        "per_day 에서 주기를 7일 전부에 퍼뜨리고 있다 — 요일별로 짜 둔 관수 "
        "주기가 저장 한 번에 하나로 뭉개진다")


def test_per_day_only_touches_the_period_when_the_user_changed_it():
    branch = _per_day_branch()
    assert "'sequence_period' in pushed_fields" in branch, (
        "주기 칸을 고치지 않았는데도 스케줄을 만지고 있다")


def test_per_day_writes_todays_index_only():
    branch = _per_day_branch()
    assert 'get_today_idx' in branch, "어느 요일에 반영할지 정하지 않는다"
    assert 'get_device_tz' in branch, (
        "서버 시계로 요일을 정하면 기기 로컬 자정 전후에 엉뚱한 요일이 바뀐다")


def test_shared_mode_still_propagates_to_all_days():
    """공유 모드는 모든 요일이 같은 것이 정의다 — 여기까지 막으면 안 된다."""
    marker = "if sched.get('mode') == 'shared':"
    assert marker in SRC
    start = SRC.index(marker)
    branch = SRC[start:SRC.index("elif sched.get('mode') == 'per_day':")]
    assert "for i in range(7)" in branch


def test_pushed_fields_is_actually_populated():
    """집합을 만들어 두고 채우지 않으면 조건이 영영 거짓이 되어, 주기를 고쳐도
    반영되지 않는다 — 반대 방향의 조용한 실패다."""
    assert 'pushed_fields = set()' in SRC
    assert 'pushed_fields.add(field_key)' in SRC


def test_the_add_sits_on_the_push_path():
    """`pushed_fields.add` 가 pull 쪽에 붙어 있으면 아무 의미가 없다."""
    tree = ast.parse(SRC)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != 'smart_sync_field':
            continue
        for sub in ast.walk(node):
            # push 분기는 updates_to_push = True 와 같은 블록에 있다.
            if isinstance(sub, ast.Try):
                body = ast.dump(ast.Module(body=sub.body, type_ignores=[]))
                if 'updates_to_push' in body and 'pushed_fields' in body:
                    found = True
    assert found, "pushed_fields 기록이 push 분기 안에 있지 않다"
