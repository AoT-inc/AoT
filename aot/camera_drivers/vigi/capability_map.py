# coding=utf-8
"""getModuleList·get*Capability → 능력 어휘. 설계 §3.2.

제품별 하드코딩 표가 아니라 런타임 능력 질의의 결과로 만든다. 실카메라 확인(V4)으로
확정할 값(이벤트 type 철자, 응답 필드 이름)은 이 파일에 모은다. 모르는 값은
버리지 않고 안전한 쪽(기록만)으로 처리한다.
"""
import re

from aot.camera_drivers import capabilities as C
from aot.camera_drivers.capabilities import Capabilities
from aot.camera_drivers.driver import CamResult

# 모듈 이름 → 능력(들). [문서] getModuleList 목록.
MODULE_FEATURES = {
    'ptz': (C.PTZ_PAN_TILT, C.PTZ_PRESET),
    'ptz_zoom': (C.PTZ_ZOOM,),
    'dayNightMode': (C.DAY_NIGHT,),
    'sound_alarm_enabled': (C.ALARM_SOUND,),
    'light_alarm_enabled': (C.ALARM_LIGHT,),
    'manualAlarm': (C.ALARM_MANUAL,),
    'audio_speaker': (C.AUDIO_SPEAKER,),
    'audio_microphone': (C.AUDIO_MIC,),
    'sdCard': (C.STORAGE_SD,),
    'msgPush': (C.EVENTS_PUSH,),
    'playback': (C.RECORD_PLAYBACK,),
    'download': (C.RECORD_DOWNLOAD,),
}

# 감지 모듈 이름 → 중립 이벤트 종류
MODULE_EVENT_KIND = {
    'motionDetection': 'motion',
    'CrossLineDetection': 'crossline',
    'InvasionDetection': 'intrusion',
    'AreaEntryDetection': 'area_entry',
    'AreaLeaveDetection': 'area_leave',
    'PeopleDetection': 'people',
    'VehicleDetection': 'vehicle',
    'DropAndTakeDetection': 'drop_take',
    'LoiterDetection': 'loiter',
    'tamperDetection': 'tamper',
    'SceneChangeDetection': 'scene_change',
    'AudioAnomalyDetection': 'audio_anomaly',
}

PTZ_PRESET_MAX = 8  # [문서] API 는 프리셋 id 1~8

# subscribeMsg 의 event_type 철자. "TamperDetection" 한 건만 문서 예시로 확인했다.
# 나머지는 [미확인] — 모듈 이름과 같은 꼴일 것으로 가정하고 대소문자·밑줄을 무시한다(V4 에서 확정).
_EVENT_TYPE_TABLE = {k.lower().replace('_', ''): v for k, v in MODULE_EVENT_KIND.items()}


def normalize_event_type(raw):
    """event_type 문자열 → (kind, enhanced). 모르는 값은 ('unknown', '')."""
    if not raw or not isinstance(raw, str):
        return C.UNKNOWN_KIND, ''
    s = raw.strip()
    enhanced = ''
    # [미확인] 강화 이벤트는 "xxx_yyy_enhance" 꼴. yyy 가 people/vehicle 인 경우만 해석한다.
    m = re.match(r'^(.+)_(people|vehicle)_enhance$', s, re.IGNORECASE)
    if m:
        s, enhanced = m.group(1), m.group(2).lower()
        if not s.lower().endswith('detection'):
            s += 'Detection'
    key = s.lower().replace('_', '')
    kind = _EVENT_TYPE_TABLE.get(key)
    if kind is None:
        return C.UNKNOWN_KIND, ''
    return kind, enhanced


def _first(d, *keys):
    if isinstance(d, dict):
        for k in keys:
            if k in d:
                return d[k]
    return None


def parse_module_list(result):
    """getModuleList result → 모듈 이름 집합. 응답 필드 이름이 [미확인]이라 관대하게 읽는다."""
    items = None
    if isinstance(result, dict):
        items = _first(result, 'module_list', 'module_spec', 'modules')
        if items is None:
            for v in result.values():
                if isinstance(v, (list, dict)):
                    items = v
                    break
    elif isinstance(result, list):
        items = result
    names = set()
    if isinstance(items, dict):
        names.update(str(k) for k in items)
    elif isinstance(items, list):
        for it in items:
            if isinstance(it, str):
                names.add(it)
            elif isinstance(it, dict) and 'name' in it:
                names.add(str(it['name']))
    return names


