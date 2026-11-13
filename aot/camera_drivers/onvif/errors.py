# coding=utf-8
"""ONVIF 오류(HTTP 상태·SOAP Fault) → 분류. 범위 문서 §4, 설계 §6.1.

철자는 모의 서버 기준이다(실카메라 확인은 O6). 모르는 값은 안전한 쪽으로 처리한다:
인증 단계의 모르는 응답은 래치, 인증 뒤 호출의 모르는 Fault 는 DEVICE(래치 아님).
확정할 값은 이 파일 한 곳에 모은다.
"""
import re

from aot.camera_drivers.driver import ErrorClass

_LOCKED = re.compile(r'lock', re.I)
_LIMIT = re.compile(r'too many|max(imum)?\b.*(session|client|connection|user)|session limit', re.I)
# SOAP 1.2 Subcode 의 로컬 이름 (ter:NotAuthorized 등). 접두사는 무시한다.
_AUTH_SUBCODES = frozenset({'notauthorized', 'sendernotauthorized', 'failedauthentication',
                            'authfailed', 'invalidsecuritytoken', 'failedcheck'})
_UNSUPPORTED_SUBCODES = frozenset({'actionnotsupported', 'optionalactionnotimplemented',
                                   'notimplemented'})


def classify_http(status) -> ErrorClass:
    """HTTP 상태만으로 판단할 수 있는 것. 200 이면 NONE."""
    if status == 401:
        return ErrorClass.AUTH_FAILED
    if status in (429, 503):
        return ErrorClass.CLIENT_LIMIT
    if status and status >= 400:
        return ErrorClass.DEVICE
    return ErrorClass.NONE


def _local(name):
    return (name or '').rsplit(':', 1)[-1].lower()


def classify_fault(subcodes, reason='') -> ErrorClass:
    """SOAP Fault 의 Subcode 로컬 이름들과 사유 문자열 → ErrorClass."""
    names = {_local(s) for s in subcodes}
    text = ' '.join([reason or ''] + list(subcodes))
    if _LOCKED.search(text):
        return ErrorClass.LOCKED
    if _LIMIT.search(text):
        return ErrorClass.CLIENT_LIMIT
    if names & _AUTH_SUBCODES:
        return ErrorClass.AUTH_FAILED
    if names & _UNSUPPORTED_SUBCODES:
        return ErrorClass.UNSUPPORTED
    return ErrorClass.DEVICE


def safe_token(s, n=48):
    """로그·메시지에 넣을 Fault 식별자: 영숫자·콜론·점·밑줄만, 길이 제한. 사유 원문은 넣지 않는다."""
    return re.sub(r'[^A-Za-z0-9:._-]', '', s or '')[:n]
