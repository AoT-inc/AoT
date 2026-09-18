# coding=utf-8
"""L2 · J12 — 색을 바꾸면 앱 전체가 그 색이 되는가.

`settings/custom_ui` 는 이 앱의 **색 정본**이다. 거기서 고친 값은
`/custom.css` 로 발행되어 모든 화면에 실린다. 그래서 "저장했는데 그 화면에만
먹는다" 거나 "발행은 됐는데 화면은 옛 색" 인 상태가 생길 수 있고, 둘 다
설정 화면만 보아서는 드러나지 않는다.

그래서 세 곳을 본다 — 설정 화면(고른 값) · `/custom.css`(발행된 값) ·
다른 페이지의 실제 계산된 색.

⚠ 이 검사는 **앱 전체의 색을 바꾼다.** 끝에서 반드시 되돌리고, 되돌린 것까지
단언한다.
"""
import re

import pytest

pytestmark = pytest.mark.e2e

# 색 입력은 `name` 이 없고 **id 로만** 잡힌다(옆에 hex 칸과 스와치가 따로 있는
# 커스텀 색 컨트롤이다). name 셀렉터로 찾으면 "보이지 않는 요소" 로 기다린다.
SWATCH = '#swatch_brand_primary'
TOKEN = '--aot-color-brand-primary'
# 기본 브랜드색과 확실히 다른 값. 되돌리기가 실패하면 눈에 띄어야 한다.
TEST_COLOR = '#7b2ff7'


def _published_color(admin_http, base_url, token=TOKEN):
    """`/custom.css` 가 지금 발행하는 색 — 서버가 아는 값이다."""
    resp = admin_http.get(f'{base_url}/custom.css', timeout=30)
    assert resp.status_code == 200, (
        f'custom.css 가 HTTP {resp.status_code} 를 냈습니다')
    match = re.search(re.escape(token) + r'\s*:\s*(#[0-9A-Fa-f]{3,8})', resp.text)
    assert match, f'{token} 을 custom.css 에서 찾지 못했습니다'
    return match.group(1).lower()


def _open_custom_ui(page, base_url):
    page.goto(f'{base_url}/settings/custom_ui', wait_until='domcontentloaded')
    page.wait_for_selector(SWATCH, timeout=25000)
    page.wait_for_timeout(1200)


def _set_color_and_save(page, color):
    field = page.locator(SWATCH).first
    field.fill(color)
    # 색 입력은 change 로 값이 반영되는 화면이 많다 — 사람이 색을 고르고
    # 칸을 벗어나는 동작까지 흉내 낸다.
    field.dispatch_event('change')
    page.wait_for_timeout(400)

    # 같은 폼 안의 일반 저장(submit). 프리셋 저장(#btn-preset-save)이 아니다 —
    # 그쪽은 색을 프리셋으로 따로 보관할 뿐 정본을 바꾸지 않는다.
    with page.expect_response(
            lambda r: r.request.method == 'POST', timeout=40000) as saved:
        page.locator(f'form:has({SWATCH}) button[type="submit"]').first.click()
    assert saved.value.status in (200, 302), (
        f'색 저장이 HTTP {saved.value.status} 로 끝났습니다')
    page.wait_for_timeout(2500)


def test_a_changed_brand_color_reaches_every_page(page, base_url, admin_http):
    _open_custom_ui(page, base_url)
    original = _published_color(admin_http, base_url)
    assert original != TEST_COLOR, (
        f'시험용 색이 원래 색과 같습니다({original}) — 다른 값을 고르세요')

    try:
        _set_color_and_save(page, TEST_COLOR)

        # 1) 서버가 발행하는 값이 바뀌었는가.
        published = _published_color(admin_http, base_url)
        assert published == TEST_COLOR, (
            f'저장했는데 custom.css 는 여전히 {published} 입니다')

        # 2) **다른 페이지**에서 실제로 그 색으로 계산되는가. 발행만 되고
        #    화면이 옛 값을 쓰면(캐시·우선순위) 사람 눈에는 안 바뀐 것이다.
        page.goto(f'{base_url}/live', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        computed = page.evaluate(
            "(token) => getComputedStyle(document.documentElement)"
            ".getPropertyValue(token).trim().toLowerCase()", TOKEN)
        assert computed.replace(' ', '') == TEST_COLOR, (
            f'다른 페이지의 계산된 색이 {computed!r} 입니다 — 발행은 됐는데 '
            f'화면에는 안 먹었습니다')
    finally:
        _open_custom_ui(page, base_url)
        _set_color_and_save(page, original)

    restored = _published_color(admin_http, base_url)
    assert restored == original, (
        f'색을 되돌리지 못했습니다: {original} → {restored}. '
        f'앱 전체가 시험용 색으로 남습니다')
