# coding=utf-8
"""L2 · J16 — 시설 저장이 조건을 지키고, 막을 때는 알려 주는가.

시설은 구획·설비·환경 제어가 딛고 서는 바탕이다. 저장에는 두 가지가 먼저
있어야 한다(`saveFacility`):

  1. 지도를 골랐을 것(`geo_id`)
  2. **지도에 시설을 배치했을 것**(`outer_geometry`) — "Place on Map"

둘 중 하나라도 없으면 저장은 나가지 않는다. 그 자체는 옳다. 다만 **말없이**
멈추면 사람은 저장된 줄 안다 — 그래서 여기서는 "막혔을 때 알려 주는가" 를 본다.
이름만 넣고 저장을 누르는 것은 실제로 흔한 순서다.

그다음 **전체 생성 흐름**을 사람 순서대로 탄다: 새 시설 → 이름·치수 →
위치 단계 → 지도 고르기 → "지도에 배치" → 지도 클릭 → 저장. 끝은 "저장됐다"
토스트가 아니라 **되읽기**다 — 서버가 돌려주는 외곽이 입력한 치수와 맞는지,
새로 열어도 같은 값인지. 삭제는 목록의 삭제 → 확인창 → 시설과 외곽 도형이
함께 사라지는지까지 본다.

지도 카메라는 가정하지 않는다. 배치는 "지금 보이는 지도의 가운데" 를 누르는
것이라, 카메라가 어디에 있든 같은 검사가 된다.
"""
import math
import re

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import choose_option

pytestmark = pytest.mark.e2e

SETTLE_MS = 7000


def _open_facility(page, base_url):
    page.goto(f'{base_url}/geo/facility', wait_until='domcontentloaded')
    page.wait_for_selector('#btn-save-facility', timeout=30000)
    page.wait_for_timeout(SETTLE_MS)


def test_the_facility_editor_opens_with_its_controls(page, base_url):
    """받침 — 편집기가 뜨고 이름 칸과 저장 단추가 있는가.

    3D 편집기라 늦게 그려진다. 이것이 서지 않으면 아래 검사는 "화면이 아직
    없어서" 통과한다.
    """
    _open_facility(page, base_url)
    assert page.locator('#facility-name').count(), '시설 이름 칸이 없습니다'
    assert page.locator('#btn-save-facility').count(), '시설 저장 단추가 없습니다'


def test_saving_without_placing_it_on_the_map_says_so(page, base_url):
    """지도에 배치하지 않고 저장하면 **말해 주는가**.

    조용히 멈추면 사람은 저장된 줄 안다. 알림(alert)이든 토스트든, 무언가
    말은 해야 한다.
    """
    _open_facility(page, base_url)

    page.locator('button:has-text("새 시설"), a:has-text("새 시설")').first.click()
    page.wait_for_timeout(2000)
    page.locator('#facility-name').first.fill(F.FACILITY_NAME)
    page.wait_for_timeout(400)

    said = []
    page.on('dialog', lambda d: (said.append(d.message), d.accept()))

    page.locator('#btn-save-facility').first.click()
    page.wait_for_timeout(4000)

    notices = page.evaluate(
        "() => Array.from(document.querySelectorAll('.toast, "
        "#toast-container div, .alert, #aot-flash-fallback div'))"
        "  .map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 3)")

    assert said or notices, (
        '지도에 배치하지 않았는데 저장이 조용히 멈췄습니다 — 사람은 저장된 줄 '
        '압니다(알림도 토스트도 없었습니다)')


# --------------------------------------------------------------------------
# 전체 생성 흐름
# --------------------------------------------------------------------------
SPAN_M = 7      # 편집기 기본값 — 건드리지 않는다
LENGTH_M = 40   # 기본값(30)과 다르게 둬야 "입력이 저장까지 갔다" 가 드러난다


