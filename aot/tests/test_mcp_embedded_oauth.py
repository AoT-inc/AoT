# coding=utf-8
"""MCP 내장 인가 서버 — 메타데이터·등록·인가·토큰·갱신·끊기, 그리고 `aot_mcp` 의 토큰 확인(적합성).

고정하는 계약(docs/design/mcp-embedded-oauth.md §4~§8, aot-auth 의 DESIGN §2~§4):

  1. 켜지 않았으면(중앙 모드이거나 꺼짐) 모든 경로가 404.
  2. 메타데이터는 PKCE S256 만, 발급자는 MCP 공개 주소의 출처(경로 없음). /register 는 되돌림 주소 허용 목록만.
  3. /authorize 는 resource 가 MCP 공개 주소와 정확히 같아야 하고, 로그인 전이면 로그인으로 보냈다가 돌아온다.
  4. 코드는 한 번만, 60초 안에, 같은 되돌림 주소·PKCE 로. 다시 쓰면 그 코드로 만든 연결이 끊긴다.
  5. 갱신 토큰은 쓸 때마다 교체되고, 옛 것이 다시 오면 연결 전체가 끊긴다.
  6. 접근 토큰은 다른 aud·끝 `/`·만료·nbf 미래·서명 틀림·alg none/HS256·typ 틀림·끊긴 gid 를 전부 거부한다.
  7. 비밀번호가 바뀌면 그 사용자의 연결이 끊긴다. 서명 키 파일은 권한 600.

진짜 ES256 키로 서명하고 Flask 테스트 클라이언트로 HTTP 흐름을 끝까지 탄다. 라이브 DB 는 쓰지 않는다.
"""
import base64
import hashlib
import json
import os
import stat
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit

from joserfc import jws, jwt
from joserfc.jwk import ECKey, OctKey

WEB = 'https://farm.example.org'
RESOURCE = WEB + '/mcp'
CALLBACK = 'https://claude.ai/api/mcp/auth_callback'
VERIFIER = 'v' * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip('=')


class _Base(unittest.TestCase):

    def setUp(self):
        import flask_login
        from flask import Flask
        from flask_babel import Babel

        import aot.databases.models  # noqa: F401
        from aot.aot_flask import routes_mcp_auth, routes_oauth_embedded
        from aot.aot_flask.extensions import csrf, db
        from aot.databases.models import AIGlobalSettings, Misc, Role, User
        from aot.tools import mcp_central, mcp_embedded

        self._tmp = tempfile.TemporaryDirectory()
        self.key_file = os.path.join(self._tmp.name, 'oauth.pem')
        self._env = {'AOT_MCP_OAUTH_KEY_FILE': self.key_file}
        for name in list(mcp_central._ENV.values()) + ['OAUTH_PUBLIC_BASE_URL', 'AOT_MCP_REDIRECT_ALLOWLIST']:
            os.environ.pop(name, None)
        os.environ.update(self._env)
        mcp_embedded._key_cache.clear()
        with mcp_central._verifiers_lock:
            mcp_central._verifiers.clear()

        app = Flask(__name__)
        app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(self._tmp.name, 't.db'),
                          SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY='t', WTF_CSRF_ENABLED=False,
                          TESTING=True, SESSION_PROTECTION=None)
        db.init_app(app)
        csrf.init_app(app)
        Babel(app)
        app.register_blueprint(routes_oauth_embedded.blueprint)
        app.register_blueprint(routes_mcp_auth.blueprint)
        home = __import__('flask').Blueprint('routes_general', __name__)
        home.add_url_rule('/', 'home', lambda: 'home')
        app.register_blueprint(home)
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
            db.session.add(AIGlobalSettings(mcp_central_enabled=True, mcp_auth_mode='embedded', mcp_public_url=RESOURCE))
            db.session.add(Misc(hostname_override='Kimje Farm'))
            db.session.commit()
            self.boss_id = User.query.filter_by(name='boss').first().id
            self.watcher_id = User.query.filter_by(name='watcher').first().id
        self.client = app.test_client()

    def tearDown(self):
        from aot.tools import mcp_central, mcp_embedded
        with self.app.app_context():
            self.db.session.remove()
            self.db.drop_all()
        self._tmp.cleanup()
        os.environ.pop('AOT_MCP_OAUTH_KEY_FILE', None)
        os.environ.pop('AOT_MCP_REDIRECT_ALLOWLIST', None)
        mcp_embedded._key_cache.clear()
        with mcp_central._verifiers_lock:
            mcp_central._verifiers.clear()

    # ── 도우미 ──

    def _login(self, client, user_id):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def _register(self, redirect=CALLBACK, **over):
        body = {'client_name': 'Claude', 'redirect_uris': [redirect], 'token_endpoint_auth_method': 'none'}
        body.update(over)
        response = self.client.post('/register', json=body)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()['client_id']

    def _authorize_args(self, client_id, **over):
        args = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': CALLBACK,
                'code_challenge': CHALLENGE, 'code_challenge_method': 'S256', 'state': 'st',
                'resource': RESOURCE, 'scope': 'aot.read aot.control aot.config'}
        args.update(over)
        return args

    def _allow(self, client_id, user_id=None, scopes=('aot.read', 'aot.control'), **over):
        """로그인한 사용자가 동의 화면에서 허용 → (코드, 응답 주소의 쿼리)."""
        user_client = self.app.test_client()
        self._login(user_client, user_id or self.boss_id)
        args = self._authorize_args(client_id, **over)
        data = dict(args, decision='allow', grant=list(scopes))
        response = user_client.post('/authorize', data=data)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        query = parse_qs(urlsplit(response.headers['Location']).query)
        return query.get('code', [None])[0], query

    def _token(self, **form):
        return self.client.post('/token', data=form)

    def _code_exchange(self, cid, code, **over):
        form = {'grant_type': 'authorization_code', 'client_id': cid, 'code': code,
                'redirect_uri': CALLBACK, 'code_verifier': VERIFIER, 'resource': RESOURCE}
        form.update(over)
        return self._token(**form)

    def _connect(self, user_id=None, scopes=('aot.read', 'aot.control')):
        client_id = self._register()
        code, _ = self._allow(client_id, user_id, scopes)
        response = self._code_exchange(client_id, code)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return client_id, response.get_json()

    def _auth(self, token):
        from aot.tools import mcp_auth
        with self.app.app_context():
            return mcp_auth.authenticate_http({'Authorization': 'Bearer ' + token})

    def _grant(self, gid=None):
        from aot.databases.models import OAuthGrant
        with self.app.app_context():
            query = OAuthGrant.query.filter_by(gid=gid) if gid else OAuthGrant.query
            row = query.first()
            return {'gid': row.gid, 'status': row.status, 'reason': row.revoked_reason,
                    'scope': row.scope} if row is not None else None


