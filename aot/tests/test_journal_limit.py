# coding=utf-8
"""systemd 저널 상한(journal_limit).

실제 /etc 와 journald 는 건드리지 않는다 — 설정 경로를 임시 폴더로 돌리고
subprocess 를 가짜로 바꾼다. 확인하는 것은 세 가지다.

1. 사람이 직접 정한 값을 덮어쓰지 않는다 (기본값 적용도, 웹의 변경도).
2. 범위 밖·문자열 값은 파일을 쓰기 전에 거절한다.
3. 웹(비특권)이 /etc 를 직접 쓰는 경로가 없다 — 쓰기는 데몬 RPC 를 지난다.
"""
import ast
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from aot.utils import journal_limit as jl

_ROOT = os.path.join(os.path.dirname(__file__), '..')


class _Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf_dir = os.path.join(self.tmp.name, 'journald.conf.d')
        self.main = os.path.join(self.tmp.name, 'journald.conf')
        self.own = os.path.join(self.conf_dir, 'aot.conf')
        self.calls = []

        def fake_run(cmd, **kwargs):
            self.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

        for target, value in (('CONF_DIR', self.conf_dir),
                              ('MAIN_CONF', self.main),
                              ('CONF_PATH', self.own)):
            patcher = mock.patch.object(jl, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (mock.patch.object(jl, 'supported', return_value=True),
                        mock.patch.object(jl.subprocess, 'run', fake_run)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)


class TestParseSize(unittest.TestCase):

    def test_units(self):
        self.assertEqual(jl.parse_size_mb('500M'), 500)
        self.assertEqual(jl.parse_size_mb('1G'), 1024)
        self.assertAlmostEqual(jl.parse_size_mb('3.9G'), 3993.6)
        self.assertEqual(jl.parse_size_mb('1048576'), 1)  # 바이트

    def test_garbage_is_none(self):
        self.assertIsNone(jl.parse_size_mb('abc'))
        self.assertIsNone(jl.parse_size_mb(''))
        self.assertIsNone(jl.parse_size_mb(None))


class TestValidate(unittest.TestCase):

    def test_accepts_range(self):
        self.assertEqual(jl.validate_mb('500'), 500)
        self.assertEqual(jl.validate_mb(jl.MIN_MB), jl.MIN_MB)
        self.assertEqual(jl.validate_mb(jl.MAX_MB), jl.MAX_MB)

    def test_rejects_outside_range_and_non_integers(self):
        for bad in (jl.MIN_MB - 1, jl.MAX_MB + 1, 0, -5, '', 'abc', '5e2',
                    '500; rm -rf /', None, True):
            with self.assertRaises((ValueError, TypeError), msg=repr(bad)):
                jl.validate_mb(bad)


class TestApply(_Base):

    def test_writes_conf_then_restarts_and_vacuums(self):
        ok, _ = jl.apply(500)
        self.assertTrue(ok)
        with open(self.own) as f:
            self.assertIn('SystemMaxUse=500M', f.read())
        self.assertEqual(self.calls[0], ['systemctl', 'restart', 'systemd-journald'])
        self.assertEqual(self.calls[1], ['journalctl', '--vacuum-size=500M'])

    def test_invalid_value_touches_nothing(self):
        ok, _ = jl.apply('9999999')
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.own))
        self.assertEqual(self.calls, [])

    def test_does_not_override_a_value_set_by_a_person(self):
        self.write(self.main, '[Journal]\nSystemMaxUse=2G\n')
        ok, message = jl.apply(500)
        self.assertFalse(ok)
        self.assertIn('managed elsewhere', message)
        self.assertFalse(os.path.exists(self.own))

    def test_commented_default_is_not_a_setting(self):
        """배포판 기본 journald.conf 는 값이 주석이다 — 그것을 '설정됨' 으로 읽으면 안 된다."""
        self.write(self.main, '[Journal]\n#SystemMaxUse=\n')
        ok, _ = jl.apply(300)
        self.assertTrue(ok)

    def test_failed_apply_step_is_reported_not_raised(self):
        def failing(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='boom')
        with mock.patch.object(jl.subprocess, 'run', failing):
            ok, message = jl.apply(500)
        self.assertFalse(ok)
        self.assertIn('saved', message)
        self.assertTrue(os.path.exists(self.own))  # 파일은 써졌다 — 다음 재시작에 적용


class TestEnsureDefault(_Base):

    def test_sets_default_when_nothing_is_set(self):
        self.assertTrue(jl.ensure_default())
        self.assertEqual(jl.effective_setting()[0], jl.DEFAULT_MB)

    def test_keeps_our_own_value(self):
        jl.apply(800)
        self.calls.clear()
        self.assertFalse(jl.ensure_default())
        self.assertEqual(jl.effective_setting()[0], 800)
        self.assertEqual(self.calls, [])

    def test_keeps_a_value_set_by_a_person(self):
        self.write(os.path.join(self.conf_dir, 'zz-mine.conf'),
                   '[Journal]\nSystemMaxUse=1G\n')
        self.assertFalse(jl.ensure_default())
        self.assertFalse(os.path.exists(self.own))

    def test_unsupported_environment_is_a_noop(self):
        with mock.patch.object(jl, 'supported', return_value=False):
            self.assertFalse(jl.ensure_default())
        self.assertFalse(os.path.exists(self.own))


