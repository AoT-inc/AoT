# coding=utf-8
"""`_` 에 값을 받으면 그 함수의 gettext 가 통째로 가려진다.

## 왜 이 테스트가 있나

`from flask_babel import gettext as _` 로 들어온 `_` 는 모듈 전역이다. 그런데
함수 안에서 `a, _, b = ...` 처럼 **한 번이라도 `_` 에 대입하면** 파이썬은 그
함수에서 `_` 를 지역변수로 보고, 이후 `_("...")` 는 번역이 아니라 **그 값을
호출**하는 코드가 된다.

증상이 원인을 가리지 않는다. 같은 원인이 함수마다 다른 오류로 나타났다
(`which_controller()` 가 `(종류, 모델 클래스, 모델 인스턴스)` 를 돌려주는데,
어느 값을 `_` 로 받았느냐에 따라 호출되는 대상이 달랐다):

  - `action_add` — 세 번째 값(인스턴스)을 받아
    `TypeError: 'Trigger' object is not callable`   (2026-09-27 보고)
  - `action_del` — 가운데 값(**클래스**)을 받아
    `TypeError: __init__() takes 1 positional argument but 2 were given`
    (2026-10-08 사본 DB 에 실제 요청을 보내 확인 — 처음에는 이것도 위와
    같은 문구일 거라고 잘못 적었다)

두 경우 모두 **행은 이미 바뀐 뒤**라 사용자는 "지워졌는데(추가됐는데) 오류가
뜬다" 를 보고, 오류 문구가 모델 쪽을 가리키므로 원인이 번역 함수에 있다고
읽기 어렵다. 삭제는 한 가지가 더 있다 — 오류가 데몬에 새로고침을 알리는 줄
**앞에서** 나므로, 돌고 있는 시퀀스는 지운 액션을 새로고침 전까지 그대로 안고
있다. 추가 경로만 먼저 고쳐져 추가는 되는데 삭제는 안 되는 상태로 남아 있었다.

`pyflakes`(`check_undefined_names.py`)로는 잡히지 않는다 — 이름이 정의돼 있고
문법도 멀쩡하다. 그 줄을 실제로 밟아야 터지므로 테스트도 그 경로를 돌려야
하는데, 모든 번역 호출 경로를 돌려 볼 수는 없다. 그래서 **구조**를 본다.

판정 규칙:

  그 함수가 자기 범위에서 `_` 에 값을 묶고(대입·for·with·walrus),
  그 함수 안에서(중첩 함수 포함) `_()` 를 부른다  →  결함

**중첩 함수에서의 대입은 바깥을 가리지 않는다**(자기 범위만 가린다). 그래서
범위를 구분하지 않으면 `routes_page.page_info` 의 `run_cmd` 안
`(out, _) = proc.communicate()` 가 오탐으로 올라온다 — 실제로 이 검사를 만들며
한 번 그렇게 셌다. 반대로 **호출 쪽은 중첩까지 본다**: 안쪽 함수의 `_()` 는
바깥 함수의 지역 `_` 를 집으므로 그것도 결함이다.

`_` 에 묶기만 하고 `_()` 를 안 부르는 함수는 보지 않는다(지금은 무해하다 —
나중에 그 함수에 번역 호출이 들어오는 순간 이 검사가 잡는다).
"""
import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SOURCE_ROOT = REPO / 'aot'

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _own_scope(fn):
    """`fn` 의 몸통에서 중첩 범위를 들어가지 않고 순회한다."""
    stack = list(fn.body) + [d for d in fn.decorator_list]
    while stack:
        node = stack.pop()
        yield node
        # 중첩 범위는 **그 안으로 들어가지 않는다.** 범위 노드를 걸러내는
        # 자리를 자식 쪽에만 두면, 중첩 함수 자체는 걸러도 그 몸통은 다음
        # 바퀴에 그대로 따라 들어가 아무것도 막지 못한다(이 검사를 쓰며
        # 실제로 그랬다 — page_info 가 계속 오탐으로 올라왔다).
        if isinstance(node, _SCOPES):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _binds_underscore(fn):
    """`fn` 이 자기 범위에서 `_` 에 값을 묶는 줄 번호들."""
    lines = []
    for node in _own_scope(fn):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            targets = [node.target]
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            targets = [node.target]
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            targets = [node.optional_vars]
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name) and sub.id == '_':
                    lines.append(getattr(node, 'lineno', 0))
    return sorted(set(lines))


def _calls_underscore(fn):
    """`fn` 안에서 `_()` 를 부르는 줄 번호들 — 중첩 함수까지 본다."""
    return sorted(
        node.lineno for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == '_')


def find_shadowed_gettext(root):
    """`root` 아래에서 gettext 를 가린 채 번역을 부르는 함수들."""
    offenders = []
    for path in sorted(root.rglob('*.py')):
        rel = path.relative_to(REPO).as_posix()
        if '/tests/' in rel:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            bound = _binds_underscore(fn)
            if not bound:
                continue
            called = _calls_underscore(fn)
            if called:
                offenders.append((rel, fn.name, bound, called))
    return offenders


def test_no_function_shadows_gettext_and_then_translates():
    offenders = find_shadowed_gettext(SOURCE_ROOT)
    assert not offenders, '\n'.join(
        f'{rel}: {name}() 가 {bound} 줄에서 `_` 를 가린 뒤 {called} 줄에서 '
        f'`_()` 를 부른다 — 변수 이름을 `_unused_…` 처럼 바꿀 것'
        for rel, name, bound, called in offenders)


def test_the_check_sees_the_real_defect():
    """판정 규칙 자체의 회귀 — 실제 사고 모양과 오탐 모양을 함께 고정한다."""
    source = '''
from flask_babel import gettext as _

def action_del(form):
    controller_type, _, entry = which_controller(form.device_id.data)
    return _("Action deleted")

def page_info():
    def run_cmd(cmd):
        (out, _) = cmd.communicate()
        return out
    return _("Info")

def plain(form):
    for _ in range(3):
        pass
    return None
'''
    tree = ast.parse(source)
    verdict = {}
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        verdict[fn.name] = bool(_binds_underscore(fn)) and bool(_calls_underscore(fn))

    assert verdict['action_del'] is True, '실제 사고 모양을 못 잡는다'
    assert verdict['page_info'] is False, '중첩 함수의 대입을 바깥 결함으로 센다'
    assert verdict['run_cmd'] is False, '`_()` 를 안 부르는 함수를 결함으로 센다'
    assert verdict['plain'] is False, '`_()` 를 안 부르는 함수를 결함으로 센다'