class TestOffByDefault(_Base):

    def test_every_path_is_404_unless_embedded_mode_is_on(self):
        from aot.databases.models import AIGlobalSettings
        with self.app.app_context():
            AIGlobalSettings.query.first().mcp_auth_mode = 'central'
            self.db.session.commit()
        for method, path in (('get', '/.well-known/oauth-authorization-server'), ('get', '/.well-known/jwks.json'),
                             ('post', '/register'), ('get', '/authorize'), ('post', '/token'), ('post', '/revoke')):
            self.assertEqual(getattr(self.client, method)(path).status_code, 404, path)

    def test_mode_defaults_to_central_and_embedded_derives_the_issuer_from_the_public_url(self):
        from aot.databases.models import AIGlobalSettings
        from aot.tools import mcp_central
        with self.app.app_context():
            cfg = mcp_central.config()
            self.assertEqual((cfg.mode, cfg.issuer, cfg.public_url), ('embedded', WEB, RESOURCE))
            self.assertTrue(mcp_central.is_active(cfg))
            self.assertFalse(mcp_central.can_link(cfg))
            AIGlobalSettings.query.first().mcp_auth_mode = ''
            self.db.session.commit()
            self.assertEqual(mcp_central.config().mode, 'central')
            AIGlobalSettings.query.first().mcp_auth_mode = 'embedded'
            AIGlobalSettings.query.first().mcp_public_url = 'http://farm.example.org/mcp'
            self.db.session.commit()
            self.assertFalse(mcp_central.is_active(mcp_central.config()))  # http 는 루프백만


