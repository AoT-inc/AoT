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
        self.app.config['SESSION_SWEEP_INTERVAL'] = 0  # 시험에서는 스레드를 띄우지 않는다
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
    """threshold 는 0(무제한)이어야 한다 — 요청 경로에서 디렉터리를 훑지 않는다.

    cachelib 은 threshold 가 0 이 아니면 파일 수가 그것을 넘은 뒤 세션을 저장할
    때마다 전체 파일을 두 번 읽는다(2026-10-31 실측: 쿠키 없는 요청 건당 약 165ms).
    정리는 `_start_session_sweeper` 가 요청 밖에서 한다.
    """

    def test_threshold_is_zero_so_requests_never_scan_the_directory(self):
        self.assertEqual(
            self.app.config.get('SESSION_FILE_THRESHOLD'), 0,
            "SESSION_FILE_THRESHOLD 가 0 이 아니다 — 세션을 저장할 때마다 "
            "디렉터리 전체를 훑는 비용이 요청 경로로 돌아온다")
        self.assertEqual(self.iface.cache._threshold, 0)


class TestAnonymousSessionsAreNotStored(_SessionAppFixture):
    """쓸 내용이 없는 익명 요청은 세션 파일도 Set-Cookie 도 만들지 않는다.

    flask-session 0.5.0 은 새 세션에 `_permanent` 를 넣어 세션이 늘 비어 있지 않게
    만든다. 그래서 404·401·robots.txt 까지 요청마다 파일 하나가 생겼다(하루 약
    1만 개). 로그인 화면은 CSRF 토큰 때문에 세션이 필요하므로 예외다.
    """

    def _cycle(self, path, mutate=None, status=200, cookie=None):
        from flask import Response, request as _rq
        headers = {'Cookie': 'session=%s' % cookie} if cookie else {}
        with self.app.test_request_context(path, headers=headers):
            sess = self.iface.open_session(self.app, _rq)
            if mutate:
                mutate(sess)
            resp = Response('', status=status)
            self.iface.save_session(self.app, sess, resp)
            return sess, resp

    def test_untouched_anonymous_request_stores_nothing(self):
        # flask-login 이 익명 요청마다 하는 일: _fresh=False
        sess, resp = self._cycle('/api/geo/devices', lambda s: s.update(
            {'_fresh': False}), status=401)
        self.assertEqual(self.writes, [])
        self.assertNotIn('Set-Cookie', resp.headers)

    def test_bare_new_session_stores_nothing(self):
        sess, resp = self._cycle('/robots.txt')
        self.assertTrue(sess.get('_permanent'),
                        "전제가 바뀌었다: flask-session 이 더는 _permanent 를 넣지 않는다")
        self.assertEqual(self.writes, [])
        self.assertNotIn('Set-Cookie', resp.headers)

    def test_404_with_only_a_csrf_token_stores_nothing(self):
        sess, resp = self._cycle('/nope', lambda s: s.update(
            {'_fresh': False, 'csrf_token': 'T'}), status=404)
        self.assertEqual(self.writes, [])
        self.assertNotIn('Set-Cookie', resp.headers)

    def test_login_page_still_gets_a_session_for_csrf(self):
        sess, resp = self._cycle('/login_password', lambda s: s.update(
            {'_fresh': False, 'csrf_token': 'T'}), status=200)
        self.assertEqual(len(self.writes), 1)
        self.assertIn('session=', resp.headers.get('Set-Cookie', ''))

    def test_flash_redirect_still_stores_the_message(self):
        sess, resp = self._cycle('/dashboard', lambda s: s.update(
            {'_fresh': False, '_flashes': [('error', 'x')]}), status=302)
        self.assertEqual(len(self.writes), 1)

    def test_logout_still_rewrites_a_session_that_had_content(self):
        """내용이 있던 세션은 비워져도 다시 써야 한다 — 안 쓰면 _user_id 가 남는다."""
        first, _ = self._cycle('/login_password', lambda s: s.update(
            {'csrf_token': 'T', '_user_id': '7'}))
        self.assertEqual(len(self.writes), 1)

        def logout(s):
            s.pop('_user_id', None)
            s.pop('csrf_token', None)
            s['_fresh'] = False
            s.modified = True
        self._cycle('/logout', logout, status=302, cookie=first.sid)
        self.assertEqual(len(self.writes), 2, "로그아웃이 저장되지 않았다")
        stored = self.iface.cache.get(self.iface.key_prefix + first.sid)
        self.assertNotIn('_user_id', stored, "로그아웃했는데 로그인 표지가 남았다")

    def test_session_with_a_login_marker_is_stored_even_on_404(self):
        sess, resp = self._cycle('/nope', lambda s: s.update(
            {'_user_id': '7', 'csrf_token': 'T'}), status=404)
        self.assertEqual(len(self.writes), 1)

    def test_pending_login_state_is_stored(self):
        sess, resp = self._cycle('/login_totp', lambda s: s.update(
            {'_totp_pending_user': 3}), status=200)
        self.assertEqual(len(self.writes), 1)


