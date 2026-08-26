#!/usr/bin/env python3
# coding=utf-8
"""제어 경로가 그룹 스코프를 지나는지 소스에서 확인한다 (A1a).

정본 설계: `docs/design/access-scope-groups.md` §5-3

접근 제어가 빠진 것은 **에러를 내지 않는다.** 게이트를 지우거나 새 제어 경로를
스코프 없이 만들어도 화면은 멀쩡히 돌고, 테스트도 그 경로를 부르지 않으면
통과한다. 그 사실은 남의 장치가 움직인 뒤에야 드러난다.

## 무엇을 "제어" 로 보는가 — 역할 게이트가 아니라 **실제 작동**

`user_has_permission('edit_controllers')` 를 기준으로 삼지 않는다. 그 게이트는
레포에 211곳이고 대부분 엔티티 CRUD 라(A1b), 그것을 기준으로 하면 명부가
잡음으로 가득 차 아무도 안 보게 된다.

대신 **데몬에게 물리 작동을 시키는 호출**을 찾는다(`DAEMON_CONTROL_CALLS`).
그것이 A1a 가 막으려는 것의 정의다 — 남의 장치가 실제로 움직이는 자리.

두 가지를 본다:

| 검사 | 무엇 | 왜 |
|------|------|-----|
| `missing-gate` | 제어 호출이 있는데 스코프를 안 부르는 함수 | **새 우회로** |
| `inventory-drift` | 명부에 있는데 스코프 호출이 사라진 함수 | **게이트 제거** |

명부(`GATED_CONTROL_VIEWS`)를 따로 두는 이유는 `missing-gate` 만으로는 "원래
게이트가 있었는데 누가 뺐다" 를 구분할 수 없기 때문이다 — 둘 다 결과는
같지만, 후자는 되돌리면 되고 전자는 판단이 필요하다.

사용:
    python3 aot/scripts/check_scope_gates.py
    python3 aot/scripts/check_scope_gates.py --json

종료 코드: 0 = 정상 · 1 = 문제 발견 · 2 = 검사 실패
"""
import argparse
import ast
import json
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

#: 데몬에게 물리 작동을 시키는 메서드. 여기 없는 것을 추가할 때는 "이 호출이
#: 장치를 실제로 움직이는가" 하나만 물을 것 — 조회(`output_state`,
#: `output_states_all`)는 제어가 아니다.
DAEMON_CONTROL_CALLS = {
    'output_on', 'output_off', 'output_on_off',
    'controller_activate', 'controller_deactivate',
    'pid_set', 'pid_mod', 'pid_hold', 'pid_pause', 'pid_resume',
    'widget_execute',
    'trigger_action', 'trigger_all_actions',
}

#: 스코프를 물었다고 인정하는 호출.
SCOPE_CALLS = {'can_operate', 'can_operate_device', 'can_operate_widget'}

#: A1a 에서 실제로 게이트를 세운 자리. 여기서 스코프 호출이 사라지면
#: `inventory-drift` 다. **줄이려면 그 경로가 없어졌을 때뿐이다.**
GATED_CONTROL_VIEWS = {
    ('aot/aot_flask/routes_general.py', 'output_mod'),
    ('aot/aot_flask/routes_general.py', 'widget_execute'),
    ('aot/aot_flask/routes_geo.py', 'api_geo_output_state'),
    ('aot/aot_flask/routes_geo.py', 'api_facility_apply'),
    ('aot/aot_flask/routes_geo_iec.py', 'api_facility_control'),
    ('aot/aot_flask/routes_geo_iec.py', 'api_facility_function_state'),
    ('aot/aot_flask/api/output.py', 'post'),
    ('aot/aot_flask/api/controller.py', 'post'),
    # 초크포인트 — utils_input·utils_controller·utils_trigger·utils_conditional·
    # utils_device_connection 등 10여 곳이 이 함수를 지난다.
    ('aot/aot_flask/utils/utils_general.py', 'controller_activate_deactivate'),
    ('aot/widgets/AoT_controller.py', 'aot_controller_activate_deactivate'),
    ('aot/widgets/AoT_PID.py', 'pid_mod_unique_id'),
    ('aot/widgets/AoT_PID.py', 'pid_set_params'),
    ('aot/widgets/AoT_timer.py', 'aot_timer_cycle_start'),
    ('aot/widgets/AoT_timer.py', 'aot_timer_cycle_stop'),
    ('aot/widgets/widget_trigger_sequence.py', 'sequence_func_activate_toggle'),
}

