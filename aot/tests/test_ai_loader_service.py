# coding=utf-8
"""AILoaderService 가 import 만이 아니라 **실제로 불렸을 때** 도는지 본다.

이 모듈은 히스토리 시작부터 모듈 전역(`_loader_cache`·`_cache_lock`·`logger`·
`yaml`·`timedelta`·시드 경로 3개)이 통째로 빠진 채였다. 함수 본문에서만
참조되므로 **import 는 멀쩡히 성공하고**, 어느 메서드를 부르든 그때서야
NameError 가 난다.

그 NameError 를 유일한 호출부(`action_registry_sync.py`)가 광범위한
`except Exception` 으로 받아 `(non-fatal)` 경고 한 줄로 남기고 있었다. 그래서
증상은 "MCP 도구 동기화 후 캐시가 안 비워진다" 도 아니고 그냥 **아무것도
안 일어나는 것**이었다 — 역할·액션 설정을 읽는 경로 전체가 죽어 있었는데
기동도 정상, 로그도 경고 한 줄이라 아무도 못 봤다.

import 만 확인하는 검사로는 이 계열을 절대 못 잡는다. 그래서 여기서는
공개 API 를 실제로 호출한다.

DB 없이도 돌아야 한다 — 모듈이 선언한 폴백이 "DB 를 못 읽으면 YAML 기본값"
이기 때문이다. 그래서 이 테스트는 app context 없이 그대로 돈다.

    python3 aot/tests/test_ai_loader_service.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.ai.ai_loader_service import AILoaderService  # noqa: E402


class LoaderActuallyRunsTest(unittest.TestCase):
    """공개 API 5종을 실제로 부른다. 부르지 않으면 아무 의미가 없다."""

    def setUp(self):
        AILoaderService.invalidate()

    def test_roles_load_from_the_yaml_seed(self):
        roles = AILoaderService.get_all_roles()
        self.assertTrue(roles, "역할이 하나도 안 실렸습니다 — YAML 시드를 "
                               "못 읽었거나 모듈 전역이 또 빠졌습니다.")
        for expected in ('router', 'planner', 'executor'):
            self.assertIn(expected, roles)

    def test_actions_load_from_the_yaml_seed(self):
        actions = AILoaderService.get_all_actions()
        self.assertTrue(actions)

    def test_single_lookups(self):
        self.assertTrue(AILoaderService.get_role('router'))
        self.assertEqual({}, AILoaderService.get_role('없는역할'))
        self.assertEqual({}, AILoaderService.get_action('없는액션'))

    def test_cache_is_reused_and_can_be_invalidated(self):
        """캐시가 실제로 물리는지 — _loader_cache/_cache_lock 이 살아 있어야 한다."""
        first = AILoaderService.get_all_roles()
        self.assertIs(first, AILoaderService.get_all_roles())

        AILoaderService.invalidate('roles')
        self.assertIsNot(first, AILoaderService.get_all_roles())

        AILoaderService.invalidate()
        self.assertIsNot(first, AILoaderService.get_all_roles())

    def test_legacy_import_path_still_works(self):
        """aot.ai.services.ai_loader_service 는 옛 경로 shim 이다."""
        from aot.ai.services.ai_loader_service import AILoaderService as Shim
        self.assertTrue(Shim.get_all_actions())


class NoUndefinedModuleGlobalsTest(unittest.TestCase):
    """함수 본문이 쓰는 이름이 모듈에 실제로 정의돼 있는가.

    위 호출 테스트가 지나가는 경로만으로는 부족하다 — 드물게 타는 분기에서
    같은 실수가 나면 그대로 통과한다. 소스를 훑어 한 번에 본다.
    """

    def test_every_referenced_global_is_defined(self):
        import ast
        import builtins

        path = os.path.join(os.path.dirname(__file__), '..', 'ai',
                            'ai_loader_service.py')
        with open(os.path.abspath(path), encoding='utf-8') as handle:
            tree = ast.parse(handle.read())

        defined = set(dir(builtins))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    defined.add((alias.asname or alias.name).split('.')[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                defined.update(target.id for target in node.targets
                               if isinstance(target, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                                ast.Name):
                defined.add(node.target.id)

        missing = set()
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            local = {arg.arg for arg in fn.args.args + fn.args.kwonlyargs}
            for sub in ast.walk(fn):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    local.add(sub.id)
                elif isinstance(sub, ast.ExceptHandler) and sub.name:
                    local.add(sub.name)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        local.add((alias.asname or alias.name).split('.')[0])
            for sub in ast.walk(fn):
                if (isinstance(sub, ast.Name)
                        and isinstance(sub.ctx, ast.Load)
                        and sub.id not in defined
                        and sub.id not in local):
                    missing.add(sub.id)

        self.assertFalse(
            missing,
            "모듈에 정의되지 않은 이름을 함수가 참조합니다: {} — import 는 "
            "성공하고 호출 시점에 NameError 가 납니다.".format(sorted(missing)))


if __name__ == '__main__':
    unittest.main()
