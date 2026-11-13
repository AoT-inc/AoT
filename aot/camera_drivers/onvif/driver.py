# coding=utf-8
"""OnvifDriver — 범용 ONVIF(Profile S) 드라이버. 범위 문서 O1: 연결 확인·능력 협상·기기 정보·스트림 목록.

제어(PTZ·주야)는 O3, 이벤트 스트림은 O4 에서 채운다. 그때까지 베이스의 unsupported /
NotImplementedError 를 그대로 둔다. 요청은 전부 `OnvifSoap` 을 거친다(래치·재인증·비노출은 거기서).
`camera_driver.openapi_port` 칸은 ONVIF 서비스 포트로 재사용한다(D6a).
"""
from urllib.parse import urlsplit

from aot.camera_drivers import register_driver
from aot.camera_drivers.driver import CameraDriver, CamResult, Credential, StreamProfile
from aot.camera_drivers.onvif import capability_map
from aot.camera_drivers.onvif import soap as S
from aot.camera_drivers.onvif.soap import DEFAULT_PORT, OnvifSoap


def _rtsp_url_for(host, uri):
    """카메라가 준 스트림 URI 에서 자격 증명을 지우고 host 를 설정값으로 바꾼다(포트·경로는 유지)."""
    try:
        u = urlsplit(uri)
        port = u.port
    except ValueError:
        return ''
    if u.scheme not in ('rtsp', 'rtsps', 'http', 'https') or not u.hostname:
        return ''
    h = '[%s]' % host if ':' in host and not host.startswith('[') else host
    netloc = '%s:%d' % (h, port) if port else h
    return '%s://%s%s%s' % (u.scheme, netloc, u.path or '', ('?' + u.query) if u.query else '')


class OnvifDriver(CameraDriver):
    vendor = 'onvif'

    def __init__(self, host, credential: Credential, *, camera_id, guard, fp_key,
                 openapi_port=DEFAULT_PORT, rtsp_port=554, tls_pin=None, transport=None, timeout=5.0):
        self.host = host
        self.rtsp_port = rtsp_port      # 호환용 — 실제 RTSP 포트는 스트림 URI 가 정한다
        kw = {'transport': transport} if transport else {}
        self.api = OnvifSoap(host, credential, camera_id=camera_id, guard=guard, fp_key=fp_key,
                             port=openapi_port, timeout=timeout, **kw)
        self._caps = None
        self._profiles = []
        self.last_negotiation = None
        self.observed_pin = None        # 평문 HTTP — TLS 핀 없음

    def verify(self, credential=None, reuse=False) -> CamResult:
        """ONVIF 는 무상태라 세션이 없다. reuse 여도 연결 확인은 한 번의 인증 시도다."""
        return self.api.connect()

    def device_info(self) -> CamResult:
        r = self.api.call('device', 'GetDeviceInformation')
        if not r.accepted:
            return r
        keys = ('Manufacturer', 'Model', 'FirmwareVersion', 'SerialNumber', 'HardwareId')
        data = {k: S.text_of(r.data, k) for k in keys}
        # 화면(status.build_status)이 읽는 공통 키 — 제조사 중립 이름으로도 싣는다
        data.update(model=data['Model'], swVer=data['FirmwareVersion'], type=data['Manufacturer'])
        return CamResult.ok(data, 0, S.IFACE)

    def capabilities(self, refresh=False):
        if self._caps is None or refresh:
            r, profiles = capability_map.negotiate_full(self.api.call, self.api.set_service_path)
            self.last_negotiation = r
            self._caps = r.data if r.accepted else None
            self._profiles = profiles if r.accepted else []
        return self._caps

    def stream_profiles(self):
        """프로필마다 GetStreamUri 를 불러 StreamProfile 목록을 만든다. 못 얻으면 빈 목록."""
        if self.capabilities() is None:
            return []
        ranked = sorted(self._profiles, key=lambda p: -(p['width'] * p['height']))
        out = []
        for i, p in enumerate(ranked):
            inner = ('<x:StreamSetup><t:Stream xmlns:t="%s">RTP-Unicast</t:Stream>'
                     '<t:Transport xmlns:t="%s"><t:Protocol>RTSP</t:Protocol></t:Transport>'
                     '</x:StreamSetup><x:ProfileToken>%s</x:ProfileToken>'
                     % (S.NS_SCHEMA, S.NS_SCHEMA, S.q(p['token'])))
            r = self.api.call('media', 'GetStreamUri', inner)
            if not r.accepted:
                if r.error_class.value in ('auth_failed', 'locked', 'cert_changed', 'client_limit'):
                    break
                continue
            url = _rtsp_url_for(self.host, S.text_of(r.data, 'Uri'))
            if not url:
                continue
            name = 'main' if i == 0 else ('sub' if i == 1 else p['name'])
            out.append(StreamProfile(name, url, p['codec'], p['width'], p['height']))
        return out

    def snapshot_uri(self):
        """GetSnapshotUri(가장 큰 프로필). 지원하지 않거나 못 얻으면 ''. 자격 증명은 지워진 주소."""
        if self.capabilities() is None or not self._profiles:
            return ''
        p = max(self._profiles, key=lambda q: q['width'] * q['height'])
        r = self.api.call('media', 'GetSnapshotUri', '<x:ProfileToken>%s</x:ProfileToken>' % S.q(p['token']))
        if not r.accepted:
            return ''
        url = _rtsp_url_for(self.host, S.text_of(r.data, 'Uri'))
        return url if url.startswith('http://') else ''

    def close(self):
        self.api.close()


register_driver('onvif', OnvifDriver)
