"""AI 카드 P4 백엔드 — URL 가져오기(SSRF 방어)·마크다운 이미지 승격 (2026-10-20).

계약: plans/p4_contract_20261020.md ②③④⑤ 와 ⑩ 의 B1~B9.
**외부 인터넷에 의존하지 않는다.** 로컬 https 서버(자체 CA 로 서명한 인증서)와 모의 리졸버를 쓰고,
"공인 IP" 는 문서용이 아닌 임의의 공인 주소(93.184.216.34 등)를 리졸버가 돌려주는 값일 뿐이다 —
실제 연결은 urllib3 의 create_connection 을 가로채 로컬 서버로 돌린다(이때 **urllib3 가 연결하려던
주소**가 검증한 IP 인지 스파이로 확인한다).

SSRF 매트릭스 7묶음(⑩): 모양·리졸버·리바인딩·리다이렉트·응답·요청·TLS — 클래스 이름이 묶음이다.
"""
import datetime
import inspect
import json
import os
import socket
import ssl
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer, ThreadingMixIn
from unittest import mock

import urllib3.util.connection as urllib3_connection

from aot.tests.test_ai_card_files import _FilesBase, _img, _B64, _PDF
from aot.utils import ai_card_fetch as X
from aot.utils import ai_card_files as F

PUB = '93.184.216.34'               # 리졸버가 돌려주는 "공인" 주소(연결은 로컬 서버로 돌린다)
PUB2 = '151.101.1.69'
PUB6 = '2606:4700:4700::1111'
HOST = 'files.example.com'
OTHER = 'cdn.example.org'
INTERNAL = 'internal.example.net'    # 리졸버가 사설 주소로 풀어 주는 이름
OK_URL = 'https://%s/ok.txt' % HOST
_REAL_PER_HOUR = X.PER_HOUR
_REAL_SSL_CONTEXT = X._ssl_context           # 테스트가 모의로 덮기 전의 원본


# ── 테스트용 인증서(cryptography) ───────────────────────────────────────────

def _key():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1())


def _name(cn):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _make_ca(cn='AoT test CA'):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    key = _key()
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(_name(cn))
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    return key, cert


def _make_leaf(ca_key, ca_cert, dns_names, expired=False):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    key = _key()
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=(30 if expired else 1))
    end = now - datetime.timedelta(days=(10 if expired else -2))
    cert = (x509.CertificateBuilder().subject_name(_name(dns_names[0]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(start).not_valid_after(end)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in dns_names]),
                           critical=False)
            .sign(ca_key, hashes.SHA256()))
    return key, cert


def _pem(path, key=None, cert=None):
    from cryptography.hazmat.primitives import serialization
    with open(path, 'wb') as fh:
        if key is not None:
            fh.write(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
        if cert is not None:
            fh.write(cert.public_bytes(serialization.Encoding.PEM))


_PKI = {}


def setUpModule():
    tmp = tempfile.mkdtemp(prefix='aicard-pki-')
    _PKI['dir'] = tmp
    ca_key, ca_cert = _make_ca()
    other_key, other_cert = _make_ca('Untrusted CA')
    _pem(os.path.join(tmp, 'ca.pem'), cert=ca_cert)
    _pem(os.path.join(tmp, 'other_ca.pem'), cert=other_cert)
    leaves = {
        'good': (ca_key, ca_cert, [HOST, OTHER, INTERNAL, 'a.example.com', 'b.example.com',
                                   'img.youtube.com', 'i.ytimg.com', 'vimeo.com',
                                   'i.vimeocdn.com', 'cdn.example.com'], False),
        'wrongname': (ca_key, ca_cert, ['not-%s' % HOST], False),
        'untrusted': (other_key, other_cert, [HOST], False),
        'expired': (ca_key, ca_cert, [HOST], True),
    }
    for name, (k, c, names, expired) in leaves.items():
        lk, lc = _make_leaf(k, c, names, expired)
        _pem(os.path.join(tmp, name + '.key'), key=lk)
        _pem(os.path.join(tmp, name + '.crt'), cert=lc)


def tearDownModule():
    import shutil
    shutil.rmtree(_PKI.get('dir', ''), ignore_errors=True)


# ── 로컬 https 서버 ─────────────────────────────────────────────────────────

class _Server(ThreadingMixIn, TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):      # TLS 거부 등은 소음
        pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):                                     # noqa: N802
        srv = self.server
        srv.requests.append({'path': self.path, 'headers': [(k, v) for k, v in self.headers.items()],
                             'raw': dict(self.headers)})
        route = srv.routes.get(self.path.split('?', 1)[0])
        try:
            if route is None:
                respond(self, 404, b'nope')
            else:
                route(self)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, OSError):
            pass
        self.close_connection = True


def respond(h, status=200, body=b'', headers=None, length=True, chunked=False):
    h.send_response(status)
    for k, v in (headers or {}).items():
        h.send_header(k, v)
    if chunked:
        h.send_header('Transfer-Encoding', 'chunked')
        h.end_headers()
        for i in range(0, len(body), 32768):
            part = body[i:i + 32768]
            h.wfile.write(b'%x\r\n' % len(part) + part + b'\r\n')
        h.wfile.write(b'0\r\n\r\n')
    else:
        if length:
            h.send_header('Content-Length', str(len(body)))
        h.end_headers()
        h.wfile.write(body)


def redirect(location, status=302, **headers):
    def route(h):
        respond(h, status, b'', dict({'Location': location}, **headers))
    return route


def start_server(cert_name, sni_log=None, max_version=None):
    srv = _Server(('127.0.0.1', 0), _Handler)
    srv.routes, srv.requests = {}, []
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(os.path.join(_PKI['dir'], cert_name + '.crt'),
                        os.path.join(_PKI['dir'], cert_name + '.key'))
    if max_version is not None:
        ctx.maximum_version = max_version
        ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
    if sni_log is not None:
        def sni(_sock, name, _ctx):
            sni_log.append(name)
        ctx.sni_callback = sni
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    srv.thread = thread
    srv.port = srv.server_address[1]
    return srv


def stop_server(srv):
    srv.shutdown()
    srv.server_close()


# ── 공통 바탕 ───────────────────────────────────────────────────────────────

