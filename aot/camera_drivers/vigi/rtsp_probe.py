# coding=utf-8
"""RTSP DESCRIBE 로 인증 결과를 직접 확인한다. 설계 §6.1-1·5.

OpenCV(FFmpeg)는 열기에 실패한 이유가 401 인지 네트워크인지 알려 주지 않는다. 그래서 검증 안 된
자격 증명을 처음 쓸 때(와 열기에 실패한 뒤 진단할 때) 이 탐침이 자격 증명을 **정확히 한 번** 제시한다.
인증 없는 첫 DESCRIBE 는 챌린지를 받기 위한 것이다. 카메라가 Digest(MD5/SHA-256)를 내면 Digest 로,
Basic 만 내면 Basic 으로 응답한다.

결과: ('ok'|'auth_failed'|'network'|'other', status_code|None). 비밀은 로그·예외에 남기지 않는다.
"""
import base64
import hashlib
import re
import socket
import uuid


def _read_response(sock, limit=65536):
    buf = b''
    while b'\r\n\r\n' not in buf and len(buf) < limit:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    head = buf.split(b'\r\n\r\n', 1)[0].decode('latin-1')
    lines = head.split('\r\n')
    m = re.match(r'RTSP/\d\.\d\s+(\d{3})', lines[0] if lines else '')
    status = int(m.group(1)) if m else None
    headers = {}
    for ln in lines[1:]:
        if ':' in ln:
            k, v = ln.split(':', 1)
            headers.setdefault(k.strip().lower(), []).append(v.strip())
    return status, headers


def _parse_params(value):
    return {k.lower(): (a or b) for k, a, b in
            re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', value)}


def _h(algo, text):
    name = 'sha256' if 'sha-256' in algo.lower() or 'sha256' in algo.lower() else 'md5'
    return hashlib.new(name, text.encode()).hexdigest()


def _authorization(challenges, method, uri, username, password):
    digest = next((c for c in challenges if c.lower().startswith('digest')), None)
    if digest:
        p = _parse_params(digest[len('digest'):])
        algo = p.get('algorithm', 'MD5')
        realm, nonce = p.get('realm', ''), p.get('nonce', '')
        ha1 = _h(algo, '%s:%s:%s' % (username, realm, password))
        ha2 = _h(algo, '%s:%s' % (method, uri))
        if 'auth' in p.get('qop', ''):
            nc, cnonce = '00000001', uuid.uuid4().hex[:16]
            resp = _h(algo, '%s:%s:%s:%s:auth:%s' % (ha1, nonce, nc, cnonce, ha2))
            extra = ', qop=auth, nc=%s, cnonce="%s"' % (nc, cnonce)
        else:
            resp = _h(algo, '%s:%s:%s' % (ha1, nonce, ha2))
            extra = ''
        return ('Digest username="%s", realm="%s", nonce="%s", uri="%s", response="%s", '
                'algorithm=%s%s' % (username, realm, nonce, uri, resp, algo, extra))
    if any(c.lower().startswith('basic') for c in challenges):
        return 'Basic ' + base64.b64encode(('%s:%s' % (username, password)).encode()).decode()
    return None


def describe(host, port, path, username, password, timeout=5.0):
    """(result, status). 자격 증명은 챌린지에 대한 응답으로 한 번만 보낸다."""
    uri = 'rtsp://%s:%d%s' % (host, int(port), path)
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(('DESCRIBE %s RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\n'
                          '\r\n' % uri).encode())
            status, hdr = _read_response(sock)
            if status == 200:
                return 'ok', 200            # 인증이 필요 없는 스트림
            if status != 401:
                return 'other', status
            auth = _authorization(hdr.get('www-authenticate', []), 'DESCRIBE', uri,
                                  username, password)
            if auth is None:
                return 'other', 401         # 모르는 인증 방식 — 자격 증명을 보내지 않는다
            sock.sendall(('DESCRIBE %s RTSP/1.0\r\nCSeq: 2\r\nAccept: application/sdp\r\n'
                          'Authorization: %s\r\n\r\n' % (uri, auth)).encode())
            status, _ = _read_response(sock)
    except (OSError, socket.timeout):
        return 'network', None
    if status == 200:
        return 'ok', 200
    if status in (401, 403):
        return 'auth_failed', status
    return 'other', status
