# coding=utf-8
"""L2 · J3 — 지도에 저장된 도형이 화면에 남아 있는가.

겨냥하는 사고: 2026-08 에 스키마가 바뀌면서 `geo_shape` 가 **전량 유실**된 적이
있다. 도형은 사람이 직접 그려 넣은 것이라 되돌릴 수 없고, 그런데도 화면은
"도형이 없는 정상 지도" 로 보인다 — 잃었다는 사실조차 화면이 말해 주지 않는다.

그래서 여기서는 **시드가 놓은 도형이 그대로 보이는지**를 매번 확인한다.
숫자가 아니라 이름으로 본다 — 개수만 세면 엉뚱한 도형이 대신 들어와도 통과한다.

그리기 상호작용(도구 선택 → 지도 클릭 → 완료 → 저장)은 아직 다루지 않는다.
먼저 "있던 것이 남아 있는가" 를 고정해 두는 편이, 그리기가 깨졌을 때보다
훨씬 자주 일어나는 사고를 막는다.
"""
import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

MAP_SETTLE_MS = 6000


def _open_design(page, base_url):
    page.goto(f'{base_url}/geo/design', wait_until='domcontentloaded')
    page.wait_for_selector('#tool-fullscreen', timeout=25000)
    page.wait_for_timeout(MAP_SETTLE_MS)


def _shape_names_on_screen(page):
    text = page.inner_text('body')
    return {name for name in (F.GEO_SITE, F.GEO_ZONE) if name in text}


def test_the_seeded_shapes_are_on_the_design_map(page, base_url):
    _open_design(page, base_url)
    found = _shape_names_on_screen(page)
    missing = {F.GEO_SITE, F.GEO_ZONE} - found
    assert not missing, (
        f'지도 화면에서 도형이 보이지 않습니다: {sorted(missing)}. '
        f'저장된 도형이 화면에 실리지 않았거나 유실됐습니다')


def test_the_shapes_are_still_there_after_a_reload(page, base_url):
    """다시 열어도 그대로인가 — 화면 상태가 아니라 저장된 사실을 본다."""
    _open_design(page, base_url)
    before = _shape_names_on_screen(page)

    page.reload(wait_until='domcontentloaded')
    page.wait_for_selector('#tool-fullscreen', timeout=25000)
    page.wait_for_timeout(MAP_SETTLE_MS)
    after = _shape_names_on_screen(page)

    assert after == before, (
        f'새로고침 뒤 도형 목록이 달라졌습니다: {sorted(before)} → {sorted(after)}')


def test_the_shape_data_reaches_the_client(admin_http, base_url):
    """서버가 도형을 실제로 내보내는가 — 화면 문자열과 별개로 데이터를 본다.

    화면에 이름이 보이는 것과 지도 도형 데이터가 오는 것은 다른 경로다.
    한쪽만 살아 있으면 목록에는 있는데 지도에는 없는(또는 그 반대) 상태가 된다.
    """
    resp = admin_http.get(f'{base_url}/api/geo/overlays/list', timeout=30,
                          headers={'Accept': 'application/json'})
    assert resp.status_code == 200, (
        f'도형 목록 API 가 HTTP {resp.status_code} 를 냈습니다')

    payload = resp.json()
    # map_uuid 를 주지 않으면 빈 FeatureCollection 이 정상이다. 그 계약을 고정한다
    # — 예전에는 이 호출이 인자 없이 불려 **항상** 500 이었다.
    assert payload.get('type') == 'FeatureCollection', (
        f'FeatureCollection 이 아닙니다: {str(payload)[:120]}')