class TestMetadataAndRegistration(_Base):

    def test_metadata_is_s256_only_and_points_at_this_origin(self):
        body = self.client.get('/.well-known/oauth-authorization-server').get_json()
        self.assertEqual(body['issuer'], WEB)
        self.assertEqual(body['code_challenge_methods_supported'], ['S256'])
        self.assertEqual(body['token_endpoint'], WEB + '/token')
        self.assertEqual(body['registration_endpoint'], WEB + '/register')
        self.assertEqual(body['token_endpoint_auth_methods_supported'], ['none'])
        self.assertTrue(body['authorization_response_iss_parameter_supported'])

    def test_protected_resource_metadata_names_this_origin_as_the_authorization_server(self):
        from aot.tools import mcp_central
        with self.app.app_context():
            doc = mcp_central.protected_resource_metadata(mcp_central.config())
        self.assertEqual((doc['resource'], doc['authorization_servers']), (RESOURCE, [WEB]))

    def test_jwks_publishes_one_es256_public_key_and_the_file_is_private(self):
        keys = self.client.get('/.well-known/jwks.json').get_json()['keys']
        self.assertEqual(len(keys), 1)
        self.assertEqual((keys[0]['kty'], keys[0]['crv'], keys[0]['alg']), ('EC', 'P-256', 'ES256'))
        self.assertNotIn('d', keys[0])
        self.assertEqual(stat.S_IMODE(os.stat(self.key_file).st_mode), 0o600)

    def test_register_accepts_only_allowlisted_redirects(self):
        self._register(CALLBACK)
        self._register('https://claude.com/api/mcp/auth_callback')
        self._register('http://localhost:5555/callback')
        self._register('http://127.0.0.1:61000/cb')
        for bad in ('https://evil.example/cb', CALLBACK + '/x', 'http://claude.ai/api/mcp/auth_callback',
                    CALLBACK + '#frag', 'https://localhost/cb'):
            response = self.client.post('/register', json={'redirect_uris': [bad]})
            self.assertEqual((response.status_code, response.get_json()['error']), (400, 'invalid_redirect_uri'), bad)

    def test_register_rejects_secrets_and_odd_grants(self):
        for over in ({'token_endpoint_auth_method': 'client_secret_basic'}, {'grant_types': ['password']},
                     {'response_types': ['token']}, {'client_name': 5}, {'redirect_uris': []}):
            body = {'redirect_uris': [CALLBACK]}
            body.update(over)
            self.assertEqual(self.client.post('/register', json=body).status_code, 400, over)
        self.assertEqual(self.client.post('/register', data='nope').status_code, 400)

    def test_allowlist_can_be_replaced_from_the_environment(self):
        os.environ['AOT_MCP_REDIRECT_ALLOWLIST'] = 'https://chat.example/cb'
        self._register('https://chat.example/cb')
        self.assertEqual(self.client.post('/register', json={'redirect_uris': [CALLBACK]}).status_code, 400)


class TestAuthorize(_Base):

    def test_logged_out_user_is_sent_to_login_and_comes_back(self):
        client_id = self._register()
        response = self.client.get('/authorize', query_string=self._authorize_args(client_id))
        self.assertEqual((response.status_code, response.headers['Location']), (302, '/login'))
        with self.client.session_transaction() as sess:
            self.assertTrue(sess['oauth_return'].startswith('/authorize?'))
            self.assertIn('client_id=' + client_id, sess['oauth_return'])
        with self.app.test_request_context():
            from flask import session
            from aot.aot_flask.utils import utils_general
            session['oauth_return'] = '/authorize?x=1'
            self.assertEqual(utils_general.after_login_url(), '/authorize?x=1')
            session['oauth_return'] = 'https://evil.example/'
            self.assertNotEqual(utils_general.after_login_url(), 'https://evil.example/')

    def test_consent_screen_leads_with_the_farm_name_and_greys_out_what_the_role_cannot_do(self):
        client_id = self._register()
        watcher = self.app.test_client()
        self._login(watcher, self.watcher_id)
        response = watcher.get('/authorize', query_string=self._authorize_args(client_id))
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Kimje Farm', html)
        self.assertIn('farm.example.org', html)
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertIn('no-store', response.headers['Cache-Control'])
        control = html[html.index('value="aot.control"'):].split('>')[0]
        self.assertIn('disabled', control)
        self.assertNotIn('checked', control)
        read = html[html.index('value="aot.read"'):].split('>')[0]
        self.assertIn('checked', read)

    def test_bad_client_or_redirect_is_shown_not_redirected(self):
        client_id = self._register()
        for args in (self._authorize_args('nope'), self._authorize_args(client_id, redirect_uri='https://evil.example/cb')):
            response = self.client.get('/authorize', query_string=args)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn('Location', response.headers)

    def test_other_problems_go_back_to_the_client_as_errors(self):
        client_id = self._register()
        cases = (({'resource': ''}, 'invalid_target'), ({'resource': RESOURCE + '/'}, None),
                 ({'resource': 'https://other.example/mcp'}, 'invalid_target'),
                 ({'code_challenge_method': 'plain'}, 'invalid_request'),
                 ({'code_challenge': 'short'}, 'invalid_request'),
                 ({'response_type': 'token'}, 'unsupported_response_type'))
        for over, error in cases:
            response = self.client.get('/authorize', query_string=self._authorize_args(client_id, **over))
            self.assertEqual(response.status_code, 302, over)
            query = parse_qs(urlsplit(response.headers['Location']).query)
            if error:
                self.assertEqual(query['error'], [error], over)
                self.assertEqual(query['state'], ['st'])
                self.assertEqual(query['iss'], [WEB])
            else:  # 끝 / 는 정규화로 같은 주소
                self.assertEqual(response.headers['Location'], '/login')

    def test_deny_comes_back_as_access_denied(self):
        client_id = self._register()
        user = self.app.test_client()
        self._login(user, self.boss_id)
        response = user.post('/authorize', data=dict(self._authorize_args(client_id), decision='deny'))
        query = parse_qs(urlsplit(response.headers['Location']).query)
        self.assertEqual((query['error'], query['state'], 'code' in query), (['access_denied'], ['st'], False))

    def test_scopes_are_what_the_user_ticked_minus_what_the_role_cannot_do(self):
        client_id = self._register()
        code, _ = self._allow(client_id, self.watcher_id, scopes=('aot.read', 'aot.control', 'aot.config'))
        token = self._code_exchange(client_id, code).get_json()
        self.assertEqual(token['scope'], 'aot.read')
        code, _ = self._allow(client_id, self.boss_id, scopes=('aot.read', 'aot.config'))
        self.assertEqual(self._code_exchange(client_id, code).get_json()['scope'], 'aot.read aot.config')


