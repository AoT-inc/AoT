# coding=utf-8
"""설정 > 일반 '디지털트윈 (실험)' 그룹 — 저장 거부·화면 렌더·마이그레이션.

판정 모듈 자체는 test_twin_gate.py. 여기서는 그 판정이 저장 경로(이중 잠금)와
화면에 제대로 걸리는지, 서비스 상태 표시가 하트비트를 따르는지를 고정한다.
"""
import datetime
import importlib.util
import os
import re
import types
from unittest import mock

import pytest

from aot.tests.test_settings_matter_routes import _MatterAppFixture

_P6_90 = 'p6_90_twin_settings_20261021'
_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE = os.path.join(_HERE, '..', 'aot_flask', 'templates', 'settings', 'general.html')


def _fake_form(enabled=False, run_times=None):
    return types.SimpleNamespace(
        twin_enabled=types.SimpleNamespace(data=enabled),
        twin_run_times=types.SimpleNamespace(data=run_times))


def _messages():
    return {'success': [], 'info': [], 'warning': [], 'error': []}


LOCKED = (False, 'profile_low')
OK = (True, '')


class TestSaveGate(_MatterAppFixture):
    """_twin_settings_apply — 직접 POST 로도 잠긴 기기에서 켜지지 않는다."""

    def _apply(self, form, supported, flag=False, run_times='06:10,18:10'):
        from aot.aot_flask.utils import utils_settings
        from aot.databases.models import Misc
        msgs, audit = _messages(), {}
        data = {} if form.twin_run_times.data is None else {'twin_run_times': form.twin_run_times.data}
        with self.app.test_request_context('/settings/general', method='POST', data=data), \
                mock.patch('aot.utils.twin_gate.twin_supported', return_value=supported):
            misc = Misc.query.first()
            misc.twin_enabled = flag
            misc.twin_run_times = run_times
            utils_settings._twin_settings_apply(misc, form, msgs, audit)
            return bool(misc.twin_enabled), misc.twin_run_times, msgs, audit

    def test_enable_refused_when_locked(self):
        flag, _rt, msgs, audit = self._apply(_fake_form(enabled=True), LOCKED)
        self.assertFalse(flag)
        self.assertEqual(len(msgs['warning']), 1)
        self.assertNotIn('twin_enabled', audit)

    def test_enable_allowed_when_supported(self):
        flag, _rt, msgs, audit = self._apply(_fake_form(enabled=True), OK)
        self.assertTrue(flag)
        self.assertEqual(msgs['warning'], [])
        self.assertEqual(audit, {'twin_enabled': False})

    def test_locked_device_saving_without_toggle_turns_flag_off(self):
        # 비활성 체크박스는 늘 '끔' 으로 온다 — 잠긴 기기에 켜진 채 남은 플래그를 정리한다.
        flag, *_ = self._apply(_fake_form(enabled=False), LOCKED, flag=True)
        self.assertFalse(flag)

    def test_enable_refused_keeps_stored_value_even_if_on(self):
        flag, *_ = self._apply(_fake_form(enabled=True), LOCKED, flag=True)
        self.assertTrue(flag)   # 거부는 저장값을 건드리지 않는다

    def test_run_times_normalized_and_saved(self):
        _f, rt, msgs, audit = self._apply(_fake_form(run_times='18:10, 7:05'), OK)
        self.assertEqual(rt, '07:05,18:10')
        self.assertEqual(msgs['error'], [])
        self.assertEqual(audit, {'twin_run_times': '06:10,18:10'})

    def test_bad_run_times_rejected_and_not_saved(self):
        for bad in ('', '25:00', 'noon'):
            _f, rt, msgs, _a = self._apply(_fake_form(run_times=bad), OK)
            self.assertEqual(rt, '06:10,18:10', bad)
            self.assertEqual(len(msgs['error']), 1, bad)

    def test_missing_run_times_field_is_left_alone(self):
        _f, rt, msgs, audit = self._apply(_fake_form(run_times=None), OK)
        self.assertEqual(rt, '06:10,18:10')
        self.assertEqual((msgs['error'], audit), ([], {}))

    def test_general_save_calls_twin_apply(self):
        # 저장 경로가 이 함수를 실제로 부르는지(소스로 고정).
        import inspect
        from aot.aot_flask.utils import utils_settings
        assert '_twin_settings_apply(mod_misc, form, messages, _audit_before)' in \
            inspect.getsource(utils_settings.settings_general_mod)


