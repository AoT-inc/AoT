# coding=utf-8
"""AuthStore 의 DB 구현 — `camera_driver` 표 위의 compare-and-set (설계 §6.1-4).

모든 변경은 한 문장의 UPDATE 로 원자적이다. 데몬·gunicorn 워커가 각자 세션으로 불러도
시도 임대는 한 곳만 잡는다. 시간은 naive UTC 로 저장한다.
"""
from sqlalchemy import and_, or_, update

from aot.camera_drivers.auth_guard import (AuthRecord, AuthStore, CLEARABLE_STATES,
                                           LATCHED_STATES, UNVERIFIED)
from aot.utils.timekit import naive_utc, parse_utc


def _aware(dt):
    return parse_utc(dt) if dt else None


class DbAuthStore(AuthStore):
    def __init__(self, db_uri=None):
        self._uri = db_uri

    def _scope(self):
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope
        return session_scope(self._uri or AOT_DB_PATH)

    @staticmethod
    def _model():
        from aot.databases.models import CameraDriver
        return CameraDriver

    def load(self, camera_id):
        M = self._model()
        with self._scope() as s:
            r = s.query(M).filter(M.camera_id == camera_id).first()
            if r is None:
                return AuthRecord()
            return AuthRecord(
                auth_state=r.auth_state or UNVERIFIED, credential_fp=r.credential_fp,
                verified_fp=r.verified_fp, attempt_lease_until=_aware(r.attempt_lease_until),
                auth_iface=r.auth_iface or '', auth_code=r.auth_code, auth_at=_aware(r.auth_at))

    def _update(self, camera_id, extra_where=(), **values):
        M = self._model()
        with self._scope() as s:
            res = s.execute(update(M).where(and_(M.camera_id == camera_id, *extra_where))
                            .values(**values))
            return res.rowcount

    def acquire_lease(self, camera_id, fp, now, until):
        M = self._model()
        n = naive_utc(now)
        return self._update(
            camera_id,
            (M.auth_state.notin_(tuple(LATCHED_STATES)),
             or_(M.verified_fp.is_(None), M.verified_fp != fp),
             or_(M.attempt_lease_until.is_(None), M.attempt_lease_until < n)),
            attempt_lease_until=naive_utc(until)) == 1

    def mark_verified(self, camera_id, fp, now):
        self._update(camera_id, auth_state='ok', verified_fp=fp, credential_fp=fp,
                     attempt_lease_until=None, auth_iface=None, auth_code=None, auth_at=None)

    def mark_latched(self, camera_id, state, iface, code, now):
        self._update(camera_id, auth_state=state, auth_iface=iface, auth_code=code,
                     auth_at=naive_utc(now), attempt_lease_until=None)

    def release_lease(self, camera_id):
        self._update(camera_id, attempt_lease_until=None)

    def set_state(self, camera_id, state):
        self._update(camera_id, auth_state=state, attempt_lease_until=None)

    def reset_credentials(self, camera_id, new_fp):
        self._update(camera_id, credential_fp=new_fp, auth_state=UNVERIFIED,
                     attempt_lease_until=None, auth_iface=None, auth_code=None, auth_at=None)

    def clear_latch(self, camera_id):
        M = self._model()
        self._update(camera_id, (M.auth_state.in_(tuple(CLEARABLE_STATES)),),
                     auth_state=UNVERIFIED, attempt_lease_until=None,
                     auth_iface=None, auth_code=None, auth_at=None)


def registered_hosts():
    """camera_driver 에 주소가 있는 카메라 {host: camera_id} (검색 결과의 '이미 등록됨' 판정용)."""
    from aot.config import AOT_DB_PATH
    from aot.databases.models import CameraDriver
    from aot.databases.utils import session_scope
    with session_scope(AOT_DB_PATH) as s:
        return {r.host: r.camera_id for r in s.query(CameraDriver).filter(
            CameraDriver.host.isnot(None), CameraDriver.host != '').all()}
