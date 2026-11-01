# coding=utf-8
"""데몬 RPC(Pyro5) 로 나가는 값에 `LazyString` 이 섞이지 않는지 지킨다.

액션 이름(`ACTION_INFORMATION['name']`)은 번역 대상이라 `lazy_gettext` 로 선언한다.
그것을 시퀀스 상태(`function_status`)의 `action_name` 에 그대로 실으면 Pyro5 가
`LazyString` 을 직렬화하지 못해 **상태 전체가** `{'error': ['unsupported serialized
class: flask_babel.speaklater.LazyString']}` 로 돌아온다 — 에러는 200 응답 안의
내용물이라 위젯은 "시퀀스가 꺼져 있다" 처럼 보이고, 돌고 있는 단계도 표시되지 않는다.
2026-09-26 액션 이름 번역 전환(6ca698818 · f5ece0413)이 그 길을 열었다.
"""
import ast
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_CONTROLLER = os.path.join(_ROOT, 'controllers', 'controller_trigger_sequence.py')


def test_pyro5_cannot_carry_a_lazy_string_but_carries_its_text():
    """전제 — 지연 문자열은 그대로는 못 건너고, `str()` 한 값은 건넌다."""
    serializers = pytest.importorskip('Pyro5.serializers')
    from flask_babel.speaklater import LazyString
    ser = serializers.SerpentSerializer()

    payload = ser.dumps({'action_name': str(LazyString(lambda: 'Send Email'))})
    assert ser.loads(payload) == {'action_name': 'Send Email'}

    with pytest.raises(Exception):
        ser.loads(ser.dumps({'action_name': LazyString(lambda: 'Send Email')}))


def _action_name_reads(tree):
    """`<...>['name']` 로 액션 정의에서 이름을 꺼내는 곳과, 그것이 `str()` 로 감싸였는지."""
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == 'name'):
            continue
        base = ast.unparse(node.value)
        if 'dict_action' not in base:
            continue
        parent = parents.get(node)
        wrapped = (isinstance(parent, ast.Call)
                   and isinstance(parent.func, ast.Name)
                   and parent.func.id == 'str')
        yield node.lineno, base, wrapped


def test_sequence_status_stringifies_action_names():
    with open(_CONTROLLER, encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    reads = list(_action_name_reads(tree))
    assert reads, '액션 이름을 읽는 자리를 찾지 못했습니다 — 이 검사가 낡았습니다'
    bare = [(line, base) for line, base, wrapped in reads if not wrapped]
    assert not bare, (
        'controller_trigger_sequence.py 가 액션 이름을 str() 없이 싣습니다 '
        f'(데몬 RPC 가 LazyString 을 못 건넙니다): {bare}')
