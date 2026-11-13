# coding=utf-8
"""평문 HTTP 로 ONVIF Profile S 를 흉내 내는 모의 서버 (SOAP 1.2).

흉내 내는 것:
- 인증 두 가지: WS-UsernameToken PasswordDigest(`auth='wsse'`) 와 HTTP Digest(`auth='digest'`).
  GetSystemDateAndTime 만 무인증이고 나머지는 인증이 필요하다.
  **자격 증명이 실린 요청을 전부 기록**한다(`auth_log`) — 시험이 "카메라에 간 시도 수"를 센다.
- 틀리면 NotAuthorized(Fault 400 또는 HTTP 401, `unauth_style`), N회 틀리면 잠금 Fault.
- 시계 차이(`clock_skew`), 동시 세션 초과(`limit=True`), 응답 조작(`override`), 만료 nonce(`stale_after`).
- 변형 셋(`ptz`·`fixed`·`bare`): 능력 협상이 서비스별로 갈리게 한다.
- 서비스 XAddr 는 일부러 **다른 host(10.9.9.9)** 를 알려준다 — 클라이언트가 설정된 host 만 쓰는지 확인.

비밀번호는 서버 설정(`password`)으로만 존재한다.
"""
import base64
import hashlib
import json
import re
import secrets
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aot.camera_drivers.onvif import soap as S

REALM = 'ONVIF-MOCK'
FAKE_HOST = '10.9.9.9'

TOPICS_FULL = [
    'RuleEngine/CellMotionDetector/Motion',
    'RuleEngine/LineDetector/Crossed',
    'RuleEngine/FieldDetector/ObjectsInside',
    'RuleEngine/TamperDetector/Tamper',
    'VideoSource/GlobalSceneChange/ImagingService',
    'AudioAnalytics/Audio/DetectedSound',
    'Device/Trigger/Relay',              # 모르는 토픽 → unknown
]

VARIANTS = {
    # 모든 서비스 + PTZ(팬틸트·줌·프리셋 16) + IrCut + SD + 이벤트
    'ptz': dict(services=('device', 'media', 'ptz', 'imaging', 'events'), pan_tilt=True, zoom=True,
                presets=16, ircut=('ON', 'OFF', 'AUTO'), storage=True, topics=TOPICS_FULL),
    # 고정형: 미디어 + 이벤트(움직임만)
    'fixed': dict(services=('device', 'media', 'events'), pan_tilt=False, zoom=False, presets=0,
                  ircut=(), storage=False, topics=['VideoSource/MotionAlarm']),
    # 맨몸: 디바이스 + 미디어만 (Profile S 최소)
    'bare': dict(services=('device', 'media'), pan_tilt=False, zoom=False, presets=0, ircut=(),
                 storage=False, topics=None),
}

_TNS = {'device': S.NS_DEVICE, 'media': S.NS_MEDIA, 'ptz': S.NS_PTZ, 'imaging': S.NS_IMAGING,
        'events': S.NS_EVENTS}
_PATHS = {k: v[1] for k, v in S.SERVICES.items()}


def _env(body):
    return ('<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="%s" xmlns:tt="%s" '
            'xmlns:tds="%s" xmlns:trt="%s" xmlns:tptz="%s" xmlns:timg="%s" xmlns:tev="%s" '
            'xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" '
            'xmlns:wstop="http://docs.oasis-open.org/wsn/t-1" xmlns:tns1="http://www.onvif.org/ver10/topics">'
            '<s:Body>%s</s:Body></s:Envelope>'
            % (S.NS_SOAP, S.NS_SCHEMA, S.NS_DEVICE, S.NS_MEDIA, S.NS_PTZ, S.NS_IMAGING, S.NS_EVENTS,
               body)).encode()


def fault(sub, reason, code='s:Sender'):
    return _env('<s:Fault><s:Code><s:Value>%s</s:Value><s:Subcode><s:Value>%s</s:Value></s:Subcode>'
                '</s:Code><s:Reason><s:Text xml:lang="en">%s</s:Text></s:Reason></s:Fault>'
                % (code, sub, reason))


