# coding=utf-8
"""L2 · J9 — 입력을 만들고, 이름을 고치고, 지우는 한 바퀴.

장치를 들이는 첫 동작이다. 여기가 막히면 앱을 쓰기 시작할 수조차 없는데,
개발 중에는 이미 만들어 둔 장치로만 다니므로 아무도 지나지 않는다.

만들고 끝내지 않는다 — **지우는 데까지** 간다. 만들기만 검사하면 시험 산출물이
쌓이고, 무엇보다 삭제 경로가 검사되지 않는다.
"""
import pytest

from aot.tests.e2e.journeys import choose_option

pytestmark = pytest.mark.e2e

# 하드웨어가 없어도 만들어지는 종류. 화면의 선택지 이름으로 고른다.
INPUT_KIND = 'CPU Load'
NEW_NAME = 'E2E Temp Input'


def _open_inputs(page, base_url):
    page.goto(f'{base_url}/input', wait_until='domcontentloaded')
    page.wait_for_selector('#input_type', timeout=25000)
    page.wait_for_timeout(1500)


def _card_count(page):
    return page.locator('.grid-stack-item').count()


def _card_names(page):
    """카드에 적힌 장치 이름들.

    입력 화면은 이름을 **텍스트로** 그린다(출력 화면은 입력 칸에 담는다 —
    같은 격자 카드인데 구조가 다르다). 그래서 `input[value=...]` 류의
    셀렉터로는 하나도 잡히지 않는다.
    """
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('.grid-stack-item'))"
        "  .map(el => (el.innerText || '').split('\\n')[0].trim())"
        "  .filter(Boolean)")


def _card_by_name(page, name):
    """그 이름을 가진 카드 하나."""
    index = _card_names(page).index(name)
    return page.locator('.grid-stack-item').nth(index)


def _add_input(page):
    labels = page.eval_on_selector(
        '#input_type', 'el => Array.from(el.options).map(o => o.text.trim())')
    kind = next((l for l in labels if INPUT_KIND in l), None)
    assert kind, f'{INPUT_KIND} 선택지를 찾지 못했습니다(선택지 {len(labels)}개)'

    choose_option(page, 'input_type', kind)
    with page.expect_response(
            lambda r: r.request.method == 'POST' and 'input' in r.url,
            timeout=40000) as added:
        page.locator('[name="input_add"]').first.click()
    assert added.value.status in (200, 302), (
        f'입력 추가가 HTTP {added.value.status} 로 끝났습니다')
    page.wait_for_timeout(3000)


def _rename_last_input(page, new_name):
    """방금 만든(맨 마지막) 입력의 이름을 바꾼다."""
    card = page.locator('.grid-stack-item').last
    card.locator('a.aot-input-settings-open, a[class*="settings-open"]'
                 ).first.click()
    page.wait_for_selector('.aot-option-modal.show input[name="name"]',
                           timeout=15000)
    page.wait_for_timeout(500)
    page.fill('.aot-option-modal.show input[name="name"]', new_name)
    with page.expect_response(
            lambda r: r.request.method == 'POST', timeout=40000) as saved:
        page.locator('.aot-option-modal.show [onclick*="input_mod"]'
                     ).first.click()
    assert saved.value.status in (200, 302), (
        f'이름 저장이 HTTP {saved.value.status} 로 끝났습니다')
    page.wait_for_timeout(2500)


def _delete_input(page, name):
    """설정에서 지운다.

    삭제는 브라우저 기본 confirm 이 아니라 **앱의 확인 모달**
    (`#aotConfirmModal`)을 쓴다(`data-aot-confirm`). 그래서 dialog 이벤트를
    기다리면 영영 오지 않는다 — 모달의 확인 단추를 눌러야 한다.
    """
    card = _card_by_name(page, name)
    card.locator('a.aot-input-settings-open, a[class*="settings-open"]'
                 ).first.click()
    page.wait_for_selector('.aot-option-modal.show', timeout=15000)
    page.wait_for_timeout(600)

    page.locator('.aot-option-modal.show [data-aot-action="input_delete"]'
                 ).first.click()
    page.wait_for_selector('#aotConfirmModal.show', timeout=15000)
    page.wait_for_timeout(500)
    with page.expect_response(
            lambda r: r.request.method == 'POST', timeout=40000):
        page.locator('#aotConfirmModal.show .aot-confirm-ok').first.click()
    page.wait_for_timeout(3000)


def test_an_input_can_be_created_renamed_and_deleted(page, base_url):
    _open_inputs(page, base_url)
    before = _card_count(page)

    created = False
    try:
        _add_input(page)
        created = True
        _open_inputs(page, base_url)
        assert _card_count(page) == before + 1, (
            f'입력을 더했는데 카드 수가 그대로입니다: {before}')

        _rename_last_input(page, NEW_NAME)

        # 되읽기 — 새로고침해도 그 이름인가.
        _open_inputs(page, base_url)
        assert NEW_NAME in _card_names(page), (
            f'새로고침 뒤 이름이 보이지 않습니다: {NEW_NAME!r} '
            f'(보이는 이름: {_card_names(page)})')
    finally:
        if created:
            try:
                _open_inputs(page, base_url)
                if NEW_NAME in _card_names(page):
                    _delete_input(page, NEW_NAME)
            except Exception:                # noqa: BLE001
                pass

    _open_inputs(page, base_url)
    assert NEW_NAME not in _card_names(page), (
        f'지웠는데 {NEW_NAME!r} 가 남아 있습니다')
    assert _card_count(page) == before, (
        f'한 바퀴 돌았는데 카드 수가 달라졌습니다: {before} → {_card_count(page)}')