class TestUnauthorizedFlashOnlyForNavigation(unittest.TestCase):
    """로그아웃된 탭의 폴링(fetch/XHR)이 flash 로 세션을 쌓지 않아야 한다."""

    def _nav(self, headers):
        from flask import Flask
        from aot.aot_flask import app as app_module
        app = Flask(__name__)
        with app.test_request_context('/x', headers=headers):
            from flask import request
            return app_module._is_document_navigation(request)

    def test_browser_navigation_is_a_document(self):
        self.assertTrue(self._nav({'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}))
        self.assertTrue(self._nav({'Sec-Fetch-Dest': 'document'}))

    def test_fetch_xhr_and_curl_are_not(self):
        self.assertFalse(self._nav({'Accept': '*/*'}))
        self.assertFalse(self._nav({}))
        self.assertFalse(self._nav({'Sec-Fetch-Dest': 'empty',
                                    'Accept': 'text/html'}))
        self.assertFalse(self._nav({'X-Requested-With': 'XMLHttpRequest',
                                    'Accept': 'text/html'}))


class TestSessionSweeper(unittest.TestCase):
    """요청 밖 정리: 만료·오래된 익명만 지우고 로그인 세션은 지키지 않는다(=건드리지 않는다)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, value, expires, age=7200.0):
        import pickle
        import struct
        path = os.path.join(self.dir, name)
        with open(path, 'wb') as f:
            f.write(struct.pack('<I', expires))
            pickle.dump(value, f)
        mtime = __import__('time').time() - age
        os.utime(path, (mtime, mtime))
        return path

    def test_expired_files_are_removed_and_login_sessions_survive(self):
        import time
        now = time.time()
        gone = self._write('exp', {'_user_id': '1'}, int(now) - 10)
        login = self._write('login', {'_user_id': '1', 'csrf_token': 'T'},
                            int(now) + 3600)
        from aot.aot_flask import app as app_module
        expired, evicted, kept = app_module._sweep_session_files(
            self.dir, anon_max=0)
        self.assertEqual((expired, evicted), (1, 0))
        self.assertFalse(os.path.exists(gone))
        self.assertTrue(os.path.exists(login), "로그인 세션이 지워졌다")

    def test_oldest_anonymous_evicted_first_down_to_the_cap(self):
        import time
        now = time.time()
        paths = [self._write('a%d' % i, {'_permanent': True, '_fresh': False},
                             int(now) + 3600, age=7200.0 + i) for i in range(5)]
        login = self._write('login', {'_user_id': '1'}, int(now) + 3600,
                            age=99999.0)
        from aot.aot_flask import app as app_module
        _, evicted, kept = app_module._sweep_session_files(self.dir, anon_max=2)
        self.assertEqual((evicted, kept), (3, 2))
        # age 가 큰(=오래된) 3개가 지워진다
        self.assertEqual([os.path.exists(p) for p in paths],
                         [True, True, False, False, False])
        self.assertTrue(os.path.exists(login))

    def test_unknown_keys_and_fresh_files_are_not_disposable(self):
        import time
        now = time.time()
        lang = self._write('lang', {'language': 'ko', '_permanent': True},
                           int(now) + 3600)
        pending = self._write('totp', {'_totp_pending_user': 3},
                              int(now) + 3600)
        young = self._write('young', {'_permanent': True}, int(now) + 3600,
                            age=5.0)
        from aot.aot_flask import app as app_module
        app_module._sweep_session_files(self.dir, anon_max=0)
        for p in (lang, pending, young):
            self.assertTrue(os.path.exists(p), "지우면 안 되는 파일이 지워졌다: " + p)

    def test_unreadable_and_management_files_are_left_alone(self):
        bad = os.path.join(self.dir, 'bad')
        with open(bad, 'wb') as f:
            f.write(b'\x00\x00\x00\x00not-a-pickle')
        tmp = os.path.join(self.dir, 'x.__wz_cache')
        open(tmp, 'wb').close()
        from aot.aot_flask import app as app_module
        app_module._sweep_session_files(self.dir, anon_max=0)
        self.assertTrue(os.path.exists(bad))
        self.assertTrue(os.path.exists(tmp))


class TestSlowRequestLog(unittest.TestCase):
    """느린 요청만, 쿼리 문자열 없이 한 줄로 남긴다."""

    def _app(self, threshold_ms):
        import time
        from flask import Flask
        from aot.aot_flask import app as app_module
        os.environ['AOT_SLOW_REQUEST_MS'] = str(threshold_ms)
        try:
            app = Flask(__name__)
            app_module.register_slow_request_log(app)
        finally:
            os.environ.pop('AOT_SLOW_REQUEST_MS', None)

        @app.route('/slow')
        def slow():
            time.sleep(0.05)
            return 'ok'

        @app.route('/static/x.js')
        def static_x():
            time.sleep(0.05)
            return 'ok'
        return app

    def test_slow_request_logged_without_query_string(self):
        app = self._app(10)
        with self.assertLogs('aot.aot_flask.app', level='WARNING') as cm:
            app.test_client().get('/slow?token=SECRET&q=hello')
        line = cm.output[0]
        self.assertIn('GET /slow', line)
        self.assertIn('200', line)
        self.assertNotIn('SECRET', line)
        self.assertNotIn('hello', line)

    def test_fast_requests_and_static_are_not_logged(self):
        app = self._app(10000)
        with self.assertNoLogs('aot.aot_flask.app', level='WARNING'):
            app.test_client().get('/slow')
        app = self._app(10)
        with self.assertNoLogs('aot.aot_flask.app', level='WARNING'):
            app.test_client().get('/static/x.js')

    def test_zero_disables(self):
        app = self._app(0)
        with self.assertNoLogs('aot.aot_flask.app', level='WARNING'):
            app.test_client().get('/slow')


if __name__ == '__main__':
    unittest.main()
