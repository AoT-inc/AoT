# coding=utf-8
"""RTSP 경로의 인증 허가 — OpenAPI 와 같은 래치·임대를 쓴다. 설계 §6.1-4·5.

- 검증 안 된 자격 증명(FIRST_TRY): 탐침(DESCRIBE)이 자격 증명을 한 번 제시해 결과를 직접 확인한다.
  401/403 이면 즉시 래치(양쪽 인터페이스). 성공하면 verified_fp 를 기록한다.
- 검증된 자격 증명(REAUTH): 탐침 없이 바로 열게 한다. 열기에 실패하면 `diagnose` 로 **한 번만** 이유를 본다.
"""
from aot.camera_drivers.auth_guard import FIRST_TRY, Permit, credential_fp
from aot.camera_drivers.driver import ErrorClass
from aot.camera_drivers.vigi import rtsp_probe, streams


class RtspDenied(Exception):
    """열면 안 된다/열 수 없다. `fatal` 이면 재시도하지 않는다(래치·거부)."""

    def __init__(self, reason, fatal):
        super().__init__(reason)
        self.reason = reason
        self.fatal = fatal


def authorize(guard, camera_id, credential, host, port, fp_key, profile='sub', timeout=5.0):
    """열어도 되는지 판정한다. 허가면 반환, 아니면 RtspDenied. 카메라 접촉은 탐침 한 번뿐이다."""
    fp = credential_fp(credential.username, credential.password, fp_key)
    permit = guard.begin(camera_id, fp, 'rtsp')
    if not isinstance(permit, Permit):
        raise RtspDenied(permit.reason, True)
    if permit.kind != FIRST_TRY:
        return permit
    result, status = rtsp_probe.describe(host, port, streams.PATHS[profile],
                                         credential.username, credential.password, timeout)
    if result == 'ok':
        guard.report_success(permit)
        return permit
    if result == 'auth_failed':
        guard.report_failure(permit, ErrorClass.AUTH_FAILED, status)
        raise RtspDenied('auth_failed', True)
    guard.report_failure(permit, ErrorClass.NETWORK)
    raise RtspDenied(result, False)


def diagnose(guard, camera_id, credential, host, port, fp_key, profile='sub', timeout=5.0):
    """검증된 자격 증명으로 연 스트림이 실패한 뒤 이유를 한 번 본다. 401 이면 래치한다."""
    fp = credential_fp(credential.username, credential.password, fp_key)
    permit = guard.begin(camera_id, fp, 'rtsp', reauth=True)
    if not isinstance(permit, Permit):
        raise RtspDenied(permit.reason, True)
    result, status = rtsp_probe.describe(host, port, streams.PATHS[profile],
                                         credential.username, credential.password, timeout)
    if result == 'auth_failed':
        guard.report_failure(permit, ErrorClass.AUTH_FAILED, status)
        raise RtspDenied('auth_failed', True)
    return result