#: 제어 호출이 있지만 스코프를 묻지 않아도 되는 자리. **근거를 함께 적을 것** —
#: 근거 없는 면제는 다음 사람이 "원래 이런가 보다" 로 읽는다.
EXEMPT = {
    ('aot/aot_flask/utils/utils_output.py', '*'):
        '엔티티 CRUD 의 부수 효과(삭제 시 끄기 등) — A1b 에서 대상 확정 뒤로 '
        '게이트를 옮길 때 함께 본다.',
    ('aot/aot_flask/utils/utils_function.py', '*'):
        '위와 같음 (A1b).',
    ('aot/aot_flask/utils/utils_pid.py', '*'):
        '위와 같음 (A1b).',
    ('aot/aot_flask/utils/utils_controller.py', '*'):
        '위와 같음 (A1b).',
    ('aot/aot_flask/routes_admin.py', '*'):
        '관리자 전용 진단 화면 — 역할 자체가 면제 대상이다.',

    # ---- 판단이 필요했던 둘 ----

    ('aot/aot_flask/routes_geo_iec.py', 'api_facility_estop'):
        '**비상정지는 권한으로 막지 않는다.** 이 경로가 하는 일은 액추에이터를 '
        '안전 상태로 되돌리는 것뿐이고(끄기), 위험을 만드는 방향으로는 아무것도 '
        '하지 못한다. 반대로 스코프가 막으면 "지금 멈춰야 하는데 내 그룹이 '
        '아니라서 못 멈춘다" 가 되는데, 그 상황에서 잃는 것이 접근 제어로 '
        '얻는 것보다 크다. 이미 confirm="STOP" 과 edit_settings 를 요구한다. '
        '**이 판단을 뒤집으려면 "누가 남의 시설을 함부로 멈춰서 손해가 났다" 는 '
        '실제 사례가 있어야 한다** — 지금은 가정이다.',

    ('aot/aot_flask/api/geo.py', 'post'):
        '장치 위치 저장(`/device/location`). `pid_mod` 는 좌표를 바꾼 뒤 데몬의 '
        '설정을 다시 읽게 하는 **갱신**이지 작동 명령이 아니다. 위치 저장 자체는 '
        '엔티티 편집이라 A1b 에서 다룬다 — 그때 이 면제도 함께 걷을 것.',
}

#: 훑는 곳. 데몬·AI 는 제외한다 — 데몬은 설계상 스코프를 모르고(§6-1),
#: AI 쓰기 도구는 A2 의 몫이다.
SCAN_DIRS = ('aot/aot_flask', 'aot/widgets')

# --------------------------------------------------------------- A1b: 엔티티 CRUD

#: 스코프 대상 모델 이름. `scope._SCOPED_BY_OWN_TAB` + Widget/Dashboard/Tab 과
#: 같은 집합이어야 한다 — 한쪽만 늘리면 새 종류의 변경 경로를 못 본다.
SCOPED_MODELS = {'Input', 'Output', 'Function', 'Conditional', 'Trigger',
                 'PID', 'CustomController', 'Widget', 'Dashboard', 'Tab'}

#: 부여할 수 있는 자원 종류. `user_group.RESOURCE_TYPES` 와 같아야 한다 —
#: `test_scope_groups.py` 가 두 목록이 같은지 고정한다.
SCOPED_RESOURCE_TYPES = ('tab', 'dashboard', 'geo_map', 'geo_facility')

