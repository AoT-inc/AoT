# coding=utf-8
"""aot/utils/log_reader.py 회귀.

이 파일이 지키는 것 중 가장 중요한 것은 **셸 주입이 되살아나지 않는 것**이다.
예전 /logview 는 검색어를 `tail -n N file | grep "<search>"` 에 이어 붙여
`shell=True` 로 돌렸다 — `view_logs` 권한이 그대로 셸 실행 권한이었다.
읽기 경로에 셸이 다시 들어오면 그 사실이 실행 중에는 전혀 드러나지 않으므로
(로그는 멀쩡히 나온다) 소스를 AST 로도 함께 고정한다.
"""
import ast
import io
import os
import sys
import tempfile
import unittest

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.utils import log_reader  # noqa: E402


AOT_LINES = [
    '2026-08-17 10:00:00,001 - INFO - aot.aot_flask.app - app started',
    '2026-08-17 10:00:01,002 - INFO - aot.ai.services.ai_agent_service - agent ready',
    '2026-08-17 10:00:02,003 - ERROR - aot.ai.services.mcp_bridge_service - tool call failed',
    'Traceback (most recent call last):',
    '  File "x.py", line 1, in <module>',
    'ValueError: boom',
    '2026-08-17 10:00:03,004 - WARNING - aot.inputs.kma - No valid data found',
    '2026-08-17 10:00:04,005 - DEBUG - aot.aot_flask.app - PID Settings dump',
]


def _write(path, lines):
    with io.open(path, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')


class TestParsing(unittest.TestCase):
    def test_aot_format(self):
        entries = log_reader.parse_lines(AOT_LINES)
        self.assertEqual(entries[0]['level'], 'INFO')
        self.assertEqual(entries[0]['logger'], 'aot.aot_flask.app')
        self.assertEqual(entries[0]['message'], 'app started')

    def test_traceback_stays_one_entry(self):
        """이어지는 줄이 별도 항목이 되면 오류 하나가 네 줄로 세어져 화면의
        '오류 N건' 이 거짓말이 되고, AI 에 보낼 때도 트레이스백이 잘린다."""
        entries = log_reader.parse_lines(AOT_LINES)
        self.assertEqual(len(entries), 5)
        error = [e for e in entries if e['level'] == 'ERROR'][0]
        self.assertIn('ValueError: boom', error['raw'])
        self.assertIn('Traceback', error['message'])

    def test_mcp_format(self):
        """MCP 서버는 포맷이 다르다 (`asctime name levelname message`).
        한 포맷만 알면 MCP 로그는 레벨 없는 평문이 되어 필터가 통째로 죽는다."""
        entries = log_reader.parse_lines([
            '2026-08-17 10:00:00,001 aot.aot_mcp_server INFO server ready',
            '2026-08-17 10:00:01,002 aot.mcp_auth ERROR bad key',
        ])
        self.assertEqual([e['level'] for e in entries], ['INFO', 'ERROR'])
        self.assertEqual(entries[1]['logger'], 'aot.mcp_auth')

    def test_unstructured_line_keeps_content(self):
        entries = log_reader.parse_lines(
            ['2026-08-17 15:15:04+0900: NOUSER admin (NA), 93.152.221.90'])
        self.assertEqual(len(entries), 1)
        self.assertIn('93.152.221.90', entries[0]['raw'])


class TestFiltering(unittest.TestCase):
    def setUp(self):
        self.entries = log_reader.parse_lines(AOT_LINES)

    def test_min_level(self):
        out = log_reader.filter_entries(self.entries, min_level='WARNING')
        self.assertEqual([e['level'] for e in out], ['ERROR', 'WARNING'])

    def test_logger_prefix_matches_subtree_only(self):
        """'aot.ai' 접두사가 'aot.aiXyz' 같은 남의 로거를 끌어오면 AI 소스에
        엉뚱한 줄이 섞인다. 점 경계에서만 일치해야 한다."""
        entries = log_reader.parse_lines([
            '2026-08-17 10:00:00,001 - INFO - aot.ai - a',
            '2026-08-17 10:00:00,002 - INFO - aot.ai.services.x - b',
            '2026-08-17 10:00:00,003 - INFO - aot.airflow - c',
        ])
        out = log_reader.filter_entries(entries, logger_prefixes=('aot.ai',))
        self.assertEqual([e['message'] for e in out], ['a', 'b'])

    def test_search_is_case_insensitive_substring(self):
        out = log_reader.filter_entries(self.entries, search='TOOL CALL')
        self.assertEqual(len(out), 1)

    def test_search_is_not_a_shell_fragment(self):
        """예전 구현에서 셸로 넘어가던 문자열이 여기서는 그냥 리터럴이다."""
        out = log_reader.filter_entries(self.entries, search='"; touch /tmp/x #')
        self.assertEqual(out, [])


class TestFileReading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'test.log')
        _write(self.path, AOT_LINES)

    def test_scan_widens_until_filter_matches(self):
        """마지막 N줄만 읽고 거르면, 필터에 걸리는 줄이 그 창 밖에 있을 때
        결과가 빈다 — 'AI 로그가 아무것도 없다' 로 보이는 실패다."""
        noise = ['2026-08-17 11:00:{:02d},000 - INFO - aot.other - x{}'.format(
            i % 60, i) for i in range(20000)]
        _write(self.path, [AOT_LINES[2]] + noise)

        entries, offset, truncated = log_reader._scan_backwards(
            self.path, 50, '', '', ('aot.ai',), None)
        self.assertEqual(len(entries), 1)
        self.assertIn('tool call failed', entries[0]['raw'])
        self.assertEqual(offset, os.path.getsize(self.path))
        self.assertFalse(truncated)

    def test_incremental_returns_only_new_bytes(self):
        _, end_offset, _ = log_reader._scan_backwards(
            self.path, 100, '', '', None, None)
        with io.open(self.path, 'a', encoding='utf-8') as handle:
            handle.write(
                '2026-08-17 10:00:05,006 - ERROR - aot.ai.x - later\n')

        text, new_offset = log_reader._read_incremental(self.path, end_offset)
        self.assertIn('later', text)
        self.assertNotIn('app started', text)
        self.assertGreater(new_offset, end_offset)

    def test_incremental_gives_up_after_rotation(self):
        """로테이션되면 옛 오프셋은 남의 파일 위치를 가리킨다. 그대로 읽으면
        조용히 엉뚱한 구간을 붙이므로 None(→ 전체 tail 폴백)이어야 한다."""
        self.assertIsNone(log_reader._read_incremental(self.path, 10 ** 9))

    def test_reads_rotated_file_when_window_reaches_start(self):
        _write(self.path + '.1', ['2026-08-17 09:00:00,000 - INFO - aot.x - old line'])
        text, _, _ = log_reader._tail_text(self.path, 1024 * 1024)
        self.assertIn('old line', text)
        self.assertIn('app started', text)


