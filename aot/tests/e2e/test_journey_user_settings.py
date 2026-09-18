# coding=utf-8
"""L2 · J13·J20 — 사용자 설정(언어·화면 배율)이 실제로 화면을 바꾸는가.

둘 다 같은 자리에서 정한다(상단 "사용자 설정" → `#modal_config_theme`).
그리고 둘 다 **저장한 뒤 다른 화면에서 확인해야** 의미가 있다 — 모달 안에서는
고른 대로 보이지만, 실제로 적용되는 곳은 전 페이지이기 때문이다.

⚠ 이 검사들은 **계정 설정을 실제로 바꾼다.** 끝에서 반드시 되돌리고, 되돌린
것까지 단언한다. 언어가 바뀐 채로 남으면 뒤따르는 여정들이 버튼 이름을 못
찾아 줄줄이 깨진다.
"""
import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import choose_option

pytestmark = pytest.mark.e2e

ACCOUNT_MODAL = '#modal_config_theme'


def _open_account_settings(page, base_url):
    page.goto(f'{base_url}/live', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)

    # 사람이 지나는 길: 상단 "관리" 메뉴를 열고 "사용자 설정" 을 누른다.
    # 링크가 드롭다운 안에 있어, 열지 않고 누르려 하면 "보이지 않는 요소" 로
    # 영영 기다린다.
    # 메뉴 항목은 **부모 `<li>` 를 누른다.** 토글 링크의 중심점은 그 부모가
    # 덮고 있어서(hit-test 상 `<li class="nav-item dropdown">` 이 잡힌다) 링크를
    # 직접 겨냥하면 "가로채였다" 로 영영 재시도한다. 사람이 "관리" 영역을
    # 누르는 것과 같은 동작이다.
    #
    # 토글은 한 번만 누른다 — 다시 누르면 방금 연 드롭다운이 닫힌다.
    page.locator('li.nav-item.dropdown', has=page.locator('#dropdownManage')
                 ).first.click()
    page.wait_for_selector(f'[data-target="{ACCOUNT_MODAL}"]:visible',
                           timeout=10000)
    page.wait_for_timeout(500)   # 드롭다운 펼침 애니메이션
    page.locator(f'[data-target="{ACCOUNT_MODAL}"]:visible').first.click()
    page.wait_for_selector(f'{ACCOUNT_MODAL}.show', timeout=15000)
    page.wait_for_timeout(600)


def _save_account_settings(page):
    """저장하고, **거부되지 않았는지**까지 본다.

    이 폼은 한 항목이라도 검증에 걸리면 **통째로** 거부하고 원래 화면으로
    되돌린다(HTTP 200). 그래서 상태 코드만 보면 "저장했다" 로 읽힌다 —
    실제로 그랬다: 시드 이메일이 검증을 통과하지 못해 언어도 배율도 하나
    저장되지 않는데 검사는 통과했다(2026-09-18). 오류 안내를 함께 본다.
    """
    with page.expect_response(
            lambda r: r.request.method == 'POST', timeout=30000) as saved:
        page.locator('#user_account_save').first.click()
    assert saved.value.status in (200, 302), (
        f'사용자 설정 저장이 HTTP {saved.value.status} 로 끝났습니다')
    page.wait_for_timeout(2500)

    errors = page.evaluate(
        '() => Array.from(document.querySelectorAll('
        '".toast, #toast-container div, .alert, #aot-flash-fallback div"))'
        '.map(e => (e.innerText || "").trim())'
        '.filter(t => /error|오류|invalid|실패/i.test(t))')
    assert not errors, f'설정 저장이 거부됐습니다: {errors[:2]}'


def _language_option_labels(page):
    return page.eval_on_selector(
        '#language',
        'el => Array.from(el.options).map(o => o.text.trim())')


