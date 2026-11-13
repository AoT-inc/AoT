# coding=utf-8
"""VIGI 이벤트 구독 — 카메라당 연결 1개. 수명 상태도는 설계 §6.2 그대로.

    off ──(켜짐 & 인증 ok)──▶ connecting ──▶ subscribed
    subscribed ──스트림 종료/하트비트 끊김(70초)──▶ backoff(5→…→300초) ──▶ connecting
    connecting ──-10020/-10022/인증서 변경/거부──▶ stopped_auth (래치, 사용자 대기. 스레드 종료)
    connecting ──-10021──▶ stopped_limit → 60→120→…→900초 뒤 다시(래치 아님)
    connecting ──네트워크 오류──▶ backoff

인증 실패에는 자동 재시도가 없다. 이 스레드는 틀린 자격 증명을 카메라에 두 번 보낼 길이 없다
(`VigiOpenApi` 가 `AuthGuard` 를 거친다). 끊겼던 구간은 `on_gap` 으로 알린다.
"""
import json
import logging
import threading

from aot.camera_drivers.capabilities import CV_PREFIX  # noqa: F401  (이름 공간 예약 표시)
from aot.camera_drivers.driver import ErrorClass, scrub
from aot.camera_drivers.events import CameraEvent
from aot.camera_drivers.vigi import capability_map
from aot.camera_drivers.vigi.errors import Backoff
from aot.utils.timekit import utc_now

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_S = 70.0     # 하트비트 30초 × 2 + 10초 (설계 §6.2)

OFF, CONNECTING, SUBSCRIBED, BACKOFF = 'off', 'connecting', 'subscribed', 'backoff'
STOPPED_AUTH, STOPPED_LIMIT = 'stopped_auth', 'stopped_limit'


def read_parts(resp):
    """multipart/mixed 응답에서 JSON 조각을 하나씩 꺼낸다. 형식은 [미확인](V4)이라 관대하게 읽는다:
    경계선 줄을 건너뛰고, 헤더(Content-Length)가 있으면 그만큼, 없으면 다음 경계선까지 읽는다.
    스트림이 끝나면 반복이 끝난다. 읽기 제한 시간이 지나면 socket.timeout 이 올라간다."""
    while True:
        line = resp.readline()
        if not line:
            return
        if not line.strip() or not line.startswith(b'--'):
            continue
        if line.strip().endswith(b'--') and line.strip() != b'--':
            continue
        length = None
        while True:       # 조각 헤더
            h = resp.readline()
            if not h:
                return
            if not h.strip():
                break
            k, _, v = h.partition(b':')
            if k.strip().lower() == b'content-length':
                try:
                    length = int(v.strip())
                except ValueError:
                    length = None
        if length is not None:
            raw = resp.read(length)
        else:
            buf = []
            while True:
                nxt = resp.readline()
                if not nxt or nxt.startswith(b'--'):
                    break
                buf.append(nxt)
            raw = b''.join(buf)
        try:
            obj = json.loads(raw.decode('utf-8', 'replace'))
        except ValueError:
            continue
        yield obj