class TestReadLog(unittest.TestCase):
    def test_unknown_source_is_reported_not_raised(self):
        result = log_reader.read_log('does-not-exist')
        self.assertFalse(result['available'])
        self.assertTrue(result['error'])
        self.assertEqual(result['entries'], [])

    def test_every_registered_source_is_readable(self):
        """소스를 추가하고 정의를 어긋나게 쓰면(경로 오타, kind 누락) 화면에서만
        빈 로그로 보인다. 여기서 전부 한 번씩 읽어 예외가 없음을 고정한다."""
        for source in log_reader.list_sources():
            result = log_reader.read_log(source['id'], lines=5)
            self.assertEqual(result['source'], source['id'])
            self.assertIsInstance(result['entries'], list)

    def test_line_count_is_capped(self):
        result = log_reader.read_log('daemon', lines=10 ** 9)
        self.assertLessEqual(len(result['entries']), log_reader._MAX_LINES)


class TestNoShellInReadPath(unittest.TestCase):
    """소스를 AST 로 훑어 셸 실행이 되살아나지 않았는지 본다."""

    def _tree(self):
        path = os.path.join(os.path.dirname(log_reader.__file__),
                            'log_reader.py')
        with io.open(path, encoding='utf-8') as handle:
            return ast.parse(handle.read())

    def test_no_shell_true(self):
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.keyword) and node.arg == 'shell':
                self.assertIsInstance(node.value, ast.Constant)
                self.assertFalse(node.value.value,
                                 'log_reader must never run a shell')

    def test_no_os_system_or_popen(self):
        banned = {'system', 'popen', 'getoutput', 'check_output'}
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(
                    node.func.attr, banned,
                    'log_reader must not shell out ({})'.format(node.func.attr))

    def test_command_argv_has_no_user_input(self):
        """명령 소스의 argv 는 전부 리터럴이거나 {lines} 자리표시자여야 한다.
        검색어가 여기 끼어드는 순간 주입이 되돌아온다."""
        for spec in log_reader._build_registry().all():
            if spec['kind'] != 'command':
                continue
            for arg in spec['argv']:
                self.assertIsInstance(arg, str)
            self.assertEqual(spec['argv'].count('{lines}'), 1)


if __name__ == '__main__':
    unittest.main()
