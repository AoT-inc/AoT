# coding=utf-8
"""노트에는 **대상 자신의 태그**가 붙어야 한다.

노트 페이지는 태그로 묶고 태그로 찾는다(`note_item.html` 의 `#태그` 칩, 없으면
'태그 없음'). 대상이 있는 노트에 그 대상의 태그가 없으면 어느 묶음에도 들어가지
못한다 — 만든 사람은 그 구획을 보면서 적었는데 나중에 그 구획에서 찾을 수 없다.

예전에는 태그를 **클라이언트가 보내 줄 때만** 붙였다. 지도 위젯의 작성기는
보내지만 AI 도구(`create_note`)와 서버 경로는 안 보내서, 실측으로 구획 노트 넷이
태그 없이 남아 있었다(2026-08-24). 규칙을 서버 한 곳에 두면 새 작성 경로가 생겨도
따라온다.
"""
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..')


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


class TestEveryCreatePathEnsuresTheTargetTag(unittest.TestCase):

    def test_the_rule_lives_in_one_place(self):
        src = _read('aot_flask', 'utils', 'utils_notes.py')
        self.assertIn('def ensure_target_tag(', src)
        body = src.split('def ensure_target_tag(', 1)[1].split('\ndef ', 1)[0]
        # 이름을 못 찾으면 아무것도 하지 않는다 — uuid 를 태그로 만들면 사람이
        # 못 읽는 칩이 목록에 쌓이고, 그것은 태그가 없는 것보다 나쁘다.
        self.assertIn('if not name:', body)
        # 이미 있는 태그는 다시 만들지 않는다(중복 칩).
        self.assertIn('if tag.unique_id not in ids:', body)

    def test_the_widget_api_path_is_wired(self):
        src = _read('aot_flask', 'routes_notes_api.py')
        self.assertIn('utils_notes.ensure_target_tag(', src)
        self.assertIn('tags=tags_csv,', src)

    def test_the_ai_tool_path_is_wired(self):
        """AI 는 태그를 주지 않는 것이 보통이다 — 여기가 빠지면 그 노트만 조용히
        태그 없이 남는다."""
        src = _read('..', 'aot', 'ai', 'services', 'aot_data_tool_service.py')
        create = src.split('def create_note(', 1)[1].split('\n    def ', 1)[0]
        self.assertIn('ensure_target_tag(', create)
        self.assertNotIn("tags=tags or ''", create,
                         '클라이언트가 준 태그를 그대로 쓰면 대상 태그가 빠진다')

    def test_the_resolver_covers_every_target_kind(self):
        """도형·구획·시설·장치가 각각 다른 테이블이라 한 곳에서 훑는다 —
        부르는 자리마다 따로 찾으면 어느 한 종류가 조용히 빠진다."""
        src = _read('aot_flask', 'routes_notes_api.py')
        body = src.split('def _display_name_for_target(', 1)[1].split('\ndef ', 1)[0]
        for model in ('GeoShape', 'GeoPlot', 'GeoFacility', 'Input', 'Output'):
            self.assertIn(model, body, '%s 가 리졸버에 없다' % model)


if __name__ == '__main__':
    unittest.main()
