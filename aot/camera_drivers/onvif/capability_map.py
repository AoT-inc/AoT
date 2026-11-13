# coding=utf-8
"""ONVIF 서비스·프로필·토픽 → 중립 능력 어휘. 범위 문서 §3, 설계 §3.2.

제품별 하드코딩이 아니라 런타임 질의(GetServices·GetProfiles·GetNodes·GetOptions·GetEventProperties)의
결과로 만든다. 토픽 철자는 모의 서버 기준이며 실카메라 확인(O6)에서 이 파일 한 곳을 고친다.
모르는 토픽은 버리지 않고 kind='unknown' + 원문으로 돌려준다(트리거는 안 보낸다).
"""
import re

from aot.camera_drivers import capabilities as C
from aot.camera_drivers.capabilities import Capabilities
from aot.camera_drivers.driver import CamResult, ErrorClass
from aot.camera_drivers.onvif import soap as S

_AUTH_CLASSES = (ErrorClass.AUTH_FAILED, ErrorClass.LOCKED, ErrorClass.CERT_CHANGED,
                 ErrorClass.CLIENT_LIMIT)

# 위에서부터 첫 일치. 대소문자·접두사(tns1:, tnsaxis: 등) 무시, '/' 로 이은 경로에 정규식 검색.
_TOPIC_RULES = (
    ('tamper', re.compile(r'tamper')),
    ('scene_change', re.compile(r'(global)?scenechange')),
    ('crossline', re.compile(r'linedetector|linecross|crossline')),
    ('intrusion', re.compile(r'fielddetector|intrusion|objectsinside')),
    ('loiter', re.compile(r'loiter')),
    ('drop_take', re.compile(r'abandoned|objectleft|objectremoved|removedobject|droptake')),
    ('people', re.compile(r'people|human|person')),
    ('vehicle', re.compile(r'vehicle')),
    ('audio_anomaly', re.compile(r'audioanalytics|detectedsound')),
    ('motion', re.compile(r'motion')),
)
_WSTOP_TOPIC = '{http://docs.oasis-open.org/wsn/t-1}topic'


def normalize_topic(topic):
    """토픽 경로 문자열 → 중립 kind. 모르면 'unknown'."""
    if not topic or not isinstance(topic, str):
        return C.UNKNOWN_KIND
    path = '/'.join(p.rsplit(':', 1)[-1] for p in topic.split('/')).lower()
    for kind, rx in _TOPIC_RULES:
        if rx.search(path):
            return kind
    return C.UNKNOWN_KIND


def parse_topic_set(root):
    """GetEventPropertiesResponse → 리프 토픽 경로 목록. TopicSet 중첩이 곧 경로다."""
    ts = S.first(root, 'TopicSet')
    out = []

    def walk(el, path):
        for ch in el:
            p = path + [S.local(ch.tag)]
            if ch.get(_WSTOP_TOPIC, '').lower() == 'true':
                out.append('/'.join(p))
            walk(ch, p)

    if ts is not None:
        walk(ts, [])
    return out


def parse_services(root):
    """GetServicesResponse / GetCapabilitiesResponse → {service_key: xaddr}."""
    out = {}
    for svc in S.descendants(root, 'Service'):
        key = S.NS_TO_SERVICE.get(S.text_of(svc, 'Namespace'))
        xaddr = S.text_of(svc, 'XAddr')
        if key and xaddr:
            out[key] = xaddr
    if not out:   # GetCapabilities 형: <Capabilities><Media><XAddr/></Media>…
        for tag, key in (('Media', 'media'), ('PTZ', 'ptz'), ('Imaging', 'imaging'),
                         ('Events', 'events')):
            el = S.first(root, tag)
            xaddr = S.text_of(el, 'XAddr') if el is not None else ''
            if xaddr:
                out[key] = xaddr
        dev = S.first(root, 'Device')
        if dev is not None and S.text_of(dev, 'XAddr'):
            out['device'] = S.text_of(dev, 'XAddr')
    return out


def parse_profiles(root):
    """GetProfilesResponse → [{token, name, video_source, ptz, codec, width, height}]."""
    out = []
    for p in S.descendants(root, 'Profiles'):
        token = p.get('token')
        if not token:
            continue
        enc = S.first(p, 'VideoEncoderConfiguration')
        try:
            w = int(S.text_of(enc, 'Width', '0')) if enc is not None else 0
            h = int(S.text_of(enc, 'Height', '0')) if enc is not None else 0
        except ValueError:
            w = h = 0
        out.append({'token': token, 'name': S.text_of(p, 'Name') or token,
                    'video_source': S.text_of(S.first(p, 'VideoSourceConfiguration'), 'SourceToken')
                    if S.first(p, 'VideoSourceConfiguration') is not None else '',
                    'ptz': S.first(p, 'PTZConfiguration') is not None,
                    'codec': (S.text_of(enc, 'Encoding') if enc is not None else '').lower(),
                    'width': w, 'height': h})
    return out