class _NetBase(_FilesBase):
    """로컬 https 서버 3대(good·wrongname·untrusted)와 모의 리졸버·연결 스파이."""

    real_limits = False                  # True 면 시간 30·일 100 한도를 그대로 둔다(LimitAuditTest)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sni = []
        cls.good = start_server('good', sni_log=cls.sni)
        cls.wrong = start_server('wrongname')
        cls.untrusted = start_server('untrusted')
        cls.expired = start_server('expired')

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.good, cls.wrong, cls.untrusted, cls.expired):
            stop_server(srv)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.good.routes.clear()
        self.good.requests.clear()
        self.sni.clear()
        self.dns = {HOST: [PUB], OTHER: [PUB2], INTERNAL: ['10.0.0.5'],
                    'a.example.com': [PUB], 'b.example.com': [PUB],
                    'img.youtube.com': [PUB], 'i.ytimg.com': [PUB], 'vimeo.com': [PUB2],
                    'i.vimeocdn.com': [PUB2], 'cdn.example.com': [PUB]}
        self.resolved = []
        self.connects = []
        self.ip_port = {}                  # ip → 로컬 서버(기본 good)
        self.bytes_read = 0
        ctx = ssl.create_default_context(cafile=os.path.join(_PKI['dir'], 'ca.pem'))
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        self.client_ctx = ctx
        real = urllib3_connection.create_connection

        def spy(address, *a, **k):
            self.connects.append(tuple(address))
            ip = address[0]
            if ip in self.refuse:
                raise OSError('refused (test)')
            return real(('127.0.0.1', self.ip_port.get(ip, self.good.port)), *a, **k)
        self.refuse = set()
        self._patches2 = [] if self.real_limits else [
            mock.patch.object(X, 'PER_HOUR', 10 ** 6), mock.patch.object(X, 'PER_DAY', 10 ** 6)]
        self._patches2 += [
            mock.patch.object(urllib3_connection, 'create_connection', spy),
            mock.patch.object(X, '_ssl_context', lambda: self.client_ctx),
            mock.patch.object(X, '_system_resolve', self._resolver),
            mock.patch.object(X, '_slots', threading.BoundedSemaphore(X.FETCH_SLOTS)),
            mock.patch.object(X, '_busy_users', set()),
        ]
        for p in self._patches2:
            p.start()

    def tearDown(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import AuditLog
        for p in self._patches2:
            p.stop()
        db.session.rollback()
        AuditLog.query.filter(AuditLog.action == 'ai_card.fetch').delete(
            synchronize_session=False)
        db.session.commit()
        super().tearDown()

    # ── 도우미 ──────────────────────────────────────────────────────────────
    def _resolver(self, host):
        self.resolved.append(host)
        value = self.dns[host]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value()
        return list(value)

    def route(self, path, body=b'', status=200, headers=None, **kw):
        self.good.routes[path] = lambda h: respond(h, status, body, headers, **kw)

    def counting_factory(self, *args):
        pool = X._make_pool(*args)
        orig = pool.urlopen

        def urlopen(*a, **k):
            resp = orig(*a, **k)
            read = resp.read

            def counted(*ra, **rk):
                data = read(*ra, **rk)
                self.bytes_read += len(data)
                return data
            resp.read = counted
            return resp
        pool.urlopen = urlopen
        return pool

    def fetch(self, url, cap=F.MAX_FILE_BYTES, user=None, factory=None):
        return X.fetch(url, user or self.user, cap, _resolver=self._resolver,
                       _pool_factory=factory)

    def assertFailed(self, url, code, msg=X.MSG_FAILED, **kw):
        """FetchError 이고 문구는 msg, 감사 code 는 code."""
        with self.assertRaises(X.FetchError) as cm:
            self.fetch(url, **kw)
        self.assertEqual(str(cm.exception), msg, url)
        self.assertEqual(cm.exception.code, code, (url, str(cm.exception)))
        return cm.exception

    def audit_rows(self):
        from aot.databases.models import AuditLog
        return AuditLog.query.filter(AuditLog.action == 'ai_card.fetch',
                                     AuditLog.user_id == self.pk).order_by(AuditLog.id).all()


# ═════════════════════════════════════════════════════════════════════════════
# 묶음 1 — 모양 (DNS 호출 0)
# ═════════════════════════════════════════════════════════════════════════════

SHAPE_BAD = [
    'http://files.example.com/a.png', 'HTTP://files.example.com/a.png',
    'https://files.example.com:8443/a.png', 'https://files.example.com:80/a.png',
    'https://files.example.com:/a.png', 'https://files.example.com:0443/a.png',
    'https://user:pw@files.example.com/a.png', 'https://user@files.example.com/a.png',
    'https://a.com@b.com/a.png', 'https://a.com:443@b.com/a.png',
    'https://a.com\\@b.com/a.png', 'https://a.com\\.b.com/a.png',
    'https://files.example.com/a b.png', 'https://files.example.com/a\r\nHost: evil/',
    'https://files.example.com/\ta', 'https://files.example.com/a\nb', ' https://files.example.com/a',
    'https://files.example.com/a ', 'https://files.example.com/a\x00', 'https://files.example.com/\x7f',
    'https:///x', 'https:x', 'https:/files.example.com/x', 'https://', 'https:', 'https://?x',
    'https://[::1]/', 'https://[::ffff:127.0.0.1]/', 'https://[2606:4700:4700::1111]/',
    'https://127.0.0.1/', 'https://8.8.8.8/', 'https://2130706433/', 'https://0x7f000001/',
    'https://0x7f.0x0.0x0.0x1/', 'https://0177.0.0.1/', 'https://0177.0000.0000.0001/',
    'https://127.1/', 'https://127.0.1/', 'https://0/', 'https://0.0.0.0/', 'https://169.254.169.254/',
    'https://100.64.0.1/', 'https://017700000001/', 'https://1.1/',
    'https://ｅxample.com/', 'https://例え.jp/', 'https://café.example.com/',
    'https://files.example.com/é.png', 'https://files.example.com/．', 'https://①.example.com/',
    'https://localhost/', 'https://a.localhost/', 'https://x.internal/', 'https://x.local/',
    'https://x.lan/', 'https://x.home.arpa/', 'https://x.localdomain/', 'https://x.intranet/',
    'https://1.0.0.127.in-addr.arpa/', 'https://files.example.com./a.png', 'https://example/',
    'https://-a.example.com/', 'https://a-.example.com/', 'https://a..example.com/',
    'https://.example.com/', 'https://a_b.example.com/', 'https://exa%6dple.com/',
    'https://%31%32%37.0.0.1/', 'https://' + 'a' * 64 + '.example.com/',
    'https://files.example.com/' + 'a' * 2030, 'ftp://files.example.com/a', 'file:///etc/passwd',
    'javascript:alert(1)', '//files.example.com/a', 'files.example.com/a', '', '   ',
    'https://files.example.com\\', 'https://files.example.com/a\\b',
    'https://x.' + 'a' * 250 + '.com/',
]


class ShapeTest(_NetBase):
    """묶음 1 — 모양 문구, DNS 호출 0, 연결 0, 감사 code bad_url."""

    def test_every_bad_shape_is_refused_with_the_shape_message_without_dns(self):
        self.assertGreater(len(SHAPE_BAD), 70)
        for url in SHAPE_BAD:
            with self.assertRaises(X.FetchError, msg=repr(url)) as cm:
                X.check_url(url)
            self.assertEqual(str(cm.exception), X.MSG_SHAPE, repr(url))
            self.assertEqual(cm.exception.code, 'bad_url')
        for bad in (None, 5, ['https://a.com/x'], {'u': 1}, b'https://a.com/', True):
            with self.assertRaises(X.FetchError):
                X.check_url(bad)

    def test_2049_char_url_is_refused_and_2048_is_the_edge(self):
        base = 'https://files.example.com/'
        X.check_url(base + 'a' * (2048 - len(base)))
        with self.assertRaises(X.FetchError):
            X.check_url(base + 'a' * (2049 - len(base)))

    def test_fetch_never_resolves_or_connects_for_a_bad_shape(self):
        for url in SHAPE_BAD[::3] + ['http://files.example.com/a', 'https://127.0.0.1/']:
            self.assertFailed(url, 'bad_url', X.MSG_SHAPE)
        self.assertEqual((self.resolved, self.connects), ([], []))
        rows = self.audit_rows()
        self.assertEqual({r.detail.split()[0] for r in rows}, {'bad_url'})
        self.assertEqual({r.result for r in rows}, {'failure'})

    def test_good_shapes_are_normalised(self):
        t = X.check_url('HTTPS://Files.Example.COM:443/a/b.png?x=1&y=2#frag')
        self.assertEqual((t.host, t.target, t.url),
                         ('files.example.com', '/a/b.png?x=1&y=2',
                          'https://files.example.com/a/b.png?x=1&y=2'))
        self.assertEqual(X.check_url('https://files.example.com').target, '/')
        self.assertEqual(X.check_url('https://files.example.com?x=1').target, '/?x=1')
        self.assertEqual(X.check_url('https://xn--e1afmkfd.xn--p1ai/x').host, 'xn--e1afmkfd.xn--p1ai')
        # 퍼센트 인코딩은 경로에서만 쓰이고 그대로 간다(풀어 합치지 않는다)
        self.assertEqual(X.check_url('https://files.example.com/a%2e%2e/b%20c').target,
                         '/a%2e%2e/b%20c')

    def test_name_from_url_decodes_utf8_and_gives_up_on_garbage(self):
        self.assertEqual(X.name_from_url('https://a.com/x/%ED%95%9C%EA%B8%80.png?z=1'), '한글.png')
        self.assertIsNone(X.name_from_url('https://a.com/x/%ff%fe.png'))
        self.assertIsNone(X.name_from_url('https://a.com/'))
        self.assertIsNone(X.name_from_url('https://a.com'))
        self.assertEqual(X.name_from_url('https://a.com/a/b/c.csv'), 'c.csv')
        self.assertIsNone(X.name_from_url(None))

    def test_sniff_ext(self):
        self.assertEqual(X.sniff_ext(_img('PNG')), 'png')
        self.assertEqual(X.sniff_ext(_img('JPEG')), 'jpg')
        self.assertEqual(X.sniff_ext(_img('GIF')), 'gif')
        self.assertEqual(X.sniff_ext(_img('WEBP')), 'webp')
        self.assertEqual(X.sniff_ext(_PDF), 'pdf')
        for blob in (b'a,b\n1,2', b'<html>', b'', b'RIFF....AVI '):
            self.assertIsNone(X.sniff_ext(blob))


# ═════════════════════════════════════════════════════════════════════════════
# 묶음 2 — 리졸버 (IP 판정)
# ═════════════════════════════════════════════════════════════════════════════

BLOCKED_IPS = [
    '10.0.0.1', '172.16.0.1', '192.168.1.1', '127.0.0.1', '169.254.169.254', '100.64.0.1',
    '0.0.0.0', '198.18.0.1', '192.0.0.8', '224.0.0.1', '240.0.0.1', '255.255.255.255',
    '::1', 'fe80::1', 'fc00::1', 'fd00:ec2::254', '::ffff:10.0.0.1', '::ffff:169.254.169.254',
    '64:ff9b::a9fe:a9fe', '2002:a9fe:a9fe::1', '2001::1', 'ff02::1',
    # 경계와 변형
    '0.1.2.3', '10.255.255.255', '100.127.255.255', '127.255.255.255', '169.254.0.1',
    '172.31.255.255', '192.0.2.1', '192.88.99.1', '192.168.255.255', '198.19.255.255',
    '198.51.100.7', '203.0.113.9', '239.255.255.250', '250.0.0.1', '::', '::ffff:127.0.0.1',
    '::ffff:7f00:1', '::ffff:0:0', '::127.0.0.1', '::a9fe:a9fe', '64:ff9b:1::1', '100::1',
    'fec0::1', 'fe80::1%eth0', 'fe80::1%2', 'ff00::1', '2001:db8::1', '2001:2::1', '2001:1::1',
    '2002:7f00:1::1', '2002:0a00:0001::1', '2002:c0a8:0101::1', '2002:6440:0001::1', '3fff::1',
    '1::1', '4000::1', '8000::1',
]
PUBLIC_IPS = ['8.8.8.8', '1.1.1.1', '93.184.216.34', '151.101.1.69', '100.63.255.255',
              '100.128.0.1', '172.15.255.255', '172.32.0.1', '169.253.255.255', '198.17.255.255',
              '198.20.0.1', '223.255.255.254', '11.0.0.1', '126.255.255.255', '128.0.0.1',
              '2606:4700:4700::1111', '2a00:1450:4009:81f::200e', '2001:4860:4860::8888',
              '::ffff:8.8.8.8', '2002:0808:0808::1']


class IpJudgementTest(unittest.TestCase):

    def test_blocked_addresses(self):
        for ip in BLOCKED_IPS:
            self.assertFalse(X.is_public_ip(ip), ip)
        # 객체를 넘겨도 같다
        import ipaddress
        for ip in BLOCKED_IPS:
            if '%' not in ip:
                self.assertFalse(X.is_public_ip(ipaddress.ip_address(ip)), ip)

    def test_public_addresses(self):
        for ip in PUBLIC_IPS:
            self.assertTrue(X.is_public_ip(ip), ip)

    def test_garbage_is_not_public(self):
        for bad in ('', 'abc', None, 5, '1.2.3', '1.2.3.4.5', '256.1.1.1', '8.8.8.8/32',
                    '[::1]', 'http://8.8.8.8', '0x7f000001', '2130706433', b'\x08\x08\x08\x08'):
            self.assertFalse(X.is_public_ip(bad), repr(bad))

    def test_3_10_is_global_gap_is_closed_by_the_explicit_lists(self):
        """파이썬 3.10 의 is_global 은 100.64/10 를 아는 정도다 — 매핑·6to4·NAT64 는 우리가 푼다."""
        import ipaddress
        for ip in ('::ffff:10.0.0.1', '::ffff:100.64.0.1', '64:ff9b::808:808', '2002:a00:1::'):
            self.assertFalse(X.is_public_ip(ip), ip)
        self.assertTrue(ipaddress.ip_address('8.8.8.8').is_global)


class ResolverTest(_NetBase):
    """묶음 2 — 해석된 **모든** 주소가 공인이어야 한다. 사유는 구분하지 않는다(같은 문자열)."""

    def test_every_blocked_address_gives_the_same_generic_message_and_no_connection(self):
        messages = set()
        for ip in BLOCKED_IPS:
            if '%' in ip:
                continue
            self.dns[HOST] = [ip]
            err = self.assertFailed(OK_URL, 'blocked')
            messages.add(str(err))
        self.assertEqual(messages, {X.MSG_FAILED})
        self.assertEqual(self.connects, [])
        self.assertEqual(self.good.requests, [])

    def test_mixed_records_are_refused_whole_in_either_order(self):
        for records in ([PUB, '10.0.0.1'], ['10.0.0.1', PUB], [PUB, PUB2, '127.0.0.1'],
                        [PUB, '::1'], [PUB6, '169.254.169.254'], [PUB, 'fe80::1%eth0']):
            self.dns[HOST] = records
            self.assertFailed(OK_URL, 'blocked')
        self.assertEqual(self.connects, [])

    def test_unparseable_answer_is_blocked(self):
        for records in (['not-an-ip'], [''], [PUB, 'x']):
            self.dns[HOST] = records
            self.assertFailed(OK_URL, 'blocked')

    def test_nxdomain_and_resolver_errors_are_the_same_message(self):
        for exc in (socket.gaierror(-2, 'Name or service not known'), OSError('boom'),
                    RuntimeError('x'), ValueError('y')):
            self.dns[HOST] = exc
            self.assertFailed(OK_URL, 'dns')
        self.dns[HOST] = []
        self.assertFailed(OK_URL, 'dns')
        self.assertEqual(self.connects, [])

    def test_slow_dns_times_out_without_blocking_the_caller(self):
        release = threading.Event()
        self.dns[HOST] = lambda: (release.wait(5), [PUB])[1]
        started = time.monotonic()
        try:
            with mock.patch.object(X, 'DNS_S', 0.2):
                self.assertFailed(OK_URL, 'timeout')
        finally:
            release.set()
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(self.connects, [])

    def test_all_failure_messages_are_one_string(self):
        """차단·DNS·연결·TLS·상태·리다이렉트·인코딩·시간 초과 — AI 가 보는 문구는 하나다."""
        seen = set()
        self.dns[HOST] = ['10.0.0.1']
        seen.add(str(self.assertFailed(OK_URL, 'blocked')))
        self.dns[HOST] = socket.gaierror('x')
        seen.add(str(self.assertFailed(OK_URL, 'dns')))
        self.dns[HOST] = [PUB]
        self.route('/ok.txt', b'x', status=404)
        seen.add(str(self.assertFailed(OK_URL, 'status')))
        self.route('/ok.txt', b'x', headers={'Content-Encoding': 'gzip'})
        seen.add(str(self.assertFailed(OK_URL, 'encoding')))
        self.good.routes['/ok.txt'] = redirect('http://%s/' % HOST)
        seen.add(str(self.assertFailed(OK_URL, 'redirect')))
        self.refuse.add(PUB)
        seen.add(str(self.assertFailed(OK_URL, 'connect')))
        self.assertEqual(seen, {X.MSG_FAILED})

    def test_dns_answer_is_ordered_ipv4_first_and_capped_at_two(self):
        deadline = time.monotonic() + 5
        got = X.resolve_public(HOST, deadline, _resolver=lambda h: [PUB6, PUB, PUB2, PUB])
        self.assertEqual(got, [PUB, PUB2])
        got = X.resolve_public(HOST, deadline, _resolver=lambda h: [PUB6, '2606:4700:4700::1001'])
        self.assertEqual(got, [PUB6, '2606:4700:4700::1001'])

    def test_second_address_is_tried_only_when_the_first_cannot_connect(self):
        self.dns[HOST] = [PUB, PUB2, '151.101.1.70']
        self.route('/ok.txt', b'hello')
        self.refuse.add(PUB)
        got = self.fetch(OK_URL)
        self.assertEqual(got.data, b'hello')
        self.assertEqual([c[0] for c in self.connects], [PUB, PUB2])
        self.connects.clear()
        self.refuse.update({PUB, PUB2})
        self.assertFailed(OK_URL, 'connect')
        self.assertEqual([c[0] for c in self.connects], [PUB, PUB2])      # 세 번째는 시도하지 않는다

    def test_ipv6_only_host_connects_to_the_validated_v6_address(self):
        self.dns[HOST] = [PUB6]
        self.route('/ok.txt', b'v6')
        self.assertEqual(self.fetch(OK_URL).data, b'v6')
        self.assertEqual(self.connects, [(PUB6, 443)])


# ═════════════════════════════════════════════════════════════════════════════
# 묶음 3 — 리바인딩 (IP 고정 연결)
# ═════════════════════════════════════════════════════════════════════════════

class RebindingTest(_NetBase):

    def test_connection_goes_to_the_first_validated_ip_and_host_is_resolved_once(self):
        answers = iter([[PUB], ['127.0.0.1'], ['127.0.0.1']])
        self.dns[HOST] = lambda: next(answers)
        self.route('/ok.txt', b'pinned')
        pools = []

        def factory(*args):
            pools.append(args[:2])
            return X._make_pool(*args)
        got = self.fetch(OK_URL, factory=factory)
        self.assertEqual(got.data, b'pinned')
        self.assertEqual(self.resolved, [HOST])                       # 홉당 해석 1회
        self.assertEqual(self.connects, [(PUB, 443)])                 # 소켓 생성 주소 = 검증한 IP
        self.assertEqual(pools, [(PUB, HOST)])                        # 풀의 host 는 IP, SNI 는 이름

    def test_second_resolution_to_loopback_is_never_used_across_redirect_hops(self):
        answers = {HOST: iter([[PUB], ['127.0.0.1']]), OTHER: iter([[PUB2], ['10.0.0.1']])}
        self.dns[HOST] = lambda: next(answers[HOST])
        self.dns[OTHER] = lambda: next(answers[OTHER])
        self.good.routes['/ok.txt'] = redirect('https://%s/final.txt' % OTHER)
        self.route('/final.txt', b'done')
        got = self.fetch(OK_URL)
        self.assertEqual(got.data, b'done')
        self.assertEqual(self.resolved, [HOST, OTHER])
        self.assertEqual(self.connects, [(PUB, 443), (PUB2, 443)])

    def test_rebinding_to_private_on_the_redirect_hop_is_refused(self):
        self.good.routes['/ok.txt'] = redirect('https://%s/x' % INTERNAL)
        self.assertFailed(OK_URL, 'blocked')
        self.assertEqual(self.connects, [(PUB, 443)])                 # 사설 호스트로는 연결 0

    def test_request_line_and_host_header_use_the_name_not_the_ip(self):
        self.route('/ok.txt', b'x')
        self.fetch(OK_URL)
        self.assertEqual(self.good.requests[0]['raw']['Host'], HOST)
        self.assertNotIn(PUB, json.dumps(self.good.requests))


# ═════════════════════════════════════════════════════════════════════════════
# 묶음 4 — 리다이렉트
# ═════════════════════════════════════════════════════════════════════════════

class RedirectTest(_NetBase):

    def test_https_to_http_is_refused(self):
        self.good.routes['/ok.txt'] = redirect('http://%s/ok.txt' % HOST)
        self.assertFailed(OK_URL, 'redirect')
        self.assertEqual(len(self.connects), 1)

    def test_redirect_to_a_host_that_resolves_private_is_refused(self):
        self.good.routes['/ok.txt'] = redirect('https://%s/x' % INTERNAL)
        self.assertFailed(OK_URL, 'blocked')
        self.good.routes['/ok.txt'] = redirect('//%s/x' % INTERNAL)           # 스킴 상대
        self.assertFailed(OK_URL, 'blocked')
        self.assertEqual(len(self.connects), 2)                                 # 처음 홉만

    def test_redirect_to_ip_literals_ports_userinfo_and_other_schemes_is_refused(self):
        for loc in ('https://127.0.0.1/x', 'https://169.254.169.254/latest/meta-data/',
                    'https://[::1]/', 'https://2130706433/', 'https://%s:8443/x' % HOST,
                    'https://u:p@%s/x' % HOST, 'https://evil@%s/x' % HOST,
                    'ftp://%s/x' % HOST, 'file:///etc/passwd', 'javascript:alert(1)',
                    'https://%s/é' % HOST, 'https://localhost/x'):
            self.good.routes['/ok.txt'] = redirect(loc)
            self.assertFailed(OK_URL, 'redirect')
        self.assertEqual(len(self.connects), 12)       # 홉 1 만(= 시도 수)

    def _chain(self, n, final=b'end', status=302):
        for i in range(n):
            nxt = '/r%d' % (i + 1) if i + 1 < n else '/final'
            self.good.routes['/r%d' % i] = redirect(nxt, status=status)
        self.route('/final', final)

    def test_three_redirects_succeed_and_four_are_refused(self):
        self._chain(3)
        got = self.fetch('https://%s/r0' % HOST)
        self.assertEqual(got.data, b'end')
        self.assertEqual(self.resolved, [HOST] * 4)                  # 홉마다 다시 해석
        self.assertEqual(len(self.connects), 4)
        self.resolved.clear()
        self.connects.clear()
        self._chain(4)
        self.assertFailed('https://%s/r0' % HOST, 'redirect')
        self.assertEqual(len(self.connects), 4)                      # 네 번째 응답이 또 3xx → 거부
        self.assertEqual(len(self.resolved), 4)

    def test_every_redirect_status_is_followed_and_relative_locations_resolve(self):
        for status in (301, 302, 303, 307, 308):
            self.good.routes['/ok.txt'] = redirect('/rel/final.txt?x=1', status=status)
            self.route('/rel/final.txt', b'rel%d' % status)
            self.assertEqual(self.fetch(OK_URL).data, b'rel%d' % status)
        self.good.routes['/dir/a'] = redirect('b.txt')
        self.route('/dir/b.txt', b'sibling')
        self.assertEqual(self.fetch('https://%s/dir/a' % HOST).data, b'sibling')

    def test_other_3xx_and_missing_location_are_refused(self):
        for status in (300, 304, 305, 306, 309, 310):
            self.good.routes['/ok.txt'] = redirect('/final.txt', status=status)
            self.route('/final.txt', b'x')
            self.assertFailed(OK_URL, 'status')
        self.route('/ok.txt', b'', status=302)
        self.assertFailed(OK_URL, 'redirect')

    def test_redirect_to_another_public_host_works_and_keeps_name_pinning(self):
        self.good.routes['/ok.txt'] = redirect('https://%s/b.txt' % OTHER)
        self.route('/b.txt', b'other')
        got = self.fetch(OK_URL)
        self.assertEqual(got.data, b'other')
        self.assertEqual(got.host, HOST)                              # 감사·이름 힌트는 처음 호스트
        self.assertEqual([r['raw']['Host'] for r in self.good.requests], [HOST, OTHER])
        self.assertEqual(self.connects, [(PUB, 443), (PUB2, 443)])

    def test_cookies_and_credentials_do_not_follow_redirects(self):
        self.good.routes['/ok.txt'] = redirect('https://%s/b.txt' % OTHER,
                                               **{'Set-Cookie': 'sid=secret; Path=/'})
        self.route('/b.txt', b'ok')
        self.fetch(OK_URL)
        for req in self.good.requests:
            names = {k.lower() for k in req['raw']}
            self.assertFalse(names & {'cookie', 'authorization', 'referer', 'proxy-authorization'})

    def test_redirect_name_hint_uses_the_given_url_then_the_final_one(self):
        self.good.routes['/get'] = redirect('/files/photo.png')
        self.route('/files/photo.png', _img('PNG'))
        got = self.fetch('https://%s/get' % HOST)
        self.assertEqual(got.name_hint, 'photo.png')
        self.route('/report.csv', b'a,b')
        self.assertEqual(self.fetch('https://%s/report.csv' % HOST).name_hint, 'report.csv')


# ═════════════════════════════════════════════════════════════════════════════
# 묶음 5 — 응답
# ═════════════════════════════════════════════════════════════════════════════

class ResponseTest(_NetBase):

    def test_content_length_over_the_cap_is_refused_before_reading_the_body(self):
        def route(h):
            h.send_response(200)
            h.send_header('Content-Length', str(6 * 1024 * 1024))
            h.end_headers()
            h.wfile.write(b'a' * 1000)
            time.sleep(0.3)
        self.good.routes['/ok.txt'] = route
        self.assertFailed(OK_URL, 'too_large', 'attach is larger than 5 MB.',
                          factory=self.counting_factory)
        self.assertEqual(self.bytes_read, 0)

    def test_chunked_body_without_length_is_cut_at_the_cap(self):
        total = 5 * 1024 * 1024 + 1
        self.route('/ok.txt', b'z' * total, chunked=True)
        self.assertFailed(OK_URL, 'too_large', 'attach is larger than 5 MB.',
                          factory=self.counting_factory)
        self.assertLessEqual(self.bytes_read, F.MAX_FILE_BYTES + X.CHUNK)
        self.assertGreater(self.bytes_read, F.MAX_FILE_BYTES)

    def test_a_body_with_no_length_that_ends_the_connection_is_cut_at_the_cap(self):
        def route(h):                                  # CL 도 chunked 도 없이 끊길 때까지(HTTP/1.0 식)
            h.send_response(200)
            h.send_header('Connection', 'close')
            h.end_headers()
            for _ in range(200):
                h.wfile.write(b'q' * 65536)
        self.good.routes['/ok.txt'] = route
        self.assertFailed(OK_URL, 'too_large', 'attach is larger than 5 MB.',
                          factory=self.counting_factory)
        self.assertLessEqual(self.bytes_read, F.MAX_FILE_BYTES + X.CHUNK)

    def test_a_lying_small_content_length_never_yields_more_than_declared(self):
        def route(h):
            h.send_response(200)
            h.send_header('Content-Length', '10')
            h.end_headers()
            h.wfile.write(b'0123456789' + b'x' * (6 * 1024 * 1024))
        self.good.routes['/ok.txt'] = route
        got = self.fetch(OK_URL, factory=self.counting_factory)
        self.assertEqual(got.data, b'0123456789')
        self.assertEqual(self.bytes_read, 10)

    def test_short_body_for_the_declared_length_is_a_failure_not_a_truncated_file(self):
        def route(h):
            h.send_response(200)
            h.send_header('Content-Length', '100')
            h.end_headers()
            h.wfile.write(b'short')
        self.good.routes['/ok.txt'] = route
        self.assertFailed(OK_URL, 'connect')

    def test_compressed_responses_are_refused_and_identity_is_fine(self):
        import gzip
        for enc in ('gzip', 'deflate', 'br', 'zstd', 'GZIP', 'gzip, identity'):
            self.route('/ok.txt', gzip.compress(b'hi'), headers={'Content-Encoding': enc})
            self.assertFailed(OK_URL, 'encoding')
        self.route('/ok.txt', b'plain', headers={'Content-Encoding': 'identity'})
        self.assertEqual(self.fetch(OK_URL).data, b'plain')

    def test_only_status_200_succeeds(self):
        for status in (201, 202, 203, 204, 206, 205, 400, 401, 403, 404, 410, 429, 500, 502, 503):
            self.route('/ok.txt', b'' if status in (204, 205) else b'body', status=status,
                       length=status not in (204, 205))
            self.assertFailed(OK_URL, 'status')

    def test_slow_body_is_cut_by_the_total_deadline(self):
        def route(h):
            h.send_response(200)
            h.send_header('Content-Length', '1000')
            h.end_headers()
            for _ in range(100):
                h.wfile.write(b'.')
                h.wfile.flush()
                time.sleep(0.2)
        self.good.routes['/ok.txt'] = route
        started = time.monotonic()
        with mock.patch.object(X, 'TOTAL_S', 1.0):
            self.assertFailed(OK_URL, 'timeout')
        self.assertLess(time.monotonic() - started, 3.5)

    def test_slow_headers_are_cut_by_the_total_deadline_too(self):
        def route(h):
            h.wfile.write(b'HTTP/1.1 200 OK\r\n')
            for i in range(100):
                h.wfile.write(b'X-%d: 1\r\n' % i)
                h.wfile.flush()
                time.sleep(0.2)
        self.good.routes['/ok.txt'] = route
        started = time.monotonic()
        with mock.patch.object(X, 'TOTAL_S', 1.0):
            self.assertFailed(OK_URL, 'timeout')
        self.assertLess(time.monotonic() - started, 3.5)

    def test_server_that_never_answers_times_out(self):
        self.good.routes['/ok.txt'] = lambda h: time.sleep(3)
        started = time.monotonic()
        with mock.patch.object(X, 'TOTAL_S', 1.0), mock.patch.object(X, 'READ_S', 0.5):
            self.assertFailed(OK_URL, 'timeout')
        self.assertLess(time.monotonic() - started, 3.0)

    def test_html_over_512_kib_gets_the_kb_message(self):
        body = b'<p>' + b'a' * (F.ARTIFACT_MAX_BYTES - 2)            # 512 KiB + 1
        self.assertEqual(len(body), F.ARTIFACT_MAX_BYTES + 1)
        self.route('/p.html', body)
        self.assertFailed('https://%s/p.html' % HOST, 'too_large', 'html is larger than 512 KB.',
                          cap=F.ARTIFACT_MAX_BYTES)
        self.route('/p.html', body[:-1])
        self.assertEqual(len(self.fetch('https://%s/p.html' % HOST,
                                        cap=F.ARTIFACT_MAX_BYTES).data), F.ARTIFACT_MAX_BYTES)

    def test_exactly_the_cap_passes_and_one_more_fails(self):
        self.route('/ok.txt', b'a' * 1000)
        self.assertEqual(len(self.fetch(OK_URL, cap=1000).data), 1000)
        self.route('/ok.txt', b'a' * 1001)
        with self.assertRaises(X.FetchError) as cm:
            self.fetch(OK_URL, cap=1000)
        self.assertEqual(cm.exception.code, 'too_large')

    def test_content_type_and_content_disposition_are_not_trusted(self):
        png = _img('PNG')
        self.route('/get', png, headers={'Content-Type': 'text/html',
                                         'Content-Disposition': 'attachment; filename="evil.html"'})
        got = self.fetch('https://%s/get' % HOST)
        self.assertEqual((got.data, got.name_hint), (png, None))

    def test_non_ascii_header_bytes_in_location_do_not_crash(self):
        def route(h):
            h.send_response(302)
            h.send_header('Location', 'https://%s/café'.encode('latin-1', 'replace').decode('latin-1') % HOST)
            h.send_header('Content-Length', '0')
            h.end_headers()
        self.good.routes['/ok.txt'] = route
        self.assertFailed(OK_URL, 'redirect')

    def test_connection_reset_and_garbage_are_generic_failures(self):
        def route(h):
            h.wfile.write(b'this is not http\r\n\r\n')
        self.good.routes['/ok.txt'] = route
        self.assertFailed(OK_URL, 'connect')
        self.good.routes['/ok.txt'] = lambda h: h.connection.close()
        self.assertFailed(OK_URL, 'connect')


# ═════════════════════════════════════════════════════════════════════════════
# 묶음 6 — 요청
# ═════════════════════════════════════════════════════════════════════════════

class RequestTest(_NetBase):

    def test_exact_request_headers(self):
        self.route('/a.png', b'x')
        self.fetch('https://%s/a.png?q=1' % HOST)
        req = self.good.requests[0]
        self.assertEqual(req['path'], '/a.png?q=1')
        self.assertEqual(req['raw'], {'Host': HOST, 'User-Agent': X.UA, 'Accept': '*/*',
                                      'Accept-Encoding': 'identity', 'Connection': 'close'})
        self.assertEqual(X.UA, 'AoT-AI-Card/1.0')

    def test_no_cookie_authorization_referer_or_proxy_headers_ever(self):
        self.route('/a', b'x')
        self.fetch('https://%s/a' % HOST)
        names = {k.lower() for k, _v in self.good.requests[0]['headers']}
        for banned in ('cookie', 'authorization', 'referer', 'origin', 'proxy-authorization',
                       'proxy-connection', 'x-forwarded-for', 'forwarded', 'via', 'range',
                       'if-none-match', 'if-modified-since', 'content-length', 'transfer-encoding'):
            self.assertNotIn(banned, names)

    def test_percent_encoded_crlf_in_the_path_stays_encoded(self):
        # urllib3 가 퍼센트 16진수를 대문자로 맞춘다 — 중요한 것은 CR/LF 가 글자로 풀리지 않는 것
        self.route('/a%0D%0AX-Evil:%20y', b'x')
        self.fetch('https://%s/a%%0d%%0aX-Evil:%%20y' % HOST)
        req = self.good.requests[0]
        self.assertEqual(req['path'].upper(), '/a%0D%0AX-Evil:%20y'.upper())
        self.assertNotIn('X-Evil', req['raw'])
        self.assertEqual(set(req['raw']), {'Host', 'User-Agent', 'Accept', 'Accept-Encoding',
                                           'Connection'})

    def test_path_is_sent_as_given_even_when_it_looks_like_an_authority(self):
        """`//evil.com/x` 는 경로다 — 요청 줄이 다른 호스트를 가리키거나 절대 주소가 되면 안 된다."""
        for path in ('//evil.example.com/x', '///x', '/a//b/../c', '/%2e%2e/%2e%2e/etc/passwd',
                     '/?u=https://169.254.169.254/', '/@evil.example.com/', '/:443/x'):
            self.good.requests.clear()
            self.good.routes.clear()
            try:                    # urllib3 가 선행 `//` 를 하나로 합치므로 404 일 수 있다 — 여기서 볼 것은 요청 줄
                self.good.routes[path.split('?')[0]] = lambda h: respond(h, 200, b'x')
                self.fetch('https://%s%s' % (HOST, path))
            except X.FetchError:
                pass
            sent = self.good.requests[0]['path']
            self.assertTrue(sent.startswith('/'), (path, sent))
            self.assertFalse(sent.lower().startswith(('http:', 'https:')), (path, sent))
            self.assertEqual(self.good.requests[0]['raw']['Host'], HOST)
            self.assertEqual(len(self.good.requests), 1)

    def test_proxy_environment_variables_are_ignored(self):
        self.route('/a', b'direct')
        env = {k: 'http://127.0.0.1:9' for k in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY',
                                                 'http_proxy', 'ALL_PROXY', 'all_proxy')}
        env['NO_PROXY'] = 'nothing.invalid'
        env['no_proxy'] = 'nothing.invalid'
        with mock.patch.dict(os.environ, env):
            got = self.fetch('https://%s/a' % HOST)
        self.assertEqual(got.data, b'direct')
        self.assertEqual(self.connects, [(PUB, 443)])           # 프록시(127.0.0.1:9)가 아니라 검증한 IP

    def test_module_does_not_use_requests_httpx_or_proxy_managers(self):
        src = inspect.getsource(X)
        code = '\n'.join(line for line in src.splitlines() if not line.strip().startswith('#'))
        for banned in ('import requests', 'from requests', 'import httpx', 'from httpx',
                       'ProxyManager', 'PoolManager', 'trust_env', 'getproxies', 'import urllib.request',
                       'urlopen(url', 'allow_redirects', 'proxy_from_env', 'http.client'):
            self.assertNotIn(banned, code)
        self.assertNotIn('requests', vars(X))
        self.assertNotIn('httpx', vars(X))

    def test_pool_is_pinned_and_verifying(self):
        import urllib3
        pool = X._make_pool(PUB, HOST, self.client_ctx, urllib3.Timeout(connect=3, read=5),
                            lambda s: None)
        try:
            self.assertEqual((pool.host, pool.port), (PUB, 443))
            self.assertEqual(pool.conn_kw['server_hostname'], HOST)
            self.assertEqual(pool.assert_hostname, HOST)
            self.assertIs(pool.conn_kw['ssl_context'], self.client_ctx)
            self.assertIs(pool.retries, False)
            self.assertEqual(pool.pool.maxsize, 1)
            self.assertIsNone(getattr(pool, 'proxy', None))
        finally:
            pool.close()