class TestTokenFlow(_Base):

    def test_code_to_token_to_refresh_to_revoke(self):
        client_id, first = self._connect()
        self.assertEqual((first['token_type'], first['expires_in'] > 3000, first['scope']),
                         ('Bearer', True, 'aot.read aot.control'))
        ok, agent, role, error = self._auth(first['access_token'])
        self.assertEqual((ok, agent, error), (True, 'user:boss/Claude', None))
        self.assertTrue(role.can_write)

        refreshed = self._token(grant_type='refresh_token', client_id=client_id, refresh_token=first['refresh_token'])
        self.assertEqual(refreshed.status_code, 200)
        second = refreshed.get_json()
        self.assertNotEqual(second['refresh_token'], first['refresh_token'])
        self.assertTrue(self._auth(second['access_token'])[0])

        self.client.post('/revoke', data={'token': second['refresh_token'], 'client_id': client_id})
        self.assertEqual(self._grant()['status'], 'revoked')
        self.assertFalse(self._auth(second['access_token'])[0])

    def test_token_responses_are_not_cacheable(self):
        client_id = self._register()
        code, _ = self._allow(client_id)
        response = self._code_exchange(client_id, code)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_code_is_single_use_and_reuse_closes_the_connection(self):
        client_id = self._register()
        code, _ = self._allow(client_id)
        first = self._code_exchange(client_id, code)
        self.assertEqual(first.status_code, 200)
        again = self._code_exchange(client_id, code)
        self.assertEqual((again.status_code, again.get_json()['error']), (400, 'invalid_grant'))
        self.assertEqual((self._grant()['status'], self._grant()['reason']), ('revoked', 'code_reuse'))
        self.assertFalse(self._auth(first.get_json()['access_token'])[0])

    def test_code_checks(self):
        client_id = self._register()
        other_id = self._register()
        cases = {
            'wrong verifier': dict(code_verifier='w' * 64),
            'short verifier': dict(code_verifier='short'),
            'wrong redirect': dict(redirect_uri='https://claude.com/api/mcp/auth_callback'),
            'wrong client': dict(client_id=other_id),
            'wrong resource': dict(resource='https://farm.example.org/other'),
        }
        for label, over in cases.items():
            code, _ = self._allow(client_id)
            response = self._code_exchange(client_id, code, **over)
            self.assertEqual(response.status_code, 400, label)
            self.assertIn(response.get_json()['error'], ('invalid_grant', 'invalid_target'), label)
            if label == 'wrong client':
                continue  # 남의 클라이언트가 두드려도 원래 클라이언트의 코드는 소모되지 않는다
            # 틀린 시도 뒤에는 올바른 값으로도 못 쓴다 — 코드는 한 번의 기회다
            self.assertEqual(self._code_exchange(client_id, code).status_code, 400, label)
        self.assertEqual(self._code_exchange(client_id, 'nonsense').status_code, 400)
        self.assertEqual(self._token(grant_type='password', client_id=client_id).get_json()['error'],
                         'unsupported_grant_type')

    def test_expired_code_is_refused(self):
        from aot.databases.models import OAuthCode
        client_id = self._register()
        code, _ = self._allow(client_id)
        with self.app.app_context():
            OAuthCode.query.update({'expires_at': OAuthCode.expires_at.type.python_type.utcnow().replace(year=2020)})
            self.db.session.commit()
        self.assertEqual(self._code_exchange(client_id, code).get_json()['error'], 'invalid_grant')

    def test_codes_and_refresh_tokens_are_stored_only_as_hashes(self):
        from aot.databases.models import OAuthCode, OAuthGrant
        client_id = self._register()
        code, _ = self._allow(client_id)
        with self.app.app_context():
            self.assertNotEqual(OAuthCode.query.first().code_hash, code)
            self.assertEqual(len(OAuthCode.query.first().code_hash), 64)
        refresh = self._code_exchange(client_id, code).get_json()['refresh_token']
        with self.app.app_context():
            row = OAuthGrant.query.first()
            self.assertNotEqual(row.refresh_hash, refresh)
            self.assertEqual(row.refresh_hash, hashlib.sha256(refresh.encode()).hexdigest())

    def test_reused_refresh_token_closes_the_whole_connection(self):
        client_id, first = self._connect()
        second = self._token(grant_type='refresh_token', client_id=client_id,
                             refresh_token=first['refresh_token']).get_json()
        replay = self._token(grant_type='refresh_token', client_id=client_id, refresh_token=first['refresh_token'])
        self.assertEqual((replay.status_code, replay.get_json()['error']), (400, 'invalid_grant'))
        self.assertEqual((self._grant()['status'], self._grant()['reason']), ('revoked', 'refresh_reuse'))
        # 새 갱신 토큰도, 이미 낸 접근 토큰도 못 쓴다
        again = self._token(grant_type='refresh_token', client_id=client_id, refresh_token=second['refresh_token'])
        self.assertEqual(again.status_code, 400)
        self.assertFalse(self._auth(second['access_token'])[0])

    def test_refresh_cannot_widen_scope_or_change_resource_or_borrow_another_client(self):
        client_id, first = self._connect()
        other_id = self._register()
        bad = self._token(grant_type='refresh_token', client_id=client_id,
                          refresh_token=first['refresh_token'], scope='aot.read aot.config')
        self.assertEqual(bad.get_json()['error'], 'invalid_scope')
        bad = self._token(grant_type='refresh_token', client_id=client_id,
                          refresh_token=first['refresh_token'], resource='https://farm.example.org/x')
        self.assertEqual(bad.get_json()['error'], 'invalid_target')
        bad = self._token(grant_type='refresh_token', client_id=other_id, refresh_token=first['refresh_token'])
        self.assertEqual(bad.get_json()['error'], 'invalid_grant')
        narrow = self._token(grant_type='refresh_token', client_id=client_id,
                             refresh_token=first['refresh_token'], scope='aot.read')
        self.assertEqual(narrow.get_json()['scope'], 'aot.read')

    def test_expired_refresh_token_is_refused(self):
        from aot.databases.models import OAuthGrant
        from datetime import datetime, timedelta
        client_id, first = self._connect()
        with self.app.app_context():
            OAuthGrant.query.update({'refresh_expires_at': datetime.utcnow() - timedelta(minutes=1)})
            self.db.session.commit()
        response = self._token(grant_type='refresh_token', client_id=client_id, refresh_token=first['refresh_token'])
        self.assertEqual(response.get_json()['error'], 'invalid_grant')
        self.assertFalse(self._auth(first['access_token'])[0])

    def test_revoking_with_an_access_token_closes_the_connection_and_unknown_tokens_are_ignored(self):
        client_id, first = self._connect()
        self.assertEqual(self.client.post('/revoke', data={'token': 'garbage', 'client_id': client_id}).status_code, 200)
        self.assertEqual(self._grant()['status'], 'active')
        self.client.post('/revoke', data={'token': first['access_token'], 'client_id': client_id})
        self.assertEqual(self._grant()['status'], 'revoked')

    def test_another_client_cannot_revoke_the_connection(self):
        client_id, first = self._connect()
        other_id = self._register()
        self.client.post('/revoke', data={'token': first['refresh_token'], 'client_id': other_id})
        self.assertEqual(self._grant()['status'], 'active')

    def test_password_change_closes_the_users_connections(self):
        from aot.databases.models import User
        _, first = self._connect()
        self.assertTrue(self._auth(first['access_token'])[0])
        with self.app.app_context():
            User.query.filter_by(name='boss').first().set_password('y' * 12)
            self.db.session.commit()
        self.assertEqual(self._grant()['reason'], 'password_changed')
        self.assertFalse(self._auth(first['access_token'])[0])

    def test_disabled_user_loses_access_and_cannot_refresh(self):
        from aot.databases.models import User
        client_id, first = self._connect()
        with self.app.app_context():
            User.query.filter_by(name='boss').first().is_enabled = False
            self.db.session.commit()
        self.assertFalse(self._auth(first['access_token'])[0])
        response = self._token(grant_type='refresh_token', client_id=client_id, refresh_token=first['refresh_token'])
        self.assertEqual(response.get_json()['error'], 'invalid_grant')
        self.assertEqual(self._grant()['status'], 'revoked')

    def test_public_url_change_invalidates_old_connections(self):
        from aot.databases.models import AIGlobalSettings
        _, first = self._connect()
        with self.app.app_context():
            AIGlobalSettings.query.first().mcp_public_url = WEB + '/mcp2'
            self.db.session.commit()
        self.assertFalse(self._auth(first['access_token'])[0])

    def test_permissions_are_role_intersect_scope(self):
        _, readonly = self._connect(scopes=('aot.read',))
        _, ctrl = self._connect(scopes=('aot.read', 'aot.control'))
        self.assertFalse(self._auth(readonly['access_token'])[2].can_write)
        self.assertTrue(self._auth(ctrl['access_token'])[2].can_write)
        _, watcher = self._connect(self.watcher_id, scopes=('aot.read', 'aot.control'))
        self.assertFalse(self._auth(watcher['access_token'])[2].can_write)


