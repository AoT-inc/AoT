# coding=utf-8
"""인증 래치·자격 증명 지문·시도 임대. 설계 §6.1 (계약).

"카메라에 틀린 자격 증명이 두 번 가는 경로가 하나도 없다" 가 완료 조건이다.

- 실패 1회면 래치(failed/locked). 자동 재시도 없음. 푸는 것은 사용자뿐이다
  (`set_credentials` 로 새 비밀번호 저장, 또는 `release_latch` = "다시 연결").
- 재인증은 `verified_fp` 와 같은 자격 증명으로만.
- 검증 안 된 자격 증명은 프로세스를 통틀어 한 번만: 저장소의 compare-and-set 으로
  `attempt_lease_until` 을 잡은 쪽만 시도한다.

저장소는 `AuthStore` 인터페이스다. P2 에서 `camera_driver` 테이블 위의 구현이 붙는다
(UPDATE … WHERE attempt_lease_until IS NULL OR < now). P1 은 스키마를 만들지 않는다.
이 모듈은 DB·Flask 를 import 하지 않는다.
"""
import hashlib
import hmac
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Callable, Optional

from aot.camera_drivers.driver import ErrorClass

# auth_state 어휘 (camera_driver.auth_state 와 동일)
UNVERIFIED = 'unverified'
OK = 'ok'
FAILED = 'failed'
LOCKED = 'locked'
OPENAPI_OFF = 'openapi_off'
CERT_CHANGED = 'cert_changed'

# 래치: 사용자가 풀기 전에는 모든 경로가 멈춘다
LATCHED_STATES = frozenset({FAILED, LOCKED, CERT_CHANGED})

# "다시 연결"이 풀 수 있는 상태(래치 + OpenAPI 꺼짐)
CLEARABLE_STATES = LATCHED_STATES | {OPENAPI_OFF}

LEASE_SECONDS = 30


def credential_fp(username, password, key) -> str:
    """(username, password) 를 서버 비밀값으로 HMAC 한 지문. 비밀번호를 복원할 수 없다."""
    if isinstance(key, str):
        key = key.encode()
    msg = ('%d:%s:%s' % (len(username), username, password)).encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class AuthRecord:
    auth_state: str = UNVERIFIED
    credential_fp: Optional[str] = None
    verified_fp: Optional[str] = None
    attempt_lease_until: Optional[datetime] = None
    auth_iface: str = ''
    auth_code: Optional[int] = None
    auth_at: Optional[datetime] = None


class AuthStore:
    """저장소 인터페이스. 모든 변경은 원자적이어야 하고 프로세스 공용이어야 한다."""

    def load(self, camera_id) -> AuthRecord:
        raise NotImplementedError

    def acquire_lease(self, camera_id, fp, now, until) -> bool:
        """검증 안 된 자격 증명 시도 임대를 compare-and-set 으로 잡는다.

        조건: 래치 상태가 아니고, verified_fp != fp, 그리고
        (attempt_lease_until IS NULL OR attempt_lease_until < now). 잡았으면 True."""
        raise NotImplementedError

    def mark_verified(self, camera_id, fp, now):
        """성공: verified_fp=fp, auth_state='ok', 임대 해제, 실패 필드 비움."""
        raise NotImplementedError

    def mark_latched(self, camera_id, state, iface, code, now):
        """실패 래치: auth_state=state, 실패 위치·코드·시각 기록, 임대 해제."""
        raise NotImplementedError

    def release_lease(self, camera_id):
        """래치 없이 임대만 해제(네트워크 오류·클라이언트 수 초과 등)."""
        raise NotImplementedError

    def set_state(self, camera_id, state):
        """openapi_off/cert_changed 등 상태만 바꾼다(임대 해제 포함)."""
        raise NotImplementedError

    def reset_credentials(self, camera_id, new_fp):
        """사용자가 비밀번호를 새로 저장: credential_fp=new_fp, state=unverified,
        임대·실패 필드 비움. verified_fp 는 그대로 둔다(다른 지문이면 어차피 재인증 안 됨)."""
        raise NotImplementedError

    def clear_latch(self, camera_id):
        """"다시 연결": 래치를 unverified 로 되돌린다. 시도는 다음에 1회뿐이다."""
        raise NotImplementedError


