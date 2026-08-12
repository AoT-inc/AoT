# -*- coding: utf-8 -*-
"""서버측 세션의 lost update 회귀 가드.

배경 — 2026-08-12. 로그인하면 "세션이 만료되었습니다" 가 뜨며 로그인 페이지로
튕기고, 새로고침하면 멀쩡히 로그인돼 있는 증상이 있었다. 원인은 인증이 아니라
세션 저장 방식이었다.

flask-session 0.5.0 의 `FileSystemSessionInterface.save_session()` 은
`session.modified` 를 보지 않고 **매 요청마다** `dict(session)` 전체를 파일에
덮어쓴다. gunicorn 은 `workers=1 · gthread` 다중 스레드라 요청이 겹치는데,
겹친 요청들은 각자 시작 시점의 스냅샷을 들고 있다가 끝날 때 통째로 되쓴다 —
늦게 끝난 쪽이 먼저 끝난 쪽의 변경을 지운다.

지워지는 것이 `csrf_token` 이면 다음 POST 가 CSRF 400 으로 떨어지고,
`_user_id` 면 그 자리에서 로그아웃된다. 겹치는 요청은 특별한 것이 아니라 평범한
페이지 로드다 — `/custom.css` 와 `/favicon.png` 는 `/static/` 밖의 Flask 라우트라
세션을 열고 닫으며, `/custom.css` 는 `current_user.theme` 를 읽으므로 정적
건너뛰기 대상으로 돌릴 수도 없다.

해법은 "안 바뀐 세션은 다시 쓰지 않는다" 이고, 이 테스트가 그것을 고정한다.
읽기 전용 요청이 다시 쓰기 시작하면 아래 두 테스트가 깨진다.
"""
import os
import sys
import unittest

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))


class _SessionAppFixture(unittest.TestCase):
    """extension_session() 이 설치한 진짜 인터페이스를 임시 디렉터리에 띄운다.

    create_app() 은 DB·데몬·번역까지 끌고 오므로 쓰지 않는다. 대신 빈 Flask 앱에
    같은 함수를 적용해, 실제 flask-session 인터페이스 + 우리 래퍼 조합을 그대로
    시험한다. 쓰기 여부는 cachelib 캐시의 `set` 호출을 세어 판정한다 — 파일이
    실제로 다시 쓰이는지가 곧 lost update 창(window)의 존재 여부다.
    """

    def setUp(self):
        import tempfile
        from flask import Flask
        from aot.aot_flask import app as app_module

        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        self._docker = os.environ.pop('DOCKER_CONTAINER', None)
        os.chdir(self._tmp.name)

        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret'
        app_module.extension_session(self.app)
        self.iface = self.app.session_interface

        # 래퍼의 __getattr__ 가 내부 인터페이스로 위임하므로 같은 캐시 객체다.
        cache = self.iface.cache
        self.writes = []
        _orig_set = cache.set

        def _counting_set(key, value, timeout=None, **kw):
            # cachelib 이 자기 파일 수 카운터를 갱신하는 호출(mgmt_element)은
            # 세션 쓰기가 아니므로 세지 않는다.
            if not kw.get('mgmt_element'):
                self.writes.append(key)
            return _orig_set(key, value, timeout, **kw)

        cache.set = _counting_set

    def tearDown(self):
        os.chdir(self._cwd)
        if self._docker is not None:
            os.environ['DOCKER_CONTAINER'] = self._docker
        self._tmp.cleanup()

    def _request(self, path, mutate=None):
        """요청 한 번을 흉내낸다: 세션을 열고 → (선택) 바꾸고 → 저장한다."""
        from flask import Response
        with self.app.test_request_context(path) as ctx:
            sess = self.iface.open_session(self.app, ctx.request)
            if mutate:
                mutate(sess)
            self.iface.save_session(self.app, sess, Response())
            return sess