def _topic_tree(topics):
    tree = {}
    for t in topics:
        node = tree
        for part in t.split('/'):
            node = node.setdefault(part, {})
    def render(d, leaf_depth_path=''):
        out = ''
        for k, v in d.items():
            if v:
                out += '<tns1:%s>%s</tns1:%s>' % (k, render(v), k)
            else:
                out += ('<tns1:%s wstop:topic="true"><tt:MessageDescription IsProperty="true"/>'
                        '</tns1:%s>' % (k, k))
        return out
    return render(tree)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *a):
        pass

    def do_POST(self):
        srv = self.server.mock
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n)
        status, headers, body = srv.handle(self.path, raw, dict(self.headers.items()))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MockOnvifServer:
    def __init__(self, variant='ptz', username='admin', password='correct-horse-battery',
                 auth='wsse', unauth_style='fault', lock_after=0, clock_skew=0, stale_after=0,
                 anonymous=False):
        self.cfg = VARIANTS[variant]
        self.variant = variant
        self.username, self.password = username, password
        self.auth = auth
        self.unauth_style = unauth_style      # 'fault'(HTTP 400 + NotAuthorized) | 'http'(HTTP 401)
        self.lock_after = lock_after
        self.clock_skew = clock_skew
        self.stale_after = stale_after
        self.anonymous = anonymous            # 인증 없이 다 받는 카메라
        self.limit = False
        self.override = None                  # 'empty' | 'garbage' | ('status', int) | 'drop'
        self.embed_creds_in_uri = False
        self.lock = threading.Lock()
        self.auth_log = []                    # 자격 증명이 실린 요청 하나당 {'ok','scheme','op'}
        self.request_log = []                 # 모든 요청 {'op','path','cred','ok'}
        self.wrong_count = 0
        self.locked = False
        self._nonces = {}
        self.ops_seen = []
        self.wire = []                        # 받은 요청 원문 + 헤더 (비밀 비노출 시험용)
        self._httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self._httpd.mock = self
        self.port = self._httpd.server_address[1]
        self._t = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._httpd.shutdown()
        self._httpd.server_close()

    # -- 시험이 보는 값 ---------------------------------------------------
    def credentialed_attempts(self):
        return len(self.auth_log)

    def wrong_attempts(self):
        return sum(1 for a in self.auth_log if not a['ok'])

    def camera_time(self):
        return time.time() + self.clock_skew

    # -- 인증 -------------------------------------------------------------
    def _check_wsse(self, root):
        tok = S.first(root, 'UsernameToken')
        if tok is None:
            return None            # 자격 증명 없음
        user = S.text_of(tok, 'Username')
        pw = S.first(tok, 'Password')
        nonce = S.text_of(tok, 'Nonce')
        created = S.text_of(tok, 'Created')
        try:
            nonce_raw = base64.b64decode(nonce)
            ts = datetime.strptime(created, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
        except Exception:  # noqa: BLE001
            return False
        if abs(ts - self.camera_time()) > 300:
            return False
        want = base64.b64encode(hashlib.sha1(nonce_raw + created.encode() + self.password.encode())
                                .digest()).decode()
        return user == self.username and pw is not None and (pw.text or '').strip() == want

    def _check_digest(self, hdr, path):
        auth = hdr.get('Authorization') or hdr.get('authorization')
        if not auth:
            return None
        p = dict(re.findall(r'(\w+)="([^"]*)"', auth))
        for k, v in re.findall(r'(\w+)=([^",\s]+)', auth):
            p.setdefault(k, v)
        nonce = p.get('nonce')
        if nonce not in self._nonces:
            return 'stale'
        self._nonces[nonce] += 1
        if self.stale_after and self._nonces[nonce] > self.stale_after:
            del self._nonces[nonce]
            return 'stale'
        ha1 = hashlib.md5(('%s:%s:%s' % (self.username, REALM, self.password)).encode()).hexdigest()
        ha2 = hashlib.md5(('POST:%s' % p.get('uri', '')).encode()).hexdigest()
        if p.get('qop') == 'auth':
            want = hashlib.md5(('%s:%s:%s:%s:auth:%s' % (ha1, nonce, p.get('nc'), p.get('cnonce'), ha2))
                               .encode()).hexdigest()
        else:
            want = hashlib.md5(('%s:%s:%s' % (ha1, nonce, ha2)).encode()).hexdigest()
        return p.get('username') == self.username and p.get('response') == want \
            and p.get('uri') == path

    def _challenge(self, stale=False):
        nonce = secrets.token_hex(12)
        self._nonces[nonce] = 0
        return {'WWW-Authenticate': 'Digest realm="%s", qop="auth", algorithm=MD5, nonce="%s"%s'
                % (REALM, nonce, ', stale=true' if stale else '')}

    # -- 처리 -------------------------------------------------------------
    def handle(self, path, raw, hdr):
        with self.lock:
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                return 400, {}, fault('ter:InvalidArgVal', 'bad xml')
            body = S.first(root, 'Body')
            kids = list(body) if body is not None else []
            op = S.local(kids[0].tag) if kids else ''
            self.ops_seen.append(op)
            self.wire.append(raw.decode('utf-8', 'replace') + str(hdr))
            if self.override == 'drop':
                return 200, {}, b''
            if self.override == 'empty':
                return 200, {}, b''
            if self.override == 'garbage':
                return 200, {}, b'<<<not xml'
            if isinstance(self.override, tuple) and self.override[0] == 'status':
                return self.override[1], {}, b''
            if self.limit:
                return 503, {}, b''
            cred = None
            if self.auth == 'wsse':
                cred = self._check_wsse(root)
            else:
                cred = self._check_digest(hdr, path)
            entry = {'op': op, 'path': path, 'cred': cred is not None, 'ok': bool(cred) and cred != 'stale'}
            self.request_log.append(entry)
            anon_ok = op == 'GetSystemDateAndTime' or self.anonymous
            if cred is None:
                if anon_ok:
                    return 200, {}, self._respond(op, kids[0] if kids else None, path)
                return self._deny()
            if cred == 'stale':
                return 401, self._challenge(stale=True), b''
            self.auth_log.append({'ok': bool(cred), 'scheme': self.auth, 'op': op})
            if self.locked:
                return 400, {}, fault('ter:NotAuthorized', 'Account locked out')
            if not cred:
                self.wrong_count += 1
                if self.lock_after and self.wrong_count >= self.lock_after:
                    self.locked = True
                return self._deny()
            return 200, {}, self._respond(op, kids[0] if kids else None, path)

    def _deny(self):
        if self.auth == 'digest':
            return 401, self._challenge(), b''
        if self.unauth_style == 'http':
            return 401, {}, b''
        return 400, {}, fault('ter:NotAuthorized', 'Sender not authorized')

    def _xaddr(self, key):
        return 'http://%s:80%s' % (FAKE_HOST, _PATHS[key])

    def _respond(self, op, el, path):
        c = self.cfg
        if op == 'GetSystemDateAndTime':
            t = datetime.fromtimestamp(self.camera_time(), tz=timezone.utc)
            return _env('<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime>'
                        '<tt:DateTimeType>NTP</tt:DateTimeType><tt:DaylightSavings>false</tt:DaylightSavings>'
                        '<tt:UTCDateTime><tt:Time><tt:Hour>%d</tt:Hour><tt:Minute>%d</tt:Minute>'
                        '<tt:Second>%d</tt:Second></tt:Time><tt:Date><tt:Year>%d</tt:Year>'
                        '<tt:Month>%d</tt:Month><tt:Day>%d</tt:Day></tt:Date></tt:UTCDateTime>'
                        '</tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>'
                        % (t.hour, t.minute, t.second, t.year, t.month, t.day))
        if op == 'GetDeviceInformation':
            return _env('<tds:GetDeviceInformationResponse><tds:Manufacturer>MockCam</tds:Manufacturer>'
                        '<tds:Model>MC-100</tds:Model><tds:FirmwareVersion>1.2.3</tds:FirmwareVersion>'
                        '<tds:SerialNumber>SN0001</tds:SerialNumber><tds:HardwareId>HW1</tds:HardwareId>'
                        '</tds:GetDeviceInformationResponse>')
        if op == 'GetServices':
            items = ''.join('<tds:Service><tds:Namespace>%s</tds:Namespace><tds:XAddr>%s</tds:XAddr>'
                            '<tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version>'
                            '</tds:Service>' % (_TNS[k], self._xaddr(k)) for k in c['services'])
            return _env('<tds:GetServicesResponse>%s</tds:GetServicesResponse>' % items)
        if op == 'GetCapabilities':
            return _env('<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Media><tt:XAddr>%s</tt:XAddr>'
                        '</tt:Media></tds:Capabilities></tds:GetCapabilitiesResponse>' % self._xaddr('media'))
        if op == 'GetProfiles':
            def prof(tok, name, w, h, enc):
                ptz = ('<tt:PTZConfiguration token="ptzc1"><tt:Name>ptz</tt:Name></tt:PTZConfiguration>'
                       if 'ptz' in c['services'] else '')
                return ('<trt:Profiles token="%s" fixed="true"><tt:Name>%s</tt:Name>'
                        '<tt:VideoSourceConfiguration token="vsc1"><tt:Name>v</tt:Name>'
                        '<tt:SourceToken>vs1</tt:SourceToken></tt:VideoSourceConfiguration>'
                        '<tt:VideoEncoderConfiguration token="vec_%s"><tt:Name>e</tt:Name>'
                        '<tt:Encoding>%s</tt:Encoding><tt:Resolution><tt:Width>%d</tt:Width>'
                        '<tt:Height>%d</tt:Height></tt:Resolution></tt:VideoEncoderConfiguration>%s'
                        '</trt:Profiles>' % (tok, name, tok, enc, w, h, ptz))
            return _env('<trt:GetProfilesResponse>%s%s</trt:GetProfilesResponse>'
                        % (prof('sub', 'SubStream', 640, 360, 'H264'),
                           prof('main', 'MainStream', 1920, 1080, 'H265')))
        if op == 'GetStreamUri':
            tok = S.text_of(el, 'ProfileToken')
            userinfo = '%s:%s@' % (self.username, self.password) if self.embed_creds_in_uri else ''
            return _env('<trt:GetStreamUriResponse><trt:MediaUri><tt:Uri>rtsp://%s%s:554/stream/%s</tt:Uri>'
                        '</trt:MediaUri></trt:GetStreamUriResponse>' % (userinfo, FAKE_HOST, tok))
        if op == 'GetNodes':
            sp = ''
            if c['pan_tilt']:
                sp += ('<tt:ContinuousPanTiltVelocitySpace><tt:URI>x</tt:URI></tt:ContinuousPanTiltVelocitySpace>')
            if c['zoom']:
                sp += '<tt:ContinuousZoomVelocitySpace><tt:URI>x</tt:URI></tt:ContinuousZoomVelocitySpace>'
            return _env('<tptz:GetNodesResponse><tptz:PTZNode token="n1"><tt:Name>n</tt:Name>'
                        '<tt:SupportedPTZSpaces>%s</tt:SupportedPTZSpaces>'
                        '<tt:MaximumNumberOfPresets>%d</tt:MaximumNumberOfPresets>'
                        '<tt:HomeSupported>true</tt:HomeSupported></tptz:PTZNode></tptz:GetNodesResponse>'
                        % (sp, c['presets']))
        if op == 'GetOptions':
            modes = ''.join('<tt:IrCutFilterModes>%s</tt:IrCutFilterModes>' % m for m in c['ircut'])
            return _env('<timg:GetOptionsResponse><timg:ImagingOptions>%s</timg:ImagingOptions>'
                        '</timg:GetOptionsResponse>' % modes)
        if op == 'GetStorageConfigurations':
            if not c['storage']:
                return fault('ter:ActionNotSupported', 'no storage')
            return _env('<tds:GetStorageConfigurationsResponse><tds:StorageConfigurations token="sd1">'
                        '<tds:Data type="LocalStorage"><tds:LocalPath>/sd</tds:LocalPath></tds:Data>'
                        '</tds:StorageConfigurations></tds:GetStorageConfigurationsResponse>')
        if op == 'GetEventProperties':
            return _env('<tev:GetEventPropertiesResponse><wsnt:FixedTopicSet>true</wsnt:FixedTopicSet>'
                        '<wstop:TopicSet>%s</wstop:TopicSet></tev:GetEventPropertiesResponse>'
                        % _topic_tree(c['topics'] or []))
        return fault('ter:ActionNotSupported', 'unknown op %s' % op)