# ═════════════════════════════════════════════════════════════════════════════
# 묶음 7 — TLS
# ═════════════════════════════════════════════════════════════════════════════

class TlsTest(_NetBase):

    def test_sni_and_certificate_name_are_the_host_not_the_ip(self):
        self.route('/a', b'tls-ok')
        self.assertEqual(self.fetch('https://%s/a' % HOST).data, b'tls-ok')
        self.assertEqual(self.sni, [HOST])
        self.assertNotIn(PUB, self.sni)

    def test_certificate_for_another_name_is_refused(self):
        self.ip_port[PUB] = self.wrong.port
        self.wrong.routes['/a'] = lambda h: respond(h, 200, b'leak')
        self.assertFailed('https://%s/a' % HOST, 'tls')
        self.assertEqual(self.wrong.requests, [])                  # 요청이 서버에 닿지 않았다

    def test_certificate_from_an_untrusted_ca_is_refused(self):
        self.ip_port[PUB] = self.untrusted.port
        self.assertFailed('https://%s/a' % HOST, 'tls')
        self.assertEqual(self.untrusted.requests, [])

    def test_empty_trust_store_refuses_even_a_valid_certificate(self):
        ctx = ssl.create_default_context(cafile=os.path.join(_PKI['dir'], 'other_ca.pem'))
        self.client_ctx = ctx
        self.route('/a', b'x')
        self.assertFailed('https://%s/a' % HOST, 'tls')
        self.assertEqual(self.good.requests, [])

    def test_expired_certificate_is_refused(self):
        self.ip_port[PUB] = self.expired.port
        self.assertFailed('https://%s/a' % HOST, 'tls')

    def test_tls_below_1_2_is_refused(self):
        try:
            old = start_server('good', max_version=ssl.TLSVersion.TLSv1_1)
        except (ValueError, ssl.SSLError):
            self.skipTest('this OpenSSL cannot serve TLS 1.1')
        try:
            self.ip_port[PUB] = old.port
            old.routes['/a'] = lambda h: respond(h, 200, b'old')
            self.assertFailed('https://%s/a' % HOST, 'tls')
            self.assertEqual(old.requests, [])
        finally:
            stop_server(old)

    def test_real_context_is_strict(self):
        with mock.patch.object(X, '_ssl_context', _REAL_SSL_CONTEXT), \
                mock.patch.object(X, '_ctx', None):
            ctx = X._ssl_context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertGreater(len(ctx.get_ca_certs()), 20)           # certifi 번들이 실제로 실렸다


