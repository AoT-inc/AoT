# coding=utf-8
"""카메라 이벤트 기록·디스패치·보존 정리·구독 관리 (설계 §3.4, §5.3, §6.2, §6.3).

- `EventRecorder`   camera_event 한 줄을 쓴다. 판정 시각은 서버 수신 시각이다.
- `TriggerDispatcher` trigger_camera_event 를 골라 `trigger_all_actions` 를 부른다.
- `purge_old`       카메라당 30일 또는 1만 행(먼저 닿는 쪽).
- `EventHub`        버스·소비자 스레드·카메라별 구독을 한 곳에서 관리한다(데몬 전용).

시간은 전부 timekit. 디스패치 결과는 "트리거 실행 요청됨"까지만 말한다 — 출력이 켜졌는지는
각 Action 이 자기 기록으로 판정한다.
"""
import collections
import logging
import threading
from datetime import timedelta

from aot.camera_drivers import auth_guard as AG
from aot.camera_drivers.events import CameraEvent, CameraEventBus
from aot.utils.timekit import iso_utc, naive_utc, parse_utc, utc_now

logger = logging.getLogger(__name__)

SKEW_LIMIT_S = 120            # 카메라 시계가 이보다 어긋나면 남긴다
RETAIN_DAYS = 30
RETAIN_ROWS = 10000
RATE_LIMIT = 30               # 카메라당 1분 디스패치 상한
RATE_WINDOW_S = 60
DEFAULT_COOLDOWN_S = 60

NONE, DISPATCHED, ERROR = 'none', 'dispatched', 'dispatch_error'
SUP_COOLDOWN, SUP_RATE = 'suppressed_cooldown', 'suppressed_rate'
_RANK = {NONE: 0, SUP_COOLDOWN: 1, SUP_RATE: 2, DISPATCHED: 3, ERROR: 4}


def _scope():
    from aot.config import AOT_DB_PATH
    from aot.databases.utils import session_scope
    return session_scope(AOT_DB_PATH)


def skew_seconds(event):
    """카메라가 보낸 시각과 서버 수신 시각의 차(초). 카메라 시각이 없으면 None."""
    if event.camera_time_epoch is None:
        return None
    try:
        return int((parse_utc(event.camera_time_epoch) - parse_utc(event.received_at_utc))
                   .total_seconds())
    except (ValueError, OverflowError, OSError):
        return None


def record_event(event):
    """camera_event 한 줄을 쓰고 id 를 돌려준다. 시계 어긋남이 크면 dispatch_note 에 남긴다."""
    from aot.databases.models import CameraEvent as Row
    skew = skew_seconds(event)
    note = None
    if skew is not None and abs(skew) > SKEW_LIMIT_S:
        note = 'camera_clock_skew_s=%d' % skew
    cam_time = None
    if event.camera_time_epoch is not None:
        try:
            cam_time = naive_utc(parse_utc(event.camera_time_epoch))
        except (ValueError, OverflowError, OSError):
            cam_time = None
    with _scope() as s:
        row = Row(camera_id=event.camera_id, kind=event.kind, enhanced=event.enhanced or None,
                  raw_type=event.raw_type or None, camera_time_utc=cam_time,
                  received_at_utc=naive_utc(event.received_at_utc), dispatch_state=NONE,
                  dispatch_note=note)
        s.add(row)
        s.flush()
        rid = row.id
    if note:
        _set_driver_note(event.camera_id, note)
    return rid, note


def _set_driver_note(camera_id, note):
    from aot.databases.models import CameraDriver
    try:
        with _scope() as s:
            r = s.query(CameraDriver).filter(CameraDriver.camera_id == camera_id).first()
            if r is not None:
                r.event_note = note
    except Exception:
        logger.exception('camera event note record failed')


def _update_row(rid, state, note):
    from aot.databases.models import CameraEvent as Row
    with _scope() as s:
        r = s.query(Row).filter(Row.id == rid).first()
        if r is not None:
            r.dispatch_state = state
            if note:
                r.dispatch_note = (r.dispatch_note + '; ' + note) if r.dispatch_note else note


