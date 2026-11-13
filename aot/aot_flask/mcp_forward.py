# coding=utf-8
"""웹 서버로 들어온 `/mcp` 요청을 MCP 서버(5700)로 넘긴다 — 직접 설치의 nginx 가 하는 일.

직접 설치에서는 nginx 가 `/mcp`·`/.well-known/oauth-protected-resource` 를 5700 으로,
나머지를 웹 앱으로 보낸다(install/aotflask_nginx.conf). 도커의 웹 컨테이너에는 nginx 가 없고
gunicorn 이 바로 받으므로, 그 두 경로가 웹 앱에 떨어져 404 가 났다. 그래서 공개 주소 하나로
MCP 에 닿으려면 앞단 프록시(엣지)마다 경로를 따로 나눠야 했고, 그 설정이 사라지면 끊겼다
(2026-11-09 `https://ai.aotinc.co.kr/mcp` 404).

Flask 라우트가 아니라 WSGI 층에 두는 이유: nginx 처럼 웹 앱을 **건너뛰어야** 하기 때문이다.
Flask 안으로 들어오면 API 키 스코프 가드(읽기 전용 키의 POST 를 403), 세션 파일 생성,
CSRF, 요청 한도가 MCP 요청에 끼어든다. 인증·권한은 MCP 서버가 직접 판정한다.

`AOT_MCP_UPSTREAM`(예: `http://aot_mcp:5700`)이 있을 때만 켜진다. 비어 있으면 아무 일도
하지 않는다 — 직접 설치는 nginx 가 이미 나누므로 이 값을 두지 않는다.
"""
import logging
import os

logger = logging.getLogger('aot.aot_flask.mcp_forward')

ENV_UPSTREAM = 'AOT_MCP_UPSTREAM'

#: nginx 의 `location ^~ /mcp`·`^~ /.well-known/oauth-protected-resource` 와 같은 두 경로.
#: 다만 `/mcpfoo` 처럼 이름만 겹치는 경로까지 잡지 않게 경로 단위로 맞춘다.
FORWARDED_PREFIXES = ('/mcp', '/.well-known/oauth-protected-resource')

#: MCP 서버의 본문 상한(aot_mcp_server.MCP_HTTP_BODY_HARD_LIMIT)과 같은 값. 그 위는 MCP 서버도
#: 받지 않으므로 여기서 먼저 끊는다 — 인증 전 요청이 웹 프로세스 메모리를 채우지 않게.
MAX_BODY_BYTES = 16 * 1024 * 1024

#: 응답을 기다리는 시간. nginx 설정의 proxy_read_timeout 300s 와 맞춘다.
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 300

#: 한 홉에서만 의미가 있는 헤더(RFC 9110 §7.6.1). 넘기지 않는다.
_HOP_BY_HOP = frozenset((
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'proxy-connection', 'te', 'trailer', 'trailers', 'transfer-encoding', 'upgrade',
))


def is_forwarded_path(path):
    """`/mcp`, `/mcp/...`, `/.well-known/oauth-protected-resource[/...]` 이면 True."""
    for prefix in FORWARDED_PREFIXES:
        if path == prefix or path.startswith(prefix + '/'):
            return True
    return False


def _request_headers(environ):
    """WSGI environ → 넘길 요청 헤더. Host 는 원래 값 그대로(MCP 서버의 Origin 검사가 본다)."""
    headers = {}
    for key, value in environ.items():
        if key.startswith('HTTP_'):
            name = key[5:].replace('_', '-').title()
            if name.lower() not in _HOP_BY_HOP:
                headers[name] = value
    if environ.get('CONTENT_TYPE'):
        headers['Content-Type'] = environ['CONTENT_TYPE']

    # nginx 의 $proxy_add_x_forwarded_for 와 같다: 받은 목록 뒤에 이 홉의 상대 주소를 붙인다.
    remote = environ.get('REMOTE_ADDR')
    prior = headers.get('X-Forwarded-For')
    if remote:
        headers['X-Forwarded-For'] = '%s, %s' % (prior, remote) if prior else remote
    headers.setdefault('X-Forwarded-Proto', environ.get('wsgi.url_scheme', 'http'))
    return headers


def _read_body(environ):
    """본문을 읽는다. 상한을 넘으면 None."""
    try:
        length = int(environ.get('CONTENT_LENGTH') or 0)
    except ValueError:
        length = 0
    stream = environ.get('wsgi.input')
    if stream is None:
        return b''
    if length > MAX_BODY_BYTES:
        return None
    if length > 0:
        return stream.read(length)
    # 길이 없이 온 본문(chunked) — gunicorn 이 풀어 준 것을 상한까지만 읽는다.
    data = stream.read(MAX_BODY_BYTES + 1) if environ.get('HTTP_TRANSFER_ENCODING') else b''
    if len(data) > MAX_BODY_BYTES:
        return None
    return data


def _json_error(start_response, status, error):
    body = ('{"error": "%s"}' % error).encode('ascii')
    start_response(status, [('Content-Type', 'application/json'),
                            ('Content-Length', str(len(body))),
                            ('Cache-Control', 'no-store')])
    return [body]


class McpForward(object):
    """두 경로는 MCP 서버로, 나머지는 감싼 앱으로 보내는 WSGI 미들웨어."""

    def __init__(self, app, upstream, session=None):
        self.app = app
        self.upstream = upstream.rstrip('/')
        self._session = session

    def _http(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            # 환경의 HTTP(S)_PROXY 를 타지 않는다 — 같은 compose 망 안의 형제 컨테이너다.
            self._session.trust_env = False
        return self._session

    def __call__(self, environ, start_response):
        if not is_forwarded_path(environ.get('PATH_INFO') or ''):
            return self.app(environ, start_response)
        return self._forward(environ, start_response)

    def _forward(self, environ, start_response):
        body = _read_body(environ)
        if body is None:
            return _json_error(start_response, '413 Payload Too Large', 'payload_too_large')

        url = self.upstream + (environ.get('SCRIPT_NAME') or '') + (environ.get('PATH_INFO') or '')
        if environ.get('QUERY_STRING'):
            url += '?' + environ['QUERY_STRING']

        try:
            resp = self._http().request(
                environ.get('REQUEST_METHOD', 'GET'), url,
                headers=_request_headers(environ), data=body,
                stream=True, allow_redirects=False,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        except Exception as exc:
            logger.warning("[mcp-forward] %s %s → %s 실패: %s",
                           environ.get('REQUEST_METHOD'), environ.get('PATH_INFO'),
                           self.upstream, exc)
            return _json_error(start_response, '502 Bad Gateway', 'mcp_server_unreachable')

        headers = [(k, v) for k, v in resp.raw.headers.items()
                   if k.lower() not in _HOP_BY_HOP]
        start_response('%d %s' % (resp.status_code, resp.reason or ''), headers)

        def _body():
            try:
                # 받은 그대로(압축 풀지 않고) 넘겨야 Content-Length·Content-Encoding 이 맞는다.
                for chunk in resp.raw.stream(64 * 1024, decode_content=False):
                    yield chunk
            finally:
                resp.close()
        return _body()


def install(app):
    """`AOT_MCP_UPSTREAM` 이 있으면 app.wsgi_app 의 가장 바깥에 끼운다."""
    upstream = (os.environ.get(ENV_UPSTREAM) or '').strip()
    if not upstream:
        return False
    app.wsgi_app = McpForward(app.wsgi_app, upstream)
    logger.info("[mcp-forward] /mcp, /.well-known/oauth-protected-resource → %s", upstream)
    return True