class TestReadState(_Base):

    def test_reports_own_limit_as_editable(self):
        jl.apply(500)
        with mock.patch.object(jl, 'disk_usage_mb', return_value=123.0):
            state = jl.read_state()
        self.assertEqual(state['limit_mb'], 500)
        self.assertFalse(state['managed_elsewhere'])
        self.assertEqual(state['usage_mb'], 123.0)

    def test_foreign_limit_is_not_editable(self):
        self.write(self.main, '[Journal]\nSystemMaxUse=1G\n')
        with mock.patch.object(jl, 'disk_usage_mb', return_value=None):
            state = jl.read_state()
        self.assertTrue(state['managed_elsewhere'])
        self.assertEqual(state['limit_mb'], 1024)

    def test_unsupported(self):
        with mock.patch.object(jl, 'supported', return_value=False):
            self.assertEqual(jl.read_state(), {'supported': False})


class TestWiring(unittest.TestCase):
    """소스로 고정하는 배선 — 화면은 권한이 없는 프로세스에서 돈다."""

    def _read(self, rel):
        with open(os.path.join(_ROOT, rel), encoding='utf-8') as f:
            return f.read()

    def test_web_route_never_writes_etc_directly(self):
        tree = ast.parse(self._read('aot_flask/routes_page.py'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == 'apply':
                owner = getattr(node.value, 'id', '')
                self.assertNotEqual(owner, 'journal_limit',
                                    'routes_page 가 journal_limit.apply 를 직접 부른다 — '
                                    '비특권 프로세스라 실패하거나 권한 상승 경로가 된다. '
                                    '데몬 RPC(journal_limit_apply)를 쓸 것')

    def test_route_goes_through_daemon_rpc(self):
        self.assertIn('journal_limit_apply', self._read('aot_flask/routes_page.py'))
        self.assertIn('def journal_limit_apply', self._read('aot_daemon.py'))
        self.assertIn('def journal_limit_apply', self._read('aot_client.py'))

    def test_daemon_applies_default_at_startup(self):
        self.assertIn('journal_limit.ensure_default', self._read('aot_daemon.py'))

    def test_form_requires_edit_settings_permission(self):
        src = self._read('aot_flask/routes_page.py')
        post = src.index("if request.method == 'POST':")
        perm = src.index("user_has_permission('edit_settings')", post)
        action = src.index("'save_journal_limit'", post)
        self.assertLess(perm, action)


class TestInfoPageCard(unittest.TestCase):
    """info.html 의 저널 카드 — 레이아웃 없이 그 구간만 그려 본다."""

    @classmethod
    def setUpClass(cls):
        import jinja2
        path = os.path.join(_ROOT, 'aot_flask', 'templates', 'pages', 'info.html')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        start = src.index('{%- if journal_info.supported %}')
        end = src.index('{%- endif %}', src.index('journal_limit_mb')) + len('{%- endif %}')
        env = jinja2.Environment()
        env.globals['_'] = lambda text, **kw: (text % kw) if kw else text
        env.globals['csrf_token'] = lambda: 'tok'
        cls.template = env.from_string(src[start:end])

    def render(self, **info):
        base = {'supported': True, 'usage_mb': 3993.6, 'limit_mb': 500,
                'limit_source': jl.CONF_PATH, 'managed_elsewhere': False,
                'default_mb': 500, 'min_mb': 50, 'max_mb': 10240, 'can_edit': True}
        base.update(info)
        return self.template.render(journal_info=base)

    def test_editable_shows_usage_limit_and_form(self):
        html = self.render()
        self.assertIn('3994 MB', html)
        self.assertIn('value="500"', html)
        self.assertIn('name="action" value="save_journal_limit"', html)
        self.assertIn('name="journal_limit_mb"', html)

    def test_unsupported_renders_nothing(self):
        self.assertEqual(self.render(supported=False).strip(), '')

    def test_viewer_without_permission_gets_no_form(self):
        self.assertNotIn('<form', self.render(can_edit=False))

    def test_foreign_limit_names_the_file_and_has_no_form(self):
        html = self.render(managed_elsewhere=True, limit_source='/etc/systemd/journald.conf')
        self.assertIn('/etc/systemd/journald.conf', html)
        self.assertNotIn('<form', html)

    def test_no_limit_offers_the_default_in_the_field(self):
        html = self.render(limit_mb=None, limit_source=None)
        self.assertIn('Not set (system default)', html)
        self.assertIn('value="500"', html)


if __name__ == '__main__':
    unittest.main()
