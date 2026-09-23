# -*- coding: utf-8 -*-
"""`/api/v1/mcp` 의 역할 검사 표가 라우트와 어긋나지 않는지.

배경 — 2026-09-18. 이 블루프린트에는 `login_required` 만 있어서 게스트가 AI 의
물리 제어 요청을 승인해 출력을 켤 수 있었고, MCP 서버를 등록·시험(등록한 명령을
셸로 실행)할 수 있었다. 역할 검사는 이제 블루프린트의 `before_request` 가 엔드포인트
이름표(`_REQUIRED_PERMISSION`)로 한다.

표로 두면 두 가지가 조용히 무너진다. 이 검사가 둘 다 잡는다:
  - 새 쓰기 라우트를 더하고 표에 적지 않으면 **다시 로그인만으로 열린다.**
  - 표의 이름을 잘못 적으면(함수 이름과 다르면) 그 줄은 아무것도 막지 않는다.

실제로 막히는지(게스트 403, 출력이 움직이지 않음)는 E2E
`test_journey_ai_approval.py` 가 본다.
"""
import os
import sys

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))

_READ_ONLY = {'GET', 'HEAD', 'OPTIONS'}


def _rules():
    from flask import Flask
    from aot.aot_flask import routes_mcp_api

    app = Flask(__name__)
    app.register_blueprint(routes_mcp_api.blueprint)
    return routes_mcp_api, [r for r in app.url_map.iter_rules()
                            if r.endpoint.startswith('routes_mcp_api.')]


def test_every_write_route_names_a_permission():
    module, rules = _rules()
    guarded = set(module._REQUIRED_PERMISSION) | set(module._READ_WRITE_ENDPOINTS)
    open_writes = sorted(
        f'{r.rule} {sorted(r.methods - _READ_ONLY)}'
        for r in rules
        if (r.methods - _READ_ONLY) and r.endpoint not in guarded)
    assert not open_writes, (
        '역할 검사 표에 없는 쓰기 라우트가 있습니다 — 로그인만 하면 누구나 '
        f'부를 수 있습니다: {open_writes}')


def test_every_table_entry_is_a_real_endpoint():
    module, rules = _rules()
    endpoints = {r.endpoint for r in rules}
    stale = sorted((set(module._REQUIRED_PERMISSION)
                    | set(module._READ_WRITE_ENDPOINTS)) - endpoints)
    assert not stale, (
        f'역할 검사 표의 이름이 실제 엔드포인트와 다릅니다(아무것도 막지 않음): {stale}')


def test_call_quality_needs_view_logs():
    """호출 품질 지표는 감사 목록과 같은 권한(view_logs)으로 막힌다."""
    from aot.aot_flask import routes_mcp_api
    assert (routes_mcp_api._REQUIRED_PERMISSION['routes_mcp_api.mcp_call_quality']
            == 'view_logs')


def _guarded_client(monkeypatch, allowed):
    import flask_login
    from flask import Flask
    from aot.aot_flask import routes_mcp_api
    from aot.aot_flask.utils import utils_general

    from flask_babel import Babel

    app = Flask(__name__)
    app.secret_key = 'test'
    Babel(app)                      # 403 본문이 gettext 를 쓴다
    lm = flask_login.LoginManager(app)

    class _User(flask_login.UserMixin):
        id = 'guest'

    lm.request_loader(lambda req: _User())
    app.register_blueprint(routes_mcp_api.blueprint)
    monkeypatch.setattr(utils_general, 'user_has_permission',
                        lambda perm, silent=False: allowed)
    return app.test_client()


def test_call_quality_refuses_a_role_without_view_logs(monkeypatch):
    client = _guarded_client(monkeypatch, allowed=False)
    assert client.get('/api/v1/mcp/quality').status_code == 403


def test_call_quality_response_has_no_identity(monkeypatch):
    """실제 summarize 출력이 라우트를 지나 나간 본문에 신원 정보가 없는가.

    행에는 agent_id(로그인 이름)·세션 열쇠·UUID 가 들어 있다. 계산을 흉내 내지
    않고 진짜 summarize 를 거친 값을 돌려받아 본문 전체를 뒤진다.
    """
    from datetime import datetime, timedelta
    from aot.mcp_server import quality

    uuid = '0f8b6c1e-4a52-4c3e-9d2a-7b1e5f3a9c01'
    t0 = datetime(2026, 9, 1, 12, 0, 0)

    def _row(sec, tool, **kw):
        r = {'timestamp': t0 + timedelta(seconds=sec),
             'agent_id': 'user:alice/claude', 'tool_name': tool,
             'permission': 'read', 'result_summary': 'success',
             'duration_ms': 120, 'session_key': 'deadbeefcafef00d',
             'transport': 'mcp_http', 'via_drawer': False,
             'response_tokens': 10, 'response_bytes': 20, 'truncated': False,
             'call_state': 'executed', 'result_items': 1,
             'params_json': '{"device_id": "%s"}' % uuid, 'reason': 'why'}
        r.update(kw)
        return r

    rows = [_row(0, 'open_drawer'), _row(5, 'search_devices', via_drawer=True),
            _row(9, 'get_output_state', session_key=None)]
    seen = {}

    def _compute(days, transport):
        seen['args'] = (days, transport)
        out = quality.summarize(rows)
        out.update({'days': days, 'transport': transport})
        return out

    monkeypatch.setattr(quality, 'compute_quality', _compute)
    client = _guarded_client(monkeypatch, allowed=True)
    r = client.get('/api/v1/mcp/quality?days=30&transport=mcp_http')
    assert r.status_code == 200
    assert seen['args'] == (30, 'mcp_http')
    body = r.get_json()
    assert body['quality']['days'] == 30
    assert body['quality']['overall']['calls'] == 3
    text = r.get_data(as_text=True)
    for leaked in ('alice', 'deadbeefcafef00d', uuid, 'params_json', 'why',
                   'agent_id', 'session_key', '"reason"'):
        assert leaked not in text, leaked
