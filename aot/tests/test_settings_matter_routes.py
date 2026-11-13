# -*- coding: utf-8 -*-
"""Settings > Matter 라우트 (docs/design/matter-controller.md §5-4).

Matter 서버는 선택 사양(사이드카)이라 이 페이지는 서버가 없어도 열려야 한다 —
E2E 스모크가 모든 GET 을 관리자로 열고 5xx 가 없기를 기대한다. 그리고 추가·
삭제는 AoT 장치를 만들고 지우므로 edit_settings + edit_controllers 가 둘 다
필요하다.

여기서 고정하는 것:
  * GET /settings/matter 는 서버가 꺼져 있어도(상태 조회가 예외를 내도) 200 이다.
  * POST commission 은 서비스의 결과를 그대로 JSON 으로 돌려주고(실패여도 200),
    권한이 없으면 서비스를 부르지 않고 403 이다.
  * POST remove 는 AoT 장치가 있으면 controller_del 로(자식 정리·Matter 제거 훅이
    그 경로에 있다), 없는 고아 노드면 remove_node 로 지운다.
  * 페어링 코드가 로그에 남지 않는다.

P3(새 장치·공유·펌웨어): utils_matter_admin 의 각 함수를 monkeypatch 해 라우트만 본다 —
권한 403, 그룹 스코프 403, 잘못된 입력 400, 비밀(코드·Wi-Fi 비밀번호·Thread
데이터셋)이 로그에 남지 않는 것.

서비스(utils_matter)는 전부 monkeypatch 한다 — 서버도 DB 의 Matter 장치도 필요 없다.
"""
import contextlib
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))

CODE = '12345678901'
WIFI_PASSWORD = 'hunter2-wifi-pass'
DATASET = '0e080000000000010000000300001235060004001fffe0'
BLE_ON = {'connected': True, 'bluetooth_enabled': True}
BLE_OFF = {'connected': True, 'bluetooth_enabled': False}

DOWN = {'connected': False, 'endpoint': 'ws://matter:5580/ws', 'last_error': 'refused',
        'schema_version': None, 'sdk_version': None, 'fabric_id': None,
        'node_count': 0, 'nodes_available': 0}
UP = dict(DOWN, connected=True, last_error=None, schema_version=11,
          sdk_version='0.1', fabric_id=1, node_count=2, nodes_available=1)

NODES = [
    {'node_id': 5, 'available': True, 'name': 'Plug <b>1</b>', 'vendor_name': 'Acme',
     'product_name': 'Plug', 'sensor_count': 2, 'switch_count': 1,
     'device_id': 'dev-uuid-5', 'device_name': 'Matter Plug'},
    {'node_id': 9, 'available': False, 'name': 'Orphan', 'vendor_name': '',
     'product_name': '', 'sensor_count': 0, 'switch_count': 0,
     'device_id': None, 'device_name': None},
]


class _MatterAppFixture(unittest.TestCase):
    """routes_settings 블루프린트 하나만 등록한 임시 앱 (임시 sqlite)."""

    def setUp(self):
        from flask import Blueprint, Flask
        import flask_login
        from flask_babel import Babel

        from aot.aot_flask.extensions import db, csrf
        import aot.databases.models  # noqa: F401 — 모델 등록
        from aot.databases.models import Role, User
        from aot.aot_flask import routes_settings

        self._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(
            os.path.join(self._tmp.name, 'test.db'))
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['TESTING'] = True
        app.config['SESSION_PROTECTION'] = None

        db.init_app(app)
        csrf.init_app(app)
        Babel(app)
        app.register_blueprint(routes_settings.blueprint)

        # 권한이 없을 때 redirect(url_for('routes_general.home')) 가 갈 자리.
        general = Blueprint('routes_general', __name__)

        @general.route('/')
        def home():
            return 'home'

        app.register_blueprint(general)

        login_manager = flask_login.LoginManager()
        login_manager.init_app(app)

        @login_manager.user_loader
        def user_loader(user_id):
            raw = str(user_id or '')
            uid, sep, token = raw.partition('|')
            user = User.query.filter(User.id == uid).first()
            if not user or not user.is_enabled:
                return None
            if not sep or not user.verify_session_auth_hash(token):
                return None
            return user

        self.app = app
        self.client = app.test_client()
        self._login_ids = {}

        roles = {
            # 이름: (view_settings, edit_settings, edit_controllers)
            'admin': (True, True, True),
            'viewer': (True, False, False),          # 보기만
            'settings_only': (True, True, False),    # 장치를 만들 권한은 없다
        }
        with app.app_context():
            db.create_all()
            # Matter 는 설정 > 일반에서 켠 설치에서만 열린다(_matter_feature_gate).
            from aot.databases.models import Misc
            db.session.add(Misc(matter_enabled=True))
            db.session.commit()
            for name, (view, edit_settings, edit_controllers) in roles.items():
                role = Role()
                role.name = name
                role.view_settings = view
                role.edit_settings = edit_settings
                role.edit_controllers = edit_controllers
                db.session.add(role)
                db.session.commit()
                user = User()
                user.name = name
                user.email = '{}@example.com'.format(name)
                user.is_enabled = True
                user.is_approved = True
                user.role_id = role.id
                user.set_password('correct horse battery staple')
                db.session.add(user)
                db.session.commit()
                self._login_ids[name] = user.get_id()

    def tearDown(self):
        self._tmp.cleanup()

    def _login(self, name='admin'):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = self._login_ids[name]
            sess['_fresh'] = True


