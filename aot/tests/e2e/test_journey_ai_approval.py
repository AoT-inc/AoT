# coding=utf-8
"""L2 · J18 — AI 가 올린 제어 요청은 **사람이 결정하기 전에는** 움직이지 않는다.

외부 AI(MCP)가 쓰기 도구를 부르면 실행이 보류되고 AI → 요청 화면에 한 장씩
쌓인다. 이 여정이 지키는 약속은 셋이다:

  1. 요청은 화면에 보이고, 결정 전에는 **실행되지 않는다.**
  2. 결정은 **결정할 자격이 있는 사람만** 한다 — 출력을 직접 켤 수 없는 사람이
     승인을 거쳐 켜게 되면, 승인 게이트가 권한 우회로가 된다.
  3. 승인하면 **적힌 그대로** 실행되고, 거부하면 아무것도 움직이지 않는다.

모델은 쓰지 않는다. 승인 대기는 시드가 만든 행(`MCPConfirmation`)이고, 검사가
보는 것은 모델의 판단이 아니라 게이트다.

2026-09-18 처음 돌렸을 때 2번이 뚫려 있었다 — 게스트가 승인 API 를 불러
출력을 실제로 켰다(off → on). 같은 블루프린트의 MCP 서버 등록·시험(등록한 명령을
셸로 실행)도 로그인만 보고 있었다.
"""
import time

import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

API = '/api/v1/mcp/confirmations'


def _pending(session, base_url):
    """승인 대기 목록 — `{제목: 행}`."""
    resp = session.get(base_url + API, timeout=30)
    assert resp.status_code == 200, f'승인 대기 목록이 HTTP {resp.status_code}'
    return {row['title']: row for row in resp.json().get('pending', [])}


def _row(session, base_url, title):
    row = _pending(session, base_url).get(title)
    assert row, (
        f"승인 대기 '{title}' 가 목록에 없습니다 — 시드를 다시 돌렸는지 확인하세요")
    return row


def _post(session, base_url, path):
    """화면이 보내는 그대로 — JSON 본문 없이 CSRF 머리글만 싣는다."""
    token = session.get(base_url + '/csrf-token', timeout=30).json()['csrf_token']
    return session.post(base_url + path, timeout=30,
                        headers={'X-CSRFToken': token,
                                 'Content-Type': 'application/json'})


def _channel_zero(output_states, output_id):
    return (output_states().get(output_id) or {}).get('0')


def _wait_for(output_states, output_id, expected, timeout_s=25):
    deadline = time.time() + timeout_s
    seen = None
    while time.time() < deadline:
        seen = _channel_zero(output_states, output_id)
        if seen == expected:
            return seen
        time.sleep(1.0)
    return seen


def _set_output(admin_http, base_url, output_id, state):
    """출력을 사람이 누른 것처럼 켜거나 끈다(시작 상태 맞추기·뒷정리)."""
    resp = admin_http.get(
        f'{base_url}/output_mod/{output_id}/0/{state}/sec/0', timeout=30)
    assert resp.status_code == 200, f'출력 {state} 이 HTTP {resp.status_code}'


def _card(page, title):
    return page.locator('#mcp-pending-list .aot-settings-card', has_text=title)


@pytest.fixture
def guest_page(browser, base_url):
    """게스트로 로그인한 브라우저 화면."""
    context = browser.new_context(viewport={'width': 1440, 'height': 900},
                                  locale='ko-KR')
    page = context.new_page()
    page.goto(f'{base_url}/login_password', wait_until='domcontentloaded')
    page.fill('input[name="aot_username"]', F.GUEST_USER)
    page.fill('input[name="aot_password"]', F.GUEST_PASS)
    page.click('input[type="submit"], button[type="submit"]')
    page.wait_for_load_state('domcontentloaded')
    yield page
    context.close()


# --------------------------------------------------------------------------
# 1. 보이고, 결정 전에는 실행되지 않는다
# --------------------------------------------------------------------------
def test_a_waiting_request_shows_up_with_its_decision_buttons(page, base_url):
    page.goto(f'{base_url}/ai', wait_until='domcontentloaded')
    card = _card(page, F.APPROVAL_FOR_APPROVE)
    card.wait_for(state='visible', timeout=20000)
    assert card.locator('[data-approve]').count() == 1, '승인 버튼이 없습니다'
    assert card.locator('[data-reject-conf]').count() == 1, '거부 버튼이 없습니다'


def test_nothing_runs_until_someone_decides(admin_http, base_url):
    """대기 중인 요청은 대기 상태 그대로다 — 목록을 읽는 것만으로 실행되지 않는다."""
    for _ in range(2):   # 목록을 읽는 행위 자체가 무엇을 바꾸면 안 된다
        rows = _pending(admin_http, base_url)
    for title in (F.APPROVAL_FOR_APPROVE, F.APPROVAL_FOR_REJECT,
                  F.APPROVAL_FOR_GUEST):
        assert title in rows, f"'{title}' 가 대기 목록에서 사라졌습니다"


