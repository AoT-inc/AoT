# coding=utf-8
"""내장 인가 서버를 **진짜 앱**(create_app)에 붙여 본 종단 시험 — 블루프린트 등록·CSRF·제한·실제 로그인 화면을 거친다.

mcp_embedded_oauth 시험은 얇은 Flask 앱으로 규칙을 고정하고, 여기서는 배선만 확인한다:
로그인 전 /authorize → 실제 /login_password 로그인 → /authorize 로 복귀 → 동의 → /token 까지.
conftest 가 AOT_LOCAL_DIR 을 임시 폴더로 돌려 둬서 라이브 DB 는 건드리지 않는다.
"""
import base64
import hashlib
import os
import re
import unittest
from urllib.parse import parse_qs, urlsplit

WEB = 'https://farm.example.org'
RESOURCE = WEB + '/mcp'
CALLBACK = 'https://claude.ai/api/mcp/auth_callback'
VERIFIER = 'q' * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip('=')
PASSWORD = 'Correct-Horse-9'


class RealAppFlow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.tests._live_db_guard import refuse_live_db
        refuse_live_db()
        from aot.aot_flask.app import create_app
        from aot.aot_flask.extensions import db
        from aot.databases.models import AIGlobalSettings, Misc, Role, User
        from aot.tools import mcp_central, mcp_embedded

        cls._saved_env = {name: os.environ.pop(name, None) for name in mcp_central._ENV.values()}
        cls.app = create_app()
        cls.app.config['RATELIMIT_ENABLED'] = False
        cls.app.config['SERVER_NAME'] = None
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        cls._key = os.environ.get(mcp_embedded.KEY_FILE_ENV)
        os.environ[mcp_embedded.KEY_FILE_ENV] = os.path.join(cls._tmp.name, 'k.pem')
        mcp_embedded._key_cache.clear()
        with cls.app.app_context():
            db.create_all()
            role = Role.query.filter_by(name='Admin').first()
            if role is None:
                role = Role(name='Admin', edit_settings=True, view_settings=True, edit_controllers=True, edit_users=True)
                db.session.add(role)
                db.session.commit()
            cls._cleanup = []
            user = User(name='oauthtester', role_id=role.id, is_enabled=True, is_approved=True)
            user.set_password(PASSWORD)
            db.session.add(user)
            row = AIGlobalSettings.query.first() or AIGlobalSettings()
            db.session.add(row)
            row.mcp_central_enabled, row.mcp_auth_mode, row.mcp_public_url = True, 'embedded', RESOURCE
            if Misc.query.first() is None:
                db.session.add(Misc())
            db.session.commit()
            cls.user_id = user.id
        with mcp_central._verifiers_lock:
            mcp_central._verifiers.clear()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        from aot.databases.models import User
        from aot.tools import mcp_embedded
        with cls.app.app_context():
            User.query.filter_by(id=cls.user_id).delete()
            db.session.commit()
        if cls._key is None:
            os.environ.pop(mcp_embedded.KEY_FILE_ENV, None)
        else:
            os.environ[mcp_embedded.KEY_FILE_ENV] = cls._key
        mcp_embedded._key_cache.clear()
        cls._tmp.cleanup()
        for name, value in cls._saved_env.items():
            if value is not None:
                os.environ[name] = value

    def test_discovery_register_login_consent_token_and_mcp_auth(self):
        from aot.tools import mcp_auth
        client = self.app.test_client()
        meta = client.get('/.well-known/oauth-authorization-server')
        self.assertEqual((meta.status_code, meta.get_json()['issuer']), (200, WEB))

        reg = client.post('/register', json={'client_name': 'Claude', 'redirect_uris': [CALLBACK]})
        self.assertEqual(reg.status_code, 201, reg.get_data(as_text=True))
        client_id = reg.get_json()['client_id']
        query = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': CALLBACK, 'state': 's1',
                 'code_challenge': CHALLENGE, 'code_challenge_method': 'S256', 'resource': RESOURCE,
                 'scope': 'aot.read aot.control'}

        # 로그인 전 → 로그인 화면으로
        first = client.get('/authorize', query_string=query)
        self.assertEqual((first.status_code, urlsplit(first.headers['Location']).path), (302, '/login'))

        # 실제 로그인 화면에서 로그인 → 곧바로 /authorize 로 돌아온다
        page = client.get('/login_password')
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.get_data(as_text=True))
        self.assertIsNotNone(token, page.get_data(as_text=True)[:400])
        login = client.post('/login_password', data={'aot_username': 'oauthtester', 'aot_password': PASSWORD,
                                                      'csrf_token': token.group(1)})
        self.assertEqual(login.status_code, 302, login.get_data(as_text=True)[:300])
        back = login.headers['Location']
        self.assertTrue(urlsplit(back).path == '/authorize' and 'client_id=' + client_id in back, back)

        consent = client.get(back)
        html = consent.get_data(as_text=True)
        self.assertEqual(consent.status_code, 200)
        self.assertIn('farm.example.org', html)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        hidden = dict(re.findall(r'<input type="hidden" name="(?!csrf_token)([^"]+)" value="([^"]*)"', html))
        done = client.post('/authorize', data=dict(hidden, csrf_token=csrf, decision='allow',
                                                    grant=['aot.read', 'aot.control']))
        self.assertEqual(done.status_code, 302, done.get_data(as_text=True)[:300])
        result = parse_qs(urlsplit(done.headers['Location']).query)
        self.assertEqual((result['state'], result['iss']), (['s1'], [WEB]))

        exchange = self.app.test_client().post('/token', data={
            'grant_type': 'authorization_code', 'client_id': client_id, 'code': result['code'][0],
            'redirect_uri': CALLBACK, 'code_verifier': VERIFIER, 'resource': RESOURCE})
        self.assertEqual(exchange.status_code, 200, exchange.get_data(as_text=True))
        access = exchange.get_json()['access_token']

        with self.app.app_context():
            ok, agent, role, error = mcp_auth.authenticate_http({'Authorization': 'Bearer ' + access})
        self.assertEqual((ok, agent, error), (True, 'user:oauthtester/Claude', None))
        self.assertTrue(role.can_write)

    def test_a_consent_post_without_the_csrf_token_is_refused(self):
        from aot.databases.models import OAuthCode
        client = self.app.test_client()
        reg = client.post('/register', json={'client_name': 'Claude', 'redirect_uris': [CALLBACK]})
        client_id = reg.get_json()['client_id']
        with self.app.app_context():
            before = OAuthCode.query.count()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True
        response = client.post('/authorize', data={
            'response_type': 'code', 'client_id': client_id, 'redirect_uri': CALLBACK,
            'code_challenge': CHALLENGE, 'code_challenge_method': 'S256', 'resource': RESOURCE, 'decision': 'allow'})
        # 앱의 CSRF 처리기는 경고를 띄우고 되돌려 보낸다 — 어느 쪽이든 인가 코드는 나오지 않는다
        self.assertIn(response.status_code, (302, 400, 401))
        self.assertNotIn('code=', response.headers.get('Location', ''))
        with self.app.app_context():
            self.assertEqual(OAuthCode.query.count(), before)


if __name__ == '__main__':
    unittest.main()