def test_changing_the_language_changes_the_whole_screen(page, base_url):
    """J13 — 언어를 바꾸면 화면 글자가 그 언어가 되는가.

    모달 안이 아니라 **전 페이지**를 본다. 상단 메뉴는 어느 화면에나 있으므로
    그것이 바뀌었는지로 판정한다.
    """
    _open_account_settings(page, base_url)
    labels = _language_option_labels(page)
    english = next((label for label in labels if 'English' in label), None)
    korean = next((label for label in labels if '한국어' in label), None)
    assert english and korean, f'언어 선택지를 찾지 못했습니다: {labels[:6]}'

    try:
        choose_option(page, 'language', english)
        _save_account_settings(page)

        page.goto(f'{base_url}/live', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        body = page.inner_text('body')
        assert 'Dashboard' in body, (
            f'영어로 바꿨는데 화면이 그대로입니다(본문 앞부분: {body[:120]!r})')
        assert '대시보드' not in body, (
            '영어로 바꿨는데 한국어 메뉴가 남아 있습니다 — 일부만 바뀌었습니다')
    finally:
        # 되돌리기. 실패해도 여기는 반드시 지난다 — 언어가 바뀐 채로 남으면
        # 뒤따르는 여정들이 버튼 이름을 못 찾는다.
        _open_account_settings(page, base_url)
        choose_option(page, 'language', korean)
        _save_account_settings(page)

    page.goto(f'{base_url}/live', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)
    assert '대시보드' in page.inner_text('body'), (
        '언어를 한국어로 되돌리지 못했습니다 — 다음 검사들이 깨집니다')


def test_the_desktop_zoom_setting_does_not_break_the_layout(page, base_url):
    """J20 — 화면 배율을 바꿔도 주요 화면이 가로로 넘치지 않는가.

    배율은 CSS `zoom` 으로 먹는다. 폭 계산이 그 배율을 못 따라가면 가로
    스크롤이 생기고, 손가락으로 쓰는 화면에서는 그것이 곧 못 쓰는 화면이다.
    """
    checked = ('/live', '/output', '/notes')

    def _overflow(path):
        page.goto(base_url + path, wait_until='domcontentloaded')
        page.wait_for_timeout(2500)
        return page.evaluate(
            '() => document.documentElement.scrollWidth'
            ' - document.documentElement.clientWidth')

    try:
        _open_account_settings(page, base_url)
        labels = page.eval_on_selector(
            '#ui_zoom_desktop',
            'el => Array.from(el.options).map(o => o.text.trim())')
        bigger = next((l for l in labels if l.startswith('110')), None)
        if not bigger:
            pytest.skip(f'110% 선택지가 없습니다: {labels[:6]}')
        choose_option(page, 'ui_zoom_desktop', bigger)
        _save_account_settings(page)

        # 되읽기 — 저장이 반영되지 않았으면 아래 넘침 검사는 **기본 배율을**
        # 재는 빈 검사가 된다. 실제로 그렇게 통과한 적이 있다.
        _open_account_settings(page, base_url)
        saved_label = page.eval_on_selector(
            '#ui_zoom_desktop',
            'el => el.options[el.selectedIndex].text.trim()')
        assert saved_label == bigger, (
            f'배율이 저장되지 않았습니다: 고른 값 {bigger!r}, 다시 연 값 '
            f'{saved_label!r}')
        page.keyboard.press('Escape')
        page.wait_for_timeout(600)

        for path in checked:
            overflow = _overflow(path)
            assert overflow <= 1, (
                f'{path}: 배율 {bigger} 에서 가로로 {overflow}px 넘칩니다')
    finally:
        _open_account_settings(page, base_url)
        default = next((l for l in page.eval_on_selector(
            '#ui_zoom_desktop',
            'el => Array.from(el.options).map(o => o.text.trim())')
            if '기본값' in l or 'Default' in l), None)
        if default:
            choose_option(page, 'ui_zoom_desktop', default)
            _save_account_settings(page)
