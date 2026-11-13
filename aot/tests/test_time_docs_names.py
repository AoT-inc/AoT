# coding=utf-8
"""문서의 시간 입구 이름이 코드와 어긋나지 않는지 — 양방향.

`ARCHITECTURE.md` §6 은 모든 세션이 따르는 요약이다. 거기 적힌 이름이 `timekit` 에
없으면 하위 세션이 존재하지 않는 함수를 부르게 되고, 입구를 추가하고 문서를 안
고치면 새 입구가 영영 알려지지 않는다. `ARCHITECTURE.md` §4 의존 방향이 검사기로
지켜지는 것과 같은 구조다.

`CLAUDE.md` 는 비공개 저장소에만 있다(공개 저장소로 나가지 않는다) — 파일이 있을 때만 본다.
"""
import os
import re
import unittest

from aot.utils import timekit

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MARKERS = {'FARM', 'VIEWER'}                 # 함수가 아니라 where 표식
_FUNCTIONS = set(timekit.PUBLIC_ENTRIES) - _MARKERS
_CALL = re.compile(r'`([a-z_]+)\(')


def _read(name):
    path = os.path.join(_ROOT, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def architecture_time_section(text):
    start = text.index('## 6. Time')
    nxt = re.search(r'^## ', text[start + 3:], re.M)
    return text[start:start + 3 + nxt.start()] if nxt else text[start:]


class TestArchitectureTimeSection(unittest.TestCase):

    def setUp(self):
        text = _read('ARCHITECTURE.md')
        self.assertIsNotNone(text, 'ARCHITECTURE.md 가 없습니다')
        self.section = architecture_time_section(text)

    def test_names_match_the_public_entries_both_ways(self):
        named = set(_CALL.findall(self.section))
        self.assertEqual(
            named, _FUNCTIONS,
            '문서에만 있는 이름: %s / 문서에 빠진 입구: %s — ARCHITECTURE.md §6 과 '
            'timekit.PUBLIC_ENTRIES 를 맞추세요' % (sorted(named - _FUNCTIONS),
                                                  sorted(_FUNCTIONS - named)))

    def test_markers_are_documented_and_real(self):
        for name in _MARKERS:
            self.assertIn('`%s`' % name, self.section)
            self.assertTrue(hasattr(timekit, name))

    def test_documented_names_exist_in_timekit(self):
        for name in _CALL.findall(self.section):
            self.assertTrue(callable(getattr(timekit, name, None)), name)

    def test_points_at_the_guard_and_the_design(self):
        self.assertIn('aot/scripts/check_time_rules.py', self.section)
        self.assertIn('docs/design/timezone-management.md', self.section)
        guard = os.path.join(_ROOT, 'aot', 'scripts', 'check_time_rules.py')
        self.assertTrue(os.path.exists(guard))


class TestClaudeMdTimeRules(unittest.TestCase):

    def test_new_entry_bullets_name_real_entries(self):
        text = _read('CLAUDE.md')
        if text is None:
            self.skipTest('CLAUDE.md 는 비공개 저장소에만 있다')
        start = text.index('시간·날짜는')           # 축약된 CLAUDE.md(필수 프로젝트 규칙)의 시간 규칙
        block = text[start:]
        allowed = block[:block.index('금지:')]      # 금지 목록 앞까지가 '써야 할 것'
        named = set(_CALL.findall(allowed))
        self.assertTrue(named, '입구 이름을 찾지 못했습니다')
        self.assertFalse(named - _FUNCTIONS,
                         'CLAUDE.md 시간 규칙에 timekit 에 없는 이름: %s' % sorted(named - _FUNCTIONS))
        self.assertEqual(_FUNCTIONS - named, set(),
                         'CLAUDE.md 시간 규칙에 빠진 입구: %s' % sorted(_FUNCTIONS - named))


if __name__ == '__main__':
    unittest.main()
