# coding=utf-8
"""느린 읽기 도중의 "조회 중" 자막 (2026-10-26) — screen_follow.slow_read_notice.

말없이 일하는 AI 가 고장으로 보이지 않게, 서버가 느린 읽기 중에 보이는 화면 하나에 일회성 자막(`toast` 명령 → 자막)을
띄운다. 카드가 아니다(수신함에 쌓이지 않고 AI 가 따라야 하지도 않는다). 빨리 끝나는 조회는 아무것도 보이지 않는다.
"""
import time
import unittest
from unittest import mock

from aot.tools import screen_follow as sf


class _Env:
    """DB·화면 없이 돌리는 가짜 환경."""

    def __init__(self, visible=True, confirmed=True, ask=False, recent=0, picked=True, eligible=True):
        self.commands = []
        self.visible, self.confirmed, self.ask = visible, confirmed, ask
        self.recent, self.picked, self.eligible = recent, picked, eligible

    def patches(self):
        from aot.utils import web_presence as wp
        target = {'browser_key': 'bk', 'device': 'Mac'}
        return [
            mock.patch.object(sf, 'eligible', return_value=self.eligible),
            mock.patch.object(sf, '_pick_screen',
                              return_value=((target, self.visible), None) if self.picked else (None, None)),
            mock.patch.object(sf, '_slow_message', return_value='AI is looking this up…'),
            mock.patch.object(wp, 'follow_mode', return_value='ask' if self.ask else 'auto'),
            mock.patch.object(wp, 'auto_confirmed', return_value=self.confirmed),
            mock.patch.object(wp, 'has_grant', return_value=False),
            mock.patch.object(wp, 'recent_command_count', return_value=self.recent),
            mock.patch.object(wp, 'add_command',
                              side_effect=lambda *a, **k: self.commands.append((a, k)) or ('c1', None)),
            mock.patch.object(sf, 'SLOW_NOTICE_FIRST_S', 0.05),
            mock.patch.object(sf, 'SLOW_NOTICE_EVERY_S', 0.6),
        ]

    def run(self, work_s, tool='weather', permission='read', transport='mcp_http', user='u1', show=None):
        sf._SLOW_NOTICE_LAST.clear()
        stack = self.patches()
        for p in stack:
            p.start()
        try:
            with sf.slow_read_notice(object(), tool, permission, user, 'operations', transport, show):
                time.sleep(work_s)
            time.sleep(0.05)
        finally:
            for p in stack:
                p.stop()
        return self.commands


class SlowReadNoticeTest(unittest.TestCase):

    def test_a_fast_read_shows_nothing(self):
        env = _Env()
        self.assertEqual([], env.run(0.0))

    def test_a_slow_read_gets_one_transient_subtitle_not_a_card(self):
        env = _Env()
        cmds = env.run(0.3)
        self.assertEqual(1, len(cmds))
        args, kw = cmds[0]
        self.assertEqual('toast', args[2])                      # 옛 toast 명령 → 화면의 자막(notice)
        self.assertEqual({'message': 'AI is looking this up…', 'describe': 'show a status line'}, args[3])
        self.assertIs(kw['confirmed'], True)
        self.assertEqual('follow', kw['source'])
        self.assertLessEqual(kw['ttl_s'], 30)                    # 늦게 켜진 화면에 낡은 안내가 뜨지 않는다

    def test_a_long_wait_repeats_because_the_subtitle_fades_but_stops_at_the_cap(self):
        env = _Env()
        cmds = env.run(2.6)                                      # 0.05 + 0.6 간격 → 4번이 상한
        self.assertEqual(sf.SLOW_NOTICE_MAX, len(cmds))

    def test_the_notice_stops_when_the_read_finishes(self):
        env = _Env()
        env.run(0.3)
        n = len(env.commands)
        time.sleep(0.8)                                           # 끝난 뒤에는 타이머가 다시 울리지 않는다
        self.assertEqual(n, len(env.commands))

    def test_only_external_reads_that_are_not_screen_tools(self):
        for kw in (dict(permission='write'), dict(transport='internal'), dict(user=None),
                   dict(tool='screen_action'), dict(tool='screen'), dict(show='off')):
            with self.subTest(**kw):
                self.assertEqual([], _Env().run(0.3, **kw))

    def test_quiet_when_the_screen_cannot_show_it(self):
        for env in (_Env(visible=False), _Env(picked=False), _Env(eligible=False)):
            self.assertEqual([], env.run(0.3))
        # 안내 때문에 [허용] 카드를 띄우거나 명령 한도를 먹지 않는다
        self.assertEqual([], _Env(confirmed=False).run(0.3))
        self.assertEqual([], _Env(ask=True).run(0.3))
        self.assertEqual([], _Env(recent=sf.SLOW_NOTICE_ROOM).run(0.3))

    def test_parallel_slow_reads_of_one_question_do_not_stack_subtitles(self):
        env = _Env()
        for p in env.patches():
            p.start()
        self.addCleanup(mock.patch.stopall)
        sf._SLOW_NOTICE_LAST.clear()
        with sf.slow_read_notice(object(), 'weather', 'read', 'u1', 'operations', 'mcp_http'), \
                sf.slow_read_notice(object(), 'measure', 'read', 'u1', 'operations', 'mcp_http'):
            time.sleep(0.3)
        self.assertEqual(1, len(env.commands))

    def test_errors_in_the_notice_never_break_the_read(self):
        env = _Env()
        stack = env.patches() + [mock.patch.object(sf, '_send_slow_notice', side_effect=RuntimeError('boom'))]
        for p in stack:
            p.start()
        self.addCleanup(mock.patch.stopall)
        with sf.slow_read_notice(object(), 'weather', 'read', 'u1', 'operations', 'mcp_http'):
            time.sleep(0.2)
            result = 'ok'
        self.assertEqual('ok', result)


class WiringTest(unittest.TestCase):
    def test_the_domain_frame_wraps_the_call_with_the_agents_own_show_option(self):
        """안쪽 호출은 `_show_on_screen=off` 로 돌아 스스로는 자막을 걸지 않는다 — 틀이 AI 가 준 값으로 한 번 건다."""
        import inspect
        from aot.tools.domain import dispatch
        src = inspect.getsource(dispatch._run_call)
        self.assertIn('slow_read_notice', src)
        self.assertLess(src.index('pop_show_arg'), src.index('slow_read_notice'))
        self.assertIn('_run_call_inner', src)

    def test_the_direct_tool_path_is_wrapped_too(self):
        import inspect
        from aot.tools import tool_execution as te
        self.assertIn('slow_read_notice(app, tool_name, permission', inspect.getsource(te._execute_tool))

    def test_the_message_is_translated_for_korean_and_japanese(self):
        import gettext
        import os
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'aot_flask', 'translations')
        want = {'ko': 'AI가 조회하는 중…', 'ja': 'AIが調べています…'}
        for lang, text in want.items():
            with open(os.path.join(base, lang, 'LC_MESSAGES', 'messages.mo'), 'rb') as fh:
                self.assertEqual(text, gettext.GNUTranslations(fh).gettext('AI is looking this up…'), lang)


if __name__ == '__main__':
    unittest.main()
