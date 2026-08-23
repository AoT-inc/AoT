# coding=utf-8
"""사용자 지정 이름 번역의 HTTP 경계를 실제 라우트로 검증한다.

단위 테스트가 서비스 함수를 덮는다면, 여기서 보는 것은 브라우저가 실제로 받는
것이다 — 기능이 꺼져 있을 때 무엇이 내려가는지, 켜져 있을 때 사전이 제대로
실리는지, 그리고 관리 화면의 수정이 잠금으로 이어지는지.

가장 중요한 계약: **기능이 꺼져 있으면 사전이 비어 있어야 한다.** 사전이 비면
클라이언트 치환기는 아무 것도 하지 않으므로, 꺼진 상태의 동작이 지금과 정확히
같아진다.

설계: docs/design/user-string-live-translation.md
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))


class _TranslationAppFixture(unittest.TestCase):
    """locale/settings 블루프린트를 올린 임시 앱 (임시 sqlite, 라이브 DB 미사용)."""

    def setUp(self):
        from flask import Flask
        import flask_login
        from flask_babel import Babel

        from aot.aot_flask.extensions import cache, csrf, db
        import aot.databases.models  # noqa: F401 — 모델 등록
        from aot.databases.models import AIGlobalSettings, Role, User
        from aot.aot_flask import routes_locale_api, routes_settings

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
        app.config['CACHE_TYPE'] = 'NullCache'

        db.init_app(app)
        csrf.init_app(app)
        cache.init_app(app)
        # 실제 앱과 같이 계정 언어를 로케일로 삼는다 — 이 기능의 대상 언어가
        # 곧 그 값이므로, 여기가 어긋나면 테스트가 검증하는 것이 달라진다.
        def _locale_selector():
            try:
                user = flask_login.current_user
                if user is not None and getattr(user, 'language', None):
                    return user.language
            except Exception:
                pass
            return 'en'

        Babel(app, locale_selector=_locale_selector)
        app.register_blueprint(routes_locale_api.blueprint)
        app.register_blueprint(routes_settings.blueprint)

        # routes_settings 는 성공/실패 안내에 routes_general.home 을 링크로
        # 쓴다. 그 블루프린트까지 올리면 앱 전체를 부팅하는 셈이라, 이름만
        # 맞춘 자리표시자를 둔다.
        from flask import Blueprint as _Blueprint
        _general = _Blueprint('routes_general', __name__)

        @_general.route('/')
        def home():
            return ''

        app.register_blueprint(_general)

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
            role.view_settings = True
            role.edit_settings = True
            db.session.add(role)
            db.session.commit()

            user = User()
            user.name = 'tester'
            user.email = 'tester@example.com'
            user.is_enabled = True
            user.is_approved = True
            user.role_id = role.id
            user.language = 'ja'
            user.set_password('correct horse battery staple')
            db.session.add(user)

            # 설정 페이지 렌더는 전역 컨텍스트 프로세서를 타고, 그쪽이 Misc 를
            # 무조건 읽는다. 실제 설치에는 항상 있는 행이다.
            from aot.databases.models import Misc
            db.session.add(Misc())

            settings = AIGlobalSettings()
            settings.ai_enabled = True
            settings.user_string_translation_enabled = True
            db.session.add(settings)
            db.session.commit()

            self.user_id = user.id
            self._login_id = user.get_id()

        self.client = app.test_client()
        self._login()

    def tearDown(self):
        self._tmp.cleanup()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = self._login_id
            sess['_fresh'] = True

    def _set_feature(self, enabled):
        from aot.databases.models import AIGlobalSettings
        from aot.aot_flask.extensions import db
        with self.app.app_context():
            settings = AIGlobalSettings.query.first()
            settings.user_string_translation_enabled = enabled
            db.session.commit()

    def _seed(self, source, translated, lang='ja', status='done'):
        from aot.aot_flask.extensions import db
        from aot.databases.models.user_string_translation import \
            UserStringTranslation
        from aot.ai.services import user_string_translator as ust
        with self.app.app_context():
            db.session.add(UserStringTranslation(
                source_hash=ust.text_hash(source),
                source_text=source,
                source_lang='ko',
                target_lang=lang,
                translated_text=translated,
                domain='zone',
                status=status))
            db.session.commit()

    def _catalog_js(self):
        response = self.client.get('/api/v1/locale/user_strings.js')
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)


class TestCatalogEndpoint(_TranslationAppFixture):

    def test_serves_translations_when_enabled(self):
        self._seed('1번 하우스', '1号ハウス')
        js = self._catalog_js()
        self.assertIn('1号ハウス', js)
        self.assertIn('AOT_USER_I18N', js)

    def test_empty_dictionary_when_feature_is_off(self):
        """꺼져 있으면 사전이 비어야 한다 — 치환기가 아무 것도 하지 않도록."""
        self._seed('1번 하우스', '1号ハウス')
        self._set_feature(False)
        js = self._catalog_js()
        self.assertNotIn('1号ハウス', js)
        self.assertIn('window.AOT_USER_I18N = {};', js)
        self.assertIn('window.AOT_USER_I18N_LANG = null;', js)

    def test_user_opt_out_empties_the_dictionary(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import User
        self._seed('1번 하우스', '1号ハウス')
        with self.app.app_context():
            User.query.get(self.user_id).translate_user_strings = False
            db.session.commit()
        js = self._catalog_js()
        self.assertNotIn('1号ハウス', js)

    def test_pending_entries_are_listed_separately(self):
        self._seed('1번 하우스', '1号ハウス')
        self._seed('동편 밸브', None, status='pending')
        js = self._catalog_js()
        self.assertIn('AOT_USER_I18N_PENDING', js)
        # pending 은 사전이 아니라 pending 목록에만 있어야 한다.
        pending = js.split('AOT_USER_I18N_PENDING = ')[1].split(';')[0]
        self.assertIn('동편 밸브', pending)
        entries = js.split('AOT_USER_I18N = ')[1].split(';window')[0]
        self.assertNotIn('동편 밸브', entries)

    def test_response_varies_on_language(self):
        response = self.client.get('/api/v1/locale/user_strings.js')
        self.assertIn('Accept-Language', response.headers.get('Vary', ''))

    def test_never_500s_on_a_broken_backend(self):
        """어떤 오류에서도 화면은 원문으로 살아 있어야 한다."""
        from unittest.mock import patch
        with patch('aot.ai.services.user_string_translator.build_catalog',
                   side_effect=RuntimeError('boom')):
            response = self.client.get('/api/v1/locale/user_strings.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('window.AOT_USER_I18N = {};',
                      response.get_data(as_text=True))


class TestTranslateEndpoint(_TranslationAppFixture):

    def _post(self, texts):
        return self.client.post(
            '/api/v1/locale/user_strings/translate',
            data=json.dumps({'texts': texts}),
            content_type='application/json')

    def test_returns_cached_entries_without_calling_an_engine(self):
        self._seed('1번 하우스', '1号ハウス')
        response = self._post(['1번 하우스'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['entries'],
                         {'1번 하우스': '1号ハウス'})

    def test_reports_disabled_without_touching_the_queue(self):
        from aot.databases.models.user_string_translation import \
            UserStringTranslation
        self._set_feature(False)
        response = self._post(['생소한 이름'])
        self.assertFalse(response.get_json()['enabled'])
        with self.app.app_context():
            self.assertEqual(UserStringTranslation.query.count(), 0)

    def test_rejects_a_non_list_payload(self):
        response = self.client.post(
            '/api/v1/locale/user_strings/translate',
            data=json.dumps({'texts': 'not a list'}),
            content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_unknown_names_are_queued_not_lost(self):
        """엔진이 없어도 요청한 이름은 큐에 남아 나중에 번역된다."""
        from aot.databases.models.user_string_translation import \
            UserStringTranslation
        self._post(['남쪽 온실 3동'])
        with self.app.app_context():
            row = UserStringTranslation.query.filter_by(
                source_text='남쪽 온실 3동').first()
            self.assertIsNotNone(row)
            self.assertEqual(row.target_lang, 'ja')


class TestManagementPage(_TranslationAppFixture):

    def test_page_hands_the_template_what_it_needs(self):
        """라우트가 준비하는 컨텍스트를 본다.

        임시 앱에는 layout 이 참조하는 다른 블루프린트가 없어 전체 렌더는
        여기서 확인할 수 없다. 템플릿 문법 자체는 아래 TestTemplateSyntax 가,
        실제 화면은 브라우저 확인이 덮는다.
        """
        from unittest.mock import patch
        self._seed('1번 하우스', '1号ハウス')

        captured = {}

        def _capture(template, **context):
            captured['template'] = template
            captured['context'] = context
            return ''

        with patch('aot.aot_flask.routes_settings.render_template',
                   side_effect=_capture):
            response = self.client.get('/settings/translations?lang=ja')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['template'], 'settings/translations.html')
        ctx = captured['context']
        self.assertEqual(ctx['lang'], 'ja')
        self.assertEqual([r.source_text for r in ctx['rows']], ['1번 하우스'])
        self.assertEqual(ctx['counts']['done'], 1)
        self.assertIn('ja', ctx['langs'])

    def test_status_filter_narrows_the_list(self):
        self._seed('1번 하우스', '1号ハウス')
        self._seed('동편 밸브', None, status='pending')

        from unittest.mock import patch
        captured = {}

        def _capture(template, **context):
            captured.update(context)
            return ''

        with patch('aot.aot_flask.routes_settings.render_template',
                   side_effect=_capture):
            self.client.get('/settings/translations?lang=ja&status=pending')

        self.assertEqual([r.source_text for r in captured['rows']], ['동편 밸브'])

    def test_editing_a_translation_locks_it(self):
        from aot.databases.models.user_string_translation import \
            UserStringTranslation
        self._seed('1번 하우스', '1号ハウス')
        with self.app.app_context():
            row_id = UserStringTranslation.query.first().id

        response = self.client.post(
            '/settings/translations/save',
            data=json.dumps({'id': row_id, 'translated_text': '第1ハウス'}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            row = UserStringTranslation.query.get(row_id)
            self.assertEqual(row.translated_text, '第1ハウス')
            self.assertTrue(row.is_locked)

    def test_retranslate_all_spares_hand_edited_rows(self):
        """사람이 고친 값은 일괄 재번역이 지우면 안 된다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models.user_string_translation import \
            UserStringTranslation
        self._seed('1번 하우스', '1号ハウス')
        self._seed('동편 밸브', '東バルブ')
        with self.app.app_context():
            locked = UserStringTranslation.query.filter_by(
                source_text='1번 하우스').first()
            locked.is_locked = True
            db.session.commit()

        self.client.post('/settings/translations/retranslate',
                         data=json.dumps({'lang': 'ja'}),
                         content_type='application/json')

        with self.app.app_context():
            kept = UserStringTranslation.query.filter_by(
                source_text='1번 하우스').first()
            reset = UserStringTranslation.query.filter_by(
                source_text='동편 밸브').first()
            self.assertEqual(kept.translated_text, '1号ハウス')
            self.assertIsNone(reset.translated_text)

    def test_write_routes_require_edit_permission(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Role
        with self.app.app_context():
            role = Role.query.first()
            role.edit_settings = False
            db.session.commit()

        response = self.client.post('/settings/translations/save',
                                    data=json.dumps({'id': 1}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 403)


class TestUserPreference(_TranslationAppFixture):
    """계정별 on/off 가 실제로 저장되는지 — 켤 수도 끌 수도 없는 설정은 죽은 설정이다."""

    def _save_account(self, **extra):
        data = {'name': 'tester', 'email': 'tester@example.com',
                'language': 'ja', 'timezone': '', 'user_account_save': 'Save'}
        data.update(extra)
        # 이 라우트는 저장 후 referrer 로 돌아간다. 임시 앱에는 폴백
        # 엔드포인트(routes_general.home)가 없으므로 referrer 를 준다.
        return self.client.post('/settings/account_self', data=data,
                                headers={'Referer': '/settings/translations'})

    def _stored(self):
        from aot.databases.models import User
        with self.app.app_context():
            return User.query.filter_by(id=self.user_id).first() \
                .translate_user_strings

    def test_unchecking_the_box_turns_it_off(self):
        self._save_account()          # 체크박스 미포함 = 해제
        self.assertIs(self._stored(), False)

    def test_checking_the_box_turns_it_on(self):
        self._save_account(translate_user_strings='y')
        self.assertIs(self._stored(), True)

    def test_saving_while_the_feature_is_off_does_not_clobber_the_choice(self):
        """전역이 꺼져 있으면 모달에 칸이 없다 — 그 저장이 값을 끄면 안 된다.

        끄고 나서 다시 켰을 때, 사용자가 끈 적도 없이 꺼진 채로 남는 일을
        막는다.
        """
        self._save_account(translate_user_strings='y')
        self.assertIs(self._stored(), True)

        self._set_feature(False)
        self._save_account()          # 칸이 없는 폼으로 저장
        self.assertIs(self._stored(), True)


class TestTemplateSyntax(unittest.TestCase):
    """관리 화면 템플릿이 Jinja 문법으로 성립하는지."""

    def test_template_parses(self):
        import jinja2
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'settings', 'translations.html')
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        env = jinja2.Environment(extensions=['jinja2.ext.i18n'])
        env.parse(source)   # 문법 오류면 여기서 예외

    def test_table_never_renders_a_form_field_for_the_original(self):
        """원문 칸은 읽기 전용이어야 한다 — 여기서 고치면 원문이 바뀐다."""
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'settings', 'translations.html')
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        original_cell = source.split('<td>{{row.source_text}}</td>')
        self.assertEqual(len(original_cell), 2,
                         '원문 칸이 단순 출력이 아니다')


if __name__ == '__main__':
    unittest.main()
