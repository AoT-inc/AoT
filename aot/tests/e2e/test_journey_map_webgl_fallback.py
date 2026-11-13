# coding=utf-8
"""L2 — WebGL 을 쓸 수 없는 브라우저에서 지도가 **빈 화면이 되지 않는가**.

`AoTMapSeam.createMap` 은 지도 생성이 실패하면 예외를 던지지 않고 null 을 돌려주며
컨테이너에 안내문(`.aot-map-unavailable`)과 `data-map-error` 를 남긴다. 이 경로는
정상 경로와 달리 지금까지 e2e 가 없었다 — 그래서 호출한 쪽이 null 을 못 받아 화면 전체가
죽거나, 안내문이 번역되지 않거나, 조용히 빈 칸이 되어도 아무도 몰랐다.

WebGL 이 없는 상황은 `getContext('webgl*')` 가 null 을 돌려주게 해서 만든다
(서버 GPU 가 없는 컴퓨터, 하드웨어 가속을 끈 브라우저와 같은 증상이다).
"""
import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import open_dashboard

pytestmark = pytest.mark.e2e

MAP_SETTLE_MS = 5000

_NO_WEBGL = """
(function () {
  var orig = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type) {
    if (/webgl/i.test(String(type))) return null;
    return orig.apply(this, arguments);
  };
  if (window.OffscreenCanvas) {
    var origOff = OffscreenCanvas.prototype.getContext;
    OffscreenCanvas.prototype.getContext = function (type) {
      if (/webgl/i.test(String(type))) return null;
      return origOff.apply(this, arguments);
    };
  }
})();
"""

# 우리가 일부러 남기는 안내 로그. 이것만 빼고는 치명 오류로 본다.
_EXPECTED_ERRORS = ('[AoTMapSeam] Map create failed',)
# WebGL 이 없을 때 브라우저·MapLibre 가 스스로 남기는 잡음(우리 코드 결함이 아니다).
_BROWSER_NOISE = ('WebGL', 'webgl', 'Failed to load resource')


@pytest.fixture
def no_webgl_page(page):
    fatal = []
    page.on('pageerror', lambda e: fatal.append(f'pageerror: {e}'))
    page.on('console', lambda m: fatal.append(m.text) if m.type == 'error'
            and not any(k in m.text for k in _EXPECTED_ERRORS + _BROWSER_NOISE)
            else None)
    page.add_init_script(_NO_WEBGL)
    page.fatal = fatal
    return page


def _failure_boxes(page):
    """안내문 상자와 그 컨테이너의 `data-map-error`."""
    return page.evaluate("""() => [...document.querySelectorAll('.aot-map-unavailable')].map(b => {
        const r = b.getBoundingClientRect();
        return {text: b.innerText.trim(), w: r.width, h: r.height,
                err: b.parentElement.getAttribute('data-map-error'),
                role: b.getAttribute('role')};
    })""")


def _translated(page):
    """같은 화면의 번역 함수가 돌려주는 안내문 — 번역되지 않은 원문과 달라야 할 때도 있고
    같을 수도 있다(영어 사용자). 화면 글자가 이 함수의 결과와 같은지만 본다."""
    return page.evaluate("""() => typeof window._ === 'function'
        ? window._(%r) : null""" % (
        'The map cannot be displayed. Browser graphics acceleration (WebGL) may be off, '
        'or all available map views are in use. Close other map windows or reload the page.'))


def _assert_fallback(page, where):
    boxes = _failure_boxes(page)
    assert boxes, f'{where}: WebGL 이 없는데 안내문이 없습니다(빈 화면)'
    want = _translated(page)
    for b in boxes:
        assert b['text'], f'{where}: 안내문이 비어 있습니다'
        assert b['w'] > 50 and b['h'] > 20, f'{where}: 안내문이 보이지 않는 크기입니다: {b}'
        assert b['err'], f'{where}: data-map-error 가 없습니다'
        assert b['role'] == 'alert', f'{where}: 안내문 role 이 alert 이 아닙니다'
        if want:
            assert b['text'] == want, (
                f'{where}: 안내문이 번역 함수의 결과와 다릅니다: {b["text"]!r}')
    return boxes


def _message_is_on_top(page):
    """안내문 한가운데를 실제로 누르는 요소가 안내문 자신인가.

    MapLibre 는 WebGL 을 얻기 전에 빈 캔버스를 먼저 붙이므로 캔버스가 남아 있는 것
    자체는 결함이 아니다. 그 캔버스가 안내문을 덮어 가리면 결함이다.
    """
    return page.evaluate("""() => [...document.querySelectorAll('.aot-map-unavailable')].every(b => {
        const r = b.getBoundingClientRect();
        const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return !!t && (t === b || b.contains(t));
    })""")


# ── 지도 위젯(대시보드) ────────────────────────────────────────────────
def test_dashboard_with_a_map_widget(no_webgl_page, base_url):
    """지도 위젯은 안내문으로 바뀌고, 같은 대시보드의 다른 위젯과 격자는 그대로 산다."""
    page = no_webgl_page
    open_dashboard(page, base_url, F.MAP_DASHBOARD)
    page.wait_for_timeout(MAP_SETTLE_MS)

    _assert_fallback(page, '지도 위젯')
    assert _message_is_on_top(page), '안내문이 지도 캔버스에 가려졌습니다'

    # 지도 밖 기능: 격자가 그려졌고 위젯 제목이 읽히며, 대시보드 목록으로 돌아갈 수 있다.
    assert page.locator('.grid-stack-item').count() >= 1
    assert page.locator('.widget-title').first.inner_text().strip()
    page.goto(f'{base_url}/dashboard', wait_until='domcontentloaded')
    assert page.get_by_role('link', name=F.MAP_DASHBOARD).count() >= 1

    assert not page.fatal, f'치명 오류: {page.fatal[:3]}'


# ── 지도 페이지(/geo/design) ───────────────────────────────────────────
def test_the_map_page_shows_a_message_and_the_rest_of_the_page_works(no_webgl_page, base_url):
    """지도 설계 페이지는 안내문을 보이고, 지도 밖 도구 모음은 그대로 눌린다."""
    page = no_webgl_page
    page.goto(f'{base_url}/geo/design', wait_until='domcontentloaded')
    page.wait_for_selector('.aot-map-unavailable', timeout=25000)
    page.wait_for_timeout(1500)

    _assert_fallback(page, '지도 페이지')
    assert _message_is_on_top(page), '안내문이 지도 캔버스에 가려졌습니다'

    # 지도 외 페이지 기능: 상단 메뉴가 남아 있고 다른 페이지로 이동할 수 있다.
    assert page.locator('a[href]').count() > 5, '지도 외 페이지 메뉴가 사라졌습니다'
    page.goto(f'{base_url}/dashboard', wait_until='domcontentloaded')
    assert page.get_by_role('link', name=F.MAP_DASHBOARD).count() >= 1

    assert not page.fatal, f'치명 오류: {page.fatal[:3]}'