# ═════════════════════════════════════════════════════════════════════════════
# B2 동시성 · B3 한도·감사
# ═════════════════════════════════════════════════════════════════════════════

class ConcurrencyTest(_NetBase):

    def test_process_slots_two_third_is_busy_at_once(self):
        a, b = X._admission(101), X._admission(102)
        with a, b:
            started = time.monotonic()
            with self.assertRaises(X.FetchError) as cm:
                with X._admission(103):
                    pass
            self.assertLess(time.monotonic() - started, 0.1)         # 기다리지 않는다
            self.assertEqual((str(cm.exception), cm.exception.code), (X.MSG_BUSY, 'busy'))
        with X._admission(103):                                     # 반납됐다
            pass

    def test_same_user_twice_at_once_is_busy_and_other_users_are_not(self):
        with X._admission(201):
            with self.assertRaises(X.FetchError) as cm:
                with X._admission(201):
                    pass
            self.assertEqual(cm.exception.code, 'busy')
            with X._admission(202):
                pass

    def test_slot_and_user_are_released_on_exceptions(self):
        for _ in range(5):
            with self.assertRaises(RuntimeError):
                with X._admission(301):
                    raise RuntimeError('boom')
        a, b = X._admission(1), X._admission(2)
        with a, b:
            pass

    def test_fetch_is_busy_while_the_same_user_holds_a_slot_and_records_a_row(self):
        self.route('/ok.txt', b'x')
        with X._admission(self.pk):
            self.assertFailed(OK_URL, 'busy', X.MSG_BUSY)
        self.assertEqual(self.connects, [])
        self.assertEqual([r.detail.split()[0] for r in self.audit_rows()], ['busy'])
        self.assertEqual(self.fetch(OK_URL).data, b'x')            # 풀리면 다시 된다

    def test_fetch_is_busy_when_both_process_slots_are_taken(self):
        with X._admission(901), X._admission(902):
            self.assertFailed(OK_URL, 'busy', X.MSG_BUSY)
        self.assertEqual(self.resolved, [])

    def test_slot_is_returned_after_every_failure_path(self):
        self.route('/ok.txt', b'x', status=500)
        for _ in range(6):
            self.assertFailed(OK_URL, 'status')
        self.route('/ok.txt', b'x')
        self.assertEqual(self.fetch(OK_URL).data, b'x')

    def test_slot_is_released_before_the_image_inspection(self):
        """계약 ⑪ — 가져오기 슬롯은 디코드 전에 반납한다(디코드 슬롯과 겹쳐 쥐지 않는다)."""
        self.route('/p.png', _img('PNG'))
        held = []
        real = F.inspect_bytes

        def spy(ext, data):
            held.append(X._busy_users.copy())
            return real(ext, data)
        with mock.patch.object(F, 'inspect_bytes', spy):
            F.prepare({'url': 'https://%s/p.png' % HOST}, self.user, self.pk)
        self.assertEqual(held, [set()])


