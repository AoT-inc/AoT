# coding=utf-8
"""외부 MCP 의 중앙 인증 — 설정 모달·계정 연결·토큰 확인.

고정하는 계약:

  1. 주소는 설정값이다. 발급자는 https(루프백만 http), MCP 공개 주소는 경로가 있는 주소.
     환경변수가 화면 값보다 앞선다. 비밀은 암호화해 저장한다.
  2. Bearer 가 JWT 면 중앙 인증, 아니면 예전처럼 API 키. 중앙 인증이 꺼져 있으면 JWT 는 401.
  3. 서명·aud 가 맞는 토큰이라도 계정 연결이 없으면 HTTP 오류가 아니라 도구 오류로 안내한다.
  4. 실제 권한 = 역할 ∩ 토큰 범위(aot.read / aot.control / aot.config).
  5. 401 에는 보호 자원 메타데이터 주소를 싣고, 그 메타데이터는 설정한 인가 서버를 알린다.
  6. 계정 연결은 PKCE + state, 로그인한 그 사람에게만 잇는다. 다른 사람에게 이어진 sub 는 거절.

진짜 ES256 키로 서명한 토큰을 쓴다(공용 검증 코드의 짜임까지 확인한다). 라이브 DB 는 쓰지 않는다.
"""
import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from joserfc import jwt
from joserfc.jwk import ECKey

ISSUER = 'https://auth.example.net'
RESOURCE = 'https://farm.example.org/mcp'
WEB = 'https://farm.example.org'
KEY = ECKey.generate_key('P-256', parameters={'kid': 'k1'})


def _access_token(**over):
    now = int(time.time())
    claims = {'iss': ISSUER, 'sub': 'acct-1', 'aud': RESOURCE, 'client_id': 'claude', 'scope': 'aot.read',
              'gid': 'g1', 'iat': now, 'nbf': now, 'exp': now + 3600, 'jti': 'j1', 'client_name': 'Claude'}
    claims.update(over)
    return jwt.encode({'alg': 'ES256', 'typ': 'at+jwt', 'kid': 'k1'}, claims, KEY)


def _id_token(nonce, sub='acct-1', aud='link-client'):
    now = int(time.time())
    return jwt.encode({'alg': 'ES256', 'typ': 'JWT', 'kid': 'k1'},
                      {'iss': ISSUER, 'sub': sub, 'aud': aud, 'iat': now, 'exp': now + 300, 'nonce': nonce,
                       'email': 'staff@example.net'}, KEY)


class _FakeHttp:
    """공용 검증 코드의 받아 오기 — JWKS 만 있고 폐지 목록은 없다(없으면 마지막 것으로 계속)."""

    def get(self, url):
        if url.endswith('/.well-known/jwks.json'):
            return 200, {}, json.dumps({'keys': [KEY.as_dict(private=False)]}).encode()
        return 404, {}, b''