class CameraSubscription:
    """카메라 하나의 구독 스레드.

    make_api()    -> (VigiOpenApi|None, 사유)   매 연결마다 새로 만든다(설정 변경 반영)
    eligible()    -> (bool, state, 사유)         켜짐·인증 ok·지문 일치 확인(DB)
    on_event(ev)  CameraEvent → 버스
    on_state(state, note)   상태 변경 기록
    on_gap(start, end)      끊겼던 구간
    sleep(sec) -> bool(중단됨)  테스트가 주입한다
    """

    def __init__(self, camera_id, make_api, eligible, on_event, on_state, on_gap=None,
                 clock=utc_now, sleep=None, heartbeat_timeout=HEARTBEAT_TIMEOUT_S, rng=None,
                 gap_since=None, kinds=None):
        self.camera_id = camera_id
        self._make_api = make_api
        self._eligible = eligible
        self._on_event = on_event
        self._on_state = on_state
        self._on_gap = on_gap or (lambda s, e: None)
        self._clock = clock
        self._stop = threading.Event()
        self._sleep = sleep or (lambda sec: self._stop.wait(sec))
        self._hb = heartbeat_timeout
        self._net = Backoff('network', rng)
        self._lim = Backoff('client_limit', rng)
        self._gap_start = gap_since
        self.kinds = kinds          # None = 모든 종류
        self.state = OFF
        self.delays = []            # 시험이 보는 백오프 간격 기록
        self._stream = None
        self._api = None
        self._thread = None
        self.heartbeats = 0
        self.events_seen = 0

    # -- 수명 -----------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run, name='vigi-sub-%s' % self.camera_id[:8],
                                        daemon=True)
        self._thread.start()
        return self

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def stop(self, join=2.0):
        self._stop.set()
        st = self._stream
        if st is not None:
            st.close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(join)

    def _set(self, state, note=''):
        self.state = state
        try:
            self._on_state(state, note)
        except Exception:
            logger.exception('camera subscription state record failed')

    def _wait(self, sec):
        self.delays.append(sec)
        return self._sleep(sec)

    # -- 본체 -----------------------------------------------------------
    def _run(self):
        try:
            self._loop()
        except Exception:
            logger.exception('camera subscription crashed camera=%s', self.camera_id)
            self._set(BACKOFF, 'internal_error')
        finally:
            if self._stop.is_set():
                self.state = OFF

    def _loop(self):
        while not self._stop.is_set():
            ok, st, why = self._eligible()
            if not ok:
                self._set(st, why)
                return
            self._set(CONNECTING)
            if self._api is None:
                # 같은 api(세션)를 재연결에도 쓴다 — 재연결마다 새로 인증하면 카메라의 클라이언트 슬롯
                # (-10021)을 낭비한다. 설정이 바뀌면 허브가 이 구독을 멈추고 새로 만든다.
                self._api, why = self._make_api()
            api = self._api
            if api is None:
                self._set(OFF, why or 'not_configured')
                return
            res, stream = api.open_stream('subscribeMsg', None, read_timeout=self._hb)
            if stream is None:
                if not self._after_failure(res):
                    return
                continue
            self._stream = stream
            self._net.reset()
            self._lim.reset()
            self._mark_gap_end()
            self._set(SUBSCRIBED)
            reason = self._pump(stream)
            self._stream = None
            stream.close()
            if self._stop.is_set():
                return
            self._gap_start = self._gap_start or self._clock()
            self._set(BACKOFF, reason)
            if self._wait(self._net.next_delay()):
                return

    def _mark_gap_end(self):
        if self._gap_start is not None:
            try:
                self._on_gap(self._gap_start, self._clock())
            except Exception:
                logger.exception('camera subscription gap record failed')
            self._gap_start = None

    def _pump(self, stream):
        """스트림을 읽는다. 끝난 이유('stream_closed'·'heartbeat_timeout'·'read_error')를 돌려준다."""
        try:
            for obj in read_parts(stream.resp):
                if self._stop.is_set():
                    return 'stopped'
                what, ev = capability_map.parse_event_part(obj)
                if what == 'heartbeat':
                    self.heartbeats += 1
                elif what == 'event':
                    self.events_seen += 1
                    self._emit(ev)
            return 'stream_closed'
        except TimeoutError:
            return 'heartbeat_timeout'
        except OSError as exc:
            return 'heartbeat_timeout' if 'timed out' in str(exc) else 'read_error'
        except Exception as exc:   # noqa: BLE001
            logger.warning('camera subscription read failed: %s', type(exc).__name__)
            return 'read_error'

    def _emit(self, ev):
        kind = ev['kind']
        if self.kinds is not None and kind != 'unknown' and kind not in self.kinds:
            return      # 사용자가 받지 않기로 한 종류
        self._on_event(CameraEvent(
            camera_id=self.camera_id, kind=kind, received_at_utc=self._clock(),
            enhanced=ev['enhanced'], raw_type=ev['raw_type'], camera_time_epoch=ev['camera_epoch']))

    def _after_failure(self, res):
        """연결에 실패했을 때: True 면 백오프 뒤 계속, False 면 스레드 종료."""
        self._gap_start = self._gap_start or self._clock()
        cls = res.error_class
        msg = scrub(res.message)
        if cls in (ErrorClass.AUTH_FAILED, ErrorClass.LOCKED, ErrorClass.CERT_CHANGED) \
                or res.state.value == 'refused':
            # 래치. 자동 재시도 없음 — 사용자가 풀 때까지 멈춘다
            self._set(STOPPED_AUTH, msg or cls.value)
            return False
        if cls is ErrorClass.CLIENT_LIMIT:
            self._set(STOPPED_LIMIT, msg)
            return not self._wait(self._lim.next_delay())
        self._set(BACKOFF, msg or cls.value)
        return not self._wait(self._net.next_delay())