class LimitAuditTest(_NetBase):
    real_limits = True

    def _add_rows(self, n, age=datetime.timedelta(0), code='bad_url'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import AuditLog
        stamp = self.C._now() - age
        for _ in range(n):
            db.session.add(AuditLog(action='ai_card.fetch', user_id=self.pk, result='failure',
                                    detail='%s 0' % code, timestamp=stamp,
                                    target_type='AICardFetch'))
        db.session.commit()

    def test_31st_attempt_in_an_hour_is_refused_without_a_row_or_dns(self):
        self.route('/ok.txt', b'x')
        self._add_rows(X.PER_HOUR - 1)
        got = self.fetch(OK_URL)                                   # 30번째는 된다
        self.assertEqual(got.data, b'x')
        got.attempt.finish('ok', 1, 'card-1')
        before = len(self.audit_rows())
        self.resolved.clear()
        self.assertFailed(OK_URL, 'limit', 'URL fetch limit reached (30 per hour). Try again later.')
        self.assertEqual(len(self.audit_rows()), before)           # 한도 거부는 0행
        self.assertEqual((self.resolved, self.connects[1:]), ([], []))

    def test_failures_and_blocks_count_toward_the_limit(self):
        for i in range(X.PER_HOUR):
            with self.assertRaises(X.FetchError):
                self.fetch('http://files.example.com/%d' % i if i % 2 else 'https://127.0.0.1/%d' % i)
        self.assertEqual(len(self.audit_rows()), X.PER_HOUR)
        self.assertFailed(OK_URL, 'limit', X.MSG_HOUR)

    def test_blocked_dns_results_count_too(self):
        self.dns[HOST] = ['10.0.0.1']
        for _ in range(X.PER_HOUR):
            with self.assertRaises(X.FetchError):
                self.fetch(OK_URL)
        self.assertFailed(OK_URL, 'limit', X.MSG_HOUR)

    def test_old_rows_leave_the_hour_window_but_stay_in_the_day_window(self):
        self._add_rows(X.PER_HOUR, age=datetime.timedelta(hours=2))
        self.route('/ok.txt', b'x')
        got = self.fetch(OK_URL)                                   # 시간 창은 비었다
        self.assertEqual(got.data, b'x')
        got.attempt.finish('ok', 1, 'card-1')
        self._add_rows(X.PER_DAY - X.PER_HOUR - 1, age=datetime.timedelta(hours=5))
        self.assertEqual(len(self.audit_rows()), X.PER_DAY)
        self.assertFailed(OK_URL, 'limit', X.MSG_DAY)
        self._add_rows(5, age=datetime.timedelta(hours=30))        # 하루 밖은 세지 않는다

    def test_limit_is_per_user(self):
        self._add_rows(X.PER_HOUR)
        self.route('/ok.txt', b'x')
        self.assertFailed(OK_URL, 'limit', X.MSG_HOUR)
        self.assertEqual(self.fetch(OK_URL, user=self.other).data, b'x')

    def test_audit_row_has_the_host_only(self):
        self.route('/secret/report.csv', b'a,b')
        url = 'https://%s/secret/report.csv?token=SUPERSECRET&sig=abc#frag' % HOST
        self.fetch(url).attempt.finish('ok', 3, 'card-uuid-1')
        row = self.audit_rows()[-1]
        self.assertEqual((row.action, row.target_type, row.target_id, row.target_name, row.result),
                         ('ai_card.fetch', 'AICardFetch', 'card-uuid-1', HOST, 'success'))
        self.assertEqual(row.detail, 'ok 3')
        blob = json.dumps([row.target_name, row.detail, row.before_json, row.after_json,
                           row.target_id, row.username])
        for secret in ('SUPERSECRET', 'secret', 'token', 'sig=', 'report.csv', 'frag', 'https://'):
            self.assertNotIn(secret, blob)

    def test_userinfo_never_reaches_the_audit(self):
        self.assertFailed('https://admin:hunter2@%s/x' % HOST, 'bad_url', X.MSG_SHAPE)
        self.assertFailed('https://%s:8443/x?k=v' % HOST, 'bad_url', X.MSG_SHAPE)
        for row in self.audit_rows():
            self.assertNotIn('hunter2', json.dumps([row.target_name, row.detail]))
            self.assertNotIn('admin', json.dumps([row.target_name, row.detail]))
            self.assertEqual(row.target_name, HOST)
        self.assertFailed('https://%s/a b' % HOST, 'bad_url', X.MSG_SHAPE)
        self.assertFailed('not a url at all é', 'bad_url', X.MSG_SHAPE)
        self.assertIsNone(self.audit_rows()[-1].target_name)

    def test_one_row_per_attempt_for_every_outcome(self):
        self.route('/ok.txt', b'x')
        self.fetch(OK_URL).attempt.finish('ok', 1, 'u1')
        self.route('/ok.txt', b'x', status=404)
        with self.assertRaises(X.FetchError):
            self.fetch(OK_URL)
        with self.assertRaises(X.FetchError):
            self.fetch('http://x.com/')
        self.assertEqual([r.detail.split()[0] for r in self.audit_rows()],
                         ['ok', 'status', 'bad_url'])
        att = self.fetch_attempt_twice()
        self.assertEqual(att, 1)

    def fetch_attempt_twice(self):
        self.route('/ok.txt', b'x')
        n = len(self.audit_rows())
        a = self.fetch(OK_URL).attempt
        a.finish('ok', 1)
        a.finish('store', 1)                                        # 두 번째는 무시된다
        return len(self.audit_rows()) - n


# ═════════════════════════════════════════════════════════════════════════════
# B4 post · B5 승격 · B6 parse_attach · B7 훅 · B8 공지 · B9 토큰
# ═════════════════════════════════════════════════════════════════════════════

class PostUrlTest(_NetBase):

    def _url_post(self, url, name=None, **extra):
        attach = {'url': url}
        if name:
            attach['name'] = name
        return self._file_post(attach, **extra)

    def test_url_to_an_image_card_with_thumbnail_and_success_audit(self):
        self.route('/photos/plot.png', _img('PNG', (400, 300)))
        out = self._url_post('https://%s/photos/plot.png' % HOST)
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual((out['file']['name'], out['file']['kind']), ('plot.png', 'image'))
        card = self._card()
        self.assertEqual((card.kind, card.file_name, card.file_mime), ('image', 'plot.png', 'image/png'))
        files = sorted(os.path.basename(p) for p in self._files_on_disk())
        self.assertEqual(len(files), 2)                                         # 원본 + 섬네일
        self.assertTrue(any(f.endswith('_t.jpg') for f in files))
        self.assertFalse([f for f in files if f.endswith('.part')])
        row = self.audit_rows()[-1]
        self.assertEqual((row.result, row.target_id, row.target_name, row.detail.split()[0]),
                         ('success', card.unique_id, HOST, 'ok'))
        self.assertNotIn('note_image', out)

    def test_given_name_wins_over_the_url_name(self):
        self.route('/x/a.png', _img('PNG'))
        out = self._url_post('https://%s/x/a.png' % HOST, name='report.png')
        self.assertEqual(out['file']['name'], 'report.png')

    def test_percent_encoded_utf8_path_name(self):
        self.route('/%ED%95%9C%EA%B8%80.csv', b'a,b\n1,2\n')
        out = self._url_post('https://%s/%%ED%%95%%9C%%EA%%B8%%80.csv' % HOST)
        self.assertEqual(out['file']['name'], '한글.csv')
        self.assertEqual(out['file']['kind'], 'file')

    def test_missing_extension_is_sniffed_for_images_and_pdf_only(self):
        self.route('/download', _img('PNG'))
        self.assertEqual(self._url_post('https://%s/download' % HOST)['file']['name'], 'download.png')
        self._backdate(minutes=2)
        self.route('/doc', _PDF)
        self.assertEqual(self._url_post('https://%s/doc' % HOST)['file']['name'], 'download.pdf')
        self._backdate(minutes=2)
        self.route('/data', b'a,b\n1,2\n')
        out = self._url_post('https://%s/data' % HOST)
        self.assertEqual(out['error'], 'attach needs a name like report.csv.')
        self.assertEqual(self._url_post('https://%s/data' % HOST, name='t.csv')['status'], 'posted')

    def test_csv_and_json_text_files(self):
        self.route('/weekly.csv', 'a,b\n한,2\n'.encode('utf-8'),
                   headers={'Content-Type': 'application/octet-stream'})
        out = self._url_post('https://%s/weekly.csv' % HOST)
        self.assertEqual((out['file']['kind'], out['file']['name']), ('file', 'weekly.csv'))

    def test_url_with_a_query_but_a_good_final_name(self):
        self.good.routes['/get'] = redirect('/files/photo.png?sig=1')
        self.route('/files/photo.png', _img('PNG'))
        out = self._url_post('https://%s/get?id=7' % HOST)
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual(out['file']['name'], 'photo.png')

    def test_content_that_does_not_match_the_extension_leaves_nothing_behind(self):
        self.route('/a.png', b'<html>not a png</html>')
        out = self._url_post('https://%s/a.png' % HOST)
        self.assertEqual(out['status'], 'error')
        self.assertIn('does not match', out['error'])
        self.assertEqual(self._cards(), [])
        self.assertEqual(self._files_on_disk(), [])
        self.assertEqual(self.audit_rows()[-1].detail.split()[0], 'mismatch')

    def test_every_fetch_failure_leaves_no_file_and_no_part(self):
        self.route('/a.png', b'x', status=404)
        self.assertEqual(self._url_post('https://%s/a.png' % HOST)['error'], X.MSG_FAILED)
        self.dns[HOST] = ['10.0.0.1']
        self.assertEqual(self._url_post('https://%s/a.png' % HOST)['error'], X.MSG_FAILED)
        self.assertEqual(self._url_post('http://%s/a.png' % HOST)['error'], X.MSG_SHAPE)
        self.assertEqual(self._cards(), [])
        self.assertFalse(os.path.exists(self.root) and self._files_on_disk())

    def test_failure_after_store_removes_the_files_and_marks_the_attempt(self):
        self.route('/a.png', _img('PNG'))
        with mock.patch.object(self.C, 'create_limited', return_value=(None, 'nope')):
            out = self._url_post('https://%s/a.png' % HOST)
        self.assertEqual(out['error'], 'nope')
        self.assertEqual(self._files_on_disk(), [])
        rows = self.audit_rows()
        self.assertEqual([r.detail.split()[0] for r in rows], ['store'])
        with mock.patch.object(self.C, 'create_limited', side_effect=RuntimeError('db')):
            out = self._url_post('https://%s/a.png' % HOST)
        self.assertEqual(out['status'], 'error')
        self.assertEqual(self._files_on_disk(), [])
        self.assertEqual([r.detail.split()[0] for r in self.audit_rows()], ['store', 'store'])

    def test_url_files_count_toward_the_20_files_a_day(self):
        for i in range(F.FILES_PER_DAY):
            self.C.create(self.pk, 't%d' % i, 'b', 'AI', file={
                'path': 'x/%d.png' % i, 'name': '%d.png' % i, 'mime': 'image/png', 'size': 1,
                'kind': 'image'}, now=self.C._now() - datetime.timedelta(hours=3))
        self.route('/a.png', _img('PNG'))
        out = self._url_post('https://%s/a.png' % HOST)
        self.assertIn('Daily limit of 20 files', out['error'])
        self.assertEqual(self.resolved, [])                         # 가져오기 전에 막힌다

    def test_html_by_url_is_an_artifact_with_the_512_kib_cap(self):
        self.route('/page.html', b'<p>hello</p>')
        out = self._url_post('https://%s/page.html' % HOST)
        self.assertEqual((out['file']['kind'], out['file']['name']), ('artifact', 'page.html'))
        self._backdate(minutes=2)
        self.route('/big.html', b'<p>' + b'a' * F.ARTIFACT_MAX_BYTES)
        out = self._url_post('https://%s/big.html' % HOST)
        self.assertEqual(out['error'], 'html is larger than 512 KB.')

    def test_a_5_mib_png_is_not_stored_by_url_either(self):
        self.route('/huge.png', b'\x89PNG\r\n\x1a\n' + b'0' * (5 * 1024 * 1024))
        out = self._url_post('https://%s/huge.png' % HOST)
        self.assertEqual(out['error'], 'attach is larger than 5 MB.')

    def test_error_text_never_carries_url_status_headers_body_or_ip(self):
        self.route('/a.png', b'SECRETBODY', status=500, headers={'X-Secret': 'HEADERVALUE'})
        out = self._url_post('https://%s/a.png?k=TOKEN' % HOST)
        # 모든 응답에 실리는 `now`(현재 시각 `farm_local`) 는 숫자로만 이루어진 값이라 소수 초 등에
        # 우연히 '500' 이 들어갈 수 있다(2026-11-12 CI 오탐). 새어 나감을 보는 대상이 아니므로
        # 부분 문자열 검사에서 빼고, 대신 그 안에 시각·시간대 외의 것이 없음만 따로 확인한다.
        rest = {k: v for k, v in out.items() if k != 'now'}
        if 'now' in out:
            self.assertEqual(set(out['now']), {'farm_local', 'tz'})
        blob = json.dumps(rest)
        for leak in ('500', 'SECRETBODY', 'HEADERVALUE', 'TOKEN', PUB, HOST, '127.0.0.1'):
            self.assertNotIn(leak, blob)
        self.assertEqual((out['status'], out['error']), ('error', X.MSG_FAILED))
        self.assertFalse(set(out) - {'status', 'error', 'call_state', 'now', 'server_host'})


class PromotionTest(_NetBase):

    MD = 'See the plot:\n\n![field](https://%s/img/a.png)\n\nBye'

    def _md(self, text, **extra):
        return self._post(dict({'message': text}, **extra))

    def test_first_markdown_image_becomes_an_image_card_and_body_is_unchanged(self):
        self.route('/img/a.png', _img('PNG', (320, 200)))
        text = self.MD % HOST
        out = self._md(text)
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual(out['file']['kind'], 'image')
        card = self._card()
        self.assertEqual((card.kind, card.body), ('image', text))
        self.assertEqual(len(self._files_on_disk()), 2)
        self.assertNotIn('note_image', out)

    def test_plain_markdown_link_and_bare_url_to_an_image_are_promoted(self):
        # 2026-10-21: AI 가 `[사진 보기](https://…/x.jpg)` 처럼 느낌표 없이 보낸 카드도 섬네일이 된다.
        self.route('/img/a.png', _img('PNG', (320, 200)))
        for text in ('[사진 보기](https://%s/img/a.png)' % HOST, '사진: https://%s/img/a.png 입니다' % HOST):
            self._backdate(minutes=2)
            out = self._md(text)
            self.assertEqual(out['status'], 'posted', text)
            self.assertEqual(out['file']['kind'], 'image', text)
            self.assertNotIn('note_image', out)

    # 웹페이지 링크 미리보기(2026-10-22)는 따로 시험한다 — 여기서는 이미지 후보만 본다
    @mock.patch('aot.tools.data_tools.system.SystemToolsMixin._PREVIEW_WEB_LINKS', False)
    def test_extensionless_image_link_is_not_fetched_unless_bang_syntax(self):
        self.route('/img/sig', _img('PNG'))
        out = self._md('[사진 보기](https://%s/img/sig?t=1)' % HOST)
        self.assertEqual((out['status'], 'file' in out), ('posted', False))
        self.assertEqual(self.resolved, [])
        self._backdate(minutes=2)
        out = self._md('![사진](https://%s/img/sig?t=1)' % HOST)
        self.assertEqual(out['file']['kind'], 'image')

    def test_failed_fetch_audit_detail_carries_the_http_status(self):
        self.route('/img/a.png', b'x', status=400)
        self._md(self.MD % HOST)
        detail = self.audit_rows()[-1].detail
        self.assertEqual(detail.split(), ['status', '0', 'http=400'])
        self.assertNotIn(HOST, detail)

    def test_md_image_promotion_is_on_by_default_and_can_be_switched_off(self):
        # 사용자 결정(2026-10-20): 본문 `![](https://…)` 이미지는 서버가 받아 섬네일·뷰어로 보인다.
        from aot.tools.data_tools.system import SystemToolsMixin
        self.assertTrue(SystemToolsMixin._PROMOTE_MD_IMAGES)
        self.route('/img/a.png', _img('PNG'))
        with mock.patch.object(SystemToolsMixin, '_PROMOTE_MD_IMAGES', False):
            out = self._md(self.MD % HOST)
        self.assertEqual(out['status'], 'posted')
        self.assertNotIn('file', out)
        self.assertEqual(self.resolved, [])
        self.assertEqual(self.good.requests, [])
        out = self._md((self.MD % HOST).replace('Bye', 'Ciao'))      # 같은 글은 방금 올린 카드로 걸러진다
        self.assertEqual(out['file']['kind'], 'image')
        self.assertEqual(self.resolved, [HOST])

    def test_an_explicit_attach_still_promotes_into_the_remaining_slots(self):
        # P5: 명시 attach 가 있어도 남은 칸(8 − 명시 수)만큼 본문 이미지를 승격한다.
        self.route('/img/a.png', _img('PNG'))
        out = self._md(self.MD % HOST, attach={'name': 'n.txt', 'text': 'hi'})
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual([f['name'] for f in out['files']], ['n.txt', 'a.png'])
        self.assertEqual(self.resolved, [HOST])

    def test_up_to_four_images_are_fetched_in_order_and_the_fifth_is_not(self):
        for n in 'abcde':
            self.route('/img/%s.png' % n, _img('PNG'))
        text = ' '.join('![%s](https://%s/img/%s.png)' % (n, HOST if i % 2 == 0 else OTHER, n)
                        for i, n in enumerate('abcde'))
        self.good.routes.update(self.good.routes)
        out = self._md(text)
        self.assertEqual(out['status'], 'posted')
        self.assertEqual([f['name'] for f in out['files']],
                         ['a.png', 'b.png', 'c.png', 'd.png'])
        self.assertEqual([r['path'] for r in self.good.requests],
                         ['/img/a.png', '/img/b.png', '/img/c.png', '/img/d.png'])
        self.assertNotIn('note_image', out)

    def test_failed_fetch_keeps_the_link_posts_the_card_and_adds_a_note(self):
        self.dns[HOST] = ['10.0.0.1']
        text = self.MD % HOST
        out = self._md(text)
        self.assertEqual(out['status'], 'posted')
        self.assertEqual(out['note_image'], 'The image link was not attached; it stays a link.')
        self.assertNotIn('file', out)
        card = self._card()
        self.assertEqual((card.kind, card.body, card.file_path), ('text', text, None))
        self.assertEqual(self.audit_rows()[-1].detail.split()[0], 'blocked')

    def test_card_limits_skip_the_fetch_entirely(self):
        for i in range(F.FILES_PER_DAY):
            self.C.create(self.pk, 't%d' % i, 'b', 'AI', file={
                'path': 'x/%d.png' % i, 'name': '%d.png' % i, 'mime': 'image/png', 'size': 1,
                'kind': 'image'}, now=self.C._now() - datetime.timedelta(hours=3))
        self.route('/img/a.png', _img('PNG'))
        out = self._md(self.MD % HOST)
        self.assertEqual(out['status'], 'posted')
        self.assertIn('note_image', out)
        self.assertEqual((self.resolved, self.connects), ([], []))

    real_limits = True

    def test_url_fetch_limit_skips_to_a_text_card_with_the_note(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import AuditLog
        for _ in range(_REAL_PER_HOUR):
            db.session.add(AuditLog(action='ai_card.fetch', user_id=self.pk, result='failure',
                                    detail='bad_url 0', timestamp=self.C._now()))
        db.session.commit()
        out = self._md(self.MD % HOST)
        self.assertEqual(out['status'], 'posted')
        self.assertIn('note_image', out)
        self.assertEqual(self.resolved, [])

    def test_a_non_image_response_is_dropped_and_recorded(self):
        self.route('/img/a.png', b'a,b\n1,2\n')                         # 이미지가 아닌 내용
        out = self._md(self.MD % HOST)
        self.assertEqual(out['status'], 'posted')
        self.assertIn('note_image', out)
        self.assertEqual(self._card().kind, 'text')
        self.assertEqual(self._files_on_disk(), [])
        self.assertEqual(self.audit_rows()[-1].detail.split()[0], 'mismatch')

    def test_csv_or_pdf_that_the_link_points_to_is_not_attached(self):
        self.route('/doc.pdf', _PDF)
        out = self._md('![x](https://%s/doc.pdf)' % HOST)
        self.assertIn('note_image', out)
        self.assertEqual(self._card().kind, 'text')
        self.assertEqual(self._files_on_disk(), [])

    # 웹페이지 링크 미리보기(2026-10-22)는 따로 시험한다 — 여기서는 이미지 후보만 본다
    @mock.patch('aot.tools.data_tools.system.SystemToolsMixin._PREVIEW_WEB_LINKS', False)
    def test_non_https_or_odd_links_are_not_candidates(self):
        for text in ('![x](http://%s/a.png)' % HOST, '![x](https://%s/a (1).png)' % HOST,
                     '[x](https://%s/page)' % HOST, 'see https://%s/a.pdf now' % HOST,
                     '![x](data:image/png;base64,AAAA)', '![x](//%s/a.png)' % HOST, 'plain text'):
            self._backdate(minutes=2)
            out = self._md(text)
            self.assertEqual(out['status'], 'posted', text)
            self.assertNotIn('note_image', out)
        self.assertEqual(self.resolved, [])

    def test_unsafe_image_hosts_are_noted_and_never_resolved(self):
        for host in ('127.0.0.1', '2130706433', 'localhost', '[::1]', 'x.internal'):
            self._backdate(minutes=2)
            out = self._md('![x](https://%s/a.png)' % host)
            self.assertEqual(out['status'], 'posted')
            self.assertIn('note_image', out, host)
        self.assertEqual((self.resolved, self.connects), ([], []))

    def test_find_md_images_is_bounded_and_linear(self):
        for text in ('![' * 1000, '![' * 5000, '![' + 'a' * 5000, '![a](https://' + 'a' * 5000,
                     '![a](https://x.com/' + '(' * 3000, ('![a' * 1000) + ']', '!' * 5000 + '[' * 5000,
                     '![' + ']' * 5000, '![a](' + 'https://' * 600):
            started = time.monotonic()
            self.assertEqual(X.find_md_images(text, 1), [], text[:12])
            self.assertLess(time.monotonic() - started, 0.5)
        started = time.monotonic()
        X.find_md_images('![' * 4000 + '![a](https://x.com/a.png)', 1)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_find_md_images_limits_and_order(self):
        text = '![a](https://a.com/1.png) ![b](https://b.com/2.png) ![c](https://c.com/3.png)'
        self.assertEqual(X.find_md_images(text, 1), ['https://a.com/1.png'])
        self.assertEqual(X.find_md_images(text, 2), ['https://a.com/1.png', 'https://b.com/2.png'])
        self.assertEqual(X.find_md_images('![](https://a.com/1.png)', 1), ['https://a.com/1.png'])
        # 글자가 너무 긴 이미지 문법은 맨 주소로 읽힌다(확장자가 있으니 후보).
        self.assertEqual(X.find_md_images('![' + 'x' * 201 + '](https://a.com/1.png)', 1), ['https://a.com/1.png'])
        self.assertEqual(X.find_md_images('![a](https://a.com/' + 'a' * 2060 + ')', 1), [])
        self.assertEqual(X.find_md_images(None, 1), [])

    def test_find_md_images_accepts_plain_links_and_bare_urls_by_extension(self):
        f = X.find_md_images
        self.assertEqual(f('[사진 보기](https://a.com/x.JPG)', 1), ['https://a.com/x.JPG'])
        self.assertEqual(f('[v](https://a.com/x.jpeg?w=1#top)', 1), ['https://a.com/x.jpeg?w=1#top'])
        self.assertEqual(f('[p](https://a.com/x.png) [g](https://a.com/y.gif)', 2),
                         ['https://a.com/x.png', 'https://a.com/y.gif'])
        self.assertEqual(f('그림: https://a.com/x.webp.', 1), ['https://a.com/x.webp'])
        self.assertEqual(f('(https://a.com/x.png)', 1), ['https://a.com/x.png'])
        self.assertEqual(f('**https://a.com/x.png**', 1), ['https://a.com/x.png'])
        # 확장자가 없거나 이미지가 아니면 일반 링크·맨 주소는 후보가 아니다.
        self.assertEqual(f('[x](https://a.com/page) https://a.com/doc.pdf https://a.com/x.png/y', 1), [])
        self.assertEqual(f('[x](https://a.com/x?f=a.png)', 1), [])
        # `![]()` 는 확장자와 무관하게 후보(서명 주소는 받아서 매직바이트로 판정한다).
        self.assertEqual(f('![](https://a.com/sig?token=1)', 1), ['https://a.com/sig?token=1'])
        # 같은 주소는 한 번만, 순서는 글에 나온 순서.
        self.assertEqual(f('![a](https://a.com/1.png) https://a.com/1.png [b](https://b.com/2.png)', 3),
                         ['https://a.com/1.png', 'https://b.com/2.png'])


class ParseAttachTest(_NetBase):

    def test_url_with_another_source_needs_exactly_one(self):
        for attach in ({'url': 'https://a.com/x.png', 'b64': 'eA=='},
                       {'url': 'https://a.com/x.png', 'text': 'x'},
                       {'url': 'https://a.com/x.png', 'ref': 'card:abcdefgh'}, {'name': 'a.png'}):
            with self.assertRaises(F.FileError) as cm:
                F.parse_attach(attach)
            self.assertEqual(str(cm.exception), 'attach needs exactly one of text, b64, ref, url.')

    def test_string_attach_that_is_an_https_link_becomes_url(self):
        self.assertEqual(F.parse_attach('https://a.com/x.png'), (None, 'url', 'https://a.com/x.png'))
        self.assertEqual(F.parse_attach('HTTPS://a.com/x.png')[1:], ('url', 'HTTPS://a.com/x.png'))
        self.assertEqual(F.parse_attach(json.dumps({'name': 'n.png', 'url': 'https://a.com/x.png'})),
                         ('n.png', 'url', 'https://a.com/x.png'))

    def test_other_schemes_in_a_string_get_the_shape_message(self):
        for raw in ('http://a.com/x.png', 'file:///etc/passwd', '//a.com/x.png', 'HTTP://A.COM'):
            with self.assertRaises(F.FileError) as cm:
                F.parse_attach(raw)
            self.assertEqual(str(cm.exception), X.MSG_SHAPE, raw)

    def test_uri_href_path_and_url_shaped_ref_b64_point_to_attach_url(self):
        for attach in ({'name': 'a.png', 'uri': 'https://a.com/a.png'},
                       {'name': 'a.png', 'href': 'https://a.com/a.png'},
                       {'name': 'a.png', 'path': '/etc/passwd'},
                       {'name': 'a.png', 'ref': 'https://a.com/a.png'},
                       {'name': 'a.png', 'b64': 'https://a.com/a.png'}):
            with self.assertRaises(F.FileError) as cm:
                F.parse_attach(attach)
            self.assertEqual(str(cm.exception), 'put https links in attach.url.', attach)

    def test_url_value_must_be_a_string(self):
        for value in (5, ['https://a.com/x'], {'a': 1}, True):
            with self.assertRaises(F.FileError) as cm:
                F.parse_attach({'url': value})
            self.assertEqual(str(cm.exception), X.MSG_SHAPE)

    def test_no_network_for_non_url_attachments(self):
        with mock.patch.object(X, 'fetch', side_effect=AssertionError('fetched')):
            F.prepare({'name': 'a.txt', 'text': 'hi'}, self.user, self.pk)
            F.prepare({'name': 'a.png', 'b64': _B64(_img('PNG'))}, self.user, self.pk)


class HookIsolationTest(_NetBase):

    def test_prepare_calls_fetch_with_exactly_url_user_and_limit(self):
        calls = []

        def fake(*args, **kwargs):
            calls.append((args, kwargs))
            raise X.FetchError(X.MSG_FAILED, 'dns')
        with mock.patch.object(X, 'fetch', fake):
            with self.assertRaises(X.FetchError):
                F.prepare({'url': 'https://%s/a.png' % HOST}, self.user, self.pk)
        self.assertEqual(calls, [(('https://%s/a.png' % HOST, self.user, F.MAX_FILE_BYTES), {})])

    def test_test_hooks_are_not_reachable_from_tool_arguments(self):
        evil = mock.Mock(side_effect=AssertionError('hook reached'))
        self.route('/a.png', _img('PNG'))
        hooks = {'_resolver': evil, '_pool_factory': evil, '_ssl_context': evil}
        for where in ('attach', 'top'):
            self._backdate(minutes=2)
            if where == 'attach':
                args = {'attach': dict({'url': 'https://%s/a.png' % HOST}, **hooks)}
            else:
                args = dict({'attach': {'url': 'https://%s/a.png' % HOST}}, **hooks)
            out = self._post(dict(args, message='hi'))
            self.assertEqual(out['status'], 'posted', (where, out))
        evil.assert_not_called()
        params = inspect.signature(F.prepare).parameters
        self.assertEqual(list(params), ['attach', 'user', 'user_id'])
        from aot.tools.data_tools.system import SystemToolsMixin
        self.assertNotIn('_resolver', inspect.signature(SystemToolsMixin.screen_action).parameters)
        self.assertNotIn('_pool_factory', inspect.signature(SystemToolsMixin._screen_post).parameters)

    def test_the_hook_names_exist_only_as_keyword_only_parameters_of_fetch(self):
        params = inspect.signature(X.fetch).parameters
        self.assertEqual([n for n, p in params.items() if p.kind is p.KEYWORD_ONLY],
                         ['_resolver', '_pool_factory'])


class NoticePreviewTest(_NetBase):
    """공지 링크 미리보기는 이 모듈(fetch_public)로만 나간다 — 같은 TLS 하네스로 확인한다.
    (재현·우회 시도 쪽은 test_notice_preview_ssrf.py.)"""

    _PAGE = ('<html><head><title>Hello</title><meta property="og:title" content="OG t">'
             '<meta property="og:image" content="/img/a.png"></head><body>%s</body></html>')

    def setUp(self):
        super().setUp()
        import aot.aot_flask.routes_notice as rn
        self.rn = rn
        rn._fetch_link_preview.cache_clear()
        self.addCleanup(rn._fetch_link_preview.cache_clear)
        orig = X._make_pool

        def counted(*args):                # counting_factory 가 X._make_pool 을 부르므로 원본으로 되돌려 둔다
            with mock.patch.object(X, '_make_pool', orig):
                return self.counting_factory(*args)
        self._pf = mock.patch.object(X, '_make_pool', counted)
        self._pf.start()
        self.addCleanup(self._pf.stop)

    def test_success_parses_title_and_absolute_image(self):
        self.route('/a', (self._PAGE % '').encode())
        out = self.rn._fetch_link_preview('https://%s/a' % HOST)
        self.assertEqual(out['title'], 'OG t')
        self.assertEqual(out['image'], 'https://%s/img/a.png' % HOST)
        self.assertEqual(out['domain'], HOST)

    def test_big_page_is_truncated_not_refused(self):
        self.route('/big', (self._PAGE % ('x' * 1_000_000)).encode(), chunked=True)
        out = self.rn._fetch_link_preview('https://%s/big' % HOST)
        self.assertEqual(out['title'], 'OG t')
        self.assertLess(self.bytes_read, self.rn.LINK_PREVIEW_MAX_BYTES + 2 * X.CHUNK)

    def test_redirect_is_followed_and_revalidated(self):
        self.good.routes['/go'] = redirect('/a')
        self.route('/a', (self._PAGE % '').encode())
        self.assertEqual(self.rn._fetch_link_preview('https://%s/go' % HOST)['title'], 'OG t')
        self.good.routes['/evil'] = redirect('https://%s/x' % INTERNAL)
        before = len(self.connects)
        out = self.rn._fetch_link_preview('https://%s/evil' % HOST)
        self.assertEqual(out, {'error': 'Preview unavailable'})
        self.assertEqual(len(self.connects), before + 1)             # 내부 호스트로는 연결 0

    def test_every_failure_looks_the_same_and_failures_are_not_cached(self):
        bad = ('http://%s/a' % HOST, 'https://%s:8443/a' % HOST, 'https://%s/a' % INTERNAL,
               'https://127.0.0.1/a', 'https://%s/missing' % HOST, 'ftp://%s/a' % HOST)
        outs = {repr(self.rn._fetch_link_preview(u)) for u in bad}
        self.assertEqual(outs, {repr({'error': 'Preview unavailable'})})
        self.route('/missing', (self._PAGE % '').encode())           # 이제 생김 — 실패가 캐시되면 안 됨
        self.assertEqual(self.rn._fetch_link_preview('https://%s/missing' % HOST)['title'], 'OG t')

    def test_busy_slots_answer_generically(self):
        self.route('/a', (self._PAGE % '').encode())
        sem = threading.BoundedSemaphore(1)
        sem.acquire()
        with mock.patch.object(self.rn, '_PREVIEW_SLOTS', sem):
            out = self.rn._fetch_link_preview('https://%s/a' % HOST)
        self.assertEqual(out, {'error': 'Preview unavailable'})
        self.assertEqual(self.rn._fetch_link_preview('https://%s/a' % HOST)['title'], 'OG t')

    def test_requests_library_is_gone_from_the_notice_route(self):
        self.assertFalse(hasattr(self.rn, 'requests'))
        self.assertFalse(hasattr(self.rn, '_is_public_http_url'))


class TokenTest(unittest.TestCase):

    def test_screen_action_does_not_grow_and_documents_url(self):
        from aot.scripts.measure_ai_tool_cost import _tok
        from aot.tools import tool_registry
        spec = next(t for t in tool_registry._MCP_TOOL_PAYLOADS
                    if t['tool_name'] == 'screen_action')
        chars, tokens = _tok({'name': spec['tool_name'], 'description': spec['description'],
                              'inputSchema': spec['input_schema']})
        self.assertLessEqual(tokens, 783)
        self.assertEqual((chars, tokens), (1551, 775))
        self.assertEqual(spec['input_schema']['properties']['attach']['description'],
                         'post {name, text|b64|ref|url} or list')
        self.assertNotIn('their', spec['description'])
        self.assertIn('AI inbox', spec['description'])
        self.assertNotIn('https', json.dumps(spec))              # 규칙은 설명이 아니라 거부 문구로만

    def test_help_only_extra_args_mention_url(self):
        from aot.tools.domain import registry_data
        src = inspect.getsource(registry_data)
        self.assertIn("'attach': '{name, text|b64|ref|url} or list'", src)   # screen.card 의 help 인자


if __name__ == '__main__':
    unittest.main()
