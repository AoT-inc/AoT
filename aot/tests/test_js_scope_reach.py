# coding=utf-8
"""`check_js_scope_reach` — 바깥에서 안쪽 스코프의 이름을 부르는 것을 잡는가.

이 검사는 2026-09-06 의 실제 결함에서 나왔다. 5,500줄짜리 함수 안의 장치 모달을
IIFE 최상위로 끌어올렸는데 그것이 부르는 `_wireUpBtn` 은 아직 그 함수 안이었다 —
로드는 멀쩡하고 모달을 여는 순간 ReferenceError 가 났다. 그때 문법 검사·번들
빌드·정의 검사·전역 비교가 전부 통과했다.

여기서 지키는 것은 두 가지다:

  · 그 모양을 **잡는가** (안 잡으면 검사가 없는 것과 같다)
  · 멀쩡한 코드를 **안 잡는가** (오탐 나는 검사는 아무도 보지 않는다)
"""
import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, 'scripts', 'check_js_scope_reach.py')


def _load():
    spec = importlib.util.spec_from_file_location('check_js_scope_reach', _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestItCatchesTheRealShape(unittest.TestCase):
    """실제로 났던 결함의 모양."""

    def test_top_level_calling_an_inner_name_is_caught(self):
        m = _load()
        src = '\n'.join([
            '(function () {',
            "    'use strict';",
            '    function _renderBody(el) {',
            '        _wireUpBtn(el);',          # ← 안쪽에만 있는 이름
            '    }',
            '    function outer() {',
            '        function _wireUpBtn(el) { return el; }',
            '    }',
            '})();',
        ])
        hits = m._scan(m._mask(src))
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0]['name'], '_wireUpBtn')
        self.assertEqual(hits[0]['caller'], '_renderBody')

    def test_inner_calling_inner_is_fine(self):
        """안쪽에서 안쪽을 부르는 것은 정상이다 — 같은 스코프다."""
        m = _load()
        src = '\n'.join([
            '(function () {',
            '    function outer() {',
            '        function _a() { _b(); }',
            '        function _b() { return 1; }',
            '    }',
            '})();',
        ])
        self.assertEqual(m._scan(m._mask(src)), [])

    def test_top_calling_top_is_fine(self):
        m = _load()
        src = '\n'.join([
            '(function () {',
            '    function _a() { _b(); }',
            '    function _b() { return 1; }',
            '})();',
        ])
        self.assertEqual(m._scan(m._mask(src)), [])

    def test_a_name_defined_in_both_places_is_fine(self):
        """최상위에도 같은 이름이 있으면 그쪽이 잡히므로 위반이 아니다."""
        m = _load()
        src = '\n'.join([
            '(function () {',
            '    function _tr(s) { return s; }',
            '    function _a() { _tr("x"); }',
            '    function outer() {',
            '        function _tr(s) { return s; }',
            '    }',
            '})();',
        ])
        self.assertEqual(m._scan(m._mask(src)), [])


class TestItDoesNotCryWolf(unittest.TestCase):
    """오탐을 내지 않는다 — 실제로 이 검사를 처음 만들 때 밟은 함정들."""

    def test_a_regex_literal_does_not_swallow_the_file(self):
        """`.replace(/"/g, ...)` 의 따옴표를 문자열 시작으로 오인하면
        그 뒤 수백 줄이 통째로 지워지고, 멀쩡한 최상위 정의가 "없다" 가 된다.
        처음 만들 때 실제로 그래서 `_tr` 을 잘못 잡았다."""
        m = _load()
        src = '\n'.join([
            '(function () {',
            '    function _esc(s) {',
            '''        return String(s).replace(/"/g, '&quot;');''',
            '    }',
            '    function _a() { _esc("x"); }',
            '})();',
        ])
        masked = m._mask(src)
        self.assertEqual(len(masked.split('\n')), len(src.split('\n')))
        self.assertEqual(m._scan(masked), [])

    def test_multiline_comments_keep_the_line_count(self):
        """블록 주석이 개행을 삼키면 그 뒤 들여쓰기 판정이 전부 밀린다."""
        m = _load()
        src = '\n'.join([
            '(function () {',
            '    /* 여러',
            '       줄',
            '       주석 */',
            '    function _a() { return 1; }',
            '})();',
        ])
        masked = m._mask(src)
        self.assertEqual(len(masked.split('\n')), len(src.split('\n')))
        self.assertTrue(masked.split('\n')[4].startswith('    function _a'))

    def test_a_name_in_a_comment_is_not_a_call(self):
        m = _load()
        src = '\n'.join([
            '(function () {',
            '    function _a() {',
            '        // _wireUpBtn() 을 여기서 부르지 않는다',
            '        return 1;',
            '    }',
            '    function outer() {',
            '        function _wireUpBtn() { return 1; }',
            '    }',
            '})();',
        ])
        self.assertEqual(m._scan(m._mask(src)), [])

    def test_a_local_of_the_same_name_is_not_a_violation(self):
        m = _load()
        src = '\n'.join([
            '(function () {',
            '    function _a() {',
            '        function _helper() { return 1; }',
            '        return _helper();',
            '    }',
            '    function outer() {',
            '        function _helper() { return 2; }',
            '    }',
            '})();',
        ])
        self.assertEqual(m._scan(m._mask(src)), [])


class TestTheRepoIsClean(unittest.TestCase):
    def test_no_violation_anywhere(self):
        """지금 저장소에 위반이 없어야 한다 — 있으면 그 자체가 결함이다."""
        m = _load()
        problems, _n = m.run(staged=False)
        self.assertEqual(problems, [], '\n'.join(
            '%s:%d %s() → %s()' % (p['file'], p['line'], p['caller'], p['name'])
            for p in problems))


class TestTheHookRunsIt(unittest.TestCase):
    def test_the_hook_calls_the_checker(self):
        hook = os.path.join(os.path.dirname(_ROOT), '.githooks', 'pre-commit')
        if not os.path.exists(hook):
            self.skipTest('훅 파일이 없습니다')
        text = open(hook, encoding='utf-8').read()
        self.assertIn('check_js_scope_reach.py', text)

    def test_one_bypass_does_not_disable_the_others(self):
        """우회 변수는 자기 검사 하나만 꺼야 한다.

        예전에는 `AOT_SKIP_BUNDLE_CHECK` 가 훅 맨 앞에서 `exit 0` 을 해,
        번들 재빌드만 건너뛰려 해도 나머지 검사가 전부 함께 꺼졌다.
        """
        hook = os.path.join(os.path.dirname(_ROOT), '.githooks', 'pre-commit')
        if not os.path.exists(hook):
            self.skipTest('훅 파일이 없습니다')
        text = open(hook, encoding='utf-8').read()
        self.assertNotIn('if [ -n "$AOT_SKIP_BUNDLE_CHECK" ]; then\n    exit 0', text)


if __name__ == '__main__':
    unittest.main()
