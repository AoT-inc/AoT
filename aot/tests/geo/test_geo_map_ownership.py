# coding=utf-8
"""P1 회귀 테스트 — 지도 자동 생성 폐지.

docs/design/geo-data-integrity.md "지도 소유권 모델" 의 원칙 4 를 고정한다:
지도는 사용자가 명시적으로 만든다. 장치 생성·수정·복제도, 페이지 렌더도
지도를 만들지 않는다.

배경: AoT 초기에는 지도 위에 장치만 있어서 "장치가 지도를 소유한다"가
맞았다. site/facility 도입으로 위치의 정본이 지리요소로 옮겨간 뒤에도
`map_config_id` 자동 배정만 남아, 장치 67개가 전부 지도를 갖는데 그 지도의
91%는 도형이 하나도 없는 상태가 됐다(2026-08-04 운영 3서버 실측).
가장 심한 것은 **GET 요청이 지도를 만들고 커밋**하던 경로였다.

여기서는 소스 수준(AST)으로 자동 생성 경로의 부재를 고정한다. 라우트
핸들러 전체를 띄우려면 폼·데몬·번역 스택이 필요해 단위 테스트에 부적합하고,
정작 검증하고 싶은 것은 "그 코드가 존재하지 않는다"이기 때문이다.
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

# 지도를 만드는 팩토리들. P1 이후 호출자가 있으면 안 된다.
FACTORIES = {'ensure_map_config', 'create_map_config', 'clone_map_config'}

# 팩토리 정의 파일 자체는 예외(내부 호출·정의가 남아 있다 — P5 에서 제거).
FACTORY_MODULE = 'aot/aot_flask/utils/utils_map_config.py'


def _iter_py():
    scan = os.path.join(ROOT, 'aot')
    for dirpath, dirnames, filenames in os.walk(scan):
        dirnames[:] = [d for d in dirnames
                       if d not in ('__pycache__', 'node_modules', 'env',
                                    'tests')]
        for fn in filenames:
            if fn.endswith('.py'):
                yield os.path.join(dirpath, fn)


def _rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, '/')


class TestNoAutomaticMapCreation(unittest.TestCase):

    def test_no_caller_of_map_factories(self):
        """장치·라우트 어디에서도 지도를 자동 생성하지 않는다."""
        offenders = []
        for path in _iter_py():
            rel = _rel(path)
            if rel == FACTORY_MODULE:
                continue
            try:
                tree = ast.parse(open(path, encoding='utf-8').read())
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and \
                        isinstance(node.func, ast.Name) and \
                        node.func.id in FACTORIES:
                    offenders.append('%s:%d %s()' % (rel, node.lineno,
                                                     node.func.id))
        self.assertEqual(
            offenders, [],
            '지도 자동 생성이 되살아났습니다 (원칙 4). 지도는 사용자가 '
            '명시적으로 만들고, 장치는 배치될 때 지도에 속합니다:\n  ' +
            '\n  '.join(offenders))

    def test_function_list_page_does_not_commit(self):
        """GET /function 목록이 지도를 만들고 커밋하던 루프가 없어야 한다."""
        src = open(os.path.join(ROOT, 'aot/aot_flask/routes_function.py'),
                   encoding='utf-8').read()
        self.assertNotIn('map_cfg_committed', src,
                         'GET 요청이 지도를 생성·커밋하던 루프가 남아 있습니다.')

    def test_device_delete_guard_covers_all_seven_models(self):
        """_map_still_referenced 가 map_config_id 를 가진 7개 모델을 전부 본다.

        목록 누락은 이 도메인의 반복 실패 유형이다 — 과거 Function 이 빠져
        있어, Function 이 참조 중인 지도를 다른 장치 삭제가 지울 수 있었다.
        """
        from aot.aot_flask.utils import utils_map_config as mod
        src = open(mod.__file__.replace('.pyc', '.py'),
                   encoding='utf-8').read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == '_map_still_referenced')
        names = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name)}
        for model in ('Input', 'Output', 'PID', 'Trigger', 'Conditional',
                      'CustomController', 'Function'):
            self.assertIn(model, names,
                          '%s 가 삭제 가드에서 빠졌습니다.' % model)

    def test_factories_are_marked_dead(self):
        """폐지된 팩토리는 사망 표시를 유지한다 — 무심코 되살리지 않도록."""
        src = open(os.path.join(ROOT, FACTORY_MODULE), encoding='utf-8').read()
        tree = ast.parse(src)
        for name in FACTORIES:
            fn = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == name),
                      None)
            self.assertIsNotNone(fn, '%s 가 사라졌습니다.' % name)
            doc = ast.get_docstring(fn) or ''
            self.assertIn('사망', doc,
                          '%s 의 사망 표시가 없습니다 — 되살아날 위험.' % name)


if __name__ == '__main__':
    unittest.main()
