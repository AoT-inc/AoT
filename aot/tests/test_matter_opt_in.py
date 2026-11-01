# coding=utf-8
"""Matter 는 설정 > 일반에서 켜는 선택 기능이다(2026-10-10, 사용자 요청).

- 꺼져 있으면 Matter 페이지는 일반 설정으로 돌려보내고 API 는 404.
- Matter 장치가 남아 있는 동안은 끌 수 없다(관리할 화면이 사라지므로).
- 켤 때 전역 의존성 'matter' 를 본다: 네이티브는 의존성 설치 화면으로,
  Docker 는 이미지가 들고 있어야 하므로(설계 C6) 이미지 업데이트 안내.
- 마이그레이션은 기본 꺼짐, 이미 Matter 장치가 있는 설치는 켠 채로 올린다.
"""
import importlib.util
import os
from unittest import mock

import pytest

from aot.tests.test_settings_matter_routes import _MatterAppFixture

_P6_84 = 'p6_84_matter_enabled_20261010'


def _set_enabled(app, value):
    from aot.aot_flask.extensions import db
    from aot.databases.models import Misc
    with app.app_context():
        Misc.query.first().matter_enabled = value
        db.session.commit()


class TestGateWhenOff(_MatterAppFixture):

    def setUp(self):
        super().setUp()
        _set_enabled(self.app, False)
        self._login()

    def test_page_goes_back_to_general_settings(self):
        resp = self.client.get('/settings/matter')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers['Location'].endswith('/settings/general'))

    def test_api_answers_404(self):
        self.assertEqual(self.client.get('/settings/matter/nodes').status_code, 404)
        resp = self.client.post('/settings/matter/commission', json={'code': '12345678901'})
        self.assertEqual(resp.status_code, 404)

    def test_other_settings_pages_are_not_gated(self):
        # 게이트는 Matter 엔드포인트만 본다.
        from aot.aot_flask import routes_settings
        with self.app.test_request_context('/settings/general'):
            from flask import request
            request.url_rule = None
            self.assertIsNone(routes_settings._matter_feature_gate())

    def test_turning_it_on_opens_the_page(self):
        _set_enabled(self.app, True)
        with mock.patch('aot.aot_flask.routes_settings.render_template',
                        lambda name, **ctx: name), \
                mock.patch('aot.aot_flask.utils.utils_matter.server_status',
                           return_value={'connected': False}):
            resp = self.client.get('/settings/matter')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), 'settings/matter.html')


class TestToggle(_MatterAppFixture):

    def setUp(self):
        super().setUp()
        # 네이티브 설치에서 보낼 의존성 화면(최소 앱에는 routes_admin 이 없다).
        from flask import Blueprint
        admin = Blueprint('routes_admin', __name__)
        admin.add_url_rule('/admin/dependencies/<device>', 'admin_dependencies',
                           lambda device: device)
        self.app.register_blueprint(admin)

    def _toggle(self, enable, unmet=(), docker=False):
        from aot.aot_flask.utils import utils_settings
        messages = {'success': [], 'info': [], 'warning': [], 'error': []}
        env = {'DOCKER_CONTAINER': 'TRUE'} if docker else {'DOCKER_CONTAINER': ''}
        with self.app.test_request_context('/settings/general'), \
                mock.patch.dict(os.environ, env), \
                mock.patch('aot.aot_flask.utils.utils_general.return_dependencies',
                           return_value=(list(unmet), True, '')):
            value = utils_settings._matter_toggle(enable, messages)
        return value, messages

    def _add_matter_device(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import CustomController
        with self.app.app_context():
            db.session.add(CustomController(device='device_matter_node', name='Plug'))
            db.session.commit()

    def test_off_is_refused_while_matter_devices_exist(self):
        self._add_matter_device()
        value, messages = self._toggle(False)
        self.assertTrue(value)
        self.assertTrue(messages['warning'])

    def test_off_without_devices(self):
        value, messages = self._toggle(False)
        self.assertFalse(value)
        self.assertEqual(messages['warning'], [])

    def test_on_with_packages_present(self):
        value, messages = self._toggle(True)
        self.assertTrue(value)
        self.assertNotIn('redirect', messages)
        self.assertEqual(messages['warning'] + messages['info'], [])

    def test_on_native_without_packages_goes_to_the_dependency_page(self):
        value, messages = self._toggle(True, unmet=['websockets'])
        self.assertTrue(value)
        self.assertEqual(messages['redirect'], '/admin/dependencies/matter')

    def test_on_docker_without_packages_says_update_the_image(self):
        value, messages = self._toggle(True, unmet=['websockets'], docker=True)
        self.assertTrue(value)
        self.assertNotIn('redirect', messages)
        self.assertTrue(messages['warning'])


def test_matter_is_a_global_dependency():
    from aot.config import DEPENDENCIES_GENERAL
    deps = DEPENDENCIES_GENERAL['matter']['dependencies_module']
    assert ('pip-pypi', 'websockets', 'websockets==16.0') in deps


def test_sidebar_link_only_when_on():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', 'aot_flask', 'templates', 'layout-settings.html')) as fh:
        lines = fh.read().split('\n')
    i = next(n for n, line in enumerate(lines) if "routes_settings.settings_matter'" in line)
    assert 'settings.matter_enabled' in lines[i - 1]


# -- migration --------------------------------------------------------------

def _load_migration():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, '..', '..', 'alembic_db', 'alembic', 'versions', _P6_84 + '.py')
    spec = importlib.util.spec_from_file_location(_P6_84, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, fn, engine):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn)()


def test_migration_keeps_its_place_in_the_chain():
    mod = _load_migration()
    assert mod.revision == _P6_84
    assert mod.down_revision == 'p6_83_central_account_tool_profile_20261010'


@pytest.mark.parametrize('has_matter_device, expected', [(False, 0), (True, 1)])
def test_migration_default_off_unless_matter_already_used(tmp_path, has_matter_device, expected):
    import sqlalchemy as sa
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'mig.db'))
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE misc (id INTEGER PRIMARY KEY, hide_tooltips BOOLEAN)"))
        conn.execute(sa.text("INSERT INTO misc (hide_tooltips) VALUES (0)"))
        conn.execute(sa.text("CREATE TABLE custom_controller (id INTEGER PRIMARY KEY, device TEXT)"))
        conn.execute(sa.text("INSERT INTO custom_controller (device) VALUES ('function_x')"))
        if has_matter_device:
            conn.execute(sa.text(
                "INSERT INTO custom_controller (device) VALUES ('device_matter_node')"))

    mod = _load_migration()
    _run(mod, 'upgrade', engine)
    _run(mod, 'upgrade', engine)        # 두 번 돌려도 같다
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT matter_enabled FROM misc")).scalar() == expected
    _run(mod, 'downgrade', engine)
    _run(mod, 'downgrade', engine)
    assert 'matter_enabled' not in {c['name'] for c in sa.inspect(engine).get_columns('misc')}
