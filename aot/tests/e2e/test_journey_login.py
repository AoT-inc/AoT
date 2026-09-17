# coding=utf-8
"""L2 · J1 — 로그인·로그아웃이 화면에서 실제로 동작하는가.

L0 는 같은 경계를 HTTP 로 본다(익명이 비공개 경로에 닿는가). 여기서 보는
것은 다르다 — **폼이 동작하는가**. 로그인 화면은 전 사용자가 매일 처음
만나는 화면이고, 여기가 깨지면 앱 전체를 못 쓴다. 그런데 개발 중에는 이미
로그인된 세션으로만 다니므로 아무도 지나지 않는다.

이 시나리오만 로그인되지 않은 컨텍스트를 새로 만든다.
"""
import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

# 로그인해야 볼 수 있는 아무 화면. 튕김을 확인하는 데 쓴다.
PROTECTED = '/output'


@pytest.fixture
def anon_page(browser):
    """쿠키가 없는 새 컨텍스트 — storage_state 를 싣지 않는다."""
    context = browser.new_context(
        viewport={'width': 1440, 'height': 900}, locale='ko-KR')
    page = context.new_page()
    yield page
    context.close()


def _login(page, base_url, username, password):
    page.goto(f'{base_url}/login_password', wait_until='domcontentloaded')
    page.fill('input[name="aot_username"]', username)
    page.fill('input[name="aot_password"]', password)
    page.click('input[type="submit"], button[type="submit"]')
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(600)


def test_an_anonymous_visitor_is_sent_to_the_login_screen(anon_page, base_url):
    anon_page.goto(f'{base_url}{PROTECTED}', wait_until='domcontentloaded')
    assert '/login' in anon_page.url, (
        f'로그인하지 않고 {PROTECTED} 에 들어가졌습니다 → {anon_page.url}')
    assert anon_page.locator('input[name="aot_password"]').count() > 0, (
        '로그인 화면인데 비밀번호 칸이 없습니다')


def test_a_bad_sign_in_says_so_on_screen(anon_page, base_url):
    """잘못된 로그인은 막히고, **막혔다고 말해야** 한다.

    조용히 로그인 화면만 다시 그리면 사용자는 무엇이 잘못됐는지 모른다.
    실제로 그랬다 — 로그인 화면은 레이아웃을 상속하지 않아 `showToast` 도
    toastr 도 없었고, flash 가 그 화면에서 통째로 사라지고 있었다.

    **없는 사용자명으로 시도한다.** 실제 계정에 틀린 비밀번호를 넣으면
    실패 카운터가 쌓여(기본 5회) 몇 번째 실행에서 그 계정이 잠기고, 그 뒤
    모든 여정이 로그인부터 실패한다. 없는 이름은 잠글 대상이 없고, 안내
    문구는 실재 여부를 흘리지 않도록 어차피 같다.
    """
    _login(anon_page, base_url, 'e2enosuchuser', 'wrongpassword9999')
    assert '/login' in anon_page.url, (
        f'없는 계정으로 들어가졌습니다 → {anon_page.url}')

    body = anon_page.inner_text('body')
    # 문구를 박지 않는다 — 언어마다 다르다. 실패를 알리는 자리가 있는지만 본다.
    has_notice = (anon_page.locator(
        '.alert, .flash, .toast, [role=alert], .invalid-feedback').count() > 0)
    assert has_notice, (
        f'로그인이 막혔는데 화면에 아무 안내가 없습니다 '
        f'(본문 앞부분: {body[:120]!r})')


def test_signing_in_and_out_works_from_the_screen(anon_page, base_url):
    _login(anon_page, base_url, F.ADMIN_USER, F.ADMIN_PASS)
    assert '/login' not in anon_page.url, (
        f'올바른 비밀번호인데 로그인 화면에 남았습니다 → {anon_page.url}')

    # 들어간 뒤에는 보호된 화면이 열려야 한다.
    anon_page.goto(f'{base_url}{PROTECTED}', wait_until='domcontentloaded')
    assert '/login' not in anon_page.url, (
        f'로그인했는데 {PROTECTED} 가 튕겼습니다 → {anon_page.url}')

    anon_page.goto(f'{base_url}/logout', wait_until='domcontentloaded')
    anon_page.wait_for_timeout(600)

    # 로그아웃 뒤에는 다시 막혀야 한다. 쿠키가 남아 세션이 살아 있는 사고를
    # 잡는 자리다.
    anon_page.goto(f'{base_url}{PROTECTED}', wait_until='domcontentloaded')
    assert '/login' in anon_page.url, (
        f'로그아웃했는데 {PROTECTED} 가 그대로 열립니다 → {anon_page.url}')