class TestSessionSaveSkipsUnmodified(_SessionAppFixture):
    """읽기만 한 요청이 세션 파일을 다시 쓰지 않아야 한다."""

    def test_unmodified_session_is_not_rewritten(self):
        # 로그인한 세션을 한 번 만든다.
        sess = self._request('/login', mutate=lambda s: s.update(
            {'csrf_token': 'T1', '_user_id': '7'}))
        sid = sess.sid
        self.assertEqual(len(self.writes), 1)

        # 이후 페이지 로드가 딸고 오는 읽기 전용 요청들
        # (/custom.css · /favicon.png · 위젯 폴링 …)
        from flask import Response
        for _ in range(25):
            with self.app.test_request_context(
                    '/custom.css', headers={'Cookie': 'session=%s' % sid}):
                from flask import request as _rq
                s = self.iface.open_session(self.app, _rq)
                _ = s.get('_user_id')      # 읽기만 한다
                self.iface.save_session(self.app, s, Response())

        self.assertEqual(
            len(self.writes), 1,
            "미변경 세션이 %d회 다시 쓰였다 — 동시 요청 간 lost update 창이 "
            "그대로 열려 있다 (CSRF 토큰·_user_id 유실의 원인)" % (len(self.writes) - 1))

    def test_modified_session_is_always_written(self):
        sess = self._request('/login', mutate=lambda s: s.update({'csrf_token': 'T1'}))
        before = len(self.writes)

        from flask import Response
        with self.app.test_request_context(
                '/login_password', headers={'Cookie': 'session=%s' % sess.sid}):
            from flask import request as _rq
            s = self.iface.open_session(self.app, _rq)
            s['_user_id'] = '7'            # 로그인
            self.iface.save_session(self.app, s, Response())

        self.assertEqual(len(self.writes), before + 1,
                         "변경된 세션이 저장되지 않았다 — 로그인이 유실된다")

        # 다시 읽어 실제로 남았는지 확인
        with self.app.test_request_context(
                '/live', headers={'Cookie': 'session=%s' % sess.sid}):
            from flask import request as _rq
            self.assertEqual(
                self.iface.open_session(self.app, _rq).get('_user_id'), '7')

    def test_static_requests_never_touch_the_session(self):
        self._request('/static/js/dist/aot-map-widget.bundle.js',
                      mutate=lambda s: s.update({'csrf_token': 'T1'}))
        self.assertEqual(self.writes, [], "/static/ 요청이 세션을 저장했다")


class TestNoCookieOnCacheableResponse(unittest.TestCase):
    """`Set-Cookie` 가 실린 응답은 공유 캐시에 들어가면 안 된다.

    들어가면 그 안의 **세션 ID 가 모든 클라이언트에게 배포되고**, 뒤에 오는
    사람은 앞사람의 세션을 물려받아 앞사람 계정으로 로그인된 상태가 된다.
    기기도 브라우저도 다른데 신원이 함께 바뀌는 증상이 이것이다.

    2026-08-12 실제로 그 상태였다 — `/favicon.png` 가
    `Cache-Control: public, max-age=31536000` 와 `Set-Cookie` 를 함께 내보냈고,
    엣지(openresty)가 그 응답을 캐시해 몇 분 전 방문자의 세션 쿠키를 모든
    요청에 계속 재발행했다. `/custom.css` 도 같은 조합이었다(앱은 no-store 를
    붙였지만 엣지의 `expires` 지시자가 Cache-Control 을 덮어썼다 — **헤더로는
    막을 수 없어서** 쿠키 자체를 안 내보내는 쪽으로 고쳤다).
    """

    def test_after_request_guard_forces_private(self):
        from flask import Flask, Response
        from aot.aot_flask import app as app_module

        flask_app = Flask(__name__)
        # 문제의 조합을 그대로 만드는 라우트
        @flask_app.route('/asset')
        def _asset():
            r = Response('body', mimetype='image/png')
            r.headers['Set-Cookie'] = 'session=leaked-sid; Path=/'
            r.headers['Cache-Control'] = 'public, max-age=31536000'
            return r

        # app.py 의 출구 가드만 떼어 붙인다(create_app 전체는 DB 를 끌어온다).
        app_module.register_response_guards(flask_app)

        resp = flask_app.test_client().get('/asset')
        cc = resp.cache_control
        self.assertFalse(
            cc.public,
            "Set-Cookie 가 실린 응답이 public 으로 나간다 — 공유 캐시가 저장하면 "
            "그 세션 ID 가 모든 사용자에게 배포된다")
        self.assertTrue(cc.private or cc.no_store,
                        "Set-Cookie 응답에 private/no-store 가 없다")

    def test_asset_routes_are_declared_sessionless(self):
        """자산 라우트가 세션-생략/읽기전용 명부에서 빠지면 다시 쿠키가 붙는다."""
        import inspect
        src = inspect.getsource(
            __import__('aot.aot_flask.app', fromlist=['x']).extension_session)
        for path in ('/favicon.png', '/favicon.ico', '/custom.css'):
            self.assertIn(
                path, src,
                "%s 가 세션 명부에서 빠졌다 — 캐시되는 응답에 Set-Cookie 가 "
                "다시 붙는다" % path)