def parse_ptz_nodes(root):
    """GetNodesResponse → (pan_tilt, zoom, preset_max)."""
    pan_tilt = zoom = False
    presets = 0
    for n in S.descendants(root, 'PTZNode'):
        if S.first(n, 'ContinuousPanTiltVelocitySpace') is not None:
            pan_tilt = True
        if S.first(n, 'ContinuousZoomVelocitySpace') is not None:
            zoom = True
        try:
            presets = max(presets, int(S.text_of(n, 'MaximumNumberOfPresets', '0')))
        except ValueError:
            pass
    return pan_tilt, zoom, presets


def parse_ircut_modes(root):
    return {(e.text or '').strip().upper() for e in S.descendants(root, 'IrCutFilterModes')}


def build_capabilities(*, services, profiles, ptz=None, ircut=None, storage=False, topics=None):
    """모은 사실 → Capabilities. 인자가 None 이면 그 질의를 못 했거나 서비스가 없다는 뜻이다."""
    features, attrs = set(), {}
    if ptz and any(p['ptz'] for p in profiles):
        pan_tilt, zoom, presets = ptz
        if pan_tilt:
            features.add(C.PTZ_PAN_TILT)
        if zoom:
            features.add(C.PTZ_ZOOM)
        if presets > 0:
            features.add(C.PTZ_PRESET)
            attrs['ptz.preset_max'] = presets
    if ircut and ircut & {'ON', 'OFF', 'AUTO'}:
        features.add(C.DAY_NIGHT)
    if storage:
        features.add(C.STORAGE_SD)
    if topics is not None:
        features.add(C.EVENTS_PUSH)
        for t in topics:
            k = normalize_topic(t)
            if k != C.UNKNOWN_KIND:
                features.add(C.event_cap(k))
    attrs['onvif.profiles'] = len(profiles)
    return Capabilities(features, attrs)


def negotiate(call, set_path=None) -> CamResult:
    """`call(service, op, inner='') -> CamResult(data=Element)` 로 능력을 협상한다.

    GetServices 가 실패하면(인증 계열이면) 그 결과를 그대로 돌려준다. 이어지는 질의는 서비스가 있을 때만
    부르고, 실패해도 읽은 만큼으로 만든다('partial' 에 실패한 작업을 적는다).
    성공 data 는 `Capabilities`. 프로필 목록까지 필요하면 `negotiate_full` 을 쓴다."""
    r, _profiles = negotiate_full(call, set_path)
    return r


def negotiate_full(call, set_path=None):
    """(CamResult(data=Capabilities), profiles). 실패하면 (실패 결과, [])."""
    r = call('device', 'GetServices', '<x:IncludeCapability>false</x:IncludeCapability>')
    if not r.accepted and r.error_class in _AUTH_CLASSES:
        return r, []
    if not r.accepted:
        r = call('device', 'GetCapabilities', '<x:Category>All</x:Category>')
        if not r.accepted:
            return r, []
    services = parse_services(r.data)
    if set_path:
        for key, xaddr in services.items():
            set_path(key, xaddr)
    partial = []

    def ask(service, op, inner=''):
        rr = call(service, op, inner)
        if not rr.accepted:
            if rr.error_class is not ErrorClass.UNSUPPORTED:   # 없는 기능은 '못 읽음'이 아니다
                partial.append('%s.%s' % (service, op))
            return None, rr
        return rr.data, rr

    profiles = []
    if 'media' in services:
        root, rr = ask('media', 'GetProfiles')
        if root is not None:
            profiles = parse_profiles(root)
        elif rr.error_class in _AUTH_CLASSES:
            return rr, []
    ptz = ircut = topics = None
    storage = False
    if 'ptz' in services and any(p['ptz'] for p in profiles):
        root, rr = ask('ptz', 'GetNodes')
        if root is not None:
            ptz = parse_ptz_nodes(root)
        elif rr.error_class in _AUTH_CLASSES:
            return rr, []
    src = next((p['video_source'] for p in profiles if p['video_source']), '')
    if 'imaging' in services and src:
        root, rr = ask('imaging', 'GetOptions', '<x:VideoSourceToken>%s</x:VideoSourceToken>' % S.q(src))
        if root is not None:
            ircut = parse_ircut_modes(root)
        elif rr.error_class in _AUTH_CLASSES:
            return rr, []
    root, rr = ask('device', 'GetStorageConfigurations')
    if root is not None:
        storage = bool(S.descendants(root, 'StorageConfigurations'))
    elif rr.error_class in _AUTH_CLASSES:
        return rr, []
    if 'events' in services:
        root, rr = ask('events', 'GetEventProperties')
        if root is not None:
            topics = parse_topic_set(root)
        elif rr.error_class in _AUTH_CLASSES:
            return rr, []
    caps = build_capabilities(services=services, profiles=profiles, ptz=ptz, ircut=ircut,
                              storage=storage, topics=topics)
    if partial:
        caps.attrs['partial'] = partial
    return CamResult.ok(caps, 0, S.IFACE), profiles
