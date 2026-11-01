# coding=utf-8
"""공지 링크 미리보기 SSRF 재현·회귀 테스트 (2026-10-20).

`/notice/api/link_preview` 는 서버가 외부 URL 을 가져온다. 이 파일은 구현 방식과 무관하게
"내부 주소로는 연결하지 않는다 · 오류 문구가 차단 사유를 드러내지 않는다 · 시간이 끝난다"를
외부 인터넷 없이 확인한다. 가짜 호스트는 socket.getaddrinfo 를 바꿔 푼다(모의 리졸버).
공인 서버 흉내는 로컬 서버 + socket.connect 우회(공인 가짜 IP → 로컬 서버)로 만든다.
"""
import http.server
import os
import socket
import threading
import time
import unittest
from unittest import mock

import aot.aot_flask.routes_notice as rn

_PUBLIC = '93.184.216.34'          # 검증 통과용 가짜 공인 IP (실제로 연결되지 않게 connect 를 가로챈다)
_REAL_CONNECT = socket.socket.connect
_REAL_GETADDRINFO = socket.getaddrinfo


class _Counting(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler):
        super().__init__(('127.0.0.1', 0), handler)
        self.hits = []              # (method, path)
        self.connections = 0

    def get_request(self):
        req = super().get_request()
        self.connections += 1
        return req


def _serve(handler):
    server = _Counting(handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class _Base(unittest.TestCase):

    def setUp(self):
        rn._fetch_link_preview.cache_clear()
        self.resolutions = {}       # host → [주소 목록, ...] 호출마다 하나씩 소비(마지막은 유지)
        self.resolve_calls = []
        self.connects = []          # connect 시도한 (ip, port)
        self.reroute = {}           # (공인 가짜 IP, 포트) → 로컬 서버 포트
        self._servers = []
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        for key in list(os.environ):
            if key.lower() in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
                del os.environ[key]
        self._pa = mock.patch.object(socket, 'getaddrinfo', side_effect=self._getaddrinfo)
        test = self
        self._pc = mock.patch.object(socket.socket, 'connect',
                                     new=lambda sock, address: test._connect(sock, address))
        self._pa.start()
        self._pc.start()

    def tearDown(self):
        self._pa.stop()
        self._pc.stop()
        self._env.stop()
        for server in self._servers:
            server.shutdown()
            server.server_close()
        rn._fetch_link_preview.cache_clear()

    def serve(self, handler):
        server = _serve(handler)
        self._servers.append(server)
        return server

    def _getaddrinfo(self, host, port, *args, **kwargs):
        self.resolve_calls.append(host)
        seq = self.resolutions.get(host)
        if seq is None:
            return _REAL_GETADDRINFO(host, port, *args, **kwargs)
        addrs = seq.pop(0) if len(seq) > 1 else seq[0]
        out = []
        for addr in addrs:
            fam = socket.AF_INET6 if ':' in addr else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, 6, '', (addr, port or 0)))
        return out

    def _connect(self, sock, address):
        host, port = address[0], address[1]
        self.connects.append((host, port))
        target = self.reroute.get((host, port))
        if target is not None:
            return _REAL_CONNECT(sock, ('127.0.0.1', target))
        if host == '127.0.0.1' and port in {s.server_port for s in self._servers}:
            return _REAL_CONNECT(sock, address)     # 내부 서버가 실제로 맞았는지 보려고 통과시킨다
        raise ConnectionRefusedError('blocked by test')

    def connected_to(self, *ips):
        return [c for c in self.connects if c[0] in ips]

    def preview(self, url):
        return rn._fetch_link_preview(url)


