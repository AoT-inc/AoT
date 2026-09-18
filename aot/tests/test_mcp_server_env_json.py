# -*- coding: utf-8 -*-
"""MCP 서버 환경변수가 문자열 안의 JSON 으로 이중 저장되던 것의 회귀 가드.

배경 — 2026-09-18 E2E. 설정 화면은 입력칸의 JSON **문자열**을 보냈고, 모델
setter 가 그것을 다시 `json.dumps` 해서 `"{\\"KEY\\": ...}"` 로 저장했다. 읽으면
dict 가 아니라 문자열이라 서버 프로세스에 환경변수가 가지 않았고(연결 시험 500),
편집창을 열어 저장할 때마다 한 겹씩 더 감싸졌다.
"""
import json
import os
import sys

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))


def _server(env_json):
    from aot.databases.models.mcp_server import MCPServer
    server = MCPServer(name='t', command='true')   # 세션에 넣지 않는다
    server.env_json = env_json
    return server


def test_a_double_encoded_row_still_reads_as_a_dict():
    once = json.dumps({'AOT_MCP_API_KEY': 'abc'})
    twice = json.dumps(once)
    thrice = json.dumps(twice)
    for stored in (once, twice, thrice):
        assert _server(stored).env_vars == {'AOT_MCP_API_KEY': 'abc'}, stored


def test_garbage_reads_as_empty_not_as_a_string():
    for stored in ('', None, 'not json', json.dumps('plain'), json.dumps([1, 2])):
        assert _server(stored).env_vars == {}, stored


def test_the_route_parses_what_the_screen_sends():
    from aot.aot_flask.routes_mcp_api import _parse_env

    assert _parse_env('{"A": "1"}') == ({'A': '1'}, None)
    assert _parse_env({'A': 1}) == ({'A': '1'}, None)
    assert _parse_env('') == ({}, None)
    assert _parse_env(None) == ({}, None)

    env, error = _parse_env('{"A": ')
    assert env is None and 'JSON' in error
    env, error = _parse_env('["A"]')
    assert env is None and 'object' in error