class TestPanelContext(_MatterAppFixture):
    def _ctx(self, heartbeat, supported=OK, flag=False):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.utils import utils_settings
        from aot.databases.models import Misc
        with self.app.test_request_context('/settings/general'):
            misc = Misc.query.first()
            misc.twin_enabled = flag
            misc.twin_heartbeat = heartbeat
            misc.timezone = 'Asia/Seoul'
            db.session.commit()
            with mock.patch('aot.utils.twin_gate.twin_supported', return_value=supported):
                return utils_settings.twin_panel_context()

    @staticmethod
    def _hb(age_s, **kw):
        at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age_s)
        base = {'at': at.strftime('%Y-%m-%dT%H:%M:%SZ'), 'status': 'running', 'version': '0.2',
                'sites': 3, 'plots': 9, 'last_run_at': '2026-10-21T21:10:00Z', 'failures': 1,
                'locked_reason': None}
        base.update(kw)
        return base

    def test_no_heartbeat_means_not_running(self):
        ctx = self._ctx(None)
        self.assertFalse(ctx['running'])
        self.assertEqual((ctx['sites'], ctx['plots'], ctx['failures']), (0, 0, 0))
        self.assertEqual(ctx['run_times'], '06:10,18:10')

    def test_stale_heartbeat_means_not_running(self):
        self.assertFalse(self._ctx(self._hb(3600))['running'])

    def test_fresh_heartbeat_fields_and_local_time(self):
        ctx = self._ctx(self._hb(10), flag=True)
        self.assertTrue(ctx['running'] and ctx['enabled'])
        self.assertEqual((ctx['sites'], ctx['plots'], ctx['failures']), (3, 9, 1))
        self.assertEqual(ctx['last_run_at'], '2026-10-22 06:10')   # UTC 21:10 → 서울

    def test_locked_device_reports_reason(self):
        ctx = self._ctx(None, supported=(False, 'low_memory'))
        self.assertFalse(ctx['supported'])
        self.assertIn('GB', ctx['lock_reason'])


_TWIN_TEMPLATE = os.path.join(_HERE, '..', 'aot_flask', 'templates', 'settings', 'twin.html')


def _twin_block(page='general'):
    if page == 'twin':
        src = open(_TWIN_TEMPLATE, encoding='utf-8').read()
        return src[src.index('<!-- Route: /settings/twin -->'):src.index('<script>')]
    src = open(_TEMPLATE, encoding='utf-8').read()
    start = src.index('<!-- Section: Digital Twin')
    end = src.index('<!-- Section: Matter')
    return src[start:end]