# --------------------------------------------------------------------------
# 2. 결정할 자격이 있는 사람만 결정한다
# --------------------------------------------------------------------------
@pytest.mark.parametrize('action', ('approve', 'reject'))
def test_a_guest_cannot_decide(guest_http, admin_http, base_url, action):
    row = _row(admin_http, base_url, F.APPROVAL_FOR_GUEST)
    resp = _post(guest_http, base_url,
                 f"{API}/{row['confirmation_id']}/{action}")
    assert resp.status_code == 403, (
        f'게스트의 {action} 이 HTTP {resp.status_code} 로 받아들여졌습니다 — '
        f'출력을 직접 켤 수 없는 사람이 승인을 거쳐 켤 수 있습니다')
    assert F.APPROVAL_FOR_GUEST in _pending(admin_http, base_url), (
        '거부 응답을 줬는데 요청이 대기 목록에서 빠졌습니다(처리는 된 것)')


def test_a_guest_sees_the_request_but_no_buttons(guest_page, base_url):
    """보는 것은 된다. 누를 수 없는 버튼은 그리지 않는다."""
    guest_page.goto(f'{base_url}/ai', wait_until='domcontentloaded')
    card = _card(guest_page, F.APPROVAL_FOR_GUEST)
    card.wait_for(state='visible', timeout=20000)
    assert card.locator('button').count() == 0, (
        '게스트 화면에 승인·거부 버튼이 있습니다 — 눌러 보고 나서야 거절당합니다')


def test_a_guest_cannot_read_or_run_mcp_server_config(guest_http, base_url):
    """MCP 서버 설정에는 실행 명령과 환경변수(API 키 자리)가 있다.

    쓰기(등록·시험)는 여기서 부르지 않는다 — 검사가 뚫려 있으면 명령이 실제로
    실행된다. 쓰기 라우트가 역할 표에 빠짐없이 있는지는 단위 검사
    (`test_mcp_api_role_guard.py`)가 본다.
    """
    resp = guest_http.get(base_url + '/api/v1/mcp/servers', timeout=30)
    assert resp.status_code == 403, (
        f'게스트가 MCP 서버 설정을 읽었습니다(HTTP {resp.status_code})')


# --------------------------------------------------------------------------
# 3. 거부하면 움직이지 않고, 승인하면 적힌 그대로 실행된다
# --------------------------------------------------------------------------
def test_rejecting_takes_it_off_the_list(page, admin_http, base_url):
    page.goto(f'{base_url}/ai', wait_until='domcontentloaded')
    card = _card(page, F.APPROVAL_FOR_REJECT)
    card.wait_for(state='visible', timeout=20000)
    with page.expect_response(lambda r: r.url.endswith('/reject'),
                              timeout=20000) as decided:
        card.locator('[data-reject-conf]').click()
    assert decided.value.status == 200, (
        f'거부가 HTTP {decided.value.status} 로 끝났습니다')
    card.wait_for(state='detached', timeout=20000)
    assert F.APPROVAL_FOR_REJECT not in _pending(admin_http, base_url)


def test_approving_runs_exactly_what_was_asked(daemon, page, admin_http,
                                               base_url, output_states):
    """승인 → 확인창 → 출력이 **데몬 기준으로** 켜진다.

    화면의 "실행했습니다" 가 아니라 `/outputstate` 를 본다 — 승인은 성공으로
    보이는데 밸브는 열리지 않은 사고(2026-08-09)가 이 경로에서 있었다.
    """
    row = _row(admin_http, base_url, F.APPROVAL_FOR_APPROVE)
    output_id = row['params']['device_id']
    _set_output(admin_http, base_url, output_id, 'off')
    assert _wait_for(output_states, output_id, 'off') == 'off', (
        '시작 상태를 off 로 만들지 못했습니다')

    try:
        page.goto(f'{base_url}/ai', wait_until='domcontentloaded')
        card = _card(page, F.APPROVAL_FOR_APPROVE)
        card.wait_for(state='visible', timeout=20000)
        card.locator('[data-approve]').click()
        # 물리 동작은 한 번 더 묻는다(되돌릴 수 없으므로).
        with page.expect_response(lambda r: r.url.endswith('/approve'),
                                  timeout=40000) as decided:
            page.locator('#aotConfirmModal.show .aot-confirm-ok').first.click()
        body = decided.value.json()
        assert decided.value.status == 200 and body.get('executed') is True, (
            f'승인 후 실행되지 않았습니다: HTTP {decided.value.status}, '
            f"{body.get('execution')}")

        after = _wait_for(output_states, output_id, 'on')
        assert after == 'on', (
            f"승인은 실행됐다고 하는데 데몬은 '{after}' 라고 답합니다")
        assert F.APPROVAL_FOR_APPROVE not in _pending(admin_http, base_url)
    finally:
        _set_output(admin_http, base_url, output_id, 'off')
