# -*- coding: utf-8 -*-
"""AI 설정 드로어의 키 평문 노출 + 지식 목록 API 권한 누락 회귀 가드.

1. `/ai/agent/options/<id>` 가 돌려주는 HTML 에 저장된 API 키(에이전트
   서비스 키, password 형 커스텀 옵션)가 `value` 로 그대로 박혀 내려갔다.
   이제는 빈 password 칸만 내려가고, 저장된 값이 있을 때만 "비워 두면 유지"
   안내가 뜬다. 저장(`/ai/agent/mod/<id>`)은 빈 칸이면 기존 값을 그대로 둔다.
2. `GET /api/v1/ai/library/knowledge` 는 로그인만 보고 권한을 안 봤다 —
   페이지(edit_settings 필요)를 못 여는 계정도 API 로 라이브러리 전체를 읽었다.
3. `GET /api/v1/ai/library/sources` 가 각 소스의 config_json 을 통째로
   돌려줘 프리셋 소스의 api_key/커스텀 REST 소스의 auth_value 가 그대로
   내려갔다. 이제는 마스킹하고 has_api_key/has_auth_value 플래그만 준다.
   저장(`PATCH .../sources/<id>`)은 빈 칸이면 기존 키를 그대로 둔다.
   SmartFarmKorea 농가/작기 조회도 키 칸이 비어 있어도 source_id 로 저장된
   키를 대신 쓴다.

임시 sqlite 위에 필요한 블루프린트만 올린다 (라이브 DB 미사용).
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))


SECRET_KEY_VALUE = 'sk-TEST-SECRET-1234567890'
SECRET_TOKEN_VALUE = 'tok-CUSTOM-SECRET-abcdef'
SOURCE_API_KEY_VALUE = 'sfk-TEST-SOURCE-KEY-999'
SOURCE_AUTH_VALUE = 'Bearer TEST-AUTH-VALUE-777'

_ENGINE_INFO = {
    'ai_category': 'llm',
    'ai_name': 'Test Engine',
    'models': [{'value': 'test-model', 'label': 'Test Model'}],
    'custom_options': [
        {'id': 'svc_token', 'name': 'Service Token', 'type': 'password', 'default': ''},
        {'id': 'region', 'name': 'Region', 'type': 'text', 'default': 'kr'},
    ],
}


def _engine_info(_model_type):
    # 라우트가 custom_options 를 제자리에서 고치므로 매번 새 사본을 준다.
    return copy.deepcopy(_ENGINE_INFO)


class _AIAppFixture(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        import flask_login
        from flask_babel import Babel

        from aot.aot_flask.extensions import db, csrf
        import aot.databases.models  # noqa: F401 — 모델 등록
        from aot.databases.models import AIAgent, AIContextSource, AIEntry, Role, User
        from aot.aot_flask import routes_ai_agent, routes_ai_library, routes_settings

        self._tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp.name, 'test.db')

        template_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', 'aot_flask', 'templates'))
        app = Flask(__name__, template_folder=template_dir)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(db_path)
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['TESTING'] = True
        app.config['SESSION_PROTECTION'] = None

        db.init_app(app)
        csrf.init_app(app)
        Babel(app)
        app.register_blueprint(routes_ai_agent.blueprint)
        app.register_blueprint(routes_ai_library.ai_library_bp)
        # api_key_macro 가 url_for('routes_settings.settings_api_key') 를 쓴다.
        app.register_blueprint(routes_settings.blueprint)

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
        self.db = db

        with app.app_context():
            db.create_all()

            admin_role = Role()
            admin_role.name = 'Admin'
            admin_role.edit_settings = True
            admin_role.edit_controllers = True
            admin_role.view_settings = True
            guest_role = Role()
            guest_role.name = 'Guest'
            guest_role.edit_settings = False
            guest_role.edit_controllers = False
            guest_role.view_settings = False
            db.session.add_all([admin_role, guest_role])
            db.session.commit()

            def _user(name, role):
                u = User()
                u.name = name
                u.email = '{}@example.com'.format(name)
                u.is_enabled = True
                u.is_approved = True
                u.role_id = role.id
                u.set_password('correct horse battery staple')
                db.session.add(u)
                return u

            admin = _user('admin', admin_role)
            guest = _user('guest', guest_role)
            db.session.commit()
            self._admin_login = admin.get_id()
            self._guest_login = guest.get_id()

            entry = AIEntry(name='Test Service', model_type='test_engine',
                            model_name='test-model', api_key=SECRET_KEY_VALUE)
            db.session.add(entry)
            db.session.commit()
            agent = AIAgent(name='Test Agent', entry_id=entry.unique_id,
                            custom_options_json=json.dumps({
                                'svc_token': SECRET_TOKEN_VALUE,
                                'region': 'kr',
                            }))
            db.session.add(agent)
            db.session.commit()
            self.agent_id = agent.unique_id
            self.entry_id = entry.unique_id

            preset_source = AIContextSource(
                facility_id='default', source_name='SmartFarmKorea Test',
                source_type='rest_api', parameter_name='sfk_test',
                config_json=json.dumps({
                    'preset_key': 'smartfarmkorea',
                    'api_key': SOURCE_API_KEY_VALUE,
                    'operations': ['env'],
                }),
                is_active=True, is_enabled=False)
            db.session.add(preset_source)
            rest_source = AIContextSource(
                facility_id='default', source_name='Custom REST Test',
                source_type='rest_api', parameter_name='rest_test',
                config_json=json.dumps({
                    'endpoint_url': 'https://example.com/data',
                    'auth_type': 'bearer',
                    'auth_value': SOURCE_AUTH_VALUE,
                }),
                is_active=True, is_enabled=False)
            db.session.add(rest_source)
            db.session.commit()
            self.preset_source_id = preset_source.source_id
            self.rest_source_id = rest_source.source_id

        self.client = app.test_client()
        patcher = mock.patch.object(routes_ai_agent.AIAgentService,
                                    'get_engine_info', side_effect=_engine_info)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def _login(self, login_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = login_id
            sess['_fresh'] = True

    def _stored(self):
        from aot.databases.models import AIAgent, AIEntry
        with self.app.app_context():
            entry = AIEntry.query.filter_by(unique_id=self.entry_id).first()
            agent = AIAgent.query.filter_by(unique_id=self.agent_id).first()
            return entry.api_key, json.loads(agent.custom_options_json or '{}')

    def _set_stored(self, api_key, custom):
        from aot.databases.models import AIAgent, AIEntry
        with self.app.app_context():
            AIEntry.query.filter_by(unique_id=self.entry_id).first().api_key = api_key
            AIAgent.query.filter_by(unique_id=self.agent_id).first() \
                .custom_options_json = json.dumps(custom)
            self.db.session.commit()

    def _stored_source_config(self, source_id):
        from aot.databases.models import AIContextSource
        with self.app.app_context():
            source = AIContextSource.query.filter_by(source_id=source_id).first()
            return json.loads(source.config_json or '{}')


class TestOptionsDoNotLeakStoredKeys(_AIAppFixture):

    def _options_html(self):
        self._login(self._admin_login)
        resp = self.client.get('/ai/agent/options/{}'.format(self.agent_id))
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload['status'], 'success')
        return resp.get_data(as_text=True), payload['html']

    def test_stored_secrets_never_reach_the_browser(self):
        raw, html = self._options_html()
        # 응답 전체(JSON 포함)에 어떤 형태로도 실리면 안 된다.
        self.assertNotIn(SECRET_KEY_VALUE, raw)
        self.assertNotIn(SECRET_TOKEN_VALUE, raw)
        self.assertNotIn(SECRET_KEY_VALUE, html)
        self.assertNotIn(SECRET_TOKEN_VALUE, html)

    def test_secret_fields_are_empty_password_inputs(self):
        _, html = self._options_html()
        self.assertIn('type="password" name="custom_svc_token"', html)
        self.assertNotIn('type="text" name="custom_svc_token"', html)
        # 서비스 키 칸: 보이는 입력은 password, 값은 비어 있다.
        self.assertRegex(html, r'<input type="password" class="form-control aot-modern-input"\s+value=""')
        # 비밀이 아닌 옵션은 그대로 값을 채운다 — 동작은 바뀌지 않았다.
        self.assertIn('name="custom_region" class="form-control aot-modern-input" value="kr"', html)

    def test_placeholder_only_when_a_value_is_saved(self):
        _, html = self._options_html()
        self.assertIn('Leave blank to keep existing key', html)
        self.assertIn('placeholder="Leave blank to keep"', html)

        self._set_stored('', {'region': 'kr'})
        _, html = self._options_html()
        self.assertNotIn('Leave blank to keep existing key', html)
        self.assertNotIn('placeholder="Leave blank to keep"', html)


class TestSaveKeepsSecretsWhenBlank(_AIAppFixture):

    def _post(self, **fields):
        self._login(self._admin_login)
        data = {'name': 'Test Agent', 'custom_region': 'jp'}
        data.update(fields)
        return self.client.post('/ai/agent/mod/{}'.format(self.agent_id), data=data)

    def test_blank_fields_keep_existing_values(self):
        resp = self._post(api_key='', custom_svc_token='')
        self.assertEqual(resp.status_code, 302)
        api_key, custom = self._stored()
        self.assertEqual(api_key, SECRET_KEY_VALUE)
        self.assertEqual(custom['svc_token'], SECRET_TOKEN_VALUE)
        # 다른 옵션은 평소처럼 저장된다.
        self.assertEqual(custom['region'], 'jp')

    def test_whitespace_only_keeps_existing_values(self):
        self._post(api_key='   ', custom_svc_token='  ')
        api_key, custom = self._stored()
        self.assertEqual(api_key, SECRET_KEY_VALUE)
        self.assertEqual(custom['svc_token'], SECRET_TOKEN_VALUE)

    def test_non_empty_values_overwrite(self):
        with mock.patch('aot.aot_flask.utils.utils_settings.auto_register_api_key') as reg:
            self._post(api_key='sk-NEW-KEY-000', custom_svc_token='tok-NEW-000')
        api_key, custom = self._stored()
        self.assertEqual(api_key, 'sk-NEW-KEY-000')
        self.assertEqual(custom['svc_token'], 'tok-NEW-000')
        reg.assert_called_once()


class TestKnowledgeApiRequiresPermission(_AIAppFixture):

    URL = '/api/v1/ai/library/knowledge'

    def test_user_without_edit_settings_is_rejected(self):
        self._login(self._guest_login)
        from aot.aot_flask import routes_ai_library
        with mock.patch.object(routes_ai_library.knowledge_library_service, 'browse') as browse:
            resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json(), {'success': False, 'error': 'Permission denied'})
        browse.assert_not_called()

    def test_user_with_edit_settings_gets_the_list(self):
        self._login(self._admin_login)
        from aot.aot_flask import routes_ai_library
        svc = routes_ai_library.knowledge_library_service
        with mock.patch.object(svc, 'browse', return_value={'items': [], 'total': 0}), \
                mock.patch.object(svc, 'tag_counts', return_value=[]), \
                mock.patch.object(svc, 'summary', return_value={}):
            resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])


class TestLibrarySourcesListDoesNotLeakStoredKeys(_AIAppFixture):

    def _sources(self):
        self._login(self._admin_login)
        resp = self.client.get('/api/v1/ai/library/sources')
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True), resp.get_json()['sources']

    def test_raw_secrets_never_reach_the_browser(self):
        raw, _ = self._sources()
        self.assertNotIn(SOURCE_API_KEY_VALUE, raw)
        self.assertNotIn(SOURCE_AUTH_VALUE, raw)

    def test_flags_and_blank_config_fields(self):
        _, sources = self._sources()
        by_id = {s['source_id']: s for s in sources}

        preset = by_id[self.preset_source_id]
        self.assertTrue(preset['has_api_key'])
        self.assertFalse(preset.get('has_auth_value'))
        self.assertEqual(json.loads(preset['config_json'])['api_key'], '')

        rest = by_id[self.rest_source_id]
        self.assertTrue(rest['has_auth_value'])
        self.assertFalse(rest.get('has_api_key'))
        self.assertEqual(json.loads(rest['config_json'])['auth_value'], '')

    def test_no_flags_when_nothing_is_stored(self):
        self._patch_source_config(self.rest_source_id, {'endpoint_url': 'https://example.com'})
        _, sources = self._sources()
        rest = next(s for s in sources if s['source_id'] == self.rest_source_id)
        self.assertFalse(rest['has_api_key'])
        self.assertFalse(rest['has_auth_value'])

    def _patch_source_config(self, source_id, config):
        from aot.databases.models import AIContextSource
        with self.app.app_context():
            AIContextSource.query.filter_by(source_id=source_id).first() \
                .config_json = json.dumps(config)
            self.db.session.commit()


class TestLibrarySourcePatchKeepsSecretsWhenBlank(_AIAppFixture):

    def _patch(self, source_id, **fields):
        self._login(self._admin_login)
        payload = {'source_name': 'Renamed', 'config_json': fields}
        return self.client.patch(
            '/api/v1/ai/library/sources/{}'.format(source_id),
            data=json.dumps(payload), content_type='application/json')

    def test_blank_api_key_keeps_existing(self):
        resp = self._patch(self.preset_source_id, preset_key='smartfarmkorea',
                            api_key='', operations=['env'])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._stored_source_config(self.preset_source_id)['api_key'],
                          SOURCE_API_KEY_VALUE)

    def test_whitespace_only_api_key_keeps_existing(self):
        self._patch(self.preset_source_id, preset_key='smartfarmkorea',
                    api_key='   ', operations=['env'])
        self.assertEqual(self._stored_source_config(self.preset_source_id)['api_key'],
                          SOURCE_API_KEY_VALUE)

    def test_non_blank_api_key_overwrites(self):
        resp = self._patch(self.preset_source_id, preset_key='smartfarmkorea',
                            api_key='sk-NEW-KEY', operations=['env'])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._stored_source_config(self.preset_source_id)['api_key'],
                          'sk-NEW-KEY')

    def test_blank_auth_value_keeps_existing(self):
        resp = self._patch(self.rest_source_id, endpoint_url='https://example.com/data',
                            auth_type='bearer', auth_value='')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._stored_source_config(self.rest_source_id)['auth_value'],
                          SOURCE_AUTH_VALUE)

    def test_non_blank_auth_value_overwrites(self):
        self._patch(self.rest_source_id, endpoint_url='https://example.com/data',
                    auth_type='bearer', auth_value='Bearer NEW-VALUE')
        self.assertEqual(self._stored_source_config(self.rest_source_id)['auth_value'],
                          'Bearer NEW-VALUE')

    def test_response_does_not_echo_stored_secret(self):
        resp = self._patch(self.preset_source_id, preset_key='smartfarmkorea',
                            api_key='', operations=['env'])
        raw = resp.get_data(as_text=True)
        self.assertNotIn(SOURCE_API_KEY_VALUE, raw)


class TestSmartfarmkoreaFarmsUsesStoredKeyWhenBlank(_AIAppFixture):

    URL = '/api/v1/ai/library/smartfarmkorea/farms'

    def test_blank_api_key_falls_back_to_stored_key_via_source_id(self):
        self._login(self._admin_login)
        with mock.patch('aot.ai.context.ext.smartfarmkorea_client.resolve_farms',
                         return_value=([{'value': 'u1', 'label': 'Farm 1',
                                         'userId': 'u1'}], None)) as resolve:
            resp = self.client.post(self.URL, data=json.dumps({
                'preset_key': 'smartfarmkorea', 'api_key': '',
                'source_id': self.preset_source_id,
            }), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])
        resolve.assert_called_once()
        self.assertEqual(resolve.call_args[0][0], SOURCE_API_KEY_VALUE)

    def test_blank_api_key_without_source_id_is_rejected(self):
        self._login(self._admin_login)
        resp = self.client.post(self.URL, data=json.dumps({
            'preset_key': 'smartfarmkorea', 'api_key': '',
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()['success'])

    def test_typed_key_overrides_stored_key(self):
        self._login(self._admin_login)
        with mock.patch('aot.ai.context.ext.smartfarmkorea_client.resolve_farms',
                         return_value=([], None)) as resolve:
            self.client.post(self.URL, data=json.dumps({
                'preset_key': 'smartfarmkorea', 'api_key': 'sk-TYPED-KEY',
                'source_id': self.preset_source_id,
            }), content_type='application/json')
        self.assertEqual(resolve.call_args[0][0], 'sk-TYPED-KEY')


if __name__ == '__main__':
    unittest.main()
