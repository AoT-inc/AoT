# coding=utf-8
"""시퀀스 스케줄은 **정본 모듈 하나로만** 쓴다(`aot/utils/sequence_schedule.py`).

## 왜 이 테스트가 있나

스케줄을 쓰는 곳이 일곱 곳이었고 레거시 컬럼을 서로 다른 규칙으로 맞췄다 — 그래서
per_day 의 레거시 `period` 가 "오늘" 인지 "첫 활성 요일" 인지 "옛 값" 인지는 마지막에
누가 저장했느냐에 달려 있었다(2026-09-21 조사). 폼에서 고친 종료시간이 무시되고,
위젯 저장 한 번에 요일별 주기가 뭉개지고, 모달이 옛 값을 보여주던 결함이 전부 그
갈래에서 나왔다.

정본 모듈을 만든 것만으로는 부족하다 — 다음 사람이 급한 김에 `trigger.timer_schedule
= …` 한 줄을 쓰면 여덟 번째 경로가 조용히 생긴다. 그래서 두 가지를 AST 로 막는다.

  1. `timer_schedule` 에 쓰는 곳은 정본 모듈과 복제(원본을 그대로 옮기는 곳)뿐이다.
  2. 시퀀스를 편집하는 함수들은 레거시 창 컬럼(`timer_start_time`·
     `timer_end_time`·`timer_weekday`·`period`)에 **직접** 쓰지 않는다 — 거울은
     `save()` 가 맞춘다.

(AST 로 보므로 이 이름을 설명하는 주석·독스트링은 막지 않는다 — 문자열로 검사하면
왜 막는지 설명하는 것까지 금지된다.)
"""
import ast
import pathlib
from types import SimpleNamespace

import pytest

from aot.utils import sequence_schedule
from aot.utils.weekly_schedule import from_legacy, to_legacy

ROOT = pathlib.Path(__file__).resolve().parent.parent          # aot/
REPO = ROOT.parent

ALLOWED_SCHEDULE_WRITERS = {
    'aot/utils/sequence_schedule.py',
    # 복제는 원본의 스케줄을 스텝 id 만 바꿔 그대로 옮긴다 — 편집이 아니다.
    'aot/services/duplication.py',
}

LEGACY_WINDOW_ATTRS = {'timer_start_time', 'timer_end_time', 'timer_weekday', 'period'}


def _py_files():
    for path in ROOT.rglob('*.py'):
        rel = path.relative_to(REPO).as_posix()
        if '/tests/' in rel or rel.startswith('aot/tests'):
            continue
        yield rel, path


def _assigned_attrs(node):
    """노드 안에서 대입되는 속성 이름들(+ setattr(x, '이름', …) 의 이름)."""
    out = []
    for n in ast.walk(node):
        targets = []
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            targets = [n.target]
        for t in targets:
            for sub in ast.walk(t):
                if isinstance(sub, ast.Attribute):
                    out.append((sub.attr, getattr(sub, 'lineno', 0),
                                getattr(sub.value, 'id', None)))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == 'setattr' and len(n.args) >= 2
                and isinstance(n.args[1], ast.Constant)):
            out.append((n.args[1].value, n.lineno, None))
        # 위젯의 `smart_sync_field(옵션키, 속성이름, …)` 는 속성 이름을 **인자로**
        # 받아 안에서 setattr 한다 — 속성 이름이 상수로 드러나지 않아 위 두 검사를
        # 빠져나간다. 예전 위젯이 정확히 그렇게 레거시 period 를 썼다(옛 코드에
        # 대고 돌려 보고 알았다).
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == 'smart_sync_field' and len(n.args) >= 2
                and isinstance(n.args[1], ast.Constant)):
            out.append((n.args[1].value, n.lineno, None))
    return out


# ---------------------------------------------------------------------------
# 1. timer_schedule 에 쓰는 곳
# ---------------------------------------------------------------------------

def test_only_the_canonical_module_writes_timer_schedule():
    offenders = []
    for rel, path in _py_files():
        if rel in ALLOWED_SCHEDULE_WRITERS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        for attr, line, _ in _assigned_attrs(tree):
            if attr == 'timer_schedule':
                offenders.append(f'{rel}:{line}')
    assert not offenders, (
        '정본 모듈 밖에서 timer_schedule 을 쓴다 — sequence_schedule.save() 를 쓸 것: '
        + ', '.join(offenders))


# ---------------------------------------------------------------------------
# 2. 시퀀스 편집 함수는 레거시 창 컬럼에 직접 쓰지 않는다
# ---------------------------------------------------------------------------

def _functions(rel, name_filter):
    tree = ast.parse((REPO / rel).read_text(encoding='utf-8'))
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and name_filter(n.name)]