class TestPageRendersWithoutServer(_MatterAppFixture):

    def _get(self, **patches):
        """render_template 을 가로채 템플릿에 넘긴 값을 본다(레이아웃 전체 불필요)."""
        self._login()
        captured = {}

        def fake_render(name, **context):
            captured['name'] = name
            captured.update(context)
            return 'rendered'

        # bluetooth_enabled 는 server_status() 가 서버 정보에서 함께 준다(연결
        # 하나로). 테스트의 bluetooth 패치를 상태 값에 접어 넣는다.
        status_patch = dict(patches.get('status', {'return_value': DOWN}))
        ble_patch = patches.get('bluetooth', {'return_value': BLE_ON})
        if 'return_value' in status_patch:
            merged = dict(status_patch['return_value'])
            merged['bluetooth_enabled'] = bool(
                (ble_patch.get('return_value') or {}).get('bluetooth_enabled'))
            status_patch['return_value'] = merged
        with mock.patch('aot.aot_flask.routes_settings.render_template', fake_render), \
                mock.patch('aot.aot_flask.utils.utils_matter.server_status',
                           **status_patch), \
                mock.patch('aot.aot_flask.utils.utils_matter.list_nodes',
                           **patches.get('nodes', {'return_value': []})), \
                mock.patch('aot.aot_flask.utils.utils_matter_admin.bluetooth_status',
                           **patches.get('bluetooth', {'return_value': BLE_ON})) as ble:
            resp = self.client.get('/settings/matter')
        captured['_ble_calls'] = ble.call_count
        return resp, captured

    def test_server_down_still_renders(self):
        resp, ctx = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ctx['name'], 'settings/matter.html')
        self.assertFalse(ctx['status']['connected'])
        self.assertEqual(ctx['nodes'], [])

    def test_bluetooth_flag_is_passed_when_connected(self):
        resp, ctx = self._get(status={'return_value': UP})
        self.assertTrue(ctx['bluetooth_enabled'])
        resp, ctx = self._get(status={'return_value': UP},
                              bluetooth={'return_value': BLE_OFF})
        self.assertFalse(ctx['bluetooth_enabled'])

    def test_bluetooth_not_asked_without_a_server(self):
        resp, ctx = self._get()
        self.assertFalse(ctx['bluetooth_enabled'])
        self.assertEqual(ctx['_ble_calls'], 0)

    def test_bluetooth_status_raising_still_renders(self):
        resp, ctx = self._get(status={'return_value': UP},
                              bluetooth={'side_effect': RuntimeError('boom')})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ctx['bluetooth_enabled'])

    def test_status_raising_still_renders(self):
        resp, ctx = self._get(status={'side_effect': RuntimeError('boom')})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ctx['status']['connected'])
        self.assertTrue(ctx['list_error'])

    def test_node_list_raising_still_renders(self):
        resp, ctx = self._get(status={'return_value': UP},
                              nodes={'side_effect': RuntimeError('boom')})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ctx['nodes'], [])
        self.assertTrue(ctx['list_error'])

    def test_connected_passes_nodes(self):
        resp, ctx = self._get(status={'return_value': UP},
                              nodes={'return_value': NODES})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(ctx['status']['connected'])
        self.assertEqual(ctx['nodes'], NODES)

    def test_no_view_settings_is_sent_home(self):
        with self.app.app_context():
            from aot.databases.models import Role
            role = Role.query.filter_by(name='viewer').first()
            role.view_settings = False
            role.save()
        self._login('viewer')
        resp = self.client.get('/settings/matter')
        self.assertEqual(resp.status_code, 302)

    def test_login_required(self):
        resp = self.client.get('/settings/matter')
        self.assertNotEqual(resp.status_code, 200)


class TestNodesJson(_MatterAppFixture):

    def test_returns_status_and_nodes(self):
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.server_status', return_value=UP), \
                mock.patch('aot.aot_flask.utils.utils_matter.list_nodes', return_value=NODES):
            resp = self.client.get('/settings/matter/nodes')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['status']['connected'])
        self.assertEqual(data['nodes'], NODES)

    def test_server_down_is_not_an_error(self):
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.server_status',
                        side_effect=RuntimeError('boom')):
            resp = self.client.get('/settings/matter/nodes')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data['status']['connected'])
        self.assertEqual(data['nodes'], [])