def _design_map_id(admin_http, base_url):
    """시드 지도의 id — 편집기의 지도 목록에서 읽는다(화면이 고르는 그 값)."""
    html = admin_http.get(f'{base_url}/geo/facility', timeout=30).text
    found = re.search(r'<option value="([0-9a-f-]{36})"[^>]*>E2E Design Map', html)
    assert found, '시설 편집기의 지도 목록에 시드 지도가 없습니다'
    return found.group(1)


def _facility(admin_http, base_url, facility_uuid):
    resp = admin_http.get(f'{base_url}/api/geo/facility/{facility_uuid}',
                          timeout=30)
    return resp.status_code, (resp.json() if resp.status_code == 200 else {})


def _names_listed(admin_http, base_url):
    resp = admin_http.get(f'{base_url}/api/geo/facility/list', timeout=30)
    assert resp.status_code == 200, f'시설 목록이 HTTP {resp.status_code}'
    return [f['name'] for f in resp.json().get('facilities', [])]


def _outlines_on_map(admin_http, base_url, map_id):
    """지도에 그려지는 시설 외곽 도형 수."""
    resp = admin_http.get(
        f'{base_url}/api/geo/overlays?map_uuid={map_id}&type=facility', timeout=30)
    assert resp.status_code == 200, f'지도 도형 조회가 HTTP {resp.status_code}'
    return len(resp.json().get('features', []))


def _rect_sides_m(polygon):
    """사각 외곽의 두 변 길이(m) — 짧은 변, 긴 변."""
    ring = polygon['coordinates'][0]
    lat0 = math.radians(ring[0][1])

    def dist(a, b):
        dx = (b[0] - a[0]) * 111320 * math.cos(lat0)
        dy = (b[1] - a[1]) * 111320
        return math.hypot(dx, dy)

    return sorted([dist(ring[0], ring[1]), dist(ring[1], ring[2])])


def test_a_facility_placed_on_the_map_is_saved_and_reopens(page, admin_http,
                                                           base_url):
    _open_facility(page, base_url)
    page.locator('button:has-text("새 시설")').first.click()
    page.wait_for_timeout(1500)

    # 기본 단계 — 이름과 치수
    page.fill('#facility-name', F.FACILITY_NAME)
    page.fill('#length-m', str(LENGTH_M))
    page.locator('#length-m').dispatch_event('change')

    # 위치 단계 — 지도를 고르고, 배치 모드에서 지도 가운데를 누른다
    page.locator('.fac-step[data-step=position]').click()
    page.wait_for_timeout(1500)
    choose_option(page, 'map-selector', 'E2E Design Map')
    page.wait_for_timeout(4000)
    canvas = page.locator('#facility-map-canvas').bounding_box()
    assert canvas and canvas['width'] > 100, '위치 단계에서 지도가 보이지 않습니다'
    page.click('#btn-place-on-map')
    page.wait_for_timeout(800)
    page.mouse.click(canvas['x'] + canvas['width'] / 2,
                     canvas['y'] + canvas['height'] / 2)
    page.wait_for_timeout(2500)

    with page.expect_response(
            lambda r: r.url.endswith('/api/geo/facility')
            and r.request.method == 'POST', timeout=30000) as saved:
        page.click('#btn-save-facility')
    body = saved.value.json()
    assert saved.value.status == 200 and body.get('ok'), (
        f'시설 저장이 실패했습니다: HTTP {saved.value.status}, {body.get("message")}')
    facility_uuid = body['facility_uuid']

    # 화면 — 목록에 곧바로 나타난다(새로고침 없이)
    row = page.locator(f'.facility-list-item[data-uuid="{facility_uuid}"]')
    row.wait_for(state='attached', timeout=10000)
    assert F.FACILITY_NAME in row.inner_text()

    # 서버 — 되읽은 외곽이 입력한 치수다
    status, got = _facility(admin_http, base_url, facility_uuid)
    assert status == 200, f'저장한 시설을 다시 읽지 못했습니다(HTTP {status})'
    facility = got['facility']
    assert facility['name'] == F.FACILITY_NAME
    assert facility['geo_id'] == _design_map_id(admin_http, base_url), (
        '고른 지도가 아닌 곳에 저장됐습니다')
    assert facility['geometry_3d'].get('length_m') == LENGTH_M, (
        f"길이가 {facility['geometry_3d'].get('length_m')} 로 저장됐습니다 "
        f'(입력 {LENGTH_M})')
    outer = (facility.get('outer_feature') or {}).get('geometry')
    assert outer and outer['type'] == 'Polygon', '외곽 도형이 저장되지 않았습니다'
    short, long_ = _rect_sides_m(outer)
    assert abs(short - SPAN_M) < 1 and abs(long_ - LENGTH_M) < 1, (
        f'외곽이 {short:.1f} × {long_:.1f} m 입니다 — 입력은 '
        f'{SPAN_M} × {LENGTH_M} m')

    # 다시 열기 — 주소로 열어도 같은 값이 채워진다
    page.goto(f'{base_url}/geo/facility?facility_uuid={facility_uuid}',
              wait_until='domcontentloaded')
    page.wait_for_selector('#btn-save-facility', timeout=30000)
    page.wait_for_timeout(SETTLE_MS)
    assert page.input_value('#facility-name') == F.FACILITY_NAME, (
        '저장한 시설을 다시 열었는데 이름이 비어 있거나 다릅니다')
    assert float(page.input_value('#length-m')) == LENGTH_M, (
        f"다시 연 길이가 {page.input_value('#length-m')} 입니다")


