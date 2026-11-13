# coding=utf-8
"""별칭 사용 집계(재설계 PR 9) — 옛 이름이 실제로 쓰인 호출만 센다."""
import json
import os
import sqlite3
import tempfile
import unittest

from aot.tools.domain import renames


class UsageTest(unittest.TestCase):

    def test_only_calls_that_used_an_old_name_are_counted(self):
        rows = [
            ('record', {'op': 'note_add', 'target': 'x', 'note': 'hi'}, '2026-11-04 01:00:00'),
            ('record', json.dumps({'op': 'note_add', 'target': 'x', 'text': 'hi'}), '2026-11-05 01:00:00'),
            ('record', {'op': 'note', 'target': 'x', 'text': 'new names'}, '2026-11-05 02:00:00'),
            ('control', {'op': 'function_on', 'target': 'f'}, '2026-11-06 00:00:00'),
            ('find', {'op': 'resolve', 'target': 'x'}, None),
            ('create_note', {'op': 'note_add'}, None),                 # 도메인 도구가 아니다
            ('record', '{broken', None),
        ]
        got = renames.usage(rows)
        self.assertEqual(2, got['record.note_add'][0])
        self.assertEqual('2026-11-05 01:00:00', got['record.note_add'][1])
        self.assertEqual(1, got['note'][0])                       # 전역 인자 별칭은 옛 이름 그대로
        self.assertEqual(1, got['control.function_on'][0])
        self.assertNotIn('record.note', got)
        self.assertNotIn('find.resolve', got)

    def test_names_match_the_removal_table(self):
        rows = [('record', {'op': 'note', 'target': 'x', 'name': 'T', 'text': 'hi'}, None)]
        self.assertIn('record.note(name)', renames.usage(rows))
        known = {r[0] for r in renames.rows()}
        for key in renames.usage([('record', {'op': 'note_add', 'name': 'T'}, None)]):
            self.assertIn(key, known)

    def test_nothing_old_means_an_empty_table(self):
        self.assertEqual({}, renames.usage([('find', {'op': 'devices'}, None)]))

    def test_the_script_reads_a_database_read_only_and_prints_the_table(self):
        import io
        from contextlib import redirect_stdout
        from aot.scripts import mcp_alias_usage
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE mcp_audit_log (id INTEGER PRIMARY KEY, tool_name TEXT, params_json TEXT, timestamp TEXT)")
            from aot.utils.timekit import naive_utc, utc_now
            now = naive_utc(utc_now()).strftime('%Y-%m-%d %H:%M:%S')
            con.execute("INSERT INTO mcp_audit_log (tool_name, params_json, timestamp) VALUES (?,?,?)",
                        ('remove', json.dumps({'op': 'plot_delete', 'target': 'p'}), now))
            con.execute("INSERT INTO mcp_audit_log (tool_name, params_json, timestamp) VALUES (?,?,?)",
                        ('remove', json.dumps({'op': 'plot_delete', 'target': 'p'}), '2020-01-01 00:00:00'))
            con.commit()
            con.close()
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = mcp_alias_usage.main(['--db', path, '--days', '14'])
            out = buf.getvalue()
            self.assertEqual(0, code)
            self.assertIn('remove.plot_delete', out)
            self.assertIn('1건', out)                                  # 2020 년 행은 기간 밖
            self.assertIn('쓰이는 이름이 남았다', out)
        finally:
            os.remove(path)

    def test_a_missing_database_is_reported_not_raised(self):
        from aot.scripts import mcp_alias_usage
        self.assertEqual(2, mcp_alias_usage.main(['--db', '/nonexistent/x.db']))


if __name__ == '__main__':
    unittest.main()