class TriggerDispatcher:
    """이벤트 → 활성 `trigger_camera_event` 중 종류가 맞는 것 → `trigger_all_actions`.

    쿨다운은 트리거별 `period`(초, 기본 60) — 서버 수신 시각으로 잰다. 카메라당 1분 30건 상한.
    실패 판정: 예외, 또는 문자열이 'Could not trigger' 로 시작하면 dispatch_error."""

    def __init__(self, control=None):
        self._control = control
        self._last = {}                                  # trigger_uid -> 마지막 발화 시각
        self._window = collections.defaultdict(collections.deque)   # camera -> 발화 시각들
        self._rate_warned = {}

    def _ctl(self):
        if self._control is None:
            from aot.aot_client import DaemonControl
            self._control = DaemonControl()
        return self._control

    def _matching(self, event):
        from aot.databases.models import Camera, Trigger
        with _scope() as s:
            cam = s.query(Camera).filter(Camera.unique_id == event.camera_id).first()
            cam_name = cam.name if cam is not None else ''
            rows = s.query(Trigger).filter(
                Trigger.trigger_type == 'trigger_camera_event',
                Trigger.unique_id_1 == event.camera_id,
                Trigger.is_activated.is_(True)).all()
            out = []
            for t in rows:
                kinds = t.event_kinds if isinstance(t.event_kinds, list) else []
                if event.kind in kinds:
                    out.append((t.unique_id, t.id, t.name, t.period))
        return cam_name, out

    def _rate_ok(self, camera_id, now):
        w = self._window[camera_id]
        while w and (now - w[0]).total_seconds() >= RATE_WINDOW_S:
            w.popleft()
        return len(w) < RATE_LIMIT

    def dispatch(self, event):
        """(state, note). state 는 모든 매칭 트리거 결과 중 가장 무거운 것."""
        if event.kind == 'unknown':
            return NONE, 'unknown_kind'
        now = parse_utc(event.received_at_utc)
        cam_name, triggers = self._matching(event)
        best, notes = NONE, []
        for uid, tid, tname, period in triggers:
            cooldown = DEFAULT_COOLDOWN_S if period in (None, '') else max(0, int(float(period)))
            last = self._last.get(uid)
            if last is not None and (now - last).total_seconds() < cooldown:
                state = SUP_COOLDOWN
            elif not self._rate_ok(event.camera_id, now):
                state = SUP_RATE
                if not self._rate_warned.get(event.camera_id) or \
                        (now - self._rate_warned[event.camera_id]).total_seconds() >= RATE_WINDOW_S:
                    self._rate_warned[event.camera_id] = now
                    logger.warning('camera event dispatch rate limit reached camera=%s '
                                   '(%d per %ds)', event.camera_id, RATE_LIMIT, RATE_WINDOW_S)
                    _set_driver_note(event.camera_id, 'dispatch_rate_limited')
            else:
                self._last[uid] = now
                self._window[event.camera_id].append(now)
                state, why = self._fire(uid, tid, tname, cam_name, event)
                if why:
                    notes.append(why)
            if _RANK[state] > _RANK[best]:
                best = state
        return best, '; '.join(notes) or None

    def _fire(self, uid, tid, tname, cam_name, event):
        msg = '%s\n[Trigger %s (%s)] Camera %s event: %s' % (
            iso_utc(event.received_at_utc), tid, tname, cam_name, event.kind)
        try:
            ret = self._ctl().trigger_all_actions(uid, message=msg)
        except Exception as exc:    # noqa: BLE001 — 문자열만 남긴다
            return ERROR, 'trigger %s: %s' % (tid, type(exc).__name__)
        if isinstance(ret, str) and ret.startswith('Could not trigger'):
            return ERROR, 'trigger %s: %s' % (tid, ret[:120])
        # 실행이 "요청됨"까지만 안다 — 출력이 켜졌는지는 Action 기록으로 본다
        return DISPATCHED, None