def test_deleting_a_facility_takes_its_outline_with_it(page, admin_http,
                                                       base_url):
    """목록의 삭제 → 확인창 → 시설도 외곽 도형도 없다.

    삭제할 시설은 API 로 만든다 — 생성 화면은 위 검사가 본다.
    """
    map_id = _design_map_id(admin_http, base_url)
    token = admin_http.get(f'{base_url}/csrf-token', timeout=30).json()['csrf_token']
    lon, lat, d = 127.002, 37.002, 0.0003
    made = admin_http.post(
        f'{base_url}/api/geo/facility', timeout=30,
        headers={'X-CSRFToken': token},
        json={'geo_id': map_id,
              'name': F.FACILITY_DELETE_NAME,
              'outer_geometry': {'type': 'Polygon', 'coordinates': [[
                  [lon, lat], [lon + d, lat], [lon + d, lat + d],
                  [lon, lat + d], [lon, lat]]]},
              'geometry_3d': {'center_lng': lon + d / 2,
                              'center_lat': lat + d / 2}}).json()
    assert made.get('ok'), f'삭제할 시설을 만들지 못했습니다: {made}'
    facility_uuid = made['facility_uuid']
    outlines_before = _outlines_on_map(admin_http, base_url, map_id)

    _open_facility(page, base_url)
    row = page.locator(f'.facility-list-item[data-uuid="{facility_uuid}"]')
    assert row.count() == 1, '방금 만든 시설이 목록에 없습니다'
    row.locator('.fac-item-del').click()
    page.wait_for_timeout(500)
    with page.expect_response(
            lambda r: r.request.method == 'DELETE'
            and facility_uuid in r.url, timeout=30000) as removed:
        page.locator('#aotConfirmModal.show .aot-confirm-ok').first.click()
    assert removed.value.status == 200 and removed.value.json().get('ok'), (
        f'삭제가 HTTP {removed.value.status} 로 끝났습니다: '
        f'{removed.value.text()[:200]}')

    row.wait_for(state='detached', timeout=10000)
    status, _ = _facility(admin_http, base_url, facility_uuid)
    assert status == 404, f'삭제한 시설이 아직 읽힙니다(HTTP {status})'
    assert F.FACILITY_DELETE_NAME not in _names_listed(admin_http, base_url)
    # 시설 행만 지우고 외곽을 남기면 지도에 주인 없는 건물이 그려진다.
    outlines_after = _outlines_on_map(admin_http, base_url, map_id)
    assert outlines_after == outlines_before - 1, (
        f'시설을 지웠는데 지도의 시설 외곽이 {outlines_before} → '
        f'{outlines_after} 입니다 — 외곽 도형이 남았습니다')
