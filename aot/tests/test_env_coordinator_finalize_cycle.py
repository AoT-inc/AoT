# coding=utf-8
"""
사이클 꼬리(`_finalize_cycle`)가 사이클 길이를 넘겨받는가 — 2026-09-28 회귀 고정.

2026-08-04 `f0464ca2c` 가 `_run_cycle`(727줄)을 쪼개며 꼬리 작업을 옮겼는데
`cycle_sec` 하나를 넘기지 않았다. 그 함수 안 네 곳이 정의되지 않은 이름을
참조했고, greybox 그림자 단계가 매 사이클 `NameError` 로 죽었다.

예외는 `except Exception` 이 **debug 로 삼켰고**, 기본 설치는 debug 를 남기지
않아(로그 파일에 DEBUG 가 한 줄도 없다) 8주 동안 아무도 몰랐다. 그 사이
1스텝 예측·오차 기록, 기상 구간별 KPI, 물리 모델 재학습이 전부 멈췄다 —
즉 "물리 모델로 제어를 전환해도 되는가" 의 판정 근거가 쌓일 수 없었다.

앱은 정상 기동하고, 테스트는 통과하고, 화면에도 이상이 없었다. 그래서 이
계열은 **실행해 보는 것만으로는 안 잡힌다** — 두 축으로 고정한다.
"""

import ast
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_CYCLE_MIXIN = os.path.join(
    _REPO, 'aot', 'functions', 'custom_functions', 'env_coordinator_impl',
    '_cycle_mixin.py')


def _source():
    with open(_CYCLE_MIXIN, 'r', encoding='utf-8') as f:
        return f.read()


class TestCycleSecReachesTheTail(unittest.TestCase):
    """축 1 — 꼬리가 값을 받는가(소스 고정)."""

    def test_컨텍스트가_사이클_길이를_싣는다(self):
        tree = ast.parse(_source())
        ctx = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == '_CycleContext')
        fields = {t.target.id for t in ctx.body if isinstance(t, ast.AnnAssign)}
        self.assertIn('cycle_sec', fields,
                      '_CycleContext 에 cycle_sec 이 없으면 꼬리 작업이 이름을 잃는다')

    def test_호출부가_넘기고_꼬리가_되살린다(self):
        src = _source()
        self.assertIn('cycle_sec=cycle_sec,', src)
        self.assertIn('cycle_sec = ctx.cycle_sec', src)

    def test_꼬리에서_쓰는_이름이_전부_정의돼_있다(self):
        """이 파일에 정의되지 않은 이름이 없어야 한다(원 결함 그대로)."""
        import subprocess
        import sys
        script = os.path.join(_REPO, 'aot', 'scripts', 'check_undefined_names.py')
        if not os.path.exists(script):
            self.skipTest('check_undefined_names.py 없음')
        proc = subprocess.run(
            [sys.executable, script, os.path.relpath(_CYCLE_MIXIN, _REPO)],
            cwd=_REPO, capture_output=True, text=True)
        if proc.returncode == 2:
            self.skipTest('pyflakes 미설치 — 검사 불가')
        self.assertEqual(0, proc.returncode,
                         '정의되지 않은 이름:\n%s' % proc.stdout)


class TestFailureIsNotSwallowedForever(unittest.TestCase):
    """축 2 — 같은 실패가 이어지면 **말한다**(동작 고정)."""

    def _mixin(self):
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
            CycleMixin)
        c = CycleMixin.__new__(CycleMixin)

        class _Log:
            def __init__(self):
                self.errors = []
                self.debugs = []

            def error(self, msg, *a, **k):
                self.errors.append(msg % a if a else msg)

            def debug(self, msg, *a, **k):
                self.debugs.append(msg % a if a else msg)

        c.logger = _Log()
        return c

    def test_단발은_조용하다(self):
        c = self._mixin()
        c._note_greybox_shadow_failure(RuntimeError('한 번'))
        self.assertEqual([], c.logger.errors)
        self.assertEqual(1, len(c.logger.debugs))

    def test_이어지면_말한다(self):
        c = self._mixin()
        for _ in range(c._GB_SHADOW_FAIL_SPEAK):
            c._note_greybox_shadow_failure(RuntimeError('계속'))
        self.assertEqual(1, len(c.logger.errors),
                         '%d사이클 연속이면 한 줄은 남아야 한다' % c._GB_SHADOW_FAIL_SPEAK)
        self.assertIn('greybox', c.logger.errors[0])

    def test_말한_뒤에는_가끔만_반복한다(self):
        """매 사이클 찍으면 로그가 밀려 정작 읽어야 할 것이 사라진다."""
        c = self._mixin()
        for _ in range(c._GB_SHADOW_FAIL_REPEAT * 2 + 5):
            c._note_greybox_shadow_failure(RuntimeError('계속'))
        self.assertGreaterEqual(len(c.logger.errors), 2)
        self.assertLessEqual(len(c.logger.errors), 4)

    def test_성공하면_다시_센다(self):
        """복구 뒤 다시 실패했을 때 예전 횟수가 남아 곧장 ERROR 가 되면 안 된다."""
        c = self._mixin()
        c._note_greybox_shadow_failure(RuntimeError('한 번'))
        c._gb_shadow_fail_n = 0            # 그림자 성공 시 호출부가 하는 일
        c._note_greybox_shadow_failure(RuntimeError('다시'))
        self.assertEqual([], c.logger.errors)


if __name__ == '__main__':
    unittest.main()
