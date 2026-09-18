# coding=utf-8
"""L2 · J16 — 시설 저장이 조건을 지키고, 막을 때는 알려 주는가.

시설은 구획·설비·환경 제어가 딛고 서는 바탕이다. 저장에는 두 가지가 먼저
있어야 한다(`saveFacility`):

  1. 지도를 골랐을 것(`geo_id`)
  2. **지도에 시설을 배치했을 것**(`outer_geometry`) — "Place on Map"

둘 중 하나라도 없으면 저장은 나가지 않는다. 그 자체는 옳다. 다만 **말없이**
멈추면 사람은 저장된 줄 안다 — 그래서 여기서는 "막혔을 때 알려 주는가" 를 본다.
이름만 넣고 저장을 누르는 것은 실제로 흔한 순서다.

지도에 배치하는 데까지 가는 전체 생성 흐름은 아직 없다. 그 단계는 지도
상호작용(위치 지정)이라 J3 의 그리기와 같은 무게이고, 조건을 짚은 다음에
붙이는 편이 낫다.
"""
import pytest

from aot.tests.e2e import fixtures as F

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
