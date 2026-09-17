# coding=utf-8
"""L2 · J4 — 지도가 화면 상태를 바꿔도 살아 있는가.

지도 계열은 이 앱에서 fix 커밋이 가장 많이 몰린 곳이다(맵 위젯 번들 128회,
벡터 소스 96회). 그중 사용자가 바로 알아채는 사고는 **지도가 사라지는** 것이다:

  * "geo/design 지도 전체 화면에서 지도가 사라지던 것"
  * "드로어를 여닫는 0.4초 동안 지도가 흰 화면으로 비던 것"

둘 다 화면 상태를 바꾼 **직후**에만 드러난다. 페이지를 열어 두고 보면 멀쩡하다.
그래서 L1(부팅 검사)로는 못 잡고, 여기서 실제로 토글해 본다.
"""
import pytest

pytestmark = pytest.mark.e2e

# 지도가 뜨기까지 타일·스타일을 기다린다. 느린 CI 를 감안해 넉넉히 준다.
MAP_SETTLE_MS = 5000
TOGGLE_SETTLE_MS = 1800


def _map_size(page):
    """지도 캔버스의 실제 크기. 0 이면 사람 눈에는 흰 화면이다."""
    return page.evaluate("""() => {
        const c = document.querySelector('.maplibregl-canvas') ||
                  document.querySelector('canvas');
        if (!c) return null;
        const r = c.getBoundingClientRect();
        return {w: Math.round(r.width), h: Math.round(r.height)};
    }""")


@pytest.fixture
def design_page(page, base_url):
    errors = []
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.goto(f'{base_url}/geo/design', wait_until='domcontentloaded')
    page.wait_for_selector('#tool-fullscreen', timeout=25000)
    page.wait_for_timeout(MAP_SETTLE_MS)
    page.console_errors = errors
    return page


def test_the_map_is_drawn_at_all(design_page):
    """받침 — 지도가 아예 안 뜨면 아래 토글 검사는 의미가 없다."""
    size = _map_size(design_page)
    assert size, '지도 캔버스가 없습니다'
    assert size['w'] > 100 and size['h'] > 100, (
        f'지도가 그려지지 않았습니다: {size}')


def test_the_map_survives_going_fullscreen_and_back(design_page):
    """전체화면으로 갔다가 돌아와도 지도가 남아 있는가."""
    before = _map_size(design_page)

    design_page.click('#tool-fullscreen')
    design_page.wait_for_timeout(TOGGLE_SETTLE_MS)
    full = _map_size(design_page)

    assert full and full['w'] > 100 and full['h'] > 100, (
        f'전체화면에서 지도가 사라졌습니다: {full}')
    assert full['w'] >= before['w'] and full['h'] >= before['h'], (
        f'전체화면인데 지도가 더 작아졌습니다: {before} → {full}')

    design_page.click('#tool-fullscreen')
    design_page.wait_for_timeout(TOGGLE_SETTLE_MS)
    back = _map_size(design_page)

    assert back and back['w'] > 100 and back['h'] > 100, (
        f'전체화면에서 돌아오니 지도가 사라졌습니다: {back}')
    # 원래 크기로 돌아와야 한다. 1px 오차는 둔다(배율·스크롤바).
    assert abs(back['w'] - before['w']) <= 2 and abs(back['h'] - before['h']) <= 2, (
        f'전체화면을 껐는데 원래 크기로 돌아오지 않았습니다: '
        f'{before} → {back}')


def test_toggling_fullscreen_does_not_throw(design_page):
    """토글하는 동안 콘솔에 오류가 나지 않아야 한다.

    지도가 크기를 다시 재는 경로(resize/redraw)는 조용히 던지기 쉬운 자리다.
    화면은 멀쩡해 보여도 그 뒤 상호작용이 죽는다.
    """
    design_page.console_errors.clear()
    design_page.click('#tool-fullscreen')
    design_page.wait_for_timeout(TOGGLE_SETTLE_MS)
    design_page.click('#tool-fullscreen')
    design_page.wait_for_timeout(TOGGLE_SETTLE_MS)

    # 외부 타일 제공자의 실패는 인터넷 사정이라 판정에서 뺀다.
    ours = [e for e in design_page.console_errors
            if not any(k in e.lower() for k in
                       ('tile', 'openstreetmap', 'rainviewer', 'sentinel',
                        'agromonitoring', 'daemon', '9081'))]
    assert not ours, f'전체화면을 토글하는 동안 콘솔 오류: {ours[:3]}'
