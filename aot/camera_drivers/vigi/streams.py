# coding=utf-8
"""VIGI 일반 RTSP 경로 규칙. 설계 §3 (/stream1 주, /stream2 부, /stream6 MJPEG).

URL 에는 자격 증명을 넣지 않는다. 자격 증명은 열 때 `net_auth.build_stream_url` 대신
`with_credentials` 로 붙이고, 로그에는 `redact` 만 쓴다.
"""
from urllib.parse import quote

from aot.camera_drivers.driver import StreamProfile

PATHS = {'main': '/stream1', 'sub': '/stream2', 'mjpeg': '/stream6'}
SIZES = {'main': (2560, 1440, 'h264'), 'sub': (1280, 720, 'h264'), 'mjpeg': (640, 360, 'mjpeg')}


def rtsp_url(host, port, profile):
    return 'rtsp://%s:%d%s' % (host, int(port), PATHS[profile])


def profiles(host, port):
    out = []
    for name in ('main', 'sub', 'mjpeg'):
        w, h, codec = SIZES[name]
        out.append(StreamProfile(name, rtsp_url(host, port, name), codec, w, h))
    return out


def with_credentials(url, username, password):
    """rtsp://user:pw@host… — 열 때만 쓰는 값이다. 로그·예외에 넘기지 않는다."""
    scheme, rest = url.split('://', 1)
    return '%s://%s:%s@%s' % (scheme, quote(username, safe=''), quote(password, safe=''), rest)


def redact(url):
    """자격 증명이 들어 있을 수 있는 URL 에서 user:pw@ 를 지운다."""
    if '://' not in url:
        return url
    scheme, rest = url.split('://', 1)
    if '@' in rest.split('/', 1)[0]:
        rest = rest.split('@', 1)[1]
    return '%s://%s' % (scheme, rest)