class TestForgedAccessTokens(_Base):
    """aot_mcp 의 확인 규칙 — 서명·alg·typ·iss·aud·exp·nbf·gid 중 하나라도 틀리면 거부(→ HTTP 401)."""

    def _claims(self, grant_token, **over):
        decoded = jwt.decode(grant_token, __import__('aot.tools.mcp_embedded', fromlist=['x']).public_key_set(),
                             algorithms=['ES256'])
        claims = dict(decoded.claims)
        claims.update(over)
        return claims

    def _sign(self, claims, key=None, header=None):
        from aot.tools import mcp_embedded
        with self.app.app_context():
            key = key or mcp_embedded.signing_key()
        head = {'alg': 'ES256', 'typ': 'at+jwt', 'kid': key.kid}
        head.update(header or {})
        return jwt.encode(head, claims, key)

    def setUp(self):
        super().setUp()
        _, self.good = self._connect()
        with self.app.app_context():
            self.base = self._claims(self.good['access_token'])

    def _rejected(self, token):
        ok, _agent, _role, error = self._auth(token)
        self.assertFalse(ok)
        self.assertEqual(error['error'], 'invalid_token')

    def test_the_genuine_token_passes(self):
        self.assertTrue(self._auth(self.good['access_token'])[0])
        self.assertTrue(self._auth(self._sign(dict(self.base)))[0])  # 시험용 서명이 진짜와 같다는 확인

    def test_wrong_audience(self):
        self._rejected(self._sign(dict(self.base, aud='https://other.example.org/mcp')))

    def test_trailing_slash_audience(self):
        self._rejected(self._sign(dict(self.base, aud=RESOURCE + '/')))

    def test_audience_list(self):
        self._rejected(self._sign(dict(self.base, aud=[RESOURCE])))

    def test_wrong_issuer(self):
        self._rejected(self._sign(dict(self.base, iss='https://auth.aotinc.co.kr')))

    def test_expired(self):
        now = int(time.time())
        self._rejected(self._sign(dict(self.base, iat=now - 7300, nbf=now - 7300, exp=now - 3700)))

    def test_not_before_in_the_future(self):
        now = int(time.time())
        self._rejected(self._sign(dict(self.base, nbf=now + 3600, iat=now)))

    def test_signed_by_another_key(self):
        stranger = ECKey.generate_key('P-256', parameters={'kid': 'stranger'})
        self._rejected(self._sign(dict(self.base), key=stranger))
        # 우리 kid 를 훔쳐 붙여도 서명이 안 맞는다
        from aot.tools import mcp_embedded
        with self.app.app_context():
            kid = mcp_embedded.signing_key().kid
        self._rejected(self._sign(dict(self.base), key=ECKey.import_key(stranger.as_dict(private=True), {'kid': kid})))

    def test_alg_none_and_hs256_confusion(self):
        def b64(data):
            return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
        none_token = '%s.%s.' % (b64({'alg': 'none', 'typ': 'at+jwt', 'kid': 'x'}), b64(self.base))
        self._rejected(none_token)
        from aot.tools import mcp_embedded
        with self.app.app_context():
            public = mcp_embedded.signing_key().as_dict(private=False)
            kid = mcp_embedded.signing_key().kid
        secret = OctKey.import_key(json.dumps(public).encode())
        hs = jws.serialize_compact({'alg': 'HS256', 'typ': 'at+jwt', 'kid': kid}, json.dumps(self.base).encode(),
                                   secret, algorithms=['HS256'])
        self._rejected(hs)

    def test_wrong_typ(self):
        self._rejected(self._sign(dict(self.base), header={'typ': 'JWT'}))
        self._rejected(self._sign(dict(self.base), header={'typ': 'revocations+jwt'}))

    def test_revoked_gid(self):
        from aot.tools import mcp_embedded
        with self.app.app_context():
            mcp_embedded.revoke_grant(self.base['gid'], 'test')
        self._rejected(self.good['access_token'])

    def test_unknown_gid_and_mismatched_subject(self):
        self._rejected(self._sign(dict(self.base, gid='nonexistent')))
        self._rejected(self._sign(dict(self.base, sub=str(self.watcher_id))))

    def test_missing_pieces(self):
        for claim in ('gid', 'client_id', 'sub', 'exp', 'nbf', 'iat'):
            claims = dict(self.base)
            claims.pop(claim)
            self._rejected(self._sign(claims))
        self._rejected('not.a.jwt')
        self.assertFalse(self._auth('a.b')[0])

    def test_no_read_scope(self):
        ok, _agent, _role, error = self._auth(self._sign(dict(self.base, scope='aot.control')))
        self.assertFalse(ok)

    def test_when_embedded_mode_is_off_a_valid_looking_token_is_refused(self):
        from aot.databases.models import AIGlobalSettings
        with self.app.app_context():
            AIGlobalSettings.query.first().mcp_central_enabled = False
            self.db.session.commit()
        self.assertFalse(self._auth(self.good['access_token'])[0])