def purge_old(now=None, retain_days=RETAIN_DAYS, retain_rows=RETAIN_ROWS):
    """보존 정리. 지운 행 수를 돌려준다."""
    from aot.databases.models import CameraEvent as Row
    now = now or utc_now()
    cutoff = naive_utc(now - timedelta(days=retain_days))
    removed = 0
    with _scope() as s:
        removed += s.query(Row).filter(Row.received_at_utc < cutoff).delete(
            synchronize_session=False)
        cams = [c for (c,) in s.query(Row.camera_id).distinct().all()]
        for cid in cams:
            edge = s.query(Row.id).filter(Row.camera_id == cid).order_by(
                Row.id.desc()).offset(retain_rows).limit(1).first()
            if edge is not None:
                removed += s.query(Row).filter(Row.camera_id == cid, Row.id <= edge[0]).delete(
                    synchronize_session=False)
    return removed


class EventHub:
    """데몬 하나에 하나. 버스·소비자 스레드·카메라별 구독을 관리한다."""

    PURGE_EVERY = timedelta(days=1)

    def __init__(self, service, dispatcher=None, bus=None, clock=utc_now, sub_factory=None):
        self.service = service
        self.bus = bus or CameraEventBus()
        self.dispatcher = dispatcher or TriggerDispatcher()
        self.clock = clock
        self._sub_factory = sub_factory
        self._subs = {}
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._next_purge = None
        self.processed = 0

    # -- 소비자 ---------------------------------------------------------
    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._consume, name='camera-event-consumer',
                                            daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            subs, self._subs = list(self._subs.values()), {}
        for s in subs:
            s.stop(join=0.5)
        if self._thread is not None:
            self._thread.join(2.0)

    def _consume(self):
        while not self._stop.is_set():
            ev = self.bus.get(timeout=0.5)
            if ev is not None:
                self.handle(ev)
            self._maybe_purge()

    def handle(self, ev):
        """이벤트 하나: 기록 → 디스패치 → 결과 기록. 소비자 스레드만 부른다."""
        try:
            rid, _ = record_event(ev)
        except Exception:
            logger.exception('camera event record failed')
            return
        try:
            state, note = self.dispatcher.dispatch(ev)
        except Exception as exc:    # noqa: BLE001
            state, note = ERROR, 'dispatch: %s' % type(exc).__name__
            logger.exception('camera event dispatch failed')
        try:
            if state != NONE or note:
                _update_row(rid, state, note)
        except Exception:
            logger.exception('camera event result record failed')
        self.processed += 1

    def _maybe_purge(self):
        now = self.clock()
        if self._next_purge is None or now >= self._next_purge:
            self._next_purge = now + self.PURGE_EVERY
            try:
                n = purge_old(now)
                if n:
                    logger.info('camera_event retention removed %d rows', n)
            except Exception:
                logger.exception('camera_event retention failed')

    # -- 구독 관리 --------------------------------------------------------
    def _row(self, cid):
        from aot.databases.models import CameraDriver
        with _scope() as s:
            r = s.query(CameraDriver).filter(CameraDriver.camera_id == cid).first()
            if r is None:
                return None
            return dict(enabled=bool(r.events_enabled), auth=r.auth_state, cfp=r.credential_fp,
                        vfp=r.verified_fp, kinds=r.event_kinds, state=r.event_state,
                        state_at=r.event_state_at)

    def _eligible(self, cid):
        """(ok, 중단 상태, 사유). 데몬 재시작 때도 같은 조건: 켜짐 & auth ok & verified_fp 일치(§6.2)."""
        r = self._row(cid)
        if r is None:
            return False, 'off', 'not_configured'
        if not r['enabled']:
            return False, 'off', 'disabled'
        if r['auth'] in AG.LATCHED_STATES:
            return False, 'stopped_auth', 'auth_' + r['auth']
        if r['auth'] != 'ok' or not r['vfp'] or r['vfp'] != r['cfp']:
            return False, 'off', 'unverified'
        return True, 'connecting', ''

    def _save_state(self, cid, state, note):
        from aot.databases.models import CameraDriver
        try:
            with _scope() as s:
                r = s.query(CameraDriver).filter(CameraDriver.camera_id == cid).first()
                if r is not None:
                    r.event_state = state
                    r.event_state_at = naive_utc(self.clock())
                    if state == 'subscribed':
                        pass
                    elif note and state != 'connecting':
                        r.event_note = ('state:' + note)[:200]
        except Exception:
            logger.exception('camera event state save failed')

    def _save_gap(self, cid, start, end):
        secs = max(0, int((end - start).total_seconds()))
        _set_driver_note(cid, 'gap_s=%d' % secs)

    @staticmethod
    def _kinds_of(row):
        k = row['kinds']
        return list(k) if isinstance(k, list) and k else None

    def _new_sub(self, cid, row):
        if self._sub_factory is not None:
            return self._sub_factory(cid, row)
        from aot.camera_drivers.vigi.subscribe import CameraSubscription
        gap_since = None
        if row['state'] in ('subscribed', 'connecting', 'backoff', 'stopped_limit') \
                and row['state_at'] is not None:
            gap_since = parse_utc(row['state_at'])     # 데몬이 내려가 있던 구간도 기록한다
        return CameraSubscription(
            cid, make_api=lambda: self._make_api(cid),
            eligible=lambda: self._eligible(cid),
            on_event=self.bus.publish,
            on_state=lambda st, note: self._save_state(cid, st, note),
            on_gap=lambda a, b: self._save_gap(cid, a, b),
            clock=self.clock, gap_since=gap_since, kinds=self._kinds_of(row))

    def _make_api(self, cid):
        drv, why = self.service._driver(cid)
        return (drv.api if drv is not None else None), why

    def ensure(self, cid, restart=False):
        """설정·인증 상태에 맞게 구독을 켜거나 끈다. 이미 맞게 돌고 있으면 건드리지 않는다
        (불필요한 재연결은 끊긴 구간과 클라이언트 슬롯을 낭비한다). restart=True 는 주소·계정이
        바뀌었을 수 있을 때(설정 저장)만 — 구독이 쥔 세션을 버리고 새로 붙는다."""
        with self._lock:
            sub = self._subs.get(cid)
            if restart and sub is not None:
                sub.stop(join=1.0)
                self._subs.pop(cid, None)
                sub = None
            ok, st, why = self._eligible(cid)
            row = self._row(cid)
            if not ok:
                if sub is not None:
                    sub.stop(join=1.0)
                    self._subs.pop(cid, None)
                if row is not None and row['state'] != st:
                    self._save_state(cid, st, why)
                return {'running': False, 'state': st}
            if sub is not None and sub.alive:
                sub.kinds = self._kinds_of(row)      # 받을 종류 변경은 즉시 반영, 재연결 없음
                return {'running': True, 'state': sub.state}
            sub = self._new_sub(cid, row)
            self._subs[cid] = sub
            sub.start()
            return {'running': True, 'state': 'connecting'}

    def start_all(self):
        """데몬 시작 때: 이벤트가 켜진 카메라만(조건은 ensure 가 다시 본다)."""
        from aot.databases.models import CameraDriver
        self.start()
        try:
            with _scope() as s:
                ids = [c for (c,) in s.query(CameraDriver.camera_id).filter(
                    CameraDriver.events_enabled.is_(True)).all()]
        except Exception:
            logger.exception('camera events: listing failed')
            return
        for cid in ids:
            try:
                self.ensure(cid)
            except Exception:
                logger.exception('camera events: ensure failed')


_hub = None


def get_hub(service=None):
    global _hub
    if _hub is None:
        from aot.camera_drivers.service import get_service
        _hub = EventHub(service or get_service())
    return _hub
