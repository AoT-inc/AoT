# coding=utf-8
"""`/data_batch` 가 조회 전용이라는 전제를 고정한다.

이 전제 위에 두 가지가 얹혀 있다.

1. **CSRF 면제** (`app.extension_csrf`). API 키로 붙는 클라이언트(원격 AoT
   수집)는 세션이 없어 CSRF 토큰을 만들 방법이 없다. 면제의 근거는 "이 경로가
   상태를 바꾸지 않는다" 하나뿐이다 — 상태를 바꾸기 시작하면 근거가 사라진다.
2. **스코프 가드의 예외** (`app._READONLY_POST_PATHS`). 읽기 전용 API 키에게
   POST 를 허용하는 유일한 경로다. 여기에 쓰기가 생기면 읽기 전용 키가 쓰기를
   할 수 있게 된다.

둘 다 조용히 깨진다 — 쓰기를 하나 추가해도 에러는 나지 않고, 그저 보호가
사라질 뿐이다. 그래서 사람 대신 이 테스트가 본다.

`app.py` 의 주석은 "핸들러 본문을 읽고 확인할 것" 이라고 적어 두었지만, 읽어야
할 사람이 읽지 않는 것이 정확히 이런 검사가 필요한 이유다.
"""
import ast
import os
import unittest

_ROUTES = os.path.join(os.path.dirname(__file__), '..',
                       'aot_flask', 'routes_general.py')
_APP = os.path.join(os.path.dirname(__file__), '..', 'aot_flask', 'app.py')

#: data_batch 와 그것이 부르는 헬퍼들. 헬퍼를 새로 만들면 여기에도 넣을 것 —
#: 그러지 않으면 쓰기를 헬퍼로 옮기는 것만으로 검사를 우회하게 된다.
_READ_ONLY_FUNCTIONS = {
    'data_batch',
    '_prefetch_last_metadata',
    '_resolve_last_params',
    '_past_payload',
    '_run_last_jobs',
}

#: DB 상태를 바꾸는 호출. `execute` 는 raw SQL 로 UPDATE/INSERT 를 넣는 경로라
#: 함께 막는다.
_WRITE_CALLS = ('commit', 'add', 'add_all', 'delete', 'merge', 'flush',
                'execute', 'save', 'bulk_save_objects')


def _functions(path):
    with open(os.path.abspath(path), encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


class DataBatchIsReadOnlyTest(unittest.TestCase):

    def setUp(self):
        self.functions = _functions(_ROUTES)

    def test_every_named_function_exists(self):
        """이름이 바뀌었는데 검사만 남아 통과하는 상황을 막는다."""
        missing = _READ_ONLY_FUNCTIONS - set(self.functions)
        self.assertFalse(
            missing,
            "routes_general.py 에 없는 함수가 목록에 있습니다: {} — 이름이 "
            "바뀌었다면 이 목록도 함께 고치십시오.".format(sorted(missing)))

    def test_no_write_calls(self):
        for name in sorted(_READ_ONLY_FUNCTIONS):
            node = self.functions.get(name)
            if node is None:
                continue
            hits = [
                "{}:{} → .{}()".format(name, sub.lineno, sub.func.attr)
                for sub in ast.walk(node)
                if isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in _WRITE_CALLS
            ]
            self.assertFalse(
                hits,
                "/data_batch 가 상태를 바꾸고 있습니다: {}\n"
                "이 경로의 CSRF 면제(app.extension_csrf)와 읽기 전용 키 예외"
                "(_READONLY_POST_PATHS)는 '아무것도 쓰지 않는다' 를 근거로 합니다. "
                "쓰기가 필요하면 면제와 예외를 먼저 걷어내십시오.".format(hits))


class ExemptionWiringTest(unittest.TestCase):
    """면제가 실제로 배선돼 있는지 — 주석만 남고 코드가 빠지는 것을 막는다."""

    def setUp(self):
        with open(os.path.abspath(_APP), encoding='utf-8') as handle:
            self.source = handle.read()

    def test_data_batch_is_exempted(self):
        self.assertIn('csrf.exempt(data_batch)', self.source)

    def test_scope_guard_still_allows_the_path(self):
        """CSRF 를 풀어도 스코프 가드가 막으면 수집 키는 여전히 성립하지 않는다."""
        self.assertIn("_READONLY_POST_PATHS = frozenset(('/data_batch',))",
                      self.source)


if __name__ == '__main__':
    unittest.main()
