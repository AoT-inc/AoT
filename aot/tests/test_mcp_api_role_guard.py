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