class IpJudgement(_Base):
    """공인이 아닌 주소로 풀리는 호스트는 연결 시도 자체가 없어야 한다."""

    CASES = {
        'cgnat': '100.64.0.1',
        'cgnat_edge': '100.127.255.254',
        'sixtofour_loopback': '2002:7f00:1::',
        'sixtofour_metadata': '2002:a9fe:a9fe::1',
        'mapped_loopback': '::ffff:127.0.0.1',
        'mapped_metadata': '::ffff:169.254.169.254',
        'nat64_loopback': '64:ff9b::7f00:1',
        'teredo': '2001::1',
        'benchmark': '198.18.0.1',
        'metadata': '169.254.169.254',
        'loopback': '127.0.0.1',
        'private': '10.0.0.5',
    }

    def test_no_connection_to_non_public_addresses(self):
        for name, addr in self.CASES.items():
            with self.subTest(name):
                self.connects.clear()
                rn._fetch_link_preview.cache_clear()
                self.resolutions['x-%s.test' % name] = [[addr]]
                out = self.preview('https://x-%s.test/' % name)
                self.assertIn('error', out)
                self.assertEqual(self.connected_to(addr), [])

    def test_mixed_records_are_rejected(self):
        self.resolutions['mix.test'] = [[_PUBLIC, '10.0.0.5']]
        out = self.preview('https://mix.test/')
        self.assertIn('error', out)
        self.assertEqual(self.connects, [])


class Rebinding(_Base):

    def test_connection_goes_to_the_validated_address_only(self):
        """검증 때는 공인, 연결 때 다시 풀면 127.0.0.1 — 다시 풀지 않아야 한다."""
        internal = self.serve(http.server.BaseHTTPRequestHandler)
        self.resolutions['rebind.test'] = [[_PUBLIC], ['127.0.0.1']]
        self.preview('http://rebind.test:%d/' % internal.server_port)
        self.preview('https://rebind.test/')
        self.assertEqual(self.connected_to('127.0.0.1'), [])
        self.assertEqual(internal.connections, 0)