class TestCommission(_MatterAppFixture):

    def _post(self, body=None):
        return self.client.post('/settings/matter/commission',
                                json={'code': CODE} if body is None else body)

    def test_returns_service_result(self):
        self._login()
        result = {'ok': True, 'error': None, 'node_id': 5, 'device_id': 'dev-uuid-5',
                  'rebound': False, 'sensor_count': 2, 'switch_count': 1, 'warnings': ['w']}
        with mock.patch('aot.aot_flask.utils.utils_matter.commission',
                        return_value=result) as commission:
            resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), result)
        commission.assert_called_once_with(CODE)

    def test_service_failure_is_200_with_error_text(self):
        self._login()
        result = {'ok': False, 'error': 'The pairing code is not valid.', 'warnings': []}
        with mock.patch('aot.aot_flask.utils.utils_matter.commission', return_value=result):
            resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()['ok'])
        self.assertEqual(resp.get_json()['error'], 'The pairing code is not valid.')

    def test_service_exception_becomes_json_error(self):
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.commission',
                        side_effect=RuntimeError('boom')):
            resp = self._post()
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data['ok'])
        self.assertTrue(data['error'])

    def test_non_string_code_is_passed_as_empty(self):
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.commission',
                        return_value={'ok': False, 'error': 'x', 'warnings': []}) as commission:
            self._post({'code': 12345678901})
        commission.assert_called_once_with('')

    def test_without_edit_controllers_is_403_and_service_untouched(self):
        for name in ('viewer', 'settings_only'):
            self._login(name)
            with mock.patch('aot.aot_flask.utils.utils_matter.commission') as commission:
                resp = self._post()
            self.assertEqual(resp.status_code, 403, name)
            self.assertFalse(resp.get_json()['ok'])
            commission.assert_not_called()

    def test_login_required(self):
        with mock.patch('aot.aot_flask.utils.utils_matter.commission') as commission:
            resp = self._post()
        self.assertNotEqual(resp.status_code, 200)
        commission.assert_not_called()

    def test_pairing_code_is_never_logged(self):
        self._login()
        with _capture_aot_logs(self) as logs:
            with mock.patch('aot.aot_flask.utils.utils_matter.commission',
                            side_effect=RuntimeError('boom')):
                self._post()
        self.assertNotIn(CODE, '\n'.join(logs.output))


class TestRemove(_MatterAppFixture):

    def _post(self, node_id):
        return self.client.post('/settings/matter/remove', json={'node_id': node_id})

    def test_orphan_node_uses_remove_node(self):
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.list_nodes', return_value=NODES), \
                mock.patch('aot.aot_flask.utils.utils_matter.remove_node',
                           return_value=(True, 'still lists AoT')) as remove_node, \
                mock.patch('aot.aot_flask.utils.utils_controller.controller_del') as del_:
            resp = self._post(9)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['warnings'], ['still lists AoT'])
        remove_node.assert_called_once_with(9)
        del_.assert_not_called()

    def test_orphan_node_failure_reports_error(self):
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.list_nodes', return_value=NODES), \
                mock.patch('aot.aot_flask.utils.utils_matter.remove_node',
                           return_value=(False, 'Removing the device failed: x')):
            data = self._post(9).get_json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['error'], 'Removing the device failed: x')

    def test_node_with_device_goes_through_controller_del(self):
        self._login()
        messages = {'success': ['Controller deleted'], 'info': [], 'error': [],
                    'warning': ['AoT could not remove itself']}
        with mock.patch('aot.aot_flask.utils.utils_matter.list_nodes', return_value=NODES), \
                mock.patch('aot.aot_flask.utils.utils_matter.remove_node') as remove_node, \
                mock.patch('aot.aot_flask.utils.utils_controller.controller_del',
                           return_value=messages) as del_:
            resp = self._post(5)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['warnings'], ['AoT could not remove itself'])
        del_.assert_called_once_with('dev-uuid-5')
        remove_node.assert_not_called()

    def test_controller_del_error_is_reported(self):
        self._login()
        messages = {'success': [], 'info': [], 'warning': [], 'error': ['denied']}
        with mock.patch('aot.aot_flask.utils.utils_matter.list_nodes', return_value=NODES), \
                mock.patch('aot.aot_flask.utils.utils_controller.controller_del',
                           return_value=messages):
            data = self._post(5).get_json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['error'], 'denied')

    def test_server_down_finds_the_device_in_the_database(self):
        import json
        from aot.databases.models import CustomController
        with self.app.app_context():
            row = CustomController()
            row.device = 'device_matter_node'
            row.name = 'Matter Plug'
            row.custom_options = json.dumps({'node_id': 5})
            row.save()
            device_id = row.unique_id
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.list_nodes',
                        side_effect=RuntimeError('down')), \
                mock.patch('aot.aot_flask.utils.utils_matter.remove_node') as remove_node, \
                mock.patch('aot.aot_flask.utils.utils_controller.controller_del',
                           return_value={'error': [], 'warning': []}) as del_:
            data = self._post(5).get_json()
        self.assertTrue(data['ok'])
        del_.assert_called_once_with(device_id)
        remove_node.assert_not_called()

    def test_bad_node_id_is_400(self):
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.remove_node') as remove_node:
            resp = self._post('abc')
        self.assertEqual(resp.status_code, 400)
        remove_node.assert_not_called()

    def test_without_edit_controllers_is_403(self):
        for name in ('viewer', 'settings_only'):
            self._login(name)
            with mock.patch('aot.aot_flask.utils.utils_matter.remove_node') as remove_node, \
                    mock.patch('aot.aot_flask.utils.utils_controller.controller_del') as del_:
                resp = self._post(5)
            self.assertEqual(resp.status_code, 403, name)
            remove_node.assert_not_called()
            del_.assert_not_called()


ADMIN = 'aot.aot_flask.utils.utils_matter_admin.'
DEVICE_FOR_NODE = 'aot.aot_flask.routes_settings._matter_device_for_node'
SCOPE_CAN = 'aot.aot_flask.access.scope.can_operate_device'


