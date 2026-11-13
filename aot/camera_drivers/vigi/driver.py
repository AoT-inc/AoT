# coding=utf-8
"""VigiDriver — 설계 §3.1. P2 범위: 연결 확인·능력·기기 정보·스트림 목록. 제어(PTZ·프리셋·주야·경보)는 P3.

제어 op 는 전부 `api.call` 로만 보낸다(stok·재인증·래치는 거기서 처리). 판정은 error_code 0 뿐이다.
요청 인자 철자(pan/tilt/zoom/speed, id/name, mode, action)는 실카메라 확인(V 항목) 전까지 [미확인] 이다.
모든 호출 전에 능력을 보고, 없는 기능은 카메라에 보내지 않고 unsupported 를 돌려준다."""
from aot.camera_drivers import register_driver
from aot.camera_drivers import capabilities as C
from aot.camera_drivers.driver import CameraDriver, CamResult, Credential
from aot.camera_drivers.vigi import capability_map, streams
from aot.camera_drivers.vigi.openapi import DEFAULT_PORT, VigiOpenApi


class VigiDriver(CameraDriver):
    vendor = 'vigi'

    def __init__(self, host, credential: Credential, *, camera_id, guard, fp_key,
                 openapi_port=DEFAULT_PORT, rtsp_port=554, tls_pin=None, transport=None, timeout=5.0):
        self.host = host
        self.rtsp_port = rtsp_port
        kw = {'transport': transport} if transport else {}
        self.api = VigiOpenApi(host, credential, camera_id=camera_id, guard=guard, fp_key=fp_key,
                               port=openapi_port, tls_pin=tls_pin, timeout=timeout, **kw)
        self._caps = None

    @property
    def observed_pin(self):
        return self.api.observed_pin

    def verify(self, credential=None, reuse=False) -> CamResult:
        """reuse=True 면 살아 있는 세션을 다시 쓰고, 없을 때만 인증한다."""
        return self.api.ensure_session() if reuse else self.api.connect()

    def device_info(self) -> CamResult:
        return self.api.call('getDeviceInfo')

    def capabilities(self, refresh=False):
        """Capabilities 를 협상한다. 실패하면 None (사유는 last_negotiation)."""
        if self._caps is None or refresh:
            r = capability_map.negotiate(self.api.call)
            self.last_negotiation = r
            self._caps = r.data if r.accepted else None
        return self._caps

    # -- 제어 (P3) ------------------------------------------------------
    def _need(self, *features):
        """능력이 없으면 unsupported CamResult, 있으면 None. 능력을 모르면(None) 시도하지 않는다."""
        caps = self.capabilities()
        if caps is None:
            return CamResult.unverified('capabilities unknown; run capability read first')
        for f in features:
            if not caps.has(f):
                return CamResult.unsupported(f)
        return None

    def ptz_move(self, vector, speed=None) -> CamResult:
        """연속 이동. vector=(pan, tilt, zoom) 각 -1/0/1. 멈추려면 ptz_stop."""
        try:
            pan, tilt, zoom = (int(v) for v in vector)
        except (TypeError, ValueError):
            return CamResult.refused('bad vector')
        if any(v not in (-1, 0, 1) for v in (pan, tilt, zoom)) or not (pan or tilt or zoom):
            return CamResult.refused('bad vector')
        need = []
        if pan or tilt:
            need.append(C.PTZ_PAN_TILT)
        if zoom:
            need.append(C.PTZ_ZOOM)
        bad = self._need(*need)
        if bad:
            return bad
        params = {'pan': pan, 'tilt': tilt, 'zoom': zoom}
        if speed is not None:
            top = self.capabilities().attr('speed_max')
            sp = max(1, int(speed))
            params['speed'] = min(sp, int(top)) if top else sp
        return self.api.call('cruiseMove', params)

    def ptz_stop(self) -> CamResult:
        """정지는 능력 확인에 막히지 않는다(멈추는 것은 항상 시도) — 단 카메라에 PTZ 가 없으면 보낼 곳이 없다."""
        return self.api.call('stopMove', {})

    def _preset_id(self, preset):
        try:
            n = int(preset)
        except (TypeError, ValueError):
            return None
        return n if 1 <= n <= capability_map.PTZ_PRESET_MAX else None

    def ptz_goto(self, preset) -> CamResult:
        n = self._preset_id(preset)
        if n is None:
            return CamResult.refused('preset must be 1..%d' % capability_map.PTZ_PRESET_MAX)
        bad = self._need(C.PTZ_PRESET)
        return bad or self.api.call('gotoPresetPoint', {'id': n})

    def ptz_set_preset(self, preset, name='') -> CamResult:
        n = self._preset_id(preset)
        if n is None:
            return CamResult.refused('preset must be 1..%d' % capability_map.PTZ_PRESET_MAX)
        bad = self._need(C.PTZ_PRESET)
        return bad or self.api.call('setPresetPoint', {'id': n, 'name': str(name or '')[:32]})

    def ptz_remove_preset(self, preset) -> CamResult:
        n = self._preset_id(preset)
        if n is None:
            return CamResult.refused('preset must be 1..%d' % capability_map.PTZ_PRESET_MAX)
        bad = self._need(C.PTZ_PRESET)
        return bad or self.api.call('removePresetPoint', {'id': n})

    def get_day_night(self) -> CamResult:
        bad = self._need(C.DAY_NIGHT)
        return bad or self.api.call('getDayNightMode')

    DAY_NIGHT_MODES = ('auto', 'day', 'night')

    def set_day_night(self, mode) -> CamResult:
        if mode not in self.DAY_NIGHT_MODES:
            return CamResult.refused('bad mode')
        bad = self._need(C.DAY_NIGHT)
        return bad or self.api.call('setDayNightMode', {'mode': mode})

    def manual_alarm(self, start: bool) -> CamResult:
        bad = self._need(C.ALARM_MANUAL)
        return bad or self.api.call('manualAlarm', {'action': 'start' if start else 'stop'})

    def enable_msg_push(self, kind) -> CamResult:
        """그 감지의 msg_push_enabled 하나만 켠다(설계 §9.2-5). 읽기 → 그 필드만 바꿔 쓰기 → 다시 읽어 확인.
        감지 자체가 꺼져 있으면 쓰지 않고 refused. 응답 구조(`result` 안의 감지 이름 키)는 [미확인]."""
        module = next((m for m, k in capability_map.MODULE_EVENT_KIND.items() if k == kind), None)
        if module is None:
            return CamResult.refused('unknown kind')
        bad = self._need(C.event_cap(kind))
        if bad:
            return bad
        got = self.api.call('get%sSwitch' % module)
        if not got.accepted:
            return got
        cur = got.data if isinstance(got.data, dict) else {}
        if not cur.get('enabled'):
            return CamResult.refused('detection is off on the camera')
        if cur.get('msg_push_enabled'):
            return got
        new = dict(cur, msg_push_enabled=True)
        put = self.api.call('set%sSwitch' % module, new)
        if not put.accepted:
            return put
        back = self.api.call('get%sSwitch' % module)
        if back.accepted and isinstance(back.data, dict) and back.data.get('msg_push_enabled'):
            return back
        return CamResult.unverified('msg_push_enabled not confirmed after write')

    def get_event_switches(self) -> CamResult:
        """지원하는 감지마다 카메라의 get…Switch 를 읽어 {kind: {enabled, msg_push_enabled}} 로 돌려준다.
        읽기뿐이다. 읽지 못한 종류는 빠진다(모름 ≠ 꺼짐)."""
        caps = self.capabilities()
        if caps is None:
            return CamResult.unverified('capabilities unknown; run capability read first')
        out = {}
        for module, kind in capability_map.MODULE_EVENT_KIND.items():
            if not caps.has(C.event_cap(kind)):
                continue
            r = self.api.call('get%sSwitch' % module)
            if not r.accepted:
                if r.error_class.value in ('auth_failed', 'locked', 'cert_changed', 'client_limit'):
                    return r
                continue
            d = r.data if isinstance(r.data, dict) else {}
            out[kind] = {'enabled': bool(d.get('enabled')),
                         'msg_push_enabled': bool(d.get('msg_push_enabled'))}
        return CamResult.ok(out)

    def stream_profiles(self):
        return streams.profiles(self.host, self.rtsp_port)

    def close(self):
        self.api.close()


register_driver('vigi', VigiDriver)
