# coding=utf-8
"""L2 · J3-2 — 지도에 도형을 **그려서** 저장되는가.

`test_journey_map_shapes.py` 는 "있던 도형이 남아 있는가" 를 본다. 이쪽은 그
앞 단계다 — 사람이 도구를 골라 지도 위에 실제로 그리고, 그것이 저장되는가.

그리기는 이 앱에서 가장 손이 많이 가는 조작이고(도구 선택 → 지도 위 드래그 →
자동 저장), 저장은 `/api/geo/overlays/delta` 로 조용히 나간다. 화면에는 그린
순간 이미 도형이 보이므로, 저장이 끊겨도 **그 자리에서는 아무 표시가 없다.**

새로 그리는 것이 **기존 도형을 밀어내지 않는지**도 함께 본다.

지우는 것까지 본다. 2026-08 에 "겹친 도형을 지우면 전량이 지워지던" 사고가
있었다 — 그래서 하나를 지운 뒤 **나머지가 그대로인지**를 함께 단언한다.

⚠ **그리기와 지우기는 저장 방식이 다르다.** 그리기는 놓는 즉시
`/api/geo/overlays/delta` 로 한 건이 나간다. 지우기는 `_pendingDeletes` 에
**쌓이기만 하고**(화면에서는 이미 사라진다) 전역 저장(`#btn-save-global`)을
눌러야 `/api/geo/overlays` 로 전체가 올라간다. 되돌릴 수 있게 하려는 설계다.
그래서 삭제 여정은 저장을 누르는 데까지 가야 하고, 그러지 않으면 "지웠다" 는
화면만 보고 통과해 버린다.
"""
import re

import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

MAP_SETTLE_MS = 6000
SAVE_SETTLE_MS = 3000


def _open_design(page, base_url):
    """설계 지도를 열고, 화면이 쓰는 지도 id 를 받아 온다.

    id 를 시드에서 들고 오지 않는 이유: 화면이 **실제로 여는** 지도를 대상으로
    삼아야 한다. 둘이 갈리면 검사는 엉뚱한 지도를 세게 된다.
    """
    with page.expect_request(
            lambda r: '/api/geo/overlays?map_uuid=' in r.url,
            timeout=30000) as req:
        page.goto(f'{base_url}/geo/design', wait_until='domcontentloaded')
    page.wait_for_selector('#tool-fullscreen', timeout=25000)
    page.wait_for_timeout(MAP_SETTLE_MS)

    match = re.search(r'map_uuid=([0-9a-f-]+)', req.value.url)
    assert match, f'지도 id 를 읽지 못했습니다: {req.value.url}'
    return match.group(1)


def _shapes(admin_http, base_url, map_uuid):
    """그 지도의 도형 목록 — 화면이 아니라 저장된 사실을 본다."""
    resp = admin_http.get(f'{base_url}/api/geo/overlays?map_uuid={map_uuid}',
                          timeout=30, headers={'Accept': 'application/json'})
    assert resp.status_code == 200, (
        f'도형 목록이 HTTP {resp.status_code} 를 냈습니다')
    payload = resp.json()
    return payload.get('features', payload if isinstance(payload, list) else [])


def _shape_names(features):
    out = []
    for feat in features:
        props = (feat or {}).get('properties') or {}
        out.append(props.get('name') or '(이름없음)')
    return out


def _draw_rectangle(page, dx=160, dy=120):
    """사각형 도구를 골라 지도 위에 하나 그린다 — 사람이 하는 그대로."""
    page.locator('#draw-tools-container button[title="사각형"]').first.click()
    page.wait_for_timeout(700)

    canvas = page.locator('.maplibregl-canvas').first
    box = canvas.bounding_box()
    assert box, '지도 캔버스를 찾지 못했습니다'
    start_x = box['x'] + box['width'] / 2 - dx / 2
    start_y = box['y'] + box['height'] / 2 - dy / 2

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    for i in range(1, 9):
        page.mouse.move(start_x + dx * i / 8, start_y + dy * i / 8)
        page.wait_for_timeout(30)
    page.mouse.up()