@contextlib.contextmanager
def _capture_aot_logs(testcase):
    """Every record from aot.* during the block, whatever the logging config.

    assertLogs alone is not enough in the full suite, where earlier tests
    leave global logging state behind:
      - logging.config with disable_existing_loggers=True leaves 'aot' (and
        children created before it) disabled;
      - importing aot/scripts/check_env_coordinator_health.py runs
        logging.disable(logging.INFO) at module level, which suppresses every
        record at INFO and below process-wide.
    Either way nothing below the cut-off is emitted, so the leak check would
    see nothing and prove nothing (CI failed with "no logs ... triggered").
    Lift both for the block and restore afterwards.
    """
    names = ['aot'] + [n for n in logging.root.manager.loggerDict
                       if n.startswith('aot.')]
    loggers = [logging.getLogger(n) for n in names]
    saved = [(lg, lg.disabled) for lg in loggers]
    saved_disable = logging.root.manager.disable
    for lg in loggers:
        lg.disabled = False
    logging.disable(logging.NOTSET)
    try:
        with testcase.assertLogs('aot', level=logging.DEBUG) as logs:
            logging.getLogger('aot').debug('log capture active')
            yield logs
    finally:
        logging.disable(saved_disable)
        for lg, was in saved:
            lg.disabled = was


def _secret_free(testcase, logs):
    text = '\n'.join(logs.output)
    for secret in (CODE, WIFI_PASSWORD, DATASET):
        testcase.assertNotIn(secret, text)


class TestNewDevice(_MatterAppFixture):

    BODY = {'code': CODE,
            'network': {'kind': 'wifi', 'ssid': 'farm', 'password': WIFI_PASSWORD,
                        'dataset': ''}}

    def _post(self, body=None):
        return self.client.post('/settings/matter/new_device',
                                json=self.BODY if body is None else body)

    def test_starts_the_job_for_the_current_user(self):
        self._login()
        with mock.patch(ADMIN + 'start_new_device',
                        return_value={'ok': True, 'job_id': 'a' * 32, 'error': None}) as start:
            resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'ok': True, 'job_id': 'a' * 32, 'error': None})
        args, kwargs = start.call_args
        self.assertEqual(args[0], CODE)
        self.assertEqual(args[1]['kind'], 'wifi')
        self.assertEqual(args[1]['password'], WIFI_PASSWORD)
        self.assertTrue(kwargs['user_id'])

    def test_service_refusal_is_200_with_error_text(self):
        self._login()
        refusal = {'ok': False, 'job_id': None, 'error': 'Enter the Wi-Fi network name.'}
        with mock.patch(ADMIN + 'start_new_device', return_value=refusal):
            resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), refusal)

    def test_non_string_code_and_non_dict_network_are_coerced(self):
        self._login()
        with mock.patch(ADMIN + 'start_new_device',
                        return_value={'ok': False, 'job_id': None, 'error': 'x'}) as start:
            self._post({'code': 12345678901, 'network': 'wifi'})
            self._post(['not', 'a', 'dict'])
        first, second = start.call_args_list
        self.assertEqual(first[0], ('', {}))
        self.assertEqual(second[0], ('', {}))

    def test_service_exception_becomes_json_error(self):
        self._login()
        with mock.patch(ADMIN + 'start_new_device', side_effect=RuntimeError('boom')):
            resp = self._post()
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data['ok'])
        self.assertTrue(data['error'])

    def test_without_edit_controllers_is_403_and_service_untouched(self):
        for name in ('viewer', 'settings_only'):
            self._login(name)
            with mock.patch(ADMIN + 'start_new_device') as start:
                resp = self._post()
            self.assertEqual(resp.status_code, 403, name)
            self.assertFalse(resp.get_json()['ok'])
            start.assert_not_called()

    def test_login_required(self):
        with mock.patch(ADMIN + 'start_new_device') as start:
            resp = self._post()
        self.assertNotEqual(resp.status_code, 200)
        start.assert_not_called()

    def test_secrets_never_logged_on_success(self):
        self._login()
        with _capture_aot_logs(self) as logs:
            with mock.patch(ADMIN + 'start_new_device',
                            return_value={'ok': True, 'job_id': 'a' * 32, 'error': None}):
                self._post({'code': CODE, 'network': {
                    'kind': 'thread', 'dataset': DATASET, 'password': WIFI_PASSWORD}})
        _secret_free(self, logs)

    def test_secrets_never_logged_when_the_service_raises(self):
        self._login()
        # 예외 메시지가 입력을 되울려도(서버 오류 문구처럼) 로그에 남으면 안 된다.
        boom = RuntimeError('bad request: {} {} {}'.format(CODE, WIFI_PASSWORD, DATASET))
        with _capture_aot_logs(self) as logs:
            with mock.patch(ADMIN + 'start_new_device', side_effect=boom):
                self._post({'code': CODE, 'network': {
                    'kind': 'wifi', 'ssid': 'farm', 'password': WIFI_PASSWORD,
                    'dataset': DATASET}})
        _secret_free(self, logs)

    def test_response_does_not_echo_the_secrets(self):
        self._login()
        with mock.patch(ADMIN + 'start_new_device', side_effect=RuntimeError(WIFI_PASSWORD)):
            body = self._post().get_data(as_text=True)
        self.assertNotIn(WIFI_PASSWORD, body)