class _Base(unittest.TestCase):

    def setUp(self):
        from flask import Flask
        import flask_login
        from flask_babel import Babel

        from aot.aot_flask.extensions import db, csrf
        import aot.databases.models  # noqa: F401
        from aot.databases.models import AIGlobalSettings, Misc, Role, User
        from aot.aot_flask import routes_mcp_auth
        from aot.tools import mcp_central
        from aot.tools.central_verify import CentralTokenVerifier

        self._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(self._tmp.name, 't.db'),
                          SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY='t', WTF_CSRF_ENABLED=False,
                          TESTING=True, SESSION_PROTECTION=None)
        db.init_app(app)
        csrf.init_app(app)
        Babel(app)
        app.register_blueprint(routes_mcp_auth.blueprint)
        login = flask_login.LoginManager()
        login.init_app(app)
        login.user_loader(lambda uid: User.query.filter(User.id == int(uid)).first())
        self.app, self.db = app, db

        with app.app_context():
            db.create_all()
            admin = Role(name='Admin', edit_settings=True, view_settings=True, edit_controllers=True, edit_users=True)
            viewer = Role(name='Monitor', view_settings=True)
            db.session.add_all([admin, viewer])
            db.session.commit()
            for name, role in (('boss', admin), ('watcher', viewer)):
                user = User(name=name, role_id=role.id, is_enabled=True, is_approved=True)
                user.set_password('x' * 12)
                db.session.add(user)
            db.session.add(AIGlobalSettings())
            db.session.add(Misc())
            db.session.commit()
            self.boss_id = User.query.filter_by(name='boss').first().id
            self.watcher_id = User.query.filter_by(name='watcher').first().id

        for name in mcp_central._ENV.values():
            os.environ.pop(name, None)
        os.environ.pop('OAUTH_PUBLIC_BASE_URL', None)
        self._verifier = None

        def _verifier(cfg):
            if self._verifier is None or (self._verifier.issuer, self._verifier.resource) != (cfg.issuer, cfg.public_url):
                self._verifier = CentralTokenVerifier(cfg.issuer, cfg.public_url, http=_FakeHttp())
            return self._verifier
        patcher = mock.patch.object(mcp_central, 'verifier', _verifier)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        with self.app.app_context():
            self.db.session.remove()
            self.db.drop_all()
        self._tmp.cleanup()

    def _enable(self, **over):
        from aot.databases.models import AIGlobalSettings, Misc
        from aot.utils.crypto import encrypt_secret
        with self.app.app_context():
            row = AIGlobalSettings.query.first()
            row.mcp_central_enabled = over.get('enabled', True)
            row.mcp_central_issuer = over.get('issuer', ISSUER)
            row.mcp_public_url = over.get('public_url', RESOURCE)
            row.mcp_link_client_id = 'link-client'
            row.mcp_link_client_secret = encrypt_secret('s3cret')
            Misc.query.first().oauth_public_base_url = WEB
            self.db.session.commit()

    def _link(self, user_id, sub='acct-1'):
        from aot.databases.models import MCPExternalAccount
        with self.app.app_context():
            self.db.session.add(MCPExternalAccount(issuer=ISSUER, subject=sub, user_id=user_id))
            self.db.session.commit()

    def _auth(self, token):
        from aot.tools import mcp_auth
        with self.app.app_context():
            return mcp_auth.authenticate_http({'Authorization': 'Bearer ' + token})

    def _client(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True
        return client


class TestAddresses(unittest.TestCase):

    def test_issuer_needs_https_except_loopback(self):
        from aot.tools import mcp_central as C
        self.assertEqual(C.normalize_issuer('https://auth.lan.example/'), 'https://auth.lan.example')
        self.assertIsNone(C.normalize_issuer('http://auth.lan.example'))
        self.assertEqual(C.normalize_issuer('http://localhost:8300'), 'http://localhost:8300')
        self.assertIsNone(C.normalize_issuer('https://auth.example.net?x=1'))

    def test_public_url_is_normalized_and_needs_a_path(self):
        from aot.tools import mcp_central as C
        self.assertEqual(C.normalize_public_url('https://Farm.Example.org:443/mcp/'), RESOURCE)
        self.assertEqual(C.normalize_public_url('https://100.64.1.2:8443/mcp'), 'https://100.64.1.2:8443/mcp')
        self.assertIsNone(C.normalize_public_url('https://farm.example.org'))

    def test_metadata_url_puts_well_known_before_the_path(self):
        from aot.tools import mcp_central as C
        cfg = C.CentralConfig(True, ISSUER, RESOURCE, '', '', '', {})
        self.assertEqual(C.resource_metadata_url(cfg),
                         'https://farm.example.org/.well-known/oauth-protected-resource/mcp')


class TestConfig(_Base):

    def test_environment_wins_over_the_screen(self):
        from aot.tools import mcp_central
        self._enable()
        with mock.patch.dict(os.environ, {'AOT_MCP_CENTRAL_ISSUER': 'https://auth.other.example',
                                          'AOT_MCP_CENTRAL': '0'}):
            with self.app.app_context():
                cfg = mcp_central.config()
        self.assertEqual(cfg.issuer, 'https://auth.other.example')
        self.assertFalse(cfg.enabled)
        self.assertTrue(cfg.from_env['issuer'])
        self.assertEqual(cfg.public_url, RESOURCE)
        self.assertEqual(cfg.link_client_secret, 's3cret')

    def test_save_from_the_modal(self):
        from aot.databases.models import AIGlobalSettings, Misc
        client = self._client(self.boss_id)
        r = client.post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y',
            'mcp_central_issuer': ISSUER + '/', 'mcp_public_url': RESOURCE,
            'oauth_public_base_url': WEB, 'mcp_link_client_id': 'link-client', 'mcp_link_client_secret': 'abc'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('mcp_auth=1', r.headers['Location'])
        with self.app.app_context():
            row = AIGlobalSettings.query.first()
            self.assertTrue(row.mcp_central_enabled)
            self.assertEqual(row.mcp_central_issuer, ISSUER)
            self.assertNotEqual(row.mcp_link_client_secret, 'abc')       # 암호화
            self.assertEqual(Misc.query.first().oauth_public_base_url, WEB)
        # 비밀 칸을 비우면 그대로 둔다
        client.post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y', 'mcp_central_issuer': ISSUER,
            'mcp_public_url': RESOURCE, 'mcp_link_client_id': 'link-client', 'mcp_link_client_secret': ''})
        from aot.tools import mcp_central
        with self.app.app_context():
            self.assertEqual(mcp_central.config().link_client_secret, 'abc')

    def test_bad_addresses_are_refused(self):
        from aot.databases.models import AIGlobalSettings
        client = self._client(self.boss_id)
        client.post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y',
            'mcp_central_issuer': 'http://auth.lan.example', 'mcp_public_url': RESOURCE})
        client.post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y',
            'mcp_central_issuer': '', 'mcp_public_url': ''})
        with self.app.app_context():
            self.assertFalse(AIGlobalSettings.query.first().mcp_central_enabled)

    def test_viewer_cannot_save(self):
        from aot.databases.models import AIGlobalSettings
        self._client(self.watcher_id).post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y',
            'mcp_central_issuer': ISSUER, 'mcp_public_url': RESOURCE})
        with self.app.app_context():
            self.assertFalse(AIGlobalSettings.query.first().mcp_central_enabled)

    def test_check_reports_each_step(self):
        def fake_get(url, **_kw):
            body = {'issuer': ISSUER} if 'oauth-authorization-server' in url else {'keys': [KEY.as_dict(private=False)]}
            return mock.Mock(status_code=200, json=lambda: body)
        with mock.patch('requests.get', fake_get):
            r = self._client(self.boss_id).post('/settings/mcp_auth/check', data={
                'mcp_central_issuer': ISSUER, 'mcp_public_url': RESOURCE})
        results = r.get_json()['results']
        self.assertTrue(all(item['ok'] for item in results), results)
        with mock.patch('requests.get', lambda url, **kw: mock.Mock(status_code=200, json=lambda: {'issuer': 'https://evil'})):
            r = self._client(self.boss_id).post('/settings/mcp_auth/check', data={
                'mcp_central_issuer': ISSUER, 'mcp_public_url': RESOURCE})
        self.assertFalse(r.get_json()['results'][-1]['ok'])


