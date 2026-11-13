# coding=utf-8
"""자체 서명 HTTPS 로 VIGI Open API V1.1 을 흉내 내는 모의 서버.

흉내 내는 것(설계 §10.1):
- doAuth 2단계(SHA-256 챌린지). 틀리면 -10020, N회 틀리면 -10022 잠금.
  **모든 인증 시도를 기록**한다(`auth_log`) — 시험이 "카메라에 간 시도 수"를 센다.
- stok TTL(시험에서는 짧게)과 만료 응답, 동시 클라이언트 상한(-10021).
- getModuleList 변형 셋(PT / 고정형 / 줌), 능력 질의, 제어 메서드.
- subscribeMsg: multipart/mixed 로 이벤트·하트비트, 끊기·하트비트 멈추기.
- 제어 응답 조작: 빈 본문, 깨진 JSON, 임의 error_code.

비밀번호는 서버 설정(`password`)으로만 존재한다. 요청 본문에는 digest 만 온다.
"""
import datetime
import hashlib
import json
import queue
import ssl
import tempfile
import threading
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from aot.camera_drivers.vigi.openapi import digest_response

REALM = 'VIGI-MOCK'
SESSION_INVALID = -40401

VARIANTS = {
    # PT 카메라(C540V 가정): 패닝·틸트 + 프리셋, 줌 없음
    'pt': ['system', 'dateTime', 'audio_speaker', 'audio_microphone', 'video', 'dayNightMode',
           'sdCard', 'motionDetection', 'tamperDetection', 'PeopleDetection', 'VehicleDetection',
           'sound_alarm_enabled', 'light_alarm_enabled', 'ptz', 'StreamPort', 'msgPush',
           'recordSchedule', 'playback', 'download'],
    # 고정형: PTZ·경보 없음
    'fixed': ['system', 'dateTime', 'video', 'dayNightMode', 'sdCard', 'motionDetection',
              'tamperDetection', 'StreamPort', 'msgPush', 'recordSchedule'],
    # 줌 있음: PT + 광학 줌 + 침입 감지
    'zoom': ['system', 'dateTime', 'audio_speaker', 'audio_microphone', 'video', 'dayNightMode',
             'sdCard', 'motionDetection', 'InvasionDetection', 'CrossLineDetection',
             'tamperDetection', 'ptz', 'ptz_zoom', 'StreamPort', 'msgPush', 'playback'],
}
# 제어 시험용: 줌 변형 + 수동 경보
VARIANTS['full'] = VARIANTS['zoom'] + ['manualAlarm']


def _make_cert():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'vigi-mock')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    return key, cert