class TestNewDeviceStatus(_MatterAppFixture):

    JOB = 'b' * 32

    def _get(self):
        return self.client.get('/settings/matter/new_device/' + self.JOB)

    def test_returns_state(self):
        self._login()
        status = {'state': 'commissioning', 'node_id': None, 'error': None, 'result': None}
        with mock.patch(ADMIN + 'new_device_status', return_value=status) as svc:
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['state'], 'commissioning')
        svc.assert_called_once_with(self.JOB)

    def test_done_carries_result_counts(self):
        self._login()
        status = {'state': 'done', 'node_id': 5, 'error': None, 'result': {
            'device_id': 'dev-uuid-5', 'rebound': False, 'sensor_count': 2,
            'switch_count': 1, 'warnings': []}}
        with mock.patch(ADMIN + 'new_device_status', return_value=status):
            data = self._get().get_json()
        self.assertEqual(data['result']['sensor_count'], 2)

    def test_service_exception_is_ok_false_not_failed(self):
        self._login()
        with mock.patch(ADMIN + 'new_device_status', side_effect=RuntimeError('boom')):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data['ok'])
        self.assertIsNone(data['state'])     # 일시 오류일 뿐, 작업 실패가 아니다

    def test_without_edit_controllers_is_403(self):
        for name in ('viewer', 'settings_only'):
            self._login(name)
            with mock.patch(ADMIN + 'new_device_status') as svc:
                resp = self._get()
            self.assertEqual(resp.status_code, 403, name)
            svc.assert_not_called()

    def test_login_required(self):
        with mock.patch(ADMIN + 'new_device_status') as svc:
            resp = self._get()
        self.assertNotEqual(resp.status_code, 200)
        svc.assert_not_called()


class _NodeActionCases(object):
    """노드 하나에 대한 POST 라우트의 공통 계약: 권한·스코프·입력.

    하위 클래스가 URL, 본문, 서비스 함수 이름을 정한다.
    """
    URL = None
    SERVICE = None
    BODY = None
    RESULT = {'ok': True, 'error': None}

    def _post(self, body=None):
        return self.client.post(self.URL, json=dict(self.BODY) if body is None else body)

    def _call(self, body=None, device_id='dev-uuid-5', can_operate=True, **svc):
        svc.setdefault('return_value', self.RESULT)
        with mock.patch(DEVICE_FOR_NODE, return_value=device_id), \
                mock.patch(SCOPE_CAN, return_value=can_operate) as scope_check, \
                mock.patch(ADMIN + self.SERVICE, **svc) as service:
            resp = self._post(body)
        return resp, service, scope_check

    def test_calls_the_service_and_returns_its_result(self):
        self._login()
        resp, service, scope_check = self._call()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), self.RESULT)
        service.assert_called_once()
        self.assertEqual(service.call_args[0][0], 5)
        scope_check.assert_called_once_with('dev-uuid-5')

    def test_service_exception_becomes_json_error(self):
        self._login()
        resp, _, _ = self._call(side_effect=RuntimeError('boom'))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data['ok'])
        self.assertTrue(data['error'])
        self.assertNotIn('boom', data['error'])

    def test_group_scope_denial_is_403_and_service_untouched(self):
        self._login()
        resp, service, _ = self._call(can_operate=False)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.get_json()['ok'])
        self.assertTrue(resp.get_json()['error'])
        service.assert_not_called()

    def test_node_without_an_aot_device_has_no_scope_to_check(self):
        self._login()
        resp, service, scope_check = self._call(device_id=None, can_operate=False)
        self.assertEqual(resp.status_code, 200)
        scope_check.assert_not_called()
        service.assert_called_once()

    def test_bad_node_id_is_400(self):
        self._login()
        for bad in ('abc', None, [1]):
            body = dict(self.BODY)
            body['node_id'] = bad
            resp, service, _ = self._call(body=body)
            self.assertEqual(resp.status_code, 400, bad)
            service.assert_not_called()

    def test_non_object_body_is_400(self):
        self._login()
        resp, service, _ = self._call(body=['not', 'an', 'object'])
        self.assertEqual(resp.status_code, 400)
        service.assert_not_called()

    def test_without_edit_controllers_is_403(self):
        for name in ('viewer', 'settings_only'):
            self._login(name)
            resp, service, _ = self._call()
            self.assertEqual(resp.status_code, 403, name)
            service.assert_not_called()

    def test_login_required(self):
        resp, service, _ = self._call()
        self.assertNotEqual(resp.status_code, 200)
        service.assert_not_called()


class TestShare(_NodeActionCases, _MatterAppFixture):
    URL = '/settings/matter/share'
    SERVICE = 'open_share_window'
    BODY = {'node_id': 5}
    RESULT = {'ok': True, 'error': None, 'manual_code': '12345678901',
              'qr_code': 'MT:Y.K9042C00KA0648G00', 'expires_in': 900}

    def test_default_timeout_and_no_store(self):
        self._login()
        resp, service, _ = self._call()
        service.assert_called_once_with(5, 900)
        self.assertIn('no-store', resp.headers.get('Cache-Control', ''))

    def test_timeout_is_passed_through(self):
        self._login()
        body = {'node_id': 5, 'timeout_s': 300}
        _, service, _ = self._call(body=body)
        service.assert_called_once_with(5, 300)

    def test_pairing_codes_are_never_logged(self):
        self._login()
        with _capture_aot_logs(self) as logs:
            self._call()
            self._call(side_effect=RuntimeError('boom'))
        text = '\n'.join(logs.output)
        self.assertNotIn(self.RESULT['manual_code'], text)
        self.assertNotIn(self.RESULT['qr_code'], text)


