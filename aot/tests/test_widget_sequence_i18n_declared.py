# coding=utf-8
"""위젯 본문의 사용자 노출 문구는 전부 .py 안에서 추출 가능해야 한다.

위젯 문구는 JS(`window._('...')`)와 Jinja(`{{ _('...') }}`) 안에 있는데, 그 둘은
파이썬 삼중따옴표 문자열 **안**이라 pybabel 의 파이썬 추출기가 보지 못한다.
생성물인 widget_template_*.html 에서 뽑는 것도 성립하지 않는다 — 그건 배포
대상이 아니라 실행 시 재생성되고 .gitignore 대상이라 클린 체크아웃에는 없다.

그래서 각 위젯은 `TRANSLATABLE_STRINGS` 로 자기 문구를 한 번 더 선언한다.
선언이 본문과 어긋나면 그 문구는 조용히 번역 대상에서 빠지고, msgid 자체가
카탈로그에 없으니 **번역률 통계에도 안 잡힌다** — "완성" 으로 집계된 언어에서도
화면 절반이 영어로 나오는 상태가 된다. 실제로 70개 중 46개가 그랬다.
"""
import ast
import os
import re

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_WIDGET = os.path.join(_REPO, 'aot', 'widgets', 'widget_trigger_sequence.py')

# 본문에서 문구를 꺼내는 규칙: window._('..') · _('..') · {{ _('..') }}
_CALL = re.compile(r"""(?:window\._|\b_)\(\s*(['"])(.+?)\1\s*\)""")


def _body_strings(src: str) -> set:
    """위젯이 실제로 화면에 쓰는 문구.

    파이썬 주석 줄은 뺀다 — 설명에 적은 `window._('...')` 같은 예시 표기가
    본문 문구로 잡히면 안 된다(위젯 본문은 삼중따옴표 문자열 안이라 줄
    첫머리가 `#` 인 경우가 없다).
    """
    code = '\n'.join(l for l in src.splitlines() if not l.lstrip().startswith('#'))
    return {m.group(2) for m in _CALL.finditer(code) if m.group(2)}


def _declared_strings(src: str) -> set:
    """TRANSLATABLE_STRINGS 에 lazy_gettext 로 선언된 문구."""
    tree = ast.parse(src)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, 'id', None) == 'TRANSLATABLE_STRINGS' for t in node.targets):
            continue
        out = set()
        for el in node.value.elts:
            if (isinstance(el, ast.Call)
                    and getattr(el.func, 'id', None) == 'lazy_gettext'
                    and el.args
                    and isinstance(el.args[0], ast.Constant)):
                out.add(el.args[0].value)
        return out
    return set()


@pytest.fixture(scope='module')
def src():
    with open(_WIDGET, encoding='utf-8') as fh:
        return fh.read()


def test_선언_목록이_존재한다(src):
    assert _declared_strings(src), \
        "TRANSLATABLE_STRINGS 가 없다 — 위젯 문구가 추출되지 않는다"


def test_본문_문구가_전부_선언되어_있다(src):
    missing = sorted(_body_strings(src) - _declared_strings(src))
    assert not missing, (
        "본문에는 있는데 TRANSLATABLE_STRINGS 에 없다 — 이 문구들은 카탈로그에 "
        f"안 올라가고 통계에도 안 잡힌다:\n  " + "\n  ".join(missing))


def test_선언에만_있는_죽은_문구가_없다(src):
    """본문에서 사라진 문구가 선언에 남으면 번역자가 헛일을 한다."""
    stale = sorted(_declared_strings(src) - _body_strings(src))
    assert not stale, (
        "TRANSLATABLE_STRINGS 에만 있고 본문에는 없다:\n  " + "\n  ".join(stale))