class TestRender(_MatterAppFixture):
    BASE = {'supported': True, 'lock_reason': '', 'enabled': False, 'run_times': '06:10,18:10',
            'ignore_profile': False, 'auto_forecast': True,
            'running': False, 'status': None, 'version': '', 'last_run_at': '',
            'sites': 0, 'plots': 0, 'failures': 0, 'service_locked_reason': ''}

    RETENTION = {'days': 730, 'min': 30, 'max': 3650, 'status': '', 'warn': False}

    def _html(self, lang=None, page='general', retention=None, **over):
        # 컨텍스트 프로세서(로그인 필요)를 건너뛰려고 jinja_env 로 직접 그린다.
        from aot.aot_flask.forms import forms_settings
        twin = dict(self.BASE, **over)
        with self.app.test_request_context('/settings/general'):
            tpl = self.app.jinja_env.from_string(_twin_block(page))
            ctx = dict(twin=twin, form_settings_general=forms_settings.SettingsGeneral(),
                       form_twin=forms_settings.SettingsTwin(), can_edit=True,
                       retention=dict(self.RETENTION, **(retention or {})))
            if lang:
                from flask_babel import force_locale
                with force_locale(lang):
                    return tpl.render(**ctx)
            return tpl.render(**ctx)

    def test_data_retention_row_value_status_and_korean(self):
        html = self._html()
        self.assertRegex(html, r'id="data_retention_days"[^>]*value="730"')
        self.assertNotIn('data-retention-status', html)               # 점검 결과가 없으면 줄이 없다
        html = self._html(retention={'status': 'STATUS-TEXT', 'warn': True})
        self.assertIn('id="data-retention-status">STATUS-TEXT', html)

    def test_warning_always_shown(self):
        for over in ({}, {'enabled': True, 'running': True}, {'supported': False}):
            html = self._html(**over)
            self.assertIn('id="twin-warning"', html)
            self.assertIn('Use it for development purposes only', html)

    def test_toggle_default_off_and_enabled(self):
        html = self._html()
        self.assertRegex(html, r'id="twin_enabled"[^>]*>')
        self.assertNotRegex(re.search(r'<input[^>]*id="twin_enabled"[^>]*>', html).group(0),
                            r'checked|disabled')

    def test_locked_disables_toggle_and_shows_reason(self):
        html = self._html(supported=False, enabled=True, lock_reason='REASON-TEXT')
        tag = re.search(r'<input[^>]*id="twin_enabled"[^>]*>', html).group(0)
        self.assertIn('disabled', tag)
        self.assertNotIn('checked', tag)    # 잠긴 기기는 켜진 것으로 그리지 않는다
        self.assertIn('REASON-TEXT', html)
        self.assertIn('remote node', html)
        self.assertNotIn('twin-install-help', html)

    def test_not_running_shows_install_help(self):
        html = self._html(page='twin')
        self.assertIn('Twin service is not running', html)
        self.assertIn('COMPOSE_PROFILES=twin', html)
        self.assertIn('aottwin.service', html)

    def test_running_shows_status_not_install_help(self):
        html = self._html(page='twin', running=True, status='running', sites=3, plots=9, failures=2,
                          last_run_at='2026-10-22 06:10', version='0.2', enabled=True)
        self.assertNotIn('twin-install-help', html)
        self.assertNotIn('Twin service is not running', html)
        for needle in ('2026-10-22 06:10', 'Sites: 3', 'Plots: 9', 'Failures: 2'):
            self.assertIn(needle, html)

    def test_run_times_value_escaped(self):
        html = self._html(page='twin', run_times='"><script>x</script>')
        self.assertNotIn('<script>x</script>', html)

    def test_enable_confirm_uses_the_warning_text(self):
        src = open(_TEMPLATE, encoding='utf-8').read()
        assert "window.confirm(twinWarning.textContent.trim())" in src

    def test_korean_translation_present(self):
        tr = os.path.abspath(os.path.join(_HERE, '..', 'aot_flask', 'translations'))
        self.app.extensions['babel'].translation_directories = [tr]
        html = self._html(lang='ko')
        self.assertIn('디지털트윈 (실험)', html)
        self.assertIn('실험 기능이며 아직 초기 단계입니다. 개발을 위한 용도로만 사용하세요.', html)
        self.assertIn('데이터 보관 (일)', html)                                # 설정 > 일반 '데이터 보관' 칸
        self.assertIn('센서 측정값은 지우지 않습니다', html)
        page = self._html(lang='ko', page='twin')
        self.assertIn('트윈 서비스가 실행 중이 아님', page)
        self.assertIn('낮은 사양 프로파일에서도 허용', page)                    # 새 옵션 이름
        self.assertIn('예보 입력 자동 만들기', page)


# -- 번역 4개 언어 ------------------------------------------------------------

@pytest.mark.parametrize('lang', ['ko', 'ja', 'vi'])
def test_catalogs_carry_the_warning(lang):
    path = os.path.join(_HERE, '..', 'aot_flask', 'translations', lang, 'LC_MESSAGES', 'messages.po')
    po = open(path, encoding='utf-8').read()
    msgid = 'msgid "This is an experimental feature and is still at an early stage.'
    i = po.index(msgid)
    entry = po[i:po.index('\n\n', i)]
    assert re.search(r'msgstr "[^"]+', entry), lang


# -- migration --------------------------------------------------------------

def _load_migration():
    path = os.path.join(_HERE, '..', '..', 'alembic_db', 'alembic', 'versions', _P6_90 + '.py')
    spec = importlib.util.spec_from_file_location(_P6_90, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, fn, engine):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn)()


def test_migration_chain_position():
    mod = _load_migration()
    assert mod.revision == _P6_90
    assert mod.down_revision == 'p6_89_ai_card_attachments_20261021'