class MockVigiServer:
    def __init__(self, variant='pt', username='admin', password='correct-horse-battery',
                 fail_limit=3, stok_ttl=1800.0, max_clients=4, clock=time.monotonic,
                 host='127.0.0.1', port=0):
        self.variant = variant
        self._bind = (host, port)
        self.username = username
        self.password = password
        self.fail_limit = fail_limit
        self.stok_ttl = stok_ttl
        self.max_clients = max_clients
        self.clock = clock
        self.realm = REALM
        self.algorithm = 'SHA-256'
        self.lock = threading.RLock()
        # 관측 기록
        self.auth_log = []        # {'step':1|2,'ok':bool|None,'code':int}
        self.commands = []        # 인증된 호출 (method, params)
        self.raw_bodies = []      # 받은 요청 본문 문자열(비밀번호 평문이 오는지 검사용)
        self.fail_count = 0       # 틀린 step-2 시도 누적
        self.locked = False
        self._nonce_seq = 0
        self._nonces = set()
        self._stoks = {}          # stok -> issued_at
        self.day_night = 'auto'
        self.switches = {}        # 'motionDetection' -> {'enabled':..,'msg_push_enabled':..} (get/set…Switch)
        self.overrides = {}       # method -> 'empty'|'garbage'|int(error_code)|dict(전체 응답)
        self._events = queue.Queue()
        self.subscribers = 0
        self.subscribe_attempts = 0   # subscribeMsg 요청 수(구독 재시도 횟수 검사용)
        self._close_subs = threading.Event()
        self.heartbeat_s = 30.0
        self.heartbeats_enabled = True
        self._key, self._cert = _make_cert()
        self.cert_sha256 = hashlib.sha256(
            self._cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        self._httpd = None
        self._thread = None
        self.port = None

    # -- 시험 제어 -----------------------------------------------------------
    @property
    def failed_auth_attempts(self):
        """카메라가 본 틀린 자격 증명 시도 수(잠금 이후 거절된 시도 포함하지 않음)."""
        return self.fail_count

    @property
    def step2_count(self):
        """자격 증명(응답)이 실제로 간 횟수."""
        return sum(1 for e in self.auth_log if e['step'] == 2)

    @property
    def probe_count(self):
        return sum(1 for e in self.auth_log if e['step'] == 1)

    def expire_all_stoks(self):
        with self.lock:
            self._stoks.clear()

    def push_event(self, event):
        self._events.put(event)

    def stop_heartbeats(self):
        self.heartbeats_enabled = False

    def push_raw(self, obj):
        """모르는 모양의 조각(형식 오류 시험)을 그대로 보낸다."""
        self._events.put(obj)

    def close_subscriptions(self):
        self._close_subs.set()

    def set_password(self, password):
        self.password = password

    def unlock(self):
        with self.lock:
            self.locked = False
            self.fail_count = 0

    # -- 내부 ----------------------------------------------------------------
    def _purge(self):
        now = self.clock()
        for s in [s for s, t in self._stoks.items() if now - t >= self.stok_ttl]:
            del self._stoks[s]

    def _challenge(self):
        self._nonce_seq += 1
        nonce = hashlib.sha256(('n%d' % self._nonce_seq).encode()).hexdigest()[:32]
        self._nonces.add(nonce)
        return nonce

    def handle_doauth(self, params):
        with self.lock:
            if self.locked:
                self.auth_log.append({'step': 1 if params is None else 2, 'ok': False,
                                      'code': -10022})
                return {'error_code': -10022}
            if params is None:
                self.auth_log.append({'step': 1, 'ok': None, 'code': -10020})
                return {'error_code': -10020, 'data': {'authenticate': {
                    'realm': self.realm, 'nonce': self._challenge(), 'algorithm': self.algorithm,
                    'uri': '/', 'method': 'POST'}}}
            nonce = params.get('nonce')
            resp = params.get('response')
            expected = digest_response(self.username, self.password, self.realm, nonce, 'POST', '/')
            if nonce not in self._nonces or resp != expected:
                self.fail_count += 1
                self._nonces.discard(nonce)
                if self.fail_count >= self.fail_limit:
                    self.locked = True
                self.auth_log.append({'step': 2, 'ok': False, 'code': -10020})
                return {'error_code': -10020}
            self._nonces.discard(nonce)
            self._purge()
            if len(self._stoks) >= self.max_clients:
                self.auth_log.append({'step': 2, 'ok': False, 'code': -10021})
                return {'error_code': -10021}
            self.fail_count = 0
            stok = hashlib.sha256(('stok%d%f' % (len(self.auth_log), self.clock())).encode()
                                  ).hexdigest()[:32]
            self._stoks[stok] = self.clock()
            self.auth_log.append({'step': 2, 'ok': True, 'code': 0})
            return {'error_code': 0, 'result': {'stok': stok}}

    def handle_call(self, stok, method, params):
        with self.lock:
            self._purge()
            if stok not in self._stoks:
                return {'error_code': SESSION_INVALID}
            self.commands.append((method, params))
            ov = self.overrides.get(method)
        if ov == 'empty':
            return ''
        if ov == 'garbage':
            return '<<not json>>'
        if isinstance(ov, dict):
            return ov
        if isinstance(ov, int):
            return {'error_code': ov}
        mods = VARIANTS[self.variant]
        if method == 'getModuleList':
            return {'error_code': 0, 'result': {
                'module_list': [{'name': m, 'version': '1'} for m in mods]}}
        if method == 'getPTZCapability':
            return {'error_code': 0, 'result': {'speed_max': 7}}
        if method == 'getAudioCapability':
            return {'error_code': 0, 'result': {'speaker': 1, 'microphone': 1}}
        if method == 'getVideoCapability':
            return {'error_code': 0, 'result': {'resolutions': ['2560x1440', '640x360']}}
        if method == 'getEventEnhanceCapability':
            return {'error_code': 0, 'result': {'mask': 3}}
        if method == 'getDeviceInfo':
            return {'error_code': 0, 'result': {'model': 'VIGI C540V', 'swVer': '1.0.0',
                                                'mac': 'AA-BB-CC-00-11-22'}}
        if method == 'getDayNightMode':
            return {'error_code': 0, 'result': {'mode': self.day_night}}
        if method == 'setDayNightMode' and isinstance(params, dict):
            self.day_night = params.get('mode')
            return {'error_code': 0, 'result': {}}
        if method.startswith('get') and method.endswith('Switch'):
            sw = self.switches.get(method[3:-6])
            return {'error_code': 0, 'result': dict(sw)} if sw is not None else {'error_code': -40106}
        if method.startswith('set') and method.endswith('Switch') and isinstance(params, dict):
            self.switches[method[3:-6]] = dict(params)
            return {'error_code': 0, 'result': {}}
        return {'error_code': 0, 'result': {}}

    # -- 수명 -----------------------------------------------------------------
    def start(self):
        mock = self

        class H(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a):
                pass

            def _send(self, payload, status=200):
                body = payload if isinstance(payload, str) else json.dumps(payload)
                data = body.encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                n = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(n).decode('utf-8', 'replace')
                mock.raw_bodies.append(raw)
                try:
                    req = json.loads(raw)
                except ValueError:
                    return self._send({'error_code': -1})
                method, params = req.get('method'), req.get('params')
                if method == 'doAuth':
                    return self._send(mock.handle_doauth(params))
                if not self.path.startswith('/stok='):
                    return self._send({'error_code': SESSION_INVALID})
                stok = self.path[len('/stok='):]
                if method == 'subscribeMsg':
                    return self._subscribe(stok)
                self._send(mock.handle_call(stok, method, params))

            def _subscribe(self, stok):
                with mock.lock:
                    mock.subscribe_attempts += 1
                    mock._purge()
                    ok = stok in mock._stoks
                    ov = mock.overrides.get('subscribeMsg')
                if isinstance(ov, int):      # -10020/-10021 등 구독 거절 흉내
                    mock.commands.append(('subscribeMsg', None))
                    return self._send({'error_code': ov})
                if not ok:
                    return self._send({'error_code': SESSION_INVALID})
                mock.commands.append(('subscribeMsg', None))
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/mixed; boundary=mock-boundary')
                self.send_header('Connection', 'close')
                self.end_headers()
                mock.subscribers += 1
                mock._close_subs.clear()
                last_hb = time.monotonic()
                try:
                    while not mock._close_subs.is_set():
                        part = None
                        try:
                            part = mock._events.get(timeout=0.05)
                        except queue.Empty:
                            if mock.heartbeats_enabled and \
                                    time.monotonic() - last_hb >= mock.heartbeat_s:
                                part = {'Heartbeat': '30'}
                                last_hb = time.monotonic()
                        if part is not None:
                            body = json.dumps(part).encode()
                            self.wfile.write(
                                b'--mock-boundary\r\nContent-Type: application/json\r\n'
                                b'Content-Length: %d\r\n\r\n' % len(body) + body + b'\r\n')
                            self.wfile.flush()
                except OSError:
                    pass
                finally:
                    mock.subscribers -= 1

        httpd = ThreadingHTTPServer(self._bind, H)
        httpd.daemon_threads = True
        d = tempfile.mkdtemp(prefix='vigi-mock-')
        certf, keyf = os.path.join(d, 'c.pem'), os.path.join(d, 'k.pem')
        with open(certf, 'wb') as f:
            f.write(self._cert.public_bytes(serialization.Encoding.PEM))
        with open(keyf, 'wb') as f:
            f.write(self._key.private_bytes(serialization.Encoding.PEM,
                                            serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certf, keyf)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        for p in (certf, keyf):
            os.remove(p)
        os.rmdir(d)
        self._httpd = httpd
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._close_subs.set()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()