class InMemoryAuthStore(AuthStore):
    """단위 시험·단일 프로세스용. 락으로 compare-and-set 을 흉내 낸다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rows = {}

    def _get(self, cid):
        return self._rows.get(cid, AuthRecord())

    def load(self, camera_id):
        with self._lock:
            return self._get(camera_id)

    def acquire_lease(self, camera_id, fp, now, until):
        with self._lock:
            r = self._get(camera_id)
            if r.auth_state in LATCHED_STATES or r.verified_fp == fp:
                return False
            if r.attempt_lease_until is not None and r.attempt_lease_until >= now:
                return False
            self._rows[camera_id] = replace(r, attempt_lease_until=until)
            return True

    def mark_verified(self, camera_id, fp, now):
        with self._lock:
            r = self._get(camera_id)
            self._rows[camera_id] = replace(
                r, auth_state=OK, verified_fp=fp, credential_fp=fp or r.credential_fp,
                attempt_lease_until=None, auth_iface='', auth_code=None, auth_at=None)

    def mark_latched(self, camera_id, state, iface, code, now):
        with self._lock:
            r = self._get(camera_id)
            self._rows[camera_id] = replace(
                r, auth_state=state, auth_iface=iface, auth_code=code, auth_at=now,
                attempt_lease_until=None)

    def release_lease(self, camera_id):
        with self._lock:
            self._rows[camera_id] = replace(self._get(camera_id), attempt_lease_until=None)

    def set_state(self, camera_id, state):
        with self._lock:
            self._rows[camera_id] = replace(
                self._get(camera_id), auth_state=state, attempt_lease_until=None)

    def reset_credentials(self, camera_id, new_fp):
        with self._lock:
            self._rows[camera_id] = replace(
                self._get(camera_id), credential_fp=new_fp, auth_state=UNVERIFIED,
                attempt_lease_until=None, auth_iface='', auth_code=None, auth_at=None)

    def clear_latch(self, camera_id):
        with self._lock:
            r = self._get(camera_id)
            if r.auth_state in CLEARABLE_STATES:
                self._rows[camera_id] = replace(
                    r, auth_state=UNVERIFIED, attempt_lease_until=None,
                    auth_iface='', auth_code=None, auth_at=None)


# 허가(permit) 종류
FIRST_TRY = 'first_try'   # 검증 안 된 자격 증명의 단 한 번의 시도 (임대 보유)
REAUTH = 'reauth'         # verified_fp 와 같은 자격 증명으로의 재인증


@dataclass(frozen=True)
class Permit:
    camera_id: str
    fp: str
    kind: str
    interface: str


@dataclass(frozen=True)
class Refusal:
    reason: str      # 'latched:failed' · 'latched:locked' · 'latched:cert_changed' ·
    #                  'attempt_in_progress' · 'credential_unverified' · 'openapi_off'
    message: str

    def __bool__(self):
        return False


class AuthGuard:
    """모든 인증 시도 앞에 서는 문지기. 네트워크 호출 전에 `begin` 을 거쳐야 한다."""

    def __init__(self, store: AuthStore, clock: Callable[[], datetime] = None,
                 lease_seconds: int = LEASE_SECONDS):
        if clock is None:
            from aot.utils.timekit import utc_now
            clock = utc_now
        self.store = store
        self.clock = clock
        self.lease_seconds = lease_seconds

    def begin(self, camera_id, fp, interface='openapi', reauth=False):
        """시도 허가. 허가면 Permit, 거부면 Refusal(falsy).

        reauth=True 는 "이미 한 번 성공한 세션을 다시 여는 것"이다. verified_fp 와
        같은 지문이 아니면 거부한다(사용자가 비밀번호를 바꿨는데 아직 확인 안 됨)."""
        rec = self.store.load(camera_id)
        if rec.auth_state in LATCHED_STATES:
            return Refusal('latched:' + rec.auth_state,
                           'auth latched (%s); waiting for the user' % rec.auth_state)
        if rec.auth_state == OPENAPI_OFF and interface == 'openapi':
            return Refusal('openapi_off', 'OpenAPI is off on the camera')
        if rec.verified_fp is not None and rec.verified_fp == fp:
            return Permit(camera_id, fp, REAUTH, interface)
        if reauth:
            return Refusal('credential_unverified',
                           'credential changed and not verified; not re-authenticating')
        now = self.clock()
        if self.store.acquire_lease(camera_id, fp, now,
                                    now + timedelta(seconds=self.lease_seconds)):
            return Permit(camera_id, fp, FIRST_TRY, interface)
        # 임대를 못 잡았다: 방금 다른 쪽이 래치/검증했을 수도 있다
        rec = self.store.load(camera_id)
        if rec.auth_state in LATCHED_STATES:
            return Refusal('latched:' + rec.auth_state,
                           'auth latched (%s); waiting for the user' % rec.auth_state)
        if rec.verified_fp == fp:
            return Permit(camera_id, fp, REAUTH, interface)
        return Refusal('attempt_in_progress',
                       'another attempt with an unverified credential is in progress')

    def report_success(self, permit: Permit):
        before = self.store.load(permit.camera_id).auth_state
        self.store.mark_verified(permit.camera_id, permit.fp, self.clock())
        if before == OPENAPI_OFF:
            # RTSP 가 검증했어도 OpenAPI 가 꺼져 있다는 사실은 그대로다
            self.store.set_state(permit.camera_id, OPENAPI_OFF)

    def report_failure(self, permit: Permit, error_class: ErrorClass, code=None):
        """인증 계열 실패면 래치, 아니면 임대만 푼다(자동 재시도 금지는 호출자 책임이 아니라 래치가 보장)."""
        if error_class is ErrorClass.AUTH_FAILED:
            self.store.mark_latched(permit.camera_id, FAILED, permit.interface, code, self.clock())
        elif error_class is ErrorClass.LOCKED:
            self.store.mark_latched(permit.camera_id, LOCKED, permit.interface, code, self.clock())
        elif error_class is ErrorClass.CERT_CHANGED:
            self.store.mark_latched(permit.camera_id, CERT_CHANGED, permit.interface, code,
                                    self.clock())
        else:
            self.store.release_lease(permit.camera_id)

    def latch_any_interface(self, camera_id, state, interface, code=None):
        """한 인터페이스의 인증 실패를 양쪽에 건다(두 인터페이스 잠금 공유 여부 [미확인], §6.1-5)."""
        self.store.mark_latched(camera_id, state, interface, code, self.clock())

    def mark_openapi_off(self, camera_id):
        """OpenAPI 포트가 닫혀 있다. 이미 래치된 상태는 덮지 않는다."""
        if self.store.load(camera_id).auth_state not in LATCHED_STATES:
            self.store.set_state(camera_id, OPENAPI_OFF)