def _find_int(d, *keys):
    v = _first(d, *keys)
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return None


def build_capabilities(modules, ptz_cap=None, enhance_cap=None):
    features, attrs = set(), {}
    for m in modules:
        for f in MODULE_FEATURES.get(m, ()):
            features.add(f)
        kind = MODULE_EVENT_KIND.get(m)
        if kind:
            features.add(C.event_cap(kind))
    # [미확인] manualAlarm 은 getModuleList 목록에 없다. 소리/빛 경보 모듈이 있으면 수동 경보도 있다고 본다.
    if C.ALARM_SOUND in features or C.ALARM_LIGHT in features:
        features.add(C.ALARM_MANUAL)
    if C.PTZ_PRESET in features:
        attrs['ptz.preset_max'] = PTZ_PRESET_MAX
    speed = _find_int(ptz_cap, 'speed_max', 'max_speed', 'maxSpeed')
    if speed is not None and C.PTZ_PAN_TILT in features:
        attrs['ptz.speed_max'] = speed
    mask = _find_int(enhance_cap, 'mask', 'capability', 'enhance_capability', 'value')
    if mask is not None:
        if mask & 1:
            features.add(C.ENHANCE_PEOPLE)
        if mask & 2:
            features.add(C.ENHANCE_VEHICLE)
    return Capabilities(features, attrs)


def negotiate(call) -> CamResult:
    """`call(method, params=None) -> CamResult` 로 능력을 협상한다.

    getModuleList 가 실패하면 그 결과를 그대로 돌려준다. 이어지는 질의는 모듈이 있을 때만 부르고,
    실패해도 읽은 만큼으로 Capabilities 를 만든다('partial' 에 실패한 메서드를 적는다)."""
    r = call('getModuleList')
    if not r.accepted:
        return r
    modules = parse_module_list(r.data)
    optional = {}
    partial = []
    wanted = (('ptz', 'getPTZCapability'), ('audio_speaker', 'getAudioCapability'),
              ('audio_microphone', 'getAudioCapability'), ('video', 'getVideoCapability'),
              ('PeopleDetection', 'getEventEnhanceCapability'),
              ('VehicleDetection', 'getEventEnhanceCapability'))
    seen = set()
    for module, method in wanted:
        if module in modules and method not in seen:
            seen.add(method)
            rr = call(method)
            if rr.accepted:
                optional[method] = rr.data
            else:
                partial.append(method)
                if rr.error_class.value in ('auth_failed', 'locked', 'cert_changed'):
                    break  # 래치가 걸렸다. 더 부르지 않는다
    caps = build_capabilities(modules, optional.get('getPTZCapability'),
                              optional.get('getEventEnhanceCapability'))
    if partial:
        caps.attrs['partial'] = partial
    return CamResult.ok(caps)


# -- subscribeMsg 본문 해석 (P4) ----------------------------------------------
# 본문의 정확한 모양은 [미확인](V4). `event_type`/`time` 키를 중첩 어디에 있든 찾는다.
# 하트비트는 {"Heartbeat": "30"} 이다 [문서].
_TIME_KEYS = ('time', 'timestamp', 'event_time', 'utc_time')


def _deep_find(obj, keys, depth=0):
    if depth > 4:
        return None
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and not isinstance(obj[k], (dict, list)):
                return obj[k]
        for v in obj.values():
            r = _deep_find(v, keys, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _deep_find(v, keys, depth + 1)
            if r is not None:
                return r
    return None


def parse_event_part(obj):
    """multipart 한 조각(JSON dict) → ('heartbeat', None) | ('event', dict) | ('ignore', None).

    event dict: kind·enhanced·raw_type·camera_epoch(int|None). 모르는 event_type 은 kind='unknown'
    으로 돌려준다(버리지 않는다)."""
    if not isinstance(obj, dict):
        return 'ignore', None
    if 'Heartbeat' in obj or 'heartbeat' in obj:
        return 'heartbeat', None
    raw = _deep_find(obj, ('event_type', 'eventType', 'type'))
    if raw is None:
        return 'ignore', None
    kind, enhanced = normalize_event_type(raw)
    epoch = _deep_find(obj, _TIME_KEYS)
    try:
        epoch = int(float(epoch)) if epoch is not None and not isinstance(epoch, bool) else None
    except (TypeError, ValueError):
        epoch = None
    return 'event', {'kind': kind, 'enhanced': enhanced, 'raw_type': str(raw)[:64],
                     'camera_epoch': epoch}
