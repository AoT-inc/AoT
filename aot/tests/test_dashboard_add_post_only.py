# -*- coding: utf-8 -*-
"""`/dashboard-add` 는 POST 로만 대시보드를 만든다 — 회귀 가드.

배경 — 2026-09-20. 이 주소는 GET 만으로 빈 대시보드를 하나 만들었다. 인자 없는
GET 을 전부 여는 E2E(L0 스모크·L1 부팅)가 실행마다 둘씩 쌓았고(25개까지),
사람의 사용에서도 브라우저의 링크 미리읽기·새로고침·뒤로가기가 같은 일을 할 수
있었다. 부작용 없는 GET 이어야 할 자리에서 쓰기를 하던 것이다.

여기서 고정하는 것:
  * GET 은 405 이고 대시보드를 만들지 않는다(조회수가 늘어도 상태가 안 변한다).
  * POST 는 만든다. 만든 것으로 이동시킨다.
  * 권한이 없거나 로그인하지 않았으면 POST 도 만들지 않는다.
  * CSRF 토큰 없는 POST 는 받지 않는다(폼이 토큰을 실어 보내야 한다).
  * 템플릿에 GET 링크(`href="/dashboard-add"`)가 다시 생기지 않는다.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))

_TEMPLATES = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'aot_flask', 'templates'))


class _DashboardAddFixture(unittest.TestCase):
    """routes_dashboard 블루프린트 하나만 등록한 임시 앱 (임시 sqlite, 라이브 DB 미사용)."""

    def setUp(self):
        from flask import Blueprint, Flask
        import flask_login
        from flask_babel import Babel
        from flask_wtf.csrf import generate_csrf

        from aot.aot_flask.extensions import db, csrf
        import aot.databases.models  # noqa: F401 — 모델 등록
        from aot.databases.models import Dashboard, Role, User
        from aot.aot_flask import routes_dashboard

        self._tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp.name, 'test.db')

        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(db_path)
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False   # CSRF 를 보는 테스트만 켠다
        app.config['TESTING'] = True
        app.config['SESSION_PROTECTION'] = None

        db.init_app(app)
        csrf.init_app(app)
        Babel(app)
        app.register_blueprint(routes_dashboard.blueprint)

        # 권한이 없을 때 `redirect(url_for('routes_general.home'))` 가 갈 자리.
        general = Blueprint('routes_general', __name__)

        @general.route('/')
        def home():
            return 'home'

        @general.route('/csrf-for-test')
        def token():
            return generate_csrf()

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
        self.db = db
        self.Dashboard = Dashboard

        with app.app_context():
            db.create_all()

            editor = Role()
            editor.name = 'Editor'
            editor.edit_controllers = True
            viewer = Role()
            viewer.name = 'Guest'
            viewer.edit_controllers = False
            db.session.add_all([editor, viewer])
            db.session.commit()

            self._login_ids = {}
            for name, role in (('editor', editor), ('guest', viewer)):
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

            # 이미 대시보드가 하나 있는 보통 상태 — 새 이름은 마지막 id + 1 로
            # 만들어진다.
            first = Dashboard()
            first.name = 'Dashboard 1'
            first.save()

        self.client = app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def _login(self, name):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = self._login_ids[name]
            sess['_fresh'] = True

    def _count(self):
        with self.app.app_context():
            return self.Dashboard.query.count()


class TestGetDoesNotWrite(_DashboardAddFixture):

    def test_get_is_405_and_creates_nothing(self):
        self._login('editor')
        before = self._count()
        resp = self.client.get('/dashboard-add')
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(self._count(), before)

    def test_get_many_times_still_creates_nothing(self):
        # 링크 미리읽기·새로고침·E2E 가 열 때마다 하나씩 쌓이던 원래 증상.
        self._login('editor')
        before = self._count()
        for _ in range(5):
            self.client.get('/dashboard-add')
            self.client.get('/dashboard-add', follow_redirects=True)
        self.assertEqual(self._count(), before)

    def test_head_and_options_do_not_write_either(self):
        self._login('editor')
        before = self._count()
        self.client.head('/dashboard-add')
        self.client.options('/dashboard-add')
        self.assertEqual(self._count(), before)

    def test_route_only_advertises_post(self):
        # L0·L1 은 "인자 없는 GET" 을 수집한다. GET 이 라우트 메서드에 남아
        # 있으면 다시 수집 대상이 된다.
        methods = set()
        for rule in self.app.url_map.iter_rules():
            if rule.rule == '/dashboard-add':
                methods |= set(rule.methods)
        self.assertIn('POST', methods)
        self.assertNotIn('GET', methods)


class TestPostCreates(_DashboardAddFixture):

    def test_post_creates_one_and_redirects_to_it(self):
        self._login('editor')
        before = self._count()
        resp = self.client.post('/dashboard-add')
        self.assertEqual(self._count(), before + 1)
        self.assertEqual(resp.status_code, 302)

        with self.app.app_context():
            newest = self.Dashboard.query.order_by(
                self.Dashboard.id.desc()).first()
            self.assertTrue(resp.headers['Location'].endswith(
                '/dashboard/{}'.format(newest.unique_id)))

    def test_each_post_creates_exactly_one(self):
        self._login('editor')
        before = self._count()
        self.client.post('/dashboard-add')
        self.client.post('/dashboard-add')
        self.assertEqual(self._count(), before + 2)

    def test_post_without_permission_creates_nothing(self):
        self._login('guest')
        before = self._count()
        resp = self.client.post('/dashboard-add')
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('/dashboard/', resp.headers['Location'])
        self.assertEqual(self._count(), before)

    def test_anonymous_post_creates_nothing(self):
        before = self._count()
        resp = self.client.post('/dashboard-add')
        self.assertIn(resp.status_code, (302, 401))
        self.assertEqual(self._count(), before)


class TestCsrf(_DashboardAddFixture):

    def test_post_without_token_is_rejected_and_creates_nothing(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self._login('editor')
        before = self._count()
        resp = self.client.post('/dashboard-add')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._count(), before)

    def test_post_with_token_creates(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self._login('editor')
        token = self.client.get('/csrf-for-test').get_data(as_text=True)
        before = self._count()
        resp = self.client.post('/dashboard-add', data={'csrf_token': token})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._count(), before + 1)


class TestTemplatesUsePostForms(unittest.TestCase):
    """화면이 GET 링크로 돌아가지 못하게 템플릿 자체를 고정한다."""

    _FILES = ('layout.html', 'layout_default.html', 'pages/dashboard.html')

    def _read(self, rel):
        with open(os.path.join(_TEMPLATES, rel), encoding='utf-8') as f:
            return f.read()

    def test_no_get_link_to_dashboard_add_anywhere(self):
        offenders = []
        for dirpath, _dirs, files in os.walk(_TEMPLATES):
            for name in files:
                if not name.endswith('.html'):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding='utf-8') as f:
                    text = f.read()
                if re.search(r'href\s*=\s*["\']/?dashboard-add', text):
                    offenders.append(os.path.relpath(path, _TEMPLATES))
        self.assertEqual(offenders, [],
                         'GET 링크로 대시보드를 추가하는 템플릿이 있습니다')

    def test_add_forms_post_with_csrf_token(self):
        for rel in self._FILES:
            text = self._read(rel)
            match = re.search(
                r'<form\b[^>]*action="\{\{\s*url_for\(\'routes_dashboard'
                r'\.page_dashboard_add\'\)\s*\}\}"[^>]*>(.*?)</form>',
                text, re.S)
            self.assertIsNotNone(match, '{}: 추가 폼이 없습니다'.format(rel))
            self.assertRegex(match.group(0), r'method="post"',
                             '{}: POST 폼이 아닙니다'.format(rel))
            self.assertIn('name="csrf_token"', match.group(1),
                          '{}: CSRF 토큰이 없습니다'.format(rel))

    def test_layout_and_layout_default_stay_identical(self):
        # layout.html 은 재시작 때 layout_default.html 로 덮어써진다.
        self.assertEqual(self._read('layout.html'),
                         self._read('layout_default.html'))


if __name__ == '__main__':
    unittest.main()
