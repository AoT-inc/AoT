# -*- coding: utf-8 -*-
"""settings/users 의 API 키 발급이 비신선 세션에서 조용히 죽던 버그의 회귀 가드.

배경 — 2026-08-16. 설정 > 사용자 드로어에서 "생성" 을 눌러도 화면에 아무
반응이 없고 키도 만들어지지 않는다는 신고(로컬 재현, koat 서버는 매번). 원인은
`settings_users_submit`(AJAX 전용, 항상 `jsonify` 로 응답)이 세션이 fresh 하지
않을 때만 `redirect()` 를 돌려준 것 — jQuery 가 그 302 를 따라가 `/settings/users`
의 HTML 을 200 으로 받고 `data.data.messages` 를 읽다 콘솔에만
"Cannot read properties of undefined (reading 'messages')" 를 남기고 조용히
죽었다. 화면은 무반응, 발급도 안 되고, 에러 토스트조차 없었다.

세션이 fresh 하지 않은 상태(=flask-login 이 "Remember Me" 쿠키로 복구한 세션)는
드문 일이 아니다 — 브라우저를 며칠 열어 두면 자연히 그렇게 된다. 실측(로컬
docker, Chrome 자동화)으로 재현·수정·재검증했다.
"""
import os
import sys
import tempfile
import unittest

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))


class _UsersSubmitAppFixture(unittest.TestCase):
    """routes_settings 블루프린트 하나만 등록한 임시 앱 (임시 sqlite, 라이브 DB 미사용)."""

    def setUp(self):
        from flask import Flask
        import flask_login
        from flask_babel import Babel

        from aot.aot_flask.extensions import db, csrf
        import aot.databases.models  # noqa: F401 — 모델 등록
        from aot.databases.models import User, Role
        from aot.aot_flask import routes_settings

        self._tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp.name, 'test.db')

        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(db_path)
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['TESTING'] = True
        # flask-login 의 SESSION_PROTECTION("basic")은 remote_addr/user_agent 로
        # 만든 식별자가 세션의 _id 와 다르면 _fresh 를 조용히 False 로 깎는다.
        # 여기서는 session_transaction() 으로 _fresh 를 직접 통제하는 것이
        # 목적이므로(require_fresh_login 자체를 검증하는 것이지 flask-login의
        # 세션 보호 기능을 검증하는 게 아니다) 꺼둔다.
        app.config['SESSION_PROTECTION'] = None

        db.init_app(app)
        csrf.init_app(app)
        Babel(app)
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
            role = Role()
            role.name = 'Admin'
            role.edit_users = True
            role.view_settings = True
            db.session.add(role)
            db.session.commit()

            user = User()
            user.name = 'tester'
            user.email = 'tester@example.com'
            user.is_enabled = True
            user.is_approved = True
            user.role_id = role.id
            user.set_password('correct horse battery staple')
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id
            self.user_unique_id = user.unique_id
            self._login_id = user.get_id()

        self.client = app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def _post_generate(self, key_name='Client', fresh=True):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = self._login_id
            sess['_fresh'] = fresh
        return self.client.post('/settings/users_submit', data={
            'user_id': self.user_unique_id,
            'api_key_name': key_name,
            'api_key_scope': 'full',
            'user_generate_api_key': 'Generate',
        })

    def _active_keys(self):
        from aot.databases.models import User
        with self.app.app_context():
            return list(User.query.get(self.user_id).active_api_keys())


class TestNonFreshSessionReturnsJson(_UsersSubmitAppFixture):
    """비신선 세션에서는 redirect 가 아니라 JSON 에러로 응답해야 한다."""

    def test_response_is_json_not_a_redirect(self):
        resp = self._post_generate(fresh=False)
        # 예전 버그: 302 redirect → jQuery 가 따라가 HTML 을 200으로 받음.
        # 지금은 이 라우트가 항상 jsonify() 로만 응답해야 한다.
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, 'application/json')
        payload = resp.get_json()
        self.assertIsNotNone(payload, "응답이 JSON 이 아님 — redirect 로 샌 HTML 일 가능성")
        self.assertIn('messages', payload['data'])

    def test_error_message_present_and_no_key_issued(self):
        resp = self._post_generate(fresh=False)
        payload = resp.get_json()
        self.assertTrue(payload['data']['messages']['error'])
        self.assertIsNone(payload['data']['generated_api_key'])
        self.assertEqual(len(self._active_keys()), 0)


class TestFreshSessionIssuesKey(_UsersSubmitAppFixture):
    """신선한 세션에서는 정상적으로 발급되고 값이 응답에 실려야 한다."""

    def test_key_generated_and_returned(self):
        resp = self._post_generate(key_name='ChatGPT', fresh=True)
        payload = resp.get_json()
        self.assertEqual(payload['data']['messages']['error'], [])
        self.assertTrue(payload['data']['generated_api_key'])

        keys = self._active_keys()
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0].name, 'ChatGPT')


if __name__ == '__main__':
    unittest.main()