class Redirects(_Base):

    def test_get_redirect_to_internal_is_not_followed(self):
        """HEAD 는 200 으로 속이고 GET 은 내부로 보내는 서버 — 사전 HEAD 만으로는 못 막는다."""
        internal_hits = []

        class Internal(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                internal_hits.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<title>INTERNAL SECRET</title>')

            def log_message(self, *a):
                pass

        internal = self.serve(Internal)

        class Public(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(200)
                self.end_headers()

            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1:%d/secret' % internal.server_port)
                self.end_headers()

            def log_message(self, *a):
                pass

        public = self.serve(Public)
        self.resolutions['pub.test'] = [[_PUBLIC]]
        self.reroute[(_PUBLIC, 80)] = public.server_port
        self.reroute[(_PUBLIC, 443)] = public.server_port
        out = self.preview('http://pub.test/')
        self.assertEqual(internal_hits, [])
        self.assertNotIn('INTERNAL', str(out))

    def test_redirect_to_host_resolving_internal_is_not_followed(self):
        internal = self.serve(http.server.BaseHTTPRequestHandler)

        class Public(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', 'http://inner.test:%d/' % internal.server_port)
                self.end_headers()

            def log_message(self, *a):
                pass

        public = self.serve(Public)
        self.resolutions['pub.test'] = [[_PUBLIC]]
        self.resolutions['inner.test'] = [['127.0.0.1']]
        self.reroute[(_PUBLIC, 80)] = public.server_port
        self.reroute[(_PUBLIC, 443)] = public.server_port
        self.preview('http://pub.test/')
        self.assertEqual(internal.connections, 0)


class Proxy(_Base):

    def test_proxy_environment_is_ignored(self):
        proxy_hits = []

        class FakeProxy(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                proxy_hits.append(self.path)
                self.send_response(200)
                self.end_headers()

            do_HEAD = do_GET

            def log_message(self, *a):
                pass

        proxy = self.serve(FakeProxy)
        os.environ['HTTP_PROXY'] = os.environ['http_proxy'] = 'http://127.0.0.1:%d' % proxy.server_port
        os.environ['HTTPS_PROXY'] = os.environ['https_proxy'] = 'http://127.0.0.1:%d' % proxy.server_port
        os.environ['ALL_PROXY'] = os.environ['all_proxy'] = 'http://127.0.0.1:%d' % proxy.server_port
        self.resolutions['pub.test'] = [[_PUBLIC]]
        self.preview('http://pub.test/')
        self.preview('https://pub.test/')
        self.assertEqual(proxy_hits, [])
        self.assertEqual(proxy.connections, 0)


class Limits(_Base):

    def test_size_bomb_is_bounded(self):
        sent = []

        class Bomb(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(200)
                self.end_headers()

            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                chunk = b'<!-- ' + b'x' * 65000 + b' -->'
                try:
                    for _ in range(400):                   # 약 26 MB
                        self.wfile.write(chunk)
                        sent.append(len(chunk))
                except OSError:
                    pass

            def log_message(self, *a):
                pass

        bomb = self.serve(Bomb)
        self.resolutions['big.test'] = [[_PUBLIC]]
        self.reroute[(_PUBLIC, 80)] = bomb.server_port
        self.reroute[(_PUBLIC, 443)] = bomb.server_port
        started = time.monotonic()
        self.preview('http://big.test/')
        self.preview('https://big.test/')
        self.assertLess(time.monotonic() - started, 5)
        # 소켓 버퍼 몫을 감안해도 수 MB 를 다 밀어 넣을 수는 없어야 한다.
        self.assertLess(sum(sent), 8 * 1024 * 1024)

    def test_slow_drip_ends_by_total_deadline(self):
        class Drip(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(200)
                self.end_headers()

            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                try:
                    for _ in range(40):                    # 0.25초마다 1바이트 → 10초
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(0.25)
                except OSError:
                    pass

            def log_message(self, *a):
                pass

        drip = self.serve(Drip)
        self.resolutions['slow.test'] = [[_PUBLIC]]
        self.reroute[(_PUBLIC, 80)] = drip.server_port
        self.reroute[(_PUBLIC, 443)] = drip.server_port
        patches = [mock.patch.object(rn, 'LINK_PREVIEW_TOTAL_SECONDS', 1)]
        started = time.monotonic()
        for patch in patches:
            patch.start()
        try:
            self.preview('https://slow.test/')
        finally:
            for patch in patches:
                patch.stop()
        self.assertLess(time.monotonic() - started, 5)       # 한 번에 1초 안팎 × 2


class Oracle(_Base):

    def test_blocked_and_unreachable_look_the_same(self):
        self.resolutions['inner.test'] = [['10.0.0.5']]
        self.resolutions['pub.test'] = [[_PUBLIC]]
        blocked = self.preview('https://inner.test/')
        unreachable = self.preview('https://pub.test/')          # 연결은 test 가 거절한다
        self.assertEqual(blocked, unreachable)
        self.assertEqual(blocked, {'error': 'Preview unavailable'})
        text = str(blocked).lower()
        for word in ('unsafe', 'private', 'internal', 'blocked', 'refused', '10.0.0.5'):
            self.assertNotIn(word, text)

    def test_route_answers_blocked_and_unreachable_identically(self):
        from flask import Flask
        app = Flask('t')
        self.resolutions['inner.test'] = [['10.0.0.5']]
        self.resolutions['pub.test'] = [[_PUBLIC]]
        raw = rn.api_notice_link_preview.__wrapped__
        answers = []
        for url in ('https://inner.test/', 'https://pub.test/', 'ftp://pub.test/', 'file:///etc/passwd'):
            with app.test_request_context('/notice/api/link_preview', query_string={'url': url}):
                resp = raw()
                resp, status = (resp if isinstance(resp, tuple) else (resp, 200))
                answers.append((status, resp.get_json()))
        self.assertEqual(len({repr(a) for a in answers}), 1, answers)


if __name__ == '__main__':
    unittest.main()
