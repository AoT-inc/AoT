# coding=utf-8
"""감사로그 기록 헬퍼.

사용법:
    from aot.utils.audit import audit_log
    audit_log('settings.change', target_type='Misc', before=old, after=new)

설계 원칙 두 가지:

1. **감사로그 실패가 본 기능을 막지 않는다.** 기록은 부가 기능이므로 어떤
   예외도 삼키고 로거로만 남긴다 — 감사 테이블 문제로 로그인이나 장치 제어가
   막히면 그게 더 큰 사고다.
2. **행위자 정보는 호출부가 몰라도 된다.** Flask 요청 문맥이 있으면
   current_user와 IP를 자동으로 채운다. 데몬(요청 문맥 없음)에서 호출하면
   그냥 비워둔 채 기록한다.
"""
import json
import logging

from aot.databases.models import AuditLog
from aot.aot_flask.extensions import db
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)

# 감사 대상 행위 이름. 문자열 오타로 조회가 새는 걸 막기 위해 상수로 둔다.
LOGIN_SUCCESS = 'login.success'
LOGIN_FAILURE = 'login.failure'
LOGIN_LOCKED = 'login.locked'
LOGOUT = 'logout'
PASSWORD_RESET = 'password.reset'
USER_CREATE = 'user.create'
USER_MODIFY = 'user.modify'
USER_DELETE = 'user.delete'
SETTINGS_CHANGE = 'settings.change'
OUTPUT_CONTROL = 'output.control'
DATA_EXPORT = 'data.export'
DATA_IMPORT = 'data.import'
API_KEY_ISSUE = 'apikey.issue'
API_KEY_REVOKE = 'apikey.revoke'
API_KEY_URL_AUTH = 'apikey.url_auth'   # 폐기 예정 경로 사용 추적 (S15)
REMOTE_TOKEN_ISSUE = 'remote.token_issue'


def _current_actor():
    """(user_id, username, ip) — 요청 문맥이 없으면 (None, None, None)."""
    try:
        from flask import has_request_context, request
        import flask_login

        if not has_request_context():
            return None, None, None

        ip = (request.environ.get('HTTP_X_FORWARDED_FOR')
              or request.remote_addr
              or None)
        # X-Forwarded-For 는 프록시 체인이라 여러 개일 수 있다 — 첫 값만.
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        user = getattr(flask_login, 'current_user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            return getattr(user, 'id', None), getattr(user, 'name', None), ip
        return None, None, ip
    except Exception:
        return None, None, None


def _as_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def audit_log(action, target_type=None, target_id=None, target_name=None,
              result='success', detail=None, before=None, after=None,
              user_id=None, username=None, ip_address=None):
    """감사로그 한 줄 기록. 실패해도 예외를 올리지 않는다.

    :param action: 위 상수 중 하나(또는 'domain.verb' 형식 문자열)
    :param result: 'success' | 'failure'
    :param before/after: 변경 전후 값(dict 등). JSON 문자열로 저장된다.
    :param user_id/username/ip_address: 명시하면 자동 추출을 덮어쓴다
        (로그인 실패처럼 아직 인증되지 않은 주체를 남길 때 사용)
    """
    try:
        auto_user_id, auto_username, auto_ip = _current_actor()

        entry = AuditLog()
        entry.timestamp = utc_now()
        entry.user_id = user_id if user_id is not None else auto_user_id
        entry.username = username if username is not None else auto_username
        entry.ip_address = ip_address if ip_address is not None else auto_ip
        entry.action = action
        entry.target_type = target_type
        entry.target_id = str(target_id) if target_id is not None else None
        entry.target_name = target_name
        entry.result = result
        entry.detail = detail
        entry.before_json = _as_json(before)
        entry.after_json = _as_json(after)

        db.session.add(entry)
        db.session.commit()
    except Exception:
        # 본 기능을 막지 않는다 (모듈 docstring 원칙 1)
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.exception("감사로그 기록 실패: action=%s", action)


def purge_old_audit_logs(retention_days=None):
    """보존기간이 지난 감사로그 삭제. 기본값은 config.AUDIT_LOG_RETENTION_DAYS.

    `ai_scheduler_service._audit_log_purge_job` 이 하루 1회 호출한다.
    이 정리를 붙이지 않으면 audit_log 테이블이 무한히 커진다 — 보존기간 정책이
    기관마다 다르더라도 "일단 안 지움"은 선택지가 아니라서, 법정 최소선인 1년을
    기본값으로 두고 config 상수로 조정하게 했다.

    :param retention_days: None 이면 config 기본값. 0 이하면 정리하지 않는다.
    """
    from datetime import timedelta

    if retention_days is None:
        from aot.config import AUDIT_LOG_RETENTION_DAYS
        retention_days = AUDIT_LOG_RETENTION_DAYS

    if retention_days is None or retention_days <= 0:
        logger.debug("감사로그 보존기간이 0 이하 — 자동 정리를 건너뜁니다")
        return 0

    try:
        cutoff = utc_now() - timedelta(days=retention_days)
        deleted = AuditLog.query.filter(AuditLog.timestamp < cutoff).delete()
        db.session.commit()
        if deleted:
            logger.info("감사로그 %s건 삭제 (보존 %s일 초과)", deleted, retention_days)
        return deleted
    except Exception:
        db.session.rollback()
        logger.exception("감사로그 정리 실패")
        return 0
