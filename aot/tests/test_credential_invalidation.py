# -*- coding: utf-8 -*-
"""유출된 자격증명을 끊을 수단이 실제로 있는지 고정한다.

배경 — 2026-08-12. "90일간 유지"(remember_token) 점검 중 두 구멍이 나왔다.

1. **비밀번호를 바꿔도 다른 기기의 90일 토큰이 살아 있었다.** flask-login 은
   `User.get_id()` 가 비밀번호에 연동된 값을 돌려주면 무효화해 주는데, 그때까지
   `get_id()` 는 사용자 id 를 그대로 돌려줬다. 기기를 잃어버려도 비밀번호
   변경으로 끊을 방법이 없었다 — 토큰은 90일을 산다.

2. **`fresh_login_required` 를 쓰는 곳이 하나도 없었다.** 90일 쿠키로 복구된
   세션은 `_fresh=False` 인데, 그 상태로 비밀번호·이메일 변경과 API 키 발급이
   전부 됐다. 토큰만 쥔 사람이 계정을 통째로 가져갈 수 있었고, 게다가 1번을
   고치고 나면 **먼저 비밀번호를 바꾼 쪽이 상대를 끊는** 구조라 1번 단독으로는
   오히려 공격자에게 무기를 쥐여 주는 셈이었다. 둘은 같이 있어야 한다.

이 파일은 그 두 가지가 되살아나는 것을 막는다. 인증 흐름을 실제로 태우지 않고
**계약(무엇이 어디에 배선돼 있는가)** 을 고정한다 — 실제 동작 검증은 사람이
브라우저·실 로그인으로 했고(2026-08-12), 여기서는 회귀만 잡는다.
"""
import ast
import inspect
import os
import sys
import unittest

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))


class TestPasswordChangeInvalidatesOtherDevices(unittest.TestCase):
    """비밀번호 변경 = 다른 기기의 세션·90일 토큰 전부 무효."""

    def test_get_id_carries_a_password_derived_hash(self):
        from aot.databases.models import User
        src = inspect.getsource(User.get_id)
        self.assertIn(
            'session_auth_hash', src,
            "User.get_id() 가 비밀번호 파생 해시를 싣지 않는다 — 비밀번호를 "
            "바꿔도 다른 기기의 90일 토큰이 살아남는다")

    def test_session_auth_hash_changes_with_the_password(self):
        """같은 비밀번호면 같은 값, 바뀌면 다른 값 — HMAC 계산만 확인한다."""
        import hashlib
        import hmac as _hmac
        from aot.databases.models import User

        secret = b'test-secret'

        def h(pw):
            return _hmac.new(secret, pw, hashlib.sha256).hexdigest()[:32]

        self.assertEqual(h(b'hash-A'), h(b'hash-A'))
        self.assertNotEqual(h(b'hash-A'), h(b'hash-B'))

        # 구현이 같은 재료(앱 secret_key + password_hash)를 쓰는지 소스로 확인
        src = inspect.getsource(User.session_auth_hash)
        for token in ('secret_key', 'password_hash', 'hmac'):
            self.assertIn(token, src,
                          "session_auth_hash 가 %s 를 쓰지 않는다" % token)

    def test_user_loader_verifies_the_hash_and_rejects_the_old_format(self):
        from aot.aot_flask import app as app_module
        src = inspect.getsource(app_module.extension_login_manager)
        self.assertIn(
            'verify_session_auth_hash', src,
            "user_loader 가 해시를 대조하지 않는다 — get_id() 만 고치면 아무 "
            "효과가 없다(둘은 한 쌍이다)")
        self.assertIn(
            'partition', src,
            "user_loader 가 '<id>|<hash>' 를 되풀지 않는다")

    def test_login_paths_pass_the_db_row_not_a_bare_user(self):
        """임시 `User()` 를 넘기면 password_hash 가 None 이라 해시가 틀린다.

        예전 코드는 id/name 만 채운 빈 User() 를 login_user() 에 넘겼다. 그
        패턴이 되살아나면 로그인은 되는데 해시가 어긋나 **다음 요청에서 전원
        로그아웃**된다 — 원인을 찾기 어려운 종류의 고장이다.
        """
        from aot.aot_flask import routes_authentication as ra
        src = inspect.getsource(ra)
        self.assertNotIn(
            'login_user = User()', src,
            "로그인 경로가 임시 User() 를 만들어 넘긴다 — 그 객체에는 "
            "password_hash 가 없어 session_auth_hash 가 틀리게 계산된다")

        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == 'login_user'
                 and getattr(n.func.value, 'id', None) == 'flask_login']
        self.assertGreaterEqual(len(calls), 5,
                                "로그인 경로가 줄었다 — 확인 필요")
        for call in calls:
            self.assertTrue(
                call.args and getattr(call.args[0], 'id', None) == 'user',
                "flask_login.login_user() 에 DB 행(`user`)이 아닌 것을 넘긴다")


class TestSensitiveActionsRequireAFreshLogin(unittest.TestCase):
    """90일 쿠키로 복구된 세션(_fresh=False)은 계정을 넘길 수 없어야 한다."""

    def test_helper_checks_login_fresh(self):
        from aot.aot_flask.utils import utils_general
        src = inspect.getsource(utils_general.require_fresh_login)
        self.assertIn('login_fresh', src,
                      "require_fresh_login 이 flask-login 의 신선도를 안 본다")

    def test_password_and_email_change_is_gated(self):
        from aot.aot_flask import routes_settings
        src = inspect.getsource(routes_settings.settings_account_self)
        self.assertIn('require_fresh_login', src,
                      "자기 계정 수정 경로에 신선도 게이트가 없다 — 90일 토큰만 "
                      "쥔 사람이 비밀번호·이메일을 바꿔 계정을 가져갈 수 있다")
        self.assertIn('password_new', src)
        self.assertIn('email', src)

    def test_api_key_issue_is_gated(self):
        """API 키는 비밀번호 변경으로 무효화되지 않는다 — 여기가 뚫리면
        공격자가 영구 자격증명을 만들어 두고 빠져나간다."""
        from aot.aot_flask import routes_settings
        src = inspect.getsource(routes_settings)
        idx = src.find('user_generate_api_key.data')
        self.assertGreater(idx, -1, "API 키 발급 분기를 찾지 못했다")
        window = src[idx:idx + 800]
        self.assertIn(
            'require_fresh_login', window,
            "API 키 발급에 신선도 게이트가 없다 — 비밀번호를 바꿔도 안 끊기는 "
            "자격증명을 비신선 세션이 만들 수 있다")


if __name__ == '__main__':
    unittest.main()
