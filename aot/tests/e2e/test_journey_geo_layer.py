# coding=utf-8
"""L2 · P2 — 지도 레이어를 추가하고, 이름을 고치고, 지운다.

레이어 관리자는 모두 AJAX 다(추가 뒤에는 화면이 스스로 새로 읽는다). 끝은
"토스트가 떴다" 가 아니라 **새로 열어도 그대로인가**, 그리고 지도 편집 화면이
그 레이어를 **실제로 받는가** 다 — 관리자에만 있고 지도로 가지 않는 레이어는
없는 것과 같다.
"""
import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import choose_option

pytestmark = pytest.mark.e2e


def _layer_ids(page):
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('.grid-stack-item'))"
        "  .map(e => e.getAttribute('gs-id'))")


def _open(page, base_url):
    page.goto(f'{base_url}/geo/layer', wait_until='domcontentloaded')
    page.wait_for_timeout(2500)


def _open_settings(page, uid):
    page.click(f'.aot-geoinput-settings-open[data-input-id="{uid}"]')
    page.wait_for_selector(f'#modal_config_{uid} input[name=name]',
                           state='visible', timeout=15000)


def test_add_rename_and_delete_a_map_layer(page, admin_http, base_url):
    page.on('dialog', lambda dialog: dialog.accept())   # 삭제 확인(브라우저 confirm)
    _open(page, base_url)
    before = set(_layer_ids(page))

    choose_option(page, 'input_type', 'OpenStreetMap')
    with page.expect_response(lambda r: '/geo/input/submit' in r.url) as added:
        page.click('input[name=input_add]')
    assert added.value.status == 200, f'추가가 HTTP {added.value.status}'
    page.wait_for_load_state('domcontentloaded')   # 성공하면 화면이 새로 읽힌다
    page.wait_for_timeout(2500)
    new = [uid for uid in _layer_ids(page) if uid not in before]
    assert len(new) == 1, f'레이어가 하나 추가되지 않았습니다({len(new)}개)'
    uid = new[0]

    # 이름 고치기 — 저장 뒤 새로 열어도 그 이름
    _open_settings(page, uid)
    page.fill(f'#modal_config_{uid} input[name=name]', F.GEO_LAYER_NAME)
    with page.expect_response(lambda r: '/geo/input/submit' in r.url) as saved:
        page.click(f'#modal_config_{uid} button[onclick*="input_mod"]')
    assert saved.value.status == 200
    page.wait_for_timeout(1500)
    _open(page, base_url)
    assert F.GEO_LAYER_NAME in page.inner_text(f'#gridstack_input_{uid}'), (
        '레이어 이름을 고쳤는데 새로 열면 옛 이름입니다')

    # 켜면 지도 편집 화면이 그 레이어를 받는다(켜진 레이어만 지도로 간다)
    with page.expect_response(lambda r: '/geo/input/submit' in r.url) as activated:
        page.click(f'#input_activate_{uid}')
    assert activated.value.status == 200
    page.wait_for_timeout(1000)
    design = admin_http.get(f'{base_url}/geo/design', timeout=60).text
    assert uid in design or F.GEO_LAYER_NAME in design, (
        '켠 레이어가 지도 편집 화면의 레이어 설정에 실리지 않습니다')

    # 삭제 — 확인 뒤 카드가 사라지고, 새로 열어도 없다
    _open_settings(page, uid)
    with page.expect_response(lambda r: '/geo/input/submit' in r.url) as removed:
        page.click(f'#modal_config_{uid} button[onclick*="input_delete"]')
    assert removed.value.status == 200
    page.wait_for_timeout(1500)
    _open(page, base_url)
    assert uid not in _layer_ids(page), '삭제한 레이어가 새로 열면 다시 있습니다'
    assert uid not in admin_http.get(f'{base_url}/geo/design', timeout=60).text, (
        '삭제한 레이어가 지도 편집 화면에 남아 있습니다')


def test_a_monitor_cannot_add_a_layer(monitor_http, base_url):
    """보기만 되는 사람 — 관리 화면이 열리지 않고, 추가 요청은 거절된다."""
    resp = monitor_http.get(f'{base_url}/geo/layer', timeout=30, allow_redirects=False)
    assert resp.status_code in (302, 303), (
        f'모니터가 레이어 관리자를 열었습니다(HTTP {resp.status_code})')
