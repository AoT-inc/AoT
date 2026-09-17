# coding=utf-8
"""L2 · J8 — 설정 모달에서 고친 값이 정말 저장되는가.

모달은 이 앱에서 회귀가 가장 잦은 곳이다(`aot-modal-modern.css` 한 파일만
2026-03 이후 fix 커밋 66회). 그중에서도 **저장 왕복**이 조용히 깨지기 쉽다 —
모달이 닫히고 화면이 갱신되면 사람은 저장됐다고 믿는다. 실제로 났던 사고들:

  * 셀렉트가 네이티브 change 를 쏘지 않아 고른 값이 폼에 반영되지 않던 것
  * 모달 저장 후 AJAX 새로고침에서 색상칩 보정이 빠지던 것

그래서 이 시나리오는 **새로고침 뒤 되읽기**까지 간다.

버튼을 문구로 찾지 않는다. 저장 버튼은 `processRequest(this, 'output_mod')`
를 부르는 것으로 식별한다 — 언어를 바꿔도, 문구를 다듬어도 그대로다.
"""
import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

RENAMED = F.OUTPUT_NOCHANNEL + ' (E2E 수정)'


def _card(page, name):
    return page.locator('.grid-stack-item', has_text=name).first


def _open_settings(page, name):
    _card(page, name).locator('a.aot-output-settings-open').first.click()
    # 모달은 fade 애니메이션이 끝나야 입력을 받는다.
    page.wait_for_selector('.aot-option-modal.show input[name="name"]', timeout=15000)
    page.wait_for_timeout(400)


def _save_and_wait(page):
    with page.expect_response(
            lambda r: '/output_submit' in r.url and r.request.method == 'POST',
            timeout=20000) as saved:
        page.locator('.aot-option-modal.show [onclick*="output_mod"]').first.click()
    assert saved.value.status == 200, f'저장이 HTTP {saved.value.status} 로 끝났습니다'
    page.wait_for_timeout(1200)


def _rename(page, base_url, from_name, to_name):
    page.goto(f'{base_url}/output', wait_until='domcontentloaded')
    page.wait_for_selector('.grid-stack-item', timeout=25000)
    page.wait_for_timeout(1200)
    _open_settings(page, from_name)
    field = page.locator('.aot-option-modal.show input[name="name"]').first
    field.fill(to_name)
    _save_and_wait(page)


def test_a_renamed_output_keeps_its_new_name_after_a_reload(page, base_url):
    """모달에서 이름을 고치고 저장 → 새로고침 → 그 이름인가.

    끝에 반드시 원래 이름으로 되돌린다. 픽스처는 다음 시나리오도 쓰므로
    이 검사가 남긴 자국이 다른 검사의 전제를 바꾸면 안 된다.
    """
    try:
        _rename(page, base_url, F.OUTPUT_NOCHANNEL, RENAMED)

        page.reload(wait_until='domcontentloaded')
        page.wait_for_selector('.grid-stack-item', timeout=25000)
        page.wait_for_timeout(1200)

        assert _card(page, RENAMED).count() > 0, (
            f'새로고침 뒤 새 이름이 보이지 않습니다 — 저장이 반영되지 않았습니다. '
            f'(찾던 이름: {RENAMED!r})')

        # 모달을 다시 열었을 때 그 값이 실려 있어야 한다. 카드 제목만 갱신되고
        # 폼은 옛 값을 싣는 경우가 실제로 있었다.
        _open_settings(page, RENAMED)
        value = page.locator('.aot-option-modal.show input[name="name"]').first.input_value()
        assert value == RENAMED, (
            f'모달이 옛 값을 싣습니다: {value!r} (화면에는 {RENAMED!r})')
        page.keyboard.press('Escape')
        page.wait_for_timeout(500)
    finally:
        # 되돌리기 — 실패했더라도 이름이 바뀐 채로 남으면 안 된다.
        try:
            if _card(page, RENAMED).count() > 0:
                _rename(page, base_url, RENAMED, F.OUTPUT_NOCHANNEL)
        except Exception:                    # noqa: BLE001
            pass