class TestTokens(_Base):

    def test_jwt_is_refused_while_central_auth_is_off(self):
        ok, _agent, _role, err = self._auth(_access_token())
        self.assertFalse(ok)
        self.assertEqual(err['error'], 'unauthorized')

    def test_valid_token_without_a_link_becomes_a_tool_error(self):
        from aot.tools import mcp_auth
        self._enable()
        ok, _agent, role, err = self._auth(_access_token())
        self.assertFalse(ok)
        self.assertIsNone(role)
        self.assertEqual(err['error'], mcp_auth.ERROR_NOT_LINKED)
        self.assertIn('Link My Account', err['message'])

    def test_wrong_audience_or_issuer_is_invalid(self):
        self._enable()
        self._link(self.boss_id)
        for token in (_access_token(aud='https://other.example.org/mcp'),
                      _access_token(aud=RESOURCE + '/'),
                      _access_token(iss='https://auth.other.example')):
            ok, _agent, _role, err = self._auth(token)
            self.assertFalse(ok)
            self.assertEqual(err['error'], 'invalid_token')

    def test_scopes_narrow_the_role(self):
        from aot.tools import tool_registry as R
        self._enable()
        self._link(self.boss_id)
        ok, agent, role, _err = self._auth(_access_token())
        self.assertTrue(ok)
        self.assertEqual(agent, 'user:boss/Claude')
        self.assertFalse(role.can_write)
        self.assertFalse(role.can_edit_settings)
        self.assertEqual(role.tool_profile, R.TOOL_PROFILE_OPERATIONS)

        ok, _agent, role, _err = self._auth(_access_token(scope='aot.read aot.control aot.config'))
        self.assertTrue(role.can_write)
        self.assertTrue(role.can_edit_settings)
        self.assertEqual(role.tool_profile, R.TOOL_PROFILE_CONFIGURATION)

    def test_scope_never_adds_what_the_role_lacks(self):
        self._enable()
        self._link(self.watcher_id)
        ok, _agent, role, _err = self._auth(_access_token(scope='aot.read aot.control aot.config'))
        self.assertTrue(ok)
        self.assertFalse(role.can_write)
        self.assertFalse(role.can_edit_settings)

    def test_disabled_user_is_not_linked(self):
        from aot.databases.models import User
        self._enable()
        self._link(self.boss_id)
        with self.app.app_context():
            self.db.session.get(User, self.boss_id).is_enabled = False
            self.db.session.commit()
        ok, _agent, _role, err = self._auth(_access_token())
        self.assertFalse(ok)
        self.assertEqual(err['error'], 'account_not_linked')

    def test_api_key_as_bearer_still_goes_to_the_key_check(self):
        self._enable()
        ok, _agent, _role, err = self._auth('bm90LWEta2V5')     # 점이 없는 값 = API 키
        self.assertFalse(ok)
        self.assertEqual(err['message'], 'The API key is not valid.')