#: 변경으로 보는 함수 이름 접미사.
#:
#: ⚠ **`_del` 도 넣는다.** 처음에는 뺐다 — "삭제는 전부
#: `delete_entry_with_id()` 라는 초크포인트를 지나니 거기서 막으면 된다" 고
#: 봤기 때문이다. **틀렸다**(2026-08-22 실측):
#:
#:   `output_del` 은 초크포인트를 부르기 **전에** 측정값을 지우고 바인딩을
#:   끊는다. 그리고 초크포인트의 반환값 0(거부)을 **보지 않고** "삭제 성공" 을
#:   보고했다. 결과는 출력은 남았는데 그 측정값·채널은 사라진 **부분 변경**
#:   이고, 사용자는 성공 메시지를 봤다.
#:
#: 초크포인트는 뒤를 받치는 것이고 실제 경계는 각 `_del` 의 맨 앞이다.
#: 부수 효과보다 먼저 막지 않으면 "막았다" 가 "절반만 했다" 가 된다.
MUTATION_SUFFIXES = ('_mod', '_add', '_del', '_duplicate', '_copy', '_lock')

#: 변경 함수를 훑는 곳. 엔티티 CRUD 는 이 계층에 모여 있다.
MUTATION_DIRS = ('aot/aot_flask/utils',)

#: 변경 함수인데 스코프를 묻지 않아도 되는 자리. **근거를 함께 적을 것.**
MUTATION_EXEMPT = {
    ('aot/aot_flask/utils/utils_dashboard.py', 'dashboard_add'):
        '**새 대시보드를 만드는 일이라 판정할 대상이 없다.** 만들어진 것은 '
        '부여가 없는 자원(=전원 공개)이므로 아무 경계도 넘지 않는다. '
        '만들자마자 부여하는 것은 그룹 화면의 몫이다.',
}


def _exempt_reason(rel, func):
    for (path, name), reason in EXEMPT.items():
        if path == rel and name in ('*', func):
            return reason
    return None


