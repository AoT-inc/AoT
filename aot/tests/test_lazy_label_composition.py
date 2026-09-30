# -*- coding: utf-8 -*-
"""모듈 수준의 조합 라벨이 import 시점에 굳지 않는지 지킨다.

``f"{lazy_gettext('A')} ({lazy_gettext('B')})"`` 나 ``"{} ({})".format(lazy_gettext(..), ..)``
를 모듈 수준(함수 밖)에 쓰면 처음 import 될 때 영어로 굳는다 —
``aot.utils.lazy_text.lazy_join`` / ``lazy_format`` 을 쓸 것.
"""
import ast
import pathlib

from flask_babel.speaklater import LazyString

from aot.utils.lazy_text import lazy_format, lazy_join

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAZY_CALLS = {'lazy_gettext', 'lg', 'lazy_pgettext'}


def _is_lazy(node):
    for x in ast.walk(node):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in LAZY_CALLS:
            return True
        if isinstance(x, ast.Subscript) and isinstance(x.value, ast.Name) and x.value.id in ('T', 'TRANSLATIONS'):
            return True
    return False


def _module_level_violations(tree):
    found = []

    def visit(node, in_func):
        for ch in ast.iter_child_nodes(node):
            inner = in_func or isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            bad = (not inner) and (
                (isinstance(ch, ast.JoinedStr)
                 and any(isinstance(v, ast.FormattedValue) and _is_lazy(v.value) for v in ch.values))
                or (isinstance(ch, ast.Call) and isinstance(ch.func, ast.Attribute)
                    and ch.func.attr == 'format'
                    and (any(_is_lazy(a) for a in ch.args)
                         or any(_is_lazy(k.value) for k in ch.keywords))))
            if bad:
                found.append(ch.lineno)
            else:
                visit(ch, inner)

    visit(tree, False)
    return found


def test_모듈_수준에서_lazy_값을_f문자열_format으로_조합하지_않는다():
    problems = []
    for path in sorted(ROOT.rglob('*.py')):
        if 'tests' in path.relative_to(ROOT).parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        for line in _module_level_violations(tree):
            problems.append('%s:%d' % (path.relative_to(ROOT), line))
    assert not problems, (
        '모듈 수준 f-string/.format 이 lazy 문구를 import 시점에 굳힌다 — '
        'aot.utils.lazy_text.lazy_join/lazy_format 을 쓰세요:\n' + '\n'.join(problems))


def test_lazy_join_lazy_format_은_접근할_때마다_다시_계산한다():
    state = {'word': 'Edge'}
    part = LazyString(lambda: state['word'])
    joined = lazy_join('Trigger: ', part)
    formatted = lazy_format('{} ({})', part, 'x')

    assert str(joined) == 'Trigger: Edge'
    assert str(formatted) == 'Edge (x)'
    state['word'] = '엣지'
    assert str(joined) == 'Trigger: 엣지'
    assert str(formatted) == '엣지 (x)'
    assert joined < 'Z' and sorted([joined, 'A']) == ['A', joined]
