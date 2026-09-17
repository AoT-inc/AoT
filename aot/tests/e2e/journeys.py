# coding=utf-8
"""L2 시나리오가 공통으로 쓰는 조작.

여기 있는 것은 **사람이 하는 동작**이지 단언이 아니다. 단언은 각 시나리오가 한다.
"""


def open_dashboard(page, base_url, name):
    """대시보드 목록에서 이름으로 찾아 연다 — 사람이 하는 그대로.

    URL 을 직접 치지 않는 이유: 시드가 만든 unique_id 를 테스트가 들고 다니면
    "링크가 사라져도 통과하는" 검사가 된다. 목록에서 찾아 누르는 것까지가
    이 여정의 일부다.
    """
    page.goto(f'{base_url}/dashboard', wait_until='domcontentloaded')
    page.get_by_role('link', name=name).first.click()
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_selector('.grid-stack-item', timeout=20000)
    page.wait_for_timeout(800)   # gridstack 이 좌표를 적어 넣을 틈
    return page.url


def widget_boxes(page):
    """현재 화면의 위젯 좌표 — `{이름: {x, y, w, h}}`."""
    return page.evaluate("""() => {
        const out = {};
        for (const el of document.querySelectorAll('.grid-stack-item')) {
            // 이름은 `.widget-title` 에 있다. 드래그 손잡이
            // (`.widget-drag-handle`)는 아이콘뿐이라 글자가 없다.
            const title = (el.querySelector('.widget-title') || {}).innerText;
            out[(title || el.getAttribute('gs-id')).trim()] = {
                id: el.getAttribute('gs-id'),
                x: parseInt(el.getAttribute('gs-x') || '0'),
                y: parseInt(el.getAttribute('gs-y') || '0'),
                w: parseInt(el.getAttribute('gs-w') || '0'),
                h: parseInt(el.getAttribute('gs-h') || '0'),
            };
        }
        return out;
    }""")


def drag_widget_by(page, widget_name, dx, dy):
    """위젯을 손잡이로 잡아 (dx, dy) 픽셀만큼 끌어다 놓는다.

    gridstack API 를 직접 부르지 않는다 — 그러면 "마우스로 끌 수 있는가" 를
    검사하지 못한다. 손잡이가 사라지거나 덮이는 것도 사고이기 때문이다.
    """
    handle = page.locator('.grid-stack-item', has_text=widget_name).first.locator(
        '.widget-drag-handle').first
    handle.scroll_into_view_if_needed()
    box = handle.bounding_box()
    assert box, f'{widget_name}: 드래그 손잡이를 찾지 못했습니다'

    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    # 여러 걸음으로 나눠 움직인다 — 한 번에 순간이동하면 gridstack 의
    # 드래그 시작 판정이 서지 않는 경우가 있다.
    steps = 12
    for i in range(1, steps + 1):
        page.mouse.move(start_x + dx * i / steps, start_y + dy * i / steps)
        page.wait_for_timeout(15)
    page.mouse.up()


def choose_option(page, select_id, label):
    """공용 셀렉트에서 항목을 고른다 — **사람이 하는 그대로**.

    이 앱의 셀렉트는 bootstrap-select 로 감싸져 있고, 화면 코드는 대개
    `changed.bs.select` 만 듣는다(일지 화면의 `_onSelect` 헬퍼가 그렇다).
    (여기에 JS 원본 파일명을 적지 않는 이유: 공개본 제외 목록 생성기가
     'JS 원본 이름이 본문에 있는 테스트' 를 함께 제외해, 이 헬퍼와 그것을
     쓰는 여정들이 공개 저장소 CI 에서 통째로 빠진다.)
    그래서 `<select>` 의 값을 바꿔 네이티브 `change` 를 쏘는 방식으로는
    **아무 일도 일어나지 않는다** — 값은 바뀌었는데 화면은 고른 줄 모른다.

    드롭다운을 열어 항목을 누르면 두 경로가 모두 돈다. 느리지만, 이것이
    사람이 실제로 지나는 길이고 E2E 가 검사해야 하는 길이다.
    """
    wrapper = page.locator(f'.bootstrap-select:has(select#{select_id})')
    if wrapper.count():
        wrapper.locator('button').first.click()
        page.wait_for_timeout(350)
        # 열린 목록은 래퍼 안이 아니라 **body 바로 아래**에 붙는다
        # (`data-container="body"` — 드롭다운이 카드 경계에서 잘리던 문제를
        # 그렇게 풀었다). 그래서 래퍼 안에서 찾으면 영영 못 찾는다.
        item = page.locator('.dropdown-menu.show, .bootstrap-select .dropdown-menu.open'
                            ).locator('li, [role="option"]').filter(has_text=label).first
        item.click()
        page.wait_for_timeout(500)
        return

    # 감싸지 않은 평범한 셀렉트.
    page.select_option(f'#{select_id}', label=label)
    page.wait_for_timeout(300)