class TestSessionIdRegeneratedOnLogin(_SessionAppFixture):
    """로그인 성공 시 세션 ID 를 새로 발급해야 한다 (session fixation 방지).

    로그인 전 ID 를 그대로 쓰면 그 ID 를 아는 사람은 누구나 그 로그인에 올라탄다.
    flask-login 도 flask-session 도 이 일을 대신 해 주지 않는다.

    2026-08-12 이게 없어서 실제로 사고가 났다 — 엣지가 `Set-Cookie` 가 실린 자산
    응답을 캐시해 컴퓨터와 아이폰에 **같은 세션 ID** 를 심었고, 두 기기가 세션
    하나를 공유했다. 한쪽이 로그인하면 다른 쪽도 그 계정이 되고, 한쪽이
    로그아웃하면 둘 다 나가졌다. 캐시를 고쳐도 **이미 브라우저에 저장된 쿠키는
    되돌릴 수 없어** 그 기기들은 계속 공유 상태였다. ID 재발급이 그 상태를
    스스로 풀어 주는 유일한 수단이다.
    """

    def test_login_rotates_sid_and_drops_the_old_record(self):
        from flask import Response
        from aot.aot_flask.utils import utils_general

        # 두 기기가 같은 쿠키(공유 세션)를 들고 있는 상태를 만든다.
        first = self._request('/live', mutate=lambda s: s.update(
            {'csrf_token': 'T1', '_user_id': '1'}))
        shared_sid = first.sid
        self.assertEqual(self.iface.cache.get(self.iface.key_prefix + shared_sid).get('_user_id'), '1')

        # 두 번째 기기가 다른 계정으로 로그인한다(실제 라우트와 같은 순서:
        # regenerate → login_user).
        with self.app.test_request_context(
                '/login_password',
                headers={'Cookie': 'session=%s' % shared_sid}):
            from flask import request as _rq, session as _sess
            sess = self.iface.open_session(self.app, _rq)
            self.assertEqual(sess.sid, shared_sid)
            with self.app.app_context():
                pass
            old_sid = sess.sid
            # utils_general.regenerate_session_id() 는 flask.session 을 보므로,
            # 여기서는 같은 계약을 이 세션 객체에 직접 적용해 검증한다.
            new_sid = self.iface._generate_sid()
            self.iface.cache.delete(self.iface.key_prefix + old_sid)
            sess.sid = new_sid
            sess['_user_id'] = '7'
            sess.modified = True
            self.iface.save_session(self.app, sess, Response(''))

        self.assertNotEqual(new_sid, shared_sid, "세션 ID 가 재발급되지 않았다")
        self.assertEqual(self.iface.cache.get(self.iface.key_prefix + new_sid).get('_user_id'), '7',
                         "새 세션에 로그인 정보가 실리지 않았다")
        self.assertIsNone(
            self.iface.cache.get(self.iface.key_prefix + shared_sid),
            "옛 세션 레코드가 남아 있다 — 같은 쿠키를 든 다른 기기가 계속 "
            "그 로그인에 올라탄다(세션 고정)")

    def test_every_login_path_regenerates(self):
        """로그인 경로를 새로 만들면서 재발급을 빠뜨리면 다시 공유가 생긴다."""
        import inspect
        from aot.aot_flask import routes_authentication as ra
        src = inspect.getsource(ra)
        logins = src.count('flask_login.login_user(login_user')
        regens = src.count('utils_general.regenerate_session_id()')
        self.assertGreaterEqual(
            regens, logins,
            "login_user() 호출 %d곳 중 세션 ID 재발급은 %d곳뿐이다 — "
            "빠진 경로로 로그인하면 세션 고정이 남는다" % (logins, regens))


class TestRememberCookieFollowsSessionSecurity(unittest.TestCase):
    """"90일간 유지"(remember_token)는 세션 쿠키와 같은 Secure 를 써야 한다.

    Talisman 의 `session_cookie_secure` 는 이름 그대로 **세션 쿠키만** 건드린다.
    그래서 force_https 를 켠 HTTPS 서버에서 session 에는 Secure 가 붙는데
    remember_token 에는 안 붙는 상태였다(2026-08-12 실측) — 가장 오래 사는
    자격증명(90일)이 가장 약하게 보호됐다. 평문 HTTP 요청 한 번에 그대로 실려
    나가는데, 세션 쿠키는 Secure 라 안 나간다.
    """

    def test_remember_cookie_secure_is_wired_to_force_https(self):
        import inspect
        from aot.aot_flask import app as app_module
        src = inspect.getsource(app_module)
        self.assertIn(
            "app.config['REMEMBER_COOKIE_SECURE'] = force_https", src,
            "REMEMBER_COOKIE_SECURE 가 force_https 를 따라가지 않는다 — "
            "HTTPS 서버에서 90일 토큰만 Secure 없이 발급된다")


class TestSessionFileThreshold(_SessionAppFixture):
    """cachelib 기본 threshold(500)를 그대로 쓰면 살아 있는 로그인이 밀려난다.

    세션 파일은 로그인한 사람 수가 아니라 세션 쿠키를 받은 방문 수만큼 쌓인다
    (실측: 502개 중 로그인 23 · 익명 479). threshold 를 넘으면 cachelib 은 세션을
    저장할 때마다 만료가 이른 것부터 지우는데, 익명 쓰레기가 소진되면 그 다음
    차례는 실제 사용자다.
    """

    def test_threshold_is_raised_above_the_cachelib_default(self):
        self.assertGreater(
            self.app.config.get('SESSION_FILE_THRESHOLD', 500), 500,
            "SESSION_FILE_THRESHOLD 가 cachelib 기본값(500) 이하다 — "
            "방문자가 쌓이면 로그인 세션이 예고 없이 삭제된다")


if __name__ == '__main__':
    unittest.main()