class TestShareClose(_NodeActionCases, _MatterAppFixture):
    URL = '/settings/matter/share/close'
    SERVICE = 'close_share_window'
    BODY = {'node_id': 5}

    def test_closes_that_node(self):
        self._login()
        _, service, _ = self._call()
        service.assert_called_once_with(5)


class TestFabricRemove(_NodeActionCases, _MatterAppFixture):
    URL = '/settings/matter/fabrics/remove'
    SERVICE = 'remove_other_fabric'
    BODY = {'node_id': 5, 'fabric_index': 3}

    def test_passes_the_fabric_index(self):
        self._login()
        _, service, _ = self._call()
        service.assert_called_once_with(5, 3)

    def test_service_refusal_of_own_fabric_is_returned(self):
        self._login()
        refusal = {'ok': False, 'error': "This is AoT's own connection."}
        resp, _, _ = self._call(return_value=refusal)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), refusal)

    def test_bad_fabric_index_is_400(self):
        self._login()
        for bad in ('x', None, {}):
            resp, service, _ = self._call(body={'node_id': 5, 'fabric_index': bad})
            self.assertEqual(resp.status_code, 400, bad)
            service.assert_not_called()


class TestUpdateCheck(_NodeActionCases, _MatterAppFixture):
    URL = '/settings/matter/update/check'
    SERVICE = 'check_update'
    BODY = {'node_id': 5}
    RESULT = {'ok': True, 'error': None, 'update': {
        'version': 7, 'version_string': '1.2.0', 'release_notes_url': 'https://example.com/n',
        'source': 'main-net-dcl', 'certified': True}}

    def test_checks_that_node(self):
        self._login()
        _, service, _ = self._call()
        service.assert_called_once_with(5)


class TestUpdateStart(_NodeActionCases, _MatterAppFixture):
    URL = '/settings/matter/update/start'
    SERVICE = 'start_update'
    BODY = {'node_id': 5, 'version': 7}

    def test_passes_the_version(self):
        self._login()
        _, service, _ = self._call()
        service.assert_called_once_with(5, 7)

    def test_bad_version_is_400(self):
        self._login()
        for bad in ('x', None, {}):
            resp, service, _ = self._call(body={'node_id': 5, 'version': bad})
            self.assertEqual(resp.status_code, 400, bad)
            service.assert_not_called()


class TestFabricsList(_MatterAppFixture):
    RESULT = {'ok': True, 'error': None, 'supported': 5, 'used': 2, 'fabrics': [
        {'fabric_index': 1, 'label': 'AoT', 'vendor_id': 4939, 'vendor_name': '', 'own': True},
        {'fabric_index': 2, 'label': 'Home', 'vendor_id': 4937, 'vendor_name': 'Apple',
         'own': False}]}

    def _get(self, node='5', device_id='dev-uuid-5', can_operate=True, **svc):
        svc.setdefault('return_value', self.RESULT)
        with mock.patch(DEVICE_FOR_NODE, return_value=device_id), \
                mock.patch(SCOPE_CAN, return_value=can_operate), \
                mock.patch(ADMIN + 'list_fabrics', **svc) as service:
            resp = self.client.get('/settings/matter/fabrics/' + node)
        return resp, service

    def test_returns_the_service_result(self):
        self._login()
        resp, service = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), self.RESULT)
        service.assert_called_once_with(5)

    def test_viewing_needs_only_view_settings(self):
        self._login('viewer')
        resp, service = self._get()
        self.assertEqual(resp.status_code, 200)
        service.assert_called_once_with(5)

    def test_without_view_settings_is_403(self):
        with self.app.app_context():
            from aot.databases.models import Role
            role = Role.query.filter_by(name='viewer').first()
            role.view_settings = False
            role.save()
        self._login('viewer')
        resp, service = self._get()
        self.assertEqual(resp.status_code, 403)
        service.assert_not_called()

    def test_group_scope_denial_is_403(self):
        self._login()
        resp, service = self._get(can_operate=False)
        self.assertEqual(resp.status_code, 403)
        service.assert_not_called()

    def test_non_integer_node_never_reaches_the_service(self):
        self._login()
        resp, service = self._get(node='abc')
        self.assertEqual(resp.status_code, 404)    # <int:node_id> 가 막는다
        service.assert_not_called()

    def test_service_exception_becomes_json_error(self):
        self._login()
        resp, _ = self._get(side_effect=RuntimeError('boom'))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['fabrics'], [])

    def test_login_required(self):
        resp, service = self._get()
        self.assertNotEqual(resp.status_code, 200)
        service.assert_not_called()