class TestHttpServer(_Base):

    def _http(self):
        import importlib
        srv = importlib.import_module('aot.aot_mcp_server')
        captured = {}
        fake = types.ModuleType('waitress')
        fake.serve = lambda http_app, **kw: captured.setdefault('app', http_app)
        with mock.patch.dict(sys.modules, {'waitress': fake}):
            srv._run_http_server(self.app, port=0)
        return captured['app'].test_client()

    def test_metadata_follows_the_setting(self):
        client = self._http()
        self.assertEqual(client.get('/.well-known/oauth-protected-resource/mcp').status_code, 404)
        self._enable()
        for path in ('/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-protected-resource'):
            body = client.get(path).get_json()
            self.assertEqual(body['resource'], RESOURCE)
            self.assertEqual(body['authorization_servers'], [ISSUER])
            self.assertIn('aot.read', body['scopes_supported'])

    def test_401_points_to_the_metadata(self):
        client = self._http()
        rpc = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}
        r = client.post('/mcp', json=rpc)
        self.assertEqual(r.status_code, 401)
        self.assertNotIn('WWW-Authenticate', r.headers)          # 꺼져 있으면 알리지 않는다
        self._enable()
        r = client.post('/mcp', json=rpc)
        self.assertEqual(r.status_code, 401)
        self.assertIn('resource_metadata="https://farm.example.org/.well-known/oauth-protected-resource/mcp"',
                      r.headers['WWW-Authenticate'])
        r = client.post('/mcp', json=rpc, headers={'Authorization': 'Bearer ' + _access_token(aud='https://x.example/mcp')})
        self.assertIn('error="invalid_token"', r.headers['WWW-Authenticate'])

    def test_unlinked_token_connects_but_tools_explain_how_to_link(self):
        self._enable()
        client = self._http()
        headers = {'Authorization': 'Bearer ' + _access_token()}
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Link My Account', r.get_json()['result']['instructions'])
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                      'params': {'name': 'search_devices', 'arguments': {}}}, headers=headers)
        self.assertEqual(r.status_code, 200)
        result = r.get_json()['result']
        self.assertTrue(result['isError'])
        self.assertIn('Link My Account', result['content'][0]['text'])


