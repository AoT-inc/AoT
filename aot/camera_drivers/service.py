# coding=utf-8
"""CameraDriverService — 데몬 쪽 서비스. 설계 §4. P2: 연결 확인·새로고침·재연결·인증서 신뢰·기능 다시 읽기.

Open API(인증·stok·능력)는 데몬만 다룬다. Flask 는 데몬 RPC 로 부탁한다. 반환값은 비밀이 없는
평범한 dict 다(RPC 직렬화 안전). 카메라마다 락 하나로 호출을 한 줄에 세운다.
"""
import logging
import threading

from aot.camera_drivers import auth_guard as AG
from aot.camera_drivers import secrets as S
from aot.camera_drivers.auth_guard import AuthGuard
from aot.camera_drivers.db_store import DbAuthStore
from aot.camera_drivers.driver import CamState, Credential, scrub
from aot.camera_drivers.onvif.driver import OnvifDriver
from aot.camera_drivers.vigi.driver import VigiDriver
from aot.camera_drivers.vigi.openapi import peer_pin
from aot.utils.timekit import naive_utc, utc_now

logger = logging.getLogger(__name__)


class CameraDriverService:
    #: PTZ 데드맨 — 이동 뒤 이 시간 안에 갱신·정지가 없으면 데몬이 stopMove 를 보낸다(설계 §9.3).
    DEADMAN_S = 2.0

    def __init__(self, store=None, transport=None, clock=utc_now, deadman_s=None):
        self.store = store or DbAuthStore()
        self.transport = transport
        self.clock = clock
        self.deadman_s = self.DEADMAN_S if deadman_s is None else deadman_s
        self._locks = {}
        self._glock = threading.Lock()
        self._ctl = {}        # camera_id -> 제어용 VigiDriver (stok 재사용; 설정이 바뀌면 버린다)
        self._dead = {}       # camera_id -> threading.Timer (데드맨)
        self.events_hub = None   # 데몬이 EventHub 를 붙인다(P4). 없으면 구독은 일어나지 않는다

    # -- 내부 -----------------------------------------------------------
    def _lock(self, cid):
        with self._glock:
            return self._locks.setdefault(cid, threading.RLock())

    @staticmethod
    def _scope():
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope
        return session_scope(AOT_DB_PATH)

    def _row(self, s, cid):
        from aot.databases.models import CameraDriver
        return s.query(CameraDriver).filter(CameraDriver.camera_id == cid).first()

    def _driver(self, cid):
        """DB 행에서 드라이버를 만든다. 비밀번호를 열 수 없으면 None 과 사유."""
        with self._scope() as s:
            r = self._row(s, cid)
            if r is None:
                return None, 'not_configured'
            cfg = dict(vendor=r.vendor, host=r.host, user=r.username, sealed=r.password_sealed,
                       oport=r.openapi_port, rport=r.rtsp_port, pin=r.tls_pin_sha256)
        if not cfg['host']:
            return None, 'no_host'
        pw, state = S.open_password(cfg['sealed'])
        if not pw:
            return None, 'no_password'
        guard = AuthGuard(self.store, self.clock)
        if cfg['vendor'] == 'onvif':     # openapi_port 는 ONVIF 서비스 포트로 재사용(D6a)
            return OnvifDriver(cfg['host'], Credential(cfg['user'], pw), camera_id=cid, guard=guard,
                               fp_key=S.fp_key(), openapi_port=cfg['oport'], rtsp_port=cfg['rport'],
                               transport=self.transport), None
        return VigiDriver(cfg['host'], Credential(cfg['user'], pw), camera_id=cid, guard=guard,
                          fp_key=S.fp_key(), openapi_port=cfg['oport'], rtsp_port=cfg['rport'],
                          tls_pin=cfg['pin'], transport=self.transport), None

    def status(self, cid):
        """화면용 상태. 비밀·지문 전체를 담지 않는다."""
        from aot.camera_drivers.status import build_status, recent_events
        with self._scope() as s:
            return build_status(self._row(s, cid), recent_events(s, cid))

    def _sync_events(self, cid, restart=False):
        """인증 상태가 바뀐 뒤(연결 확인·재연결·설정 저장) 구독을 조건에 맞춘다."""
        hub = self.events_hub
        if hub is None:
            return None
        try:
            return hub.ensure(cid, restart=restart)
        except Exception:
            logger.exception('camera events ensure failed')
            return None

    def events_refresh(self, cid):
        """이벤트 켜기/끄기·종류 저장 뒤 호출. 구독을 켜거나 끄고 상태를 돌려준다."""
        if self.events_hub is None:
            return {'ok': False, 'state': 'unsupported', 'reason': 'events_not_running'}
        self._sync_events(cid)
        return {'ok': True, 'state': 'accepted', **self._brief(cid)}

    def event_switches(self, cid):
        """카메라 쪽 감지별 켜짐·알림(msg_push) 상태를 읽는다(읽기 전용, 값을 바꾸지 않는다)."""
        with self._lock(cid):
            drv, why = self._ctl_driver(cid)
            if drv is None:
                return {'ok': False, 'state': 'unconfigured', 'reason': why}
            r = drv.get_event_switches()
            return self._res(r)

    # -- RPC 진입점 -------------------------------------------------------
    def refresh(self, cid):
        """설정이 저장된 뒤 호출. 제어용 드라이버 캐시를 버리고(주소·계정이 바뀌었을 수 있다) 상태를 돌려준다."""
        self._drop_ctl(cid)
        self._sync_events(cid, restart=True)
        return self.status(cid)

    def verify(self, cid):
        """연결 확인 — 사용자가 누를 때만. 시도는 AuthGuard 가 1회로 제한한다.
        카메라당 세션(stok)은 제어와 같은 것을 재사용한다 — 누를 때마다 새로 열면 카메라의
        클라이언트 수 제한(-10021)에 걸린다. 설정이 바뀌면 refresh() 가 세션을 버린다."""
        with self._lock(cid):
            drv, why = self._ctl_driver(cid)
            if drv is None:
                return {'ok': False, 'state': 'unconfigured', 'reason': why}
            try:
                r = drv.verify(reuse=True)
                if not r.accepted:
                    self._drop_ctl(cid)
                    return {'ok': False, 'state': r.state.value, 'reason': scrub(r.message),
                            'error_class': r.error_class.value, 'code': r.code,
                            'observed_pin': (drv.observed_pin or '')[:16],
                            **self._brief(cid)}
                self._tofu(cid, drv.observed_pin)
                info = drv.device_info()
                caps = drv.capabilities(refresh=True)
                self._save_result(cid, info.data if info.accepted else None, caps)
                self._sync_events(cid)
                return {'ok': True, 'state': 'accepted', **self._brief(cid)}
            except Exception:
                self._drop_ctl(cid)
                raise

    def reconnect(self, cid):
        """"다시 연결" — 래치를 풀고 시도 1회(새 세션으로)."""
        self._drop_ctl(cid)
        with self._lock(cid):
            self.store.clear_latch(cid)
        return self.verify(cid)

    def refresh_capabilities(self, cid):
        """"기능 다시 읽기" — 이미 검증된 자격 증명·세션으로만(재인증 규칙)."""
        with self._lock(cid):
            drv, why = self._ctl_driver(cid)
            if drv is None:
                return {'ok': False, 'state': 'unconfigured', 'reason': why}
            caps = drv.capabilities(refresh=True)
            if caps is None:
                r = drv.last_negotiation
                return {'ok': False, 'state': r.state.value, 'reason': scrub(r.message),
                        **self._brief(cid)}
            self._save_result(cid, None, caps)
            return {'ok': True, 'state': 'accepted', **self._brief(cid)}

    def observe_cert(self, cid):
        """인증서가 바뀐 카메라의 현재 지문(앞 16자)을 TLS 핸드셰이크만으로 본다."""
        with self._scope() as s:
            r = self._row(s, cid)
            if r is None:
                return {'ok': False}
            host, port, old = r.host, r.openapi_port, r.tls_pin_sha256 or ''
        new = peer_pin(host, port)
        return {'ok': bool(new), 'old': old[:16], 'new': (new or '')[:16]}

    def trust_new_cert(self, cid, expect_prefix):
        """사용자가 본 새 지문(앞 16자)과 지금 지문이 같을 때만 고정을 바꾸고 래치를 푼다."""
        with self._lock(cid):
            with self._scope() as s:
                r = self._row(s, cid)
                if r is None or r.auth_state != AG.CERT_CHANGED:
                    return {'ok': False, 'reason': 'not_cert_changed'}
                host, port = r.host, r.openapi_port
            new = peer_pin(host, port)
            if not new or not expect_prefix or not new.startswith(expect_prefix) \
                    or len(expect_prefix) < 16:
                return {'ok': False, 'reason': 'fingerprint_mismatch'}
            with self._scope() as s:
                r = self._row(s, cid)
                r.tls_pin_sha256 = new
            self.store.clear_latch(cid)
            return {'ok': True}

    #: RPC 로 부를 수 있는 연산(허용 목록). 모두 비밀 없는 dict 를 돌려준다.
    READ_OPS = ('status', 'refresh', 'verify', 'reconnect', 'refresh_capabilities', 'observe_cert',
                'trust_new_cert', 'events_refresh', 'event_switches')
    #: 카메라를 움직이거나 울리거나 설정을 쓰는 op. `check_scope_gates.DAEMON_CONTROL_CALLS` 의
    #: `camera_control_call` 로만 들어오며, 호출하는 Flask 뷰가 스코프를 먼저 묻는다.
    CONTROL_OPS = ('ptz_move', 'ptz_keepalive', 'ptz_stop', 'ptz_goto', 'ptz_set_preset',
                   'ptz_remove_preset', 'day_night_get', 'day_night_set', 'alarm', 'msg_push_on')
    OPS = READ_OPS + CONTROL_OPS

    def call(self, op, camera_id, arg=None, control=False):
        """control=False(camera_driver_call 경로)에서는 제어 op 를 거부한다 — 게이트 우회 방지."""
        if op not in self.OPS or (op in self.CONTROL_OPS) != bool(control):
            return {'ok': False, 'state': 'unsupported', 'reason': 'unknown_op'}
        try:
            if op in self.CONTROL_OPS:
                return self.control(op, camera_id, arg)
            fn = getattr(self, op)
            return fn(camera_id, arg) if op == 'trust_new_cert' else fn(camera_id)
        except Exception as err:   # 예외 문자열에 비밀이 섞이지 않게 형식만 돌려준다
            logger.error('camera_driver op=%s failed: %s', op, type(err).__name__)
            return {'ok': False, 'state': 'error', 'reason': type(err).__name__}

    # -- 제어 (P3) --------------------------------------------------------
    def _drop_ctl(self, cid):
        with self._glock:
            drv = self._ctl.pop(cid, None)
        if drv is not None:
            try:
                drv.close()
            except Exception:  # noqa: BLE001 — 닫기 실패는 무시(비밀 노출 방지)
                pass

    def _ctl_driver(self, cid):
        """제어용 드라이버(카메라당 하나, stok 재사용). 호출마다 새로 인증하면 클라이언트 수 제한(-10021)에 걸린다."""
        with self._glock:
            drv = self._ctl.get(cid)
        if drv is not None:
            return drv, None
        drv, why = self._driver(cid)
        if drv is not None:
            # 저장된 능력을 쓴다 — 제어 때마다 협상(getModuleList 등)을 다시 하지 않는다.
            # 다시 읽기는 사용자가 "기능 다시 읽기"를 누를 때뿐이다(설계 §3.2).
            with self._scope() as s:
                r = self._row(s, cid)
                saved = r.capabilities if r is not None else None
            if saved:
                from aot.camera_drivers.capabilities import Capabilities
                drv._caps = Capabilities.from_json(saved)
            with self._glock:
                self._ctl[cid] = drv
        return drv, why

    @staticmethod
    def _res(r):
        d = {'ok': r.accepted, 'state': r.state.value, 'error_class': r.error_class.value,
             'code': r.code, 'reason': scrub(r.message)}
        if r.accepted and isinstance(r.data, dict):
            d['data'] = r.data
        return d

    def _arm_deadman(self, cid):
        self._cancel_deadman(cid)
        t = threading.Timer(self.deadman_s, self._deadman_fire, args=(cid,))
        t.daemon = True
        with self._glock:
            self._dead[cid] = t
        t.start()

    def _cancel_deadman(self, cid):
        with self._glock:
            t = self._dead.pop(cid, None)
        if t is not None:
            t.cancel()

    def _deadman_fire(self, cid):
        with self._glock:
            if self._dead.get(cid) is not threading.current_thread():
                return      # 그 사이 갱신·정지로 교체됨
            self._dead.pop(cid, None)
        with self._lock(cid):
            drv, _ = self._ctl_driver(cid)
            if drv is not None:
                r = drv.ptz_stop()
                logger.warning('camera ptz deadman stop camera=%s state=%s', cid, r.state.value)

    def control(self, op, cid, arg=None):
        arg = arg if isinstance(arg, dict) else {}
        with self._lock(cid):
            drv, why = self._ctl_driver(cid)
            if drv is None:
                return {'ok': False, 'state': 'unconfigured', 'reason': why}
            if op == 'ptz_move':
                r = drv.ptz_move(arg.get('vector') or (), arg.get('speed'))
                if r.accepted:
                    self._arm_deadman(cid)
                return self._res(r)
            if op == 'ptz_keepalive':
                # 이동 중일 때만 시계를 다시 맞춘다. 카메라에는 아무것도 보내지 않는다.
                with self._glock:
                    moving = cid in self._dead
                if not moving:
                    return {'ok': False, 'state': 'refused', 'reason': 'not_moving'}
                self._arm_deadman(cid)
                return {'ok': True, 'state': 'accepted', 'reason': ''}
            if op == 'ptz_stop':
                self._cancel_deadman(cid)
                return self._res(drv.ptz_stop())
            if op == 'ptz_goto':
                self._cancel_deadman(cid)
                return self._res(drv.ptz_goto(arg.get('preset')))
            if op == 'ptz_set_preset':
                return self._res(drv.ptz_set_preset(arg.get('preset'), arg.get('name', '')))
            if op == 'ptz_remove_preset':
                return self._res(drv.ptz_remove_preset(arg.get('preset')))
            if op == 'day_night_get':
                return self._res(drv.get_day_night())
            if op == 'day_night_set':
                return self._res(drv.set_day_night(arg.get('mode')))
            if op == 'alarm':
                return self._res(drv.manual_alarm(bool(arg.get('start'))))
            if op == 'msg_push_on':
                return self._res(drv.enable_msg_push(arg.get('kind')))
        return {'ok': False, 'state': 'unsupported', 'reason': 'unknown_op'}

    # -- 저장 -------------------------------------------------------------
    def _tofu(self, cid, observed):
        if not observed:
            return
        with self._scope() as s:
            r = self._row(s, cid)
            if r is not None and not r.tls_pin_sha256:
                r.tls_pin_sha256 = observed

    def _save_result(self, cid, info, caps):
        with self._scope() as s:
            r = self._row(s, cid)
            if r is None:
                return
            if isinstance(info, dict):
                r.device_info = info
                mac = info.get('mac')
                if mac:
                    r.mac = str(mac)
            if caps is not None:
                import json
                r.capabilities = json.loads(caps.to_json())
                r.capabilities_at = naive_utc(self.clock())

    def _brief(self, cid):
        st = self.status(cid)
        return {k: st.get(k) for k in ('auth_state', 'auth_iface', 'auth_code', 'device_info',
                                       'capabilities', 'capabilities_at', 'events_enabled',
                                       'event_kinds', 'event_state', 'event_note') if k in st}


_service = None


def get_service():
    global _service
    if _service is None:
        _service = CameraDriverService()
    return _service