class TestTemplateRendersInRealApp(unittest.TestCase):
    """실제 앱(레이아웃·사이드바 포함)으로 템플릿을 렌더한다.

    위의 최소 앱은 render_template 을 가로채므로 Jinja 문법 오류나
    url_for 오타는 거기서 안 잡힌다. 여기서는 conftest 의 임시 DB 위에 진짜
    create_app() 을 올려 연결 안 됨/연결됨 두 상태를 모두 렌더한다.
    """

    @classmethod
    def setUpClass(cls):
        from aot.aot_flask.app import create_app
        from aot.aot_flask.extensions import db
        from aot.databases.models import Misc, Role, User

        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['SESSION_PROTECTION'] = None
        with cls.app.app_context():
            # 설정 페이지 렌더는 전역 컨텍스트 프로세서를 타고, 그쪽이 Misc 를
            # 무조건 읽는다. 실제 설치에는 항상 있는 행이다.
            misc = Misc.query.first()
            cls._misc_created = misc is None
            if misc is None:
                misc = Misc()
                db.session.add(misc)
                cls._misc_matter_enabled = None
            else:
                cls._misc_matter_enabled = misc.matter_enabled
            misc.matter_enabled = True
            role = Role()
            role.name = 'matter_page_admin'
            role.view_settings = True
            role.edit_settings = True
            role.edit_controllers = True
            db.session.add(role)
            db.session.commit()
            user = User()
            user.name = 'matter_page_admin'
            user.email = 'matter_page_admin@example.com'
            user.is_enabled = True
            user.is_approved = True
            user.role_id = role.id
            user.set_password('correct horse battery staple')
            db.session.add(user)
            db.session.commit()
            cls._login_id = user.get_id()

    @classmethod
    def tearDownClass(cls):
        """만든 역할·사용자를 지우고 Misc 를 되돌린다.

        이 DB 는 conftest 가 세션 내내 공유하는 임시 DB 다. 조작 권한이 있는
        사용자를 남겨 두면 뒤에 도는 시험이 그 사람을 "실제 사용자" 로 센다 —
        `test_scope_groups` 의 `grant_impact` 시험 4건이 전체 묶음에서만
        `matter_page_admin` 을 "잃는 사람" 으로 세어 깨졌다.
        """
        from aot.aot_flask.extensions import db
        from aot.databases.models import Misc, Role, User

        with cls.app.app_context():
            db.session.rollback()
            User.query.filter(User.name == 'matter_page_admin').delete(
                synchronize_session=False)
            Role.query.filter(Role.name == 'matter_page_admin').delete(
                synchronize_session=False)
            misc = Misc.query.first()
            if misc is not None:
                if cls._misc_created:
                    db.session.delete(misc)
                else:
                    misc.matter_enabled = cls._misc_matter_enabled
            db.session.commit()
            db.session.remove()

    def _get(self, status, nodes, bluetooth=BLE_ON):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = self._login_id
            sess['_fresh'] = True
        status = dict(status, bluetooth_enabled=bool((bluetooth or {}).get('bluetooth_enabled')))
        with mock.patch('aot.aot_flask.utils.utils_matter.server_status', return_value=status), \
                mock.patch('aot.aot_flask.utils.utils_matter.list_nodes', return_value=nodes), \
                mock.patch('aot.aot_flask.utils.utils_matter_admin.bluetooth_status',
                           return_value=bluetooth):
            return client.get('/settings/matter')

    def test_disconnected_page_shows_how_to_enable_and_disables_add(self):
        resp = self._get(DOWN, [])
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('COMPOSE_PROFILES=matter', html)
        self.assertIn('check_matter_host.sh', html)
        self.assertIn('id="matter-add-btn"', html)
        self.assertRegex(html, r'id="matter-add-btn"[^>]*disabled')
        self.assertIn('href="/settings/matter"', html)   # 사이드바 링크

    def test_connected_page_embeds_nodes_safely(self):
        resp = self._get(UP, NODES)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertNotRegex(html, r'id="matter-add-btn"[^>]*disabled')
        self.assertIn('aot-pill-btn-danger', html)
        # 노드 이름의 마크업이 <script> 안에서 태그로 풀리지 않는다.
        self.assertNotIn('Plug <b>1</b>', html)

    def test_new_device_section_with_server_down(self):
        html = self._get(DOWN, [], bluetooth=BLE_OFF).get_data(as_text=True)
        self.assertIn('id="matter-new-btn"', html)
        self.assertRegex(html, r'id="matter-new-btn"[^>]*disabled')
        self.assertRegex(html, r'id="matter-new-code"[^>]*disabled')
        self.assertIn('value="none"', html)               # 이미 네트워크에 있는 장치
        self.assertIn('Already on the network (Ethernet)', html)
        # 서버가 없으면 블루투스 안내가 아니라 "서버부터" 안내가 나온다.
        self.assertNotIn('id="matter-new-ble-note"', html)

    def test_new_device_section_with_bluetooth_disabled(self):
        html = self._get(UP, NODES, bluetooth=BLE_OFF).get_data(as_text=True)
        self.assertRegex(html, r'id="matter-new-btn"(?![^>]*disabled)')   # JS 가 종류에 따라 끈다
        self.assertIn('id="matter-new-ble-note"', html)
        self.assertIn('check_matter_host.sh --ble', html)
        self.assertIn('docker-compose.matter-ble.yml', html)
        self.assertIn('value="none"', html)
        self.assertIn('Already on the network (Ethernet)', html)
        self.assertIn('var BLUETOOTH = false;', html)

    def test_new_device_section_with_bluetooth_enabled(self):
        html = self._get(UP, NODES, bluetooth=BLE_ON).get_data(as_text=True)
        self.assertIn('id="matter-new-btn"', html)
        self.assertNotIn('id="matter-new-ble-note"', html)
        self.assertIn('var BLUETOOTH = true;', html)
        # 비밀번호 칸은 비밀번호 칸이고 브라우저가 저장하지 않는다.
        self.assertRegex(html, r'type="password"[^>]*autocomplete="new-password"|'
                               r'autocomplete="new-password"[^>]*type="password"')
        self.assertRegex(html, r'<textarea id="matter-new-dataset"[^>]*autocomplete="off"')


