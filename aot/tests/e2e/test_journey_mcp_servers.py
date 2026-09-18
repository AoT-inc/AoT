# coding=utf-8
"""L2 · P2 — 외부 MCP 서버를 등록하고, 설정이 그대로 돌아오고, 붙고, 지워진다.

등록 대상은 앱에 들어 있는 AoT MCP 서버 자신이다(인증을 끄는 환경변수를 준다).
그래야 "연결 시험 → 도구 목록" 까지 외부 없이 끝까지 간다.

2026-09-18 처음 돌렸을 때:
  * 화면에서 넣은 환경변수가 **문자열 안의 JSON** 으로 이중 저장됐다 — 편집창을
    열면 따옴표가 한 겹 더 붙어 있고, 연결 시험은 500 이었다(서버에 환경변수가
    가지 않았다).
  * 로그인만 하면(게스트도) 서버의 실행 명령과 환경변수를 읽고 서버를 등록할 수
    있었다 — 등록한 명령은 셸로 실행된다.
"""
import json

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e

API = '/api/v1/mcp/servers'


def _row(page, name):
    return page.locator('#mcp-server-list [data-id]', has_text=name)


def _open(page, base_url):
    page.goto(f'{base_url}/api/v1/mcp/servers_page', wait_until='domcontentloaded')
    page.wait_for_selector('#mcp-server-list [data-id], #mcp-server-list .aot-settings-sub',
                           timeout=20000)


def test_register_reopen_connect_and_delete_a_server(page, admin_http, base_url):
    _open(page, base_url)

    # 등록
    page.click('#btn-add-server')
    page.wait_for_selector('#modal-mcp-server.show', timeout=10000)
    page.fill('#server-name', F.MCP_SERVER_NAME)
    page.fill('#server-command', F.MCP_SERVER_COMMAND)
    page.fill('#server-env', F.MCP_SERVER_ENV)
    with page.expect_response(lambda r: r.url.endswith(API)
                              and r.request.method == 'POST') as created:
        page.click('#btn-save-server')
    assert created.value.status == 201, (
        f'등록이 HTTP {created.value.status}: {created.value.text()[:200]}')
    server_id = created.value.json()['unique_id']
    _row(page, F.MCP_SERVER_NAME).wait_for(timeout=10000)

    # 다시 열기 — 환경변수가 넣은 그대로(객체) 돌아온다
    _row(page, F.MCP_SERVER_NAME).locator('button[data-act="edit"]').click()
    page.wait_for_selector('#modal-mcp-server.show', timeout=10000)
    shown = page.input_value('#server-env')
    assert json.loads(shown) == json.loads(F.MCP_SERVER_ENV), (
        f'편집창의 환경변수가 넣은 것과 다릅니다: {shown!r} — 문자열로 한 겹 더 '
        f'감싸여 저장됐습니다')
    page.click('#modal-mcp-server [data-dismiss="modal"]')
    page.wait_for_timeout(500)

    # 연결 시험 — 환경변수가 서버 프로세스에 가야 도구 목록이 온다
    tested = admin_http.post(f'{base_url}{API}/{server_id}/test', timeout=120,
                             headers=csrf_headers(admin_http, base_url))
    body = tested.json()
    assert tested.status_code == 200 and body.get('status') == 'success', (
        f'연결 시험이 실패했습니다: HTTP {tested.status_code}, {str(body)[:300]}')
    assert body.get('tools'), '연결은 됐는데 도구가 하나도 오지 않았습니다'

    # 지우기 — 앱 공용 확인창을 지나 목록에서 사라진다
    _row(page, F.MCP_SERVER_NAME).locator('button[data-act="edit"]').click()
    page.wait_for_selector('#modal-mcp-server.show', timeout=10000)
    page.click('#btn-delete-server')
    with page.expect_response(lambda r: server_id in r.url
                              and r.request.method == 'DELETE') as removed:
        page.locator('#aotConfirmModal.show .aot-confirm-ok').first.click()
    assert removed.value.status == 200
    _row(page, F.MCP_SERVER_NAME).wait_for(state='detached', timeout=10000)


def test_a_bad_environment_is_refused_with_a_reason(admin_http, base_url):
    resp = admin_http.post(f'{base_url}{API}', timeout=30,
                           headers=csrf_headers(admin_http, base_url),
                           json={'name': 'E2E Bad Env', 'command': 'true',
                                 'env_json': '{"A": '})
    assert resp.status_code == 400 and 'JSON' in resp.text, (
        f'잘못된 환경변수가 HTTP {resp.status_code} 로 처리됐습니다 — 조용히 저장되면 '
        f'API 키가 사라진다')
    names = [s['name'] for s in admin_http.get(f'{base_url}{API}', timeout=30).json()]
    assert 'E2E Bad Env' not in names


def test_who_can_see_and_change_server_config(guest_http, monitor_http, base_url):
    # 게스트 — 목록도 못 본다
    assert guest_http.get(f'{base_url}{API}', timeout=30).status_code == 403
    # 모니터 — 목록은 보되 실행 명령·환경변수(API 키 자리)는 없다
    rows = monitor_http.get(f'{base_url}{API}', timeout=30)
    assert rows.status_code == 200
    leaked = [r['name'] for r in rows.json() if r.get('command') or r.get('env_json')]
    assert not leaked, f'모니터에게 서버 명령·환경변수가 보입니다: {leaked}'
    # 모니터 — 등록은 못 한다
    resp = monitor_http.post(f'{base_url}{API}', timeout=30,
                             headers=csrf_headers(monitor_http, base_url),
                             json={'name': 'E2E Monitor Server', 'command': 'true'})
    assert resp.status_code == 403, f'모니터의 서버 등록이 HTTP {resp.status_code}'