SEQUENCE_EDITORS = [
    ('aot/aot_flask/routes_function.py', lambda n: 'sequence' in n),
    ('aot/tools/data_tools/function.py', lambda n: 'sequence' in n),
    ('aot/widgets/widget_trigger_sequence.py', lambda n: True),
]


@pytest.mark.parametrize('rel,name_filter', SEQUENCE_EDITORS,
                         ids=[r for r, _ in SEQUENCE_EDITORS])
def test_sequence_editors_do_not_write_the_legacy_mirror(rel, name_filter):
    funcs = _functions(rel, name_filter)
    assert funcs, f'{rel} 에서 검사할 함수를 못 찾았다 — 이름이 바뀌었으면 여기도 고칠 것'
    offenders = []
    for fn in funcs:
        for attr, line, owner in _assigned_attrs(fn):
            if attr in LEGACY_WINDOW_ATTRS and owner != 'self':
                offenders.append(f'{fn.name}:{line} .{attr}')
    assert not offenders, (
        f'{rel} 이 레거시 창 컬럼에 직접 쓴다 — 거울은 sequence_schedule.save() 가 '
        '한 규칙으로 맞춘다: ' + ', '.join(offenders))


def test_the_form_branch_does_not_write_the_legacy_mirror():
    """Functions 폼(`trigger_mod`)은 여러 트리거 종류를 처리한다 — 타이머 트리거는
    레거시 컬럼이 정본이므로 막으면 안 되고, **시퀀스 분기만** 본다."""
    tree = ast.parse((REPO / 'aot/aot_flask/utils/utils_trigger.py').read_text(encoding='utf-8'))
    branches = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and any(isinstance(c, ast.Constant) and c.value == 'trigger_sequence'
                        for c in node.test.comparators)):
            branches.append(ast.Module(body=node.body, type_ignores=[]))
    assert branches
    offenders = [f'{line} .{attr}' for b in branches
                 for attr, line, owner in _assigned_attrs(b)
                 if attr in LEGACY_WINDOW_ATTRS | {'timer_schedule'}]
    assert not offenders, '폼의 시퀀스 분기가 창 컬럼에 직접 쓴다: ' + ', '.join(offenders)


# ---------------------------------------------------------------------------
# 3. 정본 모듈의 규칙
# ---------------------------------------------------------------------------

def _trigger(schedule=None, start='05:30', end='17:00', period=3600.0):
    import json
    return SimpleNamespace(
        timer_schedule=json.dumps(schedule) if schedule else None,
        timer_start_time=start, timer_end_time=end, timer_weekday=None, period=period)


def _per_day(periods):
    return {'version': 1, 'mode': 'per_day',
            'shared': {'enabled': True, 'start': '05:30', 'end': '17:00', 'period': 3600},
            'days': {str(d): {'enabled': True, 'start': '05:30', 'end': '17:00', 'period': p}
                     for d, p in periods.items()}}


def test_load_falls_back_to_the_legacy_columns():
    t = _trigger(start='06:00', end='18:00', period=1800.0)
    sched = sequence_schedule.load(t)
    assert sched['shared']['start'] == '06:00' and sched['shared']['end'] == '18:00'


def test_save_writes_json_and_mirrors_with_one_rule():
    per = {d: 10800 for d in range(7)}
    per[0] = 1200
    t = _trigger()
    sched = _per_day(per)
    assert sequence_schedule.save(t, sched) == []
    start, end, weekday, period = to_legacy(sched)
    assert (t.timer_start_time, t.timer_end_time, t.period) == (start, end, period)
    assert sequence_schedule.load(t) == sched


def test_save_refuses_and_writes_nothing():
    t = _trigger()
    sched = sequence_schedule.load(t)
    sched['days']['0']['end'] = '05:00'          # 시작보다 앞
    assert sequence_schedule.save(t, sched)
    assert t.timer_schedule is None and t.timer_end_time == '17:00'


def test_set_window_refuses_to_flatten_per_day():
    sched = _per_day({d: 3600 for d in range(7)})
    sched['days']['4']['end'] = '20:30'
    assert sequence_schedule.set_window(sched, end='21:00') is False
    assert sched['days']['4']['end'] == '20:30'


def test_set_window_on_one_day_touches_only_that_day():
    sched = _per_day({d: 3600 for d in range(7)})
    assert sequence_schedule.set_window(sched, period=60, day=2) is True
    assert [sched['days'][str(d)]['period'] for d in range(7)] == [3600, 3600, 60, 3600, 3600, 3600, 3600]


def test_today_period_is_read_from_todays_entry(monkeypatch):
    """날마다 바뀌는 값은 저장하지 않고 읽을 때 계산한다."""
    monkeypatch.setattr(sequence_schedule, 'get_today_idx', lambda tz: 4)
    sched = _per_day({d: (1200 if d == 4 else 10800) for d in range(7)})
    assert sequence_schedule.today_period(sched, 'UTC') == 1200.0