def test_migration_defaults_and_idempotent(tmp_path):
    import sqlalchemy as sa
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'mig.db'))
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE misc (id INTEGER PRIMARY KEY, hide_tooltips BOOLEAN)"))
        conn.execute(sa.text("INSERT INTO misc (hide_tooltips) VALUES (0)"))
    mod = _load_migration()
    _run(mod, 'upgrade', engine)
    _run(mod, 'upgrade', engine)        # 두 번 돌려도 같다
    with engine.begin() as conn:
        row = conn.execute(sa.text(
            "SELECT twin_enabled, twin_run_times, twin_heartbeat FROM misc")).one()
    assert (row[0], row[1], row[2]) == (0, '06:10,18:10', None)
    _run(mod, 'downgrade', engine)
    _run(mod, 'downgrade', engine)
    cols = {c['name'] for c in sa.inspect(engine).get_columns('misc')}
    assert not ({'twin_enabled', 'twin_run_times', 'twin_heartbeat'} & cols)


class TestTwinPage(_MatterAppFixture):
    """settings/twin — 저장(실행 시각·두 옵션), 낮은 사양 잠금 해제, 메뉴 노출."""

    def _form(self, run_times='06:10,18:10', ignore=False, auto=True):
        return types.SimpleNamespace(
            validate=lambda: True, errors={},
            twin_run_times=types.SimpleNamespace(data=run_times),
            twin_ignore_profile=types.SimpleNamespace(data=ignore),
            twin_auto_forecast=types.SimpleNamespace(data=auto))

    def test_options_saved_and_audited(self):
        from aot.aot_flask.utils import utils_settings
        from aot.databases.models import Misc
        with self.app.test_request_context('/settings/twin', method='POST'), \
                mock.patch.object(utils_settings, 'invalidate_misc_cache'):
            msgs = utils_settings.settings_twin_mod(self._form('18:10, 7:05', ignore=True, auto=False))
            misc = Misc.query.first()
            self.assertEqual(msgs['error'], [])
            self.assertEqual((misc.twin_run_times, misc.twin_ignore_profile, misc.twin_auto_forecast),
                             ('07:05,18:10', True, False))
            ctx = utils_settings.twin_panel_context()
            self.assertEqual((ctx['ignore_profile'], ctx['auto_forecast']), (True, False))

    def test_bad_run_times_save_nothing(self):
        from aot.aot_flask.utils import utils_settings
        from aot.databases.models import Misc
        with self.app.test_request_context('/settings/twin', method='POST'):
            before = Misc.query.first().twin_run_times
            msgs = utils_settings.settings_twin_mod(self._form('25:00', ignore=True))
            self.assertEqual(len(msgs['error']), 1)
            misc = Misc.query.first()
            self.assertEqual(misc.twin_run_times, before)
            self.assertFalse(bool(misc.twin_ignore_profile))                     # 오류면 옵션도 저장 안 함

    def test_ignore_profile_flag_skips_only_the_profile_lock(self):
        from aot.databases.models import Misc
        from aot.utils import twin_gate
        with self.app.test_request_context('/'), \
                mock.patch('aot.config.mcp_config.HARDWARE_PROFILE', 'LOW'), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(twin_gate.IGNORE_PROFILE_ENV, None)
            misc = Misc.query.first()
            misc.twin_ignore_profile = False
            self.assertEqual(twin_gate.twin_supported(), (False, twin_gate.REASON_PROFILE_LOW))
            misc.twin_ignore_profile = True
            with mock.patch('aot.utils.system_environment.pi_model', return_value='Raspberry Pi 3 Model B'):
                self.assertEqual(twin_gate.twin_supported(), (False, twin_gate.REASON_PI_MODEL))   # 파이 잠금은 그대로
            with mock.patch('aot.utils.system_environment.pi_model', return_value=None), \
                    mock.patch('aot.utils.system_environment.mem_total_gb', return_value=8.0):
                self.assertEqual(twin_gate.twin_supported(), (True, ''))

    def test_page_is_gated_by_the_general_flag_and_listed_in_the_menu(self):
        src = open(os.path.join(_HERE, '..', 'aot_flask', 'templates', 'layout-settings.html'),
                   encoding='utf-8').read()
        assert "settings.twin_enabled" in src and "routes_settings.settings_twin" in src
        from aot.aot_flask import routes_settings
        import inspect
        assert "twin_gate.twin_flag()" in inspect.getsource(routes_settings._twin_feature_gate)