class TestSigningKey(_Base):

    def test_key_is_created_once_with_mode_600_and_survives_a_second_call(self):
        from aot.tools import mcp_embedded
        path = mcp_embedded.ensure_key(self.key_file)
        first = open(path, 'rb').read()
        mcp_embedded.ensure_key(self.key_file)
        self.assertEqual(open(path, 'rb').read(), first)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual([n for n in os.listdir(self._tmp.name) if n.endswith('.tmp')], [])

    def test_a_second_pem_next_to_the_key_is_published_for_rotation(self):
        from aot.tools import mcp_embedded
        mcp_embedded.ensure_key(self.key_file)
        with open(self.key_file[:-4] + '.old.pem', 'wb') as out:
            out.write(ECKey.generate_key('P-256').as_pem(private=True))
        self.assertEqual(len(mcp_embedded.jwks()['keys']), 2)
        self.assertTrue(all('d' not in key for key in mcp_embedded.jwks()['keys']))

    def test_the_key_is_not_in_the_database_or_the_audit_trail(self):
        _, first = self._connect()
        pem_body = open(self.key_file).read().split('\n')[1]
        raw = open(os.path.join(self._tmp.name, 't.db'), 'rb').read()
        self.assertNotIn(pem_body.encode(), raw)


class TestSettingsScreen(_Base):
    """설정 > 일반 > MCP 인증 설정 모달이 부르는 경로."""

    def _admin(self):
        client = self.app.test_client()
        self._login(client, self.boss_id)
        return client

    def _mode(self):
        from aot.databases.models import AIGlobalSettings
        with self.app.app_context():
            row = AIGlobalSettings.query.first()
            return row.mcp_auth_mode, bool(row.mcp_central_enabled), row.mcp_public_url

    def test_saving_embedded_mode_creates_the_signing_key(self):
        self.assertFalse(os.path.exists(self.key_file))
        response = self._admin().post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y', 'mcp_auth_mode': 'embedded',
            'mcp_public_url': RESOURCE, 'mcp_central_issuer': ''})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._mode(), ('embedded', True, RESOURCE))
        self.assertEqual(stat.S_IMODE(os.stat(self.key_file).st_mode), 0o600)

    def test_embedded_mode_needs_an_https_public_address_but_no_issuer(self):
        admin = self._admin()
        admin.post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y', 'mcp_auth_mode': 'embedded',
            'mcp_public_url': 'http://farm.example.org/mcp'})
        self.assertEqual(self._mode()[2], RESOURCE)  # 거절 — 처음 값 그대로
        admin.post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y', 'mcp_auth_mode': 'embedded',
            'mcp_public_url': ''})
        self.assertEqual(self._mode()[2], RESOURCE)

    def test_central_mode_still_needs_both_addresses(self):
        self._admin().post('/settings/mcp_auth/config', data={
            'mcp_central_enabled_shown': '1', 'mcp_central_enabled': 'y', 'mcp_auth_mode': 'central',
            'mcp_public_url': RESOURCE, 'mcp_central_issuer': ''})
        self.assertEqual(self._mode()[0], 'embedded')  # 거절 — 바뀌지 않았다

    def test_only_a_settings_editor_can_change_it(self):
        watcher = self.app.test_client()
        self._login(watcher, self.watcher_id)
        watcher.post('/settings/mcp_auth/config', data={'mcp_central_enabled_shown': '1', 'mcp_auth_mode': 'central'})
        self.assertEqual(self._mode()[0], 'embedded')
        self.assertEqual(watcher.post('/settings/mcp_auth/check').status_code, 403)

    def test_check_reports_the_key_and_the_issuer_for_embedded(self):
        response = self._admin().post('/settings/mcp_auth/check', data={
            'mcp_auth_mode': 'embedded', 'mcp_public_url': RESOURCE})
        results = {item['name']: item['ok'] for item in response.get_json()['results']}
        self.assertEqual(results, {'Public MCP address': True, 'Signing keys': True})
        bad = self._admin().post('/settings/mcp_auth/check', data={
            'mcp_auth_mode': 'embedded', 'mcp_public_url': 'http://farm.example.org/mcp'})
        self.assertFalse(all(item['ok'] for item in bad.get_json()['results']))

    def test_a_person_can_disconnect_only_their_own_connection(self):
        _, mine = self._connect(self.boss_id)
        gid = self._grant()['gid']
        watcher = self.app.test_client()
        self._login(watcher, self.watcher_id)
        watcher.post('/settings/mcp_auth/disconnect', data={'gid': gid})
        self.assertEqual(self._grant()['status'], 'active')
        self._admin().post('/settings/mcp_auth/disconnect', data={'gid': gid})
        self.assertEqual((self._grant()['status'], self._grant()['reason']), ('revoked', 'user_disconnect'))
        self.assertFalse(self._auth(mine['access_token'])[0])

    def test_modal_context_lists_my_active_connections(self):
        from aot.aot_flask import routes_mcp_auth
        from aot.databases.models import User
        self._connect(self.boss_id)
        with self.app.app_context():
            context = routes_mcp_auth.modal_context(User.query.filter_by(id=self.boss_id).first())
        self.assertEqual(context['mode'], 'embedded')
        self.assertEqual([g['name'] for g in context['embedded']['grants']], ['Claude'])
        self.assertIn(CALLBACK, context['embedded']['allowlist'])


