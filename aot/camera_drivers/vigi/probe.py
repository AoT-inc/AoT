# coding=utf-8
"""호스트 하나를 식별한다 — 포트 탐침 + 무인증 doAuth 1회. 설계 §8, §6.1-7.

비밀은 보내지 않는다. 20443 이 열렸을 때만 `doAuth(params:null)` 을 **1회** 보내고, -10020 과
authenticate.realm·nonce 가 오면 VIGI(OpenAPI 켜짐)로 본다. 인증서는 이 단계에서 검증하지 않는다.
결과 kind: 'vigi' | 'rtsp_only'(554 만, VIGI 인지 모름) | None(둘 다 아님 — 목록에 내지 않는다).
"""
import json
import socket

from aot.camera_drivers.vigi import errors as E
from aot.camera_drivers.vigi import openapi as O

OPENAPI_PORT = 20443
RTSP_PORT = 554
CONNECT_TIMEOUT_S = 0.5
DOAUTH_TIMEOUT_S = 2.0


def port_open(host, port, timeout=CONNECT_TIMEOUT_S):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def identify_openapi(host, port=OPENAPI_PORT, transport=None, timeout=DOAUTH_TIMEOUT_S):
    """무인증 doAuth 1회. VIGI 응답이면 {'realm','nonce_seen'} 를, 아니면 None.
    nonce 값은 돌려주지 않는다(쓸 곳이 없다)."""
    post = transport or O.https_post
    body = json.dumps({'method': 'doAuth', 'params': None}).encode()
    try:
        _status, raw, _peer = post(host, port, '/', body, None, timeout)
        obj = json.loads(raw.decode('utf-8', 'replace')) if raw else None
    except (O.TransportError, O.CertMismatch, ValueError):
        return None
    if not isinstance(obj, dict) or O._code_of(obj) != E.ERR_AUTH_FAILED:
        return None
    ch = O._find_challenge(obj)
    if not (ch.get('realm') and ch.get('nonce')):
        return None
    return {'realm': str(ch['realm'])[:64]}


def probe_host(host, connect=port_open, transport=None, api_port=OPENAPI_PORT, rtsp_port=RTSP_PORT):
    """host 하나의 식별 결과 dict 또는 None. (포트 인자는 시험용)"""
    has_api = connect(host, api_port)
    has_rtsp = connect(host, rtsp_port)
    if has_api:
        ident = identify_openapi(host, port=api_port, transport=transport)
        if ident:
            return {'host': host, 'kind': 'vigi', 'rtsp': has_rtsp, 'realm': ident['realm']}
    if has_rtsp:
        return {'host': host, 'kind': 'rtsp_only', 'rtsp': True}
    return None