def _iter_functions(tree):
    """(함수노드, 이름) — 중첩 함수도 각각 본다.

    중첩을 건너뛰면 라우트 안에 정의된 헬퍼에 제어 호출을 옮기는 것만으로
    검사를 우회하게 된다.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, node.name


def _daemon_receivers(node):
    """이 함수 안에서 `DaemonControl()` 을 담은 지역 이름들.

    **수신자를 보지 않으면 오탐이 쏟아진다.** `utils_controller.controller_activate`
    처럼 같은 이름의 유틸 함수가 있고, 그것들은 결국
    `utils_general.controller_activate_deactivate` 라는 **한 곳**을 지나므로
    거기서 한 번 막으면 된다. 호출 이름만 보면 그 10여 곳이 전부 미게이트로
    잡혀, 정작 봐야 할 진짜 제어 경로가 목록에 파묻힌다.
    """
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Assign):
            continue
        call = child.value
        if not isinstance(call, ast.Call):
            continue
        fname = call.func.id if isinstance(call.func, ast.Name) else (
            call.func.attr if isinstance(call.func, ast.Attribute) else None)
        if fname != 'DaemonControl':
            continue
        for target in child.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _control_calls_in(node):
    """이 함수 안의 **데몬 제어** 호출 이름 집합."""
    receivers = _daemon_receivers(node)
    found = set()
    for child in ast.walk(node):
        if not (isinstance(child, ast.Call) and
                isinstance(child.func, ast.Attribute)):
            continue
        if child.func.attr not in DAEMON_CONTROL_CALLS:
            continue
        value = child.func.value
        if isinstance(value, ast.Name) and value.id in receivers:
            found.add(child.func.attr)
        elif isinstance(value, ast.Call):
            # DaemonControl().output_on(...) 처럼 즉석 호출
            inner = value.func
            iname = inner.id if isinstance(inner, ast.Name) else (
                inner.attr if isinstance(inner, ast.Attribute) else None)
            if iname == 'DaemonControl':
                found.add(child.func.attr)
    return found


def _calls_in(node):
    """이 함수 안에서 불린 속성 이름 집합(스코프 호출 확인용)."""
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
    return names


def _check_mutations(findings):
    """엔티티 변경 함수가 스코프를 지나는지 (A1b).

    제어(A1a)와 판별 기준이 다르다 — 저기는 "데몬에게 작동을 시키는가",
    여기는 "스코프 대상 모델을 만들거나 고치는가" 다. 삭제는 초크포인트
    (`delete_entry_with_id`)가 이미 막으므로 세지 않는다.
    """
    for scan in MUTATION_DIRS:
        base = os.path.join(_REPO, scan)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not name.endswith('.py'):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, _REPO).replace(os.sep, '/')
            try:
                tree = ast.parse(open(path, encoding='utf-8').read())
            except SyntaxError:
                continue
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef):
                    continue
                if not node.name.endswith(MUTATION_SUFFIXES):
                    continue
                touched = {c.id for c in ast.walk(node)
                           if isinstance(c, ast.Name)} & SCOPED_MODELS
                if not touched:
                    continue
                if (rel, node.name) in MUTATION_EXEMPT:
                    continue
                if any(c in SCOPE_CALLS for c in _calls_in(node)):
                    continue
                findings['missing-mutation-gate'].append({
                    'file': rel, 'function': node.name, 'line': node.lineno,
                    'models': sorted(touched)})


def _check_resource_types_are_enforced(findings):
    """**부여할 수 있으면 강제하는 곳이 있어야 한다.**

    2026-08-22 에 실제로 어긋났다: 지도(`geo_map`)에 부여 화면을 붙이고 영향
    미리보기까지 만들었는데 **강제 지점이 0곳**이었다. 관리자는 부여하고
    "3명이 잃습니다" 를 보고 저장하지만 실제로는 아무것도 막히지 않는다 —
    설계가 "설정했는데 안 먹는다" 라 부르는 그 침묵이고, 접근 제어에서 가장
    나쁜 종류다(권한이 있다고 믿는 상태).

    변경 검사(`_check_mutations`)가 이것을 못 잡은 이유는 그쪽이
    `aot/aot_flask/utils/utils_*.py` 만 훑기 때문이다. 지도·시설의 쓰기는
    `routes_geo.py` 계열에 있다. 자리마다 훑는 규칙을 늘리는 대신, **종류마다
    최소 한 곳은 있어야 한다** 는 불변식으로 잡는다 — 새 자원 종류를 추가하는
    사람이 화면만 만들고 강제를 잊는 것이 이 실패의 모양이기 때문이다.
    """
    import re

    types = set(SCOPED_RESOURCE_TYPES)
    seen = {t: 0 for t in types}
    for root, dirs, files in os.walk(os.path.join(_REPO, 'aot')):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'tests', 'scripts')]
        for name in sorted(files):
            if not name.endswith('.py'):
                continue
            rel = os.path.relpath(os.path.join(root, name), _REPO).replace(os.sep, '/')
            if rel.startswith('aot/aot_flask/access/'):
                continue                 # 리졸버 자신은 강제가 아니다
            if rel == 'aot/aot_flask/routes_access.py':
                continue                 # 부여를 편집하는 화면이지 강제가 아니다
            try:
                src = open(os.path.join(root, name), encoding='utf-8').read()
            except OSError:
                continue
            for t in types:
                seen[t] += len(re.findall(
                    r"can_operate\(\s*['\"]%s['\"]" % re.escape(t), src))

    for t in sorted(types):
        if seen[t] == 0:
            findings['unenforced-resource-type'].append({
                'resource_type': t,
                'note': '부여는 되는데 막는 곳이 없다'})


def inspect():
    findings = {'missing-gate': [], 'missing-mutation-gate': [],
                'unenforced-resource-type': [], 'inventory-drift': []}
    seen = set()

    for scan in SCAN_DIRS:
        base = os.path.join(_REPO, scan)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for name in sorted(files):
                if not name.endswith('.py'):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, _REPO).replace(os.sep, '/')
                try:
                    tree = ast.parse(open(path, encoding='utf-8').read())
                except SyntaxError as exc:
                    return {'error': '{}: {}'.format(rel, exc)}, 2

                for node, func in _iter_functions(tree):
                    calls = _calls_in(node)
                    control = _control_calls_in(node)
                    gated = bool(calls & SCOPE_CALLS)
                    key = (rel, func)
                    if gated:
                        seen.add(key)
                    if not control:
                        continue
                    if gated:
                        continue
                    reason = _exempt_reason(rel, func)
                    if reason:
                        continue
                    findings['missing-gate'].append({
                        'file': rel, 'function': func, 'line': node.lineno,
                        'control_calls': sorted(control)})

    for rel, func in sorted(GATED_CONTROL_VIEWS):
        if (rel, func) not in seen:
            findings['inventory-drift'].append({'file': rel, 'function': func})

    _check_mutations(findings)
    _check_resource_types_are_enforced(findings)

    counts = {k: len(v) for k, v in findings.items()}
    return ({'findings': findings, 'counts': counts},
            1 if sum(counts.values()) else 0)


def _render(result):
    if 'error' in result:
        print('검사 실패: {}'.format(result['error']))
        return
    total = sum(result['counts'].values())
    if total == 0:
        print('정상 — 제어 경로 {}곳과 엔티티 변경 경로가 전부 스코프를 '
              '지납니다.'.format(len(GATED_CONTROL_VIEWS)))
        return

    drift = result['findings']['inventory-drift']
    if drift:
        print('\n[inventory-drift] 게이트가 사라진 제어 경로 — {}건'.format(len(drift)))
        for row in drift:
            print('    {file}:{function} — 스코프 호출이 없습니다. '
                  '되돌리거나, 경로가 없어졌다면 GATED_CONTROL_VIEWS 에서 뺄 것.'
                  .format(**row))

    unenforced = result['findings'].get('unenforced-resource-type') or []
    if unenforced:
        print('\n[unenforced-resource-type] 부여는 되는데 막는 곳이 없는 종류 '
              '— {}건'.format(len(unenforced)))
        for row in unenforced:
            print('    {resource_type} — {note}'.format(**row))
        print('\n    부여 화면만 있고 강제가 없으면 "설정했는데 안 먹는다" 가 '
              '된다. 그 침묵이 접근 제어에서 가장 나쁘다.')

    mut = result['findings'].get('missing-mutation-gate') or []
    if mut:
        print('\n[missing-mutation-gate] 스코프를 지나지 않는 엔티티 변경 — {}건'
              .format(len(mut)))
        for row in mut:
            print('    {file}:{line} {function}() → {models}'.format(
                models=', '.join(row['models']), **row))
        print('\n    대상이 정해진 **뒤에** scope.can_operate*() 를 부를 것.')
        print('    판정할 대상이 없다면 MUTATION_EXEMPT 에 **근거와 함께** 적을 것.')

    missing = result['findings']['missing-gate']
    if missing:
        print('\n[missing-gate] 스코프를 지나지 않는 제어 호출 — {}건'.format(len(missing)))
        for row in missing:
            print('    {file}:{line} {function}() → {calls}'.format(
                calls=', '.join(row['control_calls']), **row))
        print('\n    제어라면 scope.can_operate_device() 를 붙이고 '
              'GATED_CONTROL_VIEWS 에 넣을 것.')
        print('    제어가 아니라면 EXEMPT 에 **근거와 함께** 적을 것.')

    print('\n합계 {}건'.format(total))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--json', action='store_true', help='기계 판독')
    args = parser.parse_args()

    result, code = inspect()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _render(result)
    return code


if __name__ == '__main__':
    sys.exit(main())