class TestMigration(unittest.TestCase):

    def test_p6_95_adds_the_mode_column_and_three_tables_and_is_rerun_safe(self):
        import importlib.util

        import sqlalchemy as sa
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        path = os.path.join(os.path.dirname(__file__), '..', '..', 'alembic_db', 'alembic', 'versions',
                            'p6_95_mcp_embedded_oauth_20261024.py')
        spec = importlib.util.spec_from_file_location('p6_95', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual('p6_94_ai_shortcut_20261022', mod.down_revision)
        engine = sa.create_engine('sqlite://')
        with engine.begin() as conn:
            conn.execute(sa.text('create table users (id integer primary key)'))
            conn.execute(sa.text('create table ai_global_settings (id integer primary key)'))
            conn.execute(sa.text('insert into ai_global_settings (id) values (1)'))
            with Operations.context(MigrationContext.configure(conn)):
                mod.upgrade()
                mod.upgrade()
                inspector = sa.inspect(conn)
                self.assertTrue({'oauth_client', 'oauth_code', 'oauth_grant'} <= set(inspector.get_table_names()))
                self.assertIn('mcp_auth_mode', [c['name'] for c in inspector.get_columns('ai_global_settings')])
                self.assertEqual('central', conn.execute(sa.text('select mcp_auth_mode from ai_global_settings')).scalar())
                mod.downgrade()
                mod.downgrade()
                inspector = sa.inspect(conn)
                self.assertFalse({'oauth_client', 'oauth_code', 'oauth_grant'} & set(inspector.get_table_names()))
                self.assertNotIn('mcp_auth_mode', [c['name'] for c in inspector.get_columns('ai_global_settings')])


if __name__ == '__main__':
    unittest.main()
