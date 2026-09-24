# coding=utf-8
"""`user_mod` 의 "자기 비밀번호를 바꾸면 로그아웃" 가드.

`aot/aot_flask/utils/utils_settings.py::user_mod` 는 비밀번호를 바꾼 대상이
지금 로그인한 사람 자신이면 그 자리에서 로그아웃시켜야 한다(관리자 화면
`settings/users` 에서 자기 비밀번호를 바꿀 때). 그런데 그 판정이

    flask_login.current_user.id == form.user_id.data

였다 — `current_user.id` 는 정수 기본키, `form.user_id.data` 는 계정의
unique_id(문자열)다. 타입이 달라 **항상 거짓**이라 자기 비밀번호를 바꿔도
로그아웃되지 않았다. `user_del` 의 자기 자신 삭제 가드에 있던 것과 정확히
같은 버그이고(claude/mcp-record-write-guard, 커밋 878bfcdb4에서 그쪽만
`unique_id` 끼리 비교하도록 먼저 고쳐졌다), 여기서는 `user_mod` 쪽을 같은
패턴으로 고친다.

다른 기기에 남아 있던 세션·"90일 유지" 쿠키는 이 로그아웃 플래그와 무관하게
이미 `password_hash` 변경만으로 무효화된다 — 세션에 실리는
`session_auth_hash()` 가 비밀번호 해시에서 파생되고, 매 요청 `user_loader`
(app.py)가 그것을 대조하기 때문이다(`User.session_auth_hash` 문서 참조).
`test_changing_own_password_changes_the_hash_other_sessions_are_checked_against`
가 그 전제를 함께 잠근다 — 여기서 고치는 `logout` 플래그는 **지금 이 요청을
보낸 탭**을 그 순간 정리해 주는 것일 뿐, 다른 기기 로그아웃은 이미 별도
메커니즘이 담당한다.
"""
import types

import flask_login

from aot.databases.models import User
from aot.tests.test_mcp_record_write_guard import _Fixture


class TestUserModPasswordLogout(_Fixture):

    @staticmethod
    def _form(target, password_new='', password_repeat=None):
        d = lambda v: types.SimpleNamespace(data=v)  # noqa: E731
        return types.SimpleNamespace(
            user_id=d(target.unique_id),
            email=d(target.email),
            full_name=d(target.full_name or ''),
            code=d(''),
            password_new=d(password_new),
            password_repeat=d(password_new if password_repeat is None
                              else password_repeat),
            role_id=d(target.role_id),
            is_enabled=d(target.is_enabled),
            theme=d(target.theme or 'dark'))

    def _mod(self, who, target, **form_kwargs):
        from aot.aot_flask.utils import utils_settings
        form = self._form(target, **form_kwargs)
        with self.app.test_request_context():
            flask_login.login_user(self._user(who))
            return utils_settings.user_mod(form)

    def test_own_password_change_logs_out(self):
        admin = self._user('Admin')
        messages, logout = self._mod('Admin', admin,
                                     password_new='S3curePassphrase!')
        self.assertFalse(messages['error'], messages)
        self.assertTrue(logout)

    def test_admin_changing_anothers_password_does_not_log_admin_out(self):
        editor = self._user('Editor')
        messages, logout = self._mod('Admin', editor,
                                     password_new='An0therPassphrase!')
        self.assertFalse(messages['error'], messages)
        self.assertFalse(logout)

    def test_non_password_self_edit_does_not_log_out(self):
        """자기 자신을 고쳐도 비밀번호가 안 바뀌면 로그아웃할 이유가 없다."""
        admin = self._user('Admin')
        messages, logout = self._mod('Admin', admin, password_new='')
        self.assertFalse(messages['error'], messages)
        self.assertFalse(logout)

    def test_changing_own_password_changes_the_hash_other_sessions_are_checked_against(self):
        """다른 기기 세션은 이 해시 변화로 끊긴다 — logout 플래그와는 별개."""
        admin = self._user('Admin')
        before = admin.session_auth_hash()
        messages, logout = self._mod('Admin', admin,
                                     password_new='YetAnotherPass1!')
        self.assertFalse(messages['error'], messages)
        db_admin = User.query.filter(User.id == admin.id).first()
        self.assertNotEqual(before, db_admin.session_auth_hash())
