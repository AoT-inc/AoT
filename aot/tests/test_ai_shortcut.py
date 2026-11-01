# coding=utf-8
"""AI 바로가기 주소(2026-10-22): 검사 함수·마이그레이션 p6_94·설정 배선·레이아웃."""
import importlib.util
import os
import unittest

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from aot.utils import ai_shortcut

ROOT = os.path.join(os.path.dirname(__file__), '..')
FLASK = os.path.join(ROOT, 'aot_flask')


def _read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as fh:
        return fh.read()


class NormalizeTest(unittest.TestCase):

    def test_https_addresses_pass_unchanged_and_empty_means_no_button(self):
        for good in ('https://claude.ai/new', 'https://chatgpt.com/', 'https://gemini.google.com/app',
                     'https://example.co.kr:8443/a?b=1#c'):
            self.assertEqual(good, ai_shortcut.normalize(good))
        self.assertEqual('https://claude.ai/new', ai_shortcut.normalize('  https://claude.ai/new  '))
        for empty in ('', '   ', None):
            self.assertEqual('', ai_shortcut.normalize(empty))

    def test_unsafe_or_odd_addresses_are_refused(self):
        for bad in ('http://claude.ai/new', 'javascript:alert(1)', 'data:text/html,x', 'claude://claude.ai/new',
                    'ftp://claude.ai/', 'https://user:pw@claude.ai/', 'https://10.0.0.1/x', 'https://[::1]/x',
                    'https://localhost/x', 'https://claude.ai/ne w', 'https://claude.ai/"x', 'https://claude.ai/<x>',
                    'https://claude.ai:99999/', 'claude.ai/new', 'https://' + 'a' * 600 + '.com'):
            with self.assertRaises(ValueError, msg=bad):
                ai_shortcut.normalize(bad)

    def test_default_is_a_valid_address(self):
        self.assertEqual(ai_shortcut.DEFAULT, ai_shortcut.normalize(ai_shortcut.DEFAULT))


class MigrationTest(unittest.TestCase):

    def test_p6_94_adds_the_column_with_the_default_and_is_rerun_safe(self):
        path = os.path.join(ROOT, '..', 'alembic_db', 'alembic', 'versions', 'p6_94_ai_shortcut_20261022.py')
        spec = importlib.util.spec_from_file_location('p6_94', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual('p6_93_ai_card_auto_20261022', mod.down_revision)
        eng = sa.create_engine('sqlite://')
        with eng.begin() as conn:
            conn.execute(sa.text('create table misc (id integer primary key)'))
            conn.execute(sa.text('insert into misc (id) values (1)'))
            with Operations.context(MigrationContext.configure(conn)):
                mod.upgrade()
                mod.upgrade()
                cols = [c['name'] for c in sa.inspect(conn).get_columns('misc')]
                self.assertIn('ai_shortcut_url', cols)
                self.assertEqual('https://claude.ai/new',
                                 conn.execute(sa.text('select ai_shortcut_url from misc')).scalar())
                mod.downgrade()
                mod.downgrade()
                self.assertNotIn('ai_shortcut_url', [c['name'] for c in sa.inspect(conn).get_columns('misc')])


class WiringTest(unittest.TestCase):

    def test_form_save_template_and_layouts_are_wired(self):
        self.assertIn('ai_shortcut_url = StringField', _read(FLASK, 'forms', 'forms_settings.py'))
        save = _read(FLASK, 'utils', 'utils_settings.py')
        self.assertIn('ai_shortcut.normalize(form.ai_shortcut_url.data)', save)
        self.assertIn('It was not changed.', save)           # 틀린 주소는 바꾸지 않고 알린다
        self.assertIn('name="ai_shortcut_url"', _read(FLASK, 'templates', 'settings', 'general.html'))
        a = _read(FLASK, 'templates', 'layout.html')
        b = _read(FLASK, 'templates', 'layout_default.html')
        self.assertEqual(a, b)
        self.assertIn("'ai_shortcut_url': settings.ai_shortcut_url | default('')", a)
        self.assertIn("ai_shortcut_url: ''", a)

    def test_model_default_and_config_head(self):
        from aot.config import ALEMBIC_VERSION
        from aot.databases.models import Misc
        self.assertEqual('p7_00_target_alias_20261028', ALEMBIC_VERSION)
        self.assertEqual(ai_shortcut.DEFAULT, Misc.__table__.c.ai_shortcut_url.default.arg)


if __name__ == '__main__':
    unittest.main()