class TestTemplateStaticChecks(unittest.TestCase):
    """템플릿 자체 — 서버 없이 읽을 수 있는 약속."""

    @classmethod
    def setUpClass(cls):
        root = os.path.join(os.path.dirname(__file__), '..', 'aot_flask', 'templates')
        with open(os.path.join(root, 'settings', 'matter.html'), encoding='utf-8') as fh:
            cls.template = fh.read()
        with open(os.path.join(root, 'layout-settings.html'), encoding='utf-8') as fh:
            cls.sidebar = fh.read()

    def test_remove_button_is_danger_not_primary(self):
        self.assertIn('aot-pill-btn-danger', self.template)
        # 주 동작은 셋뿐: 공유 장치 "Add", 새 장치 "Add", 펌웨어 "Update".
        self.assertEqual(self.template.count('aot-pill-btn-primary'), 3)

    def test_sidebar_links_to_the_page(self):
        self.assertIn("routes_settings.settings_matter", self.sidebar)
        self.assertIn("active_settings == 'matter'", self.sidebar)

    def test_new_device_secrets_are_not_kept_by_the_browser(self):
        self.assertIn('autocomplete="new-password"', self.template)
        self.assertIn('type="password"', self.template)
        # 비밀번호·데이터셋은 저장소(localStorage/sessionStorage)에 두지 않는다.
        # sessionStorage 는 진행 중인 작업 id 하나만 쓴다.
        self.assertNotIn('localStorage', self.template)
        self.assertEqual(self.template.count('sessionStorage.setItem'), 1)
        self.assertIn("JSON.stringify({id: jobId, t: startedAt})", self.template)

    def test_device_text_goes_through_textcontent(self):
        # 장치가 정한 이름·버전·라벨을 HTML 로 넣는 자리가 없다.
        self.assertNotIn('innerHTML', self.template)

    def test_share_and_firmware_buttons_are_secondary(self):
        self.assertRegex(self.template,
                         r"node\('button', 'btn aot-pill-btn aot-pill-btn-secondary', T\.share\)")
        self.assertRegex(self.template,
                         r"node\('button', 'btn aot-pill-btn aot-pill-btn-secondary', T\.firmware\)")
        self.assertRegex(self.template,
                         r"node\('button', 'btn aot-pill-btn aot-pill-btn-danger', T\.disconnect\)")

    def test_pairing_code_field_is_plain_text(self):
        # MT: 코드가 있어 inputmode numeric 이면 안 된다.
        self.assertNotIn('inputmode', self.template)
        self.assertIn('autocomplete="off"', self.template)


if __name__ == '__main__':
    unittest.main()


class TestAdopt(_MatterAppFixture):
    """고아 노드(AoT 장치 없음)에 AoT 장치를 만드는 길 — 새 장치 등록 중 탭을 닫은 경우 등."""

    def test_adopt_calls_service(self):
        self._login()
        with mock.patch('aot.aot_flask.utils.utils_matter.adopt_node',
                        return_value={'ok': True, 'error': None, 'device_id': 'd1',
                                      'rebound': False, 'warnings': []}) as svc:
            resp = self.client.post('/settings/matter/adopt', json={'node_id': 7})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['ok'])
        svc.assert_called_once_with(7)

    def test_adopt_bad_input(self):
        self._login()
        resp = self.client.post('/settings/matter/adopt', json={'node_id': 'x'})
        self.assertEqual(resp.status_code, 400)


class TestNodeGateFailsClosed(_MatterAppFixture):
    """장치별 동작의 그룹 스코프 검사는 실패하면 막는다(검토)."""

    def test_lookup_error_is_503_not_allowed(self):
        self._login()
        with mock.patch('aot.aot_flask.routes_settings._matter_device_for_node',
                        side_effect=RuntimeError('db down')), \
                mock.patch('aot.aot_flask.utils.utils_matter_admin.open_share_window') as svc:
            resp = self.client.post('/settings/matter/share', json={'node_id': 5})
        self.assertEqual(resp.status_code, 503)
        svc.assert_not_called()

    def test_orphan_node_needs_unrestricted_access_when_scoping(self):
        self._login()
        with mock.patch('aot.aot_flask.routes_settings._matter_device_for_node',
                        return_value=None), \
                mock.patch('aot.aot_flask.access.scope.scoping_active', return_value=True), \
                mock.patch('aot.aot_flask.access.scope.is_exempt', return_value=False), \
                mock.patch('aot.aot_flask.utils.utils_matter_admin.open_share_window') as svc:
            resp = self.client.post('/settings/matter/share', json={'node_id': 9})
        self.assertEqual(resp.status_code, 403)
        svc.assert_not_called()
