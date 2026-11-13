# coding=utf-8
"""웹 서버의 `/mcp` 전달(aot/aot_flask/mcp_forward.py) — 도커에서 nginx 대신 MCP 서버로 넘기는 층."""
import io

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

from aot.aot_flask import mcp_forward
from aot.aot_flask.mcp_forward import McpForward, is_forwarded_path


class _FakeRaw(object):
    def __init__(self, body, headers):
        self._body = body
        self.headers = headers

    def stream(self, _size, decode_content=True):
        assert decode_content is False   # 받은 그대로 넘겨야 길이·인코딩이 맞는다
        yield self._body


class _FakeResp(object):
    def __init__(self, status, reason, body, headers):
        self.status_code = status
        self.reason = reason
        self.raw = _FakeRaw(body, headers)
        self.closed = False

    def close(self):
        self.closed = True


class _FakeSession(object):
    def __init__(self, resp=None, exc=None):
        self.resp = resp
        self.exc = exc
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.exc:
            raise self.exc
        return self.resp


def _inner_app(environ, start_response):
    return Response('web:' + environ['PATH_INFO'])(environ, start_response)


def _client(session):
    return Client(McpForward(_inner_app, 'http://aot_mcp:5700/', session=session))


@pytest.mark.parametrize('path, expected', [
    ('/mcp', True),
    ('/mcp/info', True),
    ('/mcp/tools/call', True),
    ('/.well-known/oauth-protected-resource', True),
    ('/.well-known/oauth-protected-resource/mcp', True),
    ('/mcpfoo', False),                          # 이름만 겹치는 경로는 웹 앱 것
    ('/aot-mcp/status', False),
    ('/.well-known/oauth-authorization-server', False),   # 내장 인가 서버는 웹 앱이 답한다
    ('/.well-known/jwks.json', False),
    ('/', False),
])
def test_forwarded_paths_match_nginx(path, expected):
    assert is_forwarded_path(path) is expected


def test_other_paths_stay_in_web_app():
    session = _FakeSession()
    resp = _client(session).get('/settings/general')
    assert resp.get_data(as_text=True) == 'web:/settings/general'
    assert session.calls == []


def test_post_is_forwarded_with_body_headers_and_query():
    upstream = _FakeResp(401, 'UNAUTHORIZED', b'{"error":"unauthorized"}', {
        'Content-Type': 'application/json',
        'Content-Length': '24',
        'WWW-Authenticate': 'Bearer resource_metadata="https://x/.well-known/oauth-protected-resource/mcp"',
        'Connection': 'close',
    })
    session = _FakeSession(resp=upstream)
    resp = _client(session).post(
        '/mcp?tools=lite', data=b'{"jsonrpc":"2.0"}',
        headers={'Content-Type': 'application/json', 'Host': 'ai.example.com',
                 'X-API-KEY': 'abc', 'Authorization': 'Bearer t',
                 'X-Forwarded-For': '1.2.3.4', 'X-Forwarded-Proto': 'https',
                 'Origin': 'https://ai.example.com', 'Connection': 'keep-alive'},
        environ_base={'REMOTE_ADDR': '100.96.46.85'})

    method, url, kw = session.calls[0]
    assert method == 'POST'
    assert url == 'http://aot_mcp:5700/mcp?tools=lite'
    assert kw['data'] == b'{"jsonrpc":"2.0"}'
    assert kw['allow_redirects'] is False
    sent = kw['headers']
    assert sent['Host'] == 'ai.example.com'          # MCP 서버의 Origin 검사가 원래 호스트를 본다
    assert sent['X-Api-Key'] == 'abc'
    assert sent['Authorization'] == 'Bearer t'
    assert sent['Origin'] == 'https://ai.example.com'
    assert sent['X-Forwarded-For'] == '1.2.3.4, 100.96.46.85'
    assert sent['X-Forwarded-Proto'] == 'https'
    assert sent['Content-Type'] == 'application/json'
    assert 'Connection' not in sent

    assert resp.status_code == 401
    assert resp.get_data() == b'{"error":"unauthorized"}'
    assert resp.headers['WWW-Authenticate'].startswith('Bearer resource_metadata=')
    assert 'Connection' not in resp.headers
    assert upstream.closed


def test_well_known_get_is_forwarded():
    session = _FakeSession(resp=_FakeResp(200, 'OK', b'{}', {'Content-Type': 'application/json'}))
    resp = _client(session).get('/.well-known/oauth-protected-resource/mcp')
    assert resp.status_code == 200
    assert session.calls[0][1] == 'http://aot_mcp:5700/.well-known/oauth-protected-resource/mcp'
    assert session.calls[0][2]['headers']['X-Forwarded-Proto'] == 'http'


def test_unreachable_mcp_server_is_502():
    session = _FakeSession(exc=ConnectionError('refused'))
    resp = _client(session).post('/mcp', data=b'{}')
    assert resp.status_code == 502
    assert resp.get_json() == {'error': 'mcp_server_unreachable'}


def test_oversized_body_is_rejected_before_forwarding(monkeypatch):
    monkeypatch.setattr(mcp_forward, 'MAX_BODY_BYTES', 8)
    session = _FakeSession()
    resp = _client(session).post('/mcp', data=b'0123456789')
    assert resp.status_code == 413
    assert session.calls == []


def test_chunked_body_is_read_up_to_limit(monkeypatch):
    monkeypatch.setattr(mcp_forward, 'MAX_BODY_BYTES', 8)
    environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/mcp', 'HTTP_TRANSFER_ENCODING': 'chunked',
               'wsgi.input': io.BytesIO(b'small')}
    assert mcp_forward._read_body(environ) == b'small'
    environ['wsgi.input'] = io.BytesIO(b'0123456789')
    assert mcp_forward._read_body(environ) is None


class _App(object):
    def __init__(self):
        self.wsgi_app = _inner_app


def test_install_needs_upstream(monkeypatch):
    app = _App()
    monkeypatch.delenv(mcp_forward.ENV_UPSTREAM, raising=False)
    assert mcp_forward.install(app) is False
    assert app.wsgi_app is _inner_app

    monkeypatch.setenv(mcp_forward.ENV_UPSTREAM, '  ')
    assert mcp_forward.install(app) is False

    monkeypatch.setenv(mcp_forward.ENV_UPSTREAM, 'http://aot_mcp:5700')
    assert mcp_forward.install(app) is True
    assert isinstance(app.wsgi_app, McpForward)
    assert app.wsgi_app.app is _inner_app