class TestAccountLink(_Base):

    def _start(self, client):
        r = client.post('/settings/mcp_auth/link')
        self.assertEqual(r.status_code, 302)
        target = urlsplit(r.headers['Location'])
        self.assertEqual(f'{target.scheme}://{target.netloc}{target.path}', ISSUER + '/link/authorize')
        return {k: v[0] for k, v in parse_qs(target.query).items()}

    def test_link_and_unlink_my_account(self):
        from aot.databases.models import MCPExternalAccount
        self._enable()
        client = self._client(self.boss_id)
        query = self._start(client)
        self.assertEqual(query['redirect_uri'], WEB + '/settings/mcp_auth/callback')
        self.assertEqual(query['code_challenge_method'], 'S256')
        self.assertEqual(query['client_id'], 'link-client')

        def fake_post(url, data=None, auth=None, **_kw):
            self.assertEqual(url, ISSUER + '/link/token')
            self.assertEqual(auth, ('link-client', 's3cret'))
            self.assertTrue(data['code_verifier'])
            return mock.Mock(status_code=200, json=lambda: {'id_token': _id_token(query['nonce'])})
        with mock.patch('requests.post', fake_post):
            r = client.get('/settings/mcp_auth/callback?code=c1&state=' + query['state'])
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            link = MCPExternalAccount.query.filter_by(user_id=self.boss_id).one()
            self.assertEqual((link.issuer, link.subject, link.label), (ISSUER, 'acct-1', 'staff@example.net'))

        ok, agent, _role, _err = self._auth(_access_token())
        self.assertTrue(ok)
        self.assertTrue(agent.startswith('user:boss'))

        client.post('/settings/mcp_auth/unlink')
        with self.app.app_context():
            self.assertEqual(MCPExternalAccount.query.count(), 0)

    def test_state_mismatch_or_wrong_nonce_does_not_link(self):
        from aot.databases.models import MCPExternalAccount
        self._enable()
        client = self._client(self.boss_id)
        query = self._start(client)
        with mock.patch('requests.post') as post:
            client.get('/settings/mcp_auth/callback?code=c1&state=forged')
            post.assert_not_called()
        query = self._start(client)
        with mock.patch('requests.post', lambda *a, **k: mock.Mock(
                status_code=200, json=lambda: {'id_token': _id_token('other-nonce')})):
            client.get('/settings/mcp_auth/callback?code=c1&state=' + query['state'])
        with self.app.app_context():
            self.assertEqual(MCPExternalAccount.query.count(), 0)

    def test_a_subject_linked_to_someone_else_is_refused(self):
        from aot.databases.models import MCPExternalAccount
        self._enable()
        self._link(self.watcher_id)
        client = self._client(self.boss_id)
        query = self._start(client)
        with mock.patch('requests.post', lambda *a, **k: mock.Mock(
                status_code=200, json=lambda: {'id_token': _id_token(query['nonce'])})):
            client.get('/settings/mcp_auth/callback?code=c1&state=' + query['state'])
        with self.app.app_context():
            self.assertEqual([r.user_id for r in MCPExternalAccount.query.all()], [self.watcher_id])


class TestMigration(unittest.TestCase):

    def test_migration_is_in_the_chain(self):
        # 머리(head)가 이 마이그레이션이라고 고정하면 뒤에 마이그레이션이 붙는 순간
        # 깨진다 — 체인 전체의 일치는 check_alembic_head.py 가 본다.
        import glob
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        versions = os.path.join(here, '..', '..', 'alembic_db', 'alembic', 'versions')
        self.assertTrue(glob.glob(os.path.join(
            versions, 'p6_77_mcp_central_auth_20260928*.py')))


if __name__ == '__main__':
    unittest.main()
