# coding=utf-8
"""L2 · J3-2 — 지도에 도형을 **그려서** 저장되는가.

`test_journey_map_shapes.py` 는 "있던 도형이 남아 있는가" 를 본다. 이쪽은 그
앞 단계다 — 사람이 도구를 골라 지도 위에 실제로 그리고, 그것이 저장되는가.

그리기는 이 앱에서 가장 손이 많이 가는 조작이고(도구 선택 → 지도 위 드래그 →
자동 저장), 저장은 `/api/geo/overlays/delta` 로 조용히 나간다. 화면에는 그린
순간 이미 도형이 보이므로, 저장이 끊겨도 **그 자리에서는 아무 표시가 없다.**

새로 그리는 것이 **기존 도형을 밀어내지 않는지**도 함께 본다.

지우는 흐름은 아직 없다. 삭제 모드는 버튼을 누르면 켜지지만(`text-danger` 가
붙는다) 캔버스 클릭만으로는 반응하지 않았다 — `_deleteAtPoint` 가
`queryRenderedFeatures` 로 최상단 레이어를 찾는 구조라, 자동화가 찍어야 할
지점 조건이 더 있다. 반쯤 맞는 검사를 두느니 없는 편이 낫다(통과해도 무엇을
지켰는지 말할 수 없다). "겹친 도형을 지우면 전량이 지워지던" 2026-08 사고의
재발 감시는 그 조건을 짚은 뒤에 붙인다.
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
