# coding=utf-8
"""달력 소스 통합 — 노트·공지 provider 와 자동 실행 기본 숨김.

배경: 노트·일정·공지는 서로 다른 정보가 아니다. 같은 것(문장 + 어디 + 언제)에
붙은 세 개의 **저장 위치**이고, 경계는 실제 데이터에서 양방향으로 새고 있다
(`SchedulerJobMeta.action_type='note'` · `Notes.category='schedule'`).
그래서 읽기는 한 화면에서 시간축으로 합친다.

다만 **기계가 남긴 실행 기록은 섞지 않는다** — 323건 중 249건(77%)이
`automated_fire` 라, 사람이 쓴 것이 그 속에 묻힌다.
계획서: .local/reports/notes-schedule-notice-ia-20260818.md
"""
import os
import unittest

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, '..')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class TestProvidersAreRegistered(unittest.TestCase):
    """주석으로만 있던 확장점을 실제로 채웠는가.

    원래 모듈이 "a toggle for a source with no registered provider is dead UI"
    라고 짝을 못박아 두었다 — provider 와 위젯 토글은 함께 와야 한다.
    """

    def _src(self):
        return _read(os.path.join(_ROOT, 'utils', 'calendar_event_providers.py'))

    def test_three_sources_registered(self):
        from aot.utils.calendar_event_providers import CALENDAR_EVENT_PROVIDERS
        self.assertEqual(sorted(CALENDAR_EVENT_PROVIDERS), ['note', 'notice', 'schedule'])

    def test_no_stub_left(self):
        src = self._src()
        self.assertNotIn('raise NotImplementedError', src)
        self.assertIn('def provide_note_events', src)
        self.assertIn('def provide_notice_events', src)

    def test_widget_has_a_toggle_per_source(self):
        w = _read(os.path.join(_ROOT, '..', 'aot', 'widgets', 'widget_calendar.py'))
        for opt in ("'include_schedule'", "'include_note'", "'include_notice'"):
            self.assertIn(opt, w)

    def test_bucket_filter_excludes_other_sources(self):
        """`category` 는 버킷 필터다 — 안 지키면 "사용자 일정만" 을 골라도
        노트·공지가 따라 나온다."""
        src = self._src()
        for fn in ('provide_note_events', 'provide_notice_events'):
            body = src.split('def %s' % fn, 1)[1].split('\ndef ', 1)[0]
            self.assertIn('if category and category !=', body)

    def test_read_only_from_the_calendar(self):
        """노트·공지 편집은 각자의 UI 계약(공용 노트 블록 / 게시기간·읽음)을
        지나야 한다 — 달력에서 고치게 하면 두 번째 경로가 생긴다."""
        src = self._src()
        for fn in ('provide_note_events', 'provide_notice_events'):
            body = src.split('def %s' % fn, 1)[1].split('\ndef ', 1)[0]
            self.assertIn("'rowEditable': False", body)
            self.assertIn("'rowDeletable': False", body)


class TestAutomatedRecordsHiddenByDefault(unittest.TestCase):
    """자동 실행 기록은 기본으로 숨긴다 — 다만 **말하고** 숨긴다."""

    def _src(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'routes_scheduler.py'))

    def test_page_hides_them(self):
        body = self._src().split('def page_scheduler', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("action_type != 'automated_fire'", body)
        self.assertIn('show_automated', body)

    def test_timeline_uses_the_same_default(self):
        """목록에서 숨긴 것이 달력에는 뜨면 두 화면이 다른 말을 한다."""
        body = self._src().split('def api_timeline_events', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("action_type != 'automated_fire'", body)

    def test_hidden_count_is_shown(self):
        """말없이 빼면 "일정이 사라졌다" 로 읽힌다."""
        body = self._src().split('def page_scheduler', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('automated_count', body)
        tpl = _read(os.path.join(_ROOT, 'aot_flask', 'templates', 'pages',
                                 'ai', 'scheduler.html'))
        self.assertIn('automated_count', tpl)
        self.assertIn('show_automated', tpl)

    def test_widget_default_excludes_automated(self):
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                'widget_calendar', 'aot-calendar-widget.js'))
        self.assertIn('AOT_DEFAULT_BUCKETS', js)
        block = js.split('AOT_DEFAULT_BUCKETS =', 1)[1][:120]
        self.assertNotIn("'ai'", block)

    def test_picker_lists_people_first(self):
        """기계가 남긴 것(249건)이 목록 맨 위를 차지하면 사람 글이 묻힌다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'routes_integrations.py'))
        body = src.split('def api_available_calendars', 1)[1].split('\ndef ', 1)[0]
        self.assertLess(body.index("'key': 'user'"), body.index("'key': 'ai'"))
        self.assertLess(body.index("'key': 'note'"), body.index("'key': 'ai'"))


if __name__ == '__main__':
    unittest.main()