def test_a_drawn_shape_is_saved_and_survives_a_reload(page, base_url,
                                                      admin_http):
    """그리면 저장되고, 다시 열어도 있는가."""
    map_uuid = _open_design(page, base_url)
    before = _shapes(admin_http, base_url, map_uuid)

    with page.expect_response(
            lambda r: '/api/geo/overlays/delta' in r.url
            and r.request.method == 'POST',
            timeout=30000) as saved:
        _draw_rectangle(page)
    assert saved.value.status == 200, (
        f'도형 저장이 HTTP {saved.value.status} 로 끝났습니다')
    page.wait_for_timeout(SAVE_SETTLE_MS)

    after = _shapes(admin_http, base_url, map_uuid)
    assert len(after) > len(before), (
        f'그렸는데 저장된 도형이 늘지 않았습니다: '
        f'{len(before)} → {len(after)} ({_shape_names(after)})')

    # 시드 도형은 그대로여야 한다 — 새로 그리는 것이 기존 것을 밀어내면 안 된다.
    names = _shape_names(after)
    for seeded in (F.GEO_SITE, F.GEO_ZONE):
        assert seeded in names, (
            f'도형을 그렸더니 기존 도형이 사라졌습니다: {seeded} 없음 ({names})')

    # 다시 열어도 남아 있는가 — 여기까지 와야 "저장됐다" 이다.
    reopened_uuid = _open_design(page, base_url)
    assert reopened_uuid == map_uuid, '다시 열었더니 다른 지도입니다'
    reloaded = _shapes(admin_http, base_url, map_uuid)
    assert len(reloaded) == len(after), (
        f'새로고침 뒤 도형 수가 달라졌습니다: {len(after)} → {len(reloaded)}')


def _delete_at(page, x, y):
    """삭제 모드로 그 지점의 **최상단** 도형 하나를 지운다.

    지워지는 것은 `queryRenderedFeatures` 가 z 순서로 고른 맨 위 하나다
    (`_deleteAtPoint`). 겹쳐 있으면 한 번에 하나씩, 위에서부터 지워진다 —
    그것이 2026-06 에 전량 삭제를 고치며 세운 규칙이다.
    """
    page.locator('#draw-tools-container .tool-btn-delete').first.click()
    page.wait_for_timeout(700)
    page.mouse.click(x, y)
    page.wait_for_timeout(1200)


def test_deleting_one_shape_leaves_the_others_alone(page, base_url, admin_http):
    """하나를 지우면 **그 하나만** 지워지는가."""
    map_uuid = _open_design(page, base_url)
    seeded = _shapes(admin_http, base_url, map_uuid)

    # 지울 대상을 하나 그린다. 시드 도형을 지우면 다음 검사의 전제가 무너진다.
    with page.expect_response(
            lambda r: '/api/geo/overlays/delta' in r.url
            and r.request.method == 'POST',
            timeout=30000):
        _draw_rectangle(page, dx=120, dy=90)
    page.wait_for_timeout(SAVE_SETTLE_MS)
    drawn = _shapes(admin_http, base_url, map_uuid)
    assert len(drawn) > len(seeded), '지울 도형을 만들지 못했습니다'

    canvas = page.locator('.maplibregl-canvas').first
    box = canvas.bounding_box()
    _delete_at(page, box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)

    # 여기까지는 화면에서만 사라진 상태다. 저장해야 서버로 간다.
    #
    # 전역 저장은 `/api/geo/overlays` 로 **전체를 다시 올린다**(그리기 한 건이
    # 쓰는 `/api/geo/overlays/delta` 와 다른 경로다). 끝이 정확히 `/overlays`
    # 인 것만 본다 — `in` 으로 보면 delta 요청도 걸려 엉뚱한 응답을 기다린다.
    with page.expect_response(
            lambda r: (r.url.split('?')[0].rstrip('/').endswith('/api/geo/overlays')
                       and r.request.method == 'POST'),
            timeout=40000) as saved:
        page.locator('#btn-save-global').first.click()
    assert saved.value.status == 200, (
        f'삭제 저장이 HTTP {saved.value.status} 로 끝났습니다')
    page.wait_for_timeout(SAVE_SETTLE_MS)

    after = _shapes(admin_http, base_url, map_uuid)
    names = _shape_names(after)

    assert len(after) < len(drawn), (
        f'지우고 저장했는데 도형이 줄지 않았습니다: '
        f'{len(drawn)} → {len(after)}')
    for name in (F.GEO_SITE, F.GEO_ZONE):
        assert name in names, (
            f'하나를 지웠는데 다른 도형까지 사라졌습니다: {name} 없음 ({names})')
