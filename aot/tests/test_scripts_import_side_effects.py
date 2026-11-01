# coding=utf-8
"""운영 스크립트를 **import 만 해도** 프로세스 전역 로깅이 바뀌면 안 된다.

`aot/scripts/check_env_coordinator_health.py` 는 기동 로그가 보고서 머리를
덮지 않게 모듈 머리에서 `logging.disable(logging.INFO)` 를 걸었다. 그런데
`logging.disable` 은 프로세스 전역이다. 그 모듈의 순수 헬퍼를 검사하려고
import 하는 테스트가 하나라도 먼저 돌면, 그 뒤 pytest 프로세스 전체에서 INFO
이하가 꺼져 assertLogs/caplog 로 DEBUG·INFO 를 확인하는 무관한 테스트가
**전체 스위트에서만, 순서에 따라** 실패했다 — PR #88 의
`test_settings_matter_routes.py::TestNewDevice::test_secrets_never_logged_on_success`
가 CI 에서 "no logs of level DEBUG or higher triggered" 로 죽은 원인이다.

조용한 CLI 출력은 지켜야 하므로, 끄는 것은 `__main__` 으로 돌 때만이다.
"""
import ast
import importlib
import logging
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HEALTH = os.path.join(_ROOT, 'aot', 'scripts', 'check_env_coordinator_health.py')

# import 해서 확인할 스크립트들. 새로 `logging.disable` 을 쓰는 스크립트가
# 생기면 여기에 더한다.
_MODULES = (
    'aot.scripts.check_env_coordinator_health',
    'aot.scripts.migrate_legacy_coordinator_targets',
)


class TestImportLeavesLoggingAlone(unittest.TestCase):

    def setUp(self):
        self._saved = logging.root.manager.disable
        logging.disable(logging.NOTSET)

    def tearDown(self):
        logging.disable(self._saved)

    def test_import_does_not_disable_logging(self):
        for name in _MODULES:
            with self.subTest(module=name):
                mod = importlib.import_module(name)
                # 앞선 테스트가 이미 import 했을 수 있다 — 모듈 머리를 다시 돌린다.
                importlib.reload(mod)
                self.assertEqual(
                    logging.NOTSET, logging.root.manager.disable,
                    f'{name} 를 import 하는 것만으로 logging.disable 이 걸렸다 — '
                    'CLI 진입점(main / __main__) 안으로 옮겨야 한다')


class TestHealthCheckCliStaysQuiet(unittest.TestCase):
    """반대 방향 회귀 — 옮기다가 CLI 의 조용한 출력을 잃지 않았는가.

    기동 로그는 `start_flask_ui` 를 import 하는 **그 순간** 나오므로, 끄는
    자리가 `main()` 안이면 이미 늦다. `__main__` 가드 안에서, app import 보다
    먼저 꺼야 한다. 앱을 실제로 띄우지 않고 소스 구조로 확인한다.
    """

    def test_disable_is_guarded_and_precedes_app_import(self):
        with open(_HEALTH, encoding='utf-8') as fh:
            tree = ast.parse(fh.read())

        guard_line = app_import_line = None
        for node in tree.body:
            if (isinstance(node, ast.ImportFrom)
                    and node.module == 'aot.start_flask_ui'):
                app_import_line = node.lineno
            if (isinstance(node, ast.If)
                    and ast.unparse(node.test) == "__name__ == '__main__'"
                    and any('logging.disable' in ast.unparse(s) for s in node.body)):
                guard_line = node.lineno
            # 모듈 머리에 맨몸으로 남은 disable 은 없어야 한다.
            if isinstance(node, ast.Expr):
                self.assertNotIn('logging.disable', ast.unparse(node),
                                 '모듈 머리의 logging.disable 이 되살아났다')

        self.assertIsNotNone(guard_line, '__main__ 가드 안의 logging.disable 이 없다')
        self.assertIsNotNone(app_import_line)
        self.assertLess(guard_line, app_import_line,
                        'app import 뒤에서 끄면 기동 로그가 이미 찍힌 뒤다')


if __name__ == '__main__':
    unittest.main()
