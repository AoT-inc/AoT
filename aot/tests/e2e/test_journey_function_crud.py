# coding=utf-8
"""L2 · J10 — 함수를 만들고, 이름을 고치고, 지우는 한 바퀴.

J9(입력)와 같은 여정을 함수에서 한 번 더 한다. 같은 격자 카드처럼 보이지만
**화면마다 구조가 다르기 때문이다** — 입력은 이름을 텍스트로 그리고, 함수와
출력은 입력 칸에 담는다. 한쪽에서 통하는 셀렉터가 다른 쪽에서 0건이 되는 일이
실제로 있었고, 그런 차이는 한 화면만 검사해서는 드러나지 않는다.
"""
import pytest

from aot.tests.e2e.journeys import choose_option

pytestmark = pytest.mark.e2e

FUNCTION_KIND = 'Conditional Controller'
NEW_NAME = 'E2E Temp Function'


def _open_functions(page, base_url):
    page.goto(f'{base_url}/function', wait_until='domcontentloaded')
    page.wait_for_selector('#function_type', timeout=25000)
    page.wait_for_timeout(1500)


def _cards(page):
    """카드의 (id, 이름) 쌍.

    id 와 이름을 **한 번에** 읽는다. 따로 읽어 인덱스로 맞추면, 이름이 빈
    카드가 하나라도 있는 순간 두 목록의 길이가 어긋나 엉뚱한 카드를 가리킨다.

    그리고 추적은 이름이 아니라 **id 로** 한다 — 같은 이름이 둘 생기면
    (이전 실행의 잔재, 중복 생성) 이름 기반 조작은 무너진다.
    """
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('.grid-stack-item'))"
        "  .map(el => {"
        "      const id = el.querySelector('input[name=\"function_id\"]');"
        "      const nm = el.querySelector('input.aot-entry-name-input');"
        "      return {id: id ? id.value : '', name: nm ? nm.value.trim() : ''};"
        "  }).filter(x => x.id)")


def _ids(page):
    return [c['id'] for c in _cards(page)]


def _index_of(page, function_id):
    return _ids(page).index(function_id)


def _card_by_id(page, function_id):
    return page.locator('.grid-stack-item').nth(_index_of(page, function_id))


def _name_of(page, function_id):
    return _cards(page)[_index_of(page, function_id)]['name']


def _add_function(page):
    labels = page.eval_on_selector(
        '#function_type',
        'el => Array.from(el.options).map(o => o.text.trim())')
    kind = next((l for l in labels if FUNCTION_KIND in l), None)
    assert kind, f'{FUNCTION_KIND} 선택지를 찾지 못했습니다'

    choose_option(page, 'function_type', kind)
    with page.expect_response(
            lambda r: r.request.method == 'POST', timeout=40000) as added:
        page.locator('[name="function_add"]').first.click()
    assert added.value.status in (200, 302), (
        f'함수 추가가 HTTP {added.value.status} 로 끝났습니다')
    page.wait_for_timeout(3000)


def _open_settings(page, card):
    card.locator('a.aot-function-settings-open').first.click()
    page.wait_for_selector('.aot-option-modal.show', timeout=15000)
    page.wait_for_timeout(600)


def _rename(page, function_id, new_name):
    _open_settings(page, _card_by_id(page, function_id))
    page.fill('.aot-option-modal.show input[name="name"]', new_name)
    with page.expect_response(
            lambda r: r.request.method == 'POST', timeout=40000) as saved:
        page.locator('.aot-option-modal.show [onclick*="function_mod"]'
                     ).first.click()
    assert saved.value.status in (200, 302), (
        f'이름 저장이 HTTP {saved.value.status} 로 끝났습니다')
    page.wait_for_timeout(2500)


def _delete(page, function_id):
    """앱의 확인 모달(`#aotConfirmModal`)을 거쳐 지운다."""
    _open_settings(page, _card_by_id(page, function_id))
    page.locator('.aot-option-modal.show [data-aot-action="function_delete"]'
                 ).first.click()
    page.wait_for_selector('#aotConfirmModal.show', timeout=15000)
    page.wait_for_timeout(500)
    with page.expect_response(
            lambda r: r.request.method == 'POST', timeout=40000) as removed:
        page.locator('#aotConfirmModal.show .aot-confirm-ok').first.click()
    page.wait_for_timeout(3000)
    assert removed.value.status in (200, 302), (
        f'삭제가 HTTP {removed.value.status} 로 끝났습니다')


def test_a_function_can_be_created_renamed_and_deleted(page, base_url):
    _open_functions(page, base_url)
    before_ids = _ids(page)

    new_id = None
    try:
        _add_function(page)
        _open_functions(page, base_url)
        after_ids = _ids(page)
        added = [i for i in after_ids if i not in before_ids]
        assert len(added) == 1, (
            f'함수를 하나 더했는데 늘어난 카드가 {len(added)}개입니다')
        new_id = added[0]

        _rename(page, new_id, NEW_NAME)

        _open_functions(page, base_url)
        assert _name_of(page, new_id) == NEW_NAME, (
            f'새로고침 뒤 이름이 다릅니다: {_name_of(page, new_id)!r}')
    finally:
        if new_id:
            try:
                _open_functions(page, base_url)
                if new_id in _ids(page):
                    _delete(page, new_id)
            except Exception:                # noqa: BLE001
                pass

    _open_functions(page, base_url)
    assert new_id not in _ids(page), '지웠는데 그 함수가 남아 있습니다'
    assert _ids(page) == before_ids, (
        '한 바퀴 돌았는데 목록이 달라졌습니다')
