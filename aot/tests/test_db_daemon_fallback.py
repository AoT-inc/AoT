# coding=utf-8
"""`db_retrieve_table_daemon()` 실패 반환 규약 테스트.

이 함수는 DB 조회가 실패해도(락 5회 재시도 초과, 디스크 I/O 에러) 예외를
올리지 않고 "빈 결과" 를 돌려준다. 문제는 **그 빈 결과가 성공 시 반환 타입과
달랐다는 것**이다 — 단일 행을 기대한 호출에도 `[]` 를 줬다. 그래서 호출부가
`settings.measurement_db_host` 처럼 속성에 접근하면

    AttributeError: 'list' object has no attribute 'measurement_db_host'

라는, 원인과 한참 떨어져 보이는 오류로 터졌다. 2026-08-04 에 이 경로가
SafetyPreGate.evaluate() 안에서 터지면서 강풍·강우 강제 폐쇄 명령이 반환되지도
못하고 사이클이 죽을 수 있는 상태였다.

이제 단일 행 기대에는 None, 목록 기대에는 [] 를 돌려준다. 호출부는 여전히
None 검사를 해야 하지만, 최소한 실패가 실패처럼 보이고 `if x:` 가드가 의도대로
동작한다.
"""
from unittest.mock import patch

import pytest

from aot.utils import database as dbmod


class _Boom:
    """session_scope 컨텍스트에 들어가자마자 실패하는 스텁."""

    def __init__(self, exc):
        self._exc = exc

    def __call__(self, *_a, **_k):
        raise self._exc


def _io_error():
    from sqlite3 import OperationalError
    return OperationalError('disk I/O error')


def _lock_error():
    from sqlite3 import OperationalError
    return OperationalError('database is locked')


@pytest.mark.parametrize('kwargs', [
    {'entry': 'first'},
    {'device_id': 3},
    {'unique_id': 'abc'},
])
def test_single_row_failure_returns_none(kwargs):
    """단일 행을 기대한 호출은 None 을 받아야 `if x:` 가드가 성립한다."""
    with patch.object(dbmod, 'session_scope', _Boom(_io_error())):
        result = dbmod.db_retrieve_table_daemon(object, **kwargs)
    assert result is None, f'{kwargs} → {result!r}'


@pytest.mark.parametrize('kwargs', [
    {'entry': 'all'},
    {},
])
def test_list_failure_stays_empty_list(kwargs):
    """목록을 기대한 호출은 [] 그대로 — 반복문이 그냥 안 돌면 된다."""
    with patch.object(dbmod, 'session_scope', _Boom(_io_error())):
        result = dbmod.db_retrieve_table_daemon(object, **kwargs)
    assert result == [], f'{kwargs} → {result!r}'


def test_lock_failure_also_returns_none_for_single(monkeypatch):
    """락은 재시도 후 포기한다 — 그 경로도 같은 규약을 지켜야 한다."""
    monkeypatch.setattr(dbmod.time, 'sleep', lambda *_: None)
    with patch.object(dbmod, 'session_scope', _Boom(_lock_error())):
        result = dbmod.db_retrieve_table_daemon(object, entry='first')
    assert result is None


def test_failure_never_raises():
    """호출부는 이 함수가 예외를 던지지 않는다는 전제로 쓰여 있다."""
    with patch.object(dbmod, 'session_scope', _Boom(RuntimeError('boom'))):
        assert dbmod.db_retrieve_table_daemon(object, entry='first') is None


# ---------------------------------------------------------------------------
# 호출부 계약 — 단일 행 기대인데 가드 없이 속성에 접근하는 코드가 없어야 한다
# ---------------------------------------------------------------------------

def test_no_unguarded_single_row_attribute_access():
    """AST 로 전수 검사. 새 호출부가 가드를 빠뜨리면 여기서 걸린다.

    검사 대상은 `try` 블록 **밖**에서 일어나는 접근이다 — try 안이면 예외가
    삼켜져 기능만 조용히 빠지지만, 밖이면 호출자까지 그대로 전파된다.
    """
    import ast
    import os

    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))          # <repo>/aot
    func = 'db_retrieve_table_daemon'
    offenders = []

    def wants_single(call):
        for kw in call.keywords:
            if kw.arg == 'entry':
                return isinstance(kw.value, ast.Constant) and kw.value.value == 'first'
            if kw.arg in ('device_id', 'unique_id'):
                return True
        return False

    for dirpath, _dirs, files in os.walk(root):
        if any(p in dirpath for p in ('__pycache__', '/tests')):
            continue
        for fname in files:
            if not fname.endswith('.py'):
                continue
            path = os.path.join(dirpath, fname)
            try:
                src = open(path, encoding='utf-8').read()
                tree = ast.parse(src)
            except Exception:
                continue
            if func not in src:
                continue

            protected = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    for stmt in node.body:
                        for sub in ast.walk(stmt):
                            if hasattr(sub, 'lineno'):
                                protected.add(sub.lineno)

            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                targets = {}
                for node in ast.walk(fn):
                    if (isinstance(node, ast.Assign)
                            and isinstance(node.value, ast.Call)):
                        cf = node.value.func
                        name = cf.id if isinstance(cf, ast.Name) else getattr(cf, 'attr', None)
                        if name == func and wants_single(node.value):
                            for t in node.targets:
                                if isinstance(t, ast.Name):
                                    targets[t.id] = node.lineno
                if not targets:
                    continue

                guarded, hits = set(), []
                for node in ast.walk(fn):
                    if isinstance(node, (ast.If, ast.IfExp)):
                        for sub in ast.walk(node.test):
                            if isinstance(sub, ast.Name):
                                guarded.add(sub.id)
                    elif isinstance(node, ast.BoolOp):
                        for v in node.values:
                            for sub in ast.walk(v):
                                if isinstance(sub, ast.Name):
                                    guarded.add(sub.id)
                    elif (isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Name)
                          and node.func.id == 'getattr'
                          and node.args and isinstance(node.args[0], ast.Name)):
                        guarded.add(node.args[0].id)
                    elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                        hits.append((node.value.id, node.lineno))

                for var, call_line in targets.items():
                    if var in guarded:
                        continue
                    bad = [ln for (n, ln) in hits
                           if n == var and ln > call_line and ln not in protected]
                    if bad:
                        offenders.append(
                            f"{os.path.relpath(path, root)}:{min(bad)} "
                            f"({fn.name}) {var}")

    assert not offenders, (
        "db_retrieve_table_daemon() 이 단일 행 기대 호출에 실패 시 None 을 돌려주므로, "
        "가드 없이 속성에 접근하면 DB 락 한 번에 AttributeError 로 터진다:\n  "
        + "\n  ".join(sorted(offenders)))
